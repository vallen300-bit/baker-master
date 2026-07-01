-- BOX5_DROP_OBSERVABILITY_1: queryable per-gate drop-log for the signal journey.
--
-- The airport-ticketing signal journey drops signals at every gate SILENTLY:
--   * Gate 2 (keyword prefilter) hard-filtered on 3 ILIKE keywords in SQL, so a
--     keyword-miss email was never even fetched -> it could not be counted.
--   * Gate 3 (routing) folds no-code / conflict arrivals into a generic safe-default
--     TICKET with no structured "why it wasn't auto-routed" trail.
-- With no "considered-and-dropped + reason" trail we cannot measure whether widening
-- ingestion (#450) actually delivers mail or which gate now binds. cowork's rule:
-- instrument FIRST, then size the Gate-2 keyword-broadening off real drop data.
--
-- This table records every considered-and-dropped inbound signal + reason WITHOUT
-- changing what gets ticketed (observability only; parity proven in tests). A row =
-- a signal that fell out of the confident path at a named gate:
--   * keyword_prefilter -> not ticketed (missed the active-keyword gate).
--   * routing_unrouted / routing_conflict -> still ticketed (safe-default desk review)
--     but NOT confidently auto-routed; logged so the default-vs-routed mix is queryable.
--
-- Additive + forward-only. The CREATE below is mirrored verbatim in
-- orchestrator/airport_ticketing_bridge.py::ensure_box5_dropped_signals_table so an
-- already-bootstrapped DB (where a migration runner has not yet applied this file)
-- still gains the table on the next tick (Lesson #50 migration-vs-bootstrap drift).
-- This is a brand-new table (no pre-existing prod table to ALTER), so a single
-- identical CREATE TABLE IF NOT EXISTS in both places cannot drift.
CREATE TABLE IF NOT EXISTS box5_dropped_signals (
    id              BIGSERIAL PRIMARY KEY,
    message_id      TEXT,
    thread_id       TEXT,
    sender_email    TEXT,
    subject         TEXT,                                   -- truncated at write time
    matched_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,    -- [] for keyword_prefilter drops
    gate            TEXT NOT NULL,
    reason          TEXT,
    received_date   TIMESTAMPTZ,
    tick_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT box5_dropped_signals_gate_check CHECK (
        gate IN (
            'keyword_prefilter',
            'routing_unrouted',
            'routing_conflict',
            'other'
        )
    )
);

-- "last 24h drops by gate" is the primary read (size Gate-2 widening off it): index
-- both the time filter and the group key so the scan stays bounded as the log grows.
CREATE INDEX IF NOT EXISTS idx_box5_dropped_signals_tick_at
    ON box5_dropped_signals (tick_at);
CREATE INDEX IF NOT EXISTS idx_box5_dropped_signals_gate
    ON box5_dropped_signals (gate);

-- Idempotent re-log: the contiguous-prefix watermark can re-fetch a boundary arrival
-- on a later tick (received_date >= since), so the same signal may be re-classified as
-- a drop more than once. UNIQUE(message_id, gate) + ON CONFLICT DO NOTHING makes the
-- second write a no-op instead of a duplicate row (one drop per signal per gate).
CREATE UNIQUE INDEX IF NOT EXISTS uq_box5_dropped_signals_msg_gate
    ON box5_dropped_signals (message_id, gate);
