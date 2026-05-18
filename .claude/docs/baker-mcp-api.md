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
| `baker_claimsmax_convert_to_pdf` | Convert investigation JSON into a PDF sibling. **Run ONLY on Director instruction.** Requires `pandoc` plus a PDF engine (`pdflatex` / `xelatex` / `wkhtmltopdf`) on the host. |
| `baker_claimsmax_convert_to_html` | Convert investigation JSON into standalone HTML under `docs-site/<matter>/`. **Run ONLY on Director instruction.** Caller commits + pushes docs-site so Render publishes. Requires pandoc and the `BAKER_DOCS_SITE_ROOT` env var to point at the local docs-site checkout. |

Notes:
- `/ask` endpoint is intentionally **not** exposed — vendor bug pending Ellie Technologies fix (temperature deprecated server-side as of 2026-05-16). Re-enable when vendor confirms fix.
- Investigation flow: `baker_claimsmax_investigate` → poll `baker_claimsmax_check_investigation` every ~5s → on `status="complete"`, `baker_claimsmax_save_investigation` writes JSON. PDF/HTML conversion is Director-gated, not automatic.
- Capability set `claimsmax_archive` registers with `capability_type='archive'` — out of scope for Cortex Phase 3 auto-routing; matter Desks invoke directly via the MCP tools listed above.
- Sample query: `{"name":"baker_claimsmax_search","arguments":{"query":"Pagitsch defects","filters":{"l1":["report"]}}}`.

## Grok real-time tools (3) — GROK_API_CAPABILITY_1

Wraps the xAI Grok Responses API (`https://api.x.ai/v1`) — native X/Twitter Live Search + open-web Live Search + plain Grok reasoning. Auth via `XAI_API_KEY` env var (set by AH1 in Render before merge). Default model `grok-4.3` (1M context, $1.25/M input / $2.50/M output as of 2026-05-17); reasoning variant `grok-4.20-0309-reasoning` available via the `model` param on `baker_grok_ask`.

| Tool | Purpose |
|---|---|
| `baker_grok_x_search` | Search X/Twitter via xAI Live Search (`search_parameters.sources=[{type:'x'}]`). Returns Grok's summary plus a list of tweet citations (`url`, `author`, `date`, `text`, `engagement.favorites/views/reposts`). Replaces the fragile Chrome-MCP port-9222 X path. |
| `baker_grok_web_search` | Search the open web via xAI Live Search (`sources=[{type:'web'},{type:'news'}]`). Returns Grok's summary plus citations (`url`, `title`, `date`, `snippet`). Parallel to `baker_perplexity_ask` — both stay live. |
| `baker_grok_ask` | Plain Grok Responses-API call, no Live Search. Returns `{text, model, tokens_in, tokens_out, cost_usd}`. Use for general reasoning when the prompt doesn't need real-time X/web data. |

Notes:
- All three tools resolve to `POST /v1/responses` — the X / web split exists at the MCP surface for matter-Desk clarity; the client parameterizes `search_parameters.sources` per call.
- Capability set `grok_realtime` registers with `capability_type='archive'` — out of scope for Cortex Phase 3 auto-routing (mirrors ClaimsMax C1 lesson; `baker_grok_*` tools live in MCP, not `TOOL_DEFINITIONS`).
- Cost: 32 input + 9 output tokens → ~$0.000063. A 1M+1M call → ~$3.75. Pilot starts on $250 credits, no auto top-up.
- Sample query: `{"name":"baker_grok_x_search","arguments":{"query":"Brisen Group","max_results":5}}`.
- **Per-call timeout:** each tool accepts `timeout_seconds` (positive number, max 300, default 60). Caps long-running Live Search calls so they don't starve other dispatches sharing the worker. Values outside `(0, 300]` are rejected with `Error: timeout_seconds must be a positive number ≤ 300` — the dispatcher does not invoke Grok.

### Key rotation

`GrokClient` reads `XAI_API_KEY` once at construction and caches the client at module level so the HTTPS connection pool is reused across dispatches. After rotating the key on Render (`op item edit …` → Render env-var PUT via `tools.render_env_guard.safe_env_put` per repo hard rule), the cached client will keep using the OLD key until the worker restarts unless the cache is reset. Sequence:

1. `op item edit "Baker API Keys/XAI_API_KEY"` — rotate the secret.
2. `safe_env_put("XAI_API_KEY", new_value)` — push to Render (merge-mode; never raw PUT).
3. `python3 -c "from tools.grok import reset_client_cache; reset_client_cache()"` — drop the cached client.

The next dispatch rebuilds the client and re-reads `XAI_API_KEY`. `reset_client_cache()` is thread-safe (double-checked lock) and no-ops when no client is cached. The legacy underscore name `_reset_client_for_tests` is preserved as an identity-preserving alias so existing imports keep working.

### Smoke testing

A live smoke test exists at `tests/test_grok_client.py::test_live_grok_web_search_smoke`, env-gated by `TEST_XAI_API_KEY` so CI stays green without the key. It issues a date-current query (BTC spot price) and asserts at least one citation came back. The model may **probabilistically** answer date-current queries from training instead of firing the search tool — when this happens the test sees `citations=[]` and fails even though the wire format is intact. Re-run the smoke once before treating a failure as a real regression; two consecutive failures suggest a real wire issue worth chasing.
