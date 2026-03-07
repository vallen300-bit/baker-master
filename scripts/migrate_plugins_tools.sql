-- PLUGINS-1: Add web_search and read_document tools to capability_sets
-- Run against live Neon database after deploying the new agent.py

-- web_search: nearly all capabilities benefit from real-time web data
UPDATE capability_sets
SET tools = tools || '["web_search"]'::jsonb
WHERE slug IN ('research', 'it', 'finance', 'sales', 'asset_mgmt', 'ib', 'marketing', 'legal')
  AND NOT tools @> '["web_search"]'::jsonb;

-- read_document: capabilities that analyze vendor docs, contracts, term sheets
UPDATE capability_sets
SET tools = tools || '["read_document"]'::jsonb
WHERE slug IN ('legal', 'finance', 'it', 'ib', 'comms')
  AND NOT tools @> '["read_document"]'::jsonb;

-- Verify
SELECT slug, tools FROM capability_sets WHERE active = TRUE ORDER BY slug;
