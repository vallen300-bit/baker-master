-- AI_HOTEL_OBJECT_STORAGE_R2_1: metadata for R2-backed field-capture media.
--
-- Binary video/image/audio objects live in Cloudflare R2. This table stores
-- only metadata + object keys linked to the existing ai_hotel_captures parent.
-- The existing base64 photo/audio tables are untouched for compatibility.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS ai_hotel_capture_media (
    id               BIGSERIAL PRIMARY KEY,
    capture_id       BIGINT NOT NULL REFERENCES ai_hotel_captures(id) ON DELETE CASCADE,
    media_type       TEXT NOT NULL,
    storage_key      TEXT NOT NULL,
    thumbnail_key    TEXT,
    content_type     TEXT NOT NULL,
    size_bytes       BIGINT NOT NULL,
    duration_seconds REAL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_capture_media_capture
    ON ai_hotel_capture_media (capture_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_capture_media_storage_key
    ON ai_hotel_capture_media (storage_key);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.ai_hotel_capture_media'::regclass
           AND conname = 'ai_hotel_capture_media_media_type_check'
    ) THEN
        ALTER TABLE ai_hotel_capture_media
            ADD CONSTRAINT ai_hotel_capture_media_media_type_check
            CHECK (media_type IN ('video', 'image', 'audio'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.ai_hotel_capture_media'::regclass
           AND conname = 'ai_hotel_capture_media_size_bytes_nonneg'
    ) THEN
        ALTER TABLE ai_hotel_capture_media
            ADD CONSTRAINT ai_hotel_capture_media_size_bytes_nonneg
            CHECK (size_bytes >= 0);
    END IF;
END
$$;

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- drop the table it just created on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- DROP TABLE IF EXISTS ai_hotel_capture_media;
-- COMMIT;
