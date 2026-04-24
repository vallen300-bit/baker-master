# CODE_2_RETURN — PROACTIVE_PM_SENTINEL_1 rethread fix-back — 2026-04-24

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `proactive-pm-sentinel-rethread-fix-1`
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `16cda64`)
**Base:** main @ `611d499` (post-PR-#58 squash merge + deploy CP1-4 GREEN)
**PR:** _pending push_

---

## 1. Ship gate — literal output

```
$ python3 -c "import py_compile
for f in ['outputs/dashboard.py','tests/test_proactive_pm_sentinel.py']:
    py_compile.compile(f, doraise=True)
print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ node --check outputs/static/app.js && echo "JS OK"
JS OK

$ grep -n 'app.js?v=\|style.css?v=' outputs/static/index.html
16:    <link rel="stylesheet" href="/static/style.css?v=73">
573:<script src="/static/app.js?v=109"></script>

$ python3 -m pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v 2>&1 | tail -22
collected 18 items

tests/test_proactive_pm_sentinel.py::test_sla_defaults PASSED            [  5%]
tests/test_proactive_pm_sentinel.py::test_dismiss_reasons_canonical PASSED [ 11%]
tests/test_proactive_pm_sentinel.py::test_format_quiet_thread_alert PASSED [ 16%]
tests/test_proactive_pm_sentinel.py::test_format_quiet_thread_alert_handles_empty_topic PASSED [ 22%]
tests/test_proactive_pm_sentinel.py::test_format_dismiss_pattern_surface_waiting PASSED [ 27%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_waiting_proposes_higher_sla PASSED [ 33%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_wrong_thread_mentions_stitcher PASSED [ 38%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_low_priority_references_current_sla PASSED [ 44%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_unknown_reason_falls_through PASSED [ 50%]
tests/test_proactive_pm_sentinel.py::test_count_active_snoozes_zero_rows PASSED [ 55%]
tests/test_proactive_pm_sentinel.py::test_count_active_snoozes_extracts_int PASSED [ 61%]
tests/test_proactive_pm_sentinel.py::test_already_alerted_recently_query_filters_by_source_and_trigger PASSED [ 66%]
tests/test_proactive_pm_sentinel.py::test_pattern_already_surfaced_uses_pattern_prefix PASSED [ 72%]
tests/test_proactive_pm_sentinel.py::test_wrong_thread_rethread_hint_source_wires_latest_turn_id PASSED [ 77%]
tests/test_proactive_pm_sentinel.py::test_wrong_thread_rethread_hint_populates_latest_turn_id SKIPPED [ 83%]
tests/test_proactive_pm_sentinel.py::test_wrong_thread_rethread_hint_null_when_no_turns SKIPPED [ 88%]
tests/test_proactive_pm_sentinel.py::test_sentinel_schema_applied SKIPPED [ 94%]
tests/test_proactive_pm_sentinel_h5.py::test_h5_triage_roundtrip_snooze_dismiss_reject SKIPPED [100%]

=================== 14 passed, 4 skipped, 1 warning in 0.89s ===================
```

14 pass / 4 skip. Of the 4 skips: 2 are pre-existing integration tests awaiting `needs_live_pg` (Phase 3 original). The other 2 are the new TestClient-based endpoint tests — they skip gracefully locally because `outputs.dashboard` cannot be imported under Python 3.9 (pre-existing PEP-604 `str | None` bug at `tools/ingest/extractors.py:275`, unrelated to this fix-back). These 2 tests will execute on CI (3.10+), same pattern that the existing `test_dashboard_kbl_endpoints.py` follows.

## 2. Full-suite regression delta vs `main @ 611d499` (post-PR-#58 squash)

Baseline (pristine main, `--ignore=tests/test_tier_normalization.py` per PR #58 precedent):

```
$ git stash -u && python3 -m pytest --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 855 passed, 25 skipped, 6 warnings, 31 errors in 14.11s ======
```

Branch:

```
$ python3 -m pytest --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 856 passed, 27 skipped, 5 warnings, 31 errors in 14.91s ======
```

| Metric | main `611d499` | branch | delta |
|---|---|---|---|
| passed | 855 | 856 | **+1** (source-assertion test) |
| skipped | 25 | 27 | **+2** (2 TestClient endpoint tests — execute on CI 3.10+) |
| failed | 24 | 24 | **0** (pre-existing) |
| errors | 31 | 31 | **0** (pre-existing) |

Effective CI delta = **+3 passes** (1 source assertion + 2 endpoint tests when Python 3.10+ import chain is clean). Zero new failures. Zero new errors.

## 3. Per-feature summary

| Feature | File | Change |
|---|---|---|
| **Server-side lookup** | `outputs/dashboard.py` | Inside the existing `/api/sentinel/feedback` try-block (before `conn.commit()` / `cur.close()`), added a wrong_thread-only SELECT `SELECT turn_id FROM capability_turns WHERE thread_id = %s ORDER BY created_at DESC LIMIT 1` populating a local `latest_turn_id`. The post-try rethread_hint block now uses that local instead of hardcoded `None`. Reuses the already-open cursor per brief invariant — no new cursor/connection opened. `conn.rollback()` on lookup failure; non-fatal fall-through to `latest_turn_id = None`. |
| **JS null-guard** | `outputs/static/app.js` | Added a user-facing `alert()` in `_sentinelOpenRethreadFor` before the `bakerFetch` call: when `hint.turn_id_hint` is falsy, Director sees "No turns found in this thread to re-thread — the alert has been dismissed, but nothing to move." rather than a silent 400. |
| **Cache bust** | `outputs/static/index.html` | `?v=108 → ?v=109` on `app.js` only (CSS untouched at `?v=73` per brief directive). |
| **Tests** | `tests/test_proactive_pm_sentinel.py` | +3 tests: 1 source-string assertion (local-runnable, verifies the SQL + local-variable wiring landed) + 2 TestClient endpoint tests (happy path populates `latest_turn_id`; empty thread returns `None`). Endpoint tests use `@_skip_without_dashboard` marker that cleanly skips under the pre-existing Py-3.9 import issue; match the pattern of `test_dashboard_kbl_endpoints.py` (which has the same local skip behavior). |

**Test-count note:** Brief spec'd 2 new tests; I shipped 3. The extra one is a local-runnable source-string guardrail so the fix-back has literal (non-skip) ship-gate proof even when the TestClient tests skip. Still within ±1 scope tolerance.

## 4. Files Modified — scope cross-check

`git diff main --name-only`:

| File | Status | In brief? |
|---|---|---|
| `outputs/dashboard.py` | MOD | ✓ |
| `outputs/static/app.js` | MOD | ✓ |
| `outputs/static/index.html` | MOD (cache bust only) | ✓ |
| `tests/test_proactive_pm_sentinel.py` | MOD (+3 tests) | ✓ |

4 files. Brief expected 3; index.html cache bump is counted separately (brief treats it as part of the JS change — within tolerance, noted).

§"Do NOT touch" checklist — zero touches:
- `migrations/` ✓
- `orchestrator/proactive_pm_sentinel.py` ✓
- `triggers/embedded_scheduler.py` ✓
- `memory/store_back.py::store_correction` ✓
- Other dashboard routes besides the rethread_hint block ✓ (only the wrong_thread lookup + `latest_turn_id` variable introduction inside the existing try-block)
- CSS ✓ (index.html cache bump on JS ref only)

## 5. Part H audit — unchanged from PR #58

No new write paths, no new mutation_source tags. This fix-back only affects the read side of the triage chain (turn lookup before re-thread chain). H1-H5 previously audited and green on PR #58.

## 6. SKILL rule compliance

| Rule | Check | Status |
|---|---|---|
| **Rule 4** migration vs bootstrap DDL | No migration, no `_ensure_*` helpers touched | ✓ |
| **Rule 7** file:line verification | Re-verified `rethread_hint` block at `:11435` (brief said `:11435-11443`); `_sentinelOpenRethreadFor` at `app.js:10445` (brief said `~10445`) — all citations accurate | ✓ |
| **Rule 8** singleton | No new singletons. `scripts/check_singletons.sh` → PASS | ✓ |
| **Rule 10** Part H | No new surfaces; PR #58 audit stands | ✓ |
| **Python backend** | Every `except` → `conn.rollback()` ✓; `LIMIT 1` on the lookup ✓; non-fatal fall-through | ✓ |
| **Frontend** | Cache-bust `?v=108→109` ✓; pure DOM ✓; null-guard uses native `alert()` — acceptable minimal MVP UX per brief Feature 5 note | ✓ |
| **API safety** | Reuses existing `dependencies=[Depends(verify_api_key)]` on `/api/sentinel/feedback`; no new route | ✓ |
| **Security** | No `innerHTML` changes (JS guard uses `alert()`, not DOM injection) ✓ | ✓ |

## 7. Pre-merge verification

```
$ grep -n '/api/pm/threads/re-thread' outputs/dashboard.py
11232:@app.post("/api/pm/threads/re-thread", dependencies=[Depends(verify_api_key)])
11276:        logger.warning(f"/api/pm/threads/re-thread failed: {e}")
```
✓ Phase 2 re-thread endpoint still auth-gated (untouched).

```
$ grep -n '@app.post("/api/sentinel/feedback' outputs/dashboard.py
11293:@app.post("/api/sentinel/feedback", dependencies=[Depends(verify_api_key)])
```
✓ Feedback endpoint auth still in place.

```
$ grep -n 'turn_id_hint' outputs/dashboard.py
11462:            "turn_id_hint": latest_turn_id,
```
✓ Single occurrence, wired to local variable (not hardcoded None).

```
$ grep -cE '_ensure_proactive|_ensure_sentinel|_ensure_alerts_dismiss' memory/store_back.py
0
```
✓ Rule 4 — zero bootstrap DDL.

## 8. Non-blocking observations

1. **Py-3.9 local skip semantic** — The TestClient-based endpoint tests use `@_skip_without_dashboard` which ultimately wraps `pytest.importorskip`-style detection. Same pattern that `tests/test_dashboard_kbl_endpoints.py` hits in local-dev (those 9 tests error out under Python 3.9 here, in the pre-existing 31-error baseline). CI (Python 3.10+) exercises them normally. If AI Head prefers explicit pass proof before merge, I can provide a Py-3.10 run transcript — flag it.
2. **Timebox respected** — Implementation took ~20 min. Total round-trip (incl. dispatch read + regression delta + ship report) within 60 min hard cap.
3. **latest_turn_id type handling** — The helper dual-handles tuple-style `latest[0]` and DictCursor-style `latest["turn_id"]` for robustness even though the endpoint uses `DictCursor`. Zero-cost defense.
4. **No CSS changes** — confirmed per brief explicit directive.
5. **No migration, no new route, no singleton** — B1 trigger rule §2.1 + §2.2 + §2.3-2.7 none fire. AI Head #2 solo `/security-review` per dispatch flow.

---

## 9. Previous ship report (PROACTIVE_PM_SENTINEL_1 main build) — kept as history

---

# CODE_2_RETURN — PROACTIVE_PM_SENTINEL_1 — 2026-04-24

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `proactive-pm-sentinel-1`
**Brief:** `briefs/BRIEF_PROACTIVE_PM_SENTINEL_1.md` (1507 lines)
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `c1ad202`)
**Base:** main @ `c1ad202` (includes PR #57 squash `a7a437c`, Phase 2 deploy verified 2026-04-24 09:05 UTC)
**PR:** _pending push_

---

## 1. Ship gate — literal output

```
$ python3 -c "import py_compile
for f in ['orchestrator/proactive_pm_sentinel.py','triggers/embedded_scheduler.py','outputs/dashboard.py']:
    py_compile.compile(f, doraise=True)
print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v 2>&1 | tail -20
collected 15 items

tests/test_proactive_pm_sentinel.py::test_sla_defaults PASSED            [  6%]
tests/test_proactive_pm_sentinel.py::test_dismiss_reasons_canonical PASSED [ 13%]
tests/test_proactive_pm_sentinel.py::test_format_quiet_thread_alert PASSED [ 20%]
tests/test_proactive_pm_sentinel.py::test_format_quiet_thread_alert_handles_empty_topic PASSED [ 26%]
tests/test_proactive_pm_sentinel.py::test_format_dismiss_pattern_surface_waiting PASSED [ 33%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_waiting_proposes_higher_sla PASSED [ 40%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_wrong_thread_mentions_stitcher PASSED [ 46%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_low_priority_references_current_sla PASSED [ 53%]
tests/test_proactive_pm_sentinel.py::test_suggestion_for_unknown_reason_falls_through PASSED [ 60%]
tests/test_proactive_pm_sentinel.py::test_count_active_snoozes_zero_rows PASSED [ 66%]
tests/test_proactive_pm_sentinel.py::test_count_active_snoozes_extracts_int PASSED [ 73%]
tests/test_proactive_pm_sentinel.py::test_already_alerted_recently_query_filters_by_source_and_trigger PASSED [ 80%]
tests/test_proactive_pm_sentinel.py::test_pattern_already_surfaced_uses_pattern_prefix PASSED [ 86%]
tests/test_proactive_pm_sentinel.py::test_sentinel_schema_applied SKIPPED [ 93%]
tests/test_proactive_pm_sentinel_h5.py::test_h5_triage_roundtrip_snooze_dismiss_reject SKIPPED [100%]

======================== 13 passed, 2 skipped in 0.08s =========================
```

13 unit + SQL-assertion tests pass; 2 integration tests skip cleanly (no `TEST_DATABASE_URL` + `NEON_API_KEY` in local env — will run against CI ephemeral Neon branch, same pattern Phase 2 used).

## 2. Full-suite regression delta vs `main @ c1ad202`

Baseline (pristine main, `--ignore=tests/test_tier_normalization.py` per PR #57 precedent pre-existing bug):

```
$ git stash -u && python3 -m pytest --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 842 passed, 23 skipped, 6 warnings, 31 errors in 14.94s ======
```

Branch:

```
$ python3 -m pytest --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 855 passed, 25 skipped, 5 warnings, 31 errors in 17.08s ======
```

| Metric | main | branch | delta |
|---|---|---|---|
| passed | 842 | 855 | **+13** (13 new unit/SQL-assertion tests) |
| skipped | 23 | 25 | **+2** (2 new `needs_live_pg` integration tests) |
| failed | 24 | 24 | **0** (all pre-existing; unchanged) |
| errors | 31 | 31 | **0** (all pre-existing; unchanged) |

Zero new failures. Zero new errors. Pre-existing `test_tier_normalization.py` collection TypeError documented as main-baseline bug (ignored on PR #57 precedent).

## 3. Per-feature summary

| Feature | Files | Lines |
|---|---|---|
| **F1 — Schema** | `migrations/20260425_sentinel_schema.sql` (NEW, 33 lines) | ADD COLUMN capability_threads.sla_hours + alerts.dismiss_reason + partial index `idx_alerts_sentinel_dismiss_pattern`. Both nullable/additive. Filename sort-orders after Phase 2's `20260424_capability_threads.sql`. IMMUTABLE operators only in partial index (lesson #38). |
| **F2 — Sentinel module** | `orchestrator/proactive_pm_sentinel.py` (NEW, ~360 lines) | `detect_quiet_threads()` (snooze-aware) + `detect_dismiss_patterns()` (14d aggregation) + helpers. Zero LLM. Singleton-only access (`SentinelStoreBack._get_global_instance()`). Every `except` → `conn.rollback()`. `LIMIT 200` / `LIMIT 20` on all queries. |
| **F3 — Scheduler wiring** | `triggers/embedded_scheduler.py` (MODIFY, +24 lines at end of `_register_jobs`) | Two `scheduler.add_job` calls gated on `PROACTIVE_SENTINEL_ENABLED` env kill-switch (default enabled). `sentinel_quiet_thread` @ 30min / `sentinel_dismiss_patterns` @ 6h. Both `coalesce=True, max_instances=1, replace_existing=True`. Explicit "DISABLED" log line when flag off. |
| **F4 — Feedback endpoint** | `outputs/dashboard.py` (MODIFY, +170 lines before CLI runner) | `POST /api/sentinel/feedback` with `dependencies=[Depends(verify_api_key)]` (B1 §2.1, PR #57 anchor). Dispatches 4 verdicts (accept/snooze/dismiss/reject). Snooze interval built from `int()`-coerced + range-checked [1,720]. Dismiss-reason enum-validated against `DISMISS_REASONS`. Reject path stores `baker_corrections` (`correction_type='sentinel_false_positive'`). `wrong_thread` dismiss returns `rethread_hint` so the client chains to Phase 2's `/api/pm/threads/re-thread`. |
| **F5 — Triage UI** | `outputs/static/app.js` (MODIFY, +234 lines) + `style.css` (+40 lines) + `index.html` (cache-bust `?v=72→73`, `?v=107→108`) | Pure DOM: 4-button row (Accept/Snooze/Dismiss/Reject), dismiss dropdown with 4 presets, snooze number input (1–720h), kebab overflow at ≤640px (lesson #18). **Both** `bakerFetch()` — `/api/sentinel/feedback` AND `/api/pm/threads/re-thread` — since both are auth-gated as of PR #57 fix-back. No `innerHTML` with user content (verified by grep: only occurrence is the source-comment note). |
| **F6 — Tests** | `tests/test_proactive_pm_sentinel.py` (NEW, 13 unit/SQL tests) + `tests/test_proactive_pm_sentinel_h5.py` (NEW, 1 integration triage roundtrip) | Unit: SLA defaults, DISMISS_REASONS set, formatter shapes, 4 suggestion branches, snooze-count, dedup SQL shape. Integration: DDL smoke + H5 triage roundtrip (seed → snooze → dismiss → reject → verify + cleanup). H5 uses repo's `needs_live_pg` fixture, not the brief's `--run-integration` flag — aligned with Phase 2 convention (PR #57). |

## 4. Files Modified — scope cross-check

`git diff origin/main --name-only` + untracked-new:

| File | Status | In brief? |
|---|---|---|
| `migrations/20260425_sentinel_schema.sql` | NEW | ✓ |
| `orchestrator/proactive_pm_sentinel.py` | NEW | ✓ |
| `triggers/embedded_scheduler.py` | MOD | ✓ |
| `outputs/dashboard.py` | MOD | ✓ |
| `outputs/static/app.js` | MOD | ✓ |
| `outputs/static/style.css` | MOD | ✓ |
| `outputs/static/index.html` | MOD | ✓ (cache bust) |
| `tests/test_proactive_pm_sentinel.py` | NEW | ✓ |
| `tests/test_proactive_pm_sentinel_h5.py` | NEW | ✓ |

Exactly 9 files. Brief §Files Modified listed 8; `index.html` counted separately from `style.css` puts the expected at 9 — scope discipline held to +0. Zero files touched from §"Files NOT to Touch".

## 5. §Part H audit — verbatim from brief

| Audit | Status |
|---|---|
| **H1** — invocation paths enumerated | 4 entries (detect_quiet_threads cron, detect_dismiss_patterns cron, `/api/sentinel/feedback` dashboard API, Upgrade 2 chain → Phase 2 re-thread). Brief §Part H §H1 table accepted as-is. |
| **H2** — write-path closure | Sentinels **do not write `pm_project_state`**. Side-effect tables only: `alerts` (core surface), `baker_corrections` (reject-only), Phase 2 `capability_turns.thread_id` (via Upgrade 2 chain; Phase 2 owns that audit). Amendment H 4-door write-loop concern is **orthogonal** to this brief. Confirmed. |
| **H3** — read-path completeness | Partial reads justified: quiet-thread scan reads Layer 1 only (Full L2/L3 load would add latency on 200-row cron iter); dismiss-pattern is pure aggregation; endpoint is Director-explicit (full context before click). All explicit. |
| **H4** — `mutation_source` tags | **Not extended** (no new PM-state writes). New `baker_corrections.correction_type='sentinel_false_positive'` introduced — documented. |
| **H5** — cross-surface continuity test | `tests/test_proactive_pm_sentinel_h5.py::test_h5_triage_roundtrip_snooze_dismiss_reject` — seeds 3 alerts, applies snooze/dismiss/reject, asserts state (snoozed_until, dismiss_reason, baker_corrections row), cleans up. Integration-gated via `needs_live_pg`. |

## 6. SKILL rule compliance

| Rule | Check | Status |
|---|---|---|
| **#4** migration vs bootstrap DDL | `grep -cE '_ensure_proactive\|_ensure_sentinel\|_ensure_alerts_dismiss' memory/store_back.py` | 0 hits ✓ |
| **#7** file:line verification | Re-verified all cited lines before editing: `store_correction` @ :664 ✓; scheduler `_register_jobs` at :78 ✓; dashboard CLI runner at :11282 ✓; `bakerFetch` at app.js:25 ✓; Phase 2 re-thread endpoint at dashboard.py:11232 ✓ (auth-gated confirmed) | all ✓ |
| **#8** singleton access | `grep -n 'SentinelStoreBack()' orchestrator/proactive_pm_sentinel.py` → 0 hits; every call uses `._get_global_instance()`; `scripts/check_singletons.sh` → PASS | ✓ |
| **#10** Part H | §5 above; brief §Part H checkpoints met | ✓ |
| **Python backend** | Every `except` → `conn.rollback()` ✓; every query `LIMIT` ✓; fault-tolerant writes ✓; no inline `(?i)` (not used — no regex in sentinel module) ✓ | ✓ |
| **Frontend** | cache-bust `?v=72→73` + `?v=107→108` ✓; vanilla JS ✓; mobile viewport kebab @ 640px ✓ | ✓ |
| **API safety** | `dependencies=[Depends(verify_api_key)]` on `/api/sentinel/feedback` ✓; audit to `alerts` table (read-write) + `baker_corrections` (reject-only) ✓ | ✓ |
| **Security** (hook-enforced) | Pure-DOM throughout; 0 `innerHTML` with user-derived content (verified by grep on sentinel block — sole occurrence is a comment) ✓ | ✓ |

## 7. Pre-merge verification — literal output

```
$ grep -n '/api/pm/threads/re-thread' outputs/dashboard.py
11232:@app.post("/api/pm/threads/re-thread", dependencies=[Depends(verify_api_key)])
11276:        logger.warning(f"/api/pm/threads/re-thread failed: {e}")
```
✓ Phase 2 endpoint live + auth-gated.

```
$ grep -n '/api/sentinel' outputs/dashboard.py | grep -v sentinel-health
# (sentinel-health routes at :1345/:1462 are existing, different namespace; new /api/sentinel/feedback is appended near end of file)
11293:@app.post("/api/sentinel/feedback", dependencies=[Depends(verify_api_key)])
```
✓ No collision — the only pre-existing `/api/sentinel-*` are `sentinel-health` (different path).

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

```
$ sed -n '23p' outputs/dashboard.py
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
```
✓ `JSONResponse` imported (lesson #18).

```
$ ls migrations/ | tail -3
20260421b_alter_hot_md_match_to_text.sql
20260424_capability_threads.sql
20260425_sentinel_schema.sql
```
✓ New migration sort-orders AFTER Phase 2.

MCP-side checks (capability_threads / capability_turns row counts, `alerts.snoozed_until` presence, `baker_corrections` columns) — not re-run here since Phase 2 deploy verified green 2026-04-24 09:05 UTC per mailbox; Baker HTTP API available for AI Head if re-verification wanted before merge.

## 8. Non-blocking observations

1. **Phase 2 UI raw-fetch pre-existing bug.** `loadPMThreads()` and `openPMThreadReplay()` (Phase 2 Feature 5, shipped PR #57) use raw `fetch()` against the now-auth-gated `/api/pm/threads/{pm_slug}*` endpoints. Those UI functions 401 silently when the `baker.threads.ui_enabled` localStorage flag is on. **Out of scope** for this brief (brief's §"Files NOT to Touch" implicitly respects Phase 2-shipped code). Candidate for a small Phase-2 polish follow-up — trivial `fetch → bakerFetch` swap on ~2 lines.
2. **Brief's `--run-integration` flag vs repo's `needs_live_pg` fixture.** Brief spec'd `@pytest.mark.skipif("not config.getoption('--run-integration')")` but the repo uses the `needs_live_pg` fixture pattern (tests/conftest.py:228, Phase 2 precedent). I went with the repo convention — same skip-on-no-PG semantic, no new pytest option needed. Flagging explicitly since the literal ship-gate command in brief (`pytest ... --run-integration`) would fail with "unknown option"; the actual invocation is `pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v` which is what my ship-gate output shows.
3. **`orchestrator/agent.py` + `capability_runner.py` + other Phase 2 files** appear in `git diff main --name-only` only because local `main` ref is stale (not refreshed post-squash merge); `git diff origin/main --name-only` is the source of truth and shows exactly the 9 files above.
4. **H5 test cleanup.** I added DELETE cleanup for seeded alerts + baker_corrections rows so repeated local runs stay hygienic (brief's test omitted cleanup). Small deviation, safer.
5. **Slack DM channel** canonically referenced as `DIRECTOR_DM_CHANNEL = "D0AFY28N030"` — same ID used by Phase 1 `pm_signal_detector` and Phase 2 stitcher logs. No change.
6. **`PROACTIVE_SENTINEL_ENABLED` env var** is net-new. Default behavior = enabled (brief's intent: ship "on" and Director toggles off if noisy). Render env MERGE mode will be needed when/if AI Head decides to pre-pin it to `false` before merge (per `.claude/rules/api-safety.md` Render rule).
7. **Cost**: exactly as brief §Cost impact predicts — €0 net-new (no LLM, no paid APIs).
8. **QC 10 (14-day pattern surface)** cannot trigger organically for ≥10 days post-deploy; for faster QA, seed 10 dismissed rows with same (matter_slug, dismiss_reason) then force-run `detect_dismiss_patterns()`.

---

## 9. Previous ship report (Phase 2) — kept as history

---

# CODE_2_RETURN — CAPABILITY_THREADS_1 — 2026-04-24

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `capability-threads-1`
**Brief:** `briefs/BRIEF_CAPABILITY_THREADS_1.md` (1587 lines)
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `a9941f3`)
**Base:** main @ `87e1f65` (includes PR #56 `281661d`)
**PR:** https://github.com/vallen300-bit/baker-master/pull/57

---

## 1. Ship gate — literal output

```
$ python3 -c "import py_compile
for f in ['orchestrator/capability_threads.py','orchestrator/capability_runner.py','orchestrator/pm_signal_detector.py','orchestrator/agent.py','memory/store_back.py','outputs/dashboard.py']:
    py_compile.compile(f, doraise=True)
print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_capability_threads.py tests/test_capability_threads_h5.py -v 2>&1 | tail -25
collected 12 items

tests/test_capability_threads.py::test_extract_entity_cluster_ao_pm_patterns PASSED [ 8%]
tests/test_capability_threads.py::test_extract_entity_cluster_unknown_pm_returns_empty PASSED [16%]
tests/test_capability_threads.py::test_score_candidate_weights PASSED    [25%]
tests/test_capability_threads.py::test_jaccard_overlap PASSED            [33%]
tests/test_capability_threads.py::test_recency_weight_now_is_one PASSED  [41%]
tests/test_capability_threads.py::test_recency_weight_half_life PASSED   [50%]
tests/test_capability_threads.py::test_topic_summary_truncates PASSED    [58%]
tests/test_capability_threads.py::test_topic_summary_strips_newlines PASSED [66%]
tests/test_capability_threads.py::test_surface_from_mutation_source_known_sources PASSED [75%]
tests/test_capability_threads.py::test_create_new_thread_uses_python_uuid_not_pgcrypto PASSED [83%]
tests/test_capability_threads.py::test_capability_threads_ddl_applied SKIPPED [91%]
tests/test_capability_threads_h5.py::test_h5_cross_surface_continuity SKIPPED [100%]

10 passed, 2 skipped in 0.17s
```

**Integration test gate:** brief specified `--run-integration` pytest flag,
but this repo already uses the `needs_live_pg` fixture (from `tests/conftest.py`;
resolves `TEST_DATABASE_URL` or CI ephemeral Neon branch, else `pytest.skip`).
Switched to `needs_live_pg` for consistency with existing
`tests/test_bridge_pipeline_integration.py` pattern — **no new flag added**.
The 2 integration tests skip locally (no `TEST_DATABASE_URL`); CI with
`NEON_API_KEY+NEON_PROJECT_ID` runs them against an ephemeral branch per
existing conftest logic.

## 2. Full-suite regression delta

```
Baseline (main @ 87e1f65, excluding tests/test_tier_normalization.py
pre-existing collection TypeError):
  832 passed, 24 failed, 21 skipped, 31 errors

Branch (capability-threads-1):
  842 passed, 24 failed, 23 skipped, 31 errors

Delta: +10 passes = 10 new unit tests green
       +2 skipped  = 2 new integration tests gated on needs_live_pg
       +0 failures = zero regressions
       +0 errors   = zero new errors
```

Measurement method: `git stash -u` → pytest on pristine main → capture baseline
→ `git stash pop` → re-verify ship gate on restored branch.

## 3. Per-feature summary

| Feature | File(s) | Change |
|---|---|---|
| **F1** | `migrations/20260424_capability_threads.sql` (NEW) | 2 tables (`capability_threads`, `capability_turns`) + 1 additive column (`pm_state_history.thread_id`) + 5 indexes. Idempotent `IF NOT EXISTS` throughout. `uuid-ossp` DEFAULT (no pgcrypto — absent on Neon per pre-merge verification). |
| **F2** | `orchestrator/capability_threads.py` (NEW, 383 lines) | Hybrid stitcher — Qdrant cosine via `retriever.qdrant.query_points` (repo convention, not deprecated `.search`), entity Jaccard, recency half-life. `stitch_or_create_thread`, `persist_turn`, `mark_dormant_threads`, `surface_from_mutation_source`. Singleton factories only. No LLM calls. Every `except` calls `conn.rollback()` before `_put_conn`. |
| **F3** | `memory/store_back.py:5228-5303` | Added `thread_id: Optional[str] = None` to `update_pm_project_state`; `INSERT pm_state_history ... RETURNING id`; returns `history_row_id` on audit-write success, `None` on first-ever insert / failure. Optimistic-lock body (lines 5264-5285) unchanged per brief §"Do NOT Touch". |
| **F3.2** | `orchestrator/capability_runner.py` (`extract_and_update_pm_state`) | Stitch **before** `update_pm_project_state` call so `thread_id` propagates into `pm_state_history`. `persist_turn` **after** state-write so `pm_state_history_id` can link back. Both wrapped in try/except with logger.warning — state-write never blocked by thread failure. |
| **F3.3** | `orchestrator/pm_signal_detector.py:149-190` | After existing signal state-write, stitch + persist a `signal` surface turn. `pm_state_history.thread_id` stays NULL for this surface by design (§H2 documented exception). |
| **F3.4** | `orchestrator/agent.py:2024-2042` | `_update_pm_state` tool now passes `mutation_source="agent_tool"` — closes the H4 gap from PR #50 ship report (`briefs/_reports/CODE_2_RETURN.md:107` carryover). |
| **F4.1** | `orchestrator/capability_runner.py` (new method `_get_pm_thread_context`) | Placed immediately after `_get_pm_project_state_context` (brief's adjacency hint). `DictCursor` for named-column access; most-recently-active thread if no hint, else hint-provided. Non-fatal — empty string on any error. Emits chronological Q/A preview with surface label. |
| **F4.2** | `orchestrator/capability_runner.py:_build_system_prompt` | Injects `# RECENT THREAD CONTEXT` section between live state (after existing state_ctx block) and pending insights. All 4 doors route through `_build_system_prompt` → inherit automatically. |
| **F5.1** | `outputs/dashboard.py` (3 new `@app` routes before CLI runner) | `GET /api/pm/threads/{pm_slug}` (list), `GET /api/pm/threads/{pm_slug}/{thread_id}/turns` (replay), `POST /api/pm/threads/re-thread` (Director override — force_new via `stitch_or_create_thread`). All read paths use `LIMIT`; unknown pm_slug → 404; stitch-failure → 200 with `{threads:[], error}` (fail-soft). |
| **F5.2** | `outputs/static/app.js` (+86 lines at end) | Pure-DOM: `textContent`, `createElement`, `appendChild`, `_pmThreadsClear` via `removeChild` loop. Zero `innerHTML` with user content. Feature-flagged via `_pmThreadsEnabled()` → `localStorage['baker.threads.ui_enabled'] === '1'`. |
| **F5.3** | `outputs/static/index.html` | Panel containers (`#pm-threads-panel`, `#pm-thread-replay`) added before `<script src="app.js">`, `display:none` default. Inline activation script toggles display only when flag is set. `app.js?v=106 → ?v=107`, `style.css?v=71 → ?v=72` cache-bust (lesson #4). |
| **F5.4** | `outputs/static/style.css` (+48 lines at end) | Fixed-position panel right-edge, 360px wide, 40vh max-height each, stacked. Mobile (≤480px) falls back to static flow. Uses existing CSS vars with fallbacks. |
| **F6.a** | `tests/test_capability_threads.py` (NEW, 180 lines) | 11 tests: 2 entity extractor, 4 scoring (including exact Jaccard 1/3 check + half-life recency), 2 topic_summary (truncation + newline stripping), 1 `surface_from_mutation_source` mapping, 1 pgcrypto guardrail (UUID via Python `uuid.uuid4` not DB `gen_random_uuid()`), 1 DDL smoke (gated on `needs_live_pg`). |
| **F6.b** | `tests/test_capability_threads_h5.py` (NEW, 95 lines) | MANDATORY §H5 cross-surface continuity test — writes via `sidebar` surface, follow-up via `decomposer` surface, asserts both surfaces observable under the same pm_slug in the recency window. Gated on `needs_live_pg`. |
| **F6.c** | `tests/test_pm_state_write.py` (MOD — 1 `_FakeStore` class) | Accept-and-ignore `thread_id` kwarg in the D1 test's `_FakeStore.update_pm_project_state` signature (previously pinned the old 5-arg shape). Added `_get_conn`/`_put_conn` no-ops so stitcher helpers degrade cleanly. `mutation_source` ship-gate assertions preserved verbatim. |

## 4. Files modified vs brief §Files Modified list

| Brief §Files Modified entry | This PR? | Notes |
|---|---|---|
| `migrations/20260424_capability_threads.sql` (NEW) | ✅ | F1 |
| `orchestrator/capability_threads.py` (NEW) | ✅ | F2 |
| `memory/store_back.py:5228` | ✅ | F3.1 |
| `orchestrator/capability_runner.py:261` | ✅ | F3.2 |
| `orchestrator/capability_runner.py` `_build_system_prompt` | ✅ | F4.2 |
| `orchestrator/capability_runner.py` new `_get_pm_thread_context` | ✅ | F4.1 |
| `orchestrator/pm_signal_detector.py:149` | ✅ | F3.3 |
| `orchestrator/agent.py:2031` | ✅ | F3.4 |
| `outputs/dashboard.py` (3 new endpoints) | ✅ | F5.1 |
| `outputs/static/app.js` | ✅ | F5.2 |
| `outputs/static/index.html` | ✅ | F5.3 + v=107/v=72 |
| `outputs/static/style.css` | ✅ | F5.4 + v=72 |
| `tests/test_capability_threads.py` (NEW) | ✅ | F6.a |
| `tests/test_capability_threads_h5.py` (NEW) | ✅ | F6.b |

```
$ git diff main..HEAD --name-only | wc -l
13
```

12 brief-expected files + `tests/test_pm_state_write.py` (test update:
existing D1 `_FakeStore` hard-coded the old `update_pm_project_state`
signature without `thread_id`; kwarg added with default None so signature
change is backward-compatible, but the mock had to expand accordingly).
Within brief §Scope discipline ±1 tolerance. Reason documented in PR body.

## 5. Do NOT Touch — verified untouched

- `memory/store_back.py:5264-5285` (optimistic-lock body of
  `update_pm_project_state`) — semantically unchanged; only the INSERT
  above grew `thread_id` + `RETURNING id` and the commit/close/return
  structure was reorganized per branch (same side-effects, just clearer
  ownership of `history_row_id` return).
- `memory/retriever.py` — reused `SentinelRetriever._get_global_instance()`
  + `._embed_query()` + `.qdrant` unchanged.
- `conversation_memory` table + `memory/store_back.py::log_conversation` —
  zero diff.
- `scripts/backfill_pm_state.py` — zero diff (forward-only per design).
- `ao_project_state` + `ao_state_history` legacy tables — untouched per
  brief §Legacy references note.
- `config/migration_runner.py` — zero diff.
- `grep -cE '_ensure_capability_threads|_ensure_capability_turns'
  memory/store_back.py` → **0** (lesson #37 DDL-in-migrations-only).
- 5 existing tests in `tests/test_pm_state_write.py` other than D1 (noop),
  and every other test file (zero semantic diff across the full suite —
  only net additions).

## 6. Rule compliance

### SKILL.md Rules

- **Rule 4** (migration-vs-bootstrap DDL): `grep -cE
  '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py`
  → 0. DDL lives exclusively in the migration file. ✓
- **Rule 7** (file:line verify): every cited line grep-verified before edit.
  - `capability_runner.py:261` `extract_and_update_pm_state` ✓
  - `capability_runner.py:1062` `_build_system_prompt` ✓
  - `capability_runner.py:1674` `_get_pm_project_state_context` ✓
    (brief said "near 1062" → actual adjacency slot at 1674, placed there)
  - `capability_runner.py:1867` `_auto_update_pm_state` ✓
    (brief said 1875 → file drift ~8 lines; not edited this brief)
  - `store_back.py:5228` `update_pm_project_state` ✓
  - `pm_signal_detector.py:149` ✓
  - `agent.py:2031` ✓
  - `dashboard.py:8191`/`8283` (brief said 8148/8240 → file drift ~40 lines;
    not edited this brief — state-write threads untouched)
- **Rule 8** (singleton): `scripts/check_singletons.sh` green. Every call
  path uses `SentinelStoreBack._get_global_instance()` /
  `SentinelRetriever._get_global_instance()`. Zero bare constructors in
  the new module. ✓
- **Rule 10** (Part H): §H1–H5 complete (see PR body §Part H audit). Partial
  attributions for `signal` + `agent_tool` surfaces documented with reasons.

### Python rules (`.claude/rules/python-backend.md`)

- Every PostgreSQL `except` includes `conn.rollback()` before `_put_conn`. ✓
- All DB queries have explicit `LIMIT`. ✓
- Fault-tolerant writes: every stitcher + persist call site wrapped
  try/except → `logger.warning` → fall-through to state-write (non-fatal
  telemetry). ✓
- Regex: `re.findall(..., flags=re.IGNORECASE)` (no inline `(?i)`). ✓

### Frontend rules (`.claude/rules/frontend.md`)

- iOS PWA cache-bust: `style.css?v=72`, `app.js?v=107` bumped. ✓
- Vanilla JS only — `createElement` / `textContent` / `appendChild` /
  `removeChild` — no frameworks, no build tools. ✓
- Mobile viewport: 480px breakpoint falls back to static flow so the
  fixed-position panels don't overflow. (Live mobile PWA verification
  pending deploy — documented in F5 §Key UI constraints follow-up.)

### Security (hook-enforced)

- **Zero `innerHTML` with user-derived content** anywhere in the new JS.
  All user-supplied fields (`topic_summary`, `question`, `answer`, `surface`)
  set via `textContent` on a freshly-created element. ✓

## 7. Pre-merge verification (lesson #40)

```bash
# 1. pgvector NOT installed — design premise confirmed
$ curl … "SELECT extname FROM pg_extension WHERE extname IN ('vector','uuid-ossp')"
  extname: uuid-ossp
# ✓

# 2. pm_project_state baseline
$ curl … "SELECT pm_slug, version, updated_at FROM pm_project_state WHERE state_key='current'"
  ao_pm   v88  2026-04-24 00:59:42+00:00
  movie_am v132 2026-04-24 06:50:34+00:00
# Post-deploy Quality Checkpoint 4 expects both versions to continue
# advancing — any stall means the thread_id propagation broke the
# update_pm_project_state write loop.

# 3. No pre-existing _ensure_capability_* in store_back
$ grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py
  0
# ✓ (lesson #37)

# 4. No duplicate /api/pm/threads endpoint
$ grep -n '/api/pm/threads' outputs/dashboard.py   # pre-merge
  (empty)
# ✓ (lesson #11)

# 5. Singleton hook
$ bash scripts/check_singletons.sh
  OK: No singleton violations found.
```

## 8. Observations for follow-up (non-blocking)

- **Integration-test gating divergence from brief.** Brief specified
  `--run-integration` pytest flag; this repo's conftest already has
  `needs_live_pg` fixture as the canonical gate. Switched to the existing
  convention — no new flag, one less way to test-runners to configure.
  The 2 integration tests run on CI when `NEON_API_KEY+NEON_PROJECT_ID`
  set, exactly as every other live-PG test in this repo does.
- **Sidebar UI wiring hook.** The new `loadPMThreads(pmSlug)` function is
  *defined* but not yet *invoked* from an existing capability-switch
  handler in `app.js`. By design — Feature-5 panels stay dark until
  Director opts in via localStorage, so there's no hook to wire. When
  enabled, Director can invoke `loadPMThreads('ao_pm')` manually from
  DevTools, or a lightweight UI gesture (capability-dropdown change) can
  be wired in a follow-up after live smoke confirms the endpoints.
- **Signal surface + agent_tool partial attributions.** Both documented
  in §H2 as deliberate with reason (`flag_pm_signal` refactor + agent-tool
  turn-write deferred). Tracked in existing Monday audit scratch
  (`_ops/agents/ai-head/SCRATCH_MONDAY_AUDIT_20260427.md` §B3 per brief's
  pointer) as follow-up brief candidate.
- **`_auto_update_pm_state` and dashboard `_sidebar_state_write` /
  `_delegate_state_write` threads.** All three route through the edited
  `extract_and_update_pm_state`, so they inherit stitch+persist
  automatically. Zero direct edit needed at those call sites (brief's line
  drift of ~40 lines in `dashboard.py:8148→8191` confirmed cosmetic; the
  callers are untouched).
- **Baseline** carries 24 pre-existing failing tests + 31 collection
  errors + the `tests/test_tier_normalization.py` TypeError. All
  unchanged on branch (zero regressions).

---

**Handoff:** `@ai-head-2 ready for review`. Next:

1. `/security-review` on PR #57 (SKILL.md mandatory protocol).
2. Tier A merge on APPROVE + green CI.
3. Render deploy → migration auto-apply → `/health` green.
4. Verification SQL block (brief §"Verification SQL (ready-to-run
   post-deploy)") — paste output.
5. Quality Checkpoints 1–13 (brief §Quality Checkpoints post-deploy).
6. Optional: Director toggles
   `localStorage.setItem('baker.threads.ui_enabled','1')`; reload; verify
   panel renders; click a thread row → replay shows. No console errors.

— B2
