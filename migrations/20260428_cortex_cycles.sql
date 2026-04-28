-- == migrate:up ==
-- BRIEF_CORTEX_3T_FORMALIZE_1A: Cortex Stage 2 V1 — cycle persistence.
-- One row per Cortex reasoning cycle (sense → load → reason → propose → act → archive).
-- Spec: _ops/ideas/2026-04-27-cortex-3t-formalize-spec.md (RA-22)
-- Architecture: _ops/processes/cortex-architecture-final.md (RA-23)
--
-- Idempotent and additive. Applied by config/migration_runner.py on Render boot
-- (lesson #35/#37). Bootstrap mirror in memory/store_back.py for offline parity.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS cortex_cycles (
    cycle_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    matter_slug        TEXT NOT NULL,
    triggered_by       TEXT NOT NULL,
        -- 'signal' / 'director' / 'cron' / 'gold_comment' / 'refresh'
    trigger_signal_id  BIGINT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    last_loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        -- updated on each refresh; used by final-freshness check (1C)
    current_phase      TEXT NOT NULL DEFAULT 'sense'
        CHECK (current_phase IN ('sense','load','reason','propose','act','archive')),
    status             TEXT NOT NULL DEFAULT 'in_flight'
        CHECK (status IN ('in_flight','awaiting_reason','proposed','tier_b_pending','approved','rejected','modified','failed','superseded','abandoned')),
    proposal_id        UUID,
    director_action    TEXT,
        -- 'gold_approved' / 'gold_modified' / 'gold_rejected' / 'refresh_requested'
    feedback_ledger_id BIGINT,
    cost_tokens        INTEGER DEFAULT 0,
    cost_dollars       NUMERIC(10,4) DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_cycles_matter_status
    ON cortex_cycles (matter_slug, status, started_at DESC);

COMMENT ON TABLE cortex_cycles IS
  'BRIEF_CORTEX_3T_FORMALIZE_1A: per-cycle row for Cortex Stage 2 reasoning. Phase artifacts live in cortex_phase_outputs.';

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_cortex_cycles_matter_status;
-- DROP TABLE IF EXISTS cortex_cycles;
