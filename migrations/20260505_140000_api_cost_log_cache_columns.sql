-- == migrate:up ==
-- BAKER-PROMPT-CACHING-1 — add Anthropic prompt-cache token columns to api_cost_log.
--
-- Two new INTEGER columns mirror the Anthropic SDK's response.usage fields
-- so the dashboard agent loop can record cache effectiveness alongside the
-- existing input/output token counters. Both default to 0 and are nullable
-- (DEFAULT 0 covers historical rows + non-cached call sites without backfill).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe to re-apply. Bootstrap DDL in
-- orchestrator/cost_monitor.py:ensure_api_cost_log_table mirrors this exactly,
-- so fresh DBs (tests / new environments) match the migrated prod schema
-- (Lesson #50 — migration-vs-bootstrap drift trap).
--
-- Sibling-coupling: BRIEF_BAKER_COST_INSTRUMENTATION_1 (B2) adds matter_slug
-- to the same table via a separately-named migration. Both columns are
-- independent ADD COLUMN IF NOT EXISTS so merge order is safe. Refresh
-- applied_migrations.lock once after BOTH migrations apply, in apply-order.

ALTER TABLE api_cost_log
    ADD COLUMN IF NOT EXISTS cache_creation_input_tokens INTEGER DEFAULT 0;

ALTER TABLE api_cost_log
    ADD COLUMN IF NOT EXISTS cache_read_input_tokens INTEGER DEFAULT 0;

-- == migrate:down ==
-- ALTER TABLE api_cost_log DROP COLUMN IF EXISTS cache_read_input_tokens;
-- ALTER TABLE api_cost_log DROP COLUMN IF EXISTS cache_creation_input_tokens;
