-- == migrate:up ==
-- AIRPORT_TICKETS_TERMINAL_COLUMNS_1 (BOX5_SCHEMA_FOUNDATION_1 / BRIEF-B):
-- additive terminal-classification axis on airport_tickets.
--
-- terminal_status is ORTHOGONAL to the live `status` lifecycle and to
-- `check_in_outcome` — do NOT expand either of those CHECKs. New axis only.
--
-- Mirror of orchestrator/airport_ticketing_bridge.ensure_airport_ticket_terminal_columns
-- — the two MUST stay in sync (Lesson #50). Additive + idempotent; all columns
-- nullable (or NOT NULL with a list DEFAULT) so it is safe on the already-
-- populated prod airport_tickets table.
--
-- 6-state terminal_status CHECK. VISIBLE_HOLD is DELIBERATELY EXCLUDED
-- (locked decision #4677.7) — it gets its own owner/TTL/escalation/sweep brief;
-- adding it now would make it prematurely writable. Do NOT add it.

ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_status TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_reason TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS project_code TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS matter_slug TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS desk_owner TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS confidence NUMERIC(3,2);
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS model_used TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS cost_tier TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS classification_version TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS registry_version TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_table TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_id TEXT;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_outcome_written_at TIMESTAMPTZ;

ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check;
ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_terminal_status_check
    CHECK (
        terminal_status IS NULL OR
        terminal_status IN (
            'DUPLICATE',
            'REJECT_NOISE',
            'REJECT_LOW_RELEVANCE',
            'FAST_TICKET',
            'TICKET',
            'FILE_UNSORTED'
        )
    );

-- == migrate:down ==
-- Disaster recovery only. Not auto-run (runner executes the whole file body;
-- keep rollback statements commented). To roll back manually:
-- ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_outcome_written_at;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS processed_at;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS raw_source_id;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS raw_source_table;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS manifest_match_signals;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS registry_version;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS classification_version;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS cost_tier;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS model_used;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS confidence;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS source_refs;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS desk_owner;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS matter_slug;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS project_code;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_reason;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS terminal_status;
