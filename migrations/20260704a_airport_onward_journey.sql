-- == migrate:up ==
-- BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1 (T0): onward-journey state machine.
--
-- Blocks 1/5/6 (BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1, PRs #458/#459) drove the 20 BB
-- tickets to the Airside Lounge: an airport_outbound_events row at event_state
-- 'CLICKUP_WRITTEN' (ticket_id scheme 'airport-lounge:<source_ticket_id>') + a ClickUp
-- task at status "to do". Blocks 2-4 continue the journey on that SAME event row:
--   BOARDING_POSTED  (block 2) — WORK_PACKET posted to the desk over the bus, awaiting claim
--   CLAIMED          (block 2) — desk accepted the token; ClickUp mirrored to "in progress"
--   LANDED           (block 4) — desk returned the package; awaiting receipt
--   RECEIPT_WRITTEN  (block 4) — ClickUp closed + receipt comment + bus RECEIPT proof; journey Closed
-- In-flight status mirrors (block 3) stay on CLAIMED (ClickUp-surface-only); the source
-- ticket flips to airport_tickets.status='closed' only at RECEIPT_WRITTEN.
--
-- D-23 (Controller-confirmed): NO flight lifecycle store exists. flight_id /
-- flight_from_state / flight_to_state / flight_idempotency_key stay NULL on every row
-- these states touch — journey progress lives on event_state + correlation JSON only.
--
-- Companion bootstraps carry the SAME amendment (migration-vs-bootstrap drift, Lesson
-- #37/#50): orchestrator/airport_outbound_connector.py ensure_airport_outbound_events_table()
-- and orchestrator/airport_ticketing_bridge.py ensure_airport_ticket_table(). Both use an
-- idempotent DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT so an already-bootstrapped DB
-- (where CREATE TABLE IF NOT EXISTS no-ops) still gains the new states.
--
-- Additive, idempotent, zero-downtime. The onward-journey code is guarded behind
-- AIRPORT_BOARDING_FLOW_ENABLED (default false) — this migration only widens the CHECK
-- vocabulary; nothing writes a new state until the flag is flipped.
--
-- Brief: briefs/_tasks/BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1.md

ALTER TABLE airport_outbound_events DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check;
ALTER TABLE airport_outbound_events ADD CONSTRAINT airport_outbound_events_state_check
    CHECK (event_state IN (
        'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING', 'EVIDENCE_ONLY',
        'RATIFICATION_READY', 'CLICKUP_BLOCKED', 'CLICKUP_WRITTEN',
        'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED', 'NEEDS_CONTROLLER', 'ERROR_RETRY',
        'BOARDING_POSTED', 'CLAIMED', 'LANDED', 'RECEIPT_WRITTEN'
    ));

ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_status_check;
ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_status_check
    CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected', 'closed'));


-- == migrate:down ==
-- Disaster recovery only. Reverts the CHECK vocabularies to their pre-onward-journey
-- form. Any row already at BOARDING_POSTED / CLAIMED / LANDED / RECEIPT_WRITTEN (or an
-- airport_tickets row at 'closed') MUST be reconciled by hand first, or the ADD
-- CONSTRAINT below will fail — that is intentional (fail loud, never silently drop live
-- journey state).
--
-- ALTER TABLE airport_outbound_events DROP CONSTRAINT IF EXISTS airport_outbound_events_state_check;
-- ALTER TABLE airport_outbound_events ADD CONSTRAINT airport_outbound_events_state_check
--     CHECK (event_state IN (
--         'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING', 'EVIDENCE_ONLY',
--         'RATIFICATION_READY', 'CLICKUP_BLOCKED', 'CLICKUP_WRITTEN',
--         'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED', 'NEEDS_CONTROLLER', 'ERROR_RETRY'
--     ));
-- ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_status_check;
-- ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_status_check
--     CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected'));
