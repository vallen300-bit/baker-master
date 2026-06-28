-- == migrate:up ==

CREATE TABLE IF NOT EXISTS router_second_look_items (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT,
    trigger_step TEXT,
    reason_code TEXT NOT NULL,
    primary_matter TEXT,
    triage_score INTEGER,
    triage_confidence NUMERIC,
    status TEXT NOT NULL DEFAULT 'open',
    decided_by TEXT,
    decision_note TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT router_second_look_status_check
        CHECK (status IN ('open', 'released', 'suppressed', 'escalated', 'closed')),
    CONSTRAINT router_second_look_reason_check
        CHECK (reason_code IN (
            'low_confidence',
            'scope_gate_skip',
            'important_source',
            'deadline_shape',
            'manual'
        ))
);

CREATE INDEX IF NOT EXISTS idx_router_second_look_status_created
    ON router_second_look_items (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_router_second_look_signal
    ON router_second_look_items (signal_id);

CREATE TABLE IF NOT EXISTS waiting_room_items (
    id BIGSERIAL PRIMARY KEY,
    flight_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    owner_slug TEXT,
    reason_code TEXT,
    status TEXT NOT NULL DEFAULT 'waiting',
    ready_after TIMESTAMPTZ,
    last_nudge_at TIMESTAMPTZ,
    nudge_count INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT waiting_room_flight_type_check
        CHECK (flight_type IN ('scheduled', 'chartered')),
    CONSTRAINT waiting_room_status_check
        CHECK (status IN ('waiting', 'ready', 'nudged', 'released', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_waiting_room_status_ready
    ON waiting_room_items (status, ready_after NULLS FIRST, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_waiting_room_owner_status
    ON waiting_room_items (owner_slug, status);
