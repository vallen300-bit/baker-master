# BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1

**Repo:** `baker-master` (base `main` @f4e11ec) · **Worker:** b4 · **Dispatcher:** lead (AH1)
**Recommended effort:** high (production ClickUp writes on real legal traffic; idempotency + write-cap correctness critical)
**Origin:** Baker OS V2 step-2 pilot spec (Director-ratified D-30, 2026-07-04): `baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-step2-bb-desk-onward-journey-pilot-spec-cowork-ah1-20260703.md`. This brief = scope blocks 1 (Airside Lounge writer) + 5 (exception lane) + 6 (backlog drain). Blocks 2-4 (boarding claim / status mirror / landing+receipt) follow as a separate brief once this ships.

## Context Contract

- **Task class:** production implementation, feature-flagged, reversible.
- **Entry points you already know:** `orchestrator/airport_ticketing_bridge.py` (inbound tickets, `_dedup_key`), `orchestrator/airport_outbound_connector.py` (your Box-5 build: `ensure_airport_outbound_events_table`, `correlate()`, `_get_clickup_client`, `_resolve_list_space`, `_BAKER_SPACE_ID` guard, per-list status vocab incl. BB-AUK-001 Timetable `901524194809`).
- **Tables:** `airport_tickets` (16 checked-in at BB gate: 10 VALID + 6 URGENT; 3 `sent`), `airport_outbound_events` (0 rows — journey dead-ends at boarding).
- **Sequencing rulings (Controller-confirmed, do not relitigate):**
  - **D-28:** draining already-checked-in tickets is NOT pilot widening (no new intake). Guard: pre-drain dup scan required (T3.1).
  - **D-23:** flight lifecycle store does NOT exist yet. `flight_id` / `flight_from_state` / `flight_to_state` / `flight_idempotency_key` stay **NULL** in everything this brief writes. Event rows terminate at `CLICKUP_WRITTEN` (or exception states). No flight-state transitions.
  - **D-29:** ClickUp is Surface 1. No dashboard wiring in this brief.

## Problem

16 real checked-in passengers (Merz 9 incl. 3 urgent legal, Balazs 3, others 4) sit at the BB gate with zero onward rows. Ratified non-negotiables violated: "Boarding is not completion", "No silent discard." The journey needs a lounge writer: checked-in VALID/URGENT ticket → ClickUp task + `airport_outbound_events` row, idempotent, with a visible exception lane.

## Tasks

### T1 — Airside Lounge writer (new module or extension, your call — surface in ship report)
For each checked-in VALID/URGENT `airport_tickets` row for `baden-baden-desk`:
1. Create a ClickUp task in BAKER Space (`901510186446`), BB-AUK-001 Timetable list (`901524194809`) — reuse the connector's client + space guard + status-vocab mapping.
2. Write an `airport_outbound_events` row: `ticket_id` keyed to the SOURCE ticket (pick a scheme distinct from `airport-outbound:<message_id>`, e.g. `airport-lounge:<ticket_id>`; document it), `clickup_task_id`, `clickup_list_id`, `clickup_idempotency_key`, `event_state='CLICKUP_WRITTEN'`, `desk_owner`, `matter_slug`, correlation JSON with source ticket ref. Flight columns NULL (D-23).
3. Idempotent re-run: existing event row (or existing idempotency key) ⇒ skip, no duplicate ClickUp task.
4. Feature flag: env `AIRPORT_LOUNGE_WRITER_ENABLED` (default false).

### T2 — Exception lane (ships WITH, not after)
Blocked / unclear / reschedule dispositions: ClickUp parking status (per-list vocab), event row in a non-terminal state (`NEEDS_CONTROLLER` or `CLICKUP_BLOCKED` as fits), TTL re-nudge marker in correlation JSON (actual re-nudge scheduler may be a stub logged loudly — say so in ship report). Nothing silently discarded.

### T3 — Backlog drain (the pilot proof)
1. **Pre-drain dup scan (D-28 guard):** among the 16, detect tickets sharing `dedup_key`/source message; duplicates get ONE ClickUp task, extra tickets marked in correlation JSON as dup-of. Report counts.
2. Drain urgent Merz items first, then remaining. **Respect ClickUp hard cap: max 10 writes/cycle** — drain in ≥2 passes; `BAKER_CLICKUP_READONLY` kill switch respected (dry-run mode must work and log intended writes).
3. Reconciliation readout: SQL proving 0 checked-in tickets without an onward row.

## Constraints
- BAKER Space only; max 10 ClickUp writes/cycle; kill switch honored (repo hard rules).
- All DB/API calls try/except; idempotent `_ensure_*` table boot pattern (no new migration needed — table exists).
- Tests first: idempotency, dup-scan, cap enforcement, flag-off no-op are all unit-testable before ClickUp wiring.
- Do NOT touch flight-state logic, Control Tower, dashboards, other desks.

## Done rubric / Acceptance criteria (live proofs, not compile-clean)
1. All 16 tickets reach a visible disposition (ClickUp task or exception parking); reconciliation SQL shows 0 orphans.
2. `airport_outbound_events` > 0 with `clickup_task_id` populated; re-run creates no duplicates (prove with a second live run log).
3. Exception lane proven on ≥1 blocked/unclear item (visible parking status in ClickUp).
4. Write cap + kill switch verified in the run log (visible cycle boundaries).
5. Flight columns NULL on every row written (D-23 proof — include in reconciliation SQL).
6. Existing tests green; new tests for AC2/AC3/AC4 logic.

## Gate plan
1. pytest green (unit + any live-PG tests touched).
2. Codex gate on the PR (lead routes to codex bus terminal; effort=medium — additive, well-anchored).
3. Live drain run report (T3.3 readout) to lead on bus BEFORE flipping the flag on in prod.
4. POST_DEPLOY_AC verdict on bus per `post-deploy-ac-bus-gate` before DONE.

## Notes for worker
- Branch: `b4/step2-lounge-writer-drain-1`. PR to `main`, ship report + gate verdicts to lead on bus.
- You built the outbound connector — mirror its savepoint + audit patterns (`_audit`, `_savepoint`).
- The 3 `sent` (awaiting check-in reply) tickets are OUT of scope — checked-in only.
