-- ============================================
-- Sentinel AI — PostgreSQL Schema
-- Run this to initialize the structured data layer
-- ============================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for fuzzy text search

-- ============================================
-- CONTACTS — People Sentinel knows about
-- ============================================
CREATE TABLE IF NOT EXISTS contacts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    aliases     TEXT[] DEFAULT '{}',           -- alternative names/spellings
    phone       TEXT,
    email       TEXT,
    company     TEXT,
    role        TEXT,
    relationship TEXT,                         -- buyer, partner, advisor, team, etc.
    language    TEXT DEFAULT 'en',
    timezone    TEXT,
    -- Behavioral intelligence
    communication_style TEXT,                  -- formal, casual, etc.
    response_pattern    TEXT,                  -- fast_responder, delayed, etc.
    preferred_channel   TEXT,                  -- whatsapp, email, phone
    -- Deal context
    active_deals    TEXT[] DEFAULT '{}',       -- deal IDs
    deal_history    JSONB DEFAULT '{}',
    -- Flexible metadata
    metadata    JSONB DEFAULT '{}',
    -- Timestamps
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_contact TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_contacts_name ON contacts USING gin (name gin_trgm_ops);
CREATE INDEX idx_contacts_aliases ON contacts USING gin (aliases);

-- ============================================
-- DEALS — Active and historical deals
-- ============================================
CREATE TABLE IF NOT EXISTS deals (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',  -- active, closed_won, closed_lost, paused
    stage       TEXT,                             -- qualification, negotiation, due_diligence, closing
    priority    INTEGER DEFAULT 5,                -- 1=highest, 10=lowest
    -- Key parties
    buyer_contact_id    UUID REFERENCES contacts(id),
    seller_contact_id   UUID REFERENCES contacts(id),
    advisor_contacts    UUID[] DEFAULT '{}',
    -- Financials
    deal_value      NUMERIC,
    currency        TEXT DEFAULT 'EUR',
    -- Qualification
    qualification_score INTEGER,               -- 0-100
    qualification_notes TEXT,
    -- Flexible metadata
    metadata    JSONB DEFAULT '{}',
    -- Timestamps
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    closed_at   TIMESTAMPTZ
);

CREATE INDEX idx_deals_status ON deals(status);

-- ============================================
-- DECISIONS — Baker's decision log (learning loop)
-- ============================================
CREATE TABLE IF NOT EXISTS decisions (
    id              SERIAL PRIMARY KEY,
    decision        TEXT NOT NULL,
    reasoning       TEXT,
    confidence      TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    trigger_type    TEXT,
    -- Feedback loop
    accepted        BOOLEAN,
    rejection_reason TEXT,
    feedback_at     TIMESTAMPTZ,
    -- Metadata
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_decisions_created ON decisions(created_at DESC);
CREATE INDEX idx_decisions_feedback ON decisions(accepted) WHERE accepted IS NOT NULL;

-- ============================================
-- PREFERENCES — CEO/COO settings and preferences
-- ============================================
CREATE TABLE IF NOT EXISTS preferences (
    id          SERIAL PRIMARY KEY,
    user_role   TEXT NOT NULL,                 -- ceo, coo
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_role, key)
);

-- Default CEO preferences
INSERT INTO preferences (user_role, key, value) VALUES
    ('ceo', 'language', 'en'),
    ('ceo', 'briefing_time', '08:00'),
    ('ceo', 'timezone', 'Europe/Zurich'),
    ('ceo', 'alert_channel', 'slack'),
    ('ceo', 'draft_approval_required', 'true'),
    ('ceo', 'response_style', 'direct_structured')
ON CONFLICT (user_role, key) DO NOTHING;

-- ============================================
-- TRIGGERS — Log of all processed triggers
-- ============================================
CREATE TABLE IF NOT EXISTS trigger_log (
    id          SERIAL PRIMARY KEY,
    type        TEXT NOT NULL,                 -- email, whatsapp, meeting, calendar, scheduled, manual
    source_id   TEXT,                          -- ID from source system
    content     TEXT,
    contact_id  UUID REFERENCES contacts(id),
    priority    TEXT,
    -- Pipeline results
    processed   BOOLEAN DEFAULT FALSE,
    response_id TEXT,                          -- reference to the SentinelResponse
    pipeline_ms INTEGER,                       -- processing time
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    -- Timestamps
    received_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_triggers_type ON trigger_log(type);
CREATE INDEX idx_triggers_received ON trigger_log(received_at DESC);

-- ============================================
-- ALERTS — Persistent alert queue
-- ============================================
CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    tier        INTEGER CHECK (tier IN (1, 2, 3)),
    title       TEXT NOT NULL,
    body        TEXT,
    action_required BOOLEAN DEFAULT FALSE,
    -- Status
    status      TEXT DEFAULT 'pending',        -- pending, acknowledged, resolved, dismissed
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    -- Source
    trigger_id  INTEGER REFERENCES trigger_log(id),
    contact_id  UUID REFERENCES contacts(id),
    deal_id     UUID REFERENCES deals(id),
    -- Timestamps
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_status ON alerts(status) WHERE status = 'pending';
CREATE INDEX idx_alerts_tier ON alerts(tier);

-- ============================================
-- Ingestion log (INGEST-1 — CLI batch ingestion dedup tracking)
-- ============================================
CREATE TABLE IF NOT EXISTS ingestion_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_size_bytes BIGINT,
    collection TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    point_ids TEXT[],
    source_path TEXT,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    ingested_by TEXT DEFAULT 'cli',
    UNIQUE(filename, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_log_filename ON ingestion_log(filename);
CREATE INDEX IF NOT EXISTS idx_ingestion_log_hash ON ingestion_log(file_hash);

-- ============================================
-- Seed data: Known contacts from Baker WhatsApp phase
-- ============================================
INSERT INTO contacts (name, aliases, preferred_channel, metadata) VALUES
    ('Christian Planegger', '{}', 'whatsapp', '{"whatsapp_chunks": 16}'),
    ('Vladimir Moravchik', '{}', 'whatsapp', '{"whatsapp_chunks": 7}'),
    ('Christophe Buchwalder', '{}', 'whatsapp', '{"whatsapp_chunks": 11}'),
    ('Jean Francois Suzane', '{}', 'whatsapp', '{"whatsapp_chunks": 13}'),
    ('Andrey Oskolkov', '{"Ao Mobile", "Andrey O", "AO Group"}', 'whatsapp', '{"whatsapp_chunks": 66}'),
    ('Yansong Liu', '{}', 'whatsapp', '{"whatsapp_chunks": 5}'),
    ('Christian Merz', '{}', 'whatsapp', '{"whatsapp_chunks": 7}'),
    ('Phub Zam', '{}', 'whatsapp', '{"whatsapp_chunks": 3}'),
    ('Ettore', '{"Oskolkov"}', 'whatsapp', '{"whatsapp_chunks": 10}'),
    ('Francesco', '{"Zegna"}', 'whatsapp', '{"whatsapp_chunks": 2}')
ON CONFLICT (name) DO NOTHING;
