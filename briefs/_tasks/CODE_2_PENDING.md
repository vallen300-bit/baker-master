# CODE_2 — PENDING (CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1)

**Status:** PENDING — dispatched 2026-05-03 by AI Head A
**Brief:** `briefs/BRIEF_CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1.md`
**Builder:** B2 (worktree `~/bm-b2`)
**Priority:** P1 — gates clean Step 31 (first canonical Director GOLD on AO matter)
**ETA:** ~2-3h

## Why this matters
Step 30 first LIVE AO Cortex cycle (`70c5e634-134a-4e4d-a478-6c8da512f017`) wall-clocked before Phase 4 because all 4 selected specialists ran sequentially over 13 min. Two bugs in `orchestrator/cortex_phase3_invoker.py`:

1. Sequential `for` loop with `await _invoke_one(...)` — should be concurrent.
2. `_bump_cycle_cost` called once at end of loop — never runs if cycle is cancelled mid-loop, so `cortex_cycles.cost_dollars` stuck at meta-reason cost ($0.07 vs actual $11.93 for cycle 70c5e634).

## Acceptance criteria
- `run_phase3b_invocations` uses `asyncio.gather` (not sequential `for`)
- New `_invoke_one_with_persist_and_bump` helper added; per-completion persist + cost bump
- `asyncio.Semaphore(3)` gates DB writes (PG pool `maxconn=5` per `memory/store_back.py:227-228`)
- Existing `_invoke_one`, `_persist_specialist_output`, `_bump_cycle_cost` primitives **unchanged** (only orchestration changes)
- `pytest tests/test_cortex_phase3_invoker.py -v` passes (tests updated for concurrent ordering)
- `pytest tests/test_cortex_runner_phase126.py -v` still passes
- `bash scripts/check_singletons.sh` clean
- Manual SSE test in DRY_RUN: phase_outputs timestamps clustered within ~30-60s of each other (not the prior 100-300s sequential gaps observed in cycle 70c5e634)

## Key constraints (do NOT touch)
- `cortex_runner.py` outer wrapper (`CYCLE_TIMEOUT_SECONDS=900` stays)
- `cortex_phase3_reasoner.py` Phase 3a meta-reason cost bump (already correct)
- `capability_runner.py` (already concurrency-safe — fresh runner per call)
- `SPECIALIST_TIMEOUT_S` (180s), `SPECIALIST_MAX_RETRIES` (2), `STAGING_ROOT` constants — RA-23-ratified
- DB schema (`cortex_cycles`, `cortex_phase_outputs`) — no migration

## Verification SQL
See `briefs/BRIEF_CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1.md` § Verification SQL — two queries: timestamp clustering check + cycle cost roll-up consistency.

## After merge
- Drop completion report at `briefs/_reports/B2_phase3b_parallel_cost_<YYYYMMDD>.md`
- Mark this mailbox COMPLETE
- AI Head A re-fires Step 30 LIVE AO cycle on fixed runner → canonical first Director GOLD (Step 31)

## Prior CODE_2 task (overwritten, archive reference)
Last CODE_2: `MATTER_KNOWLEDGE_CURATION_PATTERN_1` (mo-vie-am curated knowledge), COMPLETE 2026-04-30, PR baker-vault#33 merged. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
