# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — PR #16 S1 delta APPROVE (fast)

---

## Completed since last dispatch

- Task O — PR #16 STEP7-COMMIT-IMPL initial review (REDIRECT @ `1e4552b`, S1 race + 2 S2 + 6 N deferrable) ✓

---

## Task P (NOW, fast): PR #16 S1 delta APPROVE

**PR:** https://github.com/vallen300-bit/baker-master/pull/16
**Branch:** `step7-commit-impl`
**New head:** `2e845d5` (advanced from `79ad641`)
**Change:** B1 moved `_inv4_guard_target_path(main_abs)` INSIDE the `acquire_vault_lock` block, AFTER `_git_pull_rebase(cfg)`. Added `test_commit_inv4_collision_after_rebase_refuses` with 2-clone fixture simulating Director push race. 78/78 tests green.

### Scope

Confirm the one-line fix + race test land cleanly. Your estimate was ~15 min for flip to APPROVE.

**Specific scrutiny:**

1. **Order of operations inside lock** — verify new order: `_git_pull_rebase` → `_inv4_guard_target_path` → atomic writes → git add/commit/push. No guard call remaining outside the lock.

2. **Race test correctness** — `test_commit_inv4_collision_after_rebase_refuses`:
   - Uses 2 clones (Clone A = Mac Mini target, Clone B = Director's dev Mac simulator)
   - Clone B pushes a `author: director` file to origin BEFORE Step 7 runs on Clone A
   - Clone A does NOT manually pull before `commit()` is called
   - Expected: Step 7's internal `_git_pull_rebase` brings Clone B's commit in, THEN guard fires, raises `CommitError`, state → `commit_failed`
   - Assertions: final file content = Clone B's Director version (not overwritten), signal state `commit_failed`, `CommitError` raised with Inv 4 message, `git log` on main shows Clone B's commit not Step 7's

3. **Existing test still passes** — `test_commit_inv4_collision_refuses` (the original, where Director file was seeded locally). Verify it still runs green.

4. **No scope creep** — B1 was told to defer 2 S2 + 6 N. Verify the delta commits ONLY the reorder + new test. No other changes.

### Format

Short one-paragraph APPROVE: append to `B2_pr16_review_20260419.md` OR new `B2_pr16_s1_delta_20260419.md` — your preference.

### Timeline

~10-15 min.

### Dispatch back

> B2 PR #16 S1 delta APPROVE — head `2e845d5`, report at `<path>`, commit `<SHA>`.

**On APPROVE: I auto-merge PR #16. Phase 1 SHIPPED — 7 of 7 pipeline steps on main.**

---

## Working-tree reminder

Work in `~/bm-b2` (never /tmp). **Quit Terminal tab after this review** — Phase 1 ships after your APPROVE, then we regroup for KBL-C and post-Phase-1 polish PR.

---

*Posted 2026-04-19 by AI Head. Last review of the sprint. Tomorrow morning, 7/7 pipeline steps running on production.*
