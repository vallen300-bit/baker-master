-- == migrate:up ==
-- BOX5_RECEIPT_TTL_1: stale-ticket nudge state on the frozen airport_tickets table.
--
-- Part 2 of the Box-5 receipt loop re-pings desks whose `sent` tickets are never
-- checked in, and escalates to `lead` after N nudges. That state machine needs
-- two columns the issue path never created: when the ticket was last re-pinged
-- and how many times. Real columns (not JSONB) so the existing
-- idx_airport_tickets_desk_status index serves the stale scan and nudge_count is
-- NOT-NULL-defaultable.
--
-- Brief: briefs/BRIEF_BOX5_RECEIPT_TTL_1.md (2026-06-30)
--
-- Additive, idempotent, zero-downtime. last_nudged_at NULL = "never nudged".
--
-- Companion Python writer update: orchestrator/airport_ticketing_bridge.py
-- `ensure_airport_ticket_table()` carries the same two ALTER … ADD COLUMN IF NOT
-- EXISTS lines so fresh DBs bootstrap with the columns in place (lesson:
-- migration-vs-bootstrap drift trap — CREATE TABLE IF NOT EXISTS no-ops on an
-- already-bootstrapped DB, so the bootstrap must ALTER too).

ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ;
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0;
-- escalated_at decouples the one-shot escalation from the nudge count so a
-- transient escalation-POST failure cannot strand a row at nudge_count>=max with
-- the escalation silently dropped (codex G3 F2). NULL = not yet escalated; the
-- escalation pass re-scans at-max-but-unescalated rows until it succeeds.
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ;


-- == migrate:down ==
-- Disaster recovery only. Drops the nudge state; the next TTL sweep would treat
-- every stale `sent` ticket as never-nudged and re-ping the full backlog.
--
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS last_nudged_at;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS nudge_count;
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS escalated_at;
