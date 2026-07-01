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
-- Additive + nullable. The column ALTER is mirrored verbatim in
-- orchestrator/airport_ticketing_bridge.py::ensure_airport_ticket_table so an
-- already-bootstrapped DB (where CREATE TABLE IF NOT EXISTS no-ops) still gains the
-- column + index (Lesson #50 migration-vs-bootstrap drift). The BACKFILL below is
-- NOT mirrored there — ensure_ runs on every tick, so a per-tick backfill would be
-- wasteful; the one-time data fix belongs here, in the applied migration.
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS thread_id TEXT;

-- thread_id is the lane's lookup key (resolve_by_thread WHERE thread_id = %s); index
-- it so the continuity scan stays bounded on a large ticket table.
CREATE INDEX IF NOT EXISTS idx_airport_tickets_thread_id
    ON airport_tickets (thread_id);

-- BACKFILL (codex G3 #4925): the column alone is forward-only — existing airport_tickets
-- rows keep thread_id NULL, so a code-less reply on a thread whose prior CODE-BOUND
-- ticket predates this migration would not match. Recover the thread identity from its
-- authoritative source, email_messages (a ticket's source_id IS the email message_id),
-- so continuity works for every already-ticketed email thread, not only post-deploy
-- ones. Idempotent (WHERE thread_id IS NULL) + bounded by idx_airport_tickets_source.
UPDATE airport_tickets AS a
SET thread_id = e.thread_id
FROM email_messages AS e
WHERE a.source_channel = 'email'
  AND a.thread_id IS NULL
  AND a.source_id = e.message_id
  AND e.thread_id IS NOT NULL
  AND e.thread_id <> '';

-- Fallback for any email row whose source message is no longer in email_messages
-- (pruned) but whose thread identity was captured verbatim in the ticket JSONB
-- (build_email_ticket always writes a "thread_id: <id>" luggage line). This makes the
-- backfill independent of email_messages retention. Guarded on a JSON array shape so a
-- malformed ticket can never abort the migration; the regex returns NULL on no match.
UPDATE airport_tickets AS a
SET thread_id = sub.tid
FROM (
    SELECT t.id,
           trim(substring(elem FROM '^thread_id:[[:space:]]*(.*)$')) AS tid
    FROM airport_tickets AS t
    CROSS JOIN LATERAL jsonb_array_elements_text(t.ticket -> 'luggage') AS elem
    WHERE t.thread_id IS NULL
      AND t.source_channel = 'email'
      AND jsonb_typeof(t.ticket -> 'luggage') = 'array'
      AND elem LIKE 'thread_id:%'
) AS sub
WHERE a.id = sub.id
  AND sub.tid IS NOT NULL
  AND sub.tid <> '';
