-- KBL-A Schema Draft
-- Status: DRAFT (pre-stage only — DO NOT apply until KBL-A brief ratifies).
-- Prepared-by: Code Brisen #2 (app)
-- Date: 2026-04-17
-- Aligns to: briefs/ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md (KBL-19 signal_queue spec)
--           briefs/DECISIONS_PRE_KBL_A_V2_DRAFT.md (D1–D12)
--
-- Design principles (match memory/store_back.py _ensure_* convention):
--   • All statements idempotent (CREATE TABLE IF NOT EXISTS, ALTER COLUMN IF NOT EXISTS)
--   • No destructive operations (no DROP, no TRUNCATE). Down-migration = soft-deprecate.
--   • Execute inside a single transaction; fail-closed if any statement errors.
--   • Indexes created after columns; CHECK constraints named so they can be dropped cleanly.
--
-- Apply via: BEGIN; \i KBL_A_SCHEMA.sql; COMMIT;  (or wrap in psycopg2 _ensure_kbl_a_schema).
-- Rollback procedure at bottom of file.

BEGIN;

-- =============================================================================
-- 1. signal_queue — additive columns + status enum expansion (KBL-19 / R1.10 / R1.11)
-- =============================================================================
-- Assumption: KBL-A main brief creates signal_queue from KBL-19 spec (see
-- ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md:264) as part of the infrastructure
-- bootstrap. This file only adds the V2 columns + status expansion.
--
-- If signal_queue does NOT yet exist at apply time, the ALTERs below will fail
-- fast — this is intentional. Ratification checklist: confirm signal_queue
-- was created before running this file.

ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS primary_matter TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS related_matters JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_confidence NUMERIC(3,2);

-- triage_confidence bounds: 0.00..1.00 (named so it can be dropped cleanly on rollback)
ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_triage_confidence_range;
ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_triage_confidence_range
    CHECK (triage_confidence IS NULL OR (triage_confidence >= 0 AND triage_confidence <= 1));

-- Expand status CHECK to include 'classified-deferred' (R1.11 inbox routing)
-- and 'failed-reviewed' (DLQ-after-Director-review). Named constraint so
-- rollback is clean.
--
-- PostgreSQL doesn't support ALTER CONSTRAINT; we DROP + ADD idempotently.
ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
    CHECK (status IN (
        'pending',
        'processing',
        'done',
        'failed',
        'expired',
        'classified-deferred',  -- NEW: R1.11 null-matter weekly review queue
        'failed-reviewed'       -- NEW: DLQ items Director has triaged
    ));

-- Indexes supporting triage queries (R1.10 primary_matter lookup)
CREATE INDEX IF NOT EXISTS idx_signal_queue_primary_matter
    ON signal_queue (primary_matter)
    WHERE primary_matter IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_signal_queue_related_matters_gin
    ON signal_queue USING gin (related_matters);

CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority
    ON signal_queue (status, priority, created_at);

-- =============================================================================
-- 2. kbl_runtime_state — single-row pipeline state (B3)
-- =============================================================================
-- Holds the KBL pipeline's current cursor: last processed signal id, last
-- cycle timestamp, shadow-vs-live mode flag, and the active model locks.
-- Single-writer (Mac Mini cron) so a 1-row singleton is fine.

CREATE TABLE IF NOT EXISTS kbl_runtime_state (
    id                      SMALLINT PRIMARY KEY DEFAULT 1,
    mode                    TEXT NOT NULL DEFAULT 'shadow'
                            CHECK (mode IN ('shadow', 'live', 'paused')),
    last_signal_id          BIGINT,
    last_cycle_started_at   TIMESTAMPTZ,
    last_cycle_finished_at  TIMESTAMPTZ,
    last_cycle_status       TEXT,   -- 'ok' | 'partial' | 'failed'
    active_triage_model     TEXT NOT NULL DEFAULT 'gemma4:latest',   -- D1
    active_fallback_model   TEXT NOT NULL DEFAULT 'qwen2.5:14b',     -- D1 cold-swap
    flags                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT kbl_runtime_state_singleton CHECK (id = 1)
);

INSERT INTO kbl_runtime_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 3. kbl_cost_ledger — per-signal cost tracking (M5 + M6)
-- =============================================================================
-- One row per (signal_id, step). Captures model, tokens, wall-time, $$.
-- Daily/weekly roll-ups computed on read. Keeps raw grain so attribution
-- stays auditable.

CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
    id               BIGSERIAL PRIMARY KEY,
    signal_id        BIGINT NOT NULL,
    step             TEXT NOT NULL,    -- 'triage' | 'resolve' | 'extract' | 'classify' | 'decide' | 'compile'
    model            TEXT NOT NULL,    -- 'gemma4:latest' | 'claude-opus-4-7' | ...
    provider         TEXT NOT NULL,    -- 'ollama' | 'anthropic'
    input_tokens     INT,
    output_tokens    INT,
    latency_ms       INT,
    usd_cost         NUMERIC(10,6) NOT NULL DEFAULT 0,
    outcome          TEXT,             -- 'ok' | 'retry' | 'fallback' | 'dlq'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kbl_cost_ledger_signal
    ON kbl_cost_ledger (signal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kbl_cost_ledger_day
    ON kbl_cost_ledger (date_trunc('day', created_at));
CREATE INDEX IF NOT EXISTS idx_kbl_cost_ledger_provider
    ON kbl_cost_ledger (provider, created_at);

-- =============================================================================
-- 4. kbl_log — structured execution log (M1)
-- =============================================================================
-- Step-level audit trail for the KBL pipeline. One row per step per signal.
-- Mirrors cortex_events pattern (memory/store_back.py:2654) but scoped to KBL
-- execution (not the generic event bus).

CREATE TABLE IF NOT EXISTS kbl_log (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT,                       -- null for cycle-level events
    cycle_id        UUID NOT NULL,                -- groups all events from one cron run
    step            TEXT NOT NULL,
    level           TEXT NOT NULL DEFAULT 'info'
                    CHECK (level IN ('debug', 'info', 'warn', 'error')),
    message         TEXT NOT NULL,
    payload         JSONB,
    host            TEXT,                          -- 'macmini' | 'render-web' | ...
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kbl_log_cycle ON kbl_log (cycle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kbl_log_signal ON kbl_log (signal_id, created_at) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kbl_log_errors ON kbl_log (created_at) WHERE level IN ('warn', 'error');

-- =============================================================================
-- 5. gold_promote_queue — Director promote-to-gold queue (S5 redirect)
-- =============================================================================
-- When Director flags a wiki page as gold (WhatsApp /gold or endpoint POST),
-- a row lands here. Mac Mini worker drains the queue idempotently: set
-- frontmatter `author: director`, commit, push. See D2 / R1.7 / R1.8.

CREATE TABLE IF NOT EXISTS gold_promote_queue (
    id               BIGSERIAL PRIMARY KEY,
    wiki_page_path   TEXT NOT NULL,
    requested_by     TEXT NOT NULL,               -- 'whatsapp:41799605092@c.us' | 'endpoint' | ...
    requested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'noop', 'failed')),
    processed_at     TIMESTAMPTZ,
    commit_sha       TEXT,                         -- set when promoted & pushed
    error            TEXT,
    attempts         SMALLINT NOT NULL DEFAULT 0
);

-- Idempotency: one pending promotion per wiki page at a time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_gold_promote_unique_pending
    ON gold_promote_queue (wiki_page_path)
    WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_gold_promote_status
    ON gold_promote_queue (status, requested_at);

COMMIT;

-- =============================================================================
-- Rollback / soft-deprecation notes
-- =============================================================================
-- Principle: never DROP a column or table in production. Soft-deprecate so a
-- forward-rolling deploy can't lose data via rollback+replay.
--
-- To reverse this migration WITHOUT data loss:
--
--   -- signal_queue: no drops; only the widened CHECK is narrowed back.
--   ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
--   ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
--       CHECK (status IN ('pending','processing','done','failed','expired'));
--   -- (columns primary_matter, related_matters, triage_confidence left in place,
--   --  null/empty default keeps them harmless)
--
--   -- New tables: leave in place, mark deprecated via comment.
--   COMMENT ON TABLE kbl_runtime_state IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_cost_ledger   IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE kbl_log           IS 'DEPRECATED <date> — rolled back from KBL-A';
--   COMMENT ON TABLE gold_promote_queue IS 'DEPRECATED <date> — rolled back from KBL-A';
--
-- If a true DROP is ever required (e.g. schema rewrite in KBL-G), do it in a
-- separate, explicitly-gated migration AFTER at least one full retention cycle
-- with no writes.

-- End KBL_A_SCHEMA.sql
