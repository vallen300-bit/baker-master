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
| `orchestrator/action_handler.py` | Intent router — email, WhatsApp, deadline, VIP, fireflies, ClickUp actions |
| `orchestrator/decision_engine.py` | **DECISION-ENGINE-1A:** score_trigger() — domain, urgency, tier, mode, overrides, VIP SLA |
| `orchestrator/agent.py` | **AGENTIC-RAG-1 + STEP1B:** Agent loop with 8 tools, ToolExecutor, tier-based routing |
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
    → question → BAKER_AGENTIC_RAG flag?
        → true:  _scan_chat_agentic() → agent loop (Claude picks tools) → stream SSE
        → false: _scan_chat_legacy()  → single-pass RAG → stream SSE
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
    → question? → _handle_director_question() (WA-QUESTION-1)
      → BAKER_AGENTIC_RAG flag?
        → true:  _handle_director_question_agentic() → agent loop (max 3 iterations)
        → false: _handle_director_question_legacy() → single-pass RAG
      → _wa_reply(answer) + _wa_store_back() (Qdrant + conversation_memory)
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
- ~~**Agentic RAG transition:**~~ DONE — AGENTIC-RAG-1 shipped (session 4), DECISION-ENGINE-1A shipped (session 6), STEP1B shipped (session 6). 8 tools, tier-based routing, VIP SLA monitoring all live.
- **ClaimsMax / Philip emails:** Draft emails to Philip and Balazs ready (session 5). Need Philip's email address to send. Balazs = balazs.csepregi@brisengroup.com.
- **Cupial/Hagenauer claims:** Claims-analysis agent completed first pass. ClaimsMax database queries prepared. Resume agent ID: `aa9055f9f8bbe76fb`. Next: connect ClaimsMax database for evidence retrieval.

- **2026-03-04 (primary machine, session 5):** Slack/email flood fix + ClaimsMax + Cupial analysis:
  - **ALERT-DEDUP-1 (4 commits):**
    - `outputs/slack_notifier.py`: Two-level dedup cache (exact title 1h + topic entity 4h). Slack alerts reduced from ~1,100/day to ~20/day.
    - `orchestrator/prompt_builder.py`: Strict tier criteria — T1 max 1-2/day, T2 max 5/day, T3 default. Also tightened ClickUp tier guidance.
    - `triggers/email_trigger.py`: Fixed email gap alert spam (24h cooldown), fixed `post_alert()` wrong argument types, fixed double-processing bug (within-cycle dedup via `_seen_threads_this_cycle` set + cross-cycle dedup using thread_id instead of broken message_id matching).
    - `orchestrator/pipeline.py` + `triggers/embedded_scheduler.py`: Disabled 30-min alert digest email (was ~48 emails/day). Baker now sends 1 email/day (morning briefing at 08:00 CET).
  - **Agentic RAG brief review:** Full code-vs-brief validation. 6 validated, 9 gaps identified. Documented above.
  - **ClaimsMax analysis:** Read Philip's presentation (10 slides), Feb 25 meeting transcript (79 min, Philip/UBM strategy), Mar 4 meeting transcript (18 min, Dr. Jurkovic/UBM pitch). Drafted emails to Philip and Balazs. Produced commercialization roadmap (4 phases). Brainstorm dashboard deployed to GitHub Pages: https://vallen300-bit.github.io/claimsmax-brainstorm/
  - **Cupial/Hagenauer claims analysis:** Launched claims-analysis agent on Excel spreadsheet + Dropbox strategic docs. Financial exposure mapped, 5 immediate actions identified, ClaimsMax database queries prepared.
  - **Infra:** Installed `gh` CLI on primary machine, authenticated as vallen300-bit. Created movie-residences-sales repo with GitHub Pages: https://vallen300-bit.github.io/movie-residences-sales/
  - **New folder:** `projects/claim-management-ai/` created for ClaimsMax working files (gitignored).

- **2026-03-03 (dimitry300 machine, session 3):** Full-text storage overhaul + WhatsApp backfill build:
  - **Content truncation removal:** Removed all remaining [:8000], [:2000], [:4000] caps from extract_gmail.py, store_back.py, fireflies_trigger.py, action_handler.py, slack_trigger.py. Everything that passes noise filter is now stored in full.
  - **Chunk-before-embed:** store_back.py `store_document()` and `store_interaction()` now auto-chunk long content into ~500-token overlapping pieces before embedding. No more Voyage-3 32K token limit — 170K-char transcripts get ~95 searchable vectors instead of being truncated. Safety ceiling at 120K chars in `_embed()`.
  - **WhatsApp historical backfill (new feature):**
    - `triggers/waha_client.py` (new): WAHA API client — list_chats, fetch_messages, download_media_file, extract_media_text
    - `scripts/extract_whatsapp.py` (new): CLI backfill tool (--since, --limit, --chat-id, --dry-run, --no-media) + backfill_whatsapp() startup function
    - `triggers/waha_webhook.py`: upgraded to download media attachments, extract text via Claude Vision (images) / doc extractors (PDFs), include in pipeline content. Also stores to whatsapp_messages table (ARCH-7, merged with other terminal's work).
    - `triggers/embedded_scheduler.py`: added whatsapp_resync job (every 6 hours)
    - `outputs/dashboard.py`: added startup backfill thread (7-day catch-up) + POST /api/whatsapp/backfill?days=365 endpoint
    - `config/settings.py`: added api_key to WahaConfig
  - **Tested:** 476 chats found via WAHA API, history back to Dec 2025, media download confirmed (97KB JPEG). Dry-run and extraction verified locally.
  - **BLOCKED:** `WHATSAPP_API_KEY` env var needs to be added to Render baker-master service. Handoff note sent to PM. Once set, run: `curl -X POST -H "X-Baker-Key: bakerbhavanga" "https://baker-master.onrender.com/api/whatsapp/backfill?days=365"`
  - **Baker API key** (`bakerbhavanga`) and **WHATSAPP_API_KEY** (`8cbfd17c6ac9f44fa3c43fefaa078414`) added to `~/.zshrc` on dimitry300 machine.

- **2026-03-03 (dimitry300 machine, session 4):** AGENTIC-RAG-1 — agentic RAG transition (Phase 1 MVP):
  - **orchestrator/agent.py (NEW):** Agent loop module (~350 lines). 5 tools: search_memory, search_meetings, search_emails, search_whatsapp, get_contact. ToolExecutor with per-tool error handling. Two entry points: run_agent_loop() (blocking, WhatsApp) and run_agent_loop_streaming() (generator, Scan SSE). Hard 10s wall-clock timeout with fallback to legacy. AgentResult dataclass tracks iterations, tool calls, token counts, timing.
  - **memory/retriever.py:** `time.sleep(1)` → `time.sleep(0.05)` — eliminates 14s dead wait across 15 Qdrant collections. Standalone fix, benefits both old and new flows.
  - **orchestrator/scan_prompt.py:** Added `## MEMORY ACCESS` section to SCAN_SYSTEM_PROMPT — tells Claude about the 5 tools and how to use them.
  - **outputs/dashboard.py:** Refactored scan_chat() question flow. Extracted shared helpers: `_build_scan_system_prompt()`, `_scan_store_back()`. Feature flag at line 1057 routes to `_scan_chat_agentic()` or `_scan_chat_legacy()`. Legacy path is byte-for-byte identical behavior. Agentic path streams tokens via agent loop, logs agent metadata (tokens, iterations, tool counts) to Qdrant conv_metadata. Stream delimiter `[Searching further...]` on timeout fallback.
  - **triggers/waha_webhook.py:** Refactored `_handle_director_question()` into dispatcher + `_handle_director_question_agentic()` (max 3 iterations) + `_handle_director_question_legacy()` + `_wa_store_back()`. Feature flag, same fallback pattern.
  - **PM-reviewed:** All 6 hardening items addressed (hard timeout, separate sleep fix, example queries in tool descriptions, per-tool error handling, token logging from day one, stream delimiter on fallback).
  - **Status: NOT PUSHED.** All 5 files are modified locally, syntax-checked, ready to commit and push. Feature flag defaults to `false` — zero behavior change on deploy.

### AGENTIC-RAG-1 — Status
- ~~**Phase 1 (5 tools):**~~ DONE — pushed session 4, deployed.
- ~~**DECISION-ENGINE-1A:**~~ DONE — pushed session 6, deployed with all architect fixes.
- ~~**STEP1B (8 tools + tier routing):**~~ DONE — pushed session 6, deployed with all architect fixes.
- **STEP1C (task ledger + delegation):** NEXT — read brief, implement.
- **Phase 2 (future):** PostgreSQL `agent_tool_calls` observability table. Channel-aware tool selection.
- **Phase 3 (future):** Parallel tool execution (asyncio.gather), result caching (5-min TTL), token budget management.

- **2026-03-04 (dimitry300 machine, session 5):** Baker Vision Definition + Decision Engine Brief + Tooling Setup:
  - **Baker Vision defined (3 foundational questions answered by Director):**
    - **Q1 — Standing Orders (7 orders):** No surprises in meetings (pre-meeting briefings auto-prepared), no deadline missed (status checks + mitigation proposals), every VIP response within 24h (auto-draft), morning briefing with proposals not just data, track every commitment and enforce follow-through, proactive intelligence (analysis agents on significant signals), protect calendar and prepare the day (conflict resolution proposals).
    - **Q2 — Domain Priority:** Chairman > Projects > Network > Private > Travel. Urgency scoring: time(1-3) + money(1-3) + relationship(1-3) = 3-9. Tiers: 7-9=Tier 3 (WhatsApp immediate), 4-6=Tier 2 (Slack hourly), 1-3=Tier 1 (Dashboard morning briefing). Tiebreaker: money > external > oldest. Overrides: emotional urgency (Private flips to top), time-critical travel (Tier 3 forced), VIP 24h SLA breach.
    - **Q3 — Ideal Tuesday:** Three touchpoints: WhatsApp morning briefing (06:00, proactive proposals), Dashboard deep work (business hours, Scan + review), WhatsApp alerts (anytime, Tier 3 only). Ratio: 90% Baker handles autonomously, 8% Baker proposes + Director approves, 2% Director initiates. Three scheduler loops: overnight batch (02:00-06:00), continuous monitor (real-time Tier 3), hourly cycle (Tier 2 + Slack).
    - **Baker's two operational modes:** Mode A = Baker handles alone (routine: follow-ups, nudges, meeting invites, reservations, acknowledgments). Mode B = Baker delegates to specialist agent, copies Director, collects output, packages as proposal. Mode C = Baker escalates (insufficient context, needs Director input before delegating).
    - **All ClickUp spaces = Projects domain.** Domain classification uses content keywords, not workspace mapping.
    - **Family contacts for emotional urgency override:** Edita, Kira, Nona, Philip.
  - **BRIEF_DECISION_ENGINE_v1.md written** — saved to `Baker-Project/pm/briefs/`. Defines Step 1A: domain classifier, urgency scorer, override detector, tier assigner, handle/delegate router. ScoredTrigger dataclass flows through pipeline. 12 acceptance criteria. PM reviewed and approved with 3 structural observations.
  - **PM structural feedback incorporated:**
    - Ship scoring engine (1A) first, delegation framework (1C) as separate brief
    - Handle/delegate router ships conservative: Baker handles only proven templates, everything else defaults to Mode C (escalate) until Director promotes patterns
    - Edita is dual-role: content keywords override sender→domain mapping
    - VIP tiers: default all 11 to Tier 2 for now, assign properly during agentic onboarding (Step 3)
    - Financial thresholds: €100K/€10K approved as starting point, tune after 2 weeks
    - Haiku fallback: approved (~$0.04/day, negligible)
  - **Code Brisen tooled up:** 9 plugins installed (feature-dev, pyright-lsp, code-review, security-guidance, hookify, claude-code-setup, agent-sdk-dev, ralph-loop, skill-creator). Baker MCP connected. Security-code-reviewer agent active.
  - **Claims Analysis Agent created on Code Brisen** — specializes in construction dispute analysis (Cupial/Heidenauer €200K dispute). Reads spreadsheets, categorizes line items, assesses evidence strength, recommends recovery strategy.
  - **Baker Agentic RAG Transition Plan** read — PM's revision of Chat's Master Implementation Plan. 15 steps, 3 horizons. Step 1 resequenced: 1A = Decision Engine (brain), 1B = retrieval tool wrappers (hands), 1C = task ledger + delegation framework.
  - **Git state:** AGENTIC-RAG-1 still uncommitted on this machine (5 modified files + 1 new). Remote has 4 commits ahead (WA-SEND-1). Merge conflict on CLAUDE.md, dashboard.py, waha_webhook.py. Must resolve before pushing.

- **2026-03-05 (primary machine, session 6):** Decision Engine + Agentic RAG Step 1A + 1B:
  - **DECISION-ENGINE-1A (3 commits):** Full scoring and routing layer for all triggers.
    - `orchestrator/decision_engine.py` (NEW): score_trigger() with 4-step domain classifier (VIP cache → keyword regex → source mapping → Haiku fallback), 3-component urgency scorer (time + financial + relationship = 3-9), 2 override detectors (emotional urgency, travel urgent), tier assigner (1=urgent/WA, 2=slack, 3=dashboard), mode tagger (handle/delegate/escalate).
    - VIP cache (5-min TTL, thread-safe) + deadline cache (5-min TTL). VIP SLA monitoring job (every 5 min) — Tier 1 VIP unanswered >15min → WhatsApp alert, Tier 2 >4h → Slack alert.
    - Scoring inserted at 3 points: pipeline.py (background), waha_webhook.py (WhatsApp), dashboard.py (Scan). All non-fatal — scoring failure doesn't break pipeline.
    - TriggerEvent extended with 6 Optional scored fields. trigger_log table has 5 new columns. vip_contacts has tier + domain columns. 6 Tier 1 VIPs set.
    - Architect-reviewed: 3 critical + 5 medium + 3 low bugs found and fixed (tier numbering standardized to 1=urgent, financial parsing via finditer, startup DELETE removed, thread safety, caches, async blocking, VIP name matching, SLA query order).
  - **STEP1B (1 commit):** 3 new agent tools + tier-based RAG routing.
    - `orchestrator/agent.py`: Expanded from 5 to 8 tools — added get_deadlines, get_clickup_tasks, search_deals_insights.
    - `memory/retriever.py`: New get_clickup_tasks_search() — PostgreSQL ILIKE on clickup_tasks with status/priority/list_name filters.
    - Tier-based routing in both Scan (dashboard.py) and WhatsApp (waha_webhook.py): Tier 1 → legacy fast path (~3s), Tier 2-3 + flag → agentic tool loop (8 tools).
    - Fixed _scan_chat_legacy_stream missing domain_context, get_active_deals missing "label" metadata key, _scored NameError on scoring failure.
    - Architect-reviewed: 3 medium fixes applied (query optionality, fallback timing, psycopg2.extras import).
  - **Andrey Oskolkov + Christian Merz** added as VIP contacts (Tier 2 default, will promote to Tier 1 on next restart).
  - **Production verified:** 12 scheduler jobs (including vip_sla_check), all 5 scored columns live in trigger_log, Scan streaming works, tier routing active.

### Next Session Action Items (March 5+)
- **Step 1C:** Task ledger + delegation framework. Baker's Agentic RAG Transition Plan Step 1C. Read brief at `Baker-Project/pm/briefs/` (Dropbox on dimitry300 machine).
- **Set BAKER_AGENTIC_RAG=true on Render** to activate the 8-tool agentic loop for Tier 2-3 queries. Currently defaults to false.
- **Andrey Oskolkov + Christian Merz** need tier promotion to 1 — will happen automatically on next Render restart (startup migration).
- **Monitor:** Check trigger_log for scored fields after a few email/ClickUp poll cycles: `SELECT domain, tier, mode, COUNT(*) FROM trigger_log WHERE domain IS NOT NULL GROUP BY domain, tier, mode`

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
