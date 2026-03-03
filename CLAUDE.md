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
| `orchestrator/scan_prompt.py` | Scan prompt (conversational output for chat) |
| `orchestrator/action_handler.py` | Intent router — email, deadline, VIP, fireflies, ClickUp actions |
| `memory/retriever.py` | Read-side: Qdrant vector search + PostgreSQL structured queries |
| `memory/store_back.py` | Write-side: PostgreSQL writes + Qdrant interaction embeddings |

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
| `triggers/waha_webhook.py` | WhatsApp webhook receiver (WAHA push, not polling) |
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
  → classify_intent() (regex fast-path → Haiku fallback)
    → clickup_action / clickup_fetch / clickup_plan → action handler → SSE response
    → email_action → draft/send → SSE response
    → deadline_action / vip_action / fireflies_fetch → handler → SSE response
    → question → RAG pipeline (retrieve context → Claude Opus → stream SSE)
```

## Architecture: How WhatsApp Works

```
WAHA webhook → waha_webhook.py
  → Director message? → _handle_director_message()
    → check_pending_plan() → ClickUp plan loop
    → check_pending_draft() → email draft loop
    → classify_intent() → route to handler → _wa_reply()
  → Non-Director → pipeline.run() or briefing queue
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
| WASSENGER_API_KEY | WhatsApp (legacy, being replaced by WAHA) |
| FIREFLIES_API_KEY | Meeting transcripts |
| TODOIST_API_TOKEN | Todoist sync |

## Qdrant Collections

baker-whatsapp, baker-emails, baker-contacts, baker-clickup, baker-todoist,
baker-documents, baker-conversations, baker-health, baker-people, baker-deals,
baker-projects, sentinel-interactions, sentinel-email, sentinel-meetings, sentinel-documents

## PostgreSQL Key Tables

`triggers_log`, `decisions`, `alerts`, `contacts`, `deals`, `preferences`,
`clickup_tasks`, `baker_actions`, `pending_drafts`, `trigger_watermarks`,
`todoist_tasks`, `conversation_memory`, `sent_emails`, `deadlines`, `vip_contacts`,
`meeting_transcripts` (ARCH-3), `email_messages` (ARCH-6), `whatsapp_messages` (ARCH-7),
`insights` (INSIGHT-1)

## Architecture: Role Division (Baker vs Cowork)

Baker is the **Chief of Staff** — always on guard, monitors, remembers, acts on routine.
Cowork (+ Claude Code) is the **Thinker & Creator** — deep analysis, brainstorming, decisions.

| Actor | Role | Context | Connected via |
|-------|------|---------|---------------|
| **Baker (Sentinel)** | Chief of Staff — monitors, remembers, acts | Always-on (Render) | Triggers, pipeline |
| **Cowork (Claude Desktop)** | Thinker — quick PM/PL coordination | 200K tokens | Baker MCP (18 tools) |
| **Claude Code CLI** | Thinker — deep analysis, heavy thinking, coding | **1M tokens** | Baker MCP (18 tools) |
| **Director (Dimitry)** | Final authority | Human | All of the above |

**MCP bridge:** Baker MCP server exposes 14 read tools + 4 write tools. Both Cowork and Claude Code connect to the same Baker memory. Decisions stored from either environment are visible to the other.

**Write tools (Cowork/Claude Code → Baker memory):**
- `baker_store_decision` → decisions table
- `baker_add_deadline` → deadlines table
- `baker_upsert_vip` → vip_contacts table
- `baker_store_analysis` → deep_analyses table

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
5. WhatsApp output — queued
6. Dashboard data layer — queued
7. Todoist — queued
8. Calendar — queued
9. M365/Outlook — blocked (tenant not live)
10. Dropbox — queued
11. Whoop — queued
12. Feedly — queued
13. Onboarding Briefing — waiting on template

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

- **2026-03-02 (dimitry300 machine):** Orientation session. Cloned repo to second workstation (/Users/dimitry300/Desktop/baker-code). Set up ClickUp API token in ~/.zshrc. Verified ClickUp Handoff Notes list access. No code changes — context transfer only. Opening prompt for future sessions established.
- **2026-03-02 (dimitry300 machine, session 2):** ARCH-1/2/5 — removed all content truncation and added missing DB columns. 8 files changed:
  - Removed [:500] truncation: deadlines.py, email_trigger.py, waha_webhook.py
  - Removed [:200] body_preview and [:300] reply_snippet truncation: sent_emails.py
  - Removed [:500] prompt and question truncation: store_back.py
  - Added `analysis_text TEXT` column to deep_analyses table (store_back.py)
  - Added `answer TEXT` column to conversation_memory table (store_back.py) + wired full_response through dashboard.py
  - Added `summary TEXT` column to rss_articles table (state.py) + store article content in rss_trigger.py
  - All include ALTER TABLE IF NOT EXISTS for live Neon migration.
  - ARCH-3 (Fireflies full transcript storage) left as "to do" — requires new table + MCP tool.
  - ARCH-4 merged into ARCH-1 (WhatsApp truncation was one of the 3 [:500] removals).
- **2026-03-02 (dimitry300 machine, session 2 continued):** Architecture & MCP bridge work:
  - **CLAUDE.md symlink:** Created symlink from Dropbox Baker-Project/CLAUDE.md → git repo. Cowork sessions can now read live technical state. Updated Cowork instructions.md to include CLAUDE.md as document #1.
  - **Cowork Session Playbook:** Created `Baker-Project/COWORK_SESSION_PLAYBOOK.md` — template for working on any Mac without Claude Code (two-file memory system: PROJECT_MEMORY + SESSION_HANDOVER).
  - **MCP write tools (4 new):** Added `baker_store_decision`, `baker_add_deadline`, `baker_upsert_vip`, `baker_store_analysis` to `baker_mcp_server.py`. Server now has 18 tools (14 read + 4 write). Closes the feedback loop: Cowork/Claude Code → Baker memory.
  - **MCP connected to Claude Code:** Added baker MCP config to `~/.claude/settings.json` on dimitry300 machine. Claude Code now has 1M context + Baker's full memory = analytical workbench.
- **2026-03-02/03 (primary machine, long session):** CLICKUP-V2 PM Overlay + ARCH full-content overhaul:
  - **CLICKUP-V2:** 3 new intents (clickup_action, clickup_fetch, clickup_plan) in action_handler.py, wired into Scan + WhatsApp. Natural-language ClickUp task management.
  - **ARCH-3:** `meeting_transcripts` PostgreSQL table + backfill (50 Fireflies transcripts). Memory-first search + recent-3 injection into Scan context. Diagnostic endpoints: GET /api/fireflies/status, POST /api/fireflies/backfill.
  - **ARCH-6:** `email_messages` PostgreSQL table + Gmail API backfill (123 emails, 14 days). email_trigger.py stores every email. Retriever keyword search + recent-3 injection. Endpoint: POST /api/emails/backfill?days=14.
  - **ARCH-7:** `whatsapp_messages` PostgreSQL table. waha_webhook.py stores every message. Retriever keyword search + recent-3 injection. No historical backfill (API limitation).
  - **Full-text enrichment:** When Qdrant returns a meeting/email chunk, retriever swaps it with complete source from PostgreSQL.
  - **Remaining truncation cleanup:** deadline_manager.py, slack_trigger.py, pipeline.py — all [:500] and [:1000] caps removed.
  - **Chunk-before-embed (Terminal 2):** store_back.py now chunks long content into ~500-token overlapping pieces before embedding. No silent truncation on Voyage AI token limit.
  - **MCP connected to Claude Desktop:** Added baker MCP config to Claude Desktop `claude_desktop_config.json` on dimitry300 machine. Installed Python 3.11 via Homebrew + dependencies (psycopg2-binary, mcp).
  - **Architecture documented:** Added "Role Division (Baker vs Cowork)" section to CLAUDE.md — Baker remembers, Cowork/Claude Code thinks. MCP bridges them.
  - **ARCH-3** ~~still open~~ CLOSED — Fireflies full transcript storage shipped.
- **2026-03-03 (primary machine, continued):** Fireflies gap diagnosis + email attachments + insights pipeline:
  - **Fireflies backfill fixed:** Rate-limited Voyage AI embedding (2s delay), 50 transcripts now in both PostgreSQL + Qdrant. Diagnostic endpoint: GET /api/fireflies/status. Manual backfill: POST /api/fireflies/backfill.
  - **Memory-first search:** handle_fireflies_fetch now checks PostgreSQL before hitting Fireflies API. Baker returns stored transcripts immediately.
  - **Recent injection:** Scan always includes 3 most recent meetings + 3 most recent emails + 3 most recent WhatsApp messages in context — regardless of keyword match.
  - **Email attachments (ARCH-6 ext):** extract_gmail.py now downloads and parses PDF, DOCX, XLSX, CSV, TXT attachments via Gmail API. Text appended to email body. Supported up to 10MB per file.
  - **Email backfill with attachments:** POST /api/emails/backfill?days=14 re-fetches from Gmail API including attachments. 123 emails backfilled (re-run needed for attachment extraction).
  - **INSIGHT-1:** New `insights` table + API (POST/GET /api/insights). Claude Code sessions can push strategic analysis into Baker's permanent memory. Auto-embedded to Qdrant. Retriever surfaces insights in Scan context.
  - **Wertheimer SFO analysis stored:** Full proposal framework for Chanel family office LP opportunity stored as insight (project: brisen-lp).
  - **WhatsApp backfill (Terminal 2):** POST /api/whatsapp/backfill endpoint added + WAHA media extraction (waha_client.py). Historical WhatsApp messages + media attachments now backfillable.

### Still To Do
- **Email backfill re-run needed:** Run POST /api/emails/backfill?days=14 again AFTER attachment code deployed — first 123 emails don't have attachment text.
- **WhatsApp historical backfill:** Run POST /api/whatsapp/backfill?days=90 to populate whatsapp_messages table with historical data. Endpoint exists, needs to be triggered.
- **Wertheimer term sheet:** Financial decisions needed (target IRR, MO Vienna valuation, GP carry structure, management fee) before Cowork can draft.

## Director Preferences

- Bottom-line first, then supporting detail
- Warm but direct tone, like a trusted advisor
- Don't ask for confirmation on Render deploy — just push
- Challenge assumptions — play devil's advocate
- English primary, German & French in business context
