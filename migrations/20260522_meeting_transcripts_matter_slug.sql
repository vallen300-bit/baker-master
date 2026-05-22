-- PLAUD_TRANSCRIPT_BY_MATTER_1 — add matter_slug column + index
-- Director-ratified 2026-05-22 (bus #676 hag-desk path #2; bus #692 dispatch)

ALTER TABLE meeting_transcripts
    ADD COLUMN IF NOT EXISTS matter_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_matter_slug
    ON meeting_transcripts (matter_slug, meeting_date DESC NULLS LAST);
