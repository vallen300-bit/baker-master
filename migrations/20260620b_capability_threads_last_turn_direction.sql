-- DASHBOARD_ALERT_NOISE_FIX_1 (Slice A, Fix 2): durable last-turn direction.
--
-- Records whether the Director (outbound) or the counterparty (inbound) sent the
-- last turn on a PM thread, so the quiet-thread sentinel can demote
-- Director-outbound "waiting on them" threads to tier 3 instead of surfacing them
-- as Director to-dos (Director ruling 2026-06-20: demote, don't hide).
--
-- Additive + nullable: existing rows stay NULL and the sentinel falls back to the
-- topic_summary marker ("..._outbound: Director outbound — ") until the
-- thread-builder (orchestrator/capability_threads.py) populates the column at
-- write time. Reads prefer the column when present, so behaviour upgrades
-- automatically once a writer lands.

-- == migrate:up ==

ALTER TABLE capability_threads
    ADD COLUMN IF NOT EXISTS last_turn_direction TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'capability_threads_last_turn_direction_chk'
    ) THEN
        ALTER TABLE capability_threads
            ADD CONSTRAINT capability_threads_last_turn_direction_chk
            CHECK (last_turn_direction IS NULL
                   OR last_turn_direction IN ('inbound', 'outbound'));
    END IF;
END $$;

-- == migrate:down ==
-- Deliberate rollback only. The migration runner executes this file raw, so keep
-- down SQL commented.
--
-- ALTER TABLE capability_threads DROP CONSTRAINT IF EXISTS capability_threads_last_turn_direction_chk;
-- ALTER TABLE capability_threads DROP COLUMN IF EXISTS last_turn_direction;
