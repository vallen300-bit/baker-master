-- == migrate:up ==
-- BOX5_OUTBOUND_INGEST_1: direction-aware ingestion axis on airport_tickets.
--
-- Director ruling (2026-07-01): Brisen OUTBOUND email must enter the ticketing
-- system as an action-evidence signal (outbound is often the RATIFICATION of what
-- humans proposed to the Director). Increment 1 tags every airport_tickets row with
-- its direction; the sender's address decides it (a Brisen-controlled domain OR
-- address => 'outbound', else 'inbound').
--
-- Additive, idempotent, zero-downtime. NOT NULL DEFAULT 'inbound' -> existing rows
-- backfill to 'inbound' on apply; inbound tickets never set it explicitly (the
-- default carries them, so reserve_ticket's INSERT stays byte-identical), only the
-- outbound capture path writes 'outbound'. No CHECK constraint — future direction
-- values stay open (mirrors the terminal_columns "keep values open" decision).
--
-- Companion bootstrap: orchestrator/airport_ticketing_bridge.py
-- ensure_airport_ticket_table() carries the SAME `ALTER … ADD COLUMN IF NOT EXISTS`
-- line so fresh / already-bootstrapped DBs gain the column (migration-vs-bootstrap
-- drift trap — CREATE TABLE IF NOT EXISTS no-ops on an already-bootstrapped DB, so
-- the bootstrap must ALTER too; Lesson #50).
--
-- Brief: briefs/BRIEF_BOX5_OUTBOUND_INGEST_1.md (2026-07-01)

ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'inbound';


-- == migrate:down ==
-- Disaster recovery only. Drops the direction axis; captured outbound rows lose
-- their tag and the next tick re-derives direction from sender_email on the fly.
--
-- ALTER TABLE airport_tickets DROP COLUMN IF EXISTS direction;
