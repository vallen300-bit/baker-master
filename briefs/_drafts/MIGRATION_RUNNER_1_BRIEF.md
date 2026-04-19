# MIGRATION_RUNNER_1 — Brief for Code Brisen #1

**Author:** B3 (per AUTHOR_BRIEF_MIGRATION_RUNNER_1 dispatch, commit `1af5546`)
**Reviewer (brief):** B2
**Implementer:** B1 (after B2 approves this brief **and** Director ratifies ship-now vs. park)
**Target PR:** TBD (base: `main`; branch: `migration-runner-1`)
**Priority:** HIGH — production process fix. Not P0 tonight; hold in `_drafts/` until go-live stabilizes.

---

## Why — the process hole shadow-mode go-live exposed

Tonight's KBL-B shadow-mode go-live on Render hit a silent production hole: **no migration runner exists.** Nine migration files landed with PRs #8-#16 and merged into `main`, but **none were ever applied to production Neon**. Discovery path (per AI Head handover, 2026-04-19 evening):

1. `/api/kbl/cost-rollup` returned `relation "kbl_cost_ledger" does not exist` after DATABASE_URL fix.
2. `signal_queue` had 25 columns on Neon vs. the 35+ expected by Step 1-6 code.
3. `kbl_cross_link_queue` table was absent entirely.

Immediate fix (B1, in-flight): apply the 9 missing migrations manually against Neon. But manual is exactly the process that failed. **Every future migration that ships with a PR will reintroduce this hole unless we put a runner on the boot path.**

### What "works today" is misleading

The existing `@app.on_event("startup")` in `outputs/dashboard.py:329-401` already executes ad-hoc DDL inline (structured_actions column, `people_issues` table, `ideas`, `generated_documents`). These are:
- Hand-maintained Python strings — no tracking, no versioning, not idempotent-safe beyond `IF NOT EXISTS`.
- Wrapped in a broad `except Exception` that **logs warnings and continues startup** (line 395-397). A failure is invisible.
- Not discoverable — a developer doesn't know to look in `dashboard.py` for a schema change.

The new runner replaces the pattern structurally for `migrations/*.sql` files; the inline DDL block can be migrated out in a follow-up (out of scope for this brief).

---

## Scope

### IN

#### 1. New module: `config/migration_runner.py`

Co-located with `config/settings.py` — same low-level plumbing layer. Not under `kbl/` (runner covers non-KBL migrations too; e.g., `20260418_loop_infrastructure.sql`) and not under `triggers/` (has nothing to do with scheduling).

Public surface:
```python
def run_pending_migrations(database_url: str, migrations_dir: str = "migrations") -> list[str]:
    """Apply all pending *.sql files in lex order. Return list of applied filenames.

    Raises MigrationError on any failure — caller MUST abort startup.
    """
```

Private helpers:
- `_ensure_tracking_table(conn)` — creates `schema_migrations` if not present.
- `_applied_set(conn) -> dict[str, str]` — returns `{filename: stored_sha256}`.
- `_sha256(path) -> str` — file digest.
- `_apply_one(conn, path, sha) -> None` — single-file transaction.

Custom exception:
```python
class MigrationError(RuntimeError):
    """Raised when a migration fails or sha256 drift is detected. Startup must abort."""
```

#### 2. Tracking table DDL (created by runner on first boot)

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sha256     TEXT NOT NULL
);
```

Runner creates this in its own transaction before reading `_applied_set`. Not a "migration" of its own — it is the runner's own bookkeeping.

#### 3. Integration point: `outputs/dashboard.py` `@app.on_event("startup")`

**Line 329 current shape:**
```python
async def startup():
    logger.info("Baker Dashboard starting...")
    # Pre-warm the store connection
    try:
        store = _get_store()
        ...
        # inline DDL block (lines 338-399)
        ...
    # Start Sentinel trigger scheduler
    try:
        start_scheduler()
```

**New shape (B1 inserts runner call between store-init and scheduler-start):**
```python
async def startup():
    logger.info("Baker Dashboard starting...")

    # Pre-warm the store connection (unchanged)
    try:
        store = _get_store()
        ...  # existing inline DDL block stays for now — see follow-up note

    # MIGRATION-RUNNER-1: apply migrations/*.sql BEFORE scheduler registers any jobs.
    from config.migration_runner import run_pending_migrations, MigrationError
    try:
        applied = run_pending_migrations(os.environ["DATABASE_URL"])
        if applied:
            for f in applied:
                logger.info("migration applied: %s", f)
        else:
            logger.info("migrations: all up-to-date")
    except MigrationError as me:
        logger.error("migration runner failed; aborting startup: %s", me)
        raise  # let FastAPI fail loudly — do NOT let scheduler start on half-applied schema

    # Start Sentinel trigger scheduler (unchanged)
    try:
        start_scheduler()
```

**Order constraint is load-bearing.** `_register_jobs()` registers `kbl_pipeline_tick` at `triggers/embedded_scheduler.py:557`. If the scheduler starts before migrations apply, the pipeline could tick against a partial schema and error-storm. Test `test_migration_runner_runs_before_scheduler` asserts this order.

#### 4. Structured logging

Per line in applied set:
```
INFO migration applied: 20260419_step6_kbl_cross_link_queue.sql (sha256: ab12...)
```

On sha mismatch:
```
ERROR migration sha256 drift: filename=20260418_step1_signal_queue_columns.sql stored=ab12... current=cd34...
```

On SQL error:
```
ERROR migration failed: filename=<F> error=<pg error> — rolled back, startup aborting
```

Use stdlib `logging` (`logger = logging.getLogger("config.migration_runner")`) — matches Baker convention.

### OUT (explicitly not in scope for this brief)

- Migrating the existing inline DDL in `dashboard.py` (`people_issues`, `ideas`, `generated_documents`, `structured_actions`, `snoozed_until`) into proper `migrations/*.sql` files. Follow-up brief — does not block this runner.
- A CLI for running migrations standalone (`python -m config.migration_runner`). Nice-to-have; not required for tonight's fix.
- Down migrations / rollback scripts. Baker convention is forward-only; out-of-band `DELETE FROM schema_migrations ...` + manual SQL handles the rare case (see Rollback section).
- Mac Mini poller changes. See note #5 below.

#### 5. Mac Mini poller behavior — do NOT run migrations there

`~/baker-pipeline/poller.py` on Mac Mini (provisioned by B3 per MAC_MINI_LAUNCHD_PROVISION report) imports `kbl.steps.step7_commit` and opens its own short-lived `psycopg2` connection. It does **not** call the migration runner. Render owns the schema; Mac Mini is a read/write client.

B1 should add this comment at the top of `config/migration_runner.py`:

```python
"""Migration runner for Render-hosted Baker services.

Applied exclusively from outputs/dashboard.py startup hook. Mac Mini
poller.py MUST NOT invoke this: schema apply is Render's responsibility
(single migration writer per CHANDA Inv 9 spirit — multiple writers
would race on schema_migrations inserts and could half-apply a file).
"""
```

---

## Hard constraints (ratified in task brief, repeated for B1)

1. **sha256 mismatch aborts startup** — immutable migration convention. Drift = bug. Log `filename + stored_sha + current_sha`; raise `MigrationError`. No "auto-heal" branch.
2. **psycopg2, not SQLAlchemy** — matches `config/settings.py` + `kbl/db.py` pattern. Direct `psycopg2.connect(database_url)`; short-lived; close in finally.
3. **Runs BEFORE `kbl_pipeline_tick` registers in APScheduler** — ordering is the whole point. Test enforces.
4. **Per-file transaction** — one file = one `BEGIN` / `COMMIT`. On any SQL error: `ROLLBACK`, log, raise. Never insert a `schema_migrations` row for a file that didn't fully apply.
5. **Abort startup on any migration error** — do not swallow. The existing inline DDL block swallows (line 395-397); the new runner must not mirror that pattern.

### Additional constraint added by B3 (spec-author)

6. **Connection lifecycle** — the runner opens its OWN connection, not via `_get_store()` / `store._get_conn()`. Reason: `SentinelStoreBack` drags in Qdrant/Voyage bootstrap; runner must be independent so a migration failure doesn't mask as a Qdrant failure. Same rationale as `kbl/db.py:1-9`.

---

## Test expectations (spec for B1 to implement under `tests/test_migration_runner.py`)

Use `pytest` + a per-test Postgres fixture (match Baker convention in `tests/test_pipeline_tick.py` — `psycopg2.connect` against a test schema or use `testing.postgresql` / `pg_fixtures` if present; B1 picks based on what's already in `requirements.txt` test section).

1. **`test_migration_runner_applies_new_file`**
   - Fresh DB, one file `tests/fixtures/migrations/001_noop.sql` with `CREATE TABLE test_noop (id INT)`.
   - Call `run_pending_migrations(url, "tests/fixtures/migrations")`.
   - Assert: `test_noop` exists, `schema_migrations` has one row with correct filename + sha256.

2. **`test_migration_runner_skips_applied`**
   - Pre-insert `schema_migrations` row for `001_noop.sql` with current sha256.
   - Run runner.
   - Assert: no error raised, return value is empty list, table `test_noop` is NOT re-created (i.e., SQL did not execute — verify by inserting a row before running, confirm still present after).

3. **`test_migration_runner_aborts_on_sha_mismatch`**
   - Pre-insert `schema_migrations` row with `sha256='deadbeef'` for `001_noop.sql`.
   - Run runner.
   - Assert: `MigrationError` raised, error message contains filename + both shas, DB state unchanged.

4. **`test_migration_runner_aborts_on_sql_error`**
   - Fixture file `002_bad.sql` containing `CREATE TABLE test_bad (id INT); SELECT nonexistent_function();`.
   - Run runner after a valid `001_noop.sql`.
   - Assert: `001_noop.sql` applies (table + schema_migrations row), then `002_bad.sql` fails → `MigrationError` raised, `test_bad` table does NOT exist (transaction rolled back), no `schema_migrations` row for `002_bad.sql`.

5. **`test_migration_runner_runs_before_scheduler`**
   - Unit-style assert on `outputs/dashboard.py` source: use `ast.parse` to locate the `startup` coroutine, walk its body, assert the line calling `run_pending_migrations` precedes the line calling `start_scheduler` AND that both are inside the same function. Alternatively: refactor `startup()` into explicit sub-calls (`_init_store`, `_run_migrations`, `_start_scheduler`) and assert on call order in a mock test. B1's call — pick whichever lands cleaner.

Timeline budget for tests: ~30 min. Reuse pytest patterns already in `tests/test_pipeline_tick.py`.

---

## Rollback procedure (for Director / B-code runbook)

If a migration applied on Render and later needs to be re-run (e.g., it was a partial success that `schema_migrations` recorded as complete due to `CREATE TABLE IF NOT EXISTS` silently no-oping):

1. **On Neon (via psql or DB console):**
   ```sql
   DELETE FROM schema_migrations WHERE filename = '20260419_step6_kbl_cross_link_queue.sql';
   ```
2. **Restart Render service.** Runner re-applies the file on next boot, re-inserts the `schema_migrations` row.
3. **If the migration file itself was buggy and needs editing:** do NOT edit in place (sha256 check will block). Author a new `*.sql` with a later date prefix and ship as PR. Forward-only.

Document this in a follow-up `docs/ops/migration_rollback.md` (out of scope for B1's impl).

---

## CHANDA pre-push (B1 must include in PR description)

- **Q1 Loop Test:** migration runner is infrastructure; does not directly touch Legs 1 (signal-intake), 2 (ledger-write), or 3 (output). However it **guards** Leg 2 — `kbl_feedback_ledger`, `kbl_cost_ledger`, `kbl_cross_link_queue` must exist for any ledger write or cost tally to succeed. Pass.
- **Q2 Wish Test:** closes the exact failure mode CHANDA §2 warns against — "system looks functional while losing reason to exist." A missing `kbl_cost_ledger` meant Steps 5/6 would have silently failed with Postgres errors tonight, the dashboard would have shown "0 signals processed," and nobody would have known the ledger was never written. Runner makes that class of failure impossible. Pass.
- **Inv 4:** untouched — author metadata lives in markdown, not DDL.
- **Inv 8:** untouched — no KBL feedback flow changes.
- **Inv 9:** respected — Mac Mini poller does not call the runner; Render is the single schema writer.
- **Inv 10:** untouched — no prompt files.

---

## Timeline estimate for B1

- `config/migration_runner.py` — ~80 lines. ~30 min.
- `outputs/dashboard.py` integration — ~15 lines. ~10 min.
- `tests/test_migration_runner.py` — ~150 lines, 5 tests. ~30-40 min.
- Local run + green CI + CHANDA self-check — ~10 min.
- **Total: ~60-90 min.** Matches task-brief estimate.

---

## Parking option (Director decides)

Two dispositions:

### (A) Ship now as polish PR — recommended
- Merge within 24-48 hours of tonight's go-live stabilizing.
- Covers every future migration automatically; no more "did B1 remember to apply it on Neon?"
- Low risk — startup-only code path, covered by 5 tests, abort-loud semantics fail safely.

### (B) Park in `briefs/_future_optimization/`
- If tonight's go-live debugging is still eating Director cycles and any new PR feels like a distraction.
- Park cost: one more manual migration-apply cycle per future PR until unparked.
- If chosen, B3 moves this file to `briefs/_future_optimization/MIGRATION_RUNNER_1_BRIEF.md` + adds entry to that README per the parking convention.

**B3 recommendation: (A) ship now.** Tonight's hole is the exact symptom this runner prevents; parking it reopens the hole with every PR. Cost is ~90 min of B1 time + a B2 review cycle — small surface, small review.

---

## Dispatch back (B1, after impl lands on `main`)

> B1 MIGRATION_RUNNER_1 shipped — PR #<N> merged at <SHA>. `config/migration_runner.py` + startup integration + 5 green tests. `schema_migrations` table auto-created on next Render deploy; runner will retroactively claim all 9 already-applied migrations (sha256 computed against on-disk files; if any drift → fail loud, Director manually reconciles).

---

*Authored 2026-04-19 by B3 per AUTHOR_BRIEF_MIGRATION_RUNNER_1 dispatch. Reviewer: B2 (brief review, not PR review). Implementer: B1 post-ratification.*
