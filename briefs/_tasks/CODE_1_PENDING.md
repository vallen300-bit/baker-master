# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance — fresh tab, Terminal was closed post-PR-#16 per memory hygiene)
**Previous:** PR #16 STEP7-COMMIT-IMPL shipped at `79ad641`. B2 verdict: REDIRECT on one real race bug.
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — S1 fix on PR #16

---

## Task: PR16-S1-FIX — Move Inv 4 guard inside the flock+pull-rebase window

**Source:** B2 review @ `1e4552b`.

### Why — the race

Current code in `kbl/steps/step7_commit.py:579`:

```
_inv4_guard_target_path(main_abs)   # runs BEFORE the lock + rebase
with acquire_vault_lock(lock_path, timeout):
    _git_pull_rebase(cfg)            # pulls in fresh content from origin/main
    _atomic_write(main_abs, content) # overwrites WHATEVER the pull just brought in
```

**The race:** Director authors a Gold file on dev Mac + pushes to `origin/main`. Mac Mini's local clone hasn't pulled that commit yet. Step 7 runs:

1. Guard reads local file — doesn't exist yet locally, or has old content without `author: director` → guard **passes**
2. Lock acquired, pull-rebase fast-forwards Director's new Gold file into the clone
3. `_atomic_write` overwrites Director's Gold → **Inv 4 silently violated**

B1's existing test `test_commit_inv4_collision_refuses` doesn't catch it because the test seeds the Director file on the local clone before running — no pull-vs-guard ordering tested.

### Scope

**IN**

1. **`kbl/steps/step7_commit.py`** — one-line fix per B2:
   - **Move `_inv4_guard_target_path(main_abs)` INSIDE the `with acquire_vault_lock(...)` block, AFTER `_git_pull_rebase(cfg)` returns.**
   - Order inside the lock becomes: `_git_pull_rebase` → `_inv4_guard_target_path` → atomic writes → git add/commit/push.
   - No other logic changes.

2. **`tests/test_step7_commit.py`** — add ONE new test covering the race path:
   - **Test name:** `test_commit_inv4_collision_after_rebase_refuses` (or similar)
   - **Setup:** two local git clones of the fixture vault. Clone A is the Mac Mini (Step 7 target). Clone B is a "second writer" simulating Director's dev Mac.
   - **Steps:**
     - Start: both clones at same commit, target file does NOT exist locally in A
     - On Clone B: create `wiki/<matter>/<date>_topic.md` with `author: director` frontmatter, commit, push to origin
     - On Clone A (our Step 7 target): DO NOT manually pull
     - Call `commit(signal_id, conn)` on a signal that happens to produce the same `target_vault_path`
     - Expected: Step 7 acquires lock → pulls-rebases (brings in Clone B's Director file) → guard fires AFTER rebase → raises `CommitError` → state flips to `commit_failed` → nothing overwritten
   - **Assertions:**
     - Final file content matches Clone B's Director version (not Step 7's overwrite)
     - Signal state = `commit_failed`
     - `CommitError` raised with message referencing `author: director` + `target_vault_path`
     - `git log` on main still shows Clone B's commit (no Step 7 commit on top)

3. **No production code changes besides the one-line reorder.** No other refactors. No nice-to-haves. No S2 fixes.

### Deferred (do NOT apply now)

- B2's 2 S2 (rebase-abort before hard-reset, idempotent no-op commit) — track for polish PR
- B2's 6 N nits (stale pipeline_tick docstring, `_links.md` .gitignore hygiene, regex robustness on quotes/comments, `git clean -fd` scope narrowing, inline ALTER TABLE pattern from PR #15 S2) — track for polish PR

### CHANDA pre-push

- **Q1 Loop Test:** no new Leg surface; just reorder-for-correctness within existing Leg 1 producer. Pass.
- **Q2 Wish Test:** honors wish — Inv 4 protection must be genuine, not theatrical. Pass.
- **Inv 4** now genuinely enforced across the pull-rebase window.

### Branch + PR

- **Branch:** `step7-commit-impl` (same PR #16 branch).
- **Amend as additional commit** on top of `79ad641`. Do NOT open new PR.
- **PR #16 head advances** — B2 S1 delta re-review = fast APPROVE.

### Timeline

~20-30 min (one-line code change + one test with 2-clone fixture + run suite + commit + push).

### Dispatch back

> B1 PR16-S1-FIX shipped — PR #16 head advanced to `<SHA>`, `_inv4_guard_target_path` moved inside lock+pull window, `test_commit_inv4_collision_after_rebase_refuses` added, `<N>`/`<N>` tests green. Ready for B2 S1 delta APPROVE.

---

## After this task

On B2 APPROVE: I auto-merge PR #16. **7 of 7 pipeline steps on main. Cortex T3 Phase 1 SHIPPED.**

Then: B3 provisions launchd plists (items 5-6 of `AI_DENNIS_MAC_MINI_STEP7_PREP`) against your Step 7 code, and KBL-C handler implementations begin.

---

## Working-tree reminder

Work in `~/bm-b1` or `~/Desktop/baker-code` (wherever your pre-memory-pressure clone lived). Never `/tmp/`. **After this amend: quit the Terminal tab again** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Small-but-real race. B2's one-line ordering fix + one test covers it cleanly.*
