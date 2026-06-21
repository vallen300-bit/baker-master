-- ALERT_NOISE_FASTFOLLOW_1 Fix 2: race-proof dedup for quiet-thread cards.
--
-- Quiet-card dedup was application-level only (the _upsert_quiet_alert SELECT).
-- Safe under the normal single-process 30-min cadence, but a manual sweep, a
-- second worker, or a restart overlap could still create two pending cards for
-- one thread. This partial UNIQUE index enforces ≤1 pending quiet/awaiting card
-- per (source, source_id, trigger) at the DB; _upsert_quiet_alert's INSERT uses
-- ON CONFLICT DO NOTHING against it so the app path and the constraint agree.
--
-- NOTE ON CONCURRENTLY: the dispatch brief specified CREATE INDEX CONCURRENTLY,
-- but config/migration_runner.py applies every file inside a per-file
-- transaction (_apply_one: cur.execute(sql) + INSERT into schema_migrations +
-- conn.commit()). CREATE INDEX CONCURRENTLY cannot run inside a transaction
-- block and would raise, aborting startup. The only prior migration that even
-- mentions CONCURRENTLY (20260418_step3_signal_queue_extracted_entities.sql)
-- chose plain CREATE INDEX inside a transaction for the same reason. The alerts
-- table is low-volume (Director-facing cards), so the brief SHARE lock during a
-- one-time deploy-startup build is negligible. Plain CREATE UNIQUE INDEX it is.

-- == migrate:up ==

CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_pending_quiet
    ON alerts (source, source_id, (structured_actions->>'trigger'))
    WHERE status = 'pending'
      AND source = 'proactive_pm_sentinel'
      AND structured_actions->>'trigger' IN ('quiet_thread', 'awaiting_counterparty');

-- == migrate:down ==
-- Deliberate rollback only. The migration runner executes this file raw, so keep
-- down SQL commented.
--
-- DROP INDEX IF EXISTS uq_alerts_pending_quiet;
