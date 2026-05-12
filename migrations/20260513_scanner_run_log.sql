-- BRIEF_APSCHEDULER_VAULT_SCANNER_V1 — Amendment A
-- One row per vault_scanner_daily run for dashboard + sentinel observability.
-- Architecture-review concern #3 (silent regressions); paired with the
-- 3-day empty-streak sentinel in triggers/vault_scanner.py (Amendment B).
CREATE TABLE IF NOT EXISTS scanner_run_log (
    id SERIAL PRIMARY KEY,
    run_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    desks_scanned INTEGER NOT NULL DEFAULT 0,
    tasks_found INTEGER NOT NULL DEFAULT 0,
    deadlines_found INTEGER NOT NULL DEFAULT 0,
    dm_sent BOOLEAN NOT NULL DEFAULT FALSE,
    dm_error_msg TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_scanner_run_log_run_ts
    ON scanner_run_log (run_ts DESC);
