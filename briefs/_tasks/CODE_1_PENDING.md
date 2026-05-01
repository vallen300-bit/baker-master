COMPLETE — BRIEF_MIGRATION_GUARD_FOLLOWUP_1 (B1, 2026-05-01).

PR opened: https://github.com/vallen300-bit/baker-master/pull/147
Report: `briefs/_reports/B1_migration_guard_followup_1_20260501.md`

Architect deferred nits from PR #146 (3 files touched):
- `.githooks/pre-commit` — N3: worktree-correct `COMMIT_EDITMSG` via `git rev-parse --git-path`
- `scripts/check_applied_migrations.sh` — N1: hash-tool failure → distinct diagnostic (collect-all preserved)
- `scripts/refresh_applied_migrations_lock.py` — N2: pre-write disk-presence validation

Tier B / LOW / autonomous-merge-on-green (ai-head-autonomy-charter.md §3).

Parent brief's 6 acceptance cases + 3 new V1/V2/V3 cases all pass. Pre-existing 20260430_cortex_directives.sql drift was OUT OF SCOPE and currently reconciled (lock matches disk).

B1 idle. Next dispatcher: run §2 busy-check (`_ops/processes/b-code-dispatch-coordination.md`) before overwriting.
