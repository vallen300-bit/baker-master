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
| `orchestrator/agent.py` | **AGENTIC-RAG-1 + STEP1B + RETRIEVAL-FIX-1:** Agent loop with 12 tools, ToolExecutor, tier-based routing, matter-aware search |
| `orchestrator/capability_registry.py` | **AGENT-FRAMEWORK-1:** Loads capability definitions from DB, 5-min cache, trigger pattern matching |
| `orchestrator/capability_router.py` | **AGENT-FRAMEWORK-1:** Fast path (single capability) + delegate path (decomposer → multi-capability → synthesizer) |
| `orchestrator/capability_runner.py` | **AGENT-FRAMEWORK-1:** Executes capability runs — run_single, run_streaming, run_multi, run_synthesizer |
| `memory/retriever.py` | Read-side: Qdrant vector search + PostgreSQL structured queries + **full-text enrichment (meetings, emails, documents)** |
| `memory/store_back.py` | Write-side: PostgreSQL writes + Qdrant interaction embeddings + STEP3 director_preferences + VIP profiles + **capability framework tables** + **document storage** |
| `tools/document_pipeline.py` | **SPECIALIST-UPGRADE-1B:** Haiku classify → extract pipeline for documents + email attachments |
| `tools/extraction_schemas.py` | **EXTRACTION-VALIDATION-1:** 14 Pydantic v2 models, validate_extraction(), amount coercion, promotion SQL |
| `orchestrator/cadence_tracker.py` | **F3:** Per-contact communication cadence (avg_inbound_gap_days), cadence-relative silence detection, 6h scheduled job |
| `orchestrator/risk_detector.py` | **F1:** Compounding risk detector (6 signals, 2h cycle), advisory xact locks |
| `orchestrator/chain_runner.py` | **AUTONOMOUS-CHAINS-1:** Plan-execute-verify engine. T1/T2 triggers → Claude plans → ToolExecutor runs → verify → WA notify Director |
| `orchestrator/memory_consolidator.py` | **B4:** Weekly compression of old interactions (>30d) into per-matter Haiku summaries |
| `orchestrator/trend_detector.py` | **F6:** Monthly pattern analysis — alerts, contacts, costs, matters, deadlines |
| `orchestrator/initiative_engine.py` | **PROACTIVE-INITIATIVE-1:** Daily initiative proposals (priorities + calendar + deadlines + cadence → 2-3 actions) |
| `orchestrator/sentiment_scorer.py` | **SENTIMENT-TRAJECTORY-1:** Haiku tone scoring (1-5 scale), batch backfill, sentiment trend computation |
| `orchestrator/convergence_detector.py` | **CROSS-MATTER-CONVERGENCE-1:** Weekly cross-matter entity detection (people, companies, amounts across matters) |
| `tools/linkedin_client.py` | **C1:** Provider-agnostic LinkedIn enrichment (Netrows first, swap to PDL if needed) |

### API & Dashboard
| File | Purpose |
|------|---------|
| `outputs/dashboard.py` | FastAPI app — all REST endpoints + scan_chat() SSE streaming + /mobile route + /api/contacts/enrich |
| `outputs/static/index.html` | CEO Cockpit frontend |
| `outputs/static/app.js` | Frontend JS with bakerFetch() auth wrapper |
| `outputs/static/mobile.html` | **MOBILE-WEB-1:** Standalone mobile page (Ask Baker + Ask Specialist, PWA) |
| `outputs/static/mobile.js` | Mobile JS — SSE streaming, capability picker, dark mode |
| `outputs/static/mobile.css` | Mobile CSS — touch-friendly, `100dvh`, dark mode via prefers-color-scheme |
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
`capability_runs` (AGENT-FRAMEWORK-1), `decomposition_log` (AGENT-FRAMEWORK-1),
`documents` (SPECIALIST-UPGRADE-1A), `document_extractions` (SPECIALIST-UPGRADE-1B),
`baker_insights` (SPECIALIST-UPGRADE-1B),
`trips` (TRIP-INTELLIGENCE-1), `trip_contacts` (TRIP-INTELLIGENCE-1),
`proactive_initiatives` (PROACTIVE-INITIATIVE-1)

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

**AGENT-FRAMEWORK-1** — 13 capability sets deployed (11 domain + 2 meta):

| # | Slug | Domain | Autonomy | Purpose |
|---|------|--------|----------|---------|
| 1 | `sales` | projects | recommend_wait | MORV residences, investor pipeline, deal origination |
| 2 | `finance` | chairman | recommend_wait | Group finances, project tracking, tax/audit |
| 3 | `legal` | projects | recommend_wait | 5-jurisdiction legal, disputes, deadlines |
| 4 | `asset_management` | projects | recommend_wait | Property ops, portfolio KPIs, capex, insurance |
| 5 | `it` | projects | recommend_wait | M365, cybersecurity, vendor mgmt, Baker infra |
| 6 | `profiling` | chairman | **proactive_flag** | Counterparty dossiers, negotiation tactics, game theory |
| 7 | `research` | network | **proactive_flag** | Market/competitor intel, price monitoring, OSINT |
| 8 | `communications` | chairman | recommend_wait | Email drafts, investor comms, meeting prep |
| 9 | `pr_branding` | network | **proactive_flag** | Brand strategy, reputation, media, digital presence |
| 10 | `marketing` | network | recommend_wait | Capability marketing, residence collateral, campaigns |
| 11 | `ai_dev` | projects | recommend_wait | Project clAIm + Baker development |
| M1 | `decomposer` | meta | auto_execute | Breaks complex tasks into sub-issues |
| M2 | `synthesizer` | meta | auto_execute | Combines multi-capability results |

**Status:** All 11 domain capabilities fully specified (PM Session D, Mar 8, 2026). `ib` (Investment Banking) retired, replaced by `pr_branding`. Slugs renamed: `asset_mgmt` → `asset_management`, `comms` → `communications`. New autonomy level: `proactive_flag` (Baker detects and flags, distinct from `recommend_wait`).

**COCKPIT-ALERT-UI** — SHIPPED. Structured command cards with 4 action types (Plan/Analyze/Draft/Specialist), per-part controls (select/skip/something else), sequential execution via /api/scan with SSE streaming. `structured_actions` JSONB column on alerts table. Haiku generates actions for T1/T2 alerts.

**PLUGINS-WEB-SEARCH-DOC-READER** — SHIPPED. 2 new agent tools: `web_search` (Tavily, tool #10) + `read_document` (email attachments + file paths, tool #11). 8 capabilities get web_search, 5 get read_document. Meta-agents have no tools by design.

**SPECIALIST-UPGRADE-1A** — SHIPPED (Session 17). Full document storage in PostgreSQL `documents` table. Dropbox trigger stores complete text before chunking. Retriever swaps Qdrant chunks with full PostgreSQL text (same pattern as meetings/emails). Budget-aware truncation: 12K chars for enriched results (6x over 2K cap). Zero API cost.

**SPECIALIST-UPGRADE-1B** — SHIPPED (Session 17). Document intelligence pipeline: Haiku classify + extract → `document_extractions` table (structured JSON). Email attachments stored as standalone documents + extraction pipeline. `search_documents` tool (#12) on 5 capabilities (legal, finance, asset_management, sales, research). Shared `baker_insights` table injected into all specialist prompts. **Remaining:** file upload UI, backfill scripts (~$130), auto-insight extraction after specialist runs.

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
- ~~Capability spec completion: 8 remaining (PM-paced)~~ ALL 11 DONE (Session 14)
- ~~Full document storage + retrieval~~ DONE (Session 17 — SPECIALIST-UPGRADE-1A)
- ~~Document intelligence pipeline (classify + extract)~~ DONE (Session 17 — SPECIALIST-UPGRADE-1B)
- ~~Email attachments as standalone documents~~ DONE (Session 17 — SPECIALIST-UPGRADE-1B)
- ~~Shared specialist memory (baker_insights)~~ DONE (Session 17 — SPECIALIST-UPGRADE-1B)
- Dashboard data layer: CEO Cockpit frontend enhancements

### Open Items (operational)
- ~~**WhatsApp historical backfill:**~~ DONE (Session 12)
- ~~**Email backfill re-run:**~~ DONE (Session 12)
- ~~**Slack bot integration:**~~ DONE (Session 13) — polling live, Events API webhook deployed
- ~~**Commitment seeding:**~~ DONE (Session 13) — 50+ commitments extracted from meetings + emails
- ~~**Calendar OAuth:**~~ DONE (Session 13) — verified working
- **ClaimsMax / Philip emails:** Draft emails ready, need Philip's email address
- **Wertheimer term sheet:** Financial decisions needed before Cowork can draft
- **Document backfill:** ~3,188 Dropbox docs + ~2,000 email attachments need full-text storage + extraction (~$130 Haiku cost)
- **File upload UI:** Dashboard upload endpoint + drag-and-drop (SPECIALIST-UPGRADE-1B Item 4)
- **Auto-insight extraction:** Haiku call after specialist runs to store findings to baker_insights (deferred — needs testing)
- ~~**Extraction validation:**~~ DONE (Session 23) — 14 Pydantic models, validated column, amount coercion
- ~~**Travel card bug (flights vanishing):**~~ DONE (Session 23) — poll_todays_meetings(), dedicated travel_alerts query
- ~~**Travel/Meeting grid split:**~~ DONE (Session 23) — route card renderer, Travel | Fires | Deadlines | Meetings layout
- ~~**TRIP-INTELLIGENCE-1 Batch 0+1:**~~ DONE (Session 24) — trips+trip_contacts tables, city extraction, auto-detection, 5 API endpoints, full-screen trip view, route card enhancements
- ~~**TRIP-INTELLIGENCE-1 Batch 2:**~~ DONE (Session 24) — 6 trip cards with real data (Logistics, Agenda, Reading, Radar, Timezone, Objective). Zero LLM cost.
- ~~**INTERACTION-PIPELINE-1:**~~ DONE (Session 24) — contact_interactions populated (2,936+ rows), trigger hooks, daily sync, WAHA contact sync (512 contacts)
- ~~**Stats bar cleanup:**~~ DONE (Session 24) — removed separate stats bar, counts inline in grid headers, unanswered badge
- ~~**Python 3.12 regex fix:**~~ DONE (Session 24) — inline (?i) flags → re.IGNORECASE
- ~~**Email sender metadata:**~~ DONE (Session 24) — format_thread() populates primary_sender, upsert COALESCE
- **TRIP-INTELLIGENCE-1 Batch 3:** People intelligence, Proxycurl LinkedIn, conference attendees. Next major feature.
- **TRIP-INTELLIGENCE-1 Batch 4:** Trip outcomes + Networking bridge.
- ~~**OBLIGATIONS-UNIFY-1:**~~ DONE (Session 24+25) — migrated to deadlines, triaged 503→408 active. Old commitments table marked 'migrated' to stop false alerts.
- ~~**Commitment checker bug:**~~ FIXED (Session 25) — was querying old commitments table, generating ~13 false alerts every 6h.
- ~~**Email noise filter:**~~ FIXED (Session 25) — removed x-mailer, loosened list-unsubscribe filter. Backfill re-running.
- ~~**Alert bulk cleanup:**~~ DONE (Session 25) — 297→113 pending alerts. Duplicates, stale, commitment-based alerts dismissed.
- **Proxycurl LinkedIn integration:** ~EUR 40/month, needed for Batch 3. Account setup required.
- ~~**Contact enrichment:**~~ DONE (Session 25) — 55 contacts classified by Haiku (15 T1, 32 T2, 8 T3). Remaining 427 have <2 interactions. POST /api/contacts/enrich endpoint for re-runs.
- ~~**Mobile web:**~~ DONE (Session 25) — /mobile page with Ask Baker + Ask Specialist, PWA, dark mode.
- ~~**Alert dedup fix:**~~ DONE (Session 25+26) — ALERT-DEDUP-2 (pipeline.py) + ALERT-DEDUP-3 (universal in create_alert(), case-insensitive, prefix-normalized, 6h window).
- ~~**Email 365-day backfill:**~~ RUN (Session 25) — 267 emails (ceiling with current noise filters). No new historical emails found beyond existing ~30-day window.
- ~~**Commitment checker disabled:**~~ DONE (Session 26) — all 625 commitments migrated to deadlines. Scheduler job removed. deadline_cadence covers all reminders.
- ~~**Soft obligation triage:**~~ DONE (Session 26) — 391→77 soft obligations. Auto-dismiss for undated soft items after 14 days added to cadence check.
- ~~**Alert bulk cleanup (round 2):**~~ DONE (Session 26) — 198→95 pending alerts. Duplicates, stale deadlines, cross-source near-duplicates dismissed.
- ~~**Email intelligence dedup:**~~ FIXED (Session 26) — source_id now passed from email trigger, prevents same thread generating duplicate intelligence alerts.
- ~~**Desktop alert triage UI:**~~ DONE (Session 26, Code Brisen) — desktop alert badge, bulk dismiss, source filter, matter grouping.
- ~~**Mobile polish:**~~ DONE (Session 26, Code Brisen) — capability loading state, scroll fix, cache bump.
- ~~**B1 conversation embeddings backfill:**~~ DONE (Session 27) — 89/89 embedded into Qdrant baker-conversations.
- ~~**ALERT-BATCH-1:**~~ DONE (Session 27) — pipeline alerts suppressed for Dropbox ingestion, replaced with batch summary. 142→37 pending alerts.
- ~~**A6 Learning loop:**~~ DONE (Session 27) — mobile feedback buttons, task_id in main scan SSE, desktop+mobile thumbs-up/down.
- ~~**F3 Cadence tracker:**~~ DONE (Session 27) — per-contact avg_inbound_gap_days, cadence-relative silence detection (replaces fixed 30d), /api/contacts/cadence endpoint, 6h scheduled job, morning brief upgraded.
- ~~**Advisory lock fix:**~~ DONE (Session 27) — risk detector + cadence tracker use pg_try_advisory_xact_lock (auto-release).
- **Proxycurl LinkedIn integration:** ~EUR 40/month, needed for Batch 3. Account setup required.
- ~~**AUTONOMOUS-CHAINS-1 Batch 0:**~~ DONE (Session 28) — first chain fired (EVOK M365, 3/6 steps). GIN index + 30s per-tool timeout deployed.
- ~~**OpenClaw/NemoClaw evaluation:**~~ DONE (Session 28) — NO-GO.
- ~~**E3 VAPID keys:**~~ GENERATED (Session 28) — Cowork adding to Render.
- ~~**COST-OPT-1 verification:**~~ CONFIRMED (Session 28) — EUR 15-20/day projected.
- ~~**C1 LinkedIn enrichment:**~~ DONE (Session 28) — enrich_linkedin tool #18, Netrows client, profiling capability updated. Activates with LINKEDIN_API_KEY env var. Netrows free trial submitted.
- ~~**B4 Memory consolidation:**~~ DONE (Session 28) — weekly Haiku compression (Sun 04:00 UTC). memory_summaries table. Agent injects into get_matter_context.
- ~~**F6 Trend detection:**~~ DONE (Session 28) — monthly analysis (1st 05:00 UTC). Alerts, contacts, costs, matters, deadlines.
- ~~**E4 Trip cards mobile:**~~ DONE (Session 28, Code Brisen) — 6 collapsible cards, dark mode, tap-to-expand.
- ~~**E8 Mobile file upload:**~~ DONE (Session 28, Code Brisen) — paperclip button, native file picker, share_target.
- **AUTONOMOUS-CHAINS-1 Batch 1:** Standing order upgrade — pending Batch 0 evaluation (3-5 days).
- **Netrows API key:** Pending — check dvallen@brisengroup.com. Add as LINKEDIN_API_KEY on Render.

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

Sessions 1-16 archived in `SESSION_LOG.md`. One-liner summaries:

| # | Date | Key deliverables |
|---|------|-----------------|
| 7 | Mar 5 | STEP1C + matter_registry + mode-aware routing |
| 8 | Mar 5 | Step 3 Onboarding, MCP 23 tools, 14 preferences, 13 matters |
| 9 | Mar 6-7 | AGENT-FRAMEWORK-1: 13 capabilities, decomposer/synthesizer, COCKPIT-ALERT-UI |
| 10 | Mar 7 | COCKPIT-V3 complete (all 11 tabs), Phase 3A-C (all 7 standing orders live) |
| 11 | Mar 7 | (merged into Session 10 log) |
| 12 | Mar 8 | Phase 3 production fixes, WA 365-day backfill (1,490 msgs) |
| 13 | Mar 8 | Slack live, commitment seeding (50+), Browser Sentinel merged |
| 14 | Mar 8 | Phase 4A (cost monitor, observability), all 11 capability specs, learning loop |
| 15 | Mar 9 | Sentinel Health Monitor, OOM fix, email watermark resilience |
| 16 | Mar 9 | Email 429 backoff, Networking tab, specialist thinking + citations, 11 Claude Code agents |
| 17 | Mar 10 | SPECIALIST-UPGRADE-1A+1B: full document storage, Haiku classify+extract pipeline, email attachments, shared baker_insights, search_documents tool #12 |
| 18 | Mar 10 | Backfill completion (1,354 docs), PM-OOM-1, Dropbox trigger fix, handoff cleanup |
| 19 | Mar 11 | **Dashboard UX overhaul (19 commits)**: ClaimsMax banking design, Cowork-style chat, per-matter scoping, WhatsApp send/body/intent fixes, contact disambiguation, auto-contacts from WA, action memory logging |
| 20 | Mar 11 | **20 deliverables**: DEEP-MODE-1+2 (dashboard=max intelligence + cross-session memory), SPECIALIST-DEEP-1, INTELLIGENCE-GAP-1 (richer context, Haiku routing, retrieval reranking), CHANNEL-TRUST-1, DOC-TRIAGE+RECLASSIFY (42%→0.9% "other"), EMAIL-ATTACH-FIX-1, artifact panel, follow-up suggestions, DASHBOARD-STATS-1, Baker Data tab, VIP→Contacts, clickup_create removal |
| 21 | Mar 13 | **10/10 sentinels HEALTHY**: missing `import re` (pipeline.py), datetime hoist (dropbox), circuit breaker reset endpoint, auto-matter assignment on all alerts, last_contact_date backfill (9/11 VIPs), cost tracking verified (EUR 8.98/day) |
| 22 | Mar 14 | Calendar cascade fix, doc pipeline re-queuing fix, briefing data bugs, DB cleanup (9,636 junk alerts). GCal cleanup (988 Baker Prep events). |
| 23 | Mar 14 | **EXTRACTION-VALIDATION-1**: 14 Pydantic models (13 types + travel_booking), validate_extraction(), amount coercion (European format). **TRAVEL-FIX-1+2**: flights visible all day (poll_todays_meetings), travel/meeting grid split, route card renderer (origin→dest, time-based dots). **TRIP-INTELLIGENCE-1 brief**: full travel ROI engine designed with Director. |
| 24 | Mar 14-16 | **Massive session (12 commits, 9 deploys).** TRIP-INTELLIGENCE-1 Batch 0+1 (trip lifecycle) + Batch 2 (6 trip cards with real data). INTERACTION-PIPELINE-1 (2,936+ interactions from email/WA/meetings). WAHA contact sync (11→512 contacts). Stats bar → inline grid counts. Python 3.12 regex fix, VARCHAR(20) fix, email sender metadata extraction. |
| 25 | Mar 17-18 | **11 commits, parallel with Code Brisen.** MOBILE-WEB-1: /mobile page (Ask Baker + Specialist, PWA, dark mode, New Chat, camera with Haiku Vision, Play-to-hear, auto-resize). /api/scan/image endpoint. ALERT-DEDUP-2 (title fuzzy dedup). CONTACT-ENRICH-1 (55 contacts classified). Alert cleanup (297→113). Obligation triage (503→409). Commitment checker bug fix. Email noise filter fix. Interaction backfill (+650 to 3,608). 7 missing contacts added. Code Brisen: SENTINEL-SAFETY-1. |
| 26 | Mar 18 | **35 commits, record session.** Operational: DEDUP-3, 198→95 alerts, 391→77 obligations, killed Whoop/commitment_checker/VIP gap. Intelligence: B1 conversation Qdrant, B2 recency decay, B3 decision injection, F1 compounding risk (6 signals), F2 news-counterparty, F5 weekly digest, F7 meeting gap detection, C2 contact silence. Agent: 13→17 tools (query_baker_data, create_deadline, draft_email, create_calendar_event). APIs: G6 data freshness, morning brief silent contacts. Strategy: Backlog v1 (48 items). Code Brisen: alert triage, mobile polish, pipeline dedup, iOS Shortcuts, push alerts (SSE), mobile alerts view, document browser. |
| 27 | Mar 19 | **9 features shipped.** B1 backfill (89 conversations). ALERT-BATCH-1 (90→1 alert/batch, 142→37 pending). A6 mobile feedback buttons. F3 cadence tracker (36 contacts, cadence-relative silence). D7 morning brief v2 merged (Code Brisen — action cards). G5 health watchdog (circuit breaker auto-recovery + WA alert). A8 insight-to-task (specialist→ClickUp). D6 unified search API. F4 financial signal detector. C6 location backfill (12→27 contacts). Backlog v2 created (27/48 shipped). Proxycurl dead → evaluating Netrows. 4 briefs for Code Brisen (E3, D8, D7, C1). |
| 28 | Mar 19-20 | **10 features, 8 commits.** AUTONOMOUS-CHAINS-1 Batch 0 (first chain fired — EVOK M365). C1 LinkedIn enrichment (enrich_linkedin tool #18 + Netrows client). B4 memory consolidation (weekly Haiku compression). F6 trend detection (monthly analysis). Contact query fix (GIN trgm index + 30s per-tool timeout). OpenClaw/NemoClaw eval (NO-GO). VAPID keys generated. COST-OPT-1 verified. Code Brisen: E4 trip cards mobile, E8 mobile file upload. Backlog: 42/48 (88%). 22 scheduled jobs. |
| 29 | Mar 20 | **All 5 Remarkable CoS Items shipped.** PROACTIVE-INITIATIVE-1: daily initiative engine (priorities + calendar + deadlines + cadence + unanswered emails → 2-3 proposed actions, WA + dashboard, approve/dismiss/defer). SENTIMENT-TRAJECTORY-1: Haiku tone scoring (1-5 batch), sentiment trend written to vip_contacts, injected into get_contact tool. CROSS-MATTER-CONVERGENCE-1: weekly entity extraction + convergence detection across matters (people, companies, amounts in 2+ matters). Chain timeout fix (shutdown(wait=False)), planning prompt tightened (max 4 steps). 9 new API endpoints. 3 new scheduler jobs (24→27 total). 3 new files. |

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
| Specialist Upgrade 1A Brief | `briefs/BRIEF_SPECIALIST_UPGRADE_1A.md` | Full document storage + retrieval (SHIPPED) |
| Specialist Upgrade 1B Brief | `briefs/BRIEF_SPECIALIST_UPGRADE_1B.md` | Document intelligence pipeline + shared memory (SHIPPED, backfill TODO) |
| Trip Intelligence Brief | `briefs/BRIEF_TRIP_INTELLIGENCE_1.md` | Travel ROI engine — trip cards, conference intelligence, LinkedIn, outcomes (APPROVED) |

## Director Preferences

- Bottom-line first, then supporting detail
- Warm but direct tone, like a trusted advisor
- Don't ask for confirmation on Render deploy — just push
- Challenge assumptions — play devil's advocate
- English primary, German & French in business context
