-- == migrate:up ==
-- BRIEF_CORTEX_3T_FORMALIZE_1A: Cortex Stage 2 V1 — per-phase artifact persistence.
-- One row per phase output (sense, load, reason, propose, act, archive).
-- ON DELETE CASCADE wipes children when parent cycle row deleted.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS cortex_phase_outputs (
    output_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_id       UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
    phase          TEXT NOT NULL
        CHECK (phase IN ('sense','load','reason','propose','act','archive')),
    phase_order    INT NOT NULL,
    artifact_type  TEXT NOT NULL,
    payload        JSONB NOT NULL,
    citations      JSONB DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_phase_outputs_cycle_phase
    ON cortex_phase_outputs (cycle_id, phase_order);

COMMENT ON TABLE cortex_phase_outputs IS
  'BRIEF_CORTEX_3T_FORMALIZE_1A: phase-by-phase artifacts for a Cortex cycle. JSONB payload + JSONB citations for grounding.';

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_cortex_phase_outputs_cycle_phase;
-- DROP TABLE IF EXISTS cortex_phase_outputs;
