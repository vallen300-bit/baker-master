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
| `orchestrator/action_handler.py` | Intent router — email, WhatsApp, deadline, VIP, fireflies, ClickUp actions |
| `orchestrator/decision_engine.py` | **DECISION-ENGINE-1A:** score_trigger() — domain, urgency, tier, mode, overrides, VIP SLA |
| `orchestrator/agent.py` | **AGENTIC-RAG-1 + STEP1B + RETRIEVAL-FIX-1:** Agent loop with 9 tools, ToolExecutor, tier-based routing, matter-aware search |
| `memory/retriever.py` | Read-side: Qdrant vector search + PostgreSQL structured queries |
| `memory/store_back.py` | Write-side: PostgreSQL writes + Qdrant interaction embeddings + STEP3 director_preferences + VIP profiles |

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
    → clickup_action / clickup_fetch / clickup_plan → action handler → SSE response
    → email_action → draft/send → SSE response
    → whatsapp_action → resolve VIP name → send via WAHA → SSE response
    → deadline_action / vip_action / fireflies_fetch → handler → SSE response
    → question → score_trigger() → baker_task created → mode+tier routing:
        → tier 1 + mode!=delegate: _scan_chat_legacy() → fast path (~3s) → stream SSE
        → mode==delegate OR agentic flag: _scan_chat_agentic() → agent loop (8 tools, mode-aware prompt) → stream SSE
        → else: _scan_chat_legacy() → single-pass RAG → stream SSE
        → baker_task closed with deliverable + agent metadata
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
`director_preferences` (STEP3)

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
Baker becomes an orchestrator that delegates to specialist AI agents. Each agent has its own system prompt, tools, and domain expertise.

**AGENT-FRAMEWORK-1** — 10 specialist agents:

| # | Agent | Domain | Purpose |
|---|-------|--------|---------|
| 1 | Sales Agent | projects | MO Residences pitch decks, buyer follow-ups, market comps |
| 2 | Finance Agent | chairman | Loan analysis, LP term sheets, cash flow models |
| 3 | Legal/Claims Agent | projects | Dispute analysis, deadline tracking, evidence review |
| 4 | Asset Management Agent | projects | Hotel KPI reports, operational benchmarks |
| 5 | Research Agent | network | Market intelligence, competitor analysis, due diligence |
| 6 | Comms/Draft Agent | chairman | Email drafts, presentations, board memos |
| 7 | IT Agent | projects | M365 migration, Azure EU, infrastructure |
| 8 | Investment Banking Manager | chairman | Raising finance, analyzing projects, investor relations |
| 9 | Marketing & PR Agent | network | Social media, ads, promotion, marketing collaterals |
| 10 | AI Development Agent | projects | Baker system development |

**Trigger model:** Option C — Director can trigger manually ("Baker, have the finance agent analyze X") AND Baker can trigger proactively on matching signals.

**Process:** Director defines each agent's specs with Cowork PM → PM writes summary → Code 300 architects framework + writes brief → Code Brisen builds.

### Phase 3 — Proactive Baker (NEXT after Phase 2)
Baker executes the 7 standing orders autonomously. Requires Phase 2 agents + calendar integration.

| Standing Order | Depends On |
|---|---|
| No surprises in meetings — auto-prepare briefings | Calendar integration + Research Agent |
| No deadline missed — status checks + proposals | Commitment Tracker + Legal Agent |
| VIP 24h response — auto-draft responses | Comms/Draft Agent |
| Morning briefing with proposals | Morning Briefing Upgrade + all agents |
| Track commitments + follow-through | Commitment Tracker (new) |
| Proactive intelligence — analysis on signals | RETRIEVAL-FIX-2 + Research Agent |
| Protect calendar + prepare the day | Calendar integration |

### Phase 4 — Scale & Optimize (FUTURE)
- **Cost Monitor (Step 4):** API cost tracking, circuit breaker at €5/day
- **Agent Observability:** PostgreSQL agent_tool_calls table, per-agent metrics
- **Parallel Execution:** asyncio.gather for multi-tool calls, result caching (5-min TTL)
- **Additional Integrations:** Slack (queued), Calendar, M365/Outlook (blocked — tenant not live), Dropbox, Whoop, Feedly
- **Dashboard Data Layer:** CEO Cockpit frontend enhancements
- **Learning Loop:** Director feedback → tune Decision Engine weights + agent routing

### Open Items (operational)
- **WhatsApp historical backfill:** Run `POST /api/whatsapp/backfill?days=365` (needs `WHATSAPP_API_KEY` on Render)
- **Email backfill re-run:** Run POST /api/emails/backfill?days=14 for attachment text extraction
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

## Director Preferences

- Bottom-line first, then supporting detail
- Warm but direct tone, like a trusted advisor
- Don't ask for confirmation on Render deploy — just push
- Challenge assumptions — play devil's advocate
- English primary, German & French in business context
