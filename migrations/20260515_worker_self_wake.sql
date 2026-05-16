-- 20260515_worker_self_wake.sql
-- Stage 3 Phase 1: self-wake worker for B-codes (B1-B4).
-- BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.
--
-- Scope: register the `worker.wake.b_code` Tier-B action class. Idempotency
-- state (last 200 message_ids per worker) lives in per-worker state.json on
-- the Mac; no DB-side dedupe table required (bus daemon enforces unique
-- message_ids, 200-entry FIFO covers >>1 day at observed dispatch rate).

BEGIN;

INSERT INTO tier_b_action_classes (class_name, eur_cost, description) VALUES
    ('worker.wake.b_code', 0.10, 'B-code self-wake invocation (claude --print non-interactive). Cost approximation: midpoint of observed €0.05-0.30/wake. Daily cap 100K tokens enforced worker-side; rate cap 4 wakes/hour.')
ON CONFLICT (class_name) DO NOTHING;

COMMIT;
