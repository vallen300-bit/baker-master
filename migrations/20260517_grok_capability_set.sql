-- == migrate:up ==
-- GROK_API_CAPABILITY_1 — register the Grok real-time capability set.
--
-- Inserts one row into capability_sets so matter Desks (mo-vie-am,
-- hagenauer-rg7, cupial, ao, baker-internal, baden-baden-desk) can discover
-- the Grok X-search / web-search / ask MCP surface via the standard
-- capability registry.
--
-- capability_type='archive' (NOT 'domain') — mirrors CLAIMSMAX_API_CAPABILITY_1
-- PR #213 C1 fix. cortex_phase3_reasoner._load_active_domain_capabilities
-- loads tools from TOOL_DEFINITIONS, NOT from MCP. baker_grok_* tools live in
-- MCP (tools/grok.py), so a 'domain' row would feed Opus a tool-less prompt
-- and silently fail. 'archive' keeps the capability MCP-invocable by matter
-- Desks without hijacking Cortex Phase 3b.
--
-- Trigger patterns kept narrow on purpose: generic 'search' / 'lookup' /
-- 'realtime' would hijack matter-routing the moment capability_type ever
-- flips back to 'domain'. Keep these patterns as the canonical "this is
-- unambiguously a Grok ask" filter — extend only with equally narrow names.
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
    'grok_realtime',
    'Grok Real-Time Search',
    'archive',
    'realtime',
    'Real-time X/Twitter + open-web search via xAI Grok Heavy Live Search API. Three MCP tools (baker_grok_x_search / baker_grok_web_search / baker_grok_ask) replace the fragile Chrome-MCP port-9222 X path and the Director-manual-Grok workaround. Invoked by matter Desks via the baker_grok_* MCP surface; not loaded by Cortex Phase 3.',
    '["baker_grok_x_search", "baker_grok_web_search", "baker_grok_ask"]'::jsonb,
    'json',
    'recommend_wait',
    '["grok", "x search", "twitter search", "real-time web", "realtime news"]'::jsonb,
    3,
    90.0,
    TRUE
)
ON CONFLICT (slug) DO NOTHING;

-- == migrate:down ==
-- DELETE FROM capability_sets WHERE slug = 'grok_realtime';
