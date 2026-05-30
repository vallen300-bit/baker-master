-- BRIEF_DOSSIER_ROOM_READ_1: matter_slug for the dossier-engine resolver's
-- explicit-column path (Codex C1).
--
-- Idempotent + no-op-safe: prod already has the column per Codex C1
-- verification 2026-05-30. This migration closes the in-repo bootstrap drift
-- so fresh dev / test / ephemeral-Neon DBs match prod.
--
-- Nullable; existing rows stay NULL. No backfill — resolver Step 2/3 (alias
-- and metadata) handle the no-explicit-slug case. Partial index — only rows
-- with non-NULL matter_slug are indexed (matches api_cost_log pattern).

ALTER TABLE research_proposals ADD COLUMN IF NOT EXISTS matter_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_rp_matter_slug
  ON research_proposals (matter_slug)
  WHERE matter_slug IS NOT NULL;
