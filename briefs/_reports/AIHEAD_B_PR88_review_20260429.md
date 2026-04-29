# AI Head B — Cross-lane review of PR #88 CORTEX_MANUAL_INVOKE_1

**Reviewer:** AI Head B (`aihead2` — cross-lane lane per RA-24)
**PR:** https://github.com/vallen300-bit/baker-master/pull/88
**Branch:** `b1/cortex-manual-invoke-1` · commit `2bb1efd` (with `94a82ca` as the feature commit)
**Builder:** B1 (`~/bm-b1`)
**RA-24 trigger class:** HIGH (external API + auth + cost-bearing)
**Companion review:** AI Head A — APPROVE (structural + security), see PR comments
**Verdict:** **REQUEST_CHANGES** — one HIGH finding (concurrent-run cycle race in `_snapshot_cycle`); five lower-severity comments.

---

## §0 — Literal stdout (verification per Lesson #48 — no ship-by-inspection)

### Suite under review — must show 24/24 PASS

```
$ ~/bm-b1/.venv-b1/bin/pytest tests/test_cortex_run_stream.py tests/test_cortex_run_endpoint.py tests/test_scan_cortex_intent.py -v
============================= test session starts ==============================
collected 24 items

tests/test_cortex_run_stream.py::test_sse_format_single_data_block PASSED [  4%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_returns_count PASSED [  8%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_db_unavailable_returns_zero PASSED [ 12%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_returns_count PASSED [ 16%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_db_unavailable_returns_zero PASSED [ 20%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_dict PASSED [ 25%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_no_cycle PASSED [ 29%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_db_unavailable PASSED [ 33%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_emits_full_sequence PASSED [ 37%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_failed_on_exception PASSED [ 41%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_timeout PASSED [ 45%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized PASSED [ 50%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_validation_short_question PASSED [ 54%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_no_cortex_config_rejected PASSED [ 58%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_rate_limited_at_cap PASSED [ 62%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_cost_warn_posts_slack_and_runs PASSED [ 66%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_happy_path_streams PASSED [ 70%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_run_on PASSED [ 75%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_fire_for PASSED [ 79%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_review_on PASSED [ 83%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_no_match PASSED [ 87%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_hyphenated_slug PASSED [ 91%]
tests/test_scan_cortex_intent.py::test_classify_intent_fast_path_skips_llm PASSED [ 95%]
tests/test_scan_cortex_intent.py::test_scan_branch_rejects_matter_without_config PASSED [100%]

======================= 24 passed, 5 warnings in 55.80s ========================
```

✅ **24/24 PASS** — B1 claim verified.

### Cortex regression sweep (broader than B1's 10-suite list)

```
$ ~/bm-b1/.venv-b1/bin/pytest tests/ -k "cortex" -v
... [output truncated for brevity]
============== 255 passed, 1237 deselected, 6 warnings in 56.93s ===============
```

✅ **255/255 PASS** under `-k "cortex"` filter. B1's 143/143 claim covers 10 named suites; my broader filter pulls in 112 additional cortex-tagged tests (capability_router, anthropic_helper, signal classifier, etc.) — all green.

### py_compile

```
$ python3 -c "import py_compile; \
    py_compile.compile('outputs/cortex_run_stream.py', doraise=True); \
    py_compile.compile('outputs/dashboard.py', doraise=True); \
    py_compile.compile('orchestrator/action_handler.py', doraise=True); \
    print('OK all 3 files')"
OK all 3 files
```

✅ Pre-existing `SyntaxWarning at outputs/dashboard.py:2551` (escape in raw SQL regex) is unchanged from main; not introduced by this PR.

---

## §1 — HIGH finding (REQUEST_CHANGES)

### F-1: `_snapshot_cycle` returns the wrong cycle on concurrent same-trigger taps

**Location:** `outputs/cortex_run_stream.py:135-184` (`_snapshot_cycle`) called from `stream_cycle_events:232`

**Bug:** `_snapshot_cycle` queries:

```sql
SELECT cycle_id, status, current_phase
FROM cortex_cycles
WHERE matter_slug = %s AND triggered_by = %s
ORDER BY started_at DESC LIMIT 1
```

This returns the **latest** cycle for `(matter_slug, triggered_by)`. The rate limit allows **5 manual runs/hour/matter** under the same `triggered_by='director_manual'` value. When two Director taps overlap (cycles run ~5min, so two taps within 5min of each other on the same matter is plausible during smoke testing or a curl + dashboard click), the polling loop in `stream_cycle_events` cross-talks:

| t | event | C1 stream sees | C2 stream sees |
|---|---|---|---|
| 0s | Tap 1 fires → C1 created (Phase 1 commit) | C1 cycle_id (correct) | n/a |
| 0.5s | Tap 1 polls _snapshot_cycle → returns C1 | C1 phase_changed=load (correct) | n/a |
| 30s | Tap 2 fires → C2 created (rate-limit OK; n=1) | n/a | C2 cycle_id (correct) |
| 30.5s | Both streams poll `_snapshot_cycle` | **C2** (wrong — newer) | C2 (correct) |
| 90s | C2 reaches Phase 3 (DB updates current_phase='reason') | **phase_changed{phase: reason, cycle_id: C2}** ❌ | phase_changed{phase: reason, cycle_id: C2} ✓ |
| 290s | C1 cycle_task awaits → returns C1 cycle object | terminal{cycle_id: **C1**, status: proposed} | n/a |

The Director holding stream-1 sees phase events tagged with C2's cycle_id mid-stream, then the terminal event flips back to C1's cycle_id. Dashboard refresh reveals two cycles, no clear ownership.

**Why the existing tests don't catch it:** `test_stream_cycle_events_emits_full_sequence` mocks `_snapshot_cycle` to return a single hard-coded sequence. No multi-cycle concurrency fixture. The race is only visible against live PG with overlapping invocations.

**Severity:** HIGH for this trigger class. The brief expressly listed concurrent-run disambiguation as the cross-lane focus question (#2). With the rate limit at 5/hr/matter, concurrent overlap is by design, not edge case.

**Mitigating factor:** `cycle_task` resolves to the correct C1 Cycle object eventually, so the *terminal* event has the right `cycle_id`. The corrupt events are intermediate `phase_changed` + `phase_output` only. End-state Postgres rows are correct (each cycle commits its own `cycle_id`-keyed updates). The only damage is UX confusion in the SSE stream.

**Proposed fix (~5 LOC):** capture a wall-clock anchor in `stream_cycle_events` before spawning `cycle_task`, then change `_snapshot_cycle` to filter `started_at >= anchor` and `ORDER BY started_at ASC LIMIT 1`. Each polling stream sees only cycles that started after its own SSE entry, and picks the oldest such cycle — its own.

```python
# In stream_cycle_events, before cycle_task = asyncio.create_task(...):
import datetime
sse_anchor = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=2)  # 2s slack for clock skew

# Pass sse_anchor through to _snapshot_cycle
snap = _snapshot_cycle(
    matter_slug=matter_slug,
    triggered_by=triggered_by,
    since_ts=sse_anchor,
)

# In _snapshot_cycle:
cur.execute(
    "SELECT cycle_id, status, current_phase "
    "FROM cortex_cycles "
    "WHERE matter_slug = %s AND triggered_by = %s "
    "AND started_at >= %s "
    "ORDER BY started_at ASC LIMIT 1",
    (matter_slug, triggered_by, since_ts),
)
```

The 2-second slack on `sse_anchor` absorbs the small interval between `asyncio.create_task` scheduling and Phase 1's `INSERT INTO cortex_cycles` commit. Adjust if Phase 1 latency exceeds 2s in practice (unlikely — Phase 1 is local-only logic + one INSERT).

**Test addition (~25 LOC):** new test `test_snapshot_cycle_disambiguates_concurrent_taps` (live-PG marker, auto-skip when `TEST_DATABASE_URL` unset). Insert two `cortex_cycles` rows with same `(matter_slug, triggered_by)` but different `started_at`; assert `_snapshot_cycle(since_ts=t1)` returns the cycle started at `t1` and `_snapshot_cycle(since_ts=t2)` returns the one at `t2`.

**Why REQUEST_CHANGES vs accept-with-followup:** the bug surfaces in the exact concurrency mode the rate-limit explicitly enables. Smoke-testing the new endpoint by firing two curls back-to-back will reproduce it; Director will hit it in the first hour of using the surface. Fix is small and self-contained — well under the brief's hard-scope cap.

---

## §2 — Comments (non-blocking)

### F-2 (MEDIUM): Scan UI does not render cortex_run_action SSE events

**Location:** `outputs/static/app.js:3550-3590` (and equivalent in `mobile.js:616`)

The Scan SSE consumer parses each `data: {...}` line and only renders payloads carrying a `data.token` field — phase-typed events (`type: started|phase_changed|phase_output|terminal`) are silently swallowed because they don't carry `token`.

The new `cortex_run_action` route in `/api/scan` returns a `StreamingResponse` of `_sse({...})` events with shape `{type: "started"|"phase_changed"|"phase_output"|"terminal", ...}`. None of these carry a `token` field — the existing JS skips them.

**User-visible effect:** Director asks Baker "run cortex on hagenauer-rg7" in Scan. Backend pipes correctly (B1's `test_scan_branch_rejects_matter_without_config` proves the routing), Cortex cycle runs to completion, but the Scan card shows a thinking indicator indefinitely until the stream terminates with no rendered output.

**Backend correctness:** unaffected. Cycle row commits, specialist outputs persist, archive happens, terminal event fires. Only the frontend rendering is silent.

**Recommendation:** ship as-is, follow-up brief `CORTEX_RUN_SCAN_UI_RENDER_1` adds the front-end handler. Two viable shapes:
- (a) Add a `cortex_run_action` branch to the Scan SSE consumer that maps `phase_changed` → render-line, `terminal` → final summary line.
- (b) Backend emits `data.token` events alongside the typed events so the existing token-renderer surfaces a humanized phase narrative without front-end change.

This is a brief-quality-checkpoint #8 gap (`Scan smoke: ask Baker 'run cortex on oskolkov — quick smoke' → SSE proxied through Scan UI`). The post-deploy smoke will confirm.

### F-3 (LOW): Phase 'act' never written to DB; SSE never sees 'act'

`cortex_runner.py` flow runs sense → load → reason → propose, then either Phase 4 commits `current_phase='propose'` (and cycle becomes `tier_b_pending` awaiting Director button) or Phase 6 commits `current_phase='archive'`. The `act` value in the CHECK constraint at `memory/store_back.py:585` is never written by any `UPDATE cortex_cycles` statement (verified via `grep -rn "current_phase='act'" orchestrator/ triggers/`).

The Phase 5 Director-button handler (`cortex_phase5_act.py:648/676`) writes `current_phase='archive'` directly, skipping the named 'act' state. SSE polling correctly never emits `phase_changed{phase: 'act'}` because the DB never holds that value.

**Non-issue for this PR.** Worth a doc comment in `_snapshot_cycle` that 'act' is a CHECK-allowed but unused phase value, so future maintainers don't add SSE rendering for an event that never fires.

### F-4 (LOW/INFO): `specialist_calls_today` counts ALL trigger sources — intentional

The query at `cortex_run_stream.py:113-119` JOINs `cortex_phase_outputs` to `cortex_cycles` filtered by `matter_slug` only — **no `triggered_by` filter**. So signal-driven (auto-trigger) cycles, manual cycles, and scan-intent cycles all contribute to the counter.

**Behavior verification:** if AO matter accumulates 25 specialist invocations from auto-triggers in 24h, then Director's manual tap with 4 specialists pushes the count to 29 (no warn). At 30+, the next manual tap warns. **This is correct cost-watch semantics** — Director cares about total matter spend over the rolling day, not per-trigger-source spend. The "false-positive on busy auto-trigger" framing in the brief's focus area is actually correct behavior: if auto-triggers ate the budget, the Director SHOULD be warned that adding manual spend pushes the matter further over.

**Recommendation:** add a 1-line code comment to `specialist_calls_today` documenting the intentional all-sources scope, so a future maintainer doesn't "fix" it to filter by `triggered_by`.

```python
# Intentional: counts ALL specialist invocations (signal-driven + manual + scan-intent)
# because cost-warn is total-matter-spend visibility, not per-trigger-source spend.
```

### F-5 (LOW): Index plan for rate-limit + snapshot queries

Existing index (`memory/store_back.py:597`):

```sql
CREATE INDEX idx_cortex_cycles_matter_status ON cortex_cycles (matter_slug, status, started_at DESC)
```

This indexes `(matter_slug, status, started_at DESC)`. The new queries filter on `triggered_by`, not `status`:

```sql
-- runs_in_last_hour:
WHERE matter_slug = %s AND triggered_by = ANY(%s) AND started_at > NOW() - INTERVAL '1 hour'

-- _snapshot_cycle:
WHERE matter_slug = %s AND triggered_by = %s ORDER BY started_at DESC LIMIT 1
```

Postgres can use the existing index for `matter_slug` prefix + `started_at` range, then filter `triggered_by` from the row. At low cycle volume per matter (today: <100/matter), this is a non-issue. At ~10K cycles/matter (≈ year 1-2 at 5 cycles/hour × 24h × 365d × ramp-up = 43K/year/matter under steady use), the index-scan-then-filter degrades.

**Recommendation:** add follow-up migration `idx_cortex_cycles_matter_triggered_started` on `(matter_slug, triggered_by, started_at DESC)` when any matter passes 10K cycles. AI Head A's review already parked this; I'm reinforcing the watermark rather than blocking.

`EXPLAIN` confirmation at current scale (small) was not run — Cortex matters today have <100 cycles each. Worth re-running `EXPLAIN (ANALYZE)` against the rate-limit query at the 1k / 10k / 100k matter-cycle marks.

### F-6 (LOW): `CORTEX_RUN_POLL_INTERVAL=0.5s` is aggressive

At a 5-min cycle cap, the polling loop runs ~600 iterations × 2 SQL queries = **1200 queries per cycle**. With N concurrent SSE consumers (e.g. dashboard + curl + mobile = 3), that's 3600 queries per 5-min window from polling alone — plus the cycle's own DB writes (Phase 3b specialist invocations × 4-5 specialists, Phase 4 proposal commit, etc.).

**Risk at scale:** at 5 cycles/hour × 1200 queries = 6000 polling queries/hour/matter. Across 22 active matters: 132K polling queries/hour worst case. Neon Pro handles this fine today, but the load grows with matter count — and 0.5s is more granular than the human eye notices in a Cortex phase narrative (phases last 10-60s each).

**Secondary concern — phase coalescing:** if a phase transition fires faster than 0.5s (e.g. Phase 1 sense → Phase 2 load takes <500ms), the polling loop misses the intermediate snapshot and emits no `phase_changed{phase: 'load'}`. Stream skips directly from 'sense' to 'reason'. UX gap, not correctness gap.

**Recommendation:**
- Default `CORTEX_RUN_POLL_INTERVAL=2.0` (4× less load, still feels live to a human reading phase progress).
- Long-term: replace polling with PG `LISTEN/NOTIFY` on `cortex_cycles` row updates (single connection, push-driven, eliminates the polling loop entirely). Out of scope for this PR; worth a tracker entry.

---

## §3 — Cross-lane focus areas — answered against B1's implementation

| # | Focus question | Verdict |
|---|---|---|
| 1 | End-to-end SSE phase coverage vs cortex_runner emission points | **PASS** — all 5 active phases (sense, load, reason, propose, archive) commit `current_phase` to DB; SSE polling sees them. 'act' phase is CHECK-allowed but unused (F-3). 'reason' is committed by `cortex_phase3_reasoner.py:324` + `cortex_phase3_synthesizer.py:279`; verified emission. |
| 2 | Concurrent-run cycle_id disambiguation | **FAIL — F-1, REQUEST_CHANGES.** ORDER BY DESC LIMIT 1 returns wrong cycle on overlapping same-trigger streams. |
| 3 | Scan SSE rendering through dashboard JS | **GAP — F-2.** Backend pipes correctly; frontend Scan SSE consumer only renders `data.token` payloads. Follow-up brief required. |
| 4 | specialist_calls_today cross-talk between manual + auto | **CORRECT BEHAVIOR — F-4.** Counts all sources by design; this is total-matter-spend visibility. Add code comment. |
| 5 | Rate-limit query EXPLAIN against cortex_cycles | **OK FOR NOW — F-5.** Existing index covers `matter_slug` prefix; degrades at 10K+ cycles/matter. Follow-up migration. |
| 6 | POLL_INTERVAL=0.5s load profile | **TUNABLE — F-6.** 1200 queries/cycle is aggressive; recommend 2.0s default + LISTEN/NOTIFY long-term. |

---

## §4 — RA-24 dual-clear status

- **AI Head A (#1):** APPROVE (structural + security) — review on PR comments.
- **AI Head B (#2, this report):** **REQUEST_CHANGES** on F-1 (concurrent-run cycle race in `_snapshot_cycle`).

Per `_ops/processes/b-code-dispatch-coordination.md` RA-24 dual-clear, the merge is blocked until F-1 is resolved.

**Suggested next step:** AI Head A drafts a follow-up dispatch for B1 to apply the ~5 LOC `_snapshot_cycle` fix + ~25 LOC live-PG concurrency test. After commit + ship-report, AI Head B re-reviews delta only (turnaround ~30 min). Findings F-2 through F-6 ship as follow-up briefs post-merge.

If Director time-pressure dominates correctness on F-1: AI Head A may downgrade my REQUEST_CHANGES to ACCEPTED-WITH-FOLLOWUP and merge, with F-1 promoted to a P1 follow-up brief. The race is intermediate-event UX corruption, not data-corruption — terminal events and DB rows remain correct, so it's a "sharp UX edge" not a "broken contract".

---

## §5 — Side notes (non-finding observations)

- **B1 schema-deviation handling (Lesson #40 cousin):** brief named `capability_runs` for the cost-warn counter; B1 correctly identified the schema doesn't match (no `matter_slug` column) and routed to `cortex_phase_outputs` JOIN instead. Documented in module docstring lines 15-23. AI Head A's review accepted; I confirm the source-of-truth: `orchestrator/cortex_phase3_invoker.py:251-258` writes `artifact_type='specialist_invocation'` rows to `cortex_phase_outputs`. The deviation is correct.

- **Disconnect-doesn't-kill-cycle:** verified by inspection. `cycle_task = asyncio.create_task(...)` roots the task on the event loop; `CancelledError` in `asyncio.sleep` is re-raised but the cycle Task is not cancelled. Phase 1 INSERT, Phase 2 UPDATE, Phase 3 specialist outputs, Phase 4 proposal card all commit independent of consumer presence.

- **`director_question` audit:** clean. `grep -nE "director_question" outputs/cortex_run_stream.py outputs/dashboard.py orchestrator/action_handler.py | grep -i "logger.*\.\(info\|warning\)"` returns empty. Only error-level logs reference the variable, and only by name (never as substring). ✅

- **Pre-existing test pollution at `test_cortex_action_endpoint.py:62`:** B1's `_set_api_key()` defensive cleanup in `test_cortex_run_endpoint.py:23-30` is a sound mitigation. Out-of-scope fix (pollution-source teardown) parked correctly.

- **CHANDA #4 hook + commit-msg mechanics:** my own bound-for-vault commits today hit the `gold.md` author-director-guard collision; B1's PR is on baker-master not baker-vault, so that hook isn't in play here. No correlation.

---

Co-authored-by: AI Head B <aihead-b@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
