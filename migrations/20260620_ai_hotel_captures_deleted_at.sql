-- AI_HOTEL_DELETE_CARD_BUTTON_1: recoverable Field Notes delete.
--
-- Soft-delete captures by marking deleted_at. Raw capture rows and linked media
-- remain in Postgres/R2 for recovery and audit; the dashboard feed filters them.

-- == migrate:up ==

ALTER TABLE ai_hotel_captures
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ai_hotel_captures_active_created
    ON ai_hotel_captures (created_at DESC)
    WHERE deleted_at IS NULL;

-- == migrate:down ==
-- Deliberate rollback only. The migration runner executes this file raw, so keep
-- down SQL commented.
--
-- DROP INDEX IF EXISTS idx_ai_hotel_captures_active_created;
-- ALTER TABLE ai_hotel_captures DROP COLUMN IF EXISTS deleted_at;
