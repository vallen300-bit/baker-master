-- BAKER_DASHBOARD_V2_EVIDENCE_PACKET_1: durable evidence-packet schema.
--
-- Baker Dashboard V2 ("Verified Operating Room") separates raw catching from
-- verified judgment. This migration adds the three tables that carry that
-- contract:
--   * signal_candidates  — raw-capture staging (ingestion is the NEXT brief).
--   * verified_items     — the durable object Baker can stand behind. Carries
--                          claim, evidence, confidence, owner, counterargument,
--                          and moves candidate -> verified -> ratified / dismissed.
--   * verification_events — append-only audit trail; every state change writes
--                          one row in the SAME transaction as the state change.
--
-- HARD invariants encoded at the DB layer (defence-in-depth behind the Python
-- model validation in models/verified_items.py):
--   * state CHECK pins the 4 legal states.
--   * a `dismissed` row MUST carry a structured dismiss_reason.
--   * a `verified`/`ratified` row MUST carry a complete evidence packet
--     (non-empty source_refs + confidence + source_trust + verification_summary
--      + counterargument; `claim` is NOT NULL for every row).
--
-- MODEL PROVENANCE (codex-arch addendum #3748): extraction_model + source_model
-- record which model produced the candidate content. This is a STORAGE/CONTRACT
-- concern only — it does NOT enforce the no-Flash-into-trusted-surfaces bar.
-- That enforcement lives in BAKER_DASHBOARD_V2_MODEL_LOCK_1 (b4 lane). Nothing
-- here creates a path that promotes Flash-sourced extraction to `verified`.
--
-- Additive + idempotent + runner-safe: config/migration_runner.py applies the
-- whole file in ONE per-file transaction, so NO `CREATE INDEX CONCURRENTLY`
-- (cannot run inside a tx block). All DDL is IF NOT EXISTS.
--
-- ROLLBACK: deliberate disaster-recovery only. The runner executes this file
-- raw, so the DOWN section ships commented (it would otherwise drop the tables
-- it just created on first deploy). The pytest round-trip strips the `-- `
-- leader to replay it, so the DOWN section below holds ONLY commented SQL —
-- all prose lives here, above the markers. Drop order reverses UP (FK
-- dependants first): verification_events, verified_items, signal_candidates.

-- == migrate:up ==

-- Raw-capture staging. Sentinels write here in the next brief; this brief only
-- creates the base table so downstream work has a stable target.
CREATE TABLE IF NOT EXISTS signal_candidates (
    id                    BIGSERIAL PRIMARY KEY,
    raw_source_table      TEXT NOT NULL,
    raw_source_id         TEXT NOT NULL,
    candidate_type        TEXT NOT NULL,
    summary               TEXT NOT NULL,
    extraction_model      TEXT NOT NULL,
    extraction_confidence TEXT,
    source_model          TEXT,
    matter_slug           TEXT,
    people                JSONB NOT NULL DEFAULT '[]',
    source_trust          TEXT,
    status                TEXT NOT NULL DEFAULT 'awaiting_verification',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_candidates_status
    ON signal_candidates (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_source
    ON signal_candidates (raw_source_table, raw_source_id);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_matter
    ON signal_candidates (matter_slug);

-- The durable promotion object. `state` starts at 'candidate' and is moved only
-- via models.verified_items.transition_item (which writes a verification_events
-- row in the same transaction).
CREATE TABLE IF NOT EXISTS verified_items (
    id                   BIGSERIAL PRIMARY KEY,
    state                TEXT NOT NULL DEFAULT 'candidate'
                         CHECK (state IN ('candidate', 'verified', 'ratified', 'dismissed')),
    item_type            TEXT NOT NULL,
    claim                TEXT NOT NULL,
    why_matters          TEXT,
    next_action          TEXT,
    owner                TEXT,
    due_at               TIMESTAMPTZ,
    confidence           TEXT CHECK (confidence IS NULL OR confidence IN ('high', 'medium', 'low')),
    matter_slug          TEXT,
    related_matters      JSONB NOT NULL DEFAULT '[]',
    people               JSONB NOT NULL DEFAULT '[]',
    source_type          TEXT,
    source_trust         TEXT,
    source_refs          JSONB NOT NULL DEFAULT '[]',
    verification_summary TEXT,
    counterargument      TEXT,
    dismiss_reason       TEXT CHECK (
                             dismiss_reason IS NULL OR dismiss_reason IN (
                                 'marketing', 'duplicate', 'wrong_matter', 'stale',
                                 'not_important', 'already_handled', 'system_noise',
                                 'false_deadline', 'false_promise', 'other'
                             )
                         ),
    signal_candidate_id  BIGINT REFERENCES signal_candidates(id),
    -- actor + model provenance (brief field 18 + codex-arch addendum #3748)
    created_by           TEXT NOT NULL,
    extraction_model     TEXT,
    source_model         TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- AC6: dismissed rows must carry a structured reason.
    CONSTRAINT verified_items_dismiss_reason_required
        CHECK (state <> 'dismissed' OR dismiss_reason IS NOT NULL),
    -- AC4: verified/ratified rows must carry a complete evidence packet.
    -- source_refs must be a NON-EMPTY JSON ARRAY (not just <> '[]', which a raw
    -- INSERT could satisfy with '{}'::jsonb or a scalar). The CASE guards
    -- jsonb_array_length so it is never called on a non-array value — Postgres
    -- does not guarantee AND short-circuits, but CASE branch evaluation is
    -- guaranteed conditional.
    CONSTRAINT verified_items_evidence_packet_required
        CHECK (
            state NOT IN ('verified', 'ratified')
            OR (
                confidence IS NOT NULL
                AND source_trust IS NOT NULL
                AND verification_summary IS NOT NULL
                AND counterargument IS NOT NULL
                AND CASE
                        WHEN jsonb_typeof(source_refs) = 'array'
                        THEN jsonb_array_length(source_refs) > 0
                        ELSE false
                    END
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_verified_items_state
    ON verified_items (state);
CREATE INDEX IF NOT EXISTS idx_verified_items_state_matter
    ON verified_items (state, matter_slug);
CREATE INDEX IF NOT EXISTS idx_verified_items_item_type
    ON verified_items (item_type);
CREATE INDEX IF NOT EXISTS idx_verified_items_matter
    ON verified_items (matter_slug);
CREATE INDEX IF NOT EXISTS idx_verified_items_people
    ON verified_items USING GIN (people);

-- Append-only audit trail. One row per state change (incl. creation: NULL -> candidate).
CREATE TABLE IF NOT EXISTS verification_events (
    id               BIGSERIAL PRIMARY KEY,
    verified_item_id BIGINT NOT NULL REFERENCES verified_items(id) ON DELETE CASCADE,
    from_state       TEXT,
    to_state         TEXT NOT NULL,
    actor_type       TEXT NOT NULL,
    actor_id         TEXT NOT NULL,
    rationale        TEXT,
    model            TEXT,
    evidence_delta   JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_verification_events_item
    ON verification_events (verified_item_id, created_at);

-- == migrate:down ==
-- DROP TABLE IF EXISTS verification_events;
-- DROP TABLE IF EXISTS verified_items;
-- DROP TABLE IF EXISTS signal_candidates;
