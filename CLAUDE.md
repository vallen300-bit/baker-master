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
| `orchestrator/obligation_generator.py` | **OBLIGATION-GENERATOR:** Daily 06:50 UTC. Haiku extracts 5-15 per-item task proposals from signals → proposed_actions table → morning push |
| `orchestrator/action_completion_detector.py` | **ACTION-COMPLETION:** Every 6h. Checks approved actions' email_to/email_from signals against sent_emails/email_messages. Auto-marks done. |
| `orchestrator/research_trigger.py` | **ART-1:** Haiku classifies VIP WhatsApp for forwarded intelligence → research_proposals table → "Run Dossier?" card |
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
baker-projects, baker-task-examples, sentinel-interactions, sentinel-email, sentinel-meetings, sentinel-documents

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
`proactive_initiatives` (PROACTIVE-INITIATIVE-1),
`proposed_actions` (OBLIGATION-GENERATOR),
`research_proposals` (ART-1),
`baker_corrections` (CORRECTION-MEMORY-1),
`browser_actions` (BROWSER-AGENT-1 Phase 3)

## Architecture: Role Division (Baker vs Cowork)

Baker is the **Chief of Staff** — always on guard, monitors, remembers, acts on routine.
Cowork (+ Claude Code) is the **Thinker & Creator** — deep analysis, brainstorming, decisions.

| Actor | Role | Context | Connected via |
|-------|------|---------|---------------|
| **Baker (Sentinel)** | Chief of Staff — monitors, remembers, acts | Always-on (Render) | Triggers, pipeline |
| **Cowork (Claude Desktop)** | Thinker — PM/PL coordination, deep analysis | **1M tokens** (Max plan) | Baker MCP (21 tools) |
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
Sessions 1-8. Full-text storage, ClickUp integration, WhatsApp I/O, Agentic RAG, Decision Engine, Task Ledger, Matter Registry, Director Onboarding, Alert Dedup, MCP Bridge.

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

All 11 domain capabilities fully specified. Also shipped: COCKPIT-ALERT-UI (structured command cards), PLUGINS-WEB-SEARCH-DOC-READER (tools #10-11), SPECIALIST-UPGRADE-1A+1B (full document storage + Haiku classify/extract pipeline + shared baker_insights).

### Phase 3 — Proactive Baker (SHIPPED)
All 7 standing orders live: meeting prep, deadline tracking, VIP 24h SLA, morning briefing, commitment tracking, proactive intelligence, calendar protection.

### Phase 4 — Scale & Optimize (MOSTLY SHIPPED)

**Remaining:**
- M365/Outlook: blocked (tenant not migrated)
- Dashboard data layer: CEO Cockpit frontend enhancements

### Open Items (operational)
- **ClaimsMax / Philip emails:** Draft emails ready, need Philip's email address
- **Wertheimer term sheet:** Financial decisions needed before Cowork can draft
- **Document backfill:** ~3,188 Dropbox docs + ~2,000 email attachments (~$130 Haiku cost)
- **File upload UI:** Dashboard upload endpoint + drag-and-drop
- **Auto-insight extraction:** Haiku call after specialist runs → baker_insights (deferred)
- **TRIP-INTELLIGENCE-1 Batch 3:** People intelligence, LinkedIn, conference attendees
- **TRIP-INTELLIGENCE-1 Batch 4:** Trip outcomes + Networking bridge
- **AUTONOMOUS-CHAINS-1 Batch 1:** Standing order upgrade — pending Batch 0 evaluation
- **Netrows API key:** Pending — check dvallen@brisengroup.com. Add as LINKEDIN_API_KEY on Render.
- **CORRECTION-MEMORY-1 Phase 3:** Nightly consolidation job — build ~2026-04-06 after data accumulates

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

Sessions 1-28 archived in `SESSION_LOG.md`.

| # | Date | Key deliverables |
|---|------|-----------------|
| 29 | Mar 20 | **All 5 Remarkable CoS Items.** PROACTIVE-INITIATIVE-1, SENTIMENT-TRAJECTORY-1, CROSS-MATTER-CONVERGENCE-1. 9 new API endpoints. 27 scheduler jobs. |
| 30 | Mar 20-21 | **Notification & Task Redesign + ART-1.** OBLIGATION-GENERATOR, ACTION-COMPLETION-DETECTOR, push throttling, auto-research trigger. 29 scheduler jobs. |
| 31 | Mar 22 | **Baker 3.0 shipped.** Extraction engine, push notifications, context selector, post-meeting pipeline, wealth manager (Russo AI). QDRANT-CLEANUP-1 (540K→64K). **Backlog: 48/48 = 100%.** |
| 32 | Mar 22 | ACTIONS-MERGE-1, MOBILE-REACTIVE-1 Batch 1, TAX-OPT-1 (21 capabilities), RUSSO-MEMORY-1, BROWSER-AGENT-1 Phase 1. |
| 33 | Mar 23 | MOBILE-REACTIVE-1 Batch 2 (Draft a Reply + Delegate). BROWSER-AGENT-1 Phase 2 (Tailscale Funnel bridge). Travel feed card. `browse_website` tool #19. 19 agent tools. |
| 34 | Mar 23 | **CORRECTION-MEMORY-1:** correction memory + episodic retrieval. Anti-bloat: max 5/capability, 90-day expiry. Phase 3 deferred ~2026-04-06. |
| 35 | Mar 23 | **BROWSER-AGENT-1 Phase 3:** Interactive browser actions + transaction gate. `browser_action` tool #20. CDP click/fill/screenshot. Confirmation cards (mobile+desktop). 20 agent tools. |
| 36 | Mar 23 | **CORRECTION-MEMORY-1 + COMPLEXITY-ROUTER-1 Phase 1.** Reinforcement learning: Haiku extracts learned_rules from thumbs-down, episodic retrieval from thumbs-up. Complexity router: merged fast/deep classification into intent classifier (zero extra API cost), shadow mode, 4 new baker_tasks columns, /api/tasks/complexity-stats endpoint. ComplexityConfig in settings.py. |

## Key Documents (Dropbox)

| Document | Path | Purpose |
|----------|------|---------|
| Architecture v5.1 | `vallen300-bit.github.io/brisen-dashboards/Baker_Architecture_v5.html` | Three actors, three jobs, one memory |
| Operating Model v2.0 | `Baker-Project/pm/BAKER_OPERATING_MODEL_v2.md` | PM + Code + Director workflow |
| PM Onboard | `Baker-Project/pm/PM_ONBOARD.md` | Cowork PM session startup |
| Trip Intelligence Brief | `briefs/BRIEF_TRIP_INTELLIGENCE_1.md` | Travel ROI engine (Batches 3-4 pending) |

## Director Preferences

- Bottom-line first, then supporting detail
- Warm but direct tone, like a trusted advisor
- Don't ask for confirmation on Render deploy — just push
- Challenge assumptions — play devil's advocate
- English primary, German & French in business context
