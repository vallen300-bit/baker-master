# Code Brisen — CORTEX-PHASE-2A Opening Prompt

## Your Task
Implement Baker Cortex Phase 2A: Event bus + tool router + decisions→insights pipeline.

## Brief
Read: `briefs/BRIEF_CORTEX_PHASE_2A.md`

## What You're Building
1. `cortex_events` PostgreSQL table (append-only event log)
2. `source_agent` column on `deadlines` and `decisions` tables
3. `models/cortex.py` — NEW: `publish_event()`, audit logging, auto-queue decisions→pm_pending_insights
4. Tool router in `orchestrator/agent.py` — wraps `create_deadline` and `store_decision` through Cortex when `tool_router_enabled=true`
5. Set `_current_capability` on ToolExecutor for agent attribution

## Key Rules
- **Feature flag OFF = zero behavior change.** `tool_router_enabled` is already `false` in `cortex_config`.
- **Legacy path STILL runs.** Cortex route calls the existing methods first, then publishes the event.
- **NEVER call self.execute() from _cortex_route()** — infinite recursion. Return error JSON instead.
- **Post-write hooks (audit, insights) are in try/except** — failures don't block the main write.
- **LIMIT on all queries. Rollback in all except blocks.**
- **Syntax check every Python file** before committing.

## Files to Modify
- `memory/store_back.py` — 1 new method + 2 ALTER TABLEs
- `models/cortex.py` — NEW file
- `orchestrator/agent.py` — routing in `execute()`, `_cortex_route()`, `_update_source_agent()`
- `orchestrator/capability_runner.py` — set `_current_capability` on ToolExecutor

## Files NOT to Touch
- `models/deadlines.py` — legacy path unchanged
- `baker_mcp/baker_mcp_server.py` — MCP rewiring is Phase 2B
- `triggers/*` — pipeline rewiring is Phase 2B
- `data/ao_pm/*.md`, `data/movie_am/*.md` — view files unchanged

## Verify Before Done
```bash
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('orchestrator/agent.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
```

## After Push
Tables auto-create on Render deploy. Flag stays OFF — zero risk. Flip `tool_router_enabled` via SQL to test.
