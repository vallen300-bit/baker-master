-- == migrate:up ==
-- M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1
-- Add a source/provider column to email_messages so the merged mail store and
-- baker_email_search are source-aware (graph = Outlook/M365, email = Gmail,
-- exchange = legacy EWS). Populated from the ingest trigger metadata
-- (graph_mail_trigger sets source='graph'). Idempotent; mirrors the self-heal
-- ALTER in memory/store_back.py::_ensure_email_messages_table.

BEGIN;

ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS source TEXT;

-- Helper index for source-filtered, recency-ordered reads from baker_email_search.
CREATE INDEX IF NOT EXISTS idx_email_messages_source_received
    ON email_messages (source, received_date DESC);

COMMIT;
