# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening, post-B2-APPROVE)
**Status:** OPEN — MIGRATION_RUNNER_1 implementation PR

---

## Task: MIGRATION_RUNNER_1 — implement the startup-hook migration runner

B3 authored, B2 approved v2 at `3ff9d22`. Brief: `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md` (head `a532a13`).

Target PR: **#20.** Branch: `migration-runner-1`. Base: `main`. Reviewer: B2.

### Why

Tonight's production schema drift (signal_queue missing 10 cols, kbl_cost_ledger + kbl_log missing tables, `/api/kbl/cost-rollup` 500) was the direct consequence of no migration runner on Render. Migration files merged with PRs but never executed on Neon. B1 + AI Head applied them manually tonight. This PR closes the root cause so it never recurs.

### Scope summary (full detail in brief)

1. New module `config/migration_runner.py` with `apply_all(db_url=None)` entrypoint:
   - Opens dedicated `psycopg2.connect(DATABASE_URL)` — NOT `_get_store()` (avoid Qdrant/Voyage bootstrap drag).
   - Wraps the full loop in `pg_try_advisory_lock(0x42BA4E00001)` with 30s timeout + graceful `return []` on contention + `pg_advisory_unlock` in `finally`.
   - Calls `_ensure_tracking_table()` (CREATE TABLE IF NOT EXISTS schema_migrations + column-drift check via `information_schema.columns`).
   - Lists `migrations/*.sql` sorted lexicographically.
   - For each file not in `schema_migrations`: open transaction, execute file SQL, INSERT `(filename, applied_at, sha256)`, commit. On error: rollback + `raise MigrationError` (fail loud — abort startup, never leave half-applied schema).
   - On sha256 mismatch for already-applied file: abort with clear message ("migration X was modified after apply — rebase, revert, or force-re-apply via `DELETE FROM schema_migrations WHERE filename='...'`").

2. Refactor `outputs/dashboard.py:329` startup handler from single `@app.on_event("startup")` into three named functions called in order: `_init_store()` → `_run_migrations()` → `_start_scheduler()`. This makes Test #5 use mock-manager `call_args_list` assertion instead of the fragile AST walk per B2 N1.

3. Add `migrations/20260419_migration_runner_bootstrap.sql` if the `schema_migrations` tracking table isn't inline in the runner. (B3's brief had it inline; follow whichever B3 ratified — check `_ensure_tracking_table()` position in the brief spec.)

4. Seven tests in `tests/test_migration_runner.py` (or `tests/test_config_migration_runner.py` — match repo's existing naming pattern):
   - Test #1: `test_apply_all_applies_new_file` — empty DB, one file, asserts table created + tracking row inserted.
   - Test #2: `test_apply_all_skips_already_applied` — pre-populated tracking, no re-apply.
   - Test #3: `test_apply_all_aborts_on_sha_mismatch` — stored sha ≠ current, `MigrationError` raised with filename quoted.
   - Test #4: `test_apply_all_aborts_on_sql_error_no_partial` — bad SQL, transaction rolls back, no tracking row added, raise propagates.
   - Test #5: `test_startup_call_order` — runtime mock-manager, assert `_init_store` called before `_run_migrations` called before `_start_scheduler`. Per B2 N1: NOT `ast.parse`.
   - Test #6: `test_first_deploy_idempotency_dry_run` — skipped unless `TEST_DATABASE_URL` set. Seed with current prod schema snapshot, call `apply_all`, assert no errors + all 11 files in `schema_migrations` + no column-type drift. Per B2 R2.
   - Test #7: `test_migration_file_has_up_marker` — scan `migrations/*.sql`, exclude `_GRANDFATHERED = {mac_mini_heartbeat.sql, add_kbl_cost_ledger_and_kbl_log.sql}`, assert every remaining file starts with `-- == migrate:up ==`. Per B2 R3.
   - Test #8: `test_second_instance_blocks_on_advisory_lock` — sidecar blocker connection holds the advisory lock, monkey-patch `_LOCK_TIMEOUT_SECONDS = 2`, call `apply_all`, assert returns `[]` with no DDL rows inserted. Per B2 R1.

### Implementer-self-review polish items flagged by B2 (fold during impl)

- **P1:** `_LOCK_TIMEOUT_SECONDS` needs module-level declaration (so Test #8 can monkey-patch it).
- **P2:** preserve existing `_init_store()` warn-swallow-on-PG-cold-start behavior (DIFFERENT from migration runner's raise-loud policy — PG cold start is transient/retryable, migration errors aren't). Keep them separated semantically.
- **P3:** fix minor prose forward-ref in brief §Hard-constraint #5 — `raise MigrationError` referenced before the class is defined. Move class definition earlier in the file OR rewrite the constraint as "raises a configuration error" (prose-level, not a code fix).

### Test env

- `TEST_DATABASE_URL` env gate on tests that hit real PG (matches `tests/test_migrations.py:1-20` + `tests/test_layer0_dedupe.py:1-20`).
- Tests #1-5, #7 can run without real PG (pure mock / file-read).
- Tests #6 + #8 require `TEST_DATABASE_URL` + will skip cleanly if unset.

### CHANDA pre-push

Per brief: Q1 passes by construction (not touching Legs 1/2/3 directly; GUARDS Leg 2 by ensuring ledger table exists). Q2 passes ("system looks functional while losing its reason to exist" — this PR prevents exactly that failure mode). Inv 4/8/10 unaffected; Inv 9 analogically honored (runner is a single-instance concurrency discipline, parallel to Mac Mini's single-writer posture). Docstring this reasoning in `config/migration_runner.py` module header.

### Delivery

- Branch `migration-runner-1`.
- One PR.
- Target PR title: `MIGRATION_RUNNER_1: startup hook for schema migrations — idempotent, sha256-tracked, advisory-locked`.
- Full regression green (current suite + 8 new tests).
- Dispatch back:

> B1 MIGRATION_RUNNER_1 shipped — PR #20 open, branch migration-runner-1, head `<SHA>`, <N>/<N> tests green including 8 new in test_migration_runner.py. Advisory-lock-wrapped, sha256-tracked, grandfather list applied, startup refactored into 3 named functions. Dry-run test #6 passes against TEST_DATABASE_URL (local Neon branch). Ready for B2 review.

### Timeline

**~110-130 min.** Estimate components:
- `config/migration_runner.py` module (~100-120 lines)
- `outputs/dashboard.py:329` startup refactor (~15 lines)
- 8 tests (~250-300 lines)
- Local dry-run against Neon branch (~15 min)
- Fold P1-P3 polish items during impl (~5 min)

### After this task

- B2 reviews PR #20 (~20-30 min, standard PR review).
- On APPROVE + MERGEABLE: AI Head auto-merges per Tier A authority.
- Once deployed on Render: FIRST BOOT will re-apply all 11 migrations (idempotent), log one INFO line per file, populate schema_migrations table. Subsequent boots skip-if-applied.
- Net effect: tonight's schema-drift failure mode is mechanically impossible going forward.

---

## Working-tree reminder

Work in `~/bm-b1`. Quit Terminal tab after PR opens — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Last significant piece of tonight's work — after this + polish PR for store_back.py `((ts::date))` fix, shadow-mode is fully stabilized pending burn-in.*
