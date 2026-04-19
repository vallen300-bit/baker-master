# MIGRATION_RUNNER_1 — Brief for Code Brisen #1

**Author:** B3 (per AUTHOR_BRIEF_MIGRATION_RUNNER_1 dispatch, commit `1af5546`; v2 fold per `MIGRATION_RUNNER_1_BRIEF_V2` dispatch, commit `91ae095`)
**Reviewer (brief):** B2 (first pass: REDIRECT at `briefs/_reports/B2_migration_runner_brief_review_20260419.md`; re-review after v2 fold)
**Implementer:** B1 (after B2 approves this brief **and** Director ratifies ship-now vs. park)
**Target PR:** TBD (base: `main`; branch: `migration-runner-1`)
**Priority:** HIGH — production process fix. Not P0 tonight; hold in `_drafts/` until go-live stabilizes.

---

## Why — the process hole shadow-mode go-live exposed

Tonight's KBL-B shadow-mode go-live on Render hit a silent production hole: **no migration runner exists.** Nine migration files landed with PRs #8-#16 and merged into `main`, but **none were ever applied to production Neon**. Discovery path (per AI Head handover, 2026-04-19 evening):

1. `/api/kbl/cost-rollup` returned `relation "kbl_cost_ledger" does not exist` after DATABASE_URL fix.
2. `signal_queue` had 25 columns on Neon vs. the 35+ expected by Step 1-6 code.
3. `kbl_cross_link_queue` table was absent entirely.

Immediate fix (B1, in-flight): apply the 11 missing migrations manually against Neon. But manual is exactly the process that failed. **Every future migration that ships with a PR will reintroduce this hole unless we put a runner on the boot path.** A second failure mode that must be answered: if Render ever rolls out two instances concurrently (briefly, during a deploy), both startup hooks will race the apply loop — R1 below resolves this.

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
- `_ensure_tracking_table(conn)` — creates `schema_migrations` if not present **and verifies column shape** (see N4 in §Scope.IN.2 below).
- `_applied_set(conn) -> dict[str, str]` — returns `{filename: stored_sha256}`.
- `_sha256(path) -> str` — file digest.
- `_apply_one(conn, path, sha) -> None` — single-file transaction.

Custom exception:
```python
class MigrationError(RuntimeError):
    """Raised when a migration fails or sha256 drift is detected. Startup must abort."""
```

**Section-marker handling (runtime).** Runner reads each `.sql` file raw and passes the whole content to `psycopg2` — no `-- == migrate:up ==` / `-- == migrate:down ==` parsing at runtime. Rationale: the DOWN section in Baker convention is always commented-out (`--` prefix lines), so raw execution is safe regardless of markers. Parsing is `tests/test_migrations.py`'s job (per-ticket round-trip test); the runtime runner treats markers as comments. See R3 below for the forward-compat marker requirement and CI test.

#### 2. Tracking table DDL + column-drift defense (created by runner on first boot)

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sha256     TEXT NOT NULL
);
```

Runner creates this in its own transaction before reading `_applied_set`. Not a "migration" of its own — it is the runner's own bookkeeping.

**N4 — schema_migrations column-drift defense.** Immediately after `CREATE TABLE IF NOT EXISTS`, runner MUST verify column shape:

```python
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'schema_migrations'
""")
cols = {row[0] for row in cur.fetchall()}
expected = {"filename", "applied_at", "sha256"}
missing = expected - cols
if missing:
    raise MigrationError(
        f"schema_migrations exists but is missing expected columns: {missing}. "
        f"Drop and recreate manually, then restart."
    )
```

Prevents the "we upgraded the runner but forgot to migrate its own table" failure mode. If a prior ad-hoc bootstrap created `schema_migrations` with a different shape, `CREATE TABLE IF NOT EXISTS` is a silent no-op that keeps the old shape — next INSERT blows up at runtime. The column check catches the drift at boot, before any migration runs.

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

**New shape (B1 refactors `startup()` into named sub-calls — see N1 in §Test expectations for rationale):**
```python
async def startup():
    logger.info("Baker Dashboard starting...")
    _init_store()          # existing store pre-warm + inline DDL block (unchanged for now)
    _run_migrations()      # NEW — calls run_pending_migrations, raises on failure
    _start_scheduler()     # existing start_scheduler() wrapper

def _run_migrations() -> None:
    """Apply migrations/*.sql before any scheduler job registers."""
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
        raise  # FastAPI fails the lifespan — do NOT let scheduler start on half-applied schema
```

**Order constraint is load-bearing.** `_register_jobs()` registers `kbl_pipeline_tick` at `triggers/embedded_scheduler.py:557`. If the scheduler starts before migrations apply, the pipeline could tick against a partial schema and error-storm. Test `test_migration_runner_runs_before_scheduler` asserts this order via mock patching (N1, below).

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

On advisory-lock timeout (R1 below):
```
WARN migration runner could not acquire advisory lock within 30s; another replica is mid-apply. Continuing startup without running migrations.
```

Use stdlib `logging` (`logger = logging.getLogger("config.migration_runner")`) — matches Baker convention.

### OUT (explicitly not in scope for this brief)

- Migrating the existing inline DDL in `dashboard.py` (`people_issues`, `ideas`, `generated_documents`, `structured_actions`, `snoozed_until`) into proper `migrations/*.sql` files. Follow-up brief — does not block this runner.
- A CLI for running migrations standalone (`python -m config.migration_runner`). Nice-to-have; not required for tonight's fix.
- Down migrations / rollback scripts. Baker convention is forward-only; out-of-band `DELETE FROM schema_migrations ...` + manual SQL handles the rare case (see Rollback section).
- Runtime UP/DOWN section parsing. Runner passes files whole to `psycopg2`; test-suite parses markers for round-trip (see R3).
- Mac Mini poller changes. See note #5 below.

#### 5. Mac Mini poller behavior — do NOT run migrations there

`~/baker-pipeline/poller.py` on Mac Mini (provisioned by B3 per MAC_MINI_LAUNCHD_PROVISION report) imports `kbl.steps.step7_commit` and opens its own short-lived `psycopg2` connection. It does **not** call the migration runner. Render owns the schema; Mac Mini is a read/write client.

B1 should add this comment at the top of `config/migration_runner.py`:

```python
"""Migration runner for Render-hosted Baker services.

Applied exclusively from outputs/dashboard.py startup hook. Mac Mini
poller.py MUST NOT invoke this: schema apply is Render's responsibility.
By analogy to CHANDA Inv 9 (single AGENT writer for signals), Render is the
single SCHEMA writer for migrations — multiple writers would race on
schema_migrations inserts and could half-apply a file even with the
advisory lock (the lock only serializes within Postgres, not across hosts
that might target different DBs).
"""
```

---

## First deploy behavior — retroactive claim of 11 existing files

On first Render deploy after this runner ships, `schema_migrations` is empty. Runner will attempt to apply all 11 files currently under `migrations/` against production Neon (which already has all 11 applied via manual psql tonight). Every file MUST be idempotent under re-run — verified by AI Head's Tier-B apply tonight (all 11 files ran clean with `ON_ERROR_STOP=1`, zero errors, zero duplicates). Post-apply state is the reference.

**B1 MUST verify idempotency BEFORE merging** by running the runner locally against a Neon branch (or local Postgres) pre-seeded to current-prod state (no `schema_migrations` rows, all tables/columns present). Expected behavior: all 11 files apply clean, 11 rows inserted into `schema_migrations`, zero errors. See §Test expectations #6 for the exact dry-run command.

Files currently expected on boot-after-merge (lex-sorted — runner order):

1. `20260418_expand_signal_queue_status_check.sql` — `DROP CONSTRAINT IF EXISTS … ADD CONSTRAINT` (re-entrant; verified 34 status values tonight)
2. `20260418_loop_infrastructure.sql` — `CREATE TABLE IF NOT EXISTS` ×3 + `signal_queue.id → BIGINT` upgrade (`ALTER` is no-op when already BIGINT)
3. `20260418_step1_signal_queue_columns.sql` — `ADD COLUMN IF NOT EXISTS`
4. `20260418_step2_resolved_thread_paths.sql` — `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`
5. `20260418_step3_signal_queue_extracted_entities.sql` — ditto
6. `20260418_step4_signal_queue_step5_decision.sql` — `ADD COLUMN IF NOT EXISTS`
7. `20260419_add_kbl_cost_ledger_and_kbl_log.sql` — `CREATE TABLE IF NOT EXISTS` ×2 + indexes
8. `20260419_mac_mini_heartbeat.sql` — `CREATE TABLE IF NOT EXISTS`
9. `20260419_step5_signal_queue_opus_draft.sql` — `ADD COLUMN IF NOT EXISTS` + `CREATE TABLE IF NOT EXISTS kbl_circuit_breaker` + `INSERT ON CONFLICT DO NOTHING` (seed row)
10. `20260419_step6_kbl_cross_link_queue.sql` — `CREATE TABLE IF NOT EXISTS` + indexes
11. `20260419_step6_signal_queue_final_markdown.sql` — `ADD COLUMN IF NOT EXISTS`

**Idempotency invariant for all future migrations:** every file MUST run cleanly against an already-applied state. Use `IF NOT EXISTS` / `DROP … IF EXISTS` / `INSERT … ON CONFLICT DO NOTHING` / `ALTER COLUMN … IF EXISTS` throughout. This belongs in a future `docs/ops/migrations_conventions.md` (out of scope for B1).

---

## Hard constraints (ratified in task brief, repeated for B1)

1. **sha256 mismatch aborts startup** — immutable migration convention. Drift = bug. Log `filename + stored_sha + current_sha`; raise `MigrationError`. No "auto-heal" branch.
2. **psycopg2, not SQLAlchemy** — matches `config/settings.py` + `kbl/db.py` pattern. Direct `psycopg2.connect(database_url)`; short-lived; close in finally.
3. **Runs BEFORE `kbl_pipeline_tick` registers in APScheduler** — ordering is the whole point. Test enforces (see Test #5).
4. **Per-file transaction** — one file = one `BEGIN` / `COMMIT`. On any SQL error: `ROLLBACK`, log, raise. Never insert a `schema_migrations` row for a file that didn't fully apply.
   - **Corollary (N3 — CREATE INDEX CONCURRENTLY footgun):** migration SQL MUST be transactional. No `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER TYPE … ADD VALUE` (pre-PG12), or other implicit-commit / outside-txn DDL. `CREATE INDEX CONCURRENTLY` in particular will raise `active SQL transaction` under our per-file `BEGIN`. If a concurrent-index build is genuinely needed (large table, writes-blocking risk), author it as an out-of-band SQL + document in the PR description; do NOT route through this runner. Same for any future non-concurrent `CREATE INDEX` on a large table — it locks writes for the build duration; runner doesn't enforce concurrency (that is migration-author discipline), but this brief flags the gotcha for the author-checklist in a future `docs/ops/migrations_conventions.md`.
5. **Abort startup on any migration error** — do not swallow. The existing inline DDL block swallows (line 395-397); the new runner must not mirror that pattern. Exception: the advisory-lock `pg_try_advisory_lock` timeout path WARNs and returns gracefully (see #7); all other failures raise.

### Added by R1 — concurrency contract

6. **Connection lifecycle** — the runner opens its OWN connection, not via `_get_store()` / `store._get_conn()`. Reason: `SentinelStoreBack` drags in Qdrant/Voyage bootstrap; runner must be independent so a migration failure doesn't mask as a Qdrant failure. Same rationale as `kbl/db.py:1-9`.

7. **Cross-process serialization via `pg_try_advisory_lock`.** Render can spin a new instance up before the old one drains during rolling deploys — for a brief window two startup hooks run concurrently, both claiming `run_pending_migrations` ownership. `schema_migrations.filename` is PK so the second INSERT fails with unique-violation, but by then BOTH processes have executed the DDL. Most current migrations are `IF NOT EXISTS`-safe; future ones may not be (e.g., a `DROP CONSTRAINT … ADD CONSTRAINT` sequence that races).

   Runner takes a session-level advisory lock before reading `_applied_set`, releases after the apply loop:

   ```python
   # Constant lock key — mnemonic "Baker migrations v1". Document in module docstring.
   _MIGRATION_LOCK_KEY = 0x42BA4E00001  # stays within int8 range; never collide with ad-hoc locks.

   # Try with ~30s budget. pg_try_advisory_lock is non-blocking; loop-poll with short sleep.
   import time
   deadline = time.monotonic() + 30.0
   acquired = False
   while time.monotonic() < deadline:
       cur.execute("SELECT pg_try_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))
       if cur.fetchone()[0]:
           acquired = True
           break
       time.sleep(0.5)

   if not acquired:
       logger.warning(
           "migration runner could not acquire advisory lock within 30s; "
           "another replica is mid-apply. Continuing startup without running migrations."
       )
       return []  # graceful degrade — sibling replica will finish; we boot with their applied state.

   try:
       # ... full apply loop here ...
   finally:
       cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
   ```

   Held only for the duration of the apply loop (seconds, not minutes). Rationale for `pg_try_advisory_lock` + timeout over blocking `pg_advisory_lock`: if a stuck sibling never releases (pathological — process killed mid-apply before `finally`), a blocking wait deadlocks the second replica's startup forever. Timeout + graceful exit means the blocked replica picks up the state the sibling leaves behind and boots. If the sibling also crashed without applying, a subsequent deploy picks up the still-pending files; the hole is at worst one deploy cycle wide.

   If Render stays single-instance (current Starter tier), this is a cheap safety net with zero overhead. If Baker ever scales out, the invariant holds automatically.

### Added by R3 — forward-compat section-marker requirement

8. **Section markers required for NEW migration files.** All migration files added **after MIGRATION_RUNNER_1 merges** MUST begin with `-- == migrate:up ==` on the first non-empty line and include a commented `-- == migrate:down ==` block for disaster-recovery manual rollback. The 2 currently marker-less files (`20260419_mac_mini_heartbeat.sql`, `20260419_add_kbl_cost_ledger_and_kbl_log.sql`) are **grandfathered** — treated by the runner as a single UP block (current behavior). CI test `test_migration_file_has_up_marker` (see Test #7) enforces the marker on all non-grandfathered files; grandfather list hardcoded with retirement date (remove no earlier than Phase 2 when the two files are rewritten with markers).

   The runner itself remains file-level — no UP/DOWN parse at runtime. The marker requirement is forward-compat hygiene for a future UP/DOWN parser and for `tests/test_migrations.py`-style round-trip tests.

---

## Test expectations (spec for B1 to implement under `tests/test_migration_runner.py`)

**Preamble — test fixture convention (N2).** Use the `TEST_DATABASE_URL`-gated pattern from `tests/test_migrations.py`, `tests/test_layer0_dedupe.py`, `tests/test_status_check_expand_migration.py`:

```python
import os, pytest
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
```

Tests run only when `TEST_DATABASE_URL` is set (Neon throwaway branch — NEVER production). Pure unit tests (sha256 compute, lex ordering, file-discovery, marker regex) run unconditionally. Do NOT use `testing.postgresql` / `pg_fixtures` — they are not in `requirements.txt`; match existing Baker convention.

---

1. **`test_migration_runner_applies_new_file`**
   - Fresh schema (throwaway) + one fixture file `tests/fixtures/migrations/001_noop.sql` with `CREATE TABLE test_noop (id INT)`.
   - Call `run_pending_migrations(TEST_DB_URL, "tests/fixtures/migrations")`.
   - Assert: `test_noop` exists, `schema_migrations` has one row with correct filename + sha256.

2. **`test_migration_runner_skips_applied`**
   - Pre-insert `schema_migrations` row for `001_noop.sql` with current sha256.
   - Run runner.
   - Assert: no error raised, return value is empty list, table `test_noop` is NOT re-created (verify by inserting a marker row before running; confirm still present after).

3. **`test_migration_runner_aborts_on_sha_mismatch`**
   - Pre-insert `schema_migrations` row with `sha256='deadbeef'` for `001_noop.sql`.
   - Run runner.
   - Assert: `MigrationError` raised, error message contains filename + both shas, DB state unchanged.

4. **`test_migration_runner_aborts_on_sql_error`**
   - Fixture file `002_bad.sql` containing `CREATE TABLE test_bad (id INT); SELECT nonexistent_function();`.
   - Run runner after a valid `001_noop.sql`.
   - Assert: `001_noop.sql` applies (table + schema_migrations row), then `002_bad.sql` fails → `MigrationError` raised, `test_bad` table does NOT exist (transaction rolled back), no `schema_migrations` row for `002_bad.sql`.

5. **`test_migration_runner_runs_before_scheduler`** (N1 — runtime fixture, not AST)

   Refactor `outputs/dashboard.py:startup()` into named helpers (`_init_store`, `_run_migrations`, `_start_scheduler`) as shown in §Scope.IN.3. Then:

   ```python
   from unittest.mock import patch, call
   @patch("outputs.dashboard._start_scheduler")
   @patch("outputs.dashboard._run_migrations")
   @patch("outputs.dashboard._init_store")
   async def test_migration_runner_runs_before_scheduler(m_init, m_migrate, m_start):
       from outputs.dashboard import startup
       await startup()
       # Assert ordering via call_args_list against a manager mock:
       manager = Mock()
       manager.attach_mock(m_init, "init")
       manager.attach_mock(m_migrate, "migrate")
       manager.attach_mock(m_start, "start")
       # ...re-run with manager wired; assert manager.mock_calls == [call.init(), call.migrate(), call.start()]
   ```

   ~8-12 lines. Survives black/ruff reformats. AST walk was fragile — lineno assertions shift on whitespace; async-function body walk is more code than the refactor itself.

6. **`test_migration_runner_first_deploy_idempotency_audit`** (R2 dry-run committed to test suite)

   Local dry-run command B1 runs before opening the PR (documented here so reviewers can reproduce):

   ```bash
   # Prereq: TEST_DATABASE_URL points at a Neon branch seeded to current-prod schema
   # (or a local Postgres db where all 11 migrations have been psql-applied once).
   # The branch must NOT have a schema_migrations table.
   python -c "
   import os
   from config.migration_runner import run_pending_migrations
   applied = run_pending_migrations(os.environ['TEST_DATABASE_URL'])
   assert len(applied) == 11, f'expected 11 retroactive claims, got {len(applied)}'
   for f in applied: print(f'  ✓ {f}')
   "
   ```

   Expected: all 11 files apply clean (re-run against already-applied state), 11 rows inserted, exit 0. Any error here is a blocker — it means one of the existing 11 is NOT idempotent and must be hardened before this runner ships.

   Automate as a pytest: skip unless `TEST_DATABASE_URL` is set AND `migrations/` has ≥11 files; assert returned list includes all 11 grandfathered filenames + `schema_migrations` row count matches.

7. **`test_migration_file_has_up_marker`** (R3 — forward-compat CI gate)

   Pure unit test, runs unconditionally:

   ```python
   import pathlib, re
   _UP_MARKER = re.compile(r"^\s*--\s*==\s*migrate:up\s*==\s*$", re.MULTILINE)
   _GRANDFATHERED = {
       # Remove no earlier than Phase 2 — rewrite these two with markers first.
       "20260419_mac_mini_heartbeat.sql",
       "20260419_add_kbl_cost_ledger_and_kbl_log.sql",
   }
   def test_migration_file_has_up_marker():
       mig_dir = pathlib.Path("migrations")
       for p in sorted(mig_dir.glob("*.sql")):
           if p.name in _GRANDFATHERED:
               continue
           content = p.read_text()
           assert _UP_MARKER.search(content), (
               f"{p.name} missing '-- == migrate:up ==' marker on any line. "
               f"All NEW migrations must include UP/DOWN section markers."
           )
   ```

   Fails CI if any non-grandfathered file lacks the marker. When the 2 grandfathered files are rewritten, remove from `_GRANDFATHERED` in the same PR.

8. **`test_second_instance_blocks_on_advisory_lock`** (R1 — concurrency contract)

   Simulates two-instance race via two psycopg2 connections:

   ```python
   def test_second_instance_blocks_on_advisory_lock():
       import psycopg2, threading
       from config.migration_runner import _MIGRATION_LOCK_KEY, run_pending_migrations

       # Hold the lock from a sidecar connection (simulates sibling replica mid-apply).
       blocker = psycopg2.connect(TEST_DB_URL)
       blocker.autocommit = True
       with blocker.cursor() as cur:
           cur.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))

       # Monkeypatch the 30s timeout down to 2s for test speed.
       with patch("config.migration_runner._LOCK_TIMEOUT_SECONDS", 2.0):
           result = run_pending_migrations(TEST_DB_URL, "tests/fixtures/migrations")
       assert result == []  # graceful degrade — empty list, no exception

       # Cleanup: release sidecar lock.
       with blocker.cursor() as cur:
           cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
       blocker.close()
   ```

   Asserts the `pg_try_advisory_lock` timeout path returns `[]` gracefully (with a WARN log) rather than raising `MigrationError`. Also: assert no rows in `schema_migrations` after the blocked call — proves no DDL ran under the lock contention.

Timeline budget for tests: ~40 min. Reuse `TEST_DATABASE_URL` fixture idioms from `tests/test_migrations.py`.

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
- **Inv 9 (extended by analogy):** Mac Mini is the single AGENT writer for signals (literal Inv 9 per `memory/MEMORY.md` → `project_mac_mini_role.md`). By analogy, Render is the single SCHEMA writer for migrations. Mac Mini poller does not call the runner; the `pg_try_advisory_lock` additionally serializes within Render itself. Respected.
- **Inv 10:** untouched — no prompt files.

---

## Timeline estimate for B1

- `config/migration_runner.py` (~110 lines incl. advisory lock + column-drift check) — ~40 min.
- `outputs/dashboard.py` integration (refactor `startup()` into named sub-calls + wire `_run_migrations`) — ~15 min.
- `tests/test_migration_runner.py` (~220 lines, 8 tests) — ~40 min.
- Local dry-run audit against Neon branch pre-seeded to current-prod (Test #6 in §5) — ~15 min.
- Local run + green CI + CHANDA self-check — ~10 min.
- **Total: ~110-130 min.** Slightly above task-brief estimate (~60-90 min); advisory lock + dry-run audit + marker CI test are the delta.

---

## Parking option (Director decides)

Two dispositions:

### (A) Ship now as polish PR — recommended
- Merge within 24-48 hours of tonight's go-live stabilizing.
- Covers every future migration automatically; no more "did B1 remember to apply it on Neon?"
- Low risk — startup-only code path, covered by 8 tests, abort-loud semantics fail safely, advisory lock handles multi-instance boot races.

### (B) Park in `briefs/_future_optimization/`
- If tonight's go-live debugging is still eating Director cycles and any new PR feels like a distraction.
- Park cost: one more manual migration-apply cycle per future PR until unparked.
- If chosen, B3 moves this file to `briefs/_future_optimization/MIGRATION_RUNNER_1_BRIEF.md` + adds entry to that README per the parking convention.

**B3 recommendation: (A) ship now.** Tonight's hole is the exact symptom this runner prevents; parking it reopens the hole with every PR. Cost is ~110-130 min of B1 time + a B2 review cycle — small surface, small review.

---

## Dispatch back (B1, after impl lands on `main`)

> B1 MIGRATION_RUNNER_1 shipped — PR #<N> merged at <SHA>. `config/migration_runner.py` + `outputs/dashboard.py` startup refactor + 8 green tests. `schema_migrations` table auto-created on next Render deploy; runner will retroactively claim all 11 already-applied migrations (sha256 computed against on-disk files; local dry-run audit confirmed all 11 idempotent; if any drift in prod → fail loud, Director manually reconciles). `pg_try_advisory_lock` (key `0x42BA4E00001`) serializes concurrent boots with 30s timeout + graceful degrade.

---

*Authored 2026-04-19 by B3 per AUTHOR_BRIEF_MIGRATION_RUNNER_1 dispatch. v2 fold 2026-04-19 evening per MIGRATION_RUNNER_1_BRIEF_V2 dispatch (commit `91ae095`) folding B2 REDIRECT R1 + R2 + R3 + N1-N4. Reviewer: B2 (brief review, not PR review). Implementer: B1 post-ratification.*
