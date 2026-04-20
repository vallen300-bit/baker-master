# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning)
**Status:** OPEN — PR #20 MIGRATION_RUNNER_1 full review

---

## Task: PR #20 MIGRATION_RUNNER_1 full review

B1 shipped at `00fcb48` on branch `migration-runner-1`. PR `MERGEABLE`. 76/76 tests green (6 new pure + 2 TEST_DATABASE_URL-gated skips). Your own v2 brief APPROVE (`3ff9d22`) is the spec being implemented.

### Verdict focus

**Match impl against brief:**
- `config/migration_runner.py` has `apply_all(db_url=None)` entrypoint wrapping full loop in `pg_try_advisory_lock(0x42BA4E00001)` with 30s timeout + graceful `return []` on contention + `pg_advisory_unlock` in `finally`.
- `_ensure_tracking_table()` does CREATE TABLE IF NOT EXISTS + `information_schema.columns` drift check raising `MigrationError`.
- SHA256 tracking per file; mismatch = `MigrationError` with quoted filename.
- Transaction per file: BEGIN → execute → INSERT tracking row → COMMIT. On raise: ROLLBACK (no tracking row + no schema partial).
- `_GRANDFATHERED = {mac_mini_heartbeat.sql, add_kbl_cost_ledger_and_kbl_log.sql}` hardcoded with retirement-date comment.
- 9 non-grandfathered migration files now have `-- == migrate:up ==` on line 1 (verify with `head -1 migrations/*.sql | grep -v grandfathered`).

**Dashboard startup refactor:**
- `outputs/dashboard.py:329` startup split into `_init_store()` + `_run_migrations()` + `_start_scheduler()` called in order.
- `_init_store()` preserves existing warn-swallow for PG cold-start (P2 polish — semantically different from migration raise-loud).
- `_run_migrations()` raises loud on any MigrationError — FastAPI refuses to finish startup.

**Test coverage:**
- Test #1-4 (apply new, skip applied, sha mismatch abort, sql error abort): pure mock, no skip.
- Test #5 (startup call order): runtime mock-manager `call_args_list` — NOT AST walk per N1. Verify with `grep -c "ast.parse\|call_args_list" tests/test_migration_runner.py` — ast.parse should be 0, call_args_list should be ≥ 1.
- Test #6 (first-deploy idempotency dry-run): `pytest.mark.skipif` on TEST_DATABASE_URL unset.
- Test #7 (forward marker CI): scans `migrations/*.sql` minus `_GRANDFATHERED`, pure file-read.
- Test #8 (advisory-lock contention): sidecar blocker connection, monkey-patches `_LOCK_TIMEOUT_SECONDS` to 2s, gated on TEST_DATABASE_URL.

**CHANDA pre-push:**
- Q1: passes (doesn't touch Legs 1-3 directly; guards Leg 2). Q2: passes (prevents the failure mode that bit us 2026-04-19). Inv 4/8/9/10 unaffected. Module header should docstring this reasoning.

### Specific landmine to check

- **`_LOCK_TIMEOUT_SECONDS` module-level declaration (P1)** — confirm `grep -n "^_LOCK_TIMEOUT_SECONDS" config/migration_runner.py` returns one hit at module scope (so Test #8 can monkey-patch).
- **`_init_store` vs `_run_migrations` error semantics (P2)** — confirm `_init_store` catches + warns on transient PG errors; `_run_migrations` does NOT catch MigrationError.
- **`MigrationError` class declaration order (P3)** — confirm class is defined BEFORE any reference in module.
- **Brief §Hard-constraint #5 forward-ref fixed in impl code** — any docstring or comment in the module should not forward-reference undefined names.

### B1's dry-run disposition note

B1 flags: Test #6 skipped in CI (no Neon throwaway branch on MacBook). Argues idempotency validated by (a) tonight's manual apply all 11 files exit 0, (b) Test #4 rollback-on-error proof, (c) first Render deploy acting as de-facto dry-run (MigrationError → FastAPI startup aborts → Render marks deploy failed, loud signal).

**Your call:** accept this compensating argument (reasonable trade — setting up Neon test branch is a separate infra task) OR REDIRECT asking B1 to stub a `conftest.py` Neon branch fixture. AI Head lean: accept, flag as polish for future (`tests/fixtures/neon_ephemeral_branch.py` in a later PR).

### Verdict

APPROVE or REDIRECT with concrete foldable changes. File at `briefs/_reports/B2_pr20_migration_runner_review_20260420.md`. ~25-35 min.

On APPROVE + MERGEABLE: AI Head auto-merges. Render auto-deploys. First boot runs all 11 migrations against already-applied-state — all skip-if-applied after sha256 match against last-night's manual apply content. Second boot is clean.

**⚠️ sha256 check on first boot** — if the file contents today exactly match what was manually applied last night (via psql/psycopg2), sha256 computed over current file content should match what the runner COMPUTES and records. Since the runner is recording fresh (tracking table currently empty), it'll hash current file content and record. No mismatch possible on first boot. Subsequent boots: if anyone edits a migration file after apply, runner aborts — which is the whole point of R3 + N4.

---

## Working-tree reminder

Work in `~/bm-b2`. Quit tab after verdict — memory hygiene.

---

*Posted 2026-04-20 by AI Head. Last major review of Cortex T3 Phase 1 stabilization work. On merge: tonight's schema-drift failure mode mechanically closed going forward.*
