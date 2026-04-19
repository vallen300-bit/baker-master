# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — fold B2 REDIRECT into MIGRATION_RUNNER_1 brief

---

## Task: MIGRATION_RUNNER_1_BRIEF_V2 — fold B2 REDIRECT items

B2 REDIRECT at `briefs/_reports/B2_migration_runner_brief_review_20260419.md` (commit `4a2c6db`). Brief is architecturally sound; three must-fix folds + 4 N-level nits to incorporate. Expected ~15 min.

Brief file: `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md`.

---

### Must-fix folds (R1, R2, R3)

**R1 — Concurrency contract.** Brief is silent on what happens if two Render service replicas boot simultaneously and both try to apply the same migration file. Two paths — AI Head recommends path (a):

- **(a) pg_advisory_lock (recommended, 4 LOC).** Wrap the whole migration loop in `pg_try_advisory_lock(<stable int key>)` / `pg_advisory_unlock(<same>)`. If the lock can't be acquired within ~30s, log a WARN and exit startup gracefully (the other replica is mid-apply; we boot after they finish). Add one test: `test_second_instance_blocks_on_advisory_lock` — simulate via two psycopg2 connections, one holds the lock, second one times out cleanly. Pick a constant int key (e.g. `0x42B_A4E_00001` — mnemonic "Baker migrations v1"; document the constant in module docstring).
- **(b) Explicit single-instance assumption.** Add a §Scope "Concurrency — single-instance assumption" noting Render today runs 1 web service instance; if scale-up ever happens, migration runner must be disabled OR upgraded to path (a). Ship with instance-count check at startup: `os.environ.get("RENDER_INSTANCE_ID")` or equivalent — abort if unexpected value.

**Recommendation: (a).** 4 LOC + 1 test is cheaper than the documented-constraint debt in (b).

**R2 — First-deploy retroactive-claim behavior.** Add a §"First deploy behavior" section naming all 11 migration files that will re-run on the first boot after MIGRATION_RUNNER_1 merges (tracking table starts empty; runner will re-execute every file). Because all migrations are idempotent (`IF NOT EXISTS` throughout) this is safe, but the brief should state this explicitly so B1 knows what to verify during local dry-run. Enumerate:

```
20260418_expand_signal_queue_status_check.sql
20260418_loop_infrastructure.sql
20260418_step1_signal_queue_columns.sql
20260418_step2_resolved_thread_paths.sql
20260418_step3_signal_queue_extracted_entities.sql
20260418_step4_signal_queue_step5_decision.sql
20260419_mac_mini_heartbeat.sql
20260419_step5_signal_queue_opus_draft.sql
20260419_step6_kbl_cross_link_queue.sql
20260419_step6_signal_queue_final_markdown.sql
20260419_add_kbl_cost_ledger_and_kbl_log.sql
```

Commit B1 to a local dry-run idempotency audit: spin up a Neon branch (or local PG), point DATABASE_URL at it, seed with current prod schema, run migration_runner, verify no errors + every file ends up in `schema_migrations` table. Include the dry-run command in brief §5 "Test plan" as test #6.

**R3 — Section-marker convention.** Runner reads files whole today (no UP/DOWN parse). That's fine for now, BUT `tests/test_migrations.py:35-80` already uses a regex that expects `-- == migrate:up ==` markers. Two concrete changes:

1. Grandfather the 2 currently marker-less files (`mac_mini_heartbeat.sql` + `add_kbl_cost_ledger_and_kbl_log.sql`) — runner treats a file without markers as a single UP block (current behavior). Document this in brief as "section markers are optional for the initial 11 files; required going forward".
2. Require `-- == migrate:up ==` on the first line of every NEW migration file added after MIGRATION_RUNNER_1 ships. Add one test: `test_migration_file_has_up_marker` — scans `migrations/*.sql` EXCLUDING the two grandfathered files, fails CI if any new file is missing the marker. Grandfather list hardcoded + commented with retirement date ("remove grandfather list when the two files are rewritten with markers, no earlier than Phase 2").

The runner itself remains file-level (no section parse); the marker requirement is forward-compatibility hygiene for a future UP/DOWN parser.

---

### N-level folds (N1-N4)

- **N1** — replace AST-check for startup ordering (`ast.parse` on `outputs/dashboard.py` + assertion on call order) with a runtime fixture: mock `start_scheduler` + assert `migration_runner.apply_all()` was called before it. Less fragile; survives refactors. ~8 lines.
- **N2** — test DB env-gating: use `TEST_DATABASE_URL` env var convention (matches `tests/test_migrations.py` + `tests/test_layer0_dedupe.py`); do NOT use the `testing.postgresql` library the current draft hints at. Consistency with repo test patterns.
- **N3** — `CREATE INDEX CONCURRENTLY` future-proofing note: if any future migration adds a non-concurrent CREATE INDEX on a large table, it locks the table for writes. Document in brief as a "gotcha to watch for" in §6 "Known limitations". Runner doesn't enforce concurrency (that's migration-author discipline), but brief flags it.
- **N4** — `schema_migrations` column-drift defense: add a migration at the top of `migrations/` (`20260419_schema_migrations_bootstrap.sql`? — or create inline in the runner with `IF NOT EXISTS` and abort-on-column-mismatch check) that creates the tracking table itself. Include schema version check: if tracking table exists but with different columns than expected, abort with clear message. Prevents "we upgraded the runner but forgot to migrate its own table" failure mode.

---

### Deliverable

- Update `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md` in-place (no new file).
- Commit + push. Single commit: "brief(v2): fold B2 R1+R2+R3 + N1-N4 into MIGRATION_RUNNER_1".
- Dispatch back: `B3 MIGRATION_RUNNER_1_BRIEF_V2 shipped — brief at briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md head <SHA>. R1 (pg_advisory_lock + test), R2 (first-deploy §, 11 files named, dry-run command in §5), R3 (grandfather + forward marker requirement + test), N1-N4 all folded. Ready for B2 re-review.`

### Timeline

~15-20 min. Small authoring pass; no new architectural thinking, just turning B2's specific asks into brief prose + test enumeration.

### Reviewer

B2 — re-review on next cycle (expected APPROVE or single-item wave-through).

---

## Working-tree reminder

Work in `~/bm-b3`. Quit tab after push — memory hygiene.

---

*Posted 2026-04-19 by AI Head. B2's REDIRECT was surgical and well-targeted; folds are mechanical. On B2 APPROVE, AI Head dispatches B1 for the ~90 min impl PR.*
