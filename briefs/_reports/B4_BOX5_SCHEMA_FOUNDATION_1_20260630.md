# B4 ship report — BOX5_SCHEMA_FOUNDATION_1

- **Brief:** `briefs/BRIEF_BOX5_SCHEMA_FOUNDATION_1.md`
- **PR:** #441 — https://github.com/vallen300-bit/baker-master/pull/441
- **Branch:** `box5-schema-foundation-1`
- **HEAD SHA:** `8ffd7901a93a211ac6b462707881448a743e7412`
- **Base:** `main` @ `a37e69f`
- **Dispatched by:** cowork-ah1 (bus #4730)
- **Date:** 2026-06-30

## What shipped
Box 5 Build Order 3-4, schema foundation only (no runner, no resolve logic). Pure additive schema + one gated seed script; columns inert until later briefs (C/D/E) write them. No deploy flag. Implemented exactly per the copy-pasteable brief.

**Part 1 — terminal-classification axis on `airport_tickets`**
- `orchestrator/airport_ticketing_bridge.py`: new `ensure_airport_ticket_terminal_columns(conn)` (placed right after `ensure_airport_ticket_table`) — 16 additive columns + dedicated `airport_tickets_terminal_status_check` over exactly 6 states (`DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED`). `VISIBLE_HOLD` excluded (locked #4677.7). DROP-then-ADD constraint for idempotent re-runs. Mirror-call added at the end of `ensure_airport_ticket_table`.
- `migrations/20260630_airport_tickets_terminal_columns.sql`: versioned mirror (migrate:up/down; down commented; no BEGIN/COMMIT — runner wraps).

**Part 2 — gated BB pilot seed**
- `scripts/seed_bb_pilot_registry.py`: one-off, idempotent, NOT auto-run. Calls #439's `register_project` to seed `BB-AUK-001` → `baden-baden-desk` / `matter_slug=annaberg`. **NOT executed by this build** (Director-gated).

**Tests**
- `tests/test_airport_terminal_columns.py` (live-PG): 16 columns present; 6-state CHECK exact + VISIBLE_HOLD absent + NULL-tolerant; live `status`/`check_in_outcome` CHECKs unchanged; 6 states + NULL accepted; out-of-set rejected (`CheckViolation`).
- `tests/test_project_registry.py` (+2): seed constants consistent (BB→baden-baden-desk); seed mechanism (one `BBAUK001` row, BB routing, idempotent).

## Acceptance criteria — all green
- **AC1** `py_compile` clean (bridge + seed script).
- **AC2** `pytest tests/test_project_registry.py tests/test_airport_terminal_columns.py tests/test_airport_ticketing_bridge.py` → **36 passed** live PG 16; **1 passed / 26 skipped** without `TEST_DATABASE_URL` (CI runs live).
- **AC3** `check_singletons.sh` OK; `check_applied_migrations.sh` OK (exit 0 — the new migration is not in the lock yet; the check only validates already-locked files, same as PR #440 shipped).
- **AC4** terminal CHECK: `VISIBLE_HOLD`/`BOGUS`/lowercase rejected (`CheckViolation`); the 6 states + NULL accepted.
- **AC5** migration + bootstrap mirror add the identical 16-column set + same 6 states (programmatically diffed — identical); live `status`/`check_in_outcome` axis unchanged.

## Literal pytest output (live, local PG 16)
```
tests/test_project_registry.py ................... (19; 1 pure + 18 live)
tests/test_airport_terminal_columns.py ........ (8 live)
tests/test_airport_ticketing_bridge.py ......... (9)
36 passed, 1 warning in 0.40s
```
Without `TEST_DATABASE_URL`: `1 passed, 26 skipped` (only the pure seed-constants test runs).

## Done-rubric machine-checks
- 16 terminal columns present (`information_schema` — test-asserted).
- `airport_tickets_terminal_status_check` = exactly 6 states; `VISIBLE_HOLD` absent; NULL-tolerant (`pg_get_constraintdef` confirmed).
- Two live CHECKs byte-unchanged: bridge diff has **zero deletions**; `status` = `candidate/sent/failed/checked_in/rejected`, `check_in_outcome` = the 6 outcome tokens (confirmed via `pg_get_constraintdef`).
- Two-place mirror in sync: 16 columns identical (`diff` empty) + same 6-state enum in both the ensure fn and the migration.
- Seed NOT auto-run: `git grep` finds no boot/startup call site (only the def + docs).

## Verification SQL (run against scratch PG 16)
```
airport_tickets_terminal_status_check => CHECK ((terminal_status IS NULL) OR (terminal_status = ANY (ARRAY['DUPLICATE','REJECT_NOISE','REJECT_LOW_RELEVANCE','FAST_TICKET','TICKET','FILE_UNSORTED'])))
airport_tickets_status_check          => CHECK (status = ANY (ARRAY['candidate','sent','failed','checked_in','rejected']))     [UNCHANGED]
airport_tickets_check_in_outcome_check=> CHECK ((check_in_outcome IS NULL) OR (... 'VALID','FAKE','DUPLICATE','WRONG_TERMINAL','URGENT','NEEDS_LUGGAGE_READ'))  [UNCHANGED]
```

## Deviations from brief
- **Did NOT run the seed** (brief's Verification suggests a scratch-DB run; the dispatch envelope says "DO NOT RUN the seed" — envelope wins). Seed correctness is proven by the mechanism test (fixture-vault slug stands in for `annaberg`, same validation path, CI-safe) + the constants test + the live confirmation that `annaberg` is canonical (slugs.yml v23). The literal `annaberg` run is the separate Director-gated step.
- Seed script uses the brief's direct `register_project` call shape (not the existing `seed_bb_pilot`), per the brief's stated decision.

## Ops follow-up (NOT part of this PR)
After the migration applies to prod on boot, refresh `migrations/applied_migrations.lock` via `DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py` (repo SOP; `start.sh` pre-flight refuses to boot on drift).

## Done-state
Build-done only (PR merged + AC1–AC5 green + migration applies clean on boot). No deploy flag (pure additive schema). Seed execution is a separate Director-gated step.

## Gate chain
G1 (builder, done) → codex G3 (bus, effort medium) → lead G4 `/security-review` → lead merge.
