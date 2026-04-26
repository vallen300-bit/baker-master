-- == migrate:up ==
-- AMEX_RECURRING_DEADLINE_1: add recurrence support to deadlines.
--
-- Anchor case: AmEx (#1438) — Director note "has to be a cron job every month
-- to avoid missing payment." Builder spec _ops/ideas/2026-04-26-amex-recurring-deadline-1.md.
--
-- Bootstrap mirror at memory/store_back.py:_ensure_deadlines_recurrence_columns.
-- Migration-vs-bootstrap diff must be empty per Code Brief Standard #4.
--
-- Columns:
--   recurrence              — one of NULL (one-shot) | 'monthly' | 'weekly' | 'quarterly' | 'annual'
--   recurrence_anchor_date  — DATE; reference for compute_next_due()
--   recurrence_count        — INT; auto-incremented per respawn
--   parent_deadline_id      — INT; FK to original deadline (chain traceability)

ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS recurrence TEXT;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS recurrence_anchor_date DATE;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS recurrence_count INT NOT NULL DEFAULT 0;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS parent_deadline_id INT;

CREATE INDEX IF NOT EXISTS idx_deadlines_recurrence
    ON deadlines(recurrence) WHERE recurrence IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deadlines_parent
    ON deadlines(parent_deadline_id) WHERE parent_deadline_id IS NOT NULL;

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_deadlines_parent;
-- DROP INDEX IF EXISTS idx_deadlines_recurrence;
-- ALTER TABLE deadlines DROP COLUMN IF EXISTS parent_deadline_id;
-- ALTER TABLE deadlines DROP COLUMN IF EXISTS recurrence_count;
-- ALTER TABLE deadlines DROP COLUMN IF EXISTS recurrence_anchor_date;
-- ALTER TABLE deadlines DROP COLUMN IF EXISTS recurrence;
