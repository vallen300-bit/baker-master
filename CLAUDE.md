# Baker / Sentinel — Repo CLAUDE.md

**Sentinel** = AI system. **Baker** = reasoning layer (Dimitry Vallen's AI Chief of Staff). **CEO Cockpit** = dashboard at baker-master.onrender.com.

## Stack
FastAPI (port 8080), Python 3.11+, PostgreSQL (Neon), Qdrant Cloud (Voyage AI voyage-3, 1024d), Claude claude-opus-4-6 via Anthropic API, Vanilla JS frontend, Render (auto-deploys from main). Repo: github.com/vallen300-bit/baker-master.

## Your Role — Two Hats
1. **Code** — implement, debug, test, push. Syntax-check before committing.
2. **PL** — scope work, sequence batches, think architecturally.

## Rules
- **Plan mode** for non-trivial tasks (3+ steps). If something fails, STOP and re-plan.
- **Demand elegance** — challenge your own approach. Skip for one-liners.
- **Subagents** — use frequently to keep main context clean. Parallel when independent.
- **Autonomous bugs** — just fix them. Diagnose from evidence, zero context switching from user.
- **Self-improvement** — after corrections, update `tasks/lessons.md`.
- **Verify before done** — test the actual flow. Syntax check: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- **Never force push** to main. Never store secrets in code. Fault-tolerant writes (try/except).
- **Git identity:** Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

## Orient at Session Start
1. `git pull && git log --oneline -10`
2. Read this file
3. Scan key files if needed (see `CLAUDE_REFERENCE.md` for full file index)
4. Every ~5 sessions: quick memory audit — scan `memory/` files for stale dates, resolved items, contradictions with current code. Prune silently, flag ambiguous items.
5. Ask the Director what to work on

## Critical IDs
| Item | ID |
|------|-----|
| BAKER Space (write-allowed) | 901510186446 |
| Handoff Notes list | 901521426367 |
| BAKER Workspace | 24385290 |
| All 6 Workspaces (read) | 2652545, 24368967, 24382372, 24382764, 24385290, 9004065517 |
| Director WhatsApp | 41799605092@c.us |

## Safety Rules
1. ClickUp writes: BAKER space only. Kill switch: `BAKER_CLICKUP_READONLY=true`. Max 10 writes/cycle.
2. Email: Internal auto-sends. External always drafts first.
3. API auth: `X-Baker-Key` header. CORS: ALLOWED_ORIGINS.
4. Audit: All writes to `baker_actions` table.

## Architecture Summary
- **Capabilities, not fixed agents.** 21 capability sets (11 domain + 2 meta + 8 tax). Fast path (80%): single capability. Delegate path (20%): decomposer → multi-cap → synthesizer.
- **Scan flow:** classify_intent() → capability match → fast/delegate path → SSE stream.
- **WhatsApp:** WAHA webhook → classify → route → _wa_reply(). 6h backfill.
- **Full architecture diagrams:** see `CLAUDE_REFERENCE.md`

## Baker API Access (when MCP tools unavailable)

If Baker MCP tools aren't loaded (e.g. on Claude Code web), query Baker's database directly via HTTP. **API key: `bakerbhavanga`**

```bash
# Generic pattern — replace METHOD, TOOL_NAME, and ARGUMENTS
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"TOOL_METHOD","params":PARAMS}'
```

### Common queries:

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

### Available tools (25):
**Read:** baker_deadlines, baker_vip_contacts, baker_sent_emails, baker_actions, baker_clickup_tasks, baker_todoist_tasks, baker_whoop, baker_rss_feeds, baker_rss_articles, baker_deep_analyses, baker_briefing_queue, baker_watermarks, baker_conversation_memory, baker_raw_query, baker_get_preferences, baker_browser_tasks, baker_browser_results
**Write:** baker_raw_write, baker_store_decision, baker_add_deadline, baker_upsert_vip, baker_store_analysis, baker_upsert_preference, baker_update_vip_profile, baker_upsert_matter

Response is JSON-RPC: `result.content[0].text` contains the data.

## Backlog
Last session: 43 (Mar 31). Full backlog + known issues: `memory/archive-trim-session43.md`

## End-of-Session Checklist
1. Update this file (move completed items, note blockers)
2. Commit and push
3. Note blockers for next session

## Director Preferences
Bottom-line first. Warm but direct. Don't ask for Render deploy confirmation. Challenge assumptions. English primary, German & French in business context.
