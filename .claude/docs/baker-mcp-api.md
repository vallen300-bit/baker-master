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

## ClaimsMax archive tools (7) — CLAIMSMAX_API_CAPABILITY_1

Wraps the ClaimsMax v1 REST API (`https://brisen.claimsmax.co.uk/api/v1/`) — 187K docs / 173K emails / 1.4M chunks covering Hagenauer/RG7, MO Vie, Brisen Development, MOHG, Cupial. Auth via `CLAIMSMAX_API_KEY` env var (set by AH1 in Render). Full API spec: `~/Desktop/ClaimsMaxAPI.md`.

| Tool | Purpose |
|---|---|
| `baker_claimsmax_search` | Hybrid full-text + semantic search; supports natural / boolean / proximity modes + filter dict. |
| `baker_claimsmax_investigate` | Start a multi-step investigation (fire-and-forget); returns `{run_id, status}`. |
| `baker_claimsmax_check_investigation` | Poll an investigation run by `run_id`; report markdown lands when status flips to `complete`. |
| `baker_claimsmax_get_document` | Fetch full document metadata; optional `include_text=true` for the extracted body. |
| `baker_claimsmax_save_investigation` | Persist a completed investigation's final state as JSON in the matter's Dropbox research folder. **Cheap default — run after every investigation.** |
| `baker_claimsmax_convert_to_pdf` | Convert investigation JSON into a PDF sibling. **Run ONLY on Director instruction.** Requires pandoc on the runtime. |
| `baker_claimsmax_convert_to_html` | Convert investigation JSON into standalone HTML under `docs-site/<matter>/`. **Run ONLY on Director instruction.** Caller commits + pushes docs-site so Render publishes. Requires pandoc. |

Notes:
- `/ask` endpoint is intentionally **not** exposed — vendor bug pending Ellie Technologies fix (temperature deprecated server-side as of 2026-05-16). Re-enable when vendor confirms fix.
- Investigation flow: `baker_claimsmax_investigate` → poll `baker_claimsmax_check_investigation` every ~5s → on `status="complete"`, `baker_claimsmax_save_investigation` writes JSON. PDF/HTML conversion is Director-gated, not automatic.
- Sample query: `{"name":"baker_claimsmax_search","arguments":{"query":"Pagitsch defects","filters":{"l1":["report"]}}}`.
