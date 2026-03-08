# Baker / Sentinel — Repo CLAUDE.md

This file is read automatically by Claude Code at session start.
It provides the context needed to work on this codebase from any machine.

## What This Is

**Sentinel** = the full AI system (triggers, infrastructure, memory).
**Baker** = the persona/reasoning layer inside Sentinel — Dimitry Vallen's AI Chief of Staff.
**CEO Cockpit** = the dashboard frontend at baker-master.onrender.com.

3-layer architecture: Sentinel (Layer 1) → Baker (Layer 2) → CEO Cockpit (Layer 3).

## Stack

- **Backend:** FastAPI (port 8080), Python 3.11+
- **Database:** PostgreSQL on Neon (structured data, audit logs)
- **Vectors:** Qdrant Cloud (Voyage AI voyage-3, 1024 dims) — cluster: baker-memory (AWS EU Central 1)
- **LLM:** Claude claude-opus-4-6 (1M context) via Anthropic API
- **Frontend:** Vanilla JS, served from outputs/static/
- **Deployment:** Render (auto-deploys from main branch on push)
- **Repo:** github.com/vallen300-bit/baker-master

## Your Role — Two Hats

1. **Code** — implement, debug, test, push. Syntax-check all modified files before committing.
2. **PL (Project Lead)** — scope work, sequence batches, think architecturally.

Switch hats as needed. When coding, code. When scoping, think.

## How to Orient at Session Start

1. `git pull && git log --oneline -10` — see what shipped recently
2. Read this file (you're doing it now)
3. Scan key files if working on a specific area (see Key Files below)
4. Ask the Director what to work on, or check ClickUp Handoff Notes list for queued tasks

## Key Files

### Core Pipeline
| File | Purpose |
|------|---------|
| `orchestrator/pipeline.py` | 5-step RAG pipeline: Classify → Retrieve → Augment → Generate → Store |
| `orchestrator/prompt_builder.py` | Pipeline prompt (structured JSON output) |
| `orchestrator/scan_prompt.py` | Scan prompt + STEP1C domain/mode prompt extensions + STEP3 DB-driven preferences + build_mode_aware_prompt() |
| `orchestrator/action_handler.py` | Intent router — email, WhatsApp, deadline, VIP, fireflies, ClickUp, **capability_task** actions |
| `orchestrator/decision_engine.py` | **DECISION-ENGINE-1A:** score_trigger() — domain, urgency, tier, mode, overrides, VIP SLA |
| `orchestrator/agent.py` | **AGENTIC-RAG-1 + STEP1B + RETRIEVAL-FIX-1:** Agent loop with 9 tools, ToolExecutor, tier-based routing, matter-aware search |
| `orchestrator/capability_registry.py` | **AGENT-FRAMEWORK-1:** Loads capability definitions from DB, 5-min cache, trigger pattern matching |
| `orchestrator/capability_router.py` | **AGENT-FRAMEWORK-1:** Fast path (single capability) + delegate path (decomposer → multi-capability → synthesizer) |
| `orchestrator/capability_runner.py` | **AGENT-FRAMEWORK-1:** Executes capability runs — run_single, run_streaming, run_multi, run_synthesizer |
| `memory/retriever.py` | Read-side: Qdrant vector search + PostgreSQL structured queries |
| `memory/store_back.py` | Write-side: PostgreSQL writes + Qdrant interaction embeddings + STEP3 director_preferences + VIP profiles + **capability framework tables** |

### API & Dashboard
| File | Purpose |
|------|---------|
| `outputs/dashboard.py` | FastAPI app — all REST endpoints + scan_chat() SSE streaming |
| `outputs/static/index.html` | CEO Cockpit frontend |
| `outputs/static/app.js` | Frontend JS with bakerFetch() auth wrapper |
| `outputs/email_router.py` | Email sending endpoints |
| `document_generator.py` | Word/Excel/PDF/PowerPoint generation from Scan |

### Triggers (Data Ingestion)
| File | Purpose |
|------|---------|
| `triggers/embedded_scheduler.py` | APScheduler — runs all polling triggers |
| `triggers/email_trigger.py` | Gmail polling (every 5 min) |
| `triggers/clickup_trigger.py` | ClickUp polling (every 5 min, all 6 workspaces) |
| `triggers/waha_webhook.py` | WhatsApp webhook receiver (WAHA push) + media download/OCR |
| `triggers/waha_client.py` | WAHA API client — list chats, fetch messages, download media, extract text |
| `triggers/fireflies_trigger.py` | Fireflies meeting transcript sync |
| `triggers/todoist_trigger.py` | Todoist task sync |
| `triggers/rss_trigger.py` | RSS feed ingestion |
| `triggers/whoop_trigger.py` | Whoop health data sync |
| `triggers/dropbox_trigger.py` | Dropbox file watcher |
| `triggers/slack_trigger.py` | Slack polling (every 5 min) — embed + @Baker pipeline |
| `triggers/slack_events.py` | Slack Events API webhook (real-time, optional) |
| `triggers/browser_client.py` | BROWSER-1: dual-mode client (simple HTTP + Browser-Use Cloud) |
| `triggers/browser_trigger.py` | BROWSER-1: web monitoring, change detection, pipeline feed |

### ClickUp Integration
| File | Purpose |
|------|---------|
| `clickup_client.py` | ClickUp API wrapper — read all 6 workspaces, write BAKER space only |

### Config
| File | Purpose |
|------|---------|
| `config/settings.py` | All config via env vars — secrets, intervals, endpoints |
| `config/.env` | Local dev secrets (gitignored) |

## Architecture: How Scan Works

```
User question → scan_chat()
  → check_pending_plan() (ClickUp plan approval loop)
  → check_pending_draft() (email draft approval loop)
  → classify_intent() (regex fast-path → Haiku fallback, with 15-turn conversation history)
    → capability_task → _scan_chat_capability() → capability framework (AGENT-FRAMEWORK-1)
    → clickup_action / clickup_fetch / clickup_plan → action handler → SSE response
    → email_action → draft/send → SSE response
    → whatsapp_action → resolve VIP name → send via WAHA → SSE response
    → deadline_action / vip_action / fireflies_fetch → handler → SSE response
    → question → score_trigger() → baker_task created →
        → CapabilityRouter.route() → if capability match:
            → fast path: single capability → CapabilityRunner.run_streaming() → SSE
            → delegate path: decomposer → multi-capability → synthesizer → SSE
        → else (no capability match) → mode+tier routing:
            → tier 1 + mode!=delegate: _scan_chat_legacy() → fast path (~3s) → stream SSE
            → mode==delegate OR agentic flag: _scan_chat_agentic() → agent loop → stream SSE
            → else: _scan_chat_legacy() → single-pass RAG → stream SSE
        → baker_task closed with deliverable + capability metadata
```

## Architecture: How WhatsApp Works

```
WAHA webhook → waha_webhook.py
  → hasMedia? → waha_client.download_media_file() → extract_media_text() (Claude Vision / doc extractors)
  → Build combined_body (text + [Attachment: extracted text])
  → Store to whatsapp_messages table (ARCH-7)
  → Director message? → _handle_director_message()
    → check_pending_plan() → ClickUp plan loop
    → check_pending_draft() → email draft loop
    → classify_intent() (with 15-turn history) → route to handler → _wa_reply()
    → whatsapp_action? → resolve VIP name → send via WAHA → _wa_reply()
    → question? → _handle_director_question() (WA-QUESTION-1 + STEP1C)
      → baker_task created → mode+tier routing:
        → tier 1 + mode!=delegate: legacy fast path
        → mode==delegate OR agentic flag: agent loop (mode-aware prompt, delegate: max 5 iter, 15s timeout)
        → else: legacy single-pass RAG
      → _wa_reply(answer) + baker_task closed + _wa_store_back()
  → Non-Director → pipeline.run() or briefing queue

Backfill: scripts/extract_whatsapp.py
  → waha_client.list_chats() → fetch_messages() per chat
  → download media → extract text → format_chat() → store_document() to baker-whatsapp
  → Startup: 7-day catch-up (dashboard.py background thread)
  → Scheduled: 6-hour re-sync (embedded_scheduler.py)
  → On-demand: POST /api/whatsapp/backfill?days=365
```

## Critical IDs

| Item | ID |
|------|-----|
| BAKER Space (write-allowed) | 901510186446 |
| Handoff Notes list | 901521426367 |
| BAKER Workspace | 24385290 |
| All 6 Workspaces (read) | 2652545, 24368967, 24382372, 24382764, 24385290, 9004065517 |
| Director WhatsApp | 41799605092@c.us |

## Safety Rules

1. **ClickUp writes:** BAKER space only (901510186446). Enforced by `_check_write_allowed()` in clickup_client.py.
2. **Kill switch:** Set `BAKER_CLICKUP_READONLY=true` to block all ClickUp writes.
3. **Max writes per cycle:** 10 (prevents runaway loops).
4. **Audit log:** All writes logged to `baker_actions` PostgreSQL table.
5. **Email:** Internal (@brisengroup.com) auto-sends. External always drafts first, Director confirms.
6. **API auth:** All /api/* routes require `X-Baker-Key` header (BAKER_API_KEY env var).
7. **CORS:** Restricted to ALLOWED_ORIGINS env var.

## Coding Rules

- **Syntax check** all modified files before committing: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- **Never force push** to main. Render auto-deploys — broken code goes live immediately.
- **Never store secrets** in code. All credentials via env vars or Render Secret Files.
- **Fault-tolerant writes:** All store-back operations wrapped in try/except — pipeline continues if DB is down.
- **Git identity:** Use whatever is configured locally. Commits include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`.

## Render Env Vars

| Var | Purpose |
|-----|---------|
| ANTHROPIC_API_KEY | Claude API |
| BAKER_API_KEY | Dashboard auth (X-Baker-Key header) |
| ALLOWED_ORIGINS | CORS whitelist |
| CLICKUP_API_KEY | ClickUp Personal API token |
| VOYAGE_API_KEY | Voyage AI embeddings |
| QDRANT_URL / QDRANT_API_KEY | Qdrant Cloud |
| POSTGRES_* | Neon PostgreSQL connection |
| WHATSAPP_API_KEY | WAHA API auth (chats, messages, media download) |
| WASSENGER_API_KEY | WhatsApp (legacy, replaced by WAHA) |
| FIREFLIES_API_KEY | Meeting transcripts |
| TODOIST_API_TOKEN | Todoist sync |
| BAKER_AGENTIC_RAG | `true`/`false` — enable agentic RAG agent loop (default: false) |
| BAKER_AGENT_TIMEOUT | Agent loop wall-clock timeout in seconds (default: 10) |
| TAVILY_API_KEY | Web search API (pending — needed for web_search tool) |

## Qdrant Collections

baker-whatsapp, baker-emails, baker-contacts, baker-clickup, baker-todoist,
baker-documents, baker-conversations, baker-health, baker-people, baker-deals,
baker-projects, sentinel-interactions, sentinel-email, sentinel-meetings, sentinel-documents

## PostgreSQL Key Tables

`triggers_log`, `decisions`, `alerts`, `contacts`, `deals`, `preferences`,
`clickup_tasks`, `baker_actions`, `pending_drafts`, `trigger_watermarks`,
`todoist_tasks`, `conversation_memory`, `sent_emails`, `deadlines`, `vip_contacts`,
`meeting_transcripts` (ARCH-3), `email_messages` (ARCH-6), `whatsapp_messages` (ARCH-7),
`insights` (INSIGHT-1), `baker_tasks` (STEP1C), `matter_registry` (RETRIEVAL-FIX-1),
`director_preferences` (STEP3), `capability_sets` (AGENT-FRAMEWORK-1),
`capability_runs` (AGENT-FRAMEWORK-1), `decomposition_log` (AGENT-FRAMEWORK-1)

## Architecture: Role Division (Baker vs Cowork)

Baker is the **Chief of Staff** — always on guard, monitors, remembers, acts on routine.
Cowork (+ Claude Code) is the **Thinker & Creator** — deep analysis, brainstorming, decisions.

| Actor | Role | Context | Connected via |
|-------|------|---------|---------------|
| **Baker (Sentinel)** | Chief of Staff — monitors, remembers, acts | Always-on (Render) | Triggers, pipeline |
| **Cowork (Claude Desktop)** | Thinker — quick PM/PL coordination | 200K tokens | Baker MCP (21 tools) |
| **Claude Code CLI** | Thinker — deep analysis, heavy thinking, coding | **1M tokens** | Baker MCP (21 tools) |
| **Director (Dimitry)** | Final authority | Human | All of the above |

**MCP bridge:** Baker MCP server exposes 15 read tools + 6 write tools. Both Cowork and Claude Code connect to the same Baker memory. Decisions stored from either environment are visible to the other.

**Write tools (Cowork/Claude Code → Baker memory):**
- `baker_store_decision` → decisions table
- `baker_add_deadline` → deadlines table
- `baker_upsert_vip` → vip_contacts table (basic: name, role, email, whatsapp_id)
- `baker_store_analysis` → deep_analyses table
- `baker_upsert_preference` → director_preferences table (STEP3: strategic priorities, domain context, communication style)
- `baker_update_vip_profile` → vip_contacts table (STEP3: tier, domain, role_context, communication_pref, expertise)

**MCP server location:** `Baker-Project/baker-mcp/baker_mcp_server.py` (Dropbox, syncs to all machines)

## Multi-Role Workshop Model

| Role | Authority | Where |
|------|-----------|-------|
| **PM** | Priorities, approvals | Cowork session |
| **PL** | Scoping briefs, fix briefs | Cowork session or Claude Code |
| **Code** | Implementation, push to GitHub | Claude Code CLI |
| **Director** (Dimitry) | Final authority | Human |

Communication between roles: ClickUp **Handoff Notes** list (901521426367).

## Roadmap

### Phase 1 — Foundation (DONE)
All shipped in sessions 1-8. Baker is a reactive Chief of Staff with memory, scoring, and matter-aware retrieval.

| What | Status |
|------|--------|
| Full-text storage (ARCH-1 through ARCH-7) | DONE — no truncation, all data sources |
| ClickUp integration (B1-B4 + CLICKUP-V2) | DONE — read all 6 workspaces, write BAKER space, 3 intents |
| WhatsApp input + output + send | DONE — backfill, media OCR, Director Q&A, send to VIPs |
| Agentic RAG (9 tools, agent loop, tier routing) | DONE — search memory/meetings/emails/WA/contacts/deadlines/ClickUp/deals/matters |
| Decision Engine (domain/urgency/tier/mode) | DONE — 4-step classifier, 3-component scorer, VIP SLA monitoring |
| Task Ledger + Delegation (STEP1C) | DONE — baker_tasks table, mode-aware routing, Director feedback |
| Matter Registry (RETRIEVAL-FIX-1) | DONE — 13 matters, auto-fetch from connected people |
| Director Onboarding (Step 3) | DONE — 14 preferences, 13 matters, VIP profiles, DB-driven prompts |
| Alert Dedup (ALERT-DEDUP-1) | DONE — ~1,100/day → ~20/day |
| MCP Bridge | DONE — 23 tools (15 read + 8 write), Cowork + Claude Code connected |

### Phase 2 — Multi-Agent Orchestration (NOW)
Baker becomes an orchestrator that assembles **capability sets** dynamically per task.

**Core concept: Capabilities, not fixed agents.** An "agent" is a temporary assembly of capability sets that Baker composes for a specific task, then dissolves. Capabilities are composable building blocks (domain knowledge + system prompt + tools + output format) stored as rows in `capability_sets` table.

**Architecture:**
- **Fast path (80%):** Single capability, no decomposition. Baker picks the best match, runs it directly.
- **Delegate path (20%):** Decomposer (itself a capability) breaks the task into sub-issues → each sub-issue runs with its own capability → Synthesizer (another capability) combines results into one unified answer.
- **Experience-informed retrieval:** Every decomposition is logged. Decomposer consults past patterns before breaking down new tasks. Director feedback propagates to improve future routing.

**AGENT-FRAMEWORK-1** — 12 capability sets deployed (10 domain + 2 meta):

| # | Capability | Domain | Purpose |
|---|------------|--------|---------|
| 1 | Sales | projects | MO Residences pitch decks, buyer follow-ups, market comps |
| 2 | Finance | chairman | Loan analysis, LP term sheets, cash flow models |
| 3 | Legal/Claims | projects | Dispute analysis, deadline tracking, evidence review |
| 4 | Asset Management | projects | Hotel KPI reports, operational benchmarks |
| 5 | Research | network | Market intelligence, competitor analysis, due diligence |
| 6 | Comms/Draft | chairman | Email drafts, presentations, board memos |
| 7 | IT Infrastructure | projects | M365 migration, BYOD security, hardware, vendor management (fully specified) |
| 8 | Investment Banking | chairman | Raising finance, analyzing projects, investor relations |
| 9 | Marketing & PR | network | Social media, ads, promotion, marketing collaterals |
| 10 | AI Development | projects | Baker system development |
| M1 | Decomposer | meta | Breaks complex tasks into sub-issues, assigns capabilities |
| M2 | Synthesizer | meta | Combines multi-capability results into unified deliverable |

**Status:** Framework built and deployed. IT capability fully specified. 9 remaining capability specs pending PM interview.

**COCKPIT-ALERT-UI** — SHIPPED. Structured command cards with 4 action types (Plan/Analyze/Draft/Specialist), per-part controls (select/skip/something else), sequential execution via /api/scan with SSE streaming. `structured_actions` JSONB column on alerts table. Haiku generates actions for T1/T2 alerts.

**PLUGINS-WEB-SEARCH-DOC-READER** — SHIPPED. 2 new agent tools: `web_search` (Tavily, tool #10) + `read_document` (email attachments + file paths, tool #11). 8 capabilities get web_search, 5 get read_document. Meta-agents have no tools by design.

**Director decisions (Q2/Q9/Q12):** Quality bar 85-90% default. Director-only visibility at launch. Success = proactive answers before asked, 10-20% editing only.

### Phase 3 — Proactive Baker (SHIPPED, Session 11 + fixes Session 12)
Baker executes the 7 standing orders autonomously. Code complete, deployed.

**Session 12 fixes (Code 300):**
- VIP SLA check: `received_at` → `timestamp` column name fix (query crashed every 5 min)
- VIP SLA check: dual-lookup by name AND WhatsApp ID (backfilled msgs have phone numbers as sender_name)
- All Phase 3 jobs: always-on completion logging (previously silent when no data to process)
- Alert source tracking: `source` column added to alerts table, all alert creation calls tagged
- WhatsApp backfill: stores individual messages to `whatsapp_messages` table (was Qdrant-only)
- WhatsApp backfill: async endpoint (BackgroundTasks) — no longer times out on long backfills

| Standing Order | Status | Notes |
|---|---|---|
| #1 No surprises in meetings | Working | Calendar OAuth verified (Session 13) |
| #2 No deadline missed | Working | 112 active deadlines tracked |
| #3 VIP 24h response | Working | Column name + WA ID matching fixed (Session 12) |
| #4 Morning briefing | Working | Runs daily 06:00 UTC |
| #5 Track commitments | **Working** | 50+ commitments seeded (Session 13 — was 0) |
| #6 Proactive intelligence | Working | 1 insight produced |
| #7 Protect calendar | Working | Calendar OAuth verified (Session 13) |

### Phase 4 — Scale & Optimize (SCOPING — Session 13)
See `BRIEF_PHASE_4_SCOPE.md` for full scope document.

**4A — Operational Hardening (cost, observability, reliability)**
- Cost monitor: API cost tracking per tool/capability, circuit breaker at €5/day
- Agent observability: PostgreSQL agent_tool_calls table, per-agent metrics, latency tracking
- Parallel execution: asyncio.gather for multi-tool calls, result caching (5-min TTL)
- Email watermark resilience: advance watermark even when no substantive emails found

**4B — Integration Expansion**
- ~~Slack~~ DONE (Session 13 — polling live, Events API webhook ready)
- ~~Calendar~~ DONE (Session 13 — OAuth verified, prep job running)
- Browser Sentinel: SHIPPED (Session 13 — BROWSER-1 merged, 10th data source)
- M365/Outlook: blocked (tenant not migrated)

**4C — Intelligence & Learning**
- Learning loop: Director feedback → tune Decision Engine weights + agent routing
- Capability spec completion: 8 remaining (PM-paced)
- Dashboard data layer: CEO Cockpit frontend enhancements

### Open Items (operational)
- ~~**WhatsApp historical backfill:**~~ DONE (Session 12)
- ~~**Email backfill re-run:**~~ DONE (Session 12)
- ~~**Slack bot integration:**~~ DONE (Session 13) — polling live, Events API webhook deployed
- ~~**Commitment seeding:**~~ DONE (Session 13) — 50+ commitments extracted from meetings + emails
- ~~**Calendar OAuth:**~~ DONE (Session 13) — verified working
- **ClaimsMax / Philip emails:** Draft emails ready, need Philip's email address
- **Wertheimer term sheet:** Financial decisions needed before Cowork can draft

## End-of-Session Checklist

Before closing a session, do these steps:

1. **Update this file.** Edit CLAUDE.md to reflect what shipped:
   - Move completed items from backlog to "done" (strikethrough)
   - Add new key files if any were created
   - Update architecture sections if flow changed
   - Add any new critical IDs, tables, or collections
2. **Commit and push.** The next session on any machine will `git pull` and get the updated state.
3. **Note blockers.** If something is blocked or half-done, add a line under the relevant backlog item so the next session knows where to pick up.

The goal: the next session reads this file and knows exactly what's current — no archaeology needed.

## Session Log

Sessions 1-6 archived in `SESSION_LOG.md`. Recent sessions below.

### Session 7 — 2026-03-05 (dimitry300 machine)
STEP1C + RETRIEVAL-FIX-1 + SSE keepalive fix. baker_tasks table, mode-aware routing, matter_registry (5 seed matters), get_matter_context tool (#9), auto-fetch from connected people.

### Session 8 — 2026-03-05 (dimitry300 machine)
Step 3 Agentic Onboarding. director_preferences table + 3 VIP columns + DB-driven prompt injection. MCP server: 23 tools (15 read + 8 write). Onboarding completed via Cowork PM: 14 preferences + 13 matters. AGENT-FRAMEWORK-1 scoped (10 specialist agents). CLAUDE.md trimmed (sessions 1-6 archived). Roadmap consolidated.

### Session 9 — 2026-03-06/07 (dimitry300 machine, Code 300 architect)
**AGENT-FRAMEWORK-1 designed, built, and deployed.** Major architectural session.

Key decisions:
- Shift from fixed agents to **composable capability sets** (Director insight: "agent" = temporary assembly, not persistent entity)
- **Decomposer + Synthesizer** as meta-capabilities for complex multi-domain tasks
- **Experience-informed retrieval** — 3 mechanisms: experience log + retrieval, Director feedback loop, curated prompt evolution
- **Fast path** (mode=handle, 80%) vs **delegate path** (mode=delegate, 20%)
- LLMs don't learn — Baker **accumulates experience as data** and consults it before acting
- Proactive alert format: structured command cards with 4 action types (Plan/Analyze/Draft/Specialist)
- Per-part controls: select actions, "something else" freetext, skip
- Director decisions: quality 85-90%, Director-only visibility, success = proactive + 10-20% editing

Built and deployed:
- 3 new files: capability_registry.py, capability_router.py, capability_runner.py
- 4 modified: store_back.py, action_handler.py, dashboard.py, waha_webhook.py
- 3 new DB tables: capability_sets, capability_runs, decomposition_log
- 12 seed capabilities (10 domain + 2 meta)
- 3 API endpoints: /api/capabilities, /api/capability-runs, /api/decompositions
- IT capability fully specified (PM session)

Briefs written:
- `BRIEF_AGENT_FRAMEWORK_1.md` v2.1 (framework + Director decisions + alert format)
- `BRIEF_COCKPIT_ALERT_UI.md` (interactive alert command interface)
- `BRIEF_PLUGINS_WEB_SEARCH_DOC_READER.md` (web search Tavily + document reader)

Also: BCOMM M365 migration meeting briefing + response letter drafted. PM's architecture document reviewed and critiqued.

### Session 10 — 2026-03-07 (dimitry300 machine, Code 300 supervisor)
**Reviewed and merged Code Brisen's first deliveries.** Branch `feat/plugins-web-search-doc-reader` (8 commits) merged to main (`fddffd5`).

Shipped:
- **COCKPIT-ALERT-UI** (5 commits) — interactive alert command cards in CEO Cockpit. Haiku generates structured actions (problem/cause/solution + action parts) for T1/T2 alerts. Director selects/skips/customizes actions, executes sequentially via /api/scan SSE. New: `structured_actions` JSONB column, dismiss endpoint, mobile responsive CSS.
- **PLUGINS-WEB-SEARCH-DOC-READER** (3 commits) — 2 new agent tools. `web_search` (Tavily SDK, graceful fallback). `read_document` (email attachment extraction via `=== ATTACHMENTS ===` marker + file path mode via extractors.py). Migration SQL run against Neon. TAVILY_API_KEY set on Render.

Bugs fixed: capability streaming (asyncio.Queue → queue.Queue + Exception catch), alert card markdown rendering (textContent → md()), copy button added. Backfilled 20 existing alerts with structured_actions. Domain capability timeouts bumped 30s → 90s.

Designed and specified **COCKPIT-V3** — full dashboard redesign with Director. Wrote `BRIEF_COCKPIT_V3.md` v1.5 (500+ lines). 11 sidebar tabs, split layout, 6-color system, matter grouping, Resolve/Dismiss exit paths, reply threads, Baker never auto-resolves, agentic RAG preservation rules. PM reviewed and approved. Prototype: `_01_INBOX_FROM_CLAUDE/baker_cockpit_v3_final.html`.

- **COCKPIT-V3 Phase A1** (5 commits) — reviewed, 1 fix applied (cache invalidation), merged. Full dashboard rewrite: sidebar navigation, Morning Brief (Haiku narrative + stats), Fires tab, Deadlines tab, Ask Baker (SSE preserved), command bar (Cmd+K). New schema: matter_slug, exit_reason, tags, board_status on alerts + alert_threads table.

- **COCKPIT-V3 Phase A2** (4 commits) — reviewed, 1 fix applied (baker reply storage in alert_threads), merged. Matter auto-assignment (score-based keyword matching in pipeline.py). Reply thread backend (POST /api/alerts/{id}/reply routes through scan_chat, GET /api/alerts/{id}/threads, 50-reply limit). Matters detail view (GET /api/matters/{slug}/items). Inline card results (SSE streams into card, not tab switch). Result toolbar (Copy, Word, Email). Enhanced deadlines (grouped by urgency). All 3 CRITICAL rules respected: every action routes through existing agentic RAG pipeline.

- **COCKPIT-V3 Phase B** (4 commits) — reviewed, 1 fix applied (auto-tag false positives: removed "it" keyword, added word-boundary matching for short keywords), merged. Tags system (15 categories, keyword-based auto-tagging in pipeline.py, GET /api/tags, POST /api/alerts/{id}/tag, GET /api/alerts/by-tag/{tag}). Ungrouped assignment (POST /api/alerts/{id}/assign with new project creation). Ask Specialist (POST /api/scan/specialist routes through _scan_chat_capability, same agentic RAG pipeline). Command bar detection (GET /api/scan/detect, regex-only, debounced badge). Board view (read-only kanban, List/Board toggle on Matters). Artifact storage (alert_artifacts table in PostgreSQL, POST /api/artifacts/save, Save button on result toolbar). All 7 verification gaps from brief addressed.

- **COCKPIT-V3 Phase C** (4 commits) — reviewed, 1 fix applied (RSS URL sanitization: reject javascript:/data: schemes in article links), merged. People tab (GET /api/people merges VIP+contacts, GET /api/people/{name}/activity across emails/WA/meetings). Search tab (GET /api/alerts/search with 7 filter params, all parameterized dynamic SQL, debounced live search). Travel tab (travel_date column, upcoming/past split). Media tab (GET /api/rss/articles + GET /api/rss/feeds, grouped by date, category filter). Alert auto-expiry (run_alert_expiry_check every 6h, T2-T4 >3 days expired, T1 + travel never expire). "Coming soon" removed — all 11 sidebar tabs functional. **COCKPIT-V3 IS COMPLETE.**

- **Phase 3A: Calendar Trigger** (4 commits) — reviewed, 1 fix applied (column name mismatches: email_messages.received_at→received_date, whatsapp_messages.body→full_text, received_at→timestamp), merged. Google Calendar polling every 15 min. Meeting auto-prep: detects meetings within 24h, assembles attendee context from memory (VIP contacts, emails, WhatsApp, past meetings), generates briefing via Haiku, creates T2 alert card. Dedup via trigger_watermarks. GET /api/calendar/upcoming with prep status. Morning Brief shows meetings today with prepped/pending badges. **Standing Order #1: "No surprises in meetings" — IMPLEMENTED.** Requires Director re-auth for calendar scope (pending).

- **Phase 3B: Proactive Upgrades** (3 commits) — reviewed, **no bugs found** (first clean delivery from Brisen), merged. Deadline proposals (Haiku generates action proposals for 48h/day_of/overdue alerts, attached as structured_actions). VIP auto-drafts (>4h unanswered → Haiku drafts substantive reply + acknowledge option, creates T2 alert with structured_actions). Morning briefing proposals (per-fire action proposals appended to Haiku narrative, inherits 30-min cache). **Standing Orders #2, #3, #4 — IMPLEMENTED.**

- **Phase 3C: Advanced** (3 commits) — reviewed, **no bugs found** (second clean delivery), merged. Commitment tracker (commitments table, Haiku extraction from meetings + emails, overdue check every 6h, GET /api/commitments). Proactive intelligence (RSS relevance scoring threshold 7/10 for alerts + 5-6 for insights, email signal detection on high-priority). Calendar protection (15-min [Baker Prep] blocks auto-created, conflict detection with T2 alerts + sorted dedup keys). **Standing Orders #5, #6, #7 — IMPLEMENTED. ALL 7 STANDING ORDERS ARE LIVE.**

**Dashboard status:** All 11 tabs live — Morning Brief (+ meetings today + proposals), Fires, Matters, People, Deadlines, Tags, Search, Ask Baker, Ask Specialist, Travel, Media.
**Proactive Baker:** 15 scheduled jobs running. Calendar prep (15min), email poll (5min), VIP SLA (5min), deadline cadence (1h), commitment check (6h), alert expiry (6h), RSS (1h), + 8 more.

### Session 12 — 2026-03-08 (dimitry300 machine, Code 300 supervisor)
**Phase 3 production review + operational fixes.** 4 commits pushed.

Production audit found Phase 3 deployed but producing zero observable output:
- **VIP SLA bug:** `whatsapp_messages.received_at` doesn't exist (column is `timestamp`). Query crashed every 5 min. Same bug class as Session 11 Phase 3A.
- **VIP SLA matching:** Backfilled WA messages have phone numbers as sender_name. Added dual-lookup by name AND WhatsApp ID.
- **Observability gap:** All Phase 3 jobs returned silently when finding nothing to process. Added always-on completion logging.
- **Alert source tracking:** Added `source` column to alerts table + migration. All create_alert() calls now tagged (pipeline, calendar_prep, vip_sla, deadline_cadence, commitment_check, rss_intelligence, calendar_protection, email_intelligence).
- **WhatsApp backfill architecture gap:** Backfill stored to Qdrant only, not `whatsapp_messages` table. Phase 3 (VIP SLA, calendar context) queries PostgreSQL directly — invisible backfill. Fixed: individual messages now stored to PostgreSQL during extraction.
- **WhatsApp backfill async:** Endpoint now uses BackgroundTasks — 365-day backfill no longer times out.

Data operations:
- **WhatsApp 365-day backfill:** Completed — 1,490+ messages from 55 chats, date range 2024-03-03 to 2026-03-08, 602 Director messages.
- **Email re-extraction:** Completed — 38 emails with attachment text (was 26).

Briefs:
- **BRIEF_SLACK_BOT_INTEGRATION.md** — Slack Events API upgrade from polling. Blocked: Director must set SLACK_BOT_TOKEN on Render.

Remaining:
- ~~Commitments table~~ FIXED Session 13 (50+ rows seeded)
- ~~Calendar OAuth~~ VERIFIED Session 13
- ~~Slack bot~~ LIVE Session 13

### Session 13 — 2026-03-08 (dimitry300 machine, Code 300 supervisor)
**Slack live + commitment extraction fixed + Browser Sentinel reviewed.** 7 commits + 1 merge.

Slack integration:
- **SLACK_BOT_TOKEN set on Render** — verified token (baker@BrisenGroup, user ID U0AFJLAP1BR)
- **Slack polling live** — every 5 min, embed to Qdrant, @Baker → pipeline
- **Events API webhook deployed** — `POST /webhook/slack` with url_verification, signature verification, event dedup. Optional upgrade from polling — Director chose polling for now.
- **Baker posted to #cockpit** — "Baker is back online"

Bugs fixed (3):
- **Gmail `sys.exit(1)`** — `authenticate()` called `sys.exit(1)` on headless token failure. `SystemExit` (BaseException) bypassed all `except Exception` handlers, silently killing the email poll scheduler job every 5 min. Changed to `raise RuntimeError`. Latent bug — would have hit on next token expiry.
- **Fireflies backfill missing commitment extraction** — `backfill_fireflies()` runs on every deploy, marks transcripts as "processed" via `pipeline.run()`, but never called `_extract_commitments_from_meeting()`. Regular poll then skipped them (already deduped). Root cause of 0 commitments.
- **Commitment extraction logging** — `logger.debug` → `logger.warning` (invisible at INFO level in production)
- **Column name mismatches** — `email_messages.body` → `full_body`, `meeting_transcripts.transcript_id` → `id`. Same bug class as Sessions 11-12.

Data operations:
- **Retroactive commitment extraction** — `POST /api/commitments/extract` endpoint. Processed 61 meeting transcripts + 180 emails via Haiku. Seeded 50+ commitments (was 0).
- **Gmail token refreshed** and uploaded to Render as Secret File.

Calendar OAuth:
- **Verified working** — calendar API connects, queries, returns results. `bakerai200@gmail.com` has access to Director's `vallen300@gmail.com` calendar. Empty because no upcoming meetings (Sunday).

Code review: feat/browser-sentinel (Brisen):
- **BROWSER-1 merged** — Baker's 10th data source. Dual-mode web monitoring (simple HTTP + Browser-Use Cloud API). 9 files, 1,199 lines. 1 fix applied (async browser-mode manual runs to avoid Render timeout). Brisen's cleanest delivery yet — zero bugs in core logic.
- **MCP tools verified** — `baker_browser_tasks` + `baker_browser_results` already in MCP server (Dropbox synced).

Phase 4 scoped — see `BRIEF_PHASE_4_SCOPE.md`.

**Baker current state:** 10 data sources, 16 scheduler jobs, 50+ commitments, 3,400+ alerts, 11-tab dashboard, all 7 standing orders functional.

## Key Documents (Dropbox)

| Document | Path | Purpose |
|----------|------|---------|
| Master Implementation Plan | `Baker-Project/Baker_Master_Implementation_Plan_1.docx` | Chat's original 16-step plan (stale snapshot) |
| Agentic RAG Transition Plan | `Baker-Project/Baker_Agentic_RAG_Transition_Plan.docx` | PM's revised plan — 15 steps, 3 horizons (current) |
| Decision Engine Brief | `Baker-Project/pm/briefs/BRIEF_DECISION_ENGINE_v1.md` | Step 1A specification (PM approved) |
| Agentic RAG Brief | `Baker-Project/pm/briefs/BRIEF_AGENTIC_RAG_v1.md` | AGENTIC-RAG-1 specification (built, not pushed) |
| Architecture v5.1 | `vallen300-bit.github.io/brisen-dashboards/Baker_Architecture_v5.html` | Three actors, three jobs, one memory |
| Operating Model v2.0 | `Baker-Project/pm/BAKER_OPERATING_MODEL_v2.md` | PM + Code + Director workflow |
| PM Onboard | `Baker-Project/pm/PM_ONBOARD.md` | Cowork PM session startup |
| Agent Framework Architecture | `Baker-Project/agent-framework-architecture.html` | PM's visual architecture (reviewed, partially adopted) |

## Director Preferences

- Bottom-line first, then supporting detail
- Warm but direct tone, like a trusted advisor
- Don't ask for confirmation on Render deploy — just push
- Challenge assumptions — play devil's advocate
- English primary, German & French in business context
