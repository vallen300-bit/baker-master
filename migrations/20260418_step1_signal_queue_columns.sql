-- == migrate:up ==
-- STEP1-TRIAGE-IMPL: signal_queue columns for Step 1 output
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP1-TRIAGE-IMPL (2026-04-18)
-- Additive, idempotent. ADD COLUMN IF NOT EXISTS throughout.
--
-- Columns written by kbl/steps/step1_triage.py.triage() per §4.2 contract
-- in briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md. Column types follow the
-- dispatch language verbatim:
--   - related_matters TEXT[] (dispatch) — KBL_A_SCHEMA.sql v3 uses JSONB;
--     we take the dispatch word here and let a future reconciliation PR
--     align the two when KBL-A lands. The writer already handles both
--     shapes via psycopg2's native adaptation.
--
-- kbl_cost_ledger table creation is NOT in scope of this migration — that
-- table is provisioned by KBL-A. Step 1 writes INTO it assuming it's
-- already created. If it's absent at runtime the insert fails loudly,
-- which is the intended fail-fast signal that KBL-A needs to land first.
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260418_step1_signal_queue_columns.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS primary_matter     TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS related_matters    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS vedana             TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_score       NUMERIC;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_confidence  NUMERIC;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_summary     TEXT;

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run. Paste into psql if a full rollback
-- of Step 1 column provisioning is required. Columns are nullable-by-design
-- (except related_matters which defaults to an empty array), so leaving
-- them in place is also safe — rollback is optional.
--
-- BEGIN;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS triage_summary;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS triage_confidence;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS triage_score;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS vedana;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS related_matters;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS primary_matter;
-- COMMIT;
