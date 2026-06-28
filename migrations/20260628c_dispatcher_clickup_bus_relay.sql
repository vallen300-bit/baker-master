-- == migrate:up ==

CREATE TABLE IF NOT EXISTS dispatcher_bus_threads (
    id BIGSERIAL PRIMARY KEY,
    clickup_task_id TEXT NOT NULL,
    owner_slug TEXT NOT NULL,
    recipient_slug TEXT NOT NULL,
    bus_message_id BIGINT,
    bus_thread_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    reason_code TEXT NOT NULL,
    condition_hash TEXT,
    last_sent_at TIMESTAMPTZ,
    last_reply_at TIMESTAMPTZ,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dispatcher_bus_threads_status_check
        CHECK (status IN ('open', 'waiting_reply', 'replied', 'closed', 'failed')),
    CONSTRAINT dispatcher_bus_threads_reason_check
        CHECK (reason_code IN (
            'due',
            'blocked',
            'unblocked',
            'stale',
            'needs_clarification'
        ))
);

CREATE INDEX IF NOT EXISTS idx_dispatcher_bus_threads_task
    ON dispatcher_bus_threads (clickup_task_id);

CREATE INDEX IF NOT EXISTS idx_dispatcher_bus_threads_status_sent
    ON dispatcher_bus_threads (status, last_sent_at DESC);
