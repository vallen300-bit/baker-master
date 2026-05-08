---
brief: briefs/BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1.md
worker: b3
shipped_at: 2026-05-08T~13:00Z
working_branch: b3/backfill-threaded-pool-and-observability-1
working_branch_head: c1aedd2
pr: 175
pr_url: https://github.com/vallen300-bit/baker-master/pull/175
pytest_run: literal
status: SHIPPED — awaiting AH1-App PL review + merge
---

# B3 ship report — BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1

## Scope shipped (4 IMPORTANTs)

1. **Fix 1 — Sentinel-on-success / failure on backfill terminal states.** `triggers/plaud_trigger.py:backfill_plaud()` and `triggers/fireflies_trigger.py:backfill_fireflies()` now write to `sentinel_health` on (a) clean ingest-loop completion, (b) empty-recordings no-op (still a successful poll round), (c) top-level except. Each sentinel write wrapped in its own try/except so a transient `sentinel_health` failure cannot mask the underlying backfill error. Closes the silent-stale gap that left `sentinel_health.plaud.last_success_at` at `2026-04-29T09:08:52Z` while 3 transcripts ingested 2026-05-08.
2. **Fix 2 — Pool swap.** `memory/store_back.py:_init_pool` now uses `psycopg2.pool.ThreadedConnectionPool`. `minconn` / `maxconn` unchanged. Same `getconn` / `putconn` API; no call-site edits. Singleton (`_get_global_instance`) intact.
3. **Fix 3 — Abandoned-thread observability.** `triggers/backfill_runner.run_backfill_with_timeout` now (a) increments module-level `abandoned_backfill_count` (process-local; resets on Render restart, which IS the recovery path), (b) captures the wedged daemon's stack via `sys._current_frames()` and emits on `logger.warning`, (c) fires `report_failure("<name>_backfill", ...)` so the cockpit alarms on the silent-pen state. No release-on-timeout / thread-cancellation logic — Render restart remains recovery path.
4. **Fix 4 — Real chain test (kill tautology).** Added shared `run_boot_backfill_chain` helper; `outputs/dashboard.py:_delayed_backfills` now calls it; replaced the tautological `test_plaud_runs_before_fireflies_in_chain` with helper-exercising regression tests. Removed the dead `_run_backfill_with_timeout` import alias from dashboard.

## Files modified (5) + new (1 test)

- `triggers/plaud_trigger.py` — Fix 1a sentinel reports.
- `triggers/fireflies_trigger.py` — Fix 1b sentinel reports.
- `memory/store_back.py` — Fix 2 pool swap + docstrings updated.
- `triggers/backfill_runner.py` — Fix 3 abandoned-thread alarm + Fix 4 `run_boot_backfill_chain` helper.
- `outputs/dashboard.py` — Fix 4 rewire `_delayed_backfills` + drop `_run_backfill_with_timeout` alias.
- `tests/test_backfill_chain_order_and_timeout.py` — Fix 3 + Fix 4 expand to 11 cases (was 6); replaced tautology with helper-exercising version.
- `tests/test_store_back_pool_threadsafe.py` — NEW (Fix 2 regression test — 1 live-construction probe + 1 source-text static guard).

## Literal pytest output

### Primary (Quality Checkpoint #1)

```
$ python3.12 -m pytest tests/test_backfill_chain_order_and_timeout.py tests/test_store_back_pool_threadsafe.py -v

tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_completes_fast_call PASSED          [  7%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_returns_after_deadline_when_hung PASSED [ 15%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_swallows_exceptions PASSED          [ 23%]
tests/test_backfill_chain_order_and_timeout.py::test_abandoned_thread_increments_counter_and_fires_sentinel_alarm PASSED [ 30%]
tests/test_backfill_chain_order_and_timeout.py::test_clean_completion_does_not_increment_abandoned_counter PASSED  [ 38%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_runs_plaud_before_fireflies PASSED    [ 46%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_plaud_when_token_missing PASSED [ 53%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_fireflies_when_module_missing PASSED [ 61%]
tests/test_backfill_chain_order_and_timeout.py::test_hung_fireflies_does_not_block_plaud_completion_pattern PASSED [ 69%]
tests/test_backfill_chain_order_and_timeout.py::test_plaud_token_missing_skips_plaud_chain PASSED                  [ 76%]
tests/test_backfill_chain_order_and_timeout.py::test_default_timeout_constant_matches_documented_5_minutes PASSED  [ 84%]
tests/test_store_back_pool_threadsafe.py::test_store_back_uses_threaded_pool SKIPPED                               [ 92%]
tests/test_store_back_pool_threadsafe.py::test_init_pool_uses_threaded_constructor PASSED                          [100%]

======================== 12 passed, 1 skipped in 3.59s =========================
```

The 1 SKIP is `test_store_back_uses_threaded_pool` — the live-instance probe cannot construct the `SentinelStoreBack` singleton without `VOYAGE_API_KEY` / `DATABASE_URL` in this local env (voyage.Client raises `AuthenticationError` before the pool is built). Added a companion source-text static guard `test_init_pool_uses_threaded_constructor` that passes everywhere — together they pin the regression in any environment.

### Regression (Quality Checkpoint #2)

```
$ python3.12 -m pytest tests/ -k "store_back or pool or backfill" -v \
    --ignore=tests/test_cortex_proposal_endpoint.py \
    --ignore=tests/test_cortex_run_endpoint.py \
    --ignore=tests/test_cortex_slack_interactivity.py \
    --ignore=tests/test_cortex_trigger_endpoint.py \
    --ignore=tests/test_dashboard_kbl_endpoints.py \
    --ignore=tests/test_scan_endpoint.py

collected 1887 items / 1868 deselected / 19 selected

tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_completes_fast_call PASSED          [  5%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_returns_after_deadline_when_hung PASSED [ 10%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_swallows_exceptions PASSED          [ 15%]
tests/test_backfill_chain_order_and_timeout.py::test_abandoned_thread_increments_counter_and_fires_sentinel_alarm PASSED [ 21%]
tests/test_backfill_chain_order_and_timeout.py::test_clean_completion_does_not_increment_abandoned_counter PASSED  [ 26%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_runs_plaud_before_fireflies PASSED    [ 31%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_plaud_when_token_missing PASSED [ 36%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_fireflies_when_module_missing PASSED [ 42%]
tests/test_backfill_chain_order_and_timeout.py::test_hung_fireflies_does_not_block_plaud_completion_pattern PASSED [ 47%]
tests/test_backfill_chain_order_and_timeout.py::test_plaud_token_missing_skips_plaud_chain PASSED                  [ 52%]
tests/test_backfill_chain_order_and_timeout.py::test_default_timeout_constant_matches_documented_5_minutes PASSED  [ 57%]
tests/test_cortex_phase3_reasoner.py::test_no_regex_match_returns_empty_pool PASSED                                [ 63%]
tests/test_plaud_trigger.py::test_backfill_skips_un_transcribed PASSED                                             [ 68%]
tests/test_plaud_trigger.py::test_backfill_re_ingests_processed_shell PASSED                                       [ 73%]
tests/test_plaud_trigger.py::test_backfill_skips_processed_real_body PASSED                                        [ 78%]
tests/test_pm_state_write.py::test_backfill_idempotency_skips_processed_rows PASSED                                [ 84%]
tests/test_status_check_expand_migration.py::test_store_back_python_writer_in_sync_with_migration PASSED           [ 89%]
tests/test_store_back_pool_threadsafe.py::test_store_back_uses_threaded_pool SKIPPED                               [ 94%]
tests/test_store_back_pool_threadsafe.py::test_init_pool_uses_threaded_constructor PASSED                          [100%]

========== 18 passed, 1 skipped, 1868 deselected, 5 warnings in 4.03s ==========
```

6 fastapi-dependent test modules excluded via `--ignore` — pre-existing local env gap (`fastapi` not in local Python 3.12 site-packages), not introduced by this PR. Render / CI environment has fastapi available.

## Quality Checkpoint #3 — singleton guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Quality Checkpoint #4 — py_compile (5 modified + 2 test files)

```
$ python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in [...]]"
OK: all 5 modified + 2 test files compile clean
```

## Grep verifications (acceptance criteria #5–#8)

```
[#5] grep -n "_run_backfill_with_timeout" outputs/dashboard.py
  → 0 matches ✓

[#6] grep -n "report_success" triggers/plaud_trigger.py
  371: from triggers.sentinel_health import report_success, report_failure, should_skip_poll
  400: report_success("plaud")            # incremental — UNCHANGED
  429: report_success("plaud")            # incremental — UNCHANGED
  624: report_success("plaud")            # incremental — UNCHANGED
  676: from triggers.sentinel_health import report_success    # NEW (empty-no-op terminus)
  677: report_success("plaud")                                 # NEW
  773: from triggers.sentinel_health import report_success    # NEW (success terminus)
  774: report_success("plaud")                                 # NEW
  → ≥1 NEW call inside backfill_plaud (lines 668-775) ✓

[#7] grep -n "report_success\|report_failure" triggers/fireflies_trigger.py
  274: from triggers.sentinel_health import report_success, report_failure, should_skip_poll
  443: report_success("fireflies")        # incremental — UNCHANGED
  447: report_failure("fireflies", str(e))    # incremental — UNCHANGED
  504: from triggers.sentinel_health import report_success    # NEW (empty-no-op terminus)
  505: report_success("fireflies")                             # NEW
  610: from triggers.sentinel_health import report_success    # NEW (success terminus)
  611: report_success("fireflies")                             # NEW
  621: from triggers.sentinel_health import report_failure    # NEW (failure terminus)
  622: report_failure("fireflies", f"backfill: {e}")           # NEW
  → ≥1 NEW success-terminus call AND ≥1 NEW failure-terminus call inside backfill_fireflies (lines 452-611) ✓

[#8] grep -n "ThreadedConnectionPool\|SimpleConnectionPool" memory/store_back.py
  6:   "Uses psycopg2 (sync) with ThreadedConnectionPool (2026-05-08; was   ← file-header docstring
  9:    SimpleConnectionPool — swapped because the pool is shared..."        ← historical reference
  229: "Uses ThreadedConnectionPool — the pool is shared by the FastAPI..."  ← _init_pool docstring
  231: "cycle threads. SimpleConnectionPool is documented single-thread-only." ← historical reference
  234: self._pool = psycopg2.pool.ThreadedConnectionPool(                    ← EXECUTABLE LINE
  → ThreadedConnectionPool present in code at line 234.
  → SimpleConnectionPool only appears in docstrings/comments referencing the historical class
    (no callable usage — `grep -n "SimpleConnectionPool(" memory/store_back.py` → 0 matches). ✓
```

Note: brief said "exactly 1 match at line ~226" for `ThreadedConnectionPool`. Actual location is line 234 because the new `_init_pool` docstring references the class once before the executable line. Two textual references are intentional documentation; only one is callable.

## Quality Checkpoint #9 — abandoned-thread alarm

`test_abandoned_thread_increments_counter_and_fires_sentinel_alarm` exercises the new path: patches `triggers.sentinel_health.report_failure`, runs a backfill that wedges past the timeout, asserts `abandoned_backfill_count` increments AND `report_failure("wedged_test_backfill", ...)` fires with "abandoned" in the reason. PASSED.

## Annotations / spec notes

1. **Brief acceptance #8 line number:** brief said `ThreadedConnectionPool` would land at line ~226 (1 match). Implementation lands at line 234 (3 textual matches: file-header doc + `_init_pool` doc + executable line). Functionally equivalent; line drift due to added docstring explaining the rationale of the swap. `SimpleConnectionPool(` callable count = 0 as required.
2. **Live-instance test skip:** `test_store_back_uses_threaded_pool` cannot run in any environment without `VOYAGE_API_KEY` (voyage.Client init blocks before pool is constructed). Added companion `test_init_pool_uses_threaded_constructor` (source-text static guard) so the regression-pin holds in any environment. CI / Render environment with env vars present will exercise both.
3. **Fastapi-dependent regression files:** 6 test modules require `fastapi` which is not installed in local Python 3.12 site-packages. Excluded via `--ignore` for the regression run. These modules error at collection time on `main` HEAD too — not introduced by this PR. CI / Render has fastapi.

## PR

- baker-master [#175](https://github.com/vallen300-bit/baker-master/pull/175) — open, awaiting AH1-App PL review + merge.

## PL ship-report paste-block

```
Paste to: AH1-App

B3 SHIPPED BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1
PR: https://github.com/vallen300-bit/baker-master/pull/175 (#175)
Branch: b3/backfill-threaded-pool-and-observability-1 @ c1aedd2

4 IMPORTANTs folded:
  Fix 1 — sentinel report_success/failure on backfill_plaud + backfill_fireflies (success/empty/except terminuses)
  Fix 2 — memory/store_back.py SimpleConnectionPool → ThreadedConnectionPool (singleton intact)
  Fix 3 — abandoned-thread alarm: counter + sys._current_frames stack dump + report_failure("<name>_backfill", ...)
  Fix 4 — run_boot_backfill_chain shared helper (dashboard + tests share canonical Plaud-first order); _run_backfill_with_timeout alias removed

Tests:
  tests/test_backfill_chain_order_and_timeout.py + tests/test_store_back_pool_threadsafe.py — 12 passed, 1 skipped (env-dep live probe)
  tests/ -k "store_back or pool or backfill" — 18 passed, 1 skipped, no regression
  bash scripts/check_singletons.sh — OK
  py_compile — clean for all 5 modified + 2 test files
  grep verifications #5–#8 — all pass (#5: 0 matches; #8: SimpleConnectionPool callable = 0)

Annotations: 2 spec gaps surfaced in ship report §"Annotations" — line-number drift on AC #8 (functionally equivalent), live-instance test skips locally (paired with source-text static guard).

Ship report: briefs/_reports/B3_backfill_threaded_pool_and_observability_1_20260508.md

Mailbox: flipping CODE_3_PENDING.md → COMPLETE on main, separate commit.

Recommendation: merge after AH1-App review of PR #175 + post-deploy SQL verification (sentinel_health.plaud.last_success_at advances + fireflies.last_failure_at advances ~70s after redeploy).

B3 idle — next dispatch eligible.
```
