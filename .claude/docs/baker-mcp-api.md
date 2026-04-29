# Baker MCP API — direct access (when MCP tools unavailable)

If Baker MCP tools aren't loaded (e.g. on Claude Code web), query Baker's database directly via HTTP.

**API key:** `bakerbhavanga`

```bash
# Generic pattern — replace METHOD, TOOL_NAME, and ARGUMENTS
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"TOOL_METHOD","params":PARAMS}'
```

## Common queries

```bash
# Search VIP contacts
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vip_contacts","arguments":{"search":"NAME","limit":10}}}'

# Get active deadlines
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_deadlines","arguments":{"status":"active","limit":20}}}'

# Search conversation memory
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_conversation_memory","arguments":{"search":"TOPIC","limit":10}}}'

# Run custom SQL (read-only)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT id, name, role FROM vip_contacts WHERE name ILIKE '\''%search%'\'' LIMIT 10"}}}'

# List all 25 available tools
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Response is JSON-RPC: `result.content[0].text` contains the data.

## Available tools (24)

**Read:** `baker_deadlines`, `baker_vip_contacts`, `baker_sent_emails`, `baker_actions`, `baker_clickup_tasks`, `baker_todoist_tasks`, `baker_rss_feeds`, `baker_rss_articles`, `baker_deep_analyses`, `baker_briefing_queue`, `baker_watermarks`, `baker_conversation_memory`, `baker_raw_query`, `baker_get_preferences`, `baker_browser_tasks`, `baker_browser_results`

**Write:** `baker_raw_write`, `baker_store_decision`, `baker_add_deadline`, `baker_upsert_vip`, `baker_store_analysis`, `baker_upsert_preference`, `baker_update_vip_profile`, `baker_upsert_matter`
