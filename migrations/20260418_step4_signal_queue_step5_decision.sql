-- == migrate:up ==
-- STEP4-CLASSIFY-IMPL: signal_queue columns for Step 4 output
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP4-CLASSIFY-IMPL (2026-04-18)
-- Additive, idempotent. ADD COLUMN IF NOT EXISTS throughout.
--
-- Columns written by kbl/steps/step4_classify.py.classify() per §4.5.
--
-- step_5_decision
--   TEXT. Value ∈ {'full_synthesis','stub_only','cross_link_only','skip_inbox'}.
--   NO CHECK constraint at the DB level per task §1 — enum is enforced in
--   Python (``kbl.steps.step4_classify.ClassifyDecision``). This avoids
--   double-source-of-truth problems; Phase 2 §5.1 two-track migration
--   revisits enum-at-DB semantics.
--
-- cross_link_hint
--   BOOLEAN. TRUE when classify chose ``FULL_SYNTHESIS`` for a signal
--   whose ``resolved_thread_paths == []`` but ``related_matters != []``
--   (Rule 4). Queryable from Step 6 without parsing extracted_entities.
--   Default FALSE so the column is safe against pre-Step-4 reads.
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260418_step4_signal_queue_step5_decision.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS step_5_decision TEXT;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS cross_link_hint BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS cross_link_hint;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS step_5_decision;
-- COMMIT;
