-- == migrate:up ==

CREATE TABLE IF NOT EXISTS airport_tickets (
    id BIGSERIAL PRIMARY KEY,
    ticket_id TEXT NOT NULL UNIQUE,
    dedup_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'candidate',
    source_channel TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_received_at TIMESTAMPTZ,
    originator TEXT,
    suspected_matter_slug TEXT,
    suspected_flight TEXT,
    proposed_desk_slug TEXT NOT NULL,
    urgency_hint TEXT NOT NULL DEFAULT 'normal',
    ticket JSONB NOT NULL DEFAULT '{}'::jsonb,
    bus_message_id BIGINT,
    bus_thread_id TEXT,
    last_sent_at TIMESTAMPTZ,
    check_in_outcome TEXT,
    check_in_at TIMESTAMPTZ,
    check_in_by TEXT,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT airport_tickets_status_check
        CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected')),
    CONSTRAINT airport_tickets_source_channel_check
        CHECK (source_channel IN ('email', 'whatsapp', 'plaud', 'clickup', 'calendar', 'other')),
    CONSTRAINT airport_tickets_urgency_check
        CHECK (urgency_hint IN ('low', 'normal', 'high', 'urgent')),
    CONSTRAINT airport_tickets_check_in_outcome_check
        CHECK (
            check_in_outcome IS NULL OR
            check_in_outcome IN (
                'VALID',
                'FAKE',
                'DUPLICATE',
                'WRONG_TERMINAL',
                'URGENT',
                'NEEDS_LUGGAGE_READ'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_airport_tickets_source
    ON airport_tickets (source_channel, source_id);

CREATE INDEX IF NOT EXISTS idx_airport_tickets_desk_status
    ON airport_tickets (proposed_desk_slug, status, last_sent_at DESC);

-- == migrate:down ==
-- Disaster recovery only. Not auto-run: config/migration_runner.py executes
-- the full file body for pending migrations, so rollback statements must stay
-- commented unless an operator runs them manually.
-- DROP INDEX IF EXISTS idx_airport_tickets_desk_status;
-- DROP INDEX IF EXISTS idx_airport_tickets_source;
-- DROP TABLE IF EXISTS airport_tickets;
