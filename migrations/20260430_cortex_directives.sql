-- == migrate:up ==
-- BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 — per-matter directives schema.
-- Two tables: cortex_directives (per-directive registry + counters)
--             prompt_review_queue (untraceable Phase 4 outputs)
-- Plus the partial unique index that Brief 3 (Phase 6 Reflector) sweep
-- relies on for ON CONFLICT DO NOTHING idempotency.
--
-- Spec: briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md §3.1
-- Sequencing: Q1 flip — ships BEFORE Brief 3 Reflector consumer.
--
-- NOTE for Brief 3 consumer: matter_slug='_global' is accepted here for
-- cross-matter directives, but bypasses KEBAB_SLUG_RE
-- (kbl/ingest_endpoint.py:35 + scripts/bootstrap_matter.py:33) which rejects
-- underscore prefix. Brief 3 must either special-case '_global' in
-- citation parsing or extend the regex.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS cortex_directives (
    directive_id     TEXT PRIMARY KEY,
        -- Format: '<matter-slug>-<topic>-<NNN>' (e.g. 'movie-aukera-001')
        --      OR '_global-<NNN>' (cross-matter directives)
    matter_slug      TEXT NOT NULL,
        -- Use '_global' for cross-matter directives.
        -- Otherwise must match a slug in baker-vault/slugs.yml at write-time.
    body             TEXT NOT NULL,
        -- The directive content (markdown). Mirrored to vault directives.md.
    source_cycle     UUID REFERENCES cortex_cycles(cycle_id) ON DELETE SET NULL,
        -- The cycle_id that originally surfaced this directive (Phase 6
        -- Reflector promote step in Brief 3). NULL for migration-seeded
        -- directives or Director-manual entries.
    status           TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deprecated', 'draft')),
    helpful_count    INTEGER NOT NULL DEFAULT 0,
        -- Director Triaga ratified a proposal that cited this directive.
    harmful_count    INTEGER NOT NULL DEFAULT 0,
        -- Director Triaga declined a proposal that cited this directive.
    stale_count      INTEGER NOT NULL DEFAULT 0,
        -- 14d silence after proposal cited this directive (no Triaga signal).
    pending_count    INTEGER NOT NULL DEFAULT 0,
        -- Currently in-flight: cited but Triaga TTL not yet expired.
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_directives_matter_status
    ON cortex_directives (matter_slug, status);

-- Score-eligible partial index (helpful + harmful > 0): supports
-- "top-N directives" queries cheaply. Stale + pending excluded from score.
CREATE INDEX IF NOT EXISTS idx_cortex_directives_scored
    ON cortex_directives (matter_slug, status)
    WHERE helpful_count + harmful_count > 0;

COMMENT ON TABLE cortex_directives IS
    'Per-matter directives playbook (Cortex Phase 6 Reflector domain). '
    'Citation mechanism: Phase 4 proposals tag [directive: <id>]; '
    'Phase 6 Reflector observes cycle outcome and increments counters. '
    'V1 simplification: Triaga-only signal source. ClickUp aux + cycle-outcome '
    'inspector deferred to V2 per simplification preamble §0.';

CREATE TABLE IF NOT EXISTS prompt_review_queue (
    queue_id         BIGSERIAL PRIMARY KEY,
    cycle_id         UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
    matter_slug      TEXT NOT NULL,
    proposal_text    TEXT NOT NULL,
        -- Phase 4 output that was missing a [directive: <id>] citation.
    flagged_reason   TEXT NOT NULL
        CHECK (flagged_reason IN (
            'no_citation',           -- proposal has zero [directive: ...] tags
            'unknown_directive_id',  -- citation references id absent from cortex_directives
            'malformed_citation'     -- regex match but invalid id format
        )),
    reviewed         BOOLEAN NOT NULL DEFAULT FALSE,
        -- Director or AI Head A reviewed; toggles true after eyeball pass.
    review_notes     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_review_queue_unreviewed
    ON prompt_review_queue (created_at DESC)
    WHERE reviewed = FALSE;

COMMENT ON TABLE prompt_review_queue IS
    'Untraceable Phase 4 outputs (no/unknown/malformed [directive: <id>] citation). '
    'Weekly eyeball-review surface. Phase 6 Reflector inserts; Director or '
    'AI Head A flips reviewed=true after pass. Per Director caveat 2 ratification '
    '2026-04-30: untraceable proposals flag for prompt-engineering review.';

-- Reflector idempotency: enforce one reflector_complete row per cycle.
-- Brief 3 (CORTEX_PHASE6_REFLECTOR_1) sweep relies on this for
-- ON CONFLICT DO NOTHING when two sweep firings collide on the same
-- cycle (e.g., Render redeploy + cron tick on same minute). Ships in
-- this migration (not a separate one) because Brief 3 depends on it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cortex_phase_outputs_reflector_complete
    ON cortex_phase_outputs (cycle_id)
    WHERE artifact_type = 'reflector_complete';

-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_cortex_phase_outputs_reflector_complete;
-- DROP INDEX IF EXISTS idx_prompt_review_queue_unreviewed;
-- DROP TABLE IF EXISTS prompt_review_queue;
-- DROP INDEX IF EXISTS idx_cortex_directives_scored;
-- DROP INDEX IF EXISTS idx_cortex_directives_matter_status;
-- DROP TABLE IF EXISTS cortex_directives;
