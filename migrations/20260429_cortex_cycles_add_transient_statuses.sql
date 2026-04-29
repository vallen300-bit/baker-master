-- == migrate:up ==
-- CORTEX_PHASE5_STATUS_RECONCILE_1: pin the 4 transient *ing statuses introduced
-- by PR #75 (CORTEX_PHASE5_IDEMPOTENCY_1) into cortex_cycles.status CHECK.
-- Brief: briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md (2026-04-29)
--
-- Status values 'approving'/'rejecting'/'editing'/'refreshing' are written
-- by _cas_lock_cycle in orchestrator/cortex_phase5_act.py and were failing
-- the CHECK constraint in production until 2026-04-29 09:47Z manual ALTER
-- (Director session). This migration pins the live state into a checked-in
-- file so fresh DBs spin up with the correct CHECK.
--
-- Companion Python writer update: memory/store_back.py
-- `_ensure_cortex_cycles_table()` carries the same expanded 15-value set so
-- bootstrap stays drift-free with the migration (lesson:
-- migration-vs-bootstrap drift trap).
--
-- Idempotent: DROP IF EXISTS + ADD; safe to re-run.
--
-- Apply order: manual operator run OR auto-assertion via app-boot
-- migration runner (config/migration_runner.py).
--   BEGIN; \i migrations/20260429_cortex_cycles_add_transient_statuses.sql ; COMMIT;

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
        -- Added 2026-04-29 by 20260429_cortex_cycles_add_archive_failed_status.sql:
        'archive_failed',
        -- Added 2026-04-29 by THIS migration — transient *ing locks set by
        -- _cas_lock_cycle (CORTEX_PHASE5_IDEMPOTENCY_1, PR #75) before
        -- handler work, released back to 'proposed' (or terminal) at end:
        'approving',
        'rejecting',
        'editing',
        'refreshing'
    ));

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Reverts to the 11-value set (without the 4 *ing
-- transient statuses). Unsafe if any row holds one of those values; drain
-- first:
--   UPDATE cortex_cycles SET status='proposed' WHERE status IN
--       ('approving','rejecting','editing','refreshing');
--
-- BEGIN;
-- ALTER TABLE cortex_cycles DROP CONSTRAINT IF EXISTS cortex_cycles_status_check;
-- ALTER TABLE cortex_cycles ADD CONSTRAINT cortex_cycles_status_check
--     CHECK (status IN (
--         'in_flight','awaiting_reason','proposed','tier_b_pending',
--         'approved','rejected','modified','failed','superseded','abandoned',
--         'archive_failed'
--     ));
-- COMMIT;
