-- TODOIST_RETIRE_1: Director retired Todoist polling 2026-06-18 ("I don't use
-- it; keep on-demand access"). The scheduler now skips todoist_poll when
-- TODOIST_POLL_ENABLED=false (config/settings.py + triggers/embedded_scheduler.py).
--
-- This migration flips the stored sentinel_health row to 'disabled' so the
-- retired source reads correctly everywhere that consults the table DIRECTLY —
-- mirroring the established 'whoop' row (status='disabled', failures=0). Without
-- this the row stays frozen at its last 'down'/401 state, which would (a) show
-- 'down' on /api/health and keep status 'degraded', (b) be picked up by
-- run_health_watchdog's `WHERE status='down' AND last_error_at < NOW()-2h` query
-- and fire a recurring T1 "stuck down" alert, and (c) make should_skip_poll see
-- a non-disabled row. Setting status='disabled' resolves all three.
--
-- consecutive_failures is zeroed and last_error_msg cleared so the stale 401
-- string stops surfacing (HEALTH_TRIAGE 2026-06-18 false-alarm pattern).
-- last_error_at / last_success_at are left intact as historical markers.
--
-- Idempotent: re-running is a no-op-equivalent UPDATE. Reversible by
-- reset_sentinel('todoist') (sets 'healthy') if Director re-enables polling.

-- == migrate:up ==

UPDATE sentinel_health
   SET status = 'disabled',
       consecutive_failures = 0,
       last_error_msg = NULL,
       updated_at = NOW()
 WHERE source = 'todoist';

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented.
--
-- BEGIN;
-- UPDATE sentinel_health SET status = 'down', updated_at = NOW() WHERE source = 'todoist';
-- COMMIT;
