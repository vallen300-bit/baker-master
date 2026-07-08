-- == migrate:up ==
-- ARRIVALS_BOARD_LIVE_1: pilot-written flight lifecycle state (D-23 first slice).
--
-- One row per registered flight. Pilots upsert this state in the same ingest pass
-- as dashboard + ClickUp stamp (two-surface seat rule, Director-ratified
-- 2026-07-08). The Director-facing ARRIVALS board reads this table and overlays
-- DELAYED when arrives_on has passed; no LLM inference writes this state.

CREATE TABLE IF NOT EXISTS flight_board_state (
    project_code   TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'CHECK-IN'
                   CHECK (status IN ('CHECK-IN','ON TIME','HOLDING','DELAYED',
                                     'FINAL APPROACH','LANDED','DIVERTED')),
    arrives_on     DATE,
    arrives_label  TEXT,
    airline        TEXT,
    destination    TEXT,
    cockpit_url    TEXT,
    page_version   TEXT,
    updated_by     TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- == migrate:down ==
-- Disaster recovery only. Dropping this table removes pilot-written live flight
-- board state and must be approved/replayed manually.
--
-- DROP TABLE IF EXISTS flight_board_state;
