# BRIEF: BOX5_SCHEMA_FOUNDATION_1 — airport_tickets terminal-status columns + BB pilot registry seed

## Context

Box 5 (Airport / terminal-classification layer) Build Order **3-4 = SCHEMA FOUNDATION ONLY**. This brief lays the two pieces of schema/data foundation that the later Box 5 briefs write to; it adds **no behavior, no runner, no resolve logic**.

- **Part 1** — additive terminal-status columns + a dedicated `terminal_status` CHECK on `airport_tickets`. These are the columns the classification **runner (BRIEF-C)** and the **fast lanes (BRIEF-D/E)** will *write* later. BRIEF-B only *creates* them.
- **Part 2** — seed the first scheduled-flight row (`BB-AUK-001`) into the `project_registry` table that **PR #439 (`PROJECT_NUMBER_REGISTRY_1`, squash `8284537`) shipped — MERGED + LIVE on `origin/main`** (HEAD `f7b3250` at brief time). This brief consumes #439's `register_project`; it does **not** reimplement registry logic.

This is the foundation BRIEF-C/D/E build on:
- BRIEF-C (runner) writes `terminal_status` + the result fields this brief creates.
- BRIEF-D/E (fast lanes) write `terminal_status='FAST_TICKET'` / `'TICKET'` etc. and the provenance fields.
- The BB pilot row this brief seeds is the first registered project the hard-lane resolver (`resolve_project_number`, already in #439) can match against.

**Locked second-pair review blockers carried into this brief (do not relitigate):**
- **Blocker 2 — orthogonal axis.** `terminal_status` is a **third, independent axis**. It is NOT the live `status` lifecycle (`candidate/sent/failed/checked_in/rejected`) and NOT `check_in_outcome` (`VALID/FAKE/…`). Do **not** expand either of those two CHECKs. New column, new CHECK only.
- **Blocker 3 — `CREATE TABLE IF NOT EXISTS` does not migrate a populated prod table.** The terminal columns therefore MUST land via the additive-`ALTER` idiom, mirrored **both** inline in the boot-time `ensure_*` path **and** as a versioned `migrations/` file (Lesson #50 migration-vs-bootstrap drift). Precedent: `memory/store_back.py:_ensure_signal_queue_additions` + `migrations/20260418_expand_signal_queue_status_check.sql`.
- **Blocker 5 — `VISIBLE_HOLD` deliberately excluded (locked decision #4677.7).** The `terminal_status` enum is **exactly 6 states**; `VISIBLE_HOLD` is intentionally NOT one of them. It gets its own owner + TTL + escalation + sweep brief later; adding it to the enum now would make it prematurely writable. Document the exclusion in code + migration.

### Surface contract: N/A — backend schema migration + one registry seed row, no clickable UI surface.

### Harness V2

**Context Contract.**
- **Inputs:** a live psycopg2 `conn` (boot path passes one to the `ensure_*` functions; the seed runner opens its own via `kbl.db.get_conn`). `slug_registry` loaded from `$BAKER_VAULT_PATH/slugs.yml` (v23). `kbl/project_registry_store.py` public API (from #439, unchanged by this brief).
- **Outputs:** (Part 1) `airport_tickets` gains 16 nullable columns + 1 new CHECK constraint `airport_tickets_terminal_status_check`. (Part 2) `project_registry` gains exactly one row keyed `match_key='BBAUK001'`.
- **Side-effects:** DDL on `airport_tickets` (additive only); one idempotent upsert into `project_registry`. No writes to any other table. No bus posts. No email. No ClickUp.
- **Idempotency invariants:**
  - `ensure_airport_ticket_terminal_columns` is safe to call on every boot: `ADD COLUMN IF NOT EXISTS` per field; `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT` for the CHECK (clean re-run).
  - The migration file is additive + idempotent (`ADD COLUMN IF NOT EXISTS` / `DROP…IF EXISTS`+`ADD`) and immutable once applied (sha256 ledger).
  - The seed is an `ON CONFLICT (match_key) DO UPDATE` upsert (via #439's `register_project`); re-running yields the same single row.

**Task class:** additive schema migration + idempotent seed.

**Done rubric (machine-checkable):**
1. `airport_tickets` has a column `terminal_status TEXT` (nullable) — `\d airport_tickets` shows it.
2. Constraint `airport_tickets_terminal_status_check` exists and permits **exactly 6** states: `DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED` — `grep`/`pg_get_constraintdef` count = 6, and `'VISIBLE_HOLD'` does **NOT** appear in the constraint def.
3. The CHECK is written `terminal_status IS NULL OR terminal_status IN (...)` so existing populated rows pass (no row violates it).
4. The 15 result/provenance columns exist: `terminal_reason, project_code, matter_slug, desk_owner, source_refs, confidence, model_used, cost_tier, classification_version, registry_version, manifest_match_signals, raw_source_table, raw_source_id, processed_at, terminal_outcome_written_at`.
5. **`airport_tickets_status_check` is UNCHANGED** (`candidate/sent/failed/checked_in/rejected`) — byte-identical to `origin/main`.
6. **`airport_tickets_check_in_outcome_check` is UNCHANGED** (`VALID/FAKE/DUPLICATE/WRONG_TERMINAL/URGENT/NEEDS_LUGGAGE_READ`) — byte-identical to `origin/main`.
7. The new ensure function is mirrored in **two** places: inline-callable from `ensure_airport_ticket_table` AND as `migrations/20260630_airport_tickets_terminal_columns.sql`; the column set + 6-state enum are identical in both.
8. After seeding, `SELECT count(*) FROM project_registry WHERE match_key='BBAUK001'` = 1; row has `desk_code='BB'`, `desk_owner='baden-baden-desk'`, `project_number='BB-AUK-001'`, `status='active'`.
9. The seed is **NOT** auto-run on boot: `git grep` finds no call to the seed in any boot/bootstrap/startup path; it is reachable only via the explicit one-off gate this brief adds.
10. `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True)"` and the seed script both compile clean; existing airport-bridge + project-registry tests pass.

**Gate plan:**
- **G1 — builder self-check.** Compile-clean both touched modules; run `pytest tests/test_project_registry.py -v` + any `airport_ticketing` tests; run the Verification SQL (below) against a scratch/test DB; confirm Done rubric 1-10.
- **G3 — codex review.** `bus_post.sh codex` for verdict before merge (codex = default deputy). Codex confirms: 6-state enum, `VISIBLE_HOLD` absent, two-place mirror in sync, status/check_in_outcome CHECKs untouched, seed not auto-run, additive-safe on populated table.
- **G4 — lead `/security-review` then lead merge.** AH1 (lead) runs `/security-review` on the diff (Tier-A-touching migration), then merges.
- **Migration application:** the new migration is **auto-applied on boot** by `config/migration_runner.py:run_pending_migrations` (invoked from `outputs/dashboard.py` startup; Render is the single schema writer). The inline `ensure_airport_ticket_terminal_columns` call re-asserts the constraint on every Render restart so the migration can't be silently reverted. **No feature flag** is needed for pure additive schema (nullable columns + a NULL-tolerant CHECK are inert until something writes them). The **seed is one-off / not auto-run** — gated behind an explicit script invocation (see Part 2). After prod-apply, refresh `migrations/applied_migrations.lock` per the repo SOP.

## Estimated time

2.5-4 hours (schema ALTER + mirrored migration + a thin gated seed runner + tests + Verification SQL). No behavioral code.

## Complexity

Low-Medium. The risk is entirely in the **mirror discipline** (inline ensure vs migration file must carry the identical column set + 6-state enum) and in **not touching** the two live CHECKs. No algorithmic complexity.

## Prerequisites

- **PR #439 `PROJECT_NUMBER_REGISTRY_1` — MERGED (squash `8284537`), LIVE on `origin/main`. Satisfied.** `project_registry` table + `register_project` / `seed_bb_pilot` / `ensure_project_registry_table` are present at `kbl/project_registry_store.py`.
- `slug_registry` available (`kbl/slug_registry.py`), `$BAKER_VAULT_PATH` pointing at the vault checkout (slugs.yml v23). Both `aukera` and `annaberg` confirmed canonical + active.
- Migration runner + ledger live (`config/migration_runner.py`, `migrations/applied_migrations.lock`).

---

## PART 1 — airport_tickets terminal-status columns + dedicated terminal_status CHECK

### Problem

Box 5 will classify each `airport_tickets` row into a terminal disposition and write the classification result + provenance back onto the row. Today `airport_tickets` has no column to hold that disposition, and its `CREATE TABLE IF NOT EXISTS` bootstrap will never add one to the already-populated prod table. We need the columns + a dedicated 6-state CHECK in place **before** the runner (BRIEF-C) can write anything. This brief creates the schema only.

### Current State (file:line from map, verified against `origin/main` f7b3250)

- `orchestrator/airport_ticketing_bridge.py:262` — `def ensure_airport_ticket_table(conn: Any) -> None`. `CREATE TABLE IF NOT EXISTS airport_tickets` with **four** existing CHECKs (verbatim from the file):
  - `airport_tickets_status_check CHECK (status IN ('candidate','sent','failed','checked_in','rejected'))`
  - `airport_tickets_source_channel_check CHECK (source_channel IN ('email','whatsapp','plaud','clickup','calendar','other'))`
  - `airport_tickets_urgency_check CHECK (urgency_hint IN ('low','normal','high','urgent'))`
  - `airport_tickets_check_in_outcome_check CHECK (check_in_outcome IS NULL OR check_in_outcome IN ('VALID','FAKE','DUPLICATE','WRONG_TERMINAL','URGENT','NEEDS_LUGGAGE_READ'))`
  - then two `CREATE INDEX IF NOT EXISTS` (`idx_airport_tickets_source`, `idx_airport_tickets_desk_status`). The function takes `conn` and uses `with conn.cursor() as cur:`; it does **not** commit internally (caller commits) — match the existing transaction handling of its caller.
- `migrations/20260629_airport_tickets.sql` — the baseline migration for this table. Body has **no** `BEGIN;`/`COMMIT;` (verified) — the runner wraps each file in its own transaction, so the new migration body must likewise omit `BEGIN/COMMIT`.
- `memory/store_back.py:7323` — `def _ensure_signal_queue_additions(self)` — **THE precedent idiom**: `ALTER TABLE … ADD COLUMN IF NOT EXISTS` per field, then `DROP CONSTRAINT IF EXISTS signal_queue_status_check` + `ADD CONSTRAINT … CHECK(...)`, `conn.commit()`. In-code comment requires it stay in sync with `migrations/20260418_expand_signal_queue_status_check.sql`.
- `migrations/20260418_expand_signal_queue_status_check.sql` — the versioned mirror (DROP/ADD CONSTRAINT with full enum; `-- == migrate:up ==` / `-- == migrate:down ==` markers; down-block commented).
- `config/migration_runner.py:190` — `run_pending_migrations(...)` applies `migrations/*.sql` in lex order on boot; records filename+sha256 in `schema_migrations`; sha256 drift on an applied file aborts startup (so the new file must never be edited after prod-apply).
- Migration naming convention: `YYYYMMDD[suffix]_<snake_desc>.sql`, lex-ordered. Latest is `20260629_airport_tickets.sql`. New file: `migrations/20260630_airport_tickets_terminal_columns.sql`.
- `kbl/slug_registry.py:174` — `registry_version() -> int` — source for the `registry_version` column (classification provenance; written later by C/D/E, not here).

### Engineering Craft Gates

- **Additive-safe on a POPULATED table** (Engineering Rule — fault-tolerant or it doesn't ship). Every new column is **nullable, no `NOT NULL`** except the two JSONB list columns which use the precedent `NOT NULL DEFAULT '[]'::jsonb` form (a default makes `NOT NULL` safe on existing rows). The CHECK is `terminal_status IS NULL OR terminal_status IN (...)` so existing rows (which have `terminal_status = NULL`) pass.
- **Two-place mirror is mandatory** (Lesson #50). The inline ensure function and the migration file MUST carry the identical 16-column set and identical 6-state enum.
- **Surface conflicts, don't average** — `terminal_status` is a new axis; do not blend it into `status`/`check_in_outcome`.
- **Fail loud** — if the column set or enum drifts between the two mirror locations, that is a defect, not a nit.

### Implementation

**Step 1 — new boot-time function in `orchestrator/airport_ticketing_bridge.py`, placed immediately AFTER `ensure_airport_ticket_table`** (signatures verified against `origin/main`):

```python
def ensure_airport_ticket_terminal_columns(conn: Any) -> None:
    """Additive terminal-classification axis on airport_tickets.

    CREATE TABLE IF NOT EXISTS does NOT migrate an already-created prod table,
    so we ALTER here and mirror migrations/20260630_airport_tickets_terminal_columns.sql
    verbatim (Lesson #50 migration-vs-bootstrap drift). Re-asserted on every Render
    restart so the migration can't be silently reverted.

    terminal_status is ORTHOGONAL to the live `status` lifecycle and to
    `check_in_outcome` — new axis, new column, new CHECK. Do NOT touch those two.

    All columns nullable (or NOT NULL with a list DEFAULT) -> safe on a populated
    table; no backfill required.
    """
    try:
        with conn.cursor() as cur:
            # Terminal-result fields written later by the runner (BRIEF-C) and the
            # fast lanes (BRIEF-D/E). BRIEF-B only creates the columns.
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_status TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_reason TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS project_code TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS matter_slug TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS desk_owner TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS confidence NUMERIC(3,2)")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS model_used TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS cost_tier TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS classification_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS registry_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_table TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_id TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_outcome_written_at TIMESTAMPTZ")

            # terminal_status CHECK — EXACTLY 6 states. VISIBLE_HOLD is DELIBERATELY
            # EXCLUDED (locked decision #4677.7): it gets its own owner + TTL +
            # escalation + sweep brief; adding it here would make it prematurely
            # writable. Do NOT "fix" this omission. DROP-then-ADD mirrors the
            # signal_queue precedent so re-runs are clean (idempotent).
            cur.execute("ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check")
            cur.execute(
                """
                ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_terminal_status_check
                    CHECK (
                        terminal_status IS NULL OR
                        terminal_status IN (
                            'DUPLICATE',
                            'REJECT_NOISE',
                            'REJECT_LOW_RELEVANCE',
                            'FAST_TICKET',
                            'TICKET',
                            'FILE_UNSORTED'
                        )
                    )
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

**Step 2 — mirror inline.** At the END of `ensure_airport_ticket_table(conn)`, AFTER the two `CREATE INDEX IF NOT EXISTS` calls and before the function returns, add a single line so a fresh DB created by the bootstrap path also gets the terminal columns AND so the constraint is re-asserted on every restart:

```python
    # Additive terminal-classification axis (BRIEF-B). Mirrors
    # migrations/20260630_airport_tickets_terminal_columns.sql. CREATE TABLE
    # IF NOT EXISTS above never migrates an existing prod table, so we ALTER here.
    ensure_airport_ticket_terminal_columns(conn)
```

(Module-level forward reference resolves at call time. If `ensure_airport_ticket_table`'s caller relies on a single outer commit, the inner `conn.commit()` is still safe — it commits the additive DDL; confirm the caller does not depend on rolling the table-create and the ALTERs back as one unit. They are independent additive operations.)

**Step 3 — paired migration `migrations/20260630_airport_tickets_terminal_columns.sql`** (no `BEGIN;`/`COMMIT;` in body — the runner wraps each file; matches `20260629_airport_tickets.sql`):

```sql
-- == migrate:up ==
-- AIRPORT_TICKETS_TERMINAL_COLUMNS_1 (BOX5_SCHEMA_FOUNDATION_1 / BRIEF-B):
-- additive terminal-classification axis on airport_tickets.
--
-- terminal_status is ORTHOGONAL to the live `status` lifecycle and to
-- `check_in_outcome` — do NOT expand either of those CHECKs. New axis only.
--
-- Mirror of orchestrator/airport_ticketing_bridge.ensure_airport_ticket_terminal_columns
-- — the two MUST stay in sync (Lesson #50). Additive + idempotent; all columns
-- nullable (or NOT NULL with a list DEFAULT) so it is safe on the already-
-- populated prod airport_tickets table.
--
-- 6-state terminal_status CHECK. VISIBLE_HOLD is DELIBERATELY EXCLUDED
-- (locked decision #4677.7) — it gets its own owner/TTL/escalation/sweep brief;
-- adding it now would make it prematurely writable. Do NOT add it.

ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_status TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_reason TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS project_code TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS matter_slug TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS desk_owner TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS confidence NUMERIC(3,2);
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS model_used TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS cost_tier TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS classification_version TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS registry_version TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_table TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_id TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_outcome_written_at TIMESTAMPTZ;

ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check;
ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_terminal_status_check
    CHECK (
        terminal_status IS NULL OR
        terminal_status IN (
            'DUPLICATE',
            'REJECT_NOISE',
            'REJECT_LOW_RELEVANCE',
            'FAST_TICKET',
            'TICKET',
            'FILE_UNSORTED'
        )
    );

-- == migrate:down ==
-- Disaster recovery only. Not auto-run (runner executes the whole file body;
-- keep rollback statements commented). To roll back manually:
-- ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_outcome_written_at;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS processed_at;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS raw_source_id;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS raw_source_table;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS manifest_match_signals;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS registry_version;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS classification_version;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS cost_tier;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS model_used;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS confidence;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS source_refs;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS desk_owner;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS matter_slug;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS project_code;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_reason;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_status;
```

**Step 4 — after prod-apply, refresh the lock.** Per repo SOP, run `DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py` so `migrations/applied_migrations.lock` records the new file's sha256. (The `start.sh` pre-flight `scripts/check_applied_migrations.sh` refuses to boot on drift.) Note this in the ship report; do not skip it.

### Key Constraints

- `terminal_status` CHECK = **exactly 6 states** (`DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED`). **`VISIBLE_HOLD` excluded — documented reason:** it requires its own owner + TTL + escalation + sweep semantics (locked #4677.7); adding it to the enum now makes it prematurely writable before that machinery exists.
- Additive ALTER must be safe on a **populated** table: nullable columns, no `NOT NULL` without a `DEFAULT`; the only `NOT NULL` columns are the two JSONB lists with `DEFAULT '[]'::jsonb`. CHECK is `IS NULL OR IN (...)`.
- New ensure function mirrored **inline in `ensure_airport_ticket_table`** AND as a **versioned `migrations/` file** matching `YYYYMMDD[suffix]_<slug>.sql`.
- Do **not** touch `airport_tickets_status_check` or `airport_tickets_check_in_outcome_check`.
- Migration body carries **no** `BEGIN;`/`COMMIT;` (runner wraps); down-block stays commented.
- All DB calls wrapped in `try/except`; every `except` calls `conn.rollback()` (shown above); DDL/ALTER statements are exempt from the LIMIT rule (no LIMIT on DDL).

### Verification

- `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True)"`.
- Against a scratch/test DB: run `ensure_airport_ticket_table(conn)` twice (idempotency), then run the Verification SQL below — confirm 16 new columns + the 6-state constraint + the two untouched CHECKs.
- Negative test: `INSERT … (terminal_status) VALUES ('VISIBLE_HOLD')` must FAIL the CHECK; `VALUES ('TICKET')` must succeed; `VALUES (NULL)`/omitting it must succeed.
- Confirm `git show origin/main:` diff for `airport_tickets_status_check` and `airport_tickets_check_in_outcome_check` shows **no change**.

---

## PART 2 — BB pilot registry seed (BB-AUK-001) via #439's register_project

### Problem

Box 5's hard-lane resolver (`resolve_project_number`, shipped in #439) only matches project numbers that are actually **registered**. The first scheduled-flight pilot — `BB-AUK-001`, the Baden-Baden / Aukera-financed project — must be seeded into `project_registry` so the resolver has something live to match. This brief seeds exactly that one row, idempotently, behind a one-off gate. No resolver logic, no runner.

### Current State (file:line from map, verified against `origin/main` f7b3250)

- `kbl/project_registry_store.py:54` — `ensure_project_registry_table(conn) -> None` — idempotent `CREATE TABLE IF NOT EXISTS project_registry`; commits internally.
- `kbl/project_registry_store.py:80` — `register_project(conn, *, project_number, desk_owner, matter_slug, clickup_list_id=None, participants=None, aliases=None) -> str`. Validates `matter_slug` via `slug_registry.is_canonical`; `fullmatch`es `DESK-MATTER-###`; derives `desk_code` from the prefix; **rejects any `desk_owner` that ≠ `DESK_CODES[desk_code]`** (prefix is authoritative). **No `desk_code` kwarg** — it is derived. Upsert is `ON CONFLICT (match_key) DO UPDATE` (idempotent). Returns canonical `project_number`.
- `kbl/project_registry_store.py:32-39` — `DESK_CODES` dict. `'BB' -> 'baden-baden-desk'` confirmed (also `AO/ao-desk, MOV/movie-desk, HAG/hagenauer-desk, BR/brisen-desk, ORIG/origination-desk`).
- `kbl/project_registry_store.py:298` — `seed_bb_pilot(conn) -> int` — **already exists, NOT auto-run** (zero call sites outside its own def). It seeds **one** row: `BB-AUK-001` / `desk_owner='baden-baden-desk'` / `matter_slug='annaberg'` / `clickup_list_id=None` / `participants=[{channel:'email', value:'balazs@brisengroup.com'}]` / `aliases=['annaberg','aukera annaberg']`. Its docstring flags `matter_slug` as a PLACEHOLDER. Idempotent (calls `register_project`).
- `kbl/slug_registry.py:188` (`is_canonical`), `:178` (`canonical_slugs`), `:183` (`active_slugs`) — both `aukera` and `annaberg` confirmed **canonical + active** (slugs.yml v23: `annaberg` = "Baden-Baden project vehicle; Aukera-financed alongside Lilienmatt"; `aukera` = "Senior Lender on MO Vienna; planned Senior Lender for Annaberg / Lilienmatt / MRCI").

### matter_slug resolution — `annaberg`, not `aukera` (surface, don't average)

The dispatching brief text said `matter_slug aukera (confirm canonical)`. **Resolved: use `matter_slug='annaberg'`**, with a one-line note that `AUK` is the **display mnemonic** in the project number, not the matter slug. Reasoning (surfaced per "don't average"):
- `BB-AUK-001` names a **Baden-Baden project vehicle**. `annaberg` IS that project (Aukera-financed). `aukera` is the **senior-lender counterparty**, a different matter.
- The already-merged `seed_bb_pilot` and the B4 author both chose `annaberg` — code and brief now agree on `annaberg`.
- Both slugs pass `is_canonical`, so this is a **semantics** choice, not a validation one. If the Director instead intends the flight to belong to the lender relationship, that is a deliberate override to flag before seeding — otherwise `annaberg` stands.

### Engineering Craft Gates

- **Use AI for judgment, not deterministic work** — N/A; this is deterministic. **Reuse, don't reimplement:** import and call #439's `register_project`; do **not** re-author registry insert/validation logic.
- **Idempotent + gated** — the seed is an upsert (re-runnable) and is reachable only via an explicit one-off invocation, never the boot path.
- **Fail loud** — if `register_project` raises (non-canonical slug, prefix/owner mismatch), let it raise; do not swallow.

### Implementation

**Decision: call `register_project` directly** from a thin gated runner — do **not** call the existing `seed_bb_pilot` as-is. Reason: `seed_bb_pilot` bundles a participant + aliases and is documented PLACEHOLDER; a direct, explicit call keeps the pilot row self-documenting and auditable, and reuses the exact same idempotent primitive. (If AH1 prefers, calling `seed_bb_pilot(conn)` behind the same gate is acceptable since it now also uses `matter_slug='annaberg'` — but the direct call below is the brief's chosen shape.)

**New one-off script `scripts/seed_bb_pilot_registry.py`** (explicit invocation only; NOT imported by any boot path):

```python
"""One-off, idempotent seed of the BB-AUK-001 pilot project into project_registry.

NOT auto-run. Invoke explicitly:  python3 scripts/seed_bb_pilot_registry.py
Re-runnable: register_project upserts on match_key, so repeated runs are no-ops.
"""
from kbl.db import get_conn  # verify this import path against the repo's conn helper
import kbl.project_registry_store as pr
import kbl.slug_registry as slug_registry

PROJECT_NUMBER = "BB-AUK-001"
DESK_OWNER = "baden-baden-desk"          # MUST equal DESK_CODES['BB']; desk_code is derived from the 'BB' prefix
MATTER_SLUG = "annaberg"                  # AUK is the display mnemonic, not the matter slug; annaberg = the BB project vehicle
CLICKUP_LIST_ID = None                    # no canonical Baden-Baden ClickUp list exists yet; backfill when provisioned
ALIASES = ["annaberg", "aukera annaberg"]


def main() -> int:
    # Fail loud before touching the DB if the slug isn't canonical.
    if not slug_registry.is_canonical(MATTER_SLUG):
        raise ValueError(f"matter_slug {MATTER_SLUG!r} is not canonical (slugs.yml)")
    try:
        with get_conn() as conn:
            pr.ensure_project_registry_table(conn)
            canonical = pr.register_project(
                conn,
                project_number=PROJECT_NUMBER,
                desk_owner=DESK_OWNER,
                matter_slug=MATTER_SLUG,
                clickup_list_id=CLICKUP_LIST_ID,
                aliases=ALIASES,
            )
            conn.commit()
            print(f"seeded/updated {canonical}")
        return 0
    except Exception:
        # get_conn() context manager may not roll back on its own; be explicit if a
        # conn is in scope. Re-raise so the operator sees the failure (fail loud).
        raise


if __name__ == "__main__":
    raise SystemExit(main())
```

(Builder: verify `kbl.db.get_conn` is the correct conn helper / context-manager shape used elsewhere in `kbl/`; if `get_conn()` is not a context manager, open/commit/rollback/close explicitly and `conn.rollback()` in the `except` before re-raising.)

### Key Constraints

- Seed exactly **one** row: `BB-AUK-001`, `desk_owner='baden-baden-desk'` (`desk_code='BB'` derived by `register_project`), `matter_slug='annaberg'`, `clickup_list_id=None`, `aliases=['annaberg','aukera annaberg']`.
- `matter_slug` MUST be canonical (`register_project` enforces; the script also pre-checks → fail loud).
- `desk_code` is **derived from the `BB` prefix** — never passed; `desk_owner` must equal `DESK_CODES['BB']` or `register_project` raises.
- **Idempotent** via `ON CONFLICT (match_key) DO UPDATE`.
- **NOT auto-run on boot** — explicit script invocation only; do not add a call site in any startup/bootstrap path.
- Import + call #439's `register_project`; do not reimplement registry logic.

### Verification

- Dry context: run the script against a scratch DB; `SELECT project_number, desk_code, desk_owner, matter_slug, status FROM project_registry WHERE match_key='BBAUK001' LIMIT 1` → exactly the row above, `desk_code='BB'`, `status='active'`.
- **Idempotency:** run the script twice; row count for `match_key='BBAUK001'` stays 1.
- **Not-auto-run proof:** `git grep -n "seed_bb_pilot_registry\|seed_bb_pilot" -- ':!tests' ':!scripts/seed_bb_pilot_registry.py'` returns no boot/startup caller.
- Negative: temporarily passing `desk_owner='movie-desk'` must raise `ValueError` (prefix authority); passing a non-canonical slug must raise.

---

## Files Modified

- `orchestrator/airport_ticketing_bridge.py` — add `ensure_airport_ticket_terminal_columns(conn)` after `ensure_airport_ticket_table`; add the single mirror-call line at the end of `ensure_airport_ticket_table`.
- `migrations/20260630_airport_tickets_terminal_columns.sql` — **new** versioned migration (mirror of the ensure function).
- `migrations/applied_migrations.lock` — refreshed after prod-apply (sha256 of the new file) via `scripts/refresh_applied_migrations_lock.py`.
- `scripts/seed_bb_pilot_registry.py` — **new** one-off gated seed runner.
- (Tests) extend `tests/test_project_registry.py` and/or add an `airport_ticketing` schema test asserting the 6-state CHECK + the two untouched CHECKs + seed idempotency.

## Do NOT Touch

- `airport_tickets_status_check` — the live `status` lifecycle CHECK (`candidate/sent/failed/checked_in/rejected`). Leave byte-identical.
- `airport_tickets_check_in_outcome_check` — the live check-in outcome CHECK (`VALID/FAKE/DUPLICATE/WRONG_TERMINAL/URGENT/NEEDS_LUGGAGE_READ`). Leave byte-identical.
- The existing `ensure_airport_ticket_table` column set + the two `CREATE INDEX` statements — do not reorder, retype, or drop any existing column.
- `kbl/project_registry_store.py` public API (`ensure_project_registry_table`, `register_project`, `resolve_project_number`, `resolve_by_participant`, `resolve_by_alias`, `seed_bb_pilot`, helpers) — import + call; do **not** edit signatures or reimplement registry logic.
- `migrations/20260629_airport_tickets.sql` and any other already-applied migration — never edit an applied file (sha256 drift aborts startup). New file only.
- `baker-vault/slugs.yml` — separate-repo, read-only here.
- `tasks/lessons.md` existing entries — append-only.

## Quality Checkpoints

1. **6-state enum, VISIBLE_HOLD absent** — `pg_get_constraintdef` for `airport_tickets_terminal_status_check` lists exactly the 6 states; `grep -c VISIBLE_HOLD` on the constraint def = 0; documented exclusion comment present in both mirror locations.
2. **Two-place mirror in sync** — column set (16) + 6-state enum identical in `ensure_airport_ticket_terminal_columns` and `migrations/20260630_airport_tickets_terminal_columns.sql`.
3. **Two live CHECKs untouched** — `git diff origin/main` shows no change to `airport_tickets_status_check` or `airport_tickets_check_in_outcome_check`.
4. **Additive-safe** — all new columns nullable except the two JSONB lists (`NOT NULL DEFAULT '[]'::jsonb`); CHECK is `IS NULL OR IN (...)`; existing rows pass.
5. **Migration hygiene** — file matches `YYYYMMDD[suffix]_<slug>.sql`; no `BEGIN/COMMIT` in body; down-block commented; lock refreshed post-apply.
6. **Seed correct + idempotent + not auto-run** — one `BB-AUK-001` row, `desk_code='BB'`, `matter_slug='annaberg'`; second run is a no-op; no boot caller.
7. **try/except + rollback** on every DB block; DDL/ALTER exempt from LIMIT.
8. **Gates clear** — G1 builder self-check → G3 codex verdict → G4 lead `/security-review` + merge.

## Verification SQL

```sql
-- 1. New terminal columns present (expect 16 rows). Bounded with LIMIT.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'airport_tickets'
  AND column_name IN (
    'terminal_status','terminal_reason','project_code','matter_slug','desk_owner',
    'source_refs','confidence','model_used','cost_tier','classification_version',
    'registry_version','manifest_match_signals','raw_source_table','raw_source_id',
    'processed_at','terminal_outcome_written_at')
ORDER BY column_name
LIMIT 20;

-- 2. terminal_status CHECK = exactly 6 states, VISIBLE_HOLD absent.
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname = 'airport_tickets_terminal_status_check'
LIMIT 1;

-- 3. The two live CHECKs are UNCHANGED (eyeball against origin/main defs).
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname IN ('airport_tickets_status_check', 'airport_tickets_check_in_outcome_check')
ORDER BY conname
LIMIT 5;

-- 4. Negative: VISIBLE_HOLD must violate the new CHECK (expect ERROR, then ROLLBACK).
-- BEGIN; INSERT INTO airport_tickets (ticket_id, dedup_key, source_channel, source_id,
--   proposed_desk_slug, terminal_status) VALUES ('vh-test','vh-test','email','x','baden-baden-desk','VISIBLE_HOLD');
-- ROLLBACK;

-- 5. BB pilot seed present, idempotent, correct desk routing.
SELECT project_number, desk_code, desk_owner, matter_slug, status
FROM project_registry
WHERE match_key = 'BBAUK001'
LIMIT 1;
```
