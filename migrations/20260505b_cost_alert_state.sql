-- BAKER-COST-INSTRUMENTATION-1: per-day per-tier alarm idempotence.
-- Replaces the in-process _alert_sent_date module-level cache that loses
-- state on Render restart and re-fires duplicate alarms.

CREATE TABLE IF NOT EXISTS cost_alert_state (
    alert_date DATE NOT NULL,
    tier_label TEXT NOT NULL,
    fired_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (alert_date, tier_label)
);
