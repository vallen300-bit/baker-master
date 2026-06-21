-- AI_HOTEL_LAB_POLICY_CORE_1: permission + evidence-lifecycle core schema.
--
-- Backend policy core for the AI Hotel Lab (Brisen + NVIDIA + MOHG + venue owner).
-- Four tables, all server-side authority — no UI, no partner view, no export path
-- in this step. Every future surface MUST go through policy.engine.evaluate; the
-- DB is the persistence layer for the object model + the audit/lifecycle trail.
--
-- Ontology (codex-arch #3625, BINDING): snake_case enums; evidence_item is the
-- term; lifecycle terminal state is action_linked; 7 classifications incl.
-- partner_safe_venue_owner; classification ≠ grant (allowed_orgs/allowed_roles
-- still decide); object types include claim.
--
-- Additive + idempotent (IF NOT EXISTS). No CREATE INDEX CONCURRENTLY — the
-- migration runner (config/migration_runner._apply_one) executes each file inside
-- a per-file transaction, and CONCURRENTLY cannot run in a transaction block (see
-- migrations/20260621_alerts_uq_pending_quiet.sql note). All indexes here are
-- plain; the tables are new + low-volume so the brief build-lock is negligible.

-- == migrate:up ==

-- 1. Evidence items — the protected object model. confidence is the first-
--    dashboard primitive; raw_body/title are internal-only (never projected).
CREATE TABLE IF NOT EXISTS policy_evidence_items (
    id              BIGSERIAL PRIMARY KEY,
    object_id       TEXT NOT NULL UNIQUE,
    object_type     TEXT NOT NULL
                    CHECK (object_type IN (
                        'claim', 'project', 'site', 'partner', 'signal',
                        'evidence', 'decision', 'action', 'risk', 'document', 'source')),
    classification  TEXT NOT NULL
                    CHECK (classification IN (
                        'brisen_raw', 'brisen_confidential', 'partner_safe_nvidia',
                        'partner_safe_mohg', 'partner_safe_venue_owner',
                        'public_source', 'exportable')),
    lifecycle_state TEXT NOT NULL DEFAULT 'raw_signal'
                    CHECK (lifecycle_state IN (
                        'raw_signal', 'research_artifact', 'verified_evidence',
                        'shared_view', 'action_linked')),
    sensitivity     TEXT
                    CHECK (sensitivity IS NULL OR sensitivity IN (
                        'email_wa_raw', 'strategy_note', 'vendor_negotiation',
                        'financial', 'legal')),
    owner_org       TEXT NOT NULL DEFAULT 'brisen'
                    CHECK (owner_org IN ('brisen', 'nvidia', 'mohg', 'venue_owner')),
    owner           TEXT,
    allowed_orgs    JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_roles   JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence      DOUBLE PRECISION,   -- NULL only legal for raw_signal (AC8)
    source_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_type     TEXT,
    claim           TEXT,
    freshness       TEXT,
    last_reviewed   TEXT,
    raw_body        TEXT,               -- internal-only; never partner-projected
    title           TEXT,               -- internal-only; never partner-projected
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_evidence_items_state_class
    ON policy_evidence_items (lifecycle_state, classification);

-- 2. Lifecycle transitions — append-only trail (AC5). One row per transition.
CREATE TABLE IF NOT EXISTS policy_lifecycle_transitions (
    id              BIGSERIAL PRIMARY KEY,
    object_id       TEXT NOT NULL,
    actor_org       TEXT NOT NULL,
    actor_role      TEXT NOT NULL,
    prior_state     TEXT NOT NULL,
    new_state       TEXT NOT NULL,
    source_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence      DOUBLE PRECISION,
    last_reviewed   TEXT,
    override_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_transitions_object_created
    ON policy_lifecycle_transitions (object_id, created_at DESC);

-- 3. Promotions — human-ratify trail for partner-safe promotion (AC6).
CREATE TABLE IF NOT EXISTS policy_promotions (
    id                  BIGSERIAL PRIMARY KEY,
    object_id           TEXT NOT NULL,
    proposer_org        TEXT NOT NULL,
    proposer_role       TEXT NOT NULL,
    approver_org        TEXT NOT NULL,
    approver_role       TEXT NOT NULL,
    approval_timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    rationale           TEXT,
    source_evidence     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_promotions_object
    ON policy_promotions (object_id);

-- 4. Audit log — every decision/promotion/transition/projection (AC9).
CREATE TABLE IF NOT EXISTS policy_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    principal_org   TEXT NOT NULL,
    principal_role  TEXT NOT NULL,
    action          TEXT,
    object_id       TEXT,
    object_type     TEXT,
    allow           BOOLEAN NOT NULL,
    reason_code     TEXT NOT NULL,
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_audit_object_created
    ON policy_audit_log (object_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_policy_audit_allow_created
    ON policy_audit_log (allow, created_at DESC);

-- == migrate:down ==
-- Disaster recovery only. The migration runner executes this file raw, so the
-- down SQL stays commented (an uncommented DROP would drop the tables it just
-- created on first deploy). Paste into psql for a deliberate rollback.
--
-- BEGIN;
-- DROP TABLE IF EXISTS policy_audit_log;
-- DROP TABLE IF EXISTS policy_promotions;
-- DROP TABLE IF EXISTS policy_lifecycle_transitions;
-- DROP TABLE IF EXISTS policy_evidence_items;
-- COMMIT;
