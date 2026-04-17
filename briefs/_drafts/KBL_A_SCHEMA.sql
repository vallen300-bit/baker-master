-- KBL-A Schema Draft (v3 — aligned to KBL-A brief §5 FK reconciliation)
-- Status: DRAFT (pre-stage only — DO NOT apply until KBL-A brief ratifies).
-- Prepared-by: Code Brisen #2 (app)
-- Date: 2026-04-17
--
-- Revision history:
--   v3 (this): signal_id typed INTEGER + FK + ON DELETE SET NULL on both
--              kbl_cost_ledger and kbl_log (resolves the BIGINT caveat).
--              Added kbl_alert_dedupe (KBL-A §5 introduces it). Rolls the
--              ALTER sequence from KBL-A §5:185-197 directly into CREATE
--              TABLE so pre-stage deploy == final deploy shape (no ALTER
--              needed post-creation). Seed keys reduced to 5 per v2.3 D8.
--   v2: aligned to v2.1 canonical shapes for 4 new tables.
--   v1 (233bf04): initial draft, kbl_runtime_state single-row.
--
-- Aligns to (quoted verbatim where possible):
--   • briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md §5 (FK reconciliation + kbl_alert_dedupe)
--   • briefs/DECISIONS_PRE_KBL_A_V2.md D8  (kbl_runtime_state)
--   • briefs/DECISIONS_PRE_KBL_A_V2.md D14 (kbl_cost_ledger)
--   • briefs/DECISIONS_PRE_KBL_A_V2.md D15 (kbl_log + CRITICAL dedupe)
--   • briefs/DECISIONS_PRE_KBL_A_V2.md D2  (gold_promote_queue)
--   • briefs/ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md KBL-19 (signal_queue base, id SERIAL)
--
-- Deploy sequence (per D12):
--   1. Render deploys KBL-A PR → _ensure_* methods run at startup
--   2. Verify via \d kbl_runtime_state etc.
--   3. Mac Mini code pulled + launchctl reload → consumes tables
--
-- Ordering constraint: signal_queue must exist (and have its new columns)
-- BEFORE kbl_cost_ledger / kbl_log are created, because the inline FKs
-- reference signal_queue.id. Enforced at the application layer:
-- SentinelStoreBack must call _ensure_signal_queue_additions BEFORE
-- _ensure_kbl_cost_ledger and _ensure_kbl_log. Section order below reflects
-- that dependency (signal_queue first, then tables that reference it).
--
-- Apply via: BEGIN; \i KBL_A_SCHEMA.sql; COMMIT;
-- Rollback procedure at bottom of file (soft-deprecate, no DROP).

BEGIN;

-- =============================================================================
-- 1. signal_queue — additive columns + status enum expansion (KBL-19 / D3 / R1.11)
-- =============================================================================
-- Additive changes per D12 policy ("ALTER TABLE ... ADD COLUMN IF NOT EXISTS").
-- Assumes KBL-A bootstrap creates signal_queue from KBL-19 spec first.
-- signal_queue.id stays SERIAL PRIMARY KEY (INTEGER) — locked by KBL-A §5.

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
-- 2. kbl_runtime_state — key-value runtime flags (D8)
-- =============================================================================
-- D8 canonical spec: key-value, seeded with specific flag keys.
-- Seed keys per v2.3 D8 env-var table:
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
-- FK reconciliation per KBL-A §5: signal_id is INTEGER (matches
-- signal_queue.id SERIAL), FK with ON DELETE SET NULL so cost rows survive
-- the 30-day signal purge and aggregate rollups stay intact (per §5:199).

CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id       INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
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
-- DEBUG/INFO stay in local rotating files on Mac Mini; only WARN+ lands
-- here. CRITICAL rows additionally trigger a WhatsApp alert (dedupe via
-- the separate kbl_alert_dedupe table below, per KBL-A §5). INFO level
-- kept for vault-size telemetry (M3).
--
-- signal_id typed INTEGER + FK + ON DELETE SET NULL (same rationale as
-- kbl_cost_ledger: rollups survive signal purge).

CREATE TABLE IF NOT EXISTS kbl_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level       TEXT NOT NULL
                CHECK (level IN ('WARN', 'ERROR', 'CRITICAL', 'INFO')),
    component   TEXT NOT NULL,                            -- 'layer0'|'triage'|'pipeline'|'gold_promote'|'circuit_breaker'|'vault_size'|...
    signal_id   INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
    message     TEXT NOT NULL,                            -- short — full bodies stay in local file
    metadata    JSONB
);

CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level
    ON kbl_log ((ts::date), level);
CREATE INDEX IF NOT EXISTS idx_kbl_log_component
    ON kbl_log (component, ts);

-- =============================================================================
-- 5. kbl_alert_dedupe — CRITICAL WhatsApp alert suppression (KBL-A §5)
-- =============================================================================
-- Introduced by KBL-A §5 (not in v2.3 decisions doc directly). Mac Mini
-- pipeline writes a row on every CRITICAL-level kbl_log insert using
-- alert_key = '<component>_<first_16_chars_of_md5(message)>_<5min_bucket>'
-- (D15: 5-min dedupe by component + message hash). Second write in same
-- 5-min bucket increments send_count but skips the WhatsApp push.
--
-- Also reused for D14 cost-envelope alerts: alert_key = 'cost_80pct_YYYY-MM-DD'
-- ensures a given day's 80% notice fires exactly once.
--
-- Purge: nightly via scripts/kbl-purge-dedupe.sh on Mac Mini
-- (LaunchAgent com.brisen.kbl.purge-dedupe). Retention target: 14 days.

CREATE TABLE IF NOT EXISTS kbl_alert_dedupe (
    alert_key   TEXT PRIMARY KEY,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sent   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_count  INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_alert_dedupe_last_sent
    ON kbl_alert_dedupe (last_sent);

-- =============================================================================
-- 6. gold_promote_queue — Director /gold queue-poll (D2)
-- =============================================================================
-- D2 canonical spec (Director-signed 2026-04-17). WhatsApp /gold → WAHA
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
--   -- FK drops (safe: ON DELETE SET NULL means detach without row loss):
--   ALTER TABLE kbl_cost_ledger DROP CONSTRAINT IF EXISTS kbl_cost_ledger_signal_id_fkey;
--   ALTER TABLE kbl_log         DROP CONSTRAINT IF EXISTS kbl_log_signal_id_fkey;
--   -- Note: Postgres auto-names these <table>_<column>_fkey; confirm via
--   -- \d kbl_cost_ledger before running rollback.
--
--   -- New tables: keep in place, mark deprecated via COMMENT.
--   COMMENT ON TABLE kbl_runtime_state  IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_cost_ledger    IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_log            IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_alert_dedupe   IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE gold_promote_queue IS 'DEPRECATED <date> — rolled back from KBL-A';
--
-- Type changes beyond INTEGER↔BIGINT would require explicit down-migration
-- SQL per D12 and reviewer sign-off on a copy before dispatch.

-- End KBL_A_SCHEMA.sql
