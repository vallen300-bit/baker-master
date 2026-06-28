-- BREACH_DETECT_PHASE1_1: central security chokepoint — read-audit log + global
-- freeze switch.
--
-- Mirror of security.access_guard.ensure_security_schema (Lesson #50 —
-- bootstrap-vs-migration drift trap). Two tables:
--   * security_access_log — metadata-ONLY read/access audit. By design it has NO
--     column that could hold a body, secret, raw key, or raw URL value; the
--     presented key, client IP and user-agent are stored as sha256 prefixes only.
--   * security_freeze — singleton (id=1) global freeze flag, flipped via
--     POST /api/security/{freeze,unfreeze} so a leaking key can be stopped
--     instantly without a redeploy. A BAKER_SECURITY_FREEZE env var is the
--     boot-time backstop that survives a DB outage.
--
-- Additive + idempotent + runner-safe: CREATE TABLE IF NOT EXISTS /
-- CREATE INDEX IF NOT EXISTS / INSERT ... ON CONFLICT DO NOTHING only. New file
-- (not an edit of an applied migration), so applied_migrations.lock is refreshed
-- from prod AFTER this applies — do NOT hand-edit the lock here.
--
-- ROLLBACK: disaster-recovery only; the DOWN section ships commented (the runner
-- executes raw, so live deploys never drop these tables). The pytest round-trip
-- strips the `-- ` leader to exercise DOWN.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS security_access_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    request_id TEXT,
    key_fp TEXT,
    actor_label TEXT,
    method TEXT,
    path_template TEXT,
    route_group TEXT,
    status_code INTEGER,
    latency_ms INTEGER,
    response_bytes INTEGER,
    client_ip_hash TEXT,
    user_agent_hash TEXT,
    origin TEXT,
    anomaly_flags TEXT
);

CREATE TABLE IF NOT EXISTS security_freeze (
    id INTEGER PRIMARY KEY DEFAULT 1,
    global_freeze BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    set_by TEXT,
    set_at TIMESTAMPTZ,
    CONSTRAINT security_freeze_singleton CHECK (id = 1)
);

INSERT INTO security_freeze (id, global_freeze) VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_sal_ts ON security_access_log (ts);
CREATE INDEX IF NOT EXISTS idx_sal_key_ts ON security_access_log (key_fp, ts);

-- == migrate:down ==

-- DROP INDEX IF EXISTS idx_sal_key_ts;
-- DROP INDEX IF EXISTS idx_sal_ts;
-- DROP TABLE IF EXISTS security_freeze;
-- DROP TABLE IF EXISTS security_access_log;
