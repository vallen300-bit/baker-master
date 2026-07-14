-- 20260714a_xai_week_ledger.sql
-- GROK_4_5_WEEK_TRIAL_1 — weekly xAI spend reservation ledger + per-call audit.
--
-- Binding spec: briefs/BRIEF_GROK_4_5_WEEK_TRIAL_1.md (Director-ratified 2026-07-14,
-- lead rulings #11260). Two tables:
--
--   xai_week_ledger  — append-only reserve/settle/release rows. Remaining weekly
--                      budget = cap - (settled_this_week + open_reserves), computed
--                      in ONE transaction under a pg advisory lock keyed on
--                      week_start (no in-memory state — order requirement). Reserve
--                      BEFORE the call (conservative max_in+max_out+tool allowance);
--                      settle actual + release residual after; stale reserves expire
--                      via a bounded TTL sweep. Cap 150 USD / warn 120 / hard-block.
--
--   xai_call_audit   — one row per trial-route grok call: provider, exact model,
--                      route, tokens in/out, reserved/est/actual USD, tool-schema
--                      result, outcome, error class. NEVER prompt bodies or secrets.
--
-- Actuals ALSO settle into api_cost_log (source=grok_realtime, cost_usd_override)
-- as today — this ledger does NOT replace the daily cost log; it governs the
-- weekly xAI cap only. Bootstrap DDL mirrored in memory/store_back via
-- orchestrator.xai_week_ledger.ensure_xai_week_ledger_tables (Lesson #50).

BEGIN;

CREATE TABLE IF NOT EXISTS xai_week_ledger (
    id          SERIAL PRIMARY KEY,
    week_start  DATE NOT NULL,
    route       TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('reserve', 'settle', 'release')),
    amount_usd  NUMERIC(12, 6) NOT NULL,
    request_ref TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Weekly budget read groups by week_start; request_ref threads reserve->settle->release.
CREATE INDEX IF NOT EXISTS idx_xai_week_ledger_week
    ON xai_week_ledger (week_start);
CREATE INDEX IF NOT EXISTS idx_xai_week_ledger_request_ref
    ON xai_week_ledger (request_ref);

CREATE TABLE IF NOT EXISTS xai_call_audit (
    id            SERIAL PRIMARY KEY,
    logged_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    provider      TEXT NOT NULL DEFAULT 'xai',
    model         TEXT NOT NULL,
    route         TEXT NOT NULL,
    request_ref   TEXT,
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    reserved_usd  NUMERIC(12, 6) DEFAULT 0,
    est_usd       NUMERIC(12, 6) DEFAULT 0,
    actual_usd    NUMERIC(12, 6) DEFAULT 0,
    tool_schema   TEXT,
    outcome       TEXT NOT NULL,
    error_class   TEXT,
    matter_slug   TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_xai_call_audit_logged_at
    ON xai_call_audit (logged_at);
CREATE INDEX IF NOT EXISTS idx_xai_call_audit_route
    ON xai_call_audit (route);

COMMIT;
