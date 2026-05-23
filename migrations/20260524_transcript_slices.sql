-- TRANSCRIPT_CURATION_PHASE_1 — slice-level data layer
-- Per architecture v1 §1 (Q1 multi-desk routing) + E1 extended schema.
-- Additive only: existing meeting_transcripts table untouched (Phase 2 deprecates matter_slug).

CREATE TABLE IF NOT EXISTS transcript_slices (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES meeting_transcripts(id) ON DELETE CASCADE,

    -- Boundary metadata (Phase 1: whole-transcript placeholder; Phase 2 populates real boundaries)
    boundary_start INT NOT NULL DEFAULT 0,
    boundary_end INT NOT NULL DEFAULT 0,
    slice_text TEXT,
    chunk_header TEXT,

    -- Q1 multi-desk routing (Phase 2 populates via classifier)
    primary_desk TEXT,
    cross_ref_desks TEXT[] NOT NULL DEFAULT '{}',

    -- Q3 three-layer privacy (default desk-shared; Phase 2 routes personal slices)
    visibility TEXT NOT NULL DEFAULT 'desk-shared'
        CHECK (visibility IN ('desk-shared','director-personal','restricted')),

    -- Confidence scores (Phase 2 populates from boundary detector + classifier)
    confidence_boundary REAL,
    confidence_classifier REAL,

    -- E1 statement classification (Phase 2 populates)
    statement_type TEXT
        CHECK (statement_type IS NULL OR statement_type IN ('FACT','OPINION','DECISION','ACTION')),
    temporal_type TEXT,
    valid_at TIMESTAMPTZ,
    invalidated_by TEXT,

    -- Q7 privilege scope (Phase 2 populates)
    privilege_scope TEXT[] NOT NULL DEFAULT '{}',

    -- Routing provenance (Phase 2 populates: classifier model, version, override events)
    routing_provenance JSONB,

    -- Pipeline state machine
    status TEXT NOT NULL DEFAULT 'pending_classification'
        CHECK (status IN ('pending_classification','classified','overridden','quarantined')),

    -- §11.7 Hook 1: target_folder + cross_ref_stub_targets[] (Phase 2 populates)
    target_folder TEXT
        CHECK (target_folder IS NULL OR target_folder IN ('03_source_summaries','01_inbox','director-personal')),
    cross_ref_stub_targets JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_transcript_slices_status_primary_desk
    ON transcript_slices (status, primary_desk);
CREATE INDEX IF NOT EXISTS idx_transcript_slices_transcript_id
    ON transcript_slices (transcript_id);
CREATE INDEX IF NOT EXISTS idx_transcript_slices_visibility
    ON transcript_slices (visibility);
