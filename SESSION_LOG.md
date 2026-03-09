# Baker — Session Log Archive

Historical session logs moved from CLAUDE.md to save tokens. Current sessions stay in CLAUDE.md.

## Session 1 — 2026-03-02 (dimitry300 machine)
Orientation session. Cloned repo to second workstation (/Users/dimitry300/Desktop/baker-code). Set up ClickUp API token in ~/.zshrc. Verified ClickUp Handoff Notes list access. No code changes — context transfer only. Opening prompt for future sessions established.

## Session 2 — 2026-03-02 (dimitry300 machine)
ARCH-1/2/5 — removed all content truncation and added missing DB columns. 8 files changed:
- Removed [:500] truncation: deadlines.py, email_trigger.py, waha_webhook.py
- Removed [:200] body_preview and [:300] reply_snippet truncation: sent_emails.py
- Removed [:500] prompt and question truncation: store_back.py
- Added `analysis_text TEXT` column to deep_analyses table (store_back.py)
- Added `answer TEXT` column to conversation_memory table (store_back.py) + wired full_response through dashboard.py
- Added `summary TEXT` column to rss_articles table (state.py) + store article content in rss_trigger.py
- All include ALTER TABLE IF NOT EXISTS for live Neon migration.
- ARCH-4 merged into ARCH-1 (WhatsApp truncation was one of the 3 [:500] removals).

Architecture & MCP bridge work:
- CLAUDE.md symlink from Dropbox → git repo. Cowork sessions can now read live technical state.
- Cowork Session Playbook created.
- MCP write tools (4 new): baker_store_decision, baker_add_deadline, baker_upsert_vip, baker_store_analysis.
- MCP connected to Claude Code on dimitry300 machine.

## Session 2b — 2026-03-02/03 (primary machine, long session)
CLICKUP-V2 PM Overlay + ARCH full-content overhaul:
- CLICKUP-V2: 3 new intents (clickup_action, clickup_fetch, clickup_plan) in action_handler.py.
- ARCH-3: meeting_transcripts PostgreSQL table + backfill (50 Fireflies transcripts).
- ARCH-6: email_messages PostgreSQL table + Gmail API backfill (123 emails, 14 days).
- ARCH-7: whatsapp_messages PostgreSQL table.
- Full-text enrichment: Qdrant returns meeting/email chunk → retriever swaps with complete source from PostgreSQL.
- Chunk-before-embed: store_back.py auto-chunks long content into ~500-token overlapping pieces.
- MCP connected to Claude Desktop on dimitry300 machine.

Fireflies gap diagnosis + email attachments + insights pipeline:
- Fireflies backfill fixed (rate-limited Voyage AI, 50 transcripts in PostgreSQL + Qdrant).
- Email attachments: extract_gmail.py downloads and parses PDF, DOCX, XLSX, CSV, TXT.
- INSIGHT-1: insights table + API. Claude Code can push strategic analysis into Baker's memory.
- WhatsApp backfill endpoint added + WAHA media extraction.

## Session 3 — 2026-03-03 (dimitry300 machine)
Full-text storage overhaul + WhatsApp backfill build:
- Content truncation removal: all remaining caps removed from extract_gmail.py, store_back.py, fireflies_trigger.py, action_handler.py, slack_trigger.py.
- Chunk-before-embed in store_back.py (store_document + store_interaction).
- WhatsApp historical backfill: waha_client.py (new), extract_whatsapp.py (new), waha_webhook.py upgraded with media download + Claude Vision OCR.
- embedded_scheduler.py: whatsapp_resync job (every 6 hours).
- Tested: 476 chats, history back to Dec 2025, media download confirmed.
- BLOCKED: WHATSAPP_API_KEY needs to be added to Render.

## Session 4 — 2026-03-03 (dimitry300 machine)
AGENTIC-RAG-1 — agentic RAG transition (Phase 1 MVP):
- orchestrator/agent.py (NEW): Agent loop, 5 tools, ToolExecutor, 10s timeout with fallback.
- memory/retriever.py: sleep(1) → sleep(0.05), eliminates 14s dead wait.
- Feature flag routing in dashboard.py and waha_webhook.py.
- PM-reviewed: all 6 hardening items addressed.

## Session 5 — 2026-03-04 (primary machine)
Slack/email flood fix + ClaimsMax + Cupial analysis:
- ALERT-DEDUP-1: Two-level dedup cache, alerts reduced from ~1,100/day to ~20/day.
- Email trigger dedup fixes (24h cooldown, thread_id dedup).
- Disabled 30-min alert digest email. Baker sends 1 email/day (morning briefing).
- ClaimsMax analysis: Philip's presentation, Feb 25 + Mar 4 meeting transcripts. Commercialization roadmap.
- Cupial/Hagenauer claims analysis agent.

## Session 5b — 2026-03-04 (dimitry300 machine)
Baker Vision Definition + Decision Engine Brief + Tooling Setup:
- Baker Vision defined (3 foundational questions answered by Director): 7 standing orders, domain priority (Chairman > Projects > Network > Private > Travel), urgency scoring (3-9), ideal Tuesday (3 touchpoints), operational modes (handle/delegate/escalate).
- BRIEF_DECISION_ENGINE_v1.md written and PM-approved.
- Code Brisen tooled up (9 plugins, Baker MCP connected).
- Claims Analysis Agent created on Code Brisen.

## Session 6 — 2026-03-05 (primary machine)
Decision Engine + Agentic RAG Step 1A + 1B:
- DECISION-ENGINE-1A: score_trigger() with 4-step domain classifier, 3-component urgency scorer, 2 override detectors, tier assigner, mode tagger. VIP cache (5-min TTL), VIP SLA monitoring.
- STEP1B: 3 new agent tools (get_deadlines, get_clickup_tasks, search_deals_insights). Tier-based routing.
- Architect-reviewed: 3 critical + 5 medium + 3 low bugs found and fixed.
- Andrey Oskolkov + Christian Merz added as VIP contacts.
- Production verified: 12 scheduler jobs, all scored columns live.


## Session 7 — 2026-03-05 (dimitry300 machine)
STEP1C + RETRIEVAL-FIX-1 + SSE keepalive fix. baker_tasks table, mode-aware routing, matter_registry (5 seed matters), get_matter_context tool (#9), auto-fetch from connected people.

## Session 8 — 2026-03-05 (dimitry300 machine)
Step 3 Agentic Onboarding. director_preferences table + 3 VIP columns + DB-driven prompt injection. MCP server: 23 tools (15 read + 8 write). Onboarding completed via Cowork PM: 14 preferences + 13 matters. AGENT-FRAMEWORK-1 scoped (10 specialist agents). CLAUDE.md trimmed (sessions 1-6 archived). Roadmap consolidated.

## Session 9 — 2026-03-06/07 (dimitry300 machine, Code 300 architect)
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

## Session 10 — 2026-03-07 (dimitry300 machine, Code 300 supervisor)
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

## Session 12 — 2026-03-08 (dimitry300 machine, Code 300 supervisor)
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

## Session 13 — 2026-03-08 (dimitry300 machine, Code 300 supervisor)
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

Phase 4 scoped — see `BRIEF_PHASE_4_SCOPE.md`. Director decisions: €15 alert / €100 hard-stop, Feedly dropped, Browser seed tasks agreed.

Output formatting:
- **Slack alert formatting** — bold summary (first sentence), Contact/Matter/Action as compact fields, divider, bullet points, auto-bold currencies (EUR/CHF/USD) and dates. Abbreviation-aware sentence detection (Mr. Dr. etc.).
- **WhatsApp signature** — external messages prefixed with "📋 Baker AI — Office of Dimitry Vallen". Director messages sent without signature.

**Baker current state:** 10 data sources, 16 scheduler jobs, 50+ commitments, 3,400+ alerts, 11-tab dashboard, all 7 standing orders functional. Slack alerts formatted. WhatsApp messages signed.

## Session 14 — 2026-03-08 (dimitry300 machine, Code 300 supervisor)
**Phase 4A shipped + all 11 capability specs + Browser Sentinel seeded.** 2 commits + 4 seed tasks.

**The biggest session yet — 18 commits + 4 merges + 4 seed tasks. Brisen: 6 consecutive clean deliveries.**

Phase 4A — Cost Monitor + Agent Observability (300):
- **`api_cost_log` table** — every Anthropic API call logged (model, tokens, cost in EUR). 6 call sites instrumented.
- **Circuit breaker** — €15 alert (Slack + WhatsApp), €100 hard-stop.
- **`agent_tool_calls` table** — every tool execution logged (latency, success/fail, capability).
- **4 new endpoints** — `/api/cost/today`, `/api/cost/history`, `/api/agent-metrics`, `/api/agent-metrics/errors`
- **`/health` endpoint** — public, no auth, for Render + monitoring.
- **`/api/status` enriched** — now includes cost_today_eur, scheduled_jobs, email_last_polled.

PM Handover — All 11 Capability Specs (300):
- **Slug renames:** `asset_mgmt` → `asset_management`, `comms` → `communications`
- **Retired:** `ib` → replaced by `pr_branding`
- **New:** `profiling` (proactive_flag), `pr_branding` (proactive_flag)
- **All 11 updated** with Director-approved full specs. Decomposer updated. Seed data updated.

Owner's Lens C+D (300):
- **Enhanced scoring** — `_score_owner_signal()` as 4th scoring axis (MOHG, 8 strategic contacts, JV/co-invest). Tier thresholds adjusted (4-axis range 4-12).
- **Briefing split** — Owner's View (top, always shown) → Decisions Needed → Operations.

Proactive Flag + AO Profiling (Brisen, clean):
- **Proactive scanner** — 30-min job scanning content against proactive_flag capability patterns.
- **AO mood classification** — Russian + English keywords, negative → T1 alert.
- **Communication gap tracker** — 6h job, 3-day AO threshold.
- **Calendar prep enrichment** — AO meetings get mood context.
- **Real-time pipeline boost** — proactive_flag patterns boost to min tier 2.

Learning Loop (Brisen, clean):
- **Cockpit feedback buttons** — Good/Revise/Wrong after Scan responses.
- **WhatsApp + Slack feedback** — "good"/"wrong"/"revise" detected and stored.
- **Fast-path experience retrieval** — capability prompts include past negative feedback.
- **Capability quality endpoint** — `/api/capability-quality` with acceptance rates.

Dashboard (Brisen, clean × 2):
- **System Health widgets** — cost today, agent metrics, capability quality on Morning Brief.
- **Commitments tab** — 50+ items, filter by status, overdue badges. (13 sidebar tabs total)
- **Browser Monitor tab** — 4 tasks, latest results, Run Now button.

Operational Fixes (300):
- **Email watermark resilience** — separate last_checked from last_email_seen, gap alert downgraded to T2.
- **Connection pool health** — `_put_conn()` always rollbacks before returning to pool.
- **T1 WhatsApp delivery** — all T1 alerts push to Director's WhatsApp automatically.
- **Slack feedback** — @Baker good/wrong/revise detected and stored.

Data Operations:
- **4 Browser Sentinel tasks seeded** — MO rates, Park Hyatt rates, Grundbuch, MO occupancy. BROWSER_USE_API_KEY set.
- **Philip Vallen email** — unblocked (philipvallen@ellietechnologies.co.uk).
- **6 VIPs created** — Oskolkov (T1), Yurkovich (T1), Steininger (T2), Walter Steininger (T2), Zangenfeind (T2), Zimmermann (T2).
- **11 duplicate VIP records cleaned.**
- **17 stale git branches deleted** (local + remote).

**Baker current state:** 10 data sources, 20 scheduler jobs, 50+ commitments, 3,388+ alerts, 13-tab dashboard, all 7 standing orders functional, 4 browser tasks active, 13 capabilities (all fully specified), cost monitoring + agent observability live, learning loop active, proactive scanning live, Owner's Lens scoring live, T1 WhatsApp delivery live.

## Session 15 — 2026-03-09 (dimitry300 machine, Code 300 supervisor)
**Production health + Sentinel Health Monitor.** 7 commits + 2 Brisen merges. Fixed OOM, email watermark, cost tracking instrumentation, ClickUp watermark, 4 missing credentials. Merged SENTINEL-HEALTH-1 (Brisen). Render env var crisis (PUT replaces all — 15-min outage, fully restored).

## Session 16 — 2026-03-09 (dimitry300 machine, Code 300 supervisor)
**Production health audit + 3 fixes.** 1 commit.

Investigations:
- Email 429: no backoff, every 5-min poll re-triggered rate limit for 67+ hours
- Dropbox: refresh token on Render is malformed (Director must regenerate)
- Whoop: OAuth credentials invalid (Director must re-authorize)
- ClickUp: all 6 workspaces authenticate, 4 have 0 spaces (not a bug)
- Cost tracking: 2 daily Haiku calls uninstrumented

Fixes shipped:
- **Email 429 backoff** — parse Retry-After timestamp, skip polls during backoff, exponential fallback (10min→1h max)
- **Cost tracking** — `log_api_cost()` added to `_get_morning_narrative()` + `_generate_morning_proposals()`
- **Whoop sentinel** — `report_failure()` on client init error (was invisible to sentinel_health)

**Blocked:** Dropbox + Whoop need valid OAuth credentials from Director.
