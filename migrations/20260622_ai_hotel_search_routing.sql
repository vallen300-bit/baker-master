-- AI_HOTEL_LAB_SEARCH_ROUTING_1: search/routing logging + amber raw-signal inbox
-- (Sprint-0 Step 3).
--
-- The controlled intelligence-intake layer for the AI Hotel Lab. This step LOGS
-- search activity, captures amber raw signals, and records routing
-- suggestions/overrides. It supplies NO visibility control — external visibility is
-- decided by the LIVE Step-1 policy engine (policy_evidence_items / policy.engine),
-- and promotion happens ONLY through the Step-1 lifecycle gate. No raw bodies or
-- snippets are stored in any partner-facing column; raw_summary_internal is
-- internal-only and never projected.
--
-- Vocab (codex-arch #3679): 5 search modes, 13 route_targets, classification +
-- lifecycle REUSE the Step-1 7-value / 5-value sets; source domains REUSE the
-- Step-2 8-value set.
--
-- Additive + idempotent (IF NOT EXISTS). No CREATE INDEX CONCURRENTLY — the
-- migration runner wraps each file in a transaction (see
-- migrations/20260621d_ai_hotel_source_registry.sql). Plain indexes only.

-- == migrate:up ==

-- 1. search_query_log — every search, who ran it, the mode/filters, and the count.
CREATE TABLE IF NOT EXISTS search_query_log (
    id              BIGSERIAL PRIMARY KEY,
    principal_org   TEXT NOT NULL
                    CHECK (principal_org IN ('brisen', 'nvidia', 'mohg', 'venue_owner')),
    principal_role  TEXT NOT NULL,
    is_external     BOOLEAN NOT NULL,
    mode            TEXT NOT NULL
                    CHECK (mode IN ('internal_global', 'partner_safe',
                                    'source_domain', 'section', 'web_live_hook')),
    filters         JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_count    INTEGER NOT NULL DEFAULT 0,
    zero_result     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_query_log_org_created
    ON search_query_log (principal_org, created_at DESC);

-- 2. search_result_audit — what was returned to whom (projected vs raw + reason).
CREATE TABLE IF NOT EXISTS search_result_audit (
    id                 BIGSERIAL PRIMARY KEY,
    principal_org      TEXT NOT NULL
                       CHECK (principal_org IN ('brisen', 'nvidia', 'mohg', 'venue_owner')),
    principal_role     TEXT NOT NULL,
    result_ref         TEXT NOT NULL,
    projected          BOOLEAN NOT NULL,
    policy_reason_code TEXT NOT NULL,
    route_target       TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- An external principal must NEVER receive a non-projected (raw) result.
    CONSTRAINT chk_external_is_projected CHECK (
        principal_org = 'brisen' OR projected = TRUE)
);

CREATE INDEX IF NOT EXISTS idx_search_result_audit_ref_created
    ON search_result_audit (result_ref, created_at DESC);

-- 3. raw_signal_inbox — the amber raw-signal record (16 codex-arch fields). Lands
-- and stays at raw_signal; promotion is via the Step-1 lifecycle gate only.
CREATE TABLE IF NOT EXISTS raw_signal_inbox (
    id                         BIGSERIAL PRIMARY KEY,
    signal_id                  TEXT NOT NULL UNIQUE,        -- opaque, non-enumerable
    source_id                  TEXT NOT NULL,               -- Step-2 registry source
    source_domain              TEXT NOT NULL
                               CHECK (source_domain IN (
                                   'baker_internal_memory', 'vault_project_rooms',
                                   'dropbox_project_files', 'comms_email_wa_slack',
                                   'field_evidence', 'open_web', 'site_search_public',
                                   'market_capital_residence')),
    object_type                TEXT NOT NULL,
    raw_summary_internal       TEXT NOT NULL,               -- internal-only, never external
    projected_summary_external TEXT,                        -- projection-built only, may be NULL
    proposed_route_target      TEXT NOT NULL
                               CHECK (proposed_route_target IN (
                                   'executive_summary', 'field_evidence',
                                   'santa_clara_site_thesis', 'nvidia_lighthouse',
                                   'mandarin_oriental_operator_logic',
                                   'market_proof_competitive_set',
                                   'business_case_financing', 'residence_buyers',
                                   'marketing_pr', 'vendors_future_operating_layer',
                                   'execution_roadmap', 'source_gap_unassigned_review',
                                   'risk_permissions_review')),
    route_reason               TEXT NOT NULL,
    confidence                 DOUBLE PRECISION,
    -- Amber signals are ALWAYS raw_signal at rest (AC4); promotion uses the Step-1
    -- lifecycle gate, which moves the linked policy object, not this inbox row.
    lifecycle_state            TEXT NOT NULL DEFAULT 'raw_signal'
                               CHECK (lifecycle_state = 'raw_signal'),
    classification             TEXT NOT NULL
                               CHECK (classification IN (
                                   'brisen_raw', 'brisen_confidential',
                                   'partner_safe_nvidia', 'partner_safe_mohg',
                                   'partner_safe_venue_owner', 'public_source',
                                   'exportable')),
    allowed_orgs               JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_roles              JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner                      TEXT NOT NULL,
    reviewer                   TEXT,
    policy_object_id           TEXT,                         -- link to Step-1 object
    freshness                  TEXT NOT NULL,
    observed_at                TEXT NOT NULL,
    evidence_needed_to_confirm TEXT NOT NULL,
    duplicate_of               TEXT,
    related_signal_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
    audit_trail                JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_signal_inbox_route
    ON raw_signal_inbox (proposed_route_target);

CREATE INDEX IF NOT EXISTS idx_raw_signal_inbox_source
    ON raw_signal_inbox (source_id);

-- 4. routing_suggestions — proposed target + reason + method (rule|llm) + confidence.
CREATE TABLE IF NOT EXISTS routing_suggestions (
    id                BIGSERIAL PRIMARY KEY,
    signal_id         TEXT,
    source_id         TEXT NOT NULL,
    route_target      TEXT NOT NULL,
    route_reason      TEXT NOT NULL,
    method            TEXT NOT NULL CHECK (method IN ('rule', 'llm', 'human_override')),
    confidence        DOUBLE PRECISION,
    rule_no           INTEGER,
    secondary_targets JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_routing_suggestions_source
    ON routing_suggestions (source_id, created_at DESC);

-- 5. routing_overrides — human override of a routing suggestion (AC5). Audited.
CREATE TABLE IF NOT EXISTS routing_overrides (
    id            BIGSERIAL PRIMARY KEY,
    signal_id     TEXT NOT NULL,
    prior_target  TEXT NOT NULL,
    new_target    TEXT NOT NULL,
    actor_org     TEXT NOT NULL,
    actor_role    TEXT NOT NULL,
    actor_is_ai   BOOLEAN NOT NULL DEFAULT FALSE,
    rationale     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_routing_overrides_signal_created
    ON routing_overrides (signal_id, created_at DESC);

-- 6. zero_result_gaps — zero-result queries logged as source_gap candidates. Never
-- records what (if anything) was hidden — only that the visible set was empty.
CREATE TABLE IF NOT EXISTS zero_result_gaps (
    id              BIGSERIAL PRIMARY KEY,
    principal_org   TEXT NOT NULL
                    CHECK (principal_org IN ('brisen', 'nvidia', 'mohg', 'venue_owner')),
    principal_role  TEXT NOT NULL,
    query           TEXT NOT NULL,
    mode            TEXT NOT NULL
                    CHECK (mode IN ('internal_global', 'partner_safe',
                                    'source_domain', 'section', 'web_live_hook')),
    route_target    TEXT NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_zero_result_gaps_created
    ON zero_result_gaps (created_at DESC);

-- == migrate:down ==
-- Disaster recovery only. The runner executes this file raw, so down SQL stays
-- commented (an uncommented DROP would drop the tables on first deploy).
--
-- BEGIN;
-- DROP TABLE IF EXISTS zero_result_gaps;
-- DROP TABLE IF EXISTS routing_overrides;
-- DROP TABLE IF EXISTS routing_suggestions;
-- DROP TABLE IF EXISTS raw_signal_inbox;
-- DROP TABLE IF EXISTS search_result_audit;
-- DROP TABLE IF EXISTS search_query_log;
-- COMMIT;
