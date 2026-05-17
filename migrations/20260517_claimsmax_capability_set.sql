-- == migrate:up ==
-- CLAIMSMAX_API_CAPABILITY_1 — register the ClaimsMax archive capability set.
--
-- Inserts one row into capability_sets so matter Desks (mo-vie-am,
-- hagenauer-rg7, cupial, ao, baker-internal) can discover the ClaimsMax
-- search/investigate surface via the standard capability registry.
--
-- Bootstrap DDL for the capability_sets table lives in
-- memory/store_back.py:_ensure_capability_sets_table — this migration only
-- inserts a row, does not touch the schema (no drift risk per Lesson #50).
--
-- Idempotent: ON CONFLICT (slug) DO NOTHING. Refresh applied_migrations.lock
-- after this migration applies in prod.

INSERT INTO capability_sets (
    slug,
    name,
    capability_type,
    domain,
    role_description,
    tools,
    output_format,
    autonomy_level,
    trigger_patterns,
    max_iterations,
    timeout_seconds,
    active
)
VALUES (
    'claimsmax_archive',
    'ClaimsMax Archive',
    'domain',
    'evidence',
    'Search and investigate Brisen''s ClaimsMax document archive (187k docs / 173k emails / Hagenauer-RG7 / MO-Vie / Brisen-Development / Cupial corpora). Hybrid full-text + semantic search; multi-step investigations via the ClaimsMax /investigate engine.',
    '["baker_claimsmax_search", "baker_claimsmax_investigate", "baker_claimsmax_check_investigation", "baker_claimsmax_get_document", "baker_claimsmax_save_investigation", "baker_claimsmax_convert_to_pdf", "baker_claimsmax_convert_to_html"]'::jsonb,
    'prose',
    'recommend_wait',
    '["claimsmax", "archive", "evidence", "investigate", "search.*documents", "Pagitsch", "Hagenauer.*defects"]'::jsonb,
    5,
    180.0,
    TRUE
)
ON CONFLICT (slug) DO NOTHING;

-- == migrate:down ==
-- DELETE FROM capability_sets WHERE slug = 'claimsmax_archive';
