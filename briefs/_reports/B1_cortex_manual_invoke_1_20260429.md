# SHIP REPORT — B1 / CORTEX_MANUAL_INVOKE_1

**Date:** 2026-04-29
**Builder:** B1 (`~/bm-b1`)
**Brief:** `briefs/BRIEF_CORTEX_MANUAL_INVOKE_1.md`
**Wave:** 1 / Track 1 (V3 rev 4 roadmap)
**Trigger class:** HIGH (external API + auth + cost-bearing)
**Branch:** `b1/cortex-manual-invoke-1`
**Reviewers:** AI Head A (`/security-review` + structural) + AI Head B (cross-lane)

---

## What shipped

A new streaming endpoint `POST /api/cortex/run` lets the Director invoke
a Cortex cycle from anywhere (curl, dashboard button, future iOS app)
with live SSE phase-by-phase visibility. A new `cortex_run_action`
intent in the Scan classifier routes "run cortex on hagenauer-rg7" into
the same streaming path. Both surfaces share the same backend helpers.

**Hard guardrails:**
1. **Auth** — `X-Baker-Key` header (existing `verify_api_key` dependency).
2. **Whitelist** — only matters with `cortex-config.md` accepted (reuses
   `matter_has_cortex_config` from PR #85).
3. **Rate limit** — 5 manual runs/hour/matter across `(director_manual,
   scan_intent)` → HTTP 429 over.
4. **Cost guardrail** — ≥30 specialist invocations/24h/matter triggers a
   Slack DM warning to the Director (observability only — does NOT block).
5. **Disconnect-resilient** — closing the SSE consumer does NOT cancel
   the cycle; it runs to completion in the background.

### Files shipped

| File | Status | LOC | Purpose |
|---|---|---|---|
| `outputs/cortex_run_stream.py` | NEW | 263 | Pure helpers — SSE format, runs/hour count, specialist/24h count, cycle snapshot, async event generator |
| `outputs/dashboard.py` | MOD | +133 | `CortexRunRequest` model, `POST /api/cortex/run`, Scan branch for `cortex_run_action` |
| `orchestrator/action_handler.py` | MOD | +57 | `_quick_cortex_run_detect` regex fast-path, `cortex_run_action` in `_INTENT_SYSTEM` JSON schema |
| `tests/test_cortex_run_stream.py` | NEW | 254 | 11 tests — helpers, snapshot, full SSE sequence, error/timeout terminal states |
| `tests/test_cortex_run_endpoint.py` | NEW | 188 | 6 tests — auth, validation, whitelist, rate limit, cost-warn, happy-path SSE |
| `tests/test_scan_cortex_intent.py` | NEW | 96 | 7 tests — regex fast-path, classify_intent short-circuit |

**Total:** 3 NEW production-side files (1 prod + 3 test = 4) + 2 modified.

---

## §0 — Literal pytest stdout (per Lesson #48 — no ship-by-inspection)

### Combined new-suite — required all green

```
$ .venv-b1/bin/pytest tests/test_cortex_run_stream.py tests/test_cortex_run_endpoint.py tests/test_scan_cortex_intent.py -v
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

======================== 24 passed, 5 warnings in 1.23s ========================
```

✅ **24/24 PASS** — full coverage of streaming, rate-limit, cost-warn,
auth, whitelist, intent classifier.

### Cortex regression — adjacent suites still green

```
$ .venv-b1/bin/pytest \
    tests/test_cortex_run_stream.py tests/test_cortex_run_endpoint.py \
    tests/test_scan_cortex_intent.py tests/test_cortex_pre_review_gate.py \
    tests/test_cortex_trigger_endpoint.py tests/test_alerts_to_signal_cortex_dispatch.py \
    tests/test_pipeline_tick.py tests/test_cortex_slack_interactivity.py \
    tests/test_cortex_runner_phase126.py tests/test_cortex_action_endpoint.py -v
======================= 143 passed, 6 warnings in 1.33s ========================
```

✅ **143/143 PASS** across 10 cortex/pipeline/scan suites. Existing
`/api/cortex/trigger` (sync) endpoint still green; gate / phase /
dispatch surfaces unchanged.

### Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### py_compile

```
$ python3.12 -c "import py_compile; \
    py_compile.compile('outputs/cortex_run_stream.py', doraise=True); \
    py_compile.compile('outputs/dashboard.py', doraise=True); \
    py_compile.compile('orchestrator/action_handler.py', doraise=True); \
    print('OK all 3 files')"
OK all 3 files
```

(Pre-existing `SyntaxWarning` at `outputs/dashboard.py:2551` — `'\['` in a
raw SQL regex string. Not introduced by this PR; flagged in PR #84 ship
report §6.)

---

## §1 — Manual SSE smoke (post-deploy curl)

After Render redeploys, the Director can run:

```bash
BAKER_KEY="<from-render>"

curl -N -X POST "https://baker-master.onrender.com/api/cortex/run" \
  -H "Content-Type: application/json" \
  -H "X-Baker-Key: $BAKER_KEY" \
  -d '{
    "matter_slug": "oskolkov",
    "director_question": "Smoke — confirm SSE stream emits phase events.",
    "triggered_by": "post_deploy_smoke"
  }'
```

**Expected event sequence** (from `stream_cycle_events`):

```
data: {"type":"started","matter_slug":"oskolkov","triggered_by":"post_deploy_smoke","ts":...}

data: {"type":"phase_changed","phase":"sense","cycle_id":"<uuid>","ts":...}

data: {"type":"phase_output","count":1,"cycle_id":"<uuid>","ts":...}

data: {"type":"phase_changed","phase":"load","cycle_id":"<uuid>","ts":...}

data: {"type":"phase_changed","phase":"reason","cycle_id":"<uuid>","ts":...}

data: {"type":"phase_output","count":2,"cycle_id":"<uuid>","ts":...}
... (specialist invocations during Phase 3b emit phase_output bumps) ...

data: {"type":"phase_changed","phase":"propose","cycle_id":"<uuid>","ts":...}
data: {"type":"phase_changed","phase":"archive","cycle_id":"<uuid>","ts":...}

data: {"type":"terminal","status":"proposed","cycle_id":"<uuid>","current_phase":"archive","cost_dollars":<float>,"cost_tokens":<int>,"aborted_reason":null,"ts":...}
```

For a config-less matter (e.g. `kitzbuhel-six-senses`) the request is
rejected with HTTP 400 BEFORE any cycle starts — saves the cost gate
trip too.

For Scan: ask Baker "run cortex on oskolkov — quick smoke" → Scan
classifier hits the fast-path regex → routes to the same
`stream_cycle_events` generator with `triggered_by="scan_intent"`.

---

## §2 — Rate-limit behavior (cap = 5)

Per `RUN_RATE_LIMIT_PER_HOUR` (env: `CORTEX_RUN_RATE_LIMIT`, default `5`):

- Calls 1-5 within the same rolling hour: each fires a cycle.
- Call 6: HTTP 429 with body `{"detail":"Rate limit: 5 runs in last hour for <matter> (cap=5)"}`.
- Counter source: `cortex_cycles WHERE triggered_by IN
  ('director_manual','scan_intent') AND started_at > NOW() - 1 hour`.
- **Test**: `test_run_endpoint_rate_limited_at_cap` mocks
  `runs_in_last_hour` → 5 → asserts 429 + cap=5 in body.

**Manual repro** (post-deploy): fire 6 sequential `/api/cortex/run`
calls within an hour for the same matter → 6th returns 429.

---

## §3 — Cost-warn behavior (warn-only, NOT a cap)

Per `COST_WARN_SPECIALIST_PER_DAY` (env:
`CORTEX_COST_WARN_SPECIALIST_PER_DAY`, default `30`):

- Counter source: `cortex_phase_outputs WHERE artifact_type =
  'specialist_invocation' AND created_at > NOW() - 24 hour` joined to
  `cortex_cycles` filtered by matter_slug.
- At ≥30 invocations: Slack DM posts to `DIRECTOR_DM_CHANNEL`
  (`D0AFY28N030`, the canonical Director DM channel from
  `triggers/audit_sentinel.py:19`):

  > ⚠️ Cortex spend watch: <matter> has <N> specialist invocations in
  > last 24h (warn threshold: 30). Run proceeding — observability ping
  > only.

- Run **proceeds** regardless. This is observability, not a hard cap
  (per brief Key Constraint #4: "DO NOT make rate-limit a hard CAP on
  cost-warn — warn-only per Director's intent").
- **Test**: `test_run_endpoint_cost_warn_posts_slack_and_runs` asserts
  HTTP 200 + `mock_post.call_count == 1` + SSE stream still flows.

**Slack target:** `DIRECTOR_DM_CHANNEL = "D0AFY28N030"` —
imported from `triggers/cortex_pre_review_gate` (canonical source).

---

## §4 — Schema clarification (deviates from brief; documented per Lesson #40)

The brief named `capability_runs` as the source for
`specialist_calls_today`. **That schema does not match production**:

```python
# memory/store_back.py:3108 (verified 2026-04-29):
CREATE TABLE IF NOT EXISTS capability_runs (
    id SERIAL PRIMARY KEY,
    baker_task_id INTEGER,
    capability_slug TEXT NOT NULL,
    sub_task TEXT,
    answer TEXT,
    ...
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
)
```

`capability_runs` has **no `matter_slug` column** and **no
`started_at`** (it has `created_at`). The actual specialist invocations
land in `cortex_phase_outputs` with `artifact_type='specialist_invocation'`
(verified at `orchestrator/cortex_phase3_invoker.py:251-258`).

Implementation uses the correct table:

```python
SELECT COUNT(*) FROM cortex_phase_outputs cpo
JOIN cortex_cycles cc ON cc.cycle_id = cpo.cycle_id
WHERE cc.matter_slug = %s
  AND cpo.artifact_type = 'specialist_invocation'
  AND cpo.created_at > NOW() - INTERVAL '24 hour'
```

Cousin of Lesson #40 (verify schema before referencing). Documented in
`outputs/cortex_run_stream.py` module docstring lines 23-32.

---

## §5 — Lane discipline (per brief §"Do NOT Touch")

| Item | Status |
|---|---|
| `orchestrator/cortex_runner.py` (signature, timeouts, error semantics) | ✅ UNTOUCHED |
| `triggers/cortex_pipeline.py` | ✅ UNTOUCHED (Track 2 lane — but read for design) |
| `triggers/cortex_pre_review_gate.py` (PR #85 lane) | ✅ UNTOUCHED (only imported) |
| Existing `POST /api/cortex/trigger` (sync) | ✅ INTACT (still passes its 4 tests) |
| Frontend / static assets | ✅ no UI work |
| `baker-vault/slugs.yml` | ✅ separate repo |
| `tasks/lessons.md` existing entries | ✅ append-only respected |
| New env vars | ✅ ONLY the 3 in brief: `CORTEX_RUN_POLL_INTERVAL`, `CORTEX_RUN_RATE_LIMIT`, `CORTEX_COST_WARN_SPECIALIST_PER_DAY` |

`director_question` audit:

```
$ grep -n "director_question" outputs/cortex_run_stream.py outputs/dashboard.py orchestrator/action_handler.py | grep -i "logger.*\.\(info\|warn\)"
(no matches)
```

✅ `director_question` is **never** info-logged. Only docstrings and
error-context strings reference the variable name. The two grep hits
are documentation comments, not log statements.

---

## §6 — Side findings (non-blocking)

### Pre-existing test pollution: `test_cortex_action_endpoint.py:62`

`tests/test_cortex_action_endpoint.py:62` does:

```python
app.dependency_overrides[verify_api_key] = lambda: None
```

…and **never cleans up**. This pollutes the global FastAPI app instance:
any subsequent test that runs against the same `app` and expects auth
enforcement fails (`verify_api_key` is bypassed).

**Pre-existing repro** (verified on truly clean main, all my files
stashed `-u`):

```
$ git stash -u
$ .venv-b1/bin/pytest tests/ -k "cortex" -q
FAILED tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_unauthorized
1 failed, 230 passed
$ git stash pop
```

**Mitigation in this PR:** my `_set_api_key()` test helper defensively
clears the dependency override at the start of every test — see
`tests/test_cortex_run_endpoint.py:23-30`. Without this, my own
`test_run_endpoint_unauthorized` would also fail when run after
`test_cortex_action_endpoint`. The trigger-test fix is out of scope for
this PR (do not touch `tests/test_cortex_trigger_endpoint.py` per
surgical-edits rule), but a follow-up brief should add a similar
defensive cleanup or convert `test_cortex_action_endpoint.py` to use a
proper teardown fixture.

### Pre-existing `tests/test_scan_endpoint.py` + `tests/test_scan_prompt.py` failures

3 tests in `test_scan_endpoint.py` (`test_scan_returns_sse_stream`,
`test_scan_rejects_empty_question`, `test_scan_accepts_history`) and 1
in `test_scan_prompt.py` (`test_prompt_is_conversational_no_json_requirement`)
fail on clean main. Unrelated to this PR (verified by running on a
fully-stashed main). Surfaced for tracker.

---

## §7 — Sanity walk: cortex_run_action intent fast-path

Test `test_classify_intent_fast_path_skips_llm` proves the regex
fast-path short-circuits before the Haiku/Gemini classifier:

```python
def test_classify_intent_fast_path_skips_llm():
    with patch("orchestrator.gemini_client.call_flash") as mock_llm:
        out = classify_intent("Run cortex on oskolkov — quick smoke")
    assert out["type"] == "cortex_run_action"
    assert out["matter_slug"] == "oskolkov"
    mock_llm.assert_not_called()  # ✅ regex matched before LLM call
```

Match patterns covered:
- `run cortex on <slug>`
- `fire cortex for <slug>`
- `trigger cortex on <slug>`
- `cortex review on <slug>` / `cortex review for <slug>`

`<slug>` is `[a-z0-9][a-z0-9-]*` — supports hyphenated canonical slugs
(`hagenauer-rg7`, `nvidia-corinthia`). No-match cases (e.g. "what's the
cortex roadmap status?") return None and fall through to the LLM
classifier.

The Haiku/Gemini system prompt was also extended with the
`cortex_run_action` type + `matter_slug` + `question` fields + 4
example patterns + canonical-slug constraint, so non-regex phrasings
still route correctly.

---

## §8 — Disconnect-doesn't-kill-cycle (design verification)

**Design:** `stream_cycle_events` uses `asyncio.create_task(maybe_run_cycle(...))`
to spawn the cycle, then polls `_snapshot_cycle` while awaiting
the task. The cycle Task is rooted on the event loop, **not on the
client request scope**. If the consumer disconnects, FastAPI closes the
SSE generator (raising `CancelledError` into `asyncio.sleep`) but the
cycle Task continues — Python event-loop semantics keep it alive until
`maybe_run_cycle`'s own `asyncio.wait_for(timeout=CYCLE_TIMEOUT_SECONDS)`
either resolves the cycle or marks it `failed` on timeout. The cycle's
own DB persistence (Phase 1 `INSERT INTO cortex_cycles`, Phase 2
`UPDATE last_loaded_at`, etc.) commits regardless of stream state.

**Test coverage:** `test_stream_cycle_events_emits_full_sequence`,
`test_stream_cycle_events_terminal_failed_on_exception`,
`test_stream_cycle_events_terminal_timeout` — all assert correct
terminal events under varied cycle outcomes. Disconnect path is
implicit (the generator just stops being consumed).

**Operational confirmation in post-deploy:** kill the curl mid-stream;
verify via SQL:

```sql
SELECT cycle_id, status, current_phase, cost_dollars, started_at, completed_at
FROM cortex_cycles
WHERE triggered_by = 'post_deploy_smoke'
ORDER BY started_at DESC LIMIT 1;
```

Expect `status='proposed'` (or `failed`/`timeout` if real upstream
issue) — NOT `in_flight` left forever.

---

## §9 — Review path

Tier A — HIGH (external API + auth + cost-bearing). Per RA-24:

1. **AI Head A** — `/security-review` + structural review (auth surface,
   SSE injection vectors, rate-limit enforcement, cost-warn boundary).
2. **AI Head B** — cross-lane review (intent classifier impact on
   non-cortex Scan flows, regression vs `clickup_plan` ordering,
   pollution-defense pattern in `_set_api_key`).
3. Dual-clear → auto-merge per `_ops/processes/b-code-dispatch-coordination.md`.

Builder ↔ Reviewer concentration: B1 builds + B1 formally reviewed PR
#85 yesterday — that workload split is acceptable per AI Head A
dispatch ("If AI Head A judges B1-builder ↔ B1-review concentration
unacceptable, reassign builder to B2 and B1 reviews"). For THIS PR, B1
is builder; reviewer is AI Head A + AI Head B (no review by B1).

---

## §10 — Post-deploy verification (AI Head)

```bash
# 1. SSE live stream smoke (config-rich matter — should work)
BAKER_KEY="<from-render>"
curl -N -X POST "https://baker-master.onrender.com/api/cortex/run" \
  -H "Content-Type: application/json" \
  -H "X-Baker-Key: $BAKER_KEY" \
  -d '{"matter_slug":"oskolkov","director_question":"Post-deploy smoke — confirm SSE stream emits phase events.","triggered_by":"post_deploy_smoke"}'
# Expected: stream of started → phase_changed → phase_output → terminal

# 2. Whitelist rejection (config-less matter — should 400)
curl -X POST "https://baker-master.onrender.com/api/cortex/run" \
  -H "Content-Type: application/json" \
  -H "X-Baker-Key: $BAKER_KEY" \
  -d '{"matter_slug":"kitzbuhel-six-senses","director_question":"Should be rejected.","triggered_by":"post_deploy_smoke"}'
# Expected: HTTP 400 + "not Cortex-enabled" in detail
```

```sql
-- 3. Confirm a manual cycle row landed
SELECT cycle_id, matter_slug, triggered_by, status, current_phase,
       cost_dollars, started_at, completed_at
FROM cortex_cycles
WHERE triggered_by IN ('director_manual','scan_intent','post_deploy_smoke')
ORDER BY started_at DESC LIMIT 5;

-- 4. Confirm cost-warn counter SQL is sane (manually run before threshold trip)
SELECT COUNT(*) FROM cortex_phase_outputs cpo
JOIN cortex_cycles cc ON cc.cycle_id = cpo.cycle_id
WHERE cc.matter_slug = 'oskolkov'
  AND cpo.artifact_type = 'specialist_invocation'
  AND cpo.created_at > NOW() - INTERVAL '24 hour';
```

---

## §11 — Mailbox status

`briefs/_tasks/CODE_1_PENDING.md` will be flipped to `PR-OPEN` on PR
push (next step in this report's commit), then to `COMPLETE` on merge.

---

Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

---

## §F1-FIX — AI Head B re-review delta (concurrent-tap race)

**Trigger:** AI Head B `REQUEST_CHANGES` on `briefs/_reports/AIHEAD_B_PR88_review_20260429.md` §1, F-1 (HIGH).

**Bug recap:** `_snapshot_cycle` did `ORDER BY started_at DESC LIMIT 1`. When
two Director taps overlapped (same `matter_slug`, both
`triggered_by='director_manual'`, inside the 5/hour rate-limit window), each
polling stream cross-talked: stream-1 saw stream-2's `cycle_id` mid-stream.
End-state DB rows stayed correct; only intermediate `phase_changed` /
`phase_output` events were corrupt — sharp UX edge, not a data-integrity
defect.

### Diff summary

| File | Change | LOC |
|---|---|---|
| `outputs/cortex_run_stream.py` | New module constant `SSE_ANCHOR_SLACK_SECONDS = 2.0` (no env var per brief Constraint #6); `_snapshot_cycle` accepts `since_ts` kwarg → `AND started_at >= %s ORDER BY started_at ASC LIMIT 1`; backward-compat `since_ts=None` branch preserves `DESC LIMIT 1`; `stream_cycle_events` captures `sse_anchor = now(utc) - SSE_ANCHOR_SLACK_SECONDS` BEFORE `asyncio.create_task` and threads it through every poll | +30 / -5 |
| `tests/test_cortex_run_stream.py` | NEW `test_snapshot_cycle_disambiguates_concurrent_taps` (unit; 3 assertions: anchor-before-both → cycle_a, anchor-between → cycle_b, `since_ts=None` → backward-compat returns latest); NEW `test_stream_cycle_events_concurrent_isolation` (async; two `stream_cycle_events` consumers run concurrently with overlapping anchors, monkeypatched slack to 0.01s; asserts each phase_changed event-set contains ONLY its own cycle_id) | +175 |

`maybe_run_cycle` signature: **UNCHANGED** (brief constraint preserved).
`runs_in_last_hour` / `specialist_calls_today`: **UNCHANGED** (count by matter
+ window, not cycle identity — F-1 is purely a snapshot-disambiguation issue).

### §F1.0 — Literal pytest stdout (per Lesson #48)

```
$ .venv-b1/bin/pytest tests/test_cortex_run_stream.py -v --no-header
============================= test session starts ==============================
collected 13 items

tests/test_cortex_run_stream.py::test_sse_format_single_data_block PASSED [  7%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_returns_count PASSED [ 15%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_db_unavailable_returns_zero PASSED [ 23%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_returns_count PASSED [ 30%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_db_unavailable_returns_zero PASSED [ 38%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_dict PASSED [ 46%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_no_cycle PASSED [ 53%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_db_unavailable PASSED [ 61%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_emits_full_sequence PASSED [ 69%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_failed_on_exception PASSED [ 76%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_timeout PASSED [ 84%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_disambiguates_concurrent_taps PASSED [ 92%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_concurrent_isolation PASSED [100%]

============================== 13 passed in 0.26s ==============================
```

✅ **13/13 PASS** — 11 prior + 2 new (Test 9 = `disambiguates_concurrent_taps`,
Test 10 = `concurrent_isolation`).

```
$ .venv-b1/bin/pytest tests/test_cortex_run_stream.py tests/test_cortex_run_endpoint.py tests/test_scan_cortex_intent.py -v --no-header
======================== 26 passed, 6 warnings in 2.03s ========================
```

✅ **26/26 PASS** combined (24 from original PR + 2 new F-1 tests).

```
$ python3.12 -c "import py_compile; \
    py_compile.compile('outputs/cortex_run_stream.py', doraise=True); \
    py_compile.compile('outputs/dashboard.py', doraise=True); \
    py_compile.compile('orchestrator/action_handler.py', doraise=True); \
    print('OK all 3 files')"
OK all 3 files

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### §F1.1 — Why `SSE_ANCHOR_SLACK_SECONDS` is a module constant, not an env var

The 2s slack absorbs the `asyncio.create_task` → Phase 1 INSERT gap. Tests
need a smaller value to stage tight concurrency without real-time waits (the
`concurrent_isolation` test uses `0.01s` via `monkeypatch.setattr`). Brief
Constraint #6 prohibits adding a 4th env var beyond the 3 declared
(`CORTEX_RUN_POLL_INTERVAL`, `CORTEX_RUN_RATE_LIMIT`,
`CORTEX_COST_WARN_SPECIALIST_PER_DAY`), so the value is hard-coded with a
module-level binding. Production retains the 2s slack specified in AI Head
B's patch sketch.

### §F1.2 — Concurrency contract bounds (transparent)

The simple anchor approach disambiguates **streams whose start times are
spaced by more than `SSE_ANCHOR_SLACK_SECONDS` (2s in production).** Two
Director taps within 2s of each other on the same matter would still race
— that scenario requires a stronger fix (e.g. pin the observed `cycle_id`
and re-query by primary key). I did **not** ship the stronger fix because:

1. Dispatch directive specified the simple AI Head B sketch verbatim.
2. Two taps within 2s on the same matter is a smoke-test / double-tap edge,
   not the steady-state pattern the rate-limit (5/hour/matter ≈ one every 12
   minutes) is designed for.
3. If AI Head B's re-review concludes the 2s window is too narrow, a
   follow-up brief can swap in cycle_id pinning — the `since_ts` query
   remains as the bootstrap mechanism.

Surfaced for AI Head B's re-review judgment.

### §F1.3 — AI Head B re-review request

**Re-review scope:** delta only — the 30 LOC patch + 175 LOC test additions
listed above. Suggested time per RA-24 dual-clear: ~30 min. F-2 through F-6
from the original review remain documented follow-up briefs and are NOT
addressed in this delta (out of scope per dispatch).

**Verdict needed:** APPROVE on F-1 → AI Head A merges PR #88. RE-REQUEST on
F-1 → I'll iterate (e.g. swap to cycle_id pinning if §F1.2 carve-out is
unacceptable).

Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
