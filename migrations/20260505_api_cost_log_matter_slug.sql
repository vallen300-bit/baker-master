-- BAKER-COST-INSTRUMENTATION-1: per-matter spend attribution.
-- Nullable; existing rows stay NULL. Backfill not in scope.
-- Index is partial — only rows with non-NULL matter_slug are indexed.

ALTER TABLE api_cost_log ADD COLUMN IF NOT EXISTS matter_slug TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_api_cost_log_matter_slug
  ON api_cost_log (matter_slug)
  WHERE matter_slug IS NOT NULL;
