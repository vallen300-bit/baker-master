-- == migrate:up ==
-- BRIDGE_HOT_MD_AND_TUNING_1: record which hot.md pattern promoted a
-- signal (NULL when another axis fired). Enables downstream analytics
-- on how often Director's weekly priorities actually produce matches,
-- and lets review surfaces label promotes as "Director-curated".
--
-- Idempotent and additive.

ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS hot_md_match TEXT;

COMMENT ON COLUMN signal_queue.hot_md_match IS
  'BRIDGE_HOT_MD_AND_TUNING_1: hot.md pattern (one line) that promoted this signal; NULL when another axis fired.';


-- == migrate:down ==
-- Column is additive + nullable; rollback only if the bridge hot.md
-- path is deliberately retired. Paste into psql if needed:
--
-- BEGIN;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS hot_md_match;
-- COMMIT;
