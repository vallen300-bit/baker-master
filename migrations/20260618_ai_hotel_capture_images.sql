-- AI_HOTEL_CAPTURE_UPGRADES_1: multiple photos per capture + audio provenance.
--
-- Extends AI_HOTEL_FIELD_CAPTURE_1 so one field capture can carry several
-- photos (business card + face + product) attached before a single Send, plus
-- a dictated audio transcript. Photos move to a child table — base64 JPEGs are
-- ~500KB each and several inline would bloat the parent row and make the list
-- query heavy. Order is preserved via ``ordinal``. Existing single-image rows
-- are backfilled as ordinal=0 children. The parent image_b64/image_media
-- columns stay in place (nullable) for the transition; a later cleanup
-- migration drops them once every read uses the child table.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS ai_hotel_capture_images (
    id          BIGSERIAL PRIMARY KEY,
    capture_id  BIGINT NOT NULL REFERENCES ai_hotel_captures(id) ON DELETE CASCADE,
    ordinal     INT NOT NULL DEFAULT 0,
    image_b64   TEXT,                 -- resized JPEG base64 (cap ~500KB, mirrors parent)
    image_media TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_hotel_capture_images_capture
    ON ai_hotel_capture_images (capture_id, ordinal);

-- Backfill: every existing parent row that has an inline image becomes an
-- ordinal=0 child row. Idempotent — the NOT EXISTS guard means a re-run (or a
-- fresh DB where the loop is empty) is a no-op, never a duplicate.
INSERT INTO ai_hotel_capture_images (capture_id, ordinal, image_b64, image_media)
SELECT c.id, 0, c.image_b64, c.image_media
  FROM ai_hotel_captures c
 WHERE c.image_b64 IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM ai_hotel_capture_images i WHERE i.capture_id = c.id
   );

-- Add 'audio' to the source provenance CHECK so an audio-only dictation is
-- visibly source='audio'. The original inline CHECK on ai_hotel_captures is
-- auto-named ai_hotel_captures_source_check by Postgres; drop-if-exists then
-- re-add the superset constraint (all existing 'photo'/'note' rows still pass).
ALTER TABLE ai_hotel_captures
    DROP CONSTRAINT IF EXISTS ai_hotel_captures_source_check;
ALTER TABLE ai_hotel_captures
    ADD CONSTRAINT ai_hotel_captures_source_check
    CHECK (source IN ('photo', 'note', 'audio'));

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- undo the migration it just applied on first deploy. Paste into psql when a
-- deliberate rollback is needed.
--
-- BEGIN;
-- ALTER TABLE ai_hotel_captures DROP CONSTRAINT IF EXISTS ai_hotel_captures_source_check;
-- ALTER TABLE ai_hotel_captures ADD CONSTRAINT ai_hotel_captures_source_check
--     CHECK (source IN ('photo', 'note'));
-- DROP TABLE IF EXISTS ai_hotel_capture_images;
-- COMMIT;
