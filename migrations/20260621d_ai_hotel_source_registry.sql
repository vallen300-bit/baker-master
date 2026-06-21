-- AI_HOTEL_LAB_SOURCE_INVENTORY_1: source registry + change audit (Sprint-0 Step 2).
--
-- The machine-usable evidence supply chain for the AI Hotel Lab. Inventories what
-- the Lab may search/ingest/monitor/route and classifies every source. This step
-- supplies classification METADATA only — external visibility is decided by the
-- LIVE Step-1 policy engine (policy_evidence_items / policy.engine), never by a
-- registry flag. No content, no snippets, no bodies are stored here.
--
-- Vocab (lead defaults #3657): 8 domains, no catch-all; classification REUSES the
-- Step-1 7-value set (single source of truth); never-external is a separate
-- sensitivity dimension (reused Step-1 Sensitivity), NOT a classification value.
--
-- Additive + idempotent (IF NOT EXISTS). No CREATE INDEX CONCURRENTLY — the
-- migration runner wraps each file in a transaction (see
-- migrations/20260621_alerts_uq_pending_quiet.sql). Plain indexes only.

-- == migrate:up ==

CREATE TABLE IF NOT EXISTS source_registry (
    id                            BIGSERIAL PRIMARY KEY,
    source_id                     TEXT NOT NULL UNIQUE,   -- opaque, non-enumerable
    domain                        TEXT NOT NULL
                                  CHECK (domain IN (
                                      'baker_internal_memory', 'vault_project_rooms',
                                      'dropbox_project_files', 'comms_email_wa_slack',
                                      'field_evidence', 'open_web', 'site_search_public',
                                      'market_capital_residence')),
    source_type                   TEXT NOT NULL,
    object_type                   TEXT NOT NULL
                                  CHECK (object_type IN (
                                      'claim', 'site_signal', 'partner_signal',
                                      'competitor_signal', 'financing_signal',
                                      'residence_signal', 'pr_signal', 'action',
                                      'document', 'note', 'image_video')),
    owner_org                     TEXT NOT NULL
                                  CHECK (owner_org IN ('brisen', 'nvidia', 'mohg', 'venue_owner')),
    classification                TEXT NOT NULL
                                  CHECK (classification IN (
                                      'brisen_raw', 'brisen_confidential',
                                      'partner_safe_nvidia', 'partner_safe_mohg',
                                      'partner_safe_venue_owner', 'public_source', 'exportable')),
    lifecycle_state               TEXT NOT NULL
                                  CHECK (lifecycle_state IN (
                                      'raw_signal', 'research_artifact', 'verified_evidence',
                                      'shared_view', 'action_linked')),
    sensitivity                   TEXT
                                  CHECK (sensitivity IS NULL OR sensitivity IN (
                                      'email_wa_raw', 'strategy_note', 'vendor_negotiation',
                                      'financial', 'legal')),
    provenance_class              TEXT NOT NULL
                                  CHECK (provenance_class IN (
                                      'first_party', 'partner_provided', 'public', 'derived')),
    collection_status             TEXT NOT NULL
                                  CHECK (collection_status IN ('wired', 'partial', 'gap')),
    allowed_orgs                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_roles                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_body_available_internal   BOOLEAN NOT NULL,
    external_projection_available BOOLEAN NOT NULL,
    redaction_reason              TEXT,
    provenance_refs               JSONB NOT NULL DEFAULT '[]'::jsonb,  -- internal-only
    policy_object_id              TEXT,        -- FK-by-value to policy_evidence_items.object_id
    name                          TEXT,
    claim                         TEXT,
    confidence                    DOUBLE PRECISION,
    freshness                     TEXT NOT NULL,
    gap_owner                     TEXT,
    gap_reason                    TEXT,
    gap_next_action               TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- AC7 enforced at the DB too: a hidden, non-gap row must carry a reason.
    CONSTRAINT chk_hidden_needs_reason CHECK (
        external_projection_available = TRUE
        OR collection_status = 'gap'
        OR redaction_reason IS NOT NULL),
    -- AC8: gap rows carry owner/reason/next_action and are never externally visible.
    CONSTRAINT chk_gap_fields CHECK (
        collection_status <> 'gap'
        OR (gap_owner IS NOT NULL AND gap_reason IS NOT NULL
            AND gap_next_action IS NOT NULL
            AND external_projection_available = FALSE))
);

CREATE INDEX IF NOT EXISTS idx_source_registry_domain_status
    ON source_registry (domain, collection_status);

CREATE INDEX IF NOT EXISTS idx_source_registry_policy_object
    ON source_registry (policy_object_id);

-- Change audit — every metadata change (AC10). Append-only.
CREATE TABLE IF NOT EXISTS source_registry_audit (
    id                            BIGSERIAL PRIMARY KEY,
    source_id                     TEXT NOT NULL,
    field                         TEXT NOT NULL,
    prior_value                   TEXT,
    new_value                     TEXT,
    actor_org                     TEXT NOT NULL,
    actor_role                    TEXT NOT NULL,
    actor_is_ai                   BOOLEAN NOT NULL DEFAULT FALSE,
    rationale                     TEXT,
    decision_source               TEXT,
    increases_external_exposure   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_registry_audit_source_created
    ON source_registry_audit (source_id, created_at DESC);

-- == migrate:down ==
-- Disaster recovery only. The runner executes this file raw, so down SQL stays
-- commented (an uncommented DROP would drop the tables on first deploy).
--
-- BEGIN;
-- DROP TABLE IF EXISTS source_registry_audit;
-- DROP TABLE IF EXISTS source_registry;
-- COMMIT;
