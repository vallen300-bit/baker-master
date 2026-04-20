-- == migrate:up ==
-- STEP6-FINALIZE-IMPL: signal_queue columns for Pydantic-validated Silver output
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STEP6-FINALIZE-IMPL (2026-04-19)
-- Additive, idempotent.
--
-- final_markdown
--   TEXT — the Pydantic-round-tripped canonical Silver document
--   (YAML frontmatter + Markdown body). Written by
--   kbl.steps.step6_finalize.finalize() on the happy path. Step 7 reads
--   this column + writes the file at target_vault_path under flock on
--   Mac Mini (Inv 9: Mac Mini is the sole vault FS writer).
--
-- target_vault_path
--   TEXT — canonical path under baker-vault, e.g.
--   'wiki/ao/2026-04-19_tonbach-commit.md'. Step 6 builds; Step 7
--   realizes. Regex-validated in Step 6 before write.
--
-- Apply order: manual operator run.
--   BEGIN; \i migrations/20260419_step6_signal_queue_final_markdown.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS final_markdown TEXT;

ALTER TABLE signal_queue
  ADD COLUMN IF NOT EXISTS target_vault_path TEXT;

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run.
--
-- BEGIN;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS target_vault_path;
-- ALTER TABLE signal_queue DROP COLUMN IF EXISTS final_markdown;
-- COMMIT;
