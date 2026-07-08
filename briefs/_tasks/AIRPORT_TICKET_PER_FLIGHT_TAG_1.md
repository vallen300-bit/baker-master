# BRIEF: AIRPORT_TICKET_PER_FLIGHT_TAG_1 — per-matter suspected_flight so each flight dashboard shows only its own tickets

dispatched_by: lead
assignee: deputy-codex
effort: medium (recommended tier for codex gate: medium)
repo: baker-master (`orchestrator/airport_ticketing_bridge.py`)
task_class: cross-layer-feature (mint-site tagging + existing-row backfill; drives CEO dashboard §4 strips)

## Context

The airport ticketing bridge tags EVERY minted ticket with ONE global `suspected_flight` from `_flight_name()` (env `_FLIGHT_ENV`, default `aukera-annaberg-financing`). Consequence surfaced live 2026-07-08 (bus #7138/#7144): the AO flight dashboard (`/flight/AO-OSK-001`) §4 ticket-count strip cannot show only AO's tickets — the shared ledger holds 185 tickets, 179 of them BB-AUK's (Aukera/Lilienmatt). Lead ruled the AO dashboard ships with honest zeros (Option B, #7139/#7145) rather than conflate; this brief is the proper fix so each flight's strip shows its own real counts.

### Context Contract
- Mint sites (all currently `suspected_flight=_flight_name()`): `build_email_ticket` (:680), `build_plaud_ticket` (:791), `build_whatsapp_ticket` (:849).
- Existing per-matter precedent to MIRROR: `_desk_for_matter(matter_slug, conn)` (:491) — resolves `project_registry.desk_owner` via `desk_owner_for_matter`, untrusted-input guarded, `conn=None` → global fallback, never raises. PR #483 pattern (lead ruling #6850: registry is single source of truth).
- Plaud builder already carries `arrival.matter_slug` and calls `_desk_for_matter` (:759). Email + WA are matter-blind today (global by design — do NOT invent per-matter for them unless a matter_slug is genuinely in hand).
- Consumer: flight dashboard `_tickets_html` reads `suspected_flight` to scope the §4 count query; bus topic is `airport-ticketing/{suspected_flight}` (:1847) — changing the tag changes the bus topic namespace, verify no escalation/dispatcher coupling breaks.
- Registry: `project_registry` rows id=1 BB-AUK-001/aukera, id=2 AO-OSK-001/ao. Flight-code source is NOT yet confirmed to be a registry column — DISCOVER it (registry column vs derived from match_key vs a mapping); fail-loud if absent, do not hardcode.

## Problem

One global `suspected_flight` means every flight's dashboard strip either shows the whole shared pile or nothing. AO (and every future flight) cannot show honest per-flight ticket counts. Fix: resolve `suspected_flight` per-matter at mint time, and backfill the 185 existing rows so BB-AUK's dashboard does NOT regress when the query starts scoping by flight.

## Task

1. Add `_flight_for_matter(matter_slug, conn)` mirroring `_desk_for_matter` semantics exactly: registry-sourced, `conn=None` → global `_flight_name()` fallback, untrusted-input guarded, NEVER raises, NEVER empty.
2. Use it in `build_plaud_ticket` (has matter_slug). For email/WA: only if a matter_slug is genuinely resolvable at that site — otherwise leave global and document why (fail-loud if you believe they need it).
3. Backfill the 185 existing `airport_tickets` rows: set `suspected_flight` from each row's `suspected_matter_slug` via the registry, idempotent, audited to `baker_actions`. DUAL-MATCH design so BB-AUK-001's dashboard strip shows the SAME count before and after (its 179 must remain visible on its own flight, not vanish).
4. Verify the flight-dashboard §4 query + bus topic namespace tolerate the new per-flight values (no escalation/dispatcher regression).

## Files Modified

- `orchestrator/airport_ticketing_bridge.py` — `_flight_for_matter` + Plaud mint-site wiring.
- `migrations/` or an audited `baker_raw_write` backfill script — the 185-row backfill (idempotent, audited).
- `tests/test_airport_nonmail_signals.py` (+ per-flight tag tests) — TDD per Verification.
- Nothing else. No dashboard renderer change here (that is the folded `tickets_note` field, out of scope — note only).

## Constraints (hard)

- Mirror `_desk_for_matter` fault-tolerance: any failure / None conn / unknown matter → global flight. Never raise, never empty.
- Backfill must be idempotent + audited; BB-AUK count invariant BEFORE == AFTER on its own flight (prove it).
- Un-flagged / matter-blind mint sites stay byte-identical unless a real matter_slug is in hand.
- Fail-loud: if the registry has no flight-code source, STOP and report — do not hardcode a matter→flight map in the bridge.

## Verification

1. TDD: test `_flight_for_matter` — ao matter → AO flight code; unknown → global; None conn → global (byte-identical to today).
2. Live-PG: Plaud AO arrival mints with AO-scoped `suspected_flight`; a BB arrival still mints BB-AUK.
3. Backfill probe (literal output): row counts per `suspected_flight` before/after; BB-AUK-001 flight count unchanged; AO-scoped rows now carry the AO flight (incl. checked-in id=601).
4. Dashboard: `/flight/AO-OSK-001` §4 strip shows AO's real count (≥1, the checked-in ticket); `/flight/BB-AUK-001` strip unchanged.

## Acceptance criteria (done rubric)

- AC1: `_flight_for_matter` live + Plaud mint-site wired; tests green (literal run output).
- AC2: 185 rows backfilled, idempotent + audited (`baker_actions` row id in report); BB-AUK count invariant proven.
- AC3: `/flight/AO-OSK-001` §4 shows id=601 live (literal curl); `/flight/BB-AUK-001` unchanged (literal curl).
- AC4: No escalation/dispatcher regression from the bus-topic namespace change (evidence).
- AC5: codex G3 medium PASS → lead merge → POST_DEPLOY_AC_VERDICT v1.

Done-state: all 5 ACs answered with literal evidence — not "by inspection".

## Gate plan

codex G3 (effort: medium) → lead merge → deputy-codex POST_DEPLOY_AC_VERDICT. No Director gate (Tier-A). deputy G2 optional (lead may waive given codex G3 covers the cross-layer risk).

## Reply target

Bus-post all state changes (start, blocker, gate request, ship) to `lead`. Reply-target = lead.
