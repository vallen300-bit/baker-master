-- KBL-A Schema Draft (v2 — aligned to DECISIONS_PRE_KBL_A_V2_DRAFT.md v2.1)
-- Status: DRAFT (pre-stage only — DO NOT apply until KBL-A brief ratifies).
-- Prepared-by: Code Brisen #2 (app)
-- Date: 2026-04-17
-- Supersedes: initial draft (committed 233bf04) which used single-row-wide
--             kbl_runtime_state. v2.1 D8 specs key-value — this draft
--             matches v2.1 canonical shape for all four new tables.
--
-- Aligns to (quoted verbatim where possible):
--   • briefs/DECISIONS_PRE_KBL_A_V2_DRAFT.md D8  (kbl_runtime_state)
--   • briefs/DECISIONS_PRE_KBL_A_V2_DRAFT.md D14 (kbl_cost_ledger)
--   • briefs/DECISIONS_PRE_KBL_A_V2_DRAFT.md D15 (kbl_log)
--   • briefs/DECISIONS_PRE_KBL_A_V2_DRAFT.md D2  (gold_promote_queue)
--   • briefs/ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md KBL-19 (signal_queue base)
--
-- Deploy sequence (per D12):
--   1. Render deploys KBL-A PR → _ensure_* methods run at startup
--   2. Verify via \d kbl_runtime_state etc.
--   3. Mac Mini code pulled + launchctl reload → consumes tables
--
-- Apply via: BEGIN; \i KBL_A_SCHEMA.sql; COMMIT;
-- Rollback procedure at bottom of file (soft-deprecate, no DROP).

BEGIN;

-- =============================================================================
-- 1. signal_queue — additive columns + status enum expansion (KBL-19 / D3 / R1.11)
-- =============================================================================
-- Additive changes per D12 policy ("ALTER TABLE ... ADD COLUMN IF NOT EXISTS").
-- Assumes KBL-A bootstrap creates signal_queue from KBL-19 spec first.

ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS primary_matter TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS related_matters JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_confidence NUMERIC(3,2);

ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_triage_confidence_range;
ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_triage_confidence_range
    CHECK (triage_confidence IS NULL OR (triage_confidence >= 0 AND triage_confidence <= 1));

-- Status expansion: add 'classified-deferred' (R1.11), 'failed-reviewed' (DLQ
-- triage), and 'cost-deferred' (D14 — circuit-open skips to next cron).
ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
    CHECK (status IN (
        'pending',
        'processing',
        'done',
        'failed',
        'expired',
        'classified-deferred',
        'failed-reviewed',
        'cost-deferred'
    ));

CREATE INDEX IF NOT EXISTS idx_signal_queue_primary_matter
    ON signal_queue (primary_matter)
    WHERE primary_matter IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signal_queue_related_matters_gin
    ON signal_queue USING gin (related_matters);

CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority
    ON signal_queue (status, priority, created_at);

-- =============================================================================
-- 2. kbl_runtime_state — key-value runtime flags (D8, D15)
-- =============================================================================
-- v2.1 D8 canonical spec: key-value, seeded with specific flag keys.
-- Seed keys per spec:
--   anthropic_circuit_open, anthropic_5xx_counter,
--   qwen_active, qwen_active_since, qwen_swap_count_today,
--   mac_mini_heartbeat  (D15)

CREATE TABLE IF NOT EXISTS kbl_runtime_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT
);

-- Seed flag keys with safe defaults. ON CONFLICT DO NOTHING preserves live
-- values across re-runs.
INSERT INTO kbl_runtime_state (key, value, updated_by) VALUES
    ('anthropic_circuit_open',    'false', 'kbl_a_bootstrap'),
    ('anthropic_5xx_counter',     '0',     'kbl_a_bootstrap'),
    ('qwen_active',               'false', 'kbl_a_bootstrap'),
    ('qwen_active_since',         '',      'kbl_a_bootstrap'),
    ('qwen_swap_count_today',     '0',     'kbl_a_bootstrap'),
    ('mac_mini_heartbeat',        '',      'kbl_a_bootstrap')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- 3. kbl_cost_ledger — per-call cost tracking (D14)
-- =============================================================================
-- v2.1 D14 canonical spec. Columns explicitly shown: id, ts, signal_id, step,
-- input_tokens, output_tokens, cost_usd, success, metadata. Adding model +
-- latency_ms as natural extensions (called out in D14 text: "actual token
-- counts", throughput for local models).
--
-- IMPORTANT FK caveat: v2.1 D14 spec'd `signal_id UUID REFERENCES signal_queue(id)`
-- but KBL-19 signal_queue spec declares `id SERIAL PRIMARY KEY` (INT). These
-- are incompatible. Flagging this to AI Head as R4 input. This draft uses
-- BIGINT (matches SERIAL) WITHOUT an explicit FK — KBL-A brief should lock
-- the ID type and add the FK back after reconciliation.

CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id       BIGINT,                               -- FK pending ID-type reconciliation
    step            TEXT NOT NULL,                        -- 'layer0'|'triage'|'resolve'|'extract'|'classify'|'opus_step5'|'sonnet_step6'|'claude_harness'|'ayoniso'
    model           TEXT,                                 -- 'gemma4:latest'|'qwen2.5:14b'|'claude-opus-4-7'|...
    input_tokens    INT,
    output_tokens   INT,
    latency_ms      INT,
    cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,     -- 0 for local Gemma/Qwen
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_day
    ON kbl_cost_ledger ((ts::date));
CREATE INDEX IF NOT EXISTS idx_cost_ledger_signal
    ON kbl_cost_ledger (signal_id, ts) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cost_ledger_step_day
    ON kbl_cost_ledger (step, (ts::date));

-- =============================================================================
-- 4. kbl_log — WARN+ central log (D15)
-- =============================================================================
-- v2.1 D15 canonical spec. DEBUG/INFO stay in local rotating files on Mac
-- Mini; only WARN+ lands here. CRITICAL rows additionally trigger a WhatsApp
-- alert (with 5-min dedupe by component + message hash — computed at
-- insert-time in app code, not in DB).

CREATE TABLE IF NOT EXISTS kbl_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level       TEXT NOT NULL
                CHECK (level IN ('WARN', 'ERROR', 'CRITICAL', 'INFO')),  -- INFO allowed for M3 vault-size telemetry
    component   TEXT NOT NULL,                            -- 'layer0'|'triage'|'pipeline'|'gold_promote'|'circuit_breaker'|'vault_size'|...
    signal_id   BIGINT,                                   -- matches kbl_cost_ledger.signal_id type (see D14 caveat above)
    message     TEXT NOT NULL,                            -- short — full bodies stay in local file
    metadata    JSONB
);

CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level
    ON kbl_log ((ts::date), level);
CREATE INDEX IF NOT EXISTS idx_kbl_log_component
    ON kbl_log (component, ts);

-- =============================================================================
-- 5. gold_promote_queue — Director /gold queue-poll (D2)
-- =============================================================================
-- v2.1 D2 canonical spec (Director-signed 2026-04-17). WhatsApp /gold → WAHA
-- → Render inserts row → Mac Mini cron drains via SKIP LOCKED.

CREATE TABLE IF NOT EXISTS gold_promote_queue (
    id              SERIAL PRIMARY KEY,
    path            TEXT NOT NULL,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wa_msg_id       TEXT,
    processed_at    TIMESTAMPTZ,
    result          TEXT,                                 -- 'ok'|'noop'|'error:<msg>'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gold_queue_pending
    ON gold_promote_queue (requested_at)
    WHERE processed_at IS NULL;

COMMIT;

-- =============================================================================
-- Rollback / soft-deprecation notes (D12 N5)
-- =============================================================================
-- Principle: never DROP a column or table in production. Soft-deprecate so a
-- forward-rolling deploy can't lose data via rollback+replay.
--
--   -- signal_queue: columns stay; only widened CHECKs narrow back.
--   ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
--   ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
--       CHECK (status IN ('pending','processing','done','failed','expired'));
--   ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_triage_confidence_range;
--
--   -- New tables: keep in place, mark deprecated via COMMENT.
--   COMMENT ON TABLE kbl_runtime_state  IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_cost_ledger    IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_log            IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE gold_promote_queue IS 'DEPRECATED <date> — rolled back from KBL-A';
--
-- Type changes (e.g. resolving the signal_id INT-vs-UUID inconsistency) require
-- explicit down-migration SQL per D12 and reviewer sign-off on a copy before dispatch.

-- End KBL_A_SCHEMA.sql
