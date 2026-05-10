-- 20260510_baker_actions_tier_b_runtime.sql
-- Tier B autonomous-action runtime: schema extension + new tables.
-- Forward-looking only. No backfill required (legacy rows keep tier IS NULL).
--
-- BRIEF_CORTEX_TIER_B_RUNTIME_V1, Director-ratified D8 2026-05-10.
-- Caps: €100/action, €500/day, €2500/mo (pool-wide); reset 1st 00:00 UTC.

BEGIN;

-- 1. Extend baker_actions with Tier-B columns (additive, nullable).
ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS tier            TEXT,
    ADD COLUMN IF NOT EXISTS cost_eur        NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS committed_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS committer_agent TEXT,
    ADD COLUMN IF NOT EXISTS action_class    TEXT,
    ADD COLUMN IF NOT EXISTS self_cost_eur   NUMERIC(12, 2);

-- Partial index for fast counter queries (only Tier-B rows with cost).
CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_committed
    ON baker_actions (committed_at)
    WHERE tier = 'B' AND cost_eur IS NOT NULL;

-- 2. Action-class registry (Q2 mixed cost source — primary).
CREATE TABLE IF NOT EXISTS tier_b_action_classes (
    id              SERIAL PRIMARY KEY,
    class_name      TEXT NOT NULL UNIQUE,
    eur_cost        NUMERIC(12, 2) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deprecated_at   TIMESTAMPTZ
);

-- 3. Pending-ratify queue (Q4 dedicated table; GOLD visual reuse but separate domain).
CREATE TABLE IF NOT EXISTS tier_b_pending (
    id               SERIAL PRIMARY KEY,
    action_payload   JSONB NOT NULL,
    cost_eur         NUMERIC(12, 2) NOT NULL,
    action_class     TEXT NOT NULL,
    committer_agent  TEXT NOT NULL,
    reason_paused    TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ratified_at      TIMESTAMPTZ,
    ratified_by      TEXT,
    decision_payload JSONB,
    expired_at       TIMESTAMPTZ,
    CONSTRAINT tier_b_pending_status_check
        CHECK (status IN ('pending', 'ratified', 'rejected', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_tier_b_pending_status
    ON tier_b_pending (status, created_at);

-- 4. Counter-reset audit table (one row per calendar-month boundary).
CREATE TABLE IF NOT EXISTS tier_b_counter_resets (
    id                SERIAL PRIMARY KEY,
    reset_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_label      TEXT NOT NULL,
    final_day_total   NUMERIC(12, 2),
    final_month_total NUMERIC(12, 2),
    actions_count     INTEGER
);

-- 5. Seed initial action-class registry.
INSERT INTO tier_b_action_classes (class_name, eur_cost, description) VALUES
    ('render.deploy.web_service.starter',     7.00,  'Render Starter web service spawn (monthly billing approximation, daily-amortized = €0.23)'),
    ('render.deploy.web_service.standard',   25.00,  'Render Standard web service spawn (monthly billing approximation)'),
    ('render.env.flip',                       0.00,  'Render env-var flip; zero direct cost; logged for audit'),
    ('vendor.subscription.monthly',          50.00,  'Generic monthly SaaS subscription default; override with specific class as registry grows'),
    ('test.synthetic',                        1.00,  'Test-only class for integration tests')
ON CONFLICT (class_name) DO NOTHING;

COMMIT;
