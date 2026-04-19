-- Mac Mini heartbeat table (Phase 1 Step 7 observability)
-- Purpose: Mac Mini writes a row every 60s via com.brisen.baker.heartbeat launchd job.
-- Baker's /health endpoint exposes the latest row's age; alert if >5min WARN, >15min critical.
-- Additive only; no existing schema touched.

CREATE TABLE IF NOT EXISTS mac_mini_heartbeat (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    host TEXT NOT NULL,
    version TEXT
);

CREATE INDEX IF NOT EXISTS idx_mac_mini_heartbeat_created_at
    ON mac_mini_heartbeat (created_at DESC);
