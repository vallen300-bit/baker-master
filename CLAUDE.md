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

## Phase 1 Backlog (PM-approved order)

1. ~~Brief 9C fixes~~ — DONE
2. ~~ClickUp foundation (B1-B4)~~ — DONE
3. ~~CLICKUP-V2 PM Overlay~~ — DONE (3 intents: action, fetch, plan)
4. Slack integration — queued
5. ~~WhatsApp input (backfill + media)~~ — DONE (backfill script, media OCR, 6h re-sync, API endpoint). **BLOCKED:** needs `WHATSAPP_API_KEY` added to Render env vars to activate.
6. ~~WhatsApp output~~ — DONE (WA-QUESTION-1: Director questions get Scan-style conversational replies via WhatsApp)
6b. ~~WhatsApp send to contacts~~ — DONE (WA-SEND-1: Baker sends WhatsApp to any VIP contact on command + 15-turn short-term memory)
7. Dashboard data layer — queued
8. Todoist — queued
9. Calendar — queued
10. M365/Outlook — blocked (tenant not live)
11. Dropbox — queued
12. Whoop — queued
13. Feedly — queued
14. Onboarding Briefing — waiting on template

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

### Completed Milestones (sessions 1-8)
- ~~ARCH-1/2/3/4/5/6/7~~ — full-text storage, no truncation, all data sources
- ~~CLICKUP-V2~~ — 3 intents (action, fetch, plan)
- ~~AGENTIC-RAG-1~~ — 9 tools, agent loop, tier-based routing
- ~~DECISION-ENGINE-1A~~ — domain classifier, urgency scorer, VIP SLA monitoring
- ~~STEP1B~~ — 8 tools + tier routing
- ~~STEP1C~~ — baker_tasks table, mode-aware routing, domain/mode prompts
- ~~RETRIEVAL-FIX-1~~ — matter registry (13 matters), auto-fetch from connected people
- ~~Step 3 (Onboarding)~~ — director_preferences (14 prefs), VIP profile enrichment, DB-driven prompts
- ~~ALERT-DEDUP-1~~ — Slack alerts reduced from ~1,100/day to ~20/day
- ~~INSIGHT-1~~ — insights table + API
- MCP server: 23 tools (15 read + 8 write)

### Open Items
- **WhatsApp historical backfill:** Run `POST /api/whatsapp/backfill?days=365` (needs `WHATSAPP_API_KEY` on Render)
- **Email backfill re-run:** Run POST /api/emails/backfill?days=14 for attachment text extraction
- **ClaimsMax / Philip emails:** Draft emails ready, need Philip's email address
- **Wertheimer term sheet:** Financial decisions needed before Cowork can draft

### Session 7 — 2026-03-05 (dimitry300 machine)
STEP1C + RETRIEVAL-FIX-1 + SSE keepalive fix. baker_tasks table, mode-aware routing, matter_registry (5 seed matters), get_matter_context tool (#9), auto-fetch from connected people. SSE keepalive pings fixed connection drops.

### Session 8 — 2026-03-05 (dimitry300 machine)
Step 3 Agentic Onboarding. director_preferences table + 3 VIP columns + DB-driven prompt injection. MCP server: 23 tools (15 read + 8 write). Onboarding completed via Cowork PM: 14 preferences + 13 matters loaded. AGENT-FRAMEWORK-1 scoped (10 specialist agents).

### Next: AGENT-FRAMEWORK-1
Multi-agent orchestration — Baker delegates to 10 specialist agents:
Sales, Finance, Legal/Claims, Asset Management, Research, Comms/Draft, IT, Investment Banking, Marketing & PR, AI Development.
Option C: manual trigger + proactive routing. Director defines specs with Cowork PM → PM sends summary → Code 300 architects + writes brief → Code Brisen builds.

### Deferred
- **Step 4 (Cost Monitor):** API cost tracking, circuit breaker at €5/day
- **Morning Briefing Upgrade:** Data dump → agentic proposals
- **Calendar Integration:** Pre-meeting briefings + conflict detection
- **RETRIEVAL-FIX-2:** Background trigger auto-tagging against matter registry
- **Commitment Tracker:** Extract + track commitments from meetings/emails

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
