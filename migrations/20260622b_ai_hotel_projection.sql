-- AI_HOTEL_LAB_PARTNER_PROJECTION_1: partner-safe projection surface (Sprint-0 Step 4).
--
-- The safety gate between internal intelligence and partner-facing cooperation. This
-- step stores DERIVED projection records, audit, redactions, and view-packet snapshot
-- metadata. It supplies NO visibility control — external visibility is decided by the
-- LIVE Step-1 policy engine (policy_evidence_items / policy.engine), and the only
-- safe-body builder is policy.engine.partner_projection. No raw source bodies are
-- stored in any partner-facing column; source_evidence_item_id stays server-side and
-- is never emitted by the external serializer (deputy-codex AC4/T9).
--
-- Vocab: 4 audience roles, 8 projection states; classification + lifecycle REUSE the
-- Step-1 enums; route_target REUSES the Step-3 13-value set.
--
-- Additive + idempotent (IF NOT EXISTS). No CREATE INDEX CONCURRENTLY — the migration
-- runner wraps each file in a transaction (see 20260622_ai_hotel_search_routing.sql).
-- Plain indexes only.

-- == migrate:up ==

-- 1. projection_item — the derived projection record (internal store). Raw source ids
-- stay here server-side; the external serializer never emits them.
CREATE TABLE IF NOT EXISTS projection_item (
    id                          BIGSERIAL PRIMARY KEY,
    projection_item_id          TEXT NOT NULL UNIQUE,        -- opaque, non-enumerable
    audience_role               TEXT NOT NULL
                                CHECK (audience_role IN (
                                    'brisen_internal', 'nvidia_lighthouse',
                                    'mohg_ops_standards', 'venue_owner_site_diligence')),
    source_evidence_item_id     TEXT NOT NULL,               -- INTERNAL only
    lifecycle_state             TEXT NOT NULL
                                CHECK (lifecycle_state IN (
                                    'raw_signal', 'research_artifact', 'verified_evidence',
                                    'shared_view', 'action_linked')),
    dashboard_section           TEXT NOT NULL,
    display_title               TEXT,
    display_summary             TEXT,
    evidence_confidence         DOUBLE PRECISION,
    confidence_reason           TEXT,
    source_label_safe           TEXT,
    citation_or_provenance_safe TEXT,
    freshness                   TEXT,
    last_verified_at            TEXT,
    owner                       TEXT,                        -- INTERNAL only
    reviewer                    TEXT,                        -- INTERNAL only
    visibility_reason           TEXT,
    redaction_applied           BOOLEAN NOT NULL DEFAULT FALSE,
    redaction_reason            TEXT,                        -- INTERNAL detail
    redaction_reason_safe       TEXT,                        -- external-safe
    action_linked_id            TEXT,                        -- INTERNAL only (raw id/url)
    action_safe_text            TEXT,                        -- external-safe action text
    revoked_at                  TIMESTAMPTZ,
    revoked_by                  TEXT,
    revoke_reason               TEXT,
    audit_trace_id              TEXT,
    projection_state            TEXT NOT NULL
                                CHECK (projection_state IN (
                                    'not_projectable', 'projectable_candidate',
                                    'projected_shared_view', 'action_linked_visible',
                                    'revoked', 'stale_projection', 'blocked_by_policy',
                                    'blocked_by_missing_confirmation')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_item_audience_state
    ON projection_item (audience_role, projection_state);

CREATE INDEX IF NOT EXISTS idx_projection_item_source
    ON projection_item (source_evidence_item_id);

-- 2. projection_audit_log — approve / revoke / refresh / deny. Append-only; RETAINED
-- across revoke (revoked item leaves the external view but the audit row stays).
CREATE TABLE IF NOT EXISTS projection_audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    event_type          TEXT NOT NULL,
    audience_role       TEXT NOT NULL,
    projection_item_id  TEXT,
    actor_org           TEXT NOT NULL,
    actor_role          TEXT NOT NULL,
    actor_is_ai         BOOLEAN NOT NULL DEFAULT FALSE,
    allow               BOOLEAN NOT NULL,
    reason              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_audit_item_created
    ON projection_audit_log (projection_item_id, created_at DESC);

-- 3. projection_redaction — what was removed from a projected item + safe reason.
CREATE TABLE IF NOT EXISTS projection_redaction (
    id                  BIGSERIAL PRIMARY KEY,
    projection_item_id  TEXT NOT NULL,
    removed_field       TEXT NOT NULL,
    reason_safe         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_redaction_item
    ON projection_redaction (projection_item_id);

-- 4. projection_snapshot — view-packet metadata (version + cache fingerprint).
CREATE TABLE IF NOT EXISTS projection_snapshot (
    id                  BIGSERIAL PRIMARY KEY,
    audience_role       TEXT NOT NULL,
    policy_version      TEXT NOT NULL,
    projection_version  TEXT NOT NULL,
    visible_count       INTEGER NOT NULL DEFAULT 0,
    fingerprint         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_snapshot_audience_created
    ON projection_snapshot (audience_role, created_at DESC);

-- 5. projection_view — a named view packet header (audience + sections summary).
CREATE TABLE IF NOT EXISTS projection_view (
    id                  BIGSERIAL PRIMARY KEY,
    audience_role       TEXT NOT NULL
                        CHECK (audience_role IN (
                            'brisen_internal', 'nvidia_lighthouse',
                            'mohg_ops_standards', 'venue_owner_site_diligence')),
    audience_label      TEXT NOT NULL,
    is_external         BOOLEAN NOT NULL,
    visible_count       INTEGER NOT NULL DEFAULT 0,
    blocked_count       INTEGER NOT NULL DEFAULT 0,
    stale_count         INTEGER NOT NULL DEFAULT 0,
    action_linked_count INTEGER NOT NULL DEFAULT 0,
    policy_version      TEXT NOT NULL,
    projection_version  TEXT NOT NULL,
    last_generated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- external packets are never marked for a non-external serializer path
    CONSTRAINT chk_projection_view_audience CHECK (
        is_external = (audience_role <> 'brisen_internal'))
);

CREATE INDEX IF NOT EXISTS idx_projection_view_audience
    ON projection_view (audience_role, last_generated_at DESC);

-- == migrate:down ==
-- Disaster recovery only. The runner executes this file raw, so down SQL stays
-- commented (an uncommented DROP would drop the tables on first deploy).
--
-- BEGIN;
-- DROP TABLE IF EXISTS projection_view;
-- DROP TABLE IF EXISTS projection_snapshot;
-- DROP TABLE IF EXISTS projection_redaction;
-- DROP TABLE IF EXISTS projection_audit_log;
-- DROP TABLE IF EXISTS projection_item;
-- COMMIT;
