-- STEP2-RESOLVE-IMPL: signal_queue.resolved_thread_paths column.
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP2-RESOLVE-IMPL (2026-04-18).
-- KBL-B §3 / §4.3: resolved_thread_paths is JSONB, NOT NULL, default []::jsonb.
-- Idempotent ADD COLUMN IF NOT EXISTS.


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue
    ADD COLUMN IF NOT EXISTS resolved_thread_paths JSONB NOT NULL DEFAULT '[]'::jsonb;

-- KBL-B §3 note: GIN index supports the "what else resolved to this thread?"
-- rollup query used by the dashboard + Director diagnostic tooling.
CREATE INDEX IF NOT EXISTS idx_signal_queue_resolved_thread_paths_gin
    ON signal_queue USING gin (resolved_thread_paths);

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_signal_queue_resolved_thread_paths_gin;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS resolved_thread_paths;
-- COMMIT;
