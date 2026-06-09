-- == migrate:up ==
-- M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1
-- Add a source/provider column to email_messages so the merged mail store and
-- baker_email_search are source-aware (graph = Outlook/M365, email = Gmail,
-- exchange = legacy EWS). Populated from the ingest trigger metadata
-- (graph_mail_trigger sets source='graph'). Idempotent; mirrors the self-heal
-- ALTER in memory/store_back.py::_ensure_email_messages_table.

BEGIN;

ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS source TEXT;

-- Backfill existing rows (codex #2639: the column is forward-only otherwise —
-- email_trigger dedups already-processed thread_ids, so old Graph mail would
-- never get source filled and a source='graph' filter would miss all 200+
-- historical M365 rows). Microsoft Graph immutable IDs are long base64url that
-- begin with 'AAQk'/'AAMk'; Gmail IDs are short hex / RFC message-ids. This
-- prefix heuristic labels the existing Graph mail; new mail is labelled at write.
UPDATE email_messages
   SET source = 'graph'
 WHERE source IS NULL
   AND (message_id LIKE 'AAQk%' OR message_id LIKE 'AAMk%');

-- Gmail / legacy mail: short 16-hex Gmail ids or RFC message-ids ('<id>@domain').
UPDATE email_messages
   SET source = 'email'
 WHERE source IS NULL
   AND (message_id ~ '^[0-9a-f]{16}$' OR message_id LIKE '%@%');

-- Helper index for source-filtered, recency-ordered reads from baker_email_search.
CREATE INDEX IF NOT EXISTS idx_email_messages_source_received
    ON email_messages (source, received_date DESC);

COMMIT;
