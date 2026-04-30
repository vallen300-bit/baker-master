# BRIEF — LOCK_KEY_900300_COLLISION_1

**Owner:** B-code (assigned: B3)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** HIGH
**ETA:** 2026-05-02
**Roadmap item:** `lock-key-900300-collision` (V4 queued)

## Problem

Two functions both use `pg_try_advisory_xact_lock(900300)`:
- `orchestrator/financial_detector.py:76`
- `orchestrator/initiative_engine.py:630`

When one holds the lock, the other silently no-ops. Pre-existing; surfaced by B3 during PR #84 review (scheduler-singleton). Not introduced by PR #84.

## Goal

Eliminate the collision. Audit ALL `pg_try_advisory_*lock` keys in the repo for uniqueness; renumber to fix.

## Scope

1. **Inventory every advisory_lock key** in baker-master repo:
   ```
   grep -rn "pg_try_advisory" orchestrator/ kbl/
   ```
   Confirmed keys at brief-author time: 900100 (risk), 900200 (?), 900201 (cadence), 900300 (financial + initiative — COLLISION), 900400 (sentiment), 900500 (convergence), 900600 (obligation), 900700 (action_completion), 8004 (memory_consolidator), 8005 (trend).

2. **Renumber:** assign `initiative_engine.py:630` to `900800` (next free key in the 9003xx series). Keep `financial_detector.py:76` at `900300` (came first in numbering convention, less risk of stale documentation drift).

3. **Verify uniqueness post-edit:** re-run grep, confirm every literal key value appears exactly once across the codebase (excluding comments/docstrings).

4. **Document:** add a comment in each detector that calls advisory_lock referencing the canonical key registry. Optional follow-up: create `orchestrator/_advisory_lock_registry.py` with named constants. **Do not** create the registry in this brief; flag it as a follow-up if it's clean to land separately.

## Test plan

1. Unit tests covering `initiative_engine.py` and `financial_detector.py` should still pass post-rename.
2. Spin up a local pytest run touching both detectors:
   ```
   cd ~/Desktop/baker-code && pytest tests/orchestrator/test_initiative_engine.py tests/orchestrator/test_financial_detector.py -v
   ```
   (Pre-pytest re-checkout ritual: `git checkout <branch>` before `pytest` per shared-worktree race.)
3. Concurrent-fire test: trigger both detectors in quick succession; verify both acquire their locks (no silent no-op).

## Done definition

- PR opened with renumber + grep proof of uniqueness in PR body.
- pytest green on both detectors.
- AI Head A reviews + merges.

## Non-trigger-class

Pure code change, no auth / no DB schema migration / no external API / no Director-override. AI Head A solo review per autonomy charter §4.
