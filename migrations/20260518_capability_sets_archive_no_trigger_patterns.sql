-- == migrate:up ==
-- GROK_API_HARDENING_1 (M4) — defense in depth against future capability_type
-- flip on archive rows. Strip trigger_patterns from any 'archive'-type row,
-- then add a CHECK constraint that prevents future writes from carrying
-- patterns on archive rows.
--
-- Why: trigger_patterns are routing-signals for Cortex Phase 3
-- (capability_type='domain'). Archive rows are MCP-invoked, not Phase-3-
-- routed. The patterns are dead code on archive rows but become live
-- routing-hijackers the moment capability_type flips. Patterns like
-- "grok", "x search", "claimsmax" are too generic to safely re-activate.
--
-- Migration order matters: the UPDATE must run before the ALTER TABLE …
-- ADD CONSTRAINT, otherwise the constraint validation fails on existing
-- archive rows and the migration aborts. Statements execute in declaration
-- order within a single migration file.
--
-- Companion bootstrap update in memory/store_back.py:_ensure_capability_sets_table
-- ensures fresh databases land with the same constraint (Lesson #50
-- migration-vs-bootstrap drift).
--
-- Idempotent: UPDATE filtered on jsonb_array_length > 0 (no-op once cleared);
-- ALTER TABLE wrapped in a NOT EXISTS guard on pg_constraint.

-- Step 1: clear patterns on existing archive rows.
UPDATE capability_sets
SET trigger_patterns = '[]'::jsonb,
    updated_at = NOW()
WHERE capability_type = 'archive'
  AND trigger_patterns IS NOT NULL
  AND jsonb_array_length(trigger_patterns) > 0;

-- Step 2: add the CHECK constraint, guarded so re-runs don't error.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'capability_sets_archive_no_trigger_patterns'
    ) THEN
        ALTER TABLE capability_sets
        ADD CONSTRAINT capability_sets_archive_no_trigger_patterns
        CHECK (
            capability_type <> 'archive'
            OR trigger_patterns IS NULL
            OR jsonb_array_length(trigger_patterns) = 0
        );
    END IF;
END $$;

-- == migrate:down ==
-- ALTER TABLE capability_sets DROP CONSTRAINT IF EXISTS capability_sets_archive_no_trigger_patterns;
-- (Stripped patterns are NOT restored on rollback — they were dead code anyway.)
