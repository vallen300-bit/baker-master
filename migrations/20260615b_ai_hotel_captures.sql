-- AI_HOTEL_FIELD_CAPTURE_1: one-tap mobile photo/voice capture store.
--
-- Captures snapped/dictated by the chairman on the HiTEC floor land here,
-- LLM-classified into one AI-Hotel dashboard section, rendered live in the
-- "Field notes" surface. Render FS is ephemeral — the resized image lives as
-- base64 TEXT in Postgres (NOT on disk) so captures survive every redeploy.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS ai_hotel_captures (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        TEXT NOT NULL CHECK (source IN ('photo','note')),
    note_text     TEXT,
    image_b64     TEXT,                 -- resized JPEG base64 (NULL for note-only); cap ~500KB
    image_media   TEXT,
    section_guess TEXT NOT NULL DEFAULT 'general'
                  CHECK (section_guess IN ('use_case','stakeholder','research','comms','general')),
    related_area  TEXT,
    summary       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new','promoted','dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_captures_created ON ai_hotel_captures (created_at DESC);

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- drop the table it just created on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- DROP TABLE IF EXISTS ai_hotel_captures;
-- COMMIT;
