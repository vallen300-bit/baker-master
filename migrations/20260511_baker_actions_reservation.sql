-- 20260511_baker_actions_reservation.sql
-- Pattern B atomicity closure for Tier B runtime: add reserved_at +
-- partial index supporting reservation-aware cap reads.
--
-- BRIEF_CORTEX_TIER_B_ATOMICITY_V1, Director-ratified 2026-05-10.

BEGIN;

ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ;

-- Index supports the reservation-aware cap read in enforce():
--   ... WHERE tier='B' AND cost_eur IS NOT NULL
--         AND ((committed_at IS NOT NULL AND committed_at >= <bucket>)
--           OR (committed_at IS NULL AND reserved_at >= NOW() - INTERVAL '15 minutes'))
-- We keep the existing idx_baker_actions_tier_b_committed (committed_at)
-- and add a sibling on reserved_at for the second branch of the OR.
CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_reserved
    ON baker_actions (reserved_at)
    WHERE tier = 'B' AND cost_eur IS NOT NULL AND committed_at IS NULL;

COMMIT;
