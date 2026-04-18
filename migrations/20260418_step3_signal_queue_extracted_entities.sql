-- STEP3-EXTRACT-IMPL: signal_queue column for Step 3 output
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP3-EXTRACT-IMPL (2026-04-18)
-- Additive, idempotent. ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
--
-- Column written by kbl/steps/step3_extract.py.extract() per the §4.4 schema
-- in briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md. The writer stores the
-- structured entities object as JSONB — shape is always an object with
-- exactly six array-valued keys: people, orgs, money, dates, references,
-- action_items. An empty stub (all six arrays empty) is the zero-result
-- contract; NULL is explicitly not used (default '{}'::jsonb).
--
-- GIN index enables downstream filters such as
--   WHERE extracted_entities->'money' @> '[{"currency":"CHF"}]'
-- without a full-table scan. Safe to create with CONCURRENTLY if the table
-- is already populated (not done here because IF NOT EXISTS + transaction
-- is fine for current row counts; tune if this migration ever runs hot).
--
-- kbl_cost_ledger is NOT provisioned here; KBL-A owns that table. Step 3
-- writes INTO it assuming it exists (fail-fast signal if absent).
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260418_step3_signal_queue_extracted_entities.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS extracted_entities JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_signal_queue_extracted_entities_gin
  ON signal_queue USING gin (extracted_entities);

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_signal_queue_extracted_entities_gin;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS extracted_entities;
-- COMMIT;
