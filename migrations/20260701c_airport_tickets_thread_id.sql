-- THREAD_CONTINUITY_ROUTING_1: queryable email thread identity on airport_tickets.
--
-- BOX5_ROUTING_REVERSAL_E_1 (#446) retired name/alias routing, which left a recall
-- hole: a code-less reply from a non-participant sender routes nowhere even on a
-- thread already bound to a matter. Thread identity is a STRONG signal (unlike fuzzy
-- names), so the thread-continuity lane inherits a prior CODE-BOUND ticket's project
-- when a reply carries no code. That lookup needs a queryable thread_id — the email
-- thread id was only ever stored as free text inside the `ticket` JSONB, never a
-- structured column.
--
-- Additive + nullable -> safe on the populated prod table (existing rows stay NULL;
-- only new inbound tickets populate it). Mirrored verbatim in
-- orchestrator/airport_ticketing_bridge.py::ensure_airport_ticket_table so an
-- already-bootstrapped DB (where CREATE TABLE IF NOT EXISTS no-ops) still gains the
-- column + index (Lesson #50 migration-vs-bootstrap drift).
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS thread_id TEXT;

-- thread_id is the lane's lookup key (resolve_by_thread WHERE thread_id = %s); index
-- it so the continuity scan stays bounded on a large ticket table.
CREATE INDEX IF NOT EXISTS idx_airport_tickets_thread_id
    ON airport_tickets (thread_id);
