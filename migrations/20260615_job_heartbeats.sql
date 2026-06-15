-- LONG_RUNNING_JOB_OWNERSHIP_1: heartbeat store + sentinel observation store.
--
-- Two separate tables BY DESIGN (deputy-codex pre-flight S2 #3035):
--   job_heartbeats       — per-job cursor heartbeats written by the JOB itself
--                          (and by the sentinel as its own meta-watchdog beat).
--   sentinel_cursor_seen — the sentinel's OWN observation + alert-window claim.
--                          Kept separate so a heartbeat UPSERT (which refreshes
--                          job_heartbeats.updated_at) can NEVER mask the very
--                          staleness the sentinel checks.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS job_heartbeats (
    job_id      TEXT PRIMARY KEY,
    cursor_text TEXT,
    state       TEXT NOT NULL DEFAULT 'RUNNING',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- state ∈ {RUNNING, DONE, FAILED, PAUSED}
ALTER TABLE job_heartbeats DROP CONSTRAINT IF EXISTS job_heartbeats_state_chk;
ALTER TABLE job_heartbeats
    ADD CONSTRAINT job_heartbeats_state_chk
    CHECK (state IN ('RUNNING', 'DONE', 'FAILED', 'PAUSED'));

CREATE TABLE IF NOT EXISTS sentinel_cursor_seen (
    job_id                  TEXT PRIMARY KEY,
    observed_cursor         TEXT,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_alert_window_start TIMESTAMPTZ
);

-- == migrate:down ==
-- Disaster recovery only. Not auto-run — config/migration_runner._apply_one
-- executes the whole file raw, so this section MUST stay commented or it would
-- drop the tables it just created on first deploy (codex G3 S1). Paste into psql
-- when a deliberate rollback is needed.
--
-- BEGIN;
-- DROP TABLE IF EXISTS sentinel_cursor_seen;
-- DROP TABLE IF EXISTS job_heartbeats;
-- COMMIT;
