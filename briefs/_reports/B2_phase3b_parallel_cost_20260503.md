# B2 ship report — CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1

**Date:** 2026-05-03
**Builder:** B2 (worktree `~/bm-b2`)
**Brief:** `briefs/BRIEF_CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1.md`
**Branch:** `b2/cortex-phase3b-parallel-cost`
**Mailbox:** `briefs/_tasks/CODE_2_PENDING.md`

## Summary

Both bugs fixed in `orchestrator/cortex_phase3_invoker.py`:

1. **Parallel Phase 3b** — sequential `for await _invoke_one` loop replaced with `asyncio.gather(*invoke_tasks)`. Phase 3b wall-clock now bounded by SLOWEST specialist (~180s p99), not SUM (~750s for cap=5). Worst-case 540s fits the 900s cycle umbrella with room for Phases 4-6.
2. **Incremental cost roll-up** — new `_invoke_one_with_persist_and_bump` helper persists artifact + bumps `cortex_cycles.cost_*` per completion. Partial cost survives mid-cycle cancellation by the outer `asyncio.wait_for(CYCLE_TIMEOUT_SECONDS)`. End-of-loop `_bump_cycle_cost` removed.

DB writes gated by `asyncio.Semaphore(3)` so concurrent PG borrowers stay ≤ pool `maxconn=5` (ref `memory/store_back.py:227-228`). Existing primitives (`_invoke_one`, `_persist_specialist_output`, `_bump_cycle_cost`) untouched per brief constraints.

## Files changed

- `orchestrator/cortex_phase3_invoker.py` — +49 / −10 (orchestration only; primitives unchanged)
- `tests/test_cortex_phase3_invoker.py` — +47 / −7 (per-completion bump assertion + concurrency assertion + zero-cost-failure skip)

## Quality checkpoints (literal output)

### 1. Syntax check (`python3 -c py_compile ... cortex_phase3_invoker.py`)
```
OK
```

### 2. `python3 -m pytest tests/test_cortex_phase3_invoker.py -v`
```
collected 13 items

tests/test_cortex_phase3_invoker.py::test_success_returns_specialist_output PASSED [  7%]
tests/test_cortex_phase3_invoker.py::test_question_includes_signal_and_matter_brain PASSED [ 15%]
tests/test_cortex_phase3_invoker.py::test_unknown_capability_records_failure_and_continues PASSED [ 23%]
tests/test_cortex_phase3_invoker.py::test_timeout_triggers_retries_then_fail_forward PASSED [ 30%]
tests/test_cortex_phase3_invoker.py::test_exception_triggers_retries_then_fail_forward PASSED [ 38%]
tests/test_cortex_phase3_invoker.py::test_partial_failure_one_of_many PASSED [ 46%]
tests/test_cortex_phase3_invoker.py::test_persist_writes_specialist_invocation_artifact PASSED [ 53%]
tests/test_cortex_phase3_invoker.py::test_persist_bumps_cycle_cost_per_completion PASSED [ 61%]
tests/test_cortex_phase3_invoker.py::test_persist_skips_cost_bump_on_zero_cost_failure PASSED [ 69%]
tests/test_cortex_phase3_invoker.py::test_concurrent_execution_bounded_by_slowest PASSED [ 76%]
tests/test_cortex_phase3_invoker.py::test_staging_file_written_on_success PASSED [ 84%]
tests/test_cortex_phase3_invoker.py::test_staging_file_skipped_on_failure PASSED [ 92%]
tests/test_cortex_phase3_invoker.py::test_empty_list_returns_empty_result PASSED [100%]

============================== 13 passed in 0.26s ==============================
```

### 3. `python3 -m pytest tests/test_cortex_runner_phase126.py -v`
```
============================== 16 passed in 0.04s ==============================
```

### 4. Caller-side regression sweep — `phase3 / phase4_wire / phase5_act / phase5_idempotency`
```
============================== 62 passed in 0.11s ==============================
```

### 5. `bash scripts/check_singletons.sh`
```
OK: No singleton violations found.
```

## New tests added

- **`test_persist_bumps_cycle_cost_per_completion`** — replaces `..._after_loop`. Asserts one UPDATE per successful specialist (so partial cost survives mid-cycle cancellation).
- **`test_persist_skips_cost_bump_on_zero_cost_failure`** — failure path returns `cost_tokens=0/cost_dollars=0`; per-completion bump is correctly skipped (no-op DB write avoided).
- **`test_concurrent_execution_bounded_by_slowest`** — 3 specialists each blocking 0.2s in `run_single`; asserts wall < 0.5s (sequential floor would be 0.6s). Direct concurrency contract.

## Out of scope per brief

- `cortex_runner.py` umbrella — untouched (`CYCLE_TIMEOUT_SECONDS=900` stays).
- `cortex_phase3_reasoner.py` Phase 3a meta-reason cost bump — untouched.
- `capability_runner.py` — already concurrency-safe per `_invoke_one` fresh-runner pattern.
- `SPECIALIST_TIMEOUT_S` (180s), `SPECIALIST_MAX_RETRIES` (2), `STAGING_ROOT` — RA-23-ratified, untouched.
- DB schema (`cortex_cycles`, `cortex_phase_outputs`) — no migration; `UPDATE cost_X = cost_X + %s` is already PG-atomic.

## Verification SQL — out-of-band (post-deploy)

The two queries from the brief (timestamp clustering + cost roll-up consistency) require a live DRY_RUN cycle on Render. Ship-time tests cover the asyncio-side contract (concurrency + per-completion bump). DRY_RUN SSE smoke-test belongs to AI Head A on merge per dispatch instruction ("Tier B autonomous-merge per charter §3 once tests are green and SSE smoke-test in DRY_RUN passes").

## Lessons applied

- **No "by inspection"** — every checkpoint above ships with literal pytest output (Lesson #51, `feedback_no_ship_by_inspection.md`).
- **Branch isolation** — work landed on `b2/cortex-phase3b-parallel-cost`, never on main (Lesson `feedback_baker_vault_shared_filesystem.md`).
- **Single-file scope** — only `orchestrator/cortex_phase3_invoker.py` + its dedicated test file modified. No collateral edits.

## Status

PR open, awaiting AI Head A review + autonomous merge per charter §3.
