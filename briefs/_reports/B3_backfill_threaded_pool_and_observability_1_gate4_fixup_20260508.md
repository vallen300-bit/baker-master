# B3 Ship Report — Gate 4 fix-up on PR #175

**Brief:** BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1 (Gate 4 follow-up)
**Original ship report:** `briefs/_reports/B3_backfill_threaded_pool_and_observability_1_20260508.md` (committed to main 95653e0)
**Trigger:** Director relayed Gate 4 (`feature-dev:code-reviewer` 2nd-pass) verdict — 1 HIGH + 2 MEDIUM. Folded into a single fix-up commit on the same PR branch.
**Branch:** `b3/backfill-threaded-pool-and-observability-1` @ HEAD `9f5d500`.
**PR:** baker-master [#175](https://github.com/vallen300-bit/baker-master/pull/175) — auto-updated by push, awaiting AH1-App PL re-review + merge.
**Shipped:** 2026-05-08 (post-Gate-4) by B3.

## Findings closed

| Severity | Finding | File | Resolution |
|----------|---------|------|------------|
| HIGH (BLOCKING) | Sentinel-key parity: `report_failure(f"{name}_backfill")` fires on timeout, but `report_success` inside `backfill_plaud` / `backfill_fireflies` uses bare `name`. The `_backfill`-suffixed failure key would never clear → trips T1 after 3 restarts, unclearable without DB edit. | `triggers/backfill_runner.py` | Added `report_success(f"{name}_backfill")` on clean completion (the `not t.is_alive()` path), wrapped in its own try/except matching the existing defensive pattern. |
| MEDIUM #1 | `except ImportError: pass` too narrow — non-ImportError module-level failures (AttributeError, NameError, etc.) propagate and silently kill the boot daemon thread; Fireflies never fires, no sentinel alarm. | `outputs/dashboard.py` (`_delayed_backfills`) | Widened to `except Exception` with `logger.warning(..., exc_info=True)`. |
| MEDIUM #2 | Fireflies has no credential gate. When `FIREFLIES_API_KEY` is unset, `backfill_fireflies` returns immediately, but `"fireflies"` still appears in `invoked` → operator-facing chain log lies. | `triggers/backfill_runner.py` (`run_boot_backfill_chain`) + `outputs/dashboard.py` caller | Added `fireflies_api_key: Optional[str]` parameter symmetric with `plaud_token`. Dashboard caller passes `config.fireflies.api_key`. |

## Tests

**Added:**
- `test_clean_completion_clears_failure_sentinel_key` — verifies `report_success("<name>_backfill")` fires on clean completion (the new HIGH-fix invariant).
- `test_run_boot_backfill_chain_skips_fireflies_when_api_key_missing` — mirrors the existing `_skips_plaud_when_token_missing` test for the new Fireflies gate.

**Updated:**
- `test_run_boot_backfill_chain_runs_plaud_before_fireflies` — passes `fireflies_api_key="present"` so Fireflies actually runs.
- `test_run_boot_backfill_chain_skips_plaud_when_token_missing` — passes `fireflies_api_key="present"`.
- `test_run_boot_backfill_chain_skips_fireflies_when_module_missing` — passes `fireflies_api_key="present"`.
- `test_run_backfill_with_timeout_completes_fast_call` / `_swallows_exceptions` / `_hung_fireflies_does_not_block_plaud_completion_pattern` / `_clean_completion_does_not_increment_abandoned_counter` / `_plaud_token_missing_skips_plaud_chain` — patched `triggers.sentinel_health.report_success` so the new success-clear path doesn't reach the real sentinel.

## Verification (literal stdout)

```
$ python3.12 -m pytest tests/test_backfill_chain_order_and_timeout.py tests/test_store_back_pool_threadsafe.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b3
collected 15 items

tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_completes_fast_call PASSED [  6%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_returns_after_deadline_when_hung PASSED [ 13%]
tests/test_backfill_chain_order_and_timeout.py::test_run_backfill_with_timeout_swallows_exceptions PASSED [ 20%]
tests/test_backfill_chain_order_and_timeout.py::test_abandoned_thread_increments_counter_and_fires_sentinel_alarm PASSED [ 26%]
tests/test_backfill_chain_order_and_timeout.py::test_clean_completion_does_not_increment_abandoned_counter PASSED [ 33%]
tests/test_backfill_chain_order_and_timeout.py::test_clean_completion_clears_failure_sentinel_key PASSED [ 40%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_runs_plaud_before_fireflies PASSED [ 46%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_plaud_when_token_missing PASSED [ 53%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_fireflies_when_api_key_missing PASSED [ 60%]
tests/test_backfill_chain_order_and_timeout.py::test_run_boot_backfill_chain_skips_fireflies_when_module_missing PASSED [ 66%]
tests/test_backfill_chain_order_and_timeout.py::test_hung_fireflies_does_not_block_plaud_completion_pattern PASSED [ 73%]
tests/test_backfill_chain_order_and_timeout.py::test_plaud_token_missing_skips_plaud_chain PASSED [ 80%]
tests/test_backfill_chain_order_and_timeout.py::test_default_timeout_constant_matches_documented_5_minutes PASSED [ 86%]
tests/test_store_back_pool_threadsafe.py::test_store_back_uses_threaded_pool SKIPPED [ 93%]
tests/test_store_back_pool_threadsafe.py::test_init_pool_uses_threaded_constructor PASSED [100%]

======================== 14 passed, 1 skipped in 3.70s =========================
```

```
$ python3.12 -m pytest tests/ -k "store_back or pool or backfill" -v \
    --ignore=tests/test_cortex_proposal_endpoint.py --ignore=tests/test_cortex_run_endpoint.py \
    --ignore=tests/test_cortex_slack_interactivity.py --ignore=tests/test_cortex_trigger_endpoint.py \
    --ignore=tests/test_dashboard_kbl_endpoints.py --ignore=tests/test_scan_endpoint.py
collected 1889 items / 1868 deselected / 21 selected
... (20 passed, 1 skipped)
========== 20 passed, 1 skipped, 1868 deselected, 5 warnings in 3.96s ==========
```

> Note on the 6 ignored files: those test modules import `fastapi.testclient` at module top, and the local 3.12 venv doesn't have `fastapi` installed. Collection failure is environmental + unrelated to the changes here. Render CI runs against the full requirements.txt.

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

```
$ python3 -c "import py_compile; py_compile.compile('triggers/backfill_runner.py', doraise=True); py_compile.compile('outputs/dashboard.py', doraise=True); py_compile.compile('tests/test_backfill_chain_order_and_timeout.py', doraise=True); print('OK')"
OK
```

## Grep verifications

```
$ grep -n "report_success" triggers/backfill_runner.py
73:            from triggers.sentinel_health import report_success
74:            report_success(f"{name}_backfill")
76:            logger.warning(f"sentinel report_success crashed (non-fatal): {_sh_e}")
```

```
$ grep -n "fireflies_api_key" triggers/backfill_runner.py outputs/dashboard.py
triggers/backfill_runner.py:112:    fireflies_api_key: Optional[str],
triggers/backfill_runner.py:137:    if fireflies_api_key and fireflies_fn is not None:
outputs/dashboard.py:584:            fireflies_api_key=config.fireflies.api_key,
```

## Annotations

- The Fireflies-API-key gate is a deliberate semantic shift from the prior contract (where Fireflies invocation depended only on the trigger module being importable). Operator-facing log accuracy was deemed more important than preserving the prior "always-attempt" semantics — and `backfill_fireflies` itself short-circuits on missing key, so the only externally-observable change is the chain log no longer claiming a no-op invocation.
- The `except Exception` widening logs at WARNING with `exc_info=True`, matching the rest of the boot path's defensive pattern. Did not promote to ERROR because Fireflies has been silent-dead since 2026-04-11 — repeat ERROR-level noise on every restart would mask other signals.

---

## PL ship-report (paste-block for AH1-App PL)

```
PL: AH1-App
FROM: B3
RE: PR #175 fix-up — Gate 4 closure

Branch b3/backfill-threaded-pool-and-observability-1 force-fast-forwarded by new commit 9f5d500. PR #175 auto-updated.

Gate 4 findings closed:
- HIGH: sentinel-key parity → run_backfill_with_timeout now fires report_success(f"{name}_backfill") on clean completion. Failure key now actually clears.
- MED #1: Fireflies import widened from ImportError to Exception with logged warning (outputs/dashboard.py).
- MED #2: run_boot_backfill_chain takes fireflies_api_key parameter symmetric with plaud_token; dashboard caller passes config.fireflies.api_key. Chain log no longer claims a no-op invocation.

Verification (literal):
- tests/test_backfill_chain_order_and_timeout.py + tests/test_store_back_pool_threadsafe.py → 14 passed, 1 skipped (env-dep live probe).
- pytest -k "store_back or pool or backfill" (ignoring 6 fastapi-import collection errors unrelated to this change) → 20 passed, 1 skipped.
- check_singletons.sh → OK.
- py_compile clean (3 modified files).

New tests:
- test_clean_completion_clears_failure_sentinel_key (HIGH invariant).
- test_run_boot_backfill_chain_skips_fireflies_when_api_key_missing (MED #2 invariant).

Existing chain tests updated to pass fireflies_api_key="present".

Director ratification anchor: 2026-05-08 chat (Gate 4 verdict relay).

B3 idle. Awaiting Gate 4 re-review verdict.
```
