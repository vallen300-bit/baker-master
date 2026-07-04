-- == migrate:up ==
-- BAKER_OS_V2_STEP2_ASSIST_LANE_1 (T0): D-32 assist lane state.
--
-- D-32 (Director-approved 2026-07-04, split out of PR #461 by lead ruling #5344): during
-- in-flight work the operating desk may request assistance (Researcher / BEN finance /
-- legal-analysis) via bus. An assist is a same-ticket sub-dispatch — never a new ticket,
-- never a side channel. While an assist is outstanding the parent airport_outbound_events
-- row sits at the new WAITING_ON_ASSIST state; it returns to CLAIMED once every assist on
-- the row has landed a receipt, and cannot reach RECEIPT_WRITTEN with any assist open.
--
-- Assist records live in the parent row's correlation JSON (correlation.assists) — no new
-- table. This migration only widens the event-state CHECK by one value.
--
-- Companion bootstrap: orchestrator/airport_outbound_connector.py
-- ensure_airport_outbound_events_table() carries the SAME amendment via idempotent
-- DROP+ADD so an already-bootstrapped DB gains the state (migration-vs-bootstrap drift,
-- Lesson #37/#50). Additive, idempotent, zero-downtime; guarded behind the existing
-- AIRPORT_BOARDING_FLOW_ENABLED — nothing writes WAITING_ON_ASSIST until the flag is on.
--
-- Brief: BAKER_OS_V2_STEP2_ASSIST_LANE_1 (parent PR #461 merged @6e9b5a0).

ALTER TABLE airport_outbound_events DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check;
ALTER TABLE airport_outbound_events ADD CONSTRAINT airport_outbound_events_state_check
    CHECK (event_state IN (
        'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING', 'EVIDENCE_ONLY',
        'RATIFICATION_READY', 'CLICKUP_BLOCKED', 'CLICKUP_WRITTEN',
        'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED', 'NEEDS_CONTROLLER', 'ERROR_RETRY',
        'BOARDING_POSTED', 'CLAIMED', 'LANDED', 'RECEIPT_WRITTEN',
        'WAITING_ON_ASSIST'
    ));


-- == migrate:down ==
-- Disaster recovery only. Reverts the CHECK to its pre-assist-lane form. Any row at
-- WAITING_ON_ASSIST must be reconciled by hand first (fail loud, never silently drop
-- an in-flight assist).
--
-- ALTER TABLE airport_outbound_events DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check;
-- ALTER TABLE airport_outbound_events ADD CONSTRAINT airport_outbound_events_state_check
--     CHECK (event_state IN (
--         'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING', 'EVIDENCE_ONLY',
--         'RATIFICATION_READY', 'CLICKUP_BLOCKED', 'CLICKUP_WRITTEN',
--         'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED', 'NEEDS_CONTROLLER', 'ERROR_RETRY',
--         'BOARDING_POSTED', 'CLAIMED', 'LANDED', 'RECEIPT_WRITTEN'
--     ));
