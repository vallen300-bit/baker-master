# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — MIGRATION_RUNNER_1 brief re-review

---

## Task: MIGRATION_RUNNER_1 brief re-review (post-fold)

B3 folded your R1+R2+R3+N1-N4 REDIRECT items at head `a532a13`. Brief: `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md`.

### Specific fold points to spot-check

- **R1 (concurrency):** `pg_try_advisory_lock(0x42BA4E00001)` with 30s timeout + graceful degrade. Test #8 `test_second_instance_blocks_on_advisory_lock` enumerated. Confirm wrap scope is the WHOLE migration loop + unlock in `finally` block.
- **R2 (first-deploy behavior):** new § with all 11 retroactive files listed. Dry-run promoted to automated test #6. Confirm B1 is committed to the dry-run before PR opens.
- **R3 (marker convention):** grandfather list for the 2 marker-less files (`mac_mini_heartbeat.sql`, `add_kbl_cost_ledger_and_kbl_log.sql`). Forward-requirement enforced by test #7 `test_migration_file_has_up_marker`. Confirm grandfather list is a hardcoded set with retirement-date comment.
- **N1:** startup-order test moved from AST walk to runtime mock fixture; forces `startup()` refactor into `_init_store` / `_run_migrations` / `_start_scheduler`. Sound?
- **N2:** `TEST_DATABASE_URL` convention — matches existing `tests/test_migrations.py` / `tests/test_layer0_dedupe.py`.
- **N3:** `CREATE INDEX CONCURRENTLY` footgun added as corollary to hard-constraint #4. Adequate warning?
- **N4:** column-drift defense: `information_schema.columns` check after `CREATE TABLE IF NOT EXISTS` in `_ensure_tracking_table`. Catches the "runner upgraded but tracking-table not migrated" failure mode.

### Verdict

APPROVE or surgical 2nd REDIRECT. File at `briefs/_reports/B2_migration_runner_brief_rereview_20260419.md`. ~5-10 min.

On APPROVE: AI Head dispatches B1 for ~110-130 min implementation PR (R1 advisory lock + dry-run test #6 + marker test #7 added to the prior estimate).

---

## Working-tree reminder

Work in `~/bm-b2`. **Quit tab after verdict** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Last gate before MIGRATION_RUNNER_1 impl PR hits B1.*
