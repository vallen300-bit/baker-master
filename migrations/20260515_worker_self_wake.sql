-- 20260515_worker_self_wake.sql
-- Stage 3 Phase 1: self-wake worker for B1-B4.
-- BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.
--
-- Registers the worker.wake.b_code action class. No new tables.
-- Idempotency state lives in per-worker state.json on the launchd host
-- (last 200 message_ids FIFO) — bus daemon already enforces unique
-- message_ids upstream so a DB-side dedupe table is unnecessary at this
-- volume.

BEGIN;

INSERT INTO tier_b_action_classes (class_name, eur_cost, description) VALUES
    (
        'worker.wake.b_code',
        0.10,
        'B-code self-wake invocation (claude --print non-interactive). Cost approximation €0.05-€0.30/wake; midpoint logged. Daily cap 100K tokens enforced worker-side via state.json; rate cap 4 wakes/hour; circuit breaker 3 consecutive fails.'
    )
ON CONFLICT (class_name) DO NOTHING;

COMMIT;
