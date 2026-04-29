-- == migrate:up ==
-- CORTEX_ARCHIVE_FAILURE_ALERTING_1: add `archive_failed` to cortex_cycles.status CHECK.
-- Brief: briefs/BRIEF_CORTEX_ARCHIVE_FAILURE_ALERTING_1.md (2026-04-29 rev 2)
--
-- Problem: Phase 6 archive failure path in orchestrator/cortex_runner.py:189
-- swallows the exception with an f-string log; the row keeps its prior
-- transient status forever and is invisible to any future query. The new
-- archive-failure alerting sentinel needs a deterministic terminal status
-- it can detect.
--
-- Fix: drop the narrow 10-value CHECK, re-add with `archive_failed` appended.
-- Additive, idempotent. Safe to run repeatedly.
--
-- Companion Python writer update: memory/store_back.py
-- `_ensure_cortex_cycles_table()` carries the same expanded set so fresh
-- DBs spin up with the correct CHECK from the start (lesson:
-- migration-vs-bootstrap drift trap). Existing DBs are unaffected because
-- CREATE TABLE IF NOT EXISTS is a no-op when the table exists.
--
-- Apply order: manual operator run OR auto-assertion via app-boot
-- migration runner (config/migration_runner.py).
--   BEGIN; \i migrations/20260429_cortex_cycles_add_archive_failed_status.sql ; COMMIT;

BEGIN;

ALTER TABLE cortex_cycles DROP CONSTRAINT IF EXISTS cortex_cycles_status_check;

ALTER TABLE cortex_cycles ADD CONSTRAINT cortex_cycles_status_check
    CHECK (status IN (
        -- Original 10-value set (migrations/20260428_cortex_cycles.sql:25)
        'in_flight',
        'awaiting_reason',
        'proposed',
        'tier_b_pending',
        'approved',
        'rejected',
        'modified',
        'failed',
        'superseded',
        'abandoned',
        -- New (CORTEX_ARCHIVE_FAILURE_ALERTING_1, 2026-04-29):
        -- Phase 6 archive itself raised; row is durably orphaned and
        -- the cortex_stuck_cycle_sentinel Detector B alerts on it.
        'archive_failed'
    ));

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Reverts to the 10-value set. Unsafe if any row
-- holds status='archive_failed' (the rollback would block on CHECK).
-- Drain those rows first:
--   UPDATE cortex_cycles SET status='failed' WHERE status='archive_failed';
--
-- BEGIN;
-- ALTER TABLE cortex_cycles DROP CONSTRAINT IF EXISTS cortex_cycles_status_check;
-- ALTER TABLE cortex_cycles ADD CONSTRAINT cortex_cycles_status_check
--     CHECK (status IN (
--         'in_flight','awaiting_reason','proposed','tier_b_pending',
--         'approved','rejected','modified','failed','superseded','abandoned'
--     ));
-- COMMIT;
