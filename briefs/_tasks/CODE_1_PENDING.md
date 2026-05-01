COMPLETE — MIGRATION_IMMUTABILITY_GUARD_1 (B1, 2026-05-01).

PR opened: see `briefs/_reports/B1_migration_immutability_guard_1_20260501.md` for full report.

Two-layer mechanical guard against editing applied migration files:
- `migrations/applied_migrations.lock` (24-entry sha256 snapshot from prod)
- `scripts/check_applied_migrations.sh` + `scripts/refresh_applied_migrations_lock.py`
- `.githooks/pre-commit` + `start.sh` pre-flight
- CLAUDE.md: 1 hard-rule + 1 session-start activation note
- All 6 acceptance criteria verified manually (no GH Actions in this repo)

Activation per clone: `git config core.hooksPath .githooks` (also documented in CLAUDE.md).

Bypass: `Migration-edit-authorized: <reason>` commit-message trailer (editor/`-F` flow) or `BAKER_MIGRATION_EDIT_AUTHORIZED=1` env var (`-m` flow).

B1 idle. Next dispatcher: run §2 busy-check (`_ops/processes/b-code-dispatch-coordination.md`) before overwriting.
