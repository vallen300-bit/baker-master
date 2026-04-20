-- == migrate:up ==
-- Add language column to rss_feeds so the pipeline can route DE/FR items
-- through translation before Layer 0 classification (per 2026-04-20 RSS
-- bulk-insert of 25 feeds across 8 active clusters). Existing rows keep
-- NULL language; updated in a follow-up bulk UPDATE after migration lands.

ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS language TEXT;

COMMENT ON COLUMN rss_feeds.language IS
  'ISO 639-1 code (en / de / fr). NULL allowed for feeds predating 2026-04-20; pipeline falls back to content-language detection when NULL.';
