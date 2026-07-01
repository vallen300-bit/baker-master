# B4 Ship Report — BOX5_HARD_FAST_LANE_1 (D)

- **Brief:** BOX5_HARD_FAST_LANE_1 (Build Order 6) — project-number hard fast lane
- **PR:** #443 (`box5-hard-fast-lane-1` → `main`)
- **Head SHA:** 39671d6
- **Dispatched_by:** cowork-ah1 · **Ship report → cowork-ah1 · Gate verdicts → lead**
- **Date:** 2026-07-01
- **Status:** SHIPPED_AWAITING_GATES (G1 self-test green; awaiting codex G3 → lead G4 /security-review → lead merge)

## What shipped
One new precedence tier in C's merged `run_tick` between `(e)` DUPLICATE and `(f)` safe-default TICKET. Clean project-number clear → `terminal_status='FAST_TICKET'` via C's `write_terminal_status`; any conflict/no-code/no-row/no-binding/exception → falls through to C's unchanged TICKET.

Files:
- `kbl/project_registry_store.py` — net-new pure `extract_project_codes()` (reuses `_NUMBER_RE`, no DB, distinct first-occurrence order); `seed_bb_pilot` `matter_slug` `annaberg`→`aukera`.
- `orchestrator/airport_ticketing_bridge.py` — import `extract_project_codes`/`resolve_project_number`/`resolve_by_participant`; `fast_ticket` counter + stats key; the hard-lane branch.
- `scripts/seed_bb_pilot_registry.py` — `MATTER_SLUG` `annaberg`→`aukera` (+ stale docstring/comment).
- `tests/test_project_registry.py` — +2 pure-regex cases + flipped seed assertion.
- `tests/test_box5_ticketing_runner.py` — +6 branch cases.

## Adapted to C's MERGED structure (not the pre-merge draft)
The brief's `brief_c_draft.md` line refs were pre-merge. C shipped after 4 P1 re-gate fixes, so the merged `run_tick` uses a `done`/`contiguous`-prefix model, a **tuple** `_claim_for_terminal` return `(id, terminal_status)`, and no `continue`/`max_received`. D's branch therefore:
- lives at the **top of the safe-default `else`** behind a `handled` flag (not a `continue` + `max_received = _advance(...)`);
- uses `claim[1] is not None` to distinguish already-terminal (idempotent) from locked;
- only sees `ok=True` rows, because C now handles `bus_failed` as a failure **before** the safe-default branch — so the brief's flagged "bus_failed-on-fast-lane" edge (Key Constraint) does not arise in the merged structure.

## Done rubric (10 items)
1. `extract_project_codes` pure/no-DB/distinct, reuses `_NUMBER_RE` — ✅ (0 DB calls in body; no 2nd compiled pattern).
2. `re.compile` count unchanged from main (1) — ✅.
3. `>1` distinct code → TICKET (`if len(set(codes)) == 1` gate) — ✅ test 16.
4. Regex-only, unregistered → TICKET — ✅ test 13.
5. Participant-binding required (`any(h.project_number == pn)`) — ✅ tests 14 (bound) / 15 (unbound).
6. Conflict/no-row/no-binding → TICKET, **never VISIBLE_HOLD** — ✅ (see caveat below).
7. Only one `FAST_TICKET` write site, inside the `if bound:` arm — ✅ (grep count 1).
8. Entire branch under `if fast_lane and row_id:`; flag false → no-op — ✅ test 18.
9. Error → `failed` + fall through, never FAST_TICKET, never `deterministic_cleared` — ✅ test 17.
10. Seed `matter_slug=='aukera'` both sites; test asserts `aukera`; zero `annaberg` slug literals — ✅.

## Tests (literal, live Postgres 16 — not compile-only)
- `tests/test_project_registry.py`: **21 passed**.
- `tests/test_box5_ticketing_runner.py`: **20 passed** (14 C-matrix no-regression + 6 D-branch).
- Airport regression (`test_airport_ticketing_bridge` + `_terminal_columns` + `_scheduler` + `_checkin_reader`): **39 passed**.
- Live-PG tests auto-skip without `TEST_DATABASE_URL`; CI runs live.

## Required ship-report statements (Quality Checkpoints)
- **(a) Participant-binding only for pilot v1.** The OR branch of #4679.2 (thread-continuity) is NOT built.
- **(b) Thread-continuity deferred.** No queryable email-thread signal on main (`airport_tickets` persists only `source_id`/`bus_thread_id`; the email `thread_id` lands as free-text luggage). Proposed future fix: add a queryable `email_thread_id` column to `airport_tickets` populated from `EmailArrival.thread_id` at reserve time, so a later brief can do an indexed "prior FAST_TICKET/TICKET in the same email thread for the same project" lookup. Did NOT invent a thread signal or scan JSONB luggage.
- **(c) Seed corrected but UN-RUN.** Only the slug literal changed (`annaberg`→`aukera`, canonical in slugs.yml v23); running `scripts/seed_bb_pilot_registry.py` is a separate Director-GO step. `aliases` unchanged (human mnemonic).

## Flags for gate (surface-don't-hide)
- **VISIBLE_HOLD grep is 1, not 0.** The single occurrence is BRIEF-B's pre-existing explanatory CHECK comment (`ensure_airport_ticket_terminal_columns`, "Do NOT Touch"), not a write. D introduces zero `VISIBLE_HOLD`. Reaching literal grep-0 would require editing BRIEF-B's DDL comment, which the brief forbids.
- **Hard-lane error rollback semantics.** Because `issue_ticket` and the terminal write share one transaction (no intervening commit), the brief-specified `conn.rollback()` on a hard-lane error also unwinds the in-flight reserve. So an errored row is retried next tick (terminal NULL, `failed`+1) rather than TICKETed this tick — consistent with C's atomic-per-row model and the brief's "TICKET or NULL per fall-through" (test 17 asserts NOT FAST_TICKET + `failed`≥1 + batch continues).

## Ships DARK
`BOX5_FAST_LANE_ENABLED` default false → the branch is skipped and C's safe-default TICKET covers everything. No activation, no seed run (both later Director GOs). E (soft fast lane) dispatches after D merges.
