-- KBL-A §5 / D14+D15 schema — DDL originally in memory/store_back.py:6514, 6562
-- Promoted to migration 2026-04-19 after production discovery: Python-embedded
-- DDL never ran on Render, pipeline would crash on first Step 5 cost write +
-- first WARN log. Idempotent IF NOT EXISTS throughout. Safe to run repeatedly.
-- Applied to production Neon 2026-04-19 by AI Head per Director authorization;
-- future service-account-triggered migration runner (MIGRATION_RUNNER_1) picks
-- this file up via the schema_migrations tracking table on next startup.

-- kbl_cost_ledger: KBL-A §5 / D14 per-call cost tracking.
-- FK to signal_queue with ON DELETE SET NULL so cost rows survive the
-- 30-day signal purge.
CREATE TABLE IF NOT EXISTS kbl_cost_ledger (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id      INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
    step           TEXT NOT NULL,
    model          TEXT,
    input_tokens   INT,
    output_tokens  INT,
    latency_ms     INT,
    cost_usd       NUMERIC(10,6) NOT NULL DEFAULT 0,
    success        BOOLEAN NOT NULL DEFAULT TRUE,
    metadata       JSONB
);

-- Note: ((ts::date)) rejected by modern Postgres (TIMESTAMPTZ→date is
-- VOLATILE because it depends on the session timezone). Using
-- ((ts AT TIME ZONE 'UTC')::date) — identical semantic, IMMUTABLE
-- because UTC is a literal. store_back.py's bare `ts::date` predates
-- this enforcement and will need the same fix when that code path runs.
CREATE INDEX IF NOT EXISTS idx_cost_ledger_day
    ON kbl_cost_ledger (((ts AT TIME ZONE 'UTC')::date));

CREATE INDEX IF NOT EXISTS idx_cost_ledger_signal
    ON kbl_cost_ledger (signal_id, ts) WHERE signal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cost_ledger_step_day
    ON kbl_cost_ledger (step, ((ts AT TIME ZONE 'UTC')::date));

-- kbl_log: KBL-A §5 / D15 WARN+ central log. INFO routed to local rotating
-- files only (R1.S2 / R1.S12). FK to signal_queue with ON DELETE SET NULL.
CREATE TABLE IF NOT EXISTS kbl_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level      TEXT NOT NULL
               CHECK (level IN ('WARN','ERROR','CRITICAL')),
    component  TEXT NOT NULL,
    signal_id  INTEGER REFERENCES signal_queue(id) ON DELETE SET NULL,
    message    TEXT NOT NULL,
    metadata   JSONB
);

CREATE INDEX IF NOT EXISTS idx_kbl_log_day_level
    ON kbl_log (((ts AT TIME ZONE 'UTC')::date), level);

CREATE INDEX IF NOT EXISTS idx_kbl_log_component
    ON kbl_log (component, ts);
