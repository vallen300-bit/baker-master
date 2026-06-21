-- ALERT_NOISE_FASTFOLLOW_1 Fix 3: durable last-turn direction on threads.
--
-- The quiet-thread sentinel's "demote Director-outbound threads to tier-3
-- awaiting_counterparty" decision relied on the OUTBOUND_MARKER ("director
-- outbound") substring living in capability_threads.topic_summary. Robust for
-- newly-written threads (both WhatsApp + email writers plant it), but old/
-- un-rebuilt outbound-email threads stay tier-2 until rethreaded, and a
-- free-text substring driving a routing decision is brittle (content collision,
-- format drift).
--
-- This additive, nullable column carries the authoritative direction signal
-- (fed at write-time from the same @brisengroup.com sender test that drives
-- contact_interactions.direction). No backfill required: detect_quiet_threads()
-- prefers the column and falls back to the OUTBOUND_MARKER substring for NULL
-- (old) rows, so the demotion never regresses for un-migrated threads.

-- == migrate:up ==

ALTER TABLE capability_threads
    ADD COLUMN IF NOT EXISTS last_turn_direction TEXT;

-- == migrate:down ==
-- Deliberate rollback only. The migration runner executes this file raw, so keep
-- down SQL commented.
--
-- ALTER TABLE capability_threads DROP COLUMN IF EXISTS last_turn_direction;
