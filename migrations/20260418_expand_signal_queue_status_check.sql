-- STATUS-CHECK-EXPAND-1: expand signal_queue.status CHECK for KBL-B per-step states
-- Ticket: briefs/_tasks/CODE_1_PENDING.md STATUS-CHECK-EXPAND-1 (2026-04-18)
-- Director-ratified path (b) from B2 PR #10 S1.
--
-- Problem: KBL-A's CHECK constraint only permits 8 legacy status values
-- ('pending','processing','done','failed','expired','classified-deferred',
-- 'failed-reviewed','cost-deferred'). KBL-B writers (PR #7/#8/#10/#11) emit
-- per-step states ('triage_running', 'resolve_running', 'extract_running',
-- 'awaiting_*', '*_failed', 'paused_cost_cap', 'completed', etc.) that
-- violate the constraint — first real signal crashes the worker.
--
-- Fix: drop the narrow CHECK, re-add with the full 34-value set below.
-- Additive, idempotent. Safe to run repeatedly.
--
-- Naming reconciliation (AI Head ratified 2026-04-18):
--   - All per-step running states standardize on `<step>_running` pattern
--     (no `triaging` / `resolving` / `extracting` / `classifying` /
--      `committing` aliases). Matches PR #8/#10/#11 writer names.
--
-- Companion Python writer update: memory/store_back.py
-- `_ensure_signal_queue_additions()` must carry the same 34-value set so
-- every app boot re-asserts the expanded CHECK — otherwise this migration
-- gets reverted on next Render restart. That update ships in the same PR.
--
-- Two-track §5.1 migration (new `stage` + `state` columns) deferred to
-- Phase 2 burn-in cleanup per KBL-B §5.7 — not in scope here.
--
-- Apply order: manual operator run OR auto-assertion via app-boot path.
--   BEGIN; \i migrations/20260418_expand_signal_queue_status_check.sql ; COMMIT;


-- == migrate:up ==

BEGIN;

ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;

ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
    CHECK (status IN (
        -- KBL-A legacy (preserved)
        'pending',
        'processing',
        'done',
        'failed',
        'expired',
        'classified-deferred',
        'failed-reviewed',
        'cost-deferred',
        -- KBL-B Layer 0
        'dropped_layer0',
        -- KBL-B Step 1 triage
        'awaiting_triage',
        'triage_running',
        'triage_failed',
        'triage_invalid',
        'routed_inbox',
        -- KBL-B Step 2 resolve
        'awaiting_resolve',
        'resolve_running',
        'resolve_failed',
        -- KBL-B Step 3 extract
        'awaiting_extract',
        'extract_running',
        'extract_failed',
        -- KBL-B Step 4 classify
        'awaiting_classify',
        'classify_running',
        'classify_failed',
        -- KBL-B Step 5 opus
        'awaiting_opus',
        'opus_running',
        'opus_failed',
        'paused_cost_cap',
        -- KBL-B Step 6 finalize
        'awaiting_finalize',
        'finalize_running',
        'finalize_failed',
        -- KBL-B Step 7 commit
        'awaiting_commit',
        'commit_running',
        'commit_failed',
        -- KBL-B terminal
        'completed'
    ));

COMMIT;


-- == migrate:down ==
-- Disaster recovery only. Not auto-run. Reverts to KBL-A 8-value set.
-- WARNING: running DOWN while KBL-B is live will block writers — any row
-- holding a KBL-B-only status will fail the CHECK on update. Use only
-- when rolling back to pre-KBL-B state AND after draining per-step rows
-- back to 'pending' / 'processing' / 'done' / 'failed'.
--
-- BEGIN;
-- ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
-- ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
--     CHECK (status IN (
--         'pending',
--         'processing',
--         'done',
--         'failed',
--         'expired',
--         'classified-deferred',
--         'failed-reviewed',
--         'cost-deferred'
--     ));
-- COMMIT;
