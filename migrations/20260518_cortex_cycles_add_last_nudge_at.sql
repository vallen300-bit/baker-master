-- == migrate:up ==
-- STALE_CYCLE_NUDGE_SENTINEL_1: anti-spam state for the daily
-- stale-tier_b_pending nudge sentinel (triggers/stale_cycle_nudge_sentinel.py).
-- Without this column the sentinel would re-fire every run and flood the
-- BAKER ClickUp space with duplicate stale-cycle tasks.
--
-- Brief: briefs/BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.md (2026-05-18)
-- Scar:  Oskolkov cycle c4242a20 sat tier_b_pending 10 days (2026-05-05 → 2026-05-15)
--        before f2954da4 accidentally re-surfaced the same proposals.
--
-- Additive, idempotent, zero-downtime. NULL = "never nudged".
--
-- Companion Python writer update: memory/store_back.py
-- `_ensure_cortex_cycles_table()` carries the same column so fresh DBs
-- bootstrap with last_nudge_at in place from the start (lesson:
-- migration-vs-bootstrap drift trap). Existing DBs are unaffected because
-- CREATE TABLE IF NOT EXISTS is a no-op when the table exists; this
-- migration adds the column on existing prod via ALTER TABLE.

ALTER TABLE cortex_cycles ADD COLUMN IF NOT EXISTS last_nudge_at TIMESTAMPTZ NULL;


-- == migrate:down ==
-- Disaster recovery only. Drops the anti-spam state; the next sentinel run
-- would treat every stale row as never-nudged and re-emit ClickUp tasks
-- for the full backlog.
--
-- ALTER TABLE cortex_cycles DROP COLUMN IF EXISTS last_nudge_at;
