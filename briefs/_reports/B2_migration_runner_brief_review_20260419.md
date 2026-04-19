# B2 MIGRATION_RUNNER_1 brief review — REDIRECT (minor folds, ship after)

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (evening)
**Target brief:** `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md` @ `cd0cdfe`
**Task mailbox:** `briefs/_tasks/CODE_2_PENDING.md` @ `4658c0c` (Task 1)
**Verdict:** **REDIRECT — 3 must-fix folds + 4 N-level nits. None are structural; B3 can fold in ~15 min; then APPROVE on re-review or AI Head waves through on second pass.**

The brief is architecturally sound — module location, connection independence, integration point, Mac-Mini exclusion, and sha256-drift semantics are all correct choices. The folds below close real gaps the brief surfaces itself but doesn't fully answer (concurrency, first-boot behavior) plus one convention-drift item I found by scanning the existing migration files.

---

## Summary of folds

| # | Severity | Topic | Location to edit |
|---|----------|-------|-------------------|
| R1 | must-fix | Concurrency contract (two-instance race) | new §"Hard constraints #7" + 1 line in §Why |
| R2 | must-fix | First-deploy retroactive-claim behavior | new §"First deploy behavior" before §Rollback |
| R3 | must-fix | `-- == migrate:up ==` section-marker convention | new bullet in §Scope.IN.1 + 1-line in §OUT |
| N1 | nice-to-have | Test #5 AST fragility — force the refactor | §Test expectations #5 |
| N2 | nice-to-have | `TEST_DATABASE_URL` test-fixture convention | §Test expectations preamble |
| N3 | nice-to-have | `CREATE INDEX CONCURRENTLY` future-proof note | new line in §Hard constraints #4 |
| N4 | nice-to-have | `schema_migrations` schema-drift defense | §Scope.IN.2 |

---

## R1 — Concurrency contract missing (must-fix)

**Gap.** The brief's review focus explicitly asks "two services starting simultaneously — does the runner handle the race?" but the brief itself doesn't answer it. Hard-constraint #6 covers per-file connection lifecycle; nothing covers cross-process safety.

**Why it matters.** Render can spin a new instance up before the old one fully drains during rolling deploys — for a brief window you have two startup hooks running concurrently, both claiming `run_pending_migrations` ownership. `schema_migrations.filename` is PK so the second INSERT will fail with a unique-violation, but by then BOTH processes have already executed the DDL. Most of the current 10 migrations are `IF NOT EXISTS`-safe for re-run, but not all DDL stays re-entrant (e.g., `DROP CONSTRAINT … ADD CONSTRAINT` sequences can race; `ALTER COLUMN TYPE` can deadlock). Future migrations are a bigger unknown.

**Fold.** Add a Hard-constraint #7:

> **7. Cross-process serialization.** Runner takes a session-level advisory lock before reading `_applied_set`:
> ```python
> cur.execute("SELECT pg_advisory_lock(%s)", (0x4B424C5F4D494752,))  # 'KBL_MIGR' packed
> try:
>     ...apply loop...
> finally:
>     cur.execute("SELECT pg_advisory_unlock(%s)", (0x4B424C5F4D494752,))
> ```
> Two processes starting simultaneously will serialize — second waits for first to release. Lock is held only for the duration of the apply loop (seconds, not minutes), so a blocked second process either inherits the applied state and skips everything (typical) or picks up a newly added file (rare). If Render is guaranteed single-instance for this service (current Starter tier), the lock is a cheap safety net with zero overhead; if Baker scales out, the invariant holds automatically.

If B3/B1 prefer (a) "document single-instance assumption only" over (b) "advisory lock," that's also defensible — but the brief MUST pick one and write the rationale. Leaving it silent means B1 makes the call unwritten, and the next person to scale Baker inherits a landmine. My preference: ship the advisory lock. 4 lines of code, no perf cost, cheap insurance.

---

## R2 — First-deploy retroactive-claim behavior not documented (must-fix)

**Gap.** The brief's dispatch-back line is the ONLY place that mentions "retroactively claim all 9 already-applied migrations." The brief body is silent on what happens on first-deploy-after-runner-ships. A reader has to infer that:

1. Runner boots against production Neon.
2. `schema_migrations` table doesn't exist → runner creates it.
3. `_applied_set()` returns `{}`.
4. Runner finds **11 files** on disk (10 from PRs #8–#16 + the new `20260419_add_kbl_cost_ledger_and_kbl_log.sql` that B1 applied tonight), all showing as "pending."
5. Runner re-runs all 11 in lex order, expects every single one to no-op safely, inserts 11 rows.

Step 5 is load-bearing. If ANY of the 11 existing files is non-idempotent under re-run against the current production state, first-deploy-with-runner crashes startup and Baker goes dark. The brief hand-waves "runner will retroactively claim" without committing B1 to an idempotency audit.

**Fold.** Add a new §"First deploy behavior" subsection (place before §Rollback):

> ### First deploy behavior — retroactive claim of 11 existing files
>
> On first Render deploy after this runner ships, `schema_migrations` is empty. Runner will attempt to apply all 11 files currently under `migrations/` against production Neon (which already has all 11 applied via manual psql tonight). Every file MUST be idempotent under re-run — verified by AI Head's Tier-B apply tonight (all 11 files ran clean with `ON_ERROR_STOP=1`, zero errors, zero duplicates). Post-apply state is the reference.
>
> B1 MUST verify idempotency BEFORE merging by running the runner locally against a Neon branch pre-seeded to current-prod state (no `schema_migrations` rows, all tables/columns present). Expected behavior: all 11 files apply clean, 11 rows inserted into `schema_migrations`, zero errors.
>
> Files currently expected on boot-after-merge:
> 1. `20260418_expand_signal_queue_status_check.sql` — DROP CONSTRAINT IF EXISTS … ADD CONSTRAINT (re-entrant, verified 34 values tonight)
> 2. `20260418_loop_infrastructure.sql` — CREATE TABLE IF NOT EXISTS ×3 + signal_queue.id→BIGINT upgrade (ALTER is no-op when already BIGINT)
> 3. `20260418_step1_signal_queue_columns.sql` — ADD COLUMN IF NOT EXISTS
> 4. `20260418_step2_resolved_thread_paths.sql` — ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS
> 5. `20260418_step3_signal_queue_extracted_entities.sql` — ditto
> 6. `20260418_step4_signal_queue_step5_decision.sql` — ADD COLUMN IF NOT EXISTS
> 7. `20260419_mac_mini_heartbeat.sql` — CREATE TABLE IF NOT EXISTS
> 8. `20260419_step5_signal_queue_opus_draft.sql` — ADD COLUMN IF NOT EXISTS + CREATE TABLE IF NOT EXISTS kbl_circuit_breaker + INSERT ON CONFLICT DO NOTHING (seed row)
> 9. `20260419_step6_kbl_cross_link_queue.sql` — CREATE TABLE IF NOT EXISTS + indexes
> 10. `20260419_step6_signal_queue_final_markdown.sql` — ADD COLUMN IF NOT EXISTS
> 11. `20260419_add_kbl_cost_ledger_and_kbl_log.sql` — CREATE TABLE IF NOT EXISTS ×2 + indexes
>
> **Idempotency invariant for all future migrations:** every file MUST run cleanly against an already-applied state. Use `IF NOT EXISTS` / `DROP … IF EXISTS` / `INSERT ON CONFLICT DO NOTHING` / `ALTER COLUMN … IF EXISTS` throughout. This belongs in a future `docs/ops/migrations_conventions.md` (out of scope for B1).

This fold does three things the brief currently skips: names the exact 11 files, commits B1 to a local dry-run, and makes idempotency an explicit forward-looking invariant.

---

## R3 — `-- == migrate:up ==` section-marker convention unaddressed (must-fix)

**Finding.** 9 of the 11 migration files on disk use the `-- == migrate:up ==` / `-- == migrate:down ==` section-marker convention parsed by `tests/test_migrations.py:35-80` (regex `^--\s*==\s*migrate:(up|down)\s*==\s*$`). The DOWN section ships commented-out for disaster recovery. The 2 files WITHOUT markers:

- `20260419_mac_mini_heartbeat.sql` (B3's launchd provisioning file)
- `20260419_add_kbl_cost_ledger_and_kbl_log.sql` (tonight's hotfix file)

**Why it matters.** The brief's proposed runner reads the file and passes it whole to `cur.execute(sql)`. For files WITH markers, the DOWN section is itself comment lines (`--` prefix) so psycopg2 will skip them — harmless. For files WITHOUT markers, the whole file runs as UP. Both work today.

BUT: the brief doesn't pick a convention. A future reader of the runner won't know whether section-parsing was a deliberate non-choice or an oversight. And `tests/test_migrations.py` explicitly parses the sections — there's already a Baker convention, just not universally applied.

**Fold.** Add a bullet in §Scope.IN.1 (`run_pending_migrations` behavior) and a corresponding §OUT line:

> **Section-marker handling.** Runner reads each `.sql` file raw and passes the whole content to psycopg2 — no UP/DOWN section parsing. Rationale: the DOWN section in Baker convention is always commented-out (lines prefixed `-- `), so raw execution is safe regardless of markers. Parsing the markers is `tests/test_migrations.py`'s job (per-ticket test verifies UP+DOWN round-trip against a throwaway DB); the runtime runner treats markers as comments.
>
> **Convention to adopt going forward:** all new migration files SHOULD include the `-- == migrate:up ==` / `-- == migrate:down ==` markers so `tests/test_migrations.py`-style per-ticket tests can round-trip them. The 2 existing files without markers (`20260419_mac_mini_heartbeat.sql`, `20260419_add_kbl_cost_ledger_and_kbl_log.sql`) are grandfathered. Forward-fold into `docs/ops/migrations_conventions.md`.

---

## N-level observations (nice-to-have folds)

### N1 — Test #5 AST fragility: force the refactor

Brief §Test expectations #5 lets B1 pick between (a) `ast.parse` + tree walk on `dashboard.py:startup` body, and (b) refactor startup into named sub-calls. (a) is fragile — a black/ruff reformat that moves whitespace can shift lineno assumptions, and walking an async-function body to find two named function calls + assert order is more code than the refactor itself. (b) is both cleaner and faster to write. Flip the wording from "pick whichever lands cleaner" to "Preferred: refactor startup() into `_init_store()`, `_run_migrations()`, `_start_scheduler()` and unit-test call order via `unittest.mock.patch`. AST walk fallback only if refactor hits unforeseen issue."

### N2 — Test fixture convention: `TEST_DATABASE_URL` env gate

Brief §Test expectations preamble says "use `pytest` + a per-test Postgres fixture (…`testing.postgresql` / `pg_fixtures` if present)." Neither library is in `requirements.txt`. Baker convention is already established — `tests/test_migrations.py`, `tests/test_layer0_dedupe.py`, `tests/test_status_check_expand_migration.py` all use `TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")` with `pytest.mark.skipif(not TEST_DB_URL, ...)`. B1 should match. Replace the preamble with:

> Use the `TEST_DATABASE_URL`-gated pattern from `tests/test_migrations.py` — tests only run when `TEST_DATABASE_URL` is set (Neon throwaway branch; NOT production). Pure unit tests (sha256 compute, lex ordering, file-discovery) run unconditionally.

### N3 — `CREATE INDEX CONCURRENTLY` future-proof note

Per-file-transaction shape (hard-constraint #4) breaks `CREATE INDEX CONCURRENTLY` (requires running OUTSIDE a transaction block). None of the 11 current migrations use it — future ones might. Add a line to §Hard constraints #4:

> Corollary: migration SQL MUST be transactional. No `CREATE INDEX CONCURRENTLY` or `VACUUM` or other implicit-commit DDL. If a concurrent-index build is genuinely needed, author it as a separate out-of-band SQL + document in the PR description; do NOT route through this runner.

### N4 — `schema_migrations` schema-drift defense

If `schema_migrations` exists from a prior ad-hoc bootstrap with different columns (unlikely but defensive), the runner's `CREATE TABLE IF NOT EXISTS` is a no-op that keeps the old shape. Missing `sha256` column = runtime error at first INSERT. Add a post-create assertion in §Scope.IN.2:

> After `CREATE TABLE IF NOT EXISTS schema_migrations …`, runner SELECTs `column_name FROM information_schema.columns WHERE table_name='schema_migrations'` and verifies `{filename, applied_at, sha256}` are all present. If not: raise `MigrationError("schema_migrations exists but is missing expected columns; drop and recreate manually")`.

---

## CHANDA pre-push — ✓ mostly correct, one clarification

The brief's CHANDA section is well-reasoned. One nit:

- **Inv 9 framing.** Brief writes "Inv 9: respected — Mac Mini poller does not call the runner; Render is the single schema writer." That's an EXTENSION of Inv 9, not Inv 9 itself. Inv 9 (per `memory/MEMORY.md` → `project_mac_mini_role.md`) is "single AGENT writer" — Mac Mini owns Step 7 signal commits, not Render. The schema-writer-singleton argument is an analogy, not literal Inv 9. Rewrite as: "Inv 9 extended by analogy: as Mac Mini is the single AGENT writer for signals, Render is the single SCHEMA writer for migrations. Mac Mini poller does not call the runner."

---

## What's right (rolled forward — no fold needed)

- **Module location `config/migration_runner.py`** ✓ correct. `config/settings.py` is the existing co-location; `kbl/` would imply KBL-only scope (runner covers non-KBL like `loop_infrastructure.sql`); `triggers/` is scheduling-only.
- **Connection independence via `psycopg2.connect(DATABASE_URL)`** ✓ mirrors `kbl/db.py:27` exactly. Bypassing `_get_store()` avoids Qdrant/Voyage bootstrap drag AND avoids masking migration failures as Qdrant failures. Correct call.
- **Integration point — insert between store-init and `start_scheduler()`** ✓. `triggers/embedded_scheduler.py:557` registers `kbl_pipeline_tick` inside `start_scheduler()`; migrations must complete before that job registers or the first tick hits a partial schema.
- **sha256 mismatch aborts startup** ✓ + rollback path via `DELETE FROM schema_migrations WHERE filename='…'` documented. Matches Baker's forward-only convention.
- **Per-file transaction (one BEGIN / one COMMIT)** ✓ not "batch-all-9-into-one-txn." Mirrors AI Head's tonight-apply pattern (per-file `ON_ERROR_STOP=1`).
- **Abort-loud semantics** ✓ explicitly contrasted against the existing inline-DDL-swallow pattern at `outputs/dashboard.py:395-397`. That contrast is the whole reason this runner exists.
- **Mac Mini poller opt-out** ✓ stated twice (§Scope.5 + docstring injection at top of `config/migration_runner.py`). Good defensive documentation.
- **Inline DDL decomm = follow-up brief** ✓ scope boundary is defensible. `structured_actions` column ALTER, `people_issues`, `ideas`, `generated_documents`, and the now-redundant `kbl_cost_ledger`/`kbl_log` inline DDL in `memory/store_back.py:6505-6589` are all fold-into-later-brief material. Good separation of concerns. The current runner fixes the *process*; a follow-up brief fixes the *inventory*.
- **Dispatch-back one-liner** ✓ cleanly identifies the behavioral invariant — "runner will retroactively claim all 9 already-applied migrations" — though R2 asks this be expanded in the body, not just the one-liner.
- **Director-ratified ship-now path** ✓ — brief correctly flags (A) as the recommendation, (B) as the fallback. Consistent with AI Head's tonight-fire directive.

---

## Re-review protocol

On B3 fold-in:
1. B3 updates `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md` with R1 + R2 + R3 (+ optionally N1-N4).
2. B3 commits as `brief(B3): fold B2 review — MIGRATION_RUNNER_1`.
3. AI Head routes to B2 for re-review (should be ~5 min — delta-only read) OR waves through if all 3 R-items landed verbatim per this report.
4. On APPROVE: AI Head dispatches B1 for impl (~60-90 min per brief estimate).

---

## Dispatch

> **REDIRECT (minor).** Brief is architecturally sound — module location, conn independence, startup integration, sha256-drift semantics, Mac-Mini exclusion all correct. Three folds needed before B1 starts: (R1) concurrency contract — pick advisory lock OR document single-instance assumption; (R2) first-deploy retroactive-claim behavior — new §First deploy behavior section listing the 11 files expected at boot-after-merge + committing B1 to local dry-run idempotency audit; (R3) section-marker convention — state explicitly that runner reads files whole (no UP/DOWN parse), grandfather the 2 marker-less files, require markers going forward. Four N-level nits (test fixture convention, AST→refactor, CONCURRENTLY footgun, schema_migrations drift defense) are optional polish.
>
> Report: `briefs/_reports/B2_migration_runner_brief_review_20260419.md`. AI Head routes to B3 for fold-in (~15 min); I re-review on next pass or wave-through if R1-R3 land verbatim.
