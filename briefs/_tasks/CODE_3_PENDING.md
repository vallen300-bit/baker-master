# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — author polish-PR brief for the root cause of tonight's migration-drift incident

---

## Task: AUTHOR_BRIEF_MIGRATION_RUNNER_1 — spec a startup-hook migration runner

### Context

Shadow-mode go-live tonight exposed a production hole: **no migration runner on Render.** 9 migration files shipped and merged with the KBL-B code (PRs #8 through #16) were never executed against production Neon. Consequence: `signal_queue` had 25 cols instead of the expected 35+, and `kbl_cost_ledger` / `kbl_cross_link_queue` tables were missing. Every pipeline step past Step 1 would have exploded on the first real signal. Discovery path: AI Head hit the dashboard `/api/kbl/cost-rollup` endpoint post-DATABASE_URL-fix and got `relation "kbl_cost_ledger" does not exist`.

Immediate fix delegated to B1 (apply missing migrations manually). Root cause = process gap. Your job: spec the brief that closes it.

### Deliverable

One authored brief at `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md`. Reviewer: B2. Implementer (later): B1.

### Spec expectations

Design a startup hook in `app.py` (or sibling bootstrap module) that:

1. On service boot (before scheduler starts, before API accepts requests), opens a connection to `DATABASE_URL`.
2. Reads a `schema_migrations` tracking table (create if not exists: `CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), sha256 TEXT)`).
3. Lists `migrations/*.sql` sorted lexicographically.
4. For each file not yet in `schema_migrations`: open a transaction, execute the file's SQL, INSERT the filename + sha256 into `schema_migrations`, commit. On error: rollback, log structured error, abort startup (fail loud — do not continue with a half-applied schema).
5. If all migrations applied: log one INFO line per file applied ("migration X applied, sha256 Y"), then return control to service startup.
6. Idempotency: re-running = no-op (tracking table skips already-applied files).

### Hard constraints to spec

- **sha256 mismatch must abort startup** — if a migration file's content changed after being applied once, that's a bug (migrations are immutable per convention); fail loudly with the filename + stored_sha vs current_sha.
- **Use psycopg2, not SQLAlchemy** — match Baker proper's style (`config/settings.py` pattern).
- **Must run BEFORE `kbl/pipeline_tick` registers in APScheduler** — otherwise the pipeline could tick with missing schema.
- **Mac Mini poller.py behavior** — poller.py is separate and should NOT run this; schema applies happen on Render only. Add a comment explaining why.
- **Rollback path** — document how a Director or B-code can force-re-apply a migration (e.g., `DELETE FROM schema_migrations WHERE filename='...'` + restart; ratified elsewhere, not in startup code).

### Test expectations to spec

- `test_migration_runner_applies_new_file` — fresh DB, one file present, after runner: table created + schema_migrations row inserted.
- `test_migration_runner_skips_applied` — schema_migrations pre-populated, no re-apply, no error.
- `test_migration_runner_aborts_on_sha_mismatch` — stored sha256 ≠ current, startup raises loudly.
- `test_migration_runner_aborts_on_sql_error` — bad SQL in file, transaction rolls back, startup fails, no partial schema, no schema_migrations row.
- `test_migration_runner_runs_before_scheduler` — verify order in `app.py` lifespan.

### CHANDA pre-push (spec must include)

- Q1 Loop Test: migration runner is infrastructure; does not touch Legs 1/2/3 directly. However it GUARDS Leg 2 (kbl_feedback_ledger must exist for ledger writes to work). Pass.
- Q2 Wish Test: serves the wish by preventing "system looks functional while losing reason to exist" (CHANDA §2) — a missing ledger table would silently break Leg 2. Pass.
- Inv 4/8/9/10: unaffected.

### Sign-posting in the brief

- Timeline estimate for B1 impl: ~60-90 min (~120 lines code + ~150 lines tests).
- Priority: HIGH — this is a production process fix. But not P0 tonight; park in `briefs/_drafts/` until tonight's go-live stabilizes + Director ratifies immediate impl or defers to polish queue.
- Parking option: if Director prefers, move to `briefs/_future_optimization/MIGRATION_RUNNER_1_BRIEF.md` per the fanout/ctatedev parking convention (`briefs/_future_optimization/README.md`).

### Deliverable

Short brief (~2-3 pages) at `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md`. Commit + push. Dispatch back:

> B3 AUTHOR_BRIEF_MIGRATION_RUNNER_1 shipped — brief at briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md, commit <SHA>. Ready for B2 brief review + Director ratification of priority (ship-now vs park).

### Timeline

~30-45 min authoring.

### Reviewer

B2 — brief review, not PR review.

---

## Working-tree reminder

Work in `~/bm-b3`. Quit tab after brief push — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Delegated parallel-track to avoid this process gap recurring. The bug that bit us tonight would have been caught automatically with this runner in place.*
