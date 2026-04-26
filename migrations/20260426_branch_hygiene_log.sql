-- == migrate:up ==
-- BRANCH_HYGIENE_1 audit log table
--
-- Records every branch deletion (L1 squash auto + L3 Director-confirmed batch).
-- Append-only; queries by branch_name OR layer for the weekly digest.

CREATE TABLE IF NOT EXISTS branch_hygiene_log (
    id              BIGSERIAL PRIMARY KEY,
    branch_name     TEXT        NOT NULL,
    last_commit_sha TEXT        NOT NULL,
    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    layer           TEXT        NOT NULL,  -- 'L1' | 'L2_FLAGGED' | 'L3'
    reason          TEXT        NOT NULL DEFAULT '',
    age_days        INT         NOT NULL DEFAULT 0,
    actor           TEXT        NOT NULL DEFAULT 'branch_hygiene'
);

CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_deleted_at
    ON branch_hygiene_log (deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_layer
    ON branch_hygiene_log (layer);
CREATE INDEX IF NOT EXISTS idx_branch_hygiene_log_branch_name
    ON branch_hygiene_log (branch_name);

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_branch_hygiene_log_branch_name;
-- DROP INDEX IF EXISTS idx_branch_hygiene_log_layer;
-- DROP INDEX IF EXISTS idx_branch_hygiene_log_deleted_at;
-- DROP TABLE IF EXISTS branch_hygiene_log;
