-- AI_HOTEL_VOICE_FORM_SUPPLIER_1: structured form-draft records.
--
-- A typed, reusable record (v1: supplier card) extracted from a field capture's
-- dictation/note. The record sits BESIDE the raw capture, never replaces it —
-- one child row per draft, linked to ai_hotel_captures by capture_id. The raw
-- base64 photos/audio stay in ai_hotel_captures / ai_hotel_capture_images; this
-- table NEVER duplicates them (codex-arch #3349).
--
-- status lifecycle: draft (extracted, unreviewed) → confirmed (user reviewed +
-- explicit save) | discarded (user kept the raw note only). No record is ever
-- 'confirmed' without an explicit review action — auto-confirm is banned.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS ai_hotel_form_records (
    id                     BIGSERIAL PRIMARY KEY,
    capture_id             BIGINT NOT NULL REFERENCES ai_hotel_captures(id) ON DELETE CASCADE,
    form_type              TEXT NOT NULL,
    schema_version         TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'confirmed', 'discarded')),
    extracted_json         JSONB,        -- raw model-extracted + normalized values
    corrected_json         JSONB,        -- user-corrected values (set at confirm)
    field_meta_json        JSONB,        -- per-field confidence/evidence/needs_review
    validation_errors_json JSONB,        -- deterministic-validator errors at extraction
    model                  TEXT,
    prompt_version         TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_form_records_type_status_created
    ON ai_hotel_form_records (form_type, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_form_records_capture
    ON ai_hotel_form_records (capture_id);

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- drop the table it just created on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- DROP TABLE IF EXISTS ai_hotel_form_records;
-- COMMIT;
