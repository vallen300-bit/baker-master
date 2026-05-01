# B1 — BRIEF_MIGRATION_GUARD_FOLLOWUP_1 completion report

- **Date:** 2026-05-01
- **Brief:** `briefs/BRIEF_MIGRATION_GUARD_FOLLOWUP_1.md` (vault-side; B-code mailbox copy was overwritten on dispatch)
- **Branch:** `b1/migration-guard-followup-1`
- **Commit:** `00c7101 fix(migrations): immutability guard architect-nit followup …`
- **PR:** https://github.com/vallen300-bit/baker-master/pull/147
- **Companion to:** PR #146 (MIGRATION_IMMUTABILITY_GUARD_1, merged 6ba7534 2026-05-01)

## What shipped (3 files, +22/-2)

| File | Change |
|---|---|
| `.githooks/pre-commit` | line 24: `COMMIT_MSG_FILE="$(git rev-parse --git-path COMMIT_EDITMSG)"` (was hardcoded `.git/COMMIT_EDITMSG`). Worktree-correct. (N3) |
| `scripts/check_applied_migrations.sh` | `_sha "$path"` now captures stderr and falls through to a distinct `hash tool failed on <path>` diagnostic when the utility returns empty. Drift-collection loop preserved (no early-exit). (N1) |
| `scripts/refresh_applied_migrations_lock.py` | Pre-write disk-presence validation: refuses to write when prod `schema_migrations` references files not present on disk; lists each missing file and points to git-restore. (N2) |

## Acceptance — parent brief's 6 criteria (re-run)

| # | Criterion | Result |
|---|---|---|
| 1 | `bash scripts/check_applied_migrations.sh` clean run | exit=0 (lock matches disk; no drift currently — pre-existing 20260430_cortex_directives.sql sha now reconciles 8ef277… disk vs 8ef277… lock) |
| 2 | `--commit-msg-file <msg-with-trailer>` bypass | exit=0 |
| 3 | `BAKER_MIGRATION_EDIT_AUTHORIZED=1` env bypass | exit=0 |
| 4 | Syntax: `bash -n .githooks/pre-commit` | OK |
| 5 | Syntax: `bash -n scripts/check_applied_migrations.sh` | OK |
| 6 | Syntax: `py_compile scripts/refresh_applied_migrations_lock.py` | OK |

## Acceptance — 3 new V cases

- **V1 (N1):** Brief proposed FIFO substitution; the existing `[ ! -f "$path" ]` guard rejects FIFOs as missing-file before reaching `_sha`. Switched to `chmod 000` on a real migration file → `_sha` shells out, `shasum` returns empty → diagnostic emitted: `[check_applied_migrations] hash tool failed on migrations/20260418_expand_signal_queue_status_check.sql (sha256sum/shasum returned empty)`. exit=1. File restored, follow-up clean run = exit=0, sha matches lock.
- **V2 (N3):** `git rev-parse --git-path COMMIT_EDITMSG` returns `.git/COMMIT_EDITMSG` in this clone (bm-b1 is a separate clone, not a `git worktree add`). In real worktrees the same call returns `<main>/.git/worktrees/<name>/COMMIT_EDITMSG`. Hook line 24 confirmed via grep.
- **V3 (N2):** Disk-presence guard branch present in `main()` source (`missing = [filename …]` + diagnostic block); verified via `inspect.getsource`. Live DB exercise skipped per brief (matches parent brief "lock refresh requires DATABASE_URL" caveat).

## Out-of-scope, untouched

- Pre-existing 20260430_cortex_directives.sql drift — currently NOT in drift state; lock matches disk. No reconcile needed.
- `start.sh` pre-flight — unchanged; `env -u BAKER_MIGRATION_EDIT_AUTHORIZED` continues to do the right thing.
- `migrations/applied_migrations.lock` — untouched.
- No new test files (consistent with parent brief; bash + standalone Python utility verified by re-run).
- No CLAUDE.md changes beyond what shipped in `b037ac7`.

## Notes for AI Head A (merge-on-green)

- Tier B / LOW / autonomous-merge per ai-head-autonomy-charter.md §3.
- No CI to wait on (Render auto-deploys post-merge; no GH Actions on this repo).
- Pre-commit hook fired clean on the followup commit itself — guard is self-consistent.
- Commit author is the local git-config default (`dimitry@macbook-pro-2.home`); Co-Authored-By Claude trailer present.
