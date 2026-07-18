# B4 ship report — VAULT_WRITER_WORKTREE_ISOLATION_1

- **Brief:** `briefs/_tasks/VAULT_WRITER_WORKTREE_ISOLATION_1.md` (lead #8932 / ruling #8942)
- **Repo:** baker-vault · **PR:** https://github.com/vallen300-bit/baker-vault/pull/157
- **Branch:** `b4/vault-writer-worktree-isolation-1` (commit `5357b3d`)
- **Worked in isolated worktree:** `/Users/dimitry/bm-b4-vault-writer-isolation` off `origin/main` — shared `~/baker-vault` untouched (it was on b2's ARM branch, per brief CRITICAL note).
- **Date:** 2026-07-11 · **Gate:** codex G3 (medium) → lead merge → broadcast.

## Deliverables
1. `.githooks/vault_writer_isolation_guard.sh` — blocks a commit when `git rev-parse --show-toplevel` resolves to `/Users/dimitry/baker-vault` and `BAKER_ROLE != lead` (fail-closed when unset). No-op in isolated worktrees/clones. `lead` permitted with warning. Bypass (lead rescue only): `VAULT_WRITER_ISOLATION_BYPASS=1`. Chained into `.githooks/pre-commit`.
2. `_ops/processes/vault-writer-worktree-isolation.md` — rule + rescue procedure + foot-guns anchored to the 3 incidents.
3. `_ops/processes/INDEX.md` — pointer line.
4. `.githooks/tests/test_vault_writer_isolation_guard.sh` — 5 cases.

## Done rubric — real defect exercised LIVE (not "by inspection")

Guard invoked directly from the real shared checkout / a real worktree, exactly as pre-commit calls it:

| AC | Scenario | Expect | Result |
|----|----------|--------|--------|
| AC1 | real `~/baker-vault` + `BAKER_ROLE=b2` | BLOCK | exit 1 ✓ |
| AC2 | isolated worktree + `BAKER_ROLE=b2` | PERMIT | exit 0 ✓ |
| AC3 | real `~/baker-vault` + `BAKER_ROLE=lead` | PERMIT + WARN | exit 0 ✓ |
| AC4 | rule doc + INDEX pointer + foot-guns cite 3 anchors | present | ✓ |
| AC5 | `core.hooksPath=.githooks` on shared checkout | set | ✓ (`= .githooks`) |
| extra | shared + role unset | BLOCK (fail-closed) | exit 1 ✓ |

Unit tests: `PASS=5 FAIL=0`. Full pre-commit chain exercised via the real commit on this branch (guard permitted in worktree, sibling hooks passed).

## Codex G3 round-1 (#8995) — FAIL → hardened (commit `bb9df07`)
Codex flagged one real HIGH (F1): the guard was bypassable by any agent via env — the exact class we cage researcher/ARM against. Both holes closed:
1. `VAULT_WRITER_ISOLATION_BYPASS` was honored *before* the role check → now honored **only when `BAKER_ROLE=lead`**; non-lead + BYPASS → BLOCK.
2. `VAULT_WRITER_ISOLATION_SHARED_ROOT` env let an agent point shared-root at a decoy path → env read removed; path hardcoded. Test seam is now a `--shared-root` argv flag, which git's commit path never passes.

Added codex's two negative tests. Unit `PASS=7 FAIL=0`; live re-exercise on real `~/baker-vault` confirms `b2+BYPASS=1 → BLOCK` and `b2+env SHARED_ROOT=/tmp/decoy → BLOCK`. Re-requested codex round-2 (medium) via lead (bus #8999).

## Note for lead (ruling #8942)
Added the branch-guard note you requested to the rule doc foot-guns: `_ops/hooks/` symlink targets (researcher cage + recommendation-check hook) assume the shared checkout tracks `main`; branch-switching it points those live symlinks at drifted content. That closes the residual you flagged and unblocks the sequenced rec-check → Option B refactor (next in queue).
