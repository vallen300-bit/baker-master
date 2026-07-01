-- == migrate:up ==
-- BOX5_OUTBOUND_INGEST_2: durable outbound-event state machine.
--
-- Director ruling (2026-07-01): Brisen OUTBOUND email is a first-class ratification
-- signal — it can advance the ClickUp timetable and the flight process. Increment 1
-- (20260701_airport_tickets_direction.sql, PR #445) captures each outbound arrival as
-- a direction='outbound' airport_tickets row + one 'airport_ticket.outbound_signal'
-- action, short-circuiting before every desk lane. Increment 2 wires that captured
-- signal to (a) a ClickUp timetable write and (b) a RECORD-ONLY flight-state
-- transition, for RATIFYING outbound only; routine outbound stays evidence-only.
--
-- This table is the durable event state, keyed 1:1 to the outbound airport_tickets
-- ticket_id ('airport-outbound:<message_id>'). It is the single source of truth for
-- idempotency (re-ticking the same outbound writes NO duplicate ClickUp task and NO
-- duplicate flight transition — the event row already carries CLICKUP_WRITTEN /
-- FLIGHT_PROGRESSED + its idempotency keys) and for retry (a transient ClickUp
-- failure lands the row in ERROR_RETRY, never a silent drop).
--
-- RECORD-ONLY flight (lead confirmed #4851, 2026-07-01): NO live flight-state store
-- exists in the repo, and building one exceeds this brief's Files Modified. The flight
-- transition is recorded on this row (flight_id / flight_from_state / flight_to_state /
-- ratification_class) + a baker_actions 'airport_outbound.flight_progressed' audit;
-- no external flight store is mutated. The real flight lifecycle store is a separate
-- future increment.
--
-- Additive, idempotent, zero-downtime. Guarded end-to-end behind the EXISTING flag
-- AIRPORT_OUTBOUND_INGEST_ENABLED (default false) — flag OFF means this table is never
-- touched on the outbound path (the (b.5) short-circuit is gated before it).
--
-- Companion bootstrap: orchestrator/airport_outbound_connector.py
-- ensure_airport_outbound_events_table() carries the SAME CREATE TABLE IF NOT EXISTS
-- so a fresh / already-bootstrapped DB gains the table without a migration run
-- (migration-vs-bootstrap drift trap — Lesson #50). This is a NEW table, so there is
-- no pre-existing-column type-drift risk.
--
-- Brief: briefs/BRIEF_BOX5_OUTBOUND_INGEST_2.md (2026-07-01)
-- Spec:  baker-os-v2-box5-routing-reversal-e-outbound-increment2-spec-codex-arch-20260701.md §Deliverable 2

CREATE TABLE IF NOT EXISTS airport_outbound_events (
    id                      BIGSERIAL PRIMARY KEY,
    ticket_id               TEXT NOT NULL UNIQUE,   -- 'airport-outbound:<message_id>'
    message_id              TEXT NOT NULL,
    thread_id               TEXT,
    event_state             TEXT NOT NULL DEFAULT 'CAPTURED',
    ratification_class      TEXT,                   -- approval|instruction|external_send|deliverable|commitment|close (NULL = routine)
    project_code            TEXT,
    matter_slug             TEXT,
    desk_owner              TEXT,
    clickup_list_id         TEXT,
    clickup_task_id         TEXT,
    clickup_status          TEXT,
    clickup_operation       TEXT,                   -- create_task|update_task|add_comment
    clickup_idempotency_key TEXT,
    flight_id               TEXT,
    flight_from_state       TEXT,
    flight_to_state         TEXT,
    flight_idempotency_key  TEXT,
    correlation             JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT airport_outbound_events_state_check
        CHECK (event_state IN (
            'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING', 'EVIDENCE_ONLY',
            'RATIFICATION_READY', 'CLICKUP_BLOCKED', 'CLICKUP_WRITTEN',
            'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED', 'NEEDS_CONTROLLER', 'ERROR_RETRY'
        ))
);

CREATE INDEX IF NOT EXISTS idx_airport_outbound_events_state
    ON airport_outbound_events (event_state);


-- == migrate:down ==
-- Disaster recovery only. Drops the outbound-event state machine; captured outbound
-- airport_tickets rows are untouched (their direction tag + outbound_signal action
-- survive), so a re-activated connector rebuilds event state from CAPTURED on the
-- next tick.
--
-- DROP TABLE IF EXISTS airport_outbound_events;
