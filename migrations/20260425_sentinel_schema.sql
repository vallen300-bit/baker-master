-- == migrate:up ==
-- BRIEF_PROACTIVE_PM_SENTINEL_1 (Rev 3, 2026-04-24):
--   (a) per-thread SLA override for quiet-thread sentinel (Feature 1a)
--   (b) dismiss reason for Upgrade 2 triage surface (Feature 1b)
-- Both additive + nullable. Zero impact on existing rows.
-- alerts.snoozed_until pre-exists and is reused by Upgrade 1 — no DDL here.
-- Filename sort-orders AFTER 20260424_capability_threads.sql (Phase 2 dep).
-- Applied by config/migration_runner.py on next Render boot (lessons #35/#37).

ALTER TABLE capability_threads
    ADD COLUMN IF NOT EXISTS sla_hours INTEGER DEFAULT NULL;

COMMENT ON COLUMN capability_threads.sla_hours IS
  'BRIEF_PROACTIVE_PM_SENTINEL_1: override per-thread quiet-period alert threshold. NULL = use pm-level default. Typical values 6/12/24/48/72.';

ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS dismiss_reason TEXT DEFAULT NULL;

COMMENT ON COLUMN alerts.dismiss_reason IS
  'BRIEF_PROACTIVE_PM_SENTINEL_1: enum-style reason for alert dismissal. Accepted values: waiting_for_counterparty, already_handled_offline, low_priority, wrong_thread. NULL for non-dismissed or pre-this-brief rows.';

-- Partial index for 14-day dismiss-pattern aggregation (Upgrade 2).
-- Uses only IMMUTABLE operators (=, IS NOT NULL) per lesson #38.
CREATE INDEX IF NOT EXISTS idx_alerts_sentinel_dismiss_pattern
    ON alerts (source, status, dismiss_reason, resolved_at DESC)
    WHERE source = 'proactive_pm_sentinel' AND dismiss_reason IS NOT NULL;

-- == migrate:down ==
-- Reversal only if Phase 3 sentinel feature is deliberately retired. Paste manually:
--
-- BEGIN;
-- DROP INDEX IF EXISTS idx_alerts_sentinel_dismiss_pattern;
-- ALTER TABLE alerts DROP COLUMN IF EXISTS dismiss_reason;
-- ALTER TABLE capability_threads DROP COLUMN IF EXISTS sla_hours;
-- COMMIT;
