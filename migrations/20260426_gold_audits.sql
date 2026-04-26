-- == migrate:up ==
-- GOLD_COMMENT_WORKFLOW_1 schema migration.
--
-- gold_audits         — weekly Gold corpus audit records (1 row per Mon 09:30 UTC fire).
-- gold_write_failures — failure log for gold_writer.append guard rejections.
--
-- Bootstrap mirror lives at memory/store_back.py:_ensure_gold_audits_table /
-- _ensure_gold_write_failures_table. Migration-vs-bootstrap diff must be
-- empty per Code Brief Standard #4.

CREATE TABLE IF NOT EXISTS gold_audits (
    id            SERIAL PRIMARY KEY,
    ran_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    issues_count  INT NOT NULL DEFAULT 0,
    payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_gold_audits_ran_at
    ON gold_audits(ran_at DESC);

CREATE TABLE IF NOT EXISTS gold_write_failures (
    id            SERIAL PRIMARY KEY,
    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_path   TEXT NOT NULL,
    error         TEXT NOT NULL,
    caller_stack  TEXT,
    payload_jsonb JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_gold_write_failures_attempted_at
    ON gold_write_failures(attempted_at DESC);

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_gold_write_failures_attempted_at;
-- DROP TABLE IF EXISTS gold_write_failures;
-- DROP INDEX IF EXISTS idx_gold_audits_ran_at;
-- DROP TABLE IF EXISTS gold_audits;
