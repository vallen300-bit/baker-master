# B1 — MIGRATION_IMMUTABILITY_GUARD_1 (2026-05-01)

## Summary
Two-layer guard against editing already-applied migration files:
- `migrations/applied_migrations.lock` — sha256 snapshot, seeded from prod `schema_migrations` (24 entries, fetched 2026-05-01 via `mcp__baker__baker_raw_query`).
- `scripts/check_applied_migrations.sh` — compares disk vs lock; bypassable via `Migration-edit-authorized:` commit trailer or `BAKER_MIGRATION_EDIT_AUTHORIZED=1` env var.
- `scripts/refresh_applied_migrations_lock.py` — pulls prod `schema_migrations`, rewrites lock.
- `.githooks/pre-commit` — invokes the check, passes `.git/COMMIT_EDITMSG` for trailer detection.
- `start.sh` — runs the check at boot pre-flight; strips the bypass env var so runtime drift is always loud.
- `CLAUDE.md` — one line under "Where stuff lives" + one Hard-Rule line.

## Files added / modified
| File | Change |
|------|--------|
| `migrations/applied_migrations.lock` | NEW — 24-entry sha256 snapshot |
| `scripts/check_applied_migrations.sh` | NEW — checker, bypass-aware |
| `scripts/refresh_applied_migrations_lock.py` | NEW — prod refresher |
| `.githooks/pre-commit` | NEW — hook wrapper |
| `start.sh` | MODIFIED — pre-flight call before `exec uvicorn` |
| `CLAUDE.md` | MODIFIED — 2 one-line additions |

## Pre-existing drift flagged by the guard
Initial seed exposed live drift on `20260430_cortex_directives.sql`:
- prod sha256: `8ef277baa6f1c980ac6f7846b0830144ca810a71d4fcca74dfb1f4d1d8b481ec`
- disk sha256: `018d5bb68fcd1a7545162026cf72de9d2cfe98810f2e5557db88ea259e8fc0a5`

This is exactly the bug the guard exists to catch — the file was edited after PR #125 (`5b55bf1`) was applied to prod. **Action required (AI Head A / Director):**
1. Decide: revert disk to prod sha, OR re-apply the edited file (DELETE + restart) and refresh the lock.
2. Until then this branch's lock will fail check; the merge of this PR itself uses the bypass trailer.

## Acceptance criteria — verified manually (no GitHub Actions in this repo)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Drift detected → exit 1 with diagnostic | ✅ exit=1, drift line + bypass-help printed |
| 2 | Trailer in `--commit-msg-file` → exit 0 | ✅ exit=0, "bypass: trailer present" |
| 3 | `BAKER_MIGRATION_EDIT_AUTHORIZED=1` → exit 0 | ✅ exit=0, "bypass: env var" |
| 4 | All-clean lock matches disk → exit 0 | ✅ exit=0, no output |
| 5 | Missing migration file referenced in lock → exit 1 | ✅ exit=1, "missing file" diagnostic |
| 6 | `start.sh` pre-flight blocks boot on drift; ignores bypass env var | ✅ exit=1 even with `BAKER_MIGRATION_EDIT_AUTHORIZED=1` (env stripped via `env -u`) |

Bonus: missing lock file → exit 2 (usage error, distinct from drift).

## Operational notes
- **Hook activation is NOT automatic.** Each clone needs `git config core.hooksPath .githooks` once. Document in onboarding (CLAUDE.md → "Session start"?). Not in scope for this brief.
- **Pre-commit + `git commit -m "..."` flow**: git does not write `COMMIT_EDITMSG` before pre-commit runs when `-m` is used. Trailer-in-message bypass therefore works only via editor or `-F` flow. The env-var fallback (`BAKER_MIGRATION_EDIT_AUTHORIZED=1 git commit -m "..."`) covers `-m`.
- **Render runtime**: production Render env should NOT carry `BAKER_MIGRATION_EDIT_AUTHORIZED`; even if set, `start.sh` strips it.
- **Lock refresh requires DATABASE_URL** at run time; intended to be run from a workstation with `.env` loaded.

## Test runs (raw)
All exit codes captured via `set +e; cmd; ec=$?; set -e`. Full transcripts in implementation chat; reproducible via:
```bash
scripts/check_applied_migrations.sh                # drift → 1
TMPMSG=$(mktemp); printf 'feat: x\n\nMigration-edit-authorized: t\n' > "$TMPMSG"
scripts/check_applied_migrations.sh --commit-msg-file "$TMPMSG"   # → 0
BAKER_MIGRATION_EDIT_AUTHORIZED=1 scripts/check_applied_migrations.sh   # → 0
```

## Branch / PR
- Branch: `b4/cortex-phase6-reflector-1` (this brief was dispatched onto an active feature branch — see PR description for rebase plan if needed)
- Commit: pending (uses `Migration-edit-authorized: bootstrap initial lock seed` trailer)
- PR title: `feat(migrations): immutability guard — applied_migrations.lock + pre-commit + start.sh pre-flight (MIGRATION_IMMUTABILITY_GUARD_1)`
