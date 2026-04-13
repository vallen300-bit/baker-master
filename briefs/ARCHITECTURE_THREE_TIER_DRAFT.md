# Baker Three-Tier Architecture — Draft Specification

**Status:** DRAFT — Being built collaboratively with Director
**Date started:** 13 April 2026
**Participants:** Director + AI Head (Tier 3 session)

---

## Core Principle

> Render agents bring the news. Mac Mini makes it smarter. Director decides what matters.

Three escalation levels, each adding depth. Most signals die at Tier 2. Only decisions escalate to Tier 3.

---

## The Three Tiers

### Tier 1 — Nerve Center (Render, always on)
**Role:** Detect, extract, alert. Fast, cheap, deterministic.
**Context:** ~8K wiki budget + PostgreSQL
**LLMs:** Flash (classify), Pro (drafts), Opus (deep path — but still 8K context)
**Output:** Raw signals — "something happened"

**What it does today:**
- Email pipeline (Gmail, Bluewin, Exchange)
- WhatsApp / Slack ingestion
- Calendar + deadline detection
- RSS + browser sentinel
- ClickUp / Todoist sync
- Meeting transcript ingestion (Fireflies, Plaud, YouTube)
- Capability runner (21 capabilities, all ~8K context)
- Dashboard rendering
- Slack/WhatsApp alert delivery

**What it cannot do:**
- Read Dropbox files
- Hold more than 8K of wiki context
- Cross-reference multi-document legal/financial analysis
- Compare a new term sheet against a historical facility agreement

### Tier 2 — Reasoning Engine (Mac Mini, always on, scheduled)
**Role:** Analyze, compare, enrich. Deep but asynchronous.
**Context:** 200K via Claude Code + full Obsidian vault + Dropbox
**LLMs:** Gemma 4 (free preprocessing), Claude Code (Opus, deep analysis)
**Output:** Enriched cards — "here's what it means"

**What it does:**
- Reads signal_queue for pending signals from Tier 1
- Pulls full document context from Dropbox / Obsidian vault
- Cross-references across matters, agreements, historical data
- Produces enriched analysis summaries (2-3 line card + full report)
- Writes results back to PostgreSQL (permanent knowledge assets)
- Updates wiki pages with new findings
- Runs scheduled jobs: hourly signal processing, daily lint, weekly synthesis

**What it cannot do:**
- Real-time response (async, minutes not seconds)
- Direct user interaction (no chat interface)
- Push to Slack/WhatsApp directly (writes to PG, Tier 1 delivers)

### Tier 3 — Director + AI Head (MacBook, session-based)
**Role:** Full review, strategy, decision-making. Maximum depth.
**Context:** 1M via Claude Code + everything (Dropbox, PG, web, conversation)
**LLMs:** Claude Opus 4.6 (1M context)
**Output:** Decisions, strategy, architecture — "here's what to do"

**What it does:**
- Deep document review (contracts, term sheets, legal analysis)
- Strategic decision-making with full historical context
- Architecture and planning for Baker itself
- Writing briefs for Code Brisen
- Cross-matter synthesis requiring Director judgment

**When it's triggered:**
- Director escalates from Tier 2 enriched card ("I need to review this myself")
- Not automated — Director chooses what deserves Tier 3 attention

---

## Information Flow

```
SIGNAL BORN                    SIGNAL ENRICHED                 DECISION MADE
(seconds)                      (minutes)                       (Director's time)

Tier 1 (Render)          →     Tier 2 (Mac Mini)         →     Tier 3 (MacBook)
"Balazs sent term sheet"       "3 changes vs 2023 agmt,        "Accept clause 4,
                                covenant ratios tightened"       reject prepayment
                                                                 change, counter at 1.2x"
        │                              │                               │
        ▼                              ▼                               ▼
   signal_queue                  cortex_events                  baker_decisions
   (raw signal)                  deep_analyses                  wiki_pages update
                                 wiki_pages update
                                 Qdrant vectors
```

---

## Locked-In Decisions

### 1. Enriched cards are permanent knowledge assets
Tier 2 analysis is NOT a notification that scrolls away. Every enriched analysis is stored permanently in PostgreSQL (`cortex_events`, `deep_analyses`, `wiki_pages`). Searchable by any tier at any time. Knowledge compounds — every signal that passes through Tier 2 makes the system smarter.

### 2. Dashboard is a radar, not a workbench
Dashboard shows THAT deep analysis happened + 2-3 line summary + link to full report. Does not try to render full legal analysis in a card. Stays fast, clean, scannable.

### 3. Tier 1 never tries to be smart
Render agents detect, extract, alert. They don't cross-reference agreements or do multi-document analysis. When something needs depth → signal_queue.

### 4. Tier 2 enriches asynchronously
Mac Mini processes signal_queue items on a schedule (not real-time). Director sees "analyzing..." badge until done. Result flows back to dashboard/Slack/WhatsApp via Tier 1 delivery.

### 5. Director is the bottleneck only for decisions
Reading, extracting, cross-referencing — that's Tier 1 and 2's job. Director's time is spent on judgment calls only.

### 6. PostgreSQL is the nervous system
Tier 1 ↔ Tier 2 communication. signal_queue = bridge. cortex_events = audit trail. Structured state (deadlines, VIPs, PM state). Not the document store.

### 7. Obsidian is Tier 2's brain
NOT a mirror. The primary knowledge store for Tier 2. All documents ingested as local .md files. Claude Code reads them natively — no network, no browser, no fragmentation. Dropbox is the intake funnel — documents arrive there, get extracted into Obsidian, and that's where they live for analysis.

### 8. Tier 2 retrieval is local-first
When a signal arrives, Mac Mini reads .md files from the Obsidian vault. Not 5 PostgreSQL queries. Not PDFs through Chrome. Local files on disk — fast, reliable, full context.

### 8b. Obsidian stores originals AND extracted text
Original files (PDF, DOCX, XLSX) live in `vault/matters/{matter}/documents/` alongside extracted `.md` versions. Tier 2 handles extraction (Python libraries for Word/Excel, Claude Code reads PDFs natively). The `.md` is for searching and analysis. The original is for "show me the actual signed contract." Both side by side.

### 8c. Obsidian replaces Dropbox
Dropbox was a default choice, not an architectural one. Only Director and Edita use it. No external parties share directly to it. Finding documents requires knowing nested paths — painful for humans and AI. Obsidian vault is organized by matter, searchable, linked, with an index per matter. Documents arrive via Tier 1 (email, WhatsApp) or Director instruction → Tier 2 ingests into vault. Director never needs to open Obsidian — Tier 2 and Tier 3 read it behind the scenes.

### 8d. Director never navigates Obsidian
Director's interfaces: dashboard, Slack, WhatsApp, Tier 3 conversations. Obsidian is the brain Tier 2 reads. Director says "Aukera" and the system finds everything. No paths, no folders, no digits.

### 9. Enriched cards are stored in Obsidian as timestamped views
Each enriched card is a snapshot of understanding at a point in time — stored as `.md` in `vault/matters/{matter}/cards/`. Views accumulate. When Tier 2 produces the next card, it reads all previous cards first. Analysis compounds — it doesn't start from scratch. The card trail shows how understanding evolved over time.

### 10. Tier 1 = news (sometimes noise). Tier 2+3 = turning news into actions
Render agents + PostgreSQL + Qdrant + polling = detection. Obsidian + Claude Code + Director judgment = intelligence. These are fundamentally different domains. Don't mix them.

### 11. PostgreSQL + Qdrant/Voyage = Tier 1 infrastructure
PostgreSQL stores Tier 1's operational state (VIPs, deadlines, PM state, emails, alerts). Qdrant + Voyage AI handle semantic dedup and similarity matching — Tier 1 noise reduction. Neither is the knowledge store. Tier 2 touches PostgreSQL ONLY for signal_queue (read pending signals, write results back). That's a phone call, not a home address. Tier 2's knowledge lives in Obsidian.

### 12. Tier 2 execution model: 15-min cron + per-signal Claude invocation
Mac Mini runs a cron job every 15 minutes: reads signal_queue for pending signals, processes each one. Per signal: (1) Gemini Pro triage (select vault files), (2) `claude -p "PROMPT"` — fresh 200K session for this one signal, (3) Claude analyzes, writes card to vault, exits, (4) cron script updates signal_queue result. Claude is not always running — invoked per signal like a consultant. Quiet day = 3 invocations. No signals = zero cost. No persistent daemon, no LISTEN/NOTIFY, no reconnection logic. Just cron — the thing that always works. Priority escape hatch: optional 2-min cron checks ONLY for `priority IN ('critical','high')`. Don't build it on day one. Measured latency pain earns the upgrade, not intuition.

### 12b. Fresh `claude -p` per signal — no persistent sessions
No debate. No persistent tmux Claude sessions. No long-lived processes. Fresh `claude -p` per signal, every time. Persistent sessions on a headless Mac Mini = zombie processes, memory drift, debugging nightmare. Loading 200K context from Obsidian takes ~2-3 seconds — not a cost worth managing state for. If a signal needs multi-turn reasoning, it happens as internal tool-use turns within a single `claude -p` invocation, not as a long-lived conversation. Process starts, works, exits. Clean.

### 13. Gemini Pro is the librarian, Gemma 4 is the fallback, Claude is the lawyer
Before Claude Code gets invoked, Gemini Pro (fast, cheap, proven in Baker) reads the signal + matter index and selects which vault files are relevant. Claude receives ~40K of focused context instead of 150K of everything. Cost: ~$0.004/signal (~$0.08/day at 20 signals). Failure detection: 60-second timeout OR response doesn't parse as valid file list OR HTTP error. 60 seconds because this is background processing — nobody is waiting. Better to let Pro finish than fall back to Gemma unnecessarily. On failure → fallback to Gemma 4 (free, local, always works — no network needed). Claude Opus reserved strictly for the actual analysis.

### 14a. Vault structure: Karpathy three-layer (raw/wiki/schema)
Not flat-by-matter — that causes duplication and drift. Three layers: (a) `raw/` — original extracted documents, immutable, one copy each. A contract between Aukera and RG7 lives here ONCE. (b) `wiki/` — synthesized knowledge pages, cross-linked. `wiki/aukera.md` and `wiki/rg7.md` both link to the same raw document. Enriched cards live here too (`wiki/aukera-cards/`). This is what agents read first. (c) `schema/` — templates for matters, people, cards. Tells agents the format for consistent output. Per-matter views for Director built via Obsidian dataview queries on top — no data duplication.

### 14. 200K ceiling managed by three strategies
(a) Gemma triage — select only relevant files per signal. (b) Multi-step sessions — complex signals split across sequential Claude invocations, each with fresh 200K. (c) Periodic compression — after N cards, Tier 2 writes a matter summary (quarterly .md) that replaces individual cards in future context loading. Like memory consolidation in the brain.

### 16. Deadman's switch — Mac Mini heartbeat to Render DB
Mac Mini daemon writes a heartbeat row to PostgreSQL (`tier2_heartbeat` table: `last_seen TIMESTAMPTZ, signals_processed_today INT, daemon_status TEXT`) on every signal processed, minimum every 30 min even if idle. Render scheduler checks every hour: if `last_seen` > 2 hours stale → WhatsApp alert to Director: "Tier 2 reasoning engine dark since {time}. {N} signals pending." Plus: (a) stale signal detector — any signal pending >1 hour → WhatsApp alert, (b) stuck processing — signal in "processing" >2 hours → WhatsApp alert, (c) Intent Feed Queue tab shows heartbeat age + queue depth — Director sees it on dashboard glance. All alerts via WhatsApp, not just Slack — Director lives in WhatsApp. Without this, you find out a week later because a Hagenauer analysis never came back.

### 20. Recovery — git snapshots + event-sourced replay
Decide recovery before you need it. Two layers: (a) Nightly `git commit` of the entire Obsidian vault on Mac Mini — automatic, cheap, versioned, restorable. If vault corrupts or a bad card overwrites good data → `git log`, find last good state, `git checkout`. Vault IS the source of truth, git IS the backup. (b) Event-sourced replay from `cortex_events` — the append-only event bus already logs every write. If signal_queue corrupts or wiki_pages desyncs from vault, replay events since last known good state to rebuild. signal_queue rows are immutable once written (status changes are new events, not UPDATEs). (c) PG wiki_pages is a cache — if it desyncs, nuke and re-sync from vault. No data loss because vault has everything. Recovery order: vault (git) → wiki_pages (re-sync) → signal_queue (replay from events).

### 18. Queue rot prevention — TTL + depth cap + dashboard visibility
Queues rot silently. If Mac Mini is offline for days, signals pile up. Mitigations: (a) Intent Feed gets a Queue tab showing queue depth, oldest unprocessed age, last processed timestamp — Director sees rot immediately on dashboard. (b) TTL per priority: critical=never, high=7d, normal=3d, low=24h. Expired signals move to `expired` status, logged but not surfaced. (c) Queue growth cap: if >50 pending, stop writing `low`; if >100, stop writing `normal`. `high` and `critical` always written, no cap. Render scheduler runs TTL cleanup daily. When Mac Mini comes back online, it processes only what's still alive — not a 500-signal backlog.

### 17. Conflicts structurally impossible, not just detectable
Only Mac Mini writes to vault and wiki_pages. Render agents NEVER write knowledge — not to vault, not to wiki_pages. If a Render sensor wants to tag or enrich a matter (new email detected, new deadline found), it writes to `wiki_staging` — a PostgreSQL staging table. Mac Mini daemon reads staging, decides what to promote, writes to vault in its own transaction, then syncs vault → PG wiki_pages one-way. Staging rows marked as promoted after processing. Generation counter on wiki_pages as belt-and-suspenders, but the architecture makes conflicts impossible, not just detectable. Two signals for the same matter processed sequentially by daemon (per-matter queue).

### 19. WhatsApp is the primary Director trigger, not dashboard
Director lives in WhatsApp. "Deep analyze Aukera term sheet" → Tier 1 recognizes intent, writes signal_queue with `priority='high', type='director_request'`, replies immediately "Queued for deep analysis." → Tier 2 processes → result sent back via WhatsApp with 3-bullet summary + "Full report on dashboard. Or ask me questions here." Director never leaves WhatsApp. Dashboard button is a cheap add-on (POST to `/api/signal_queue`) built after WhatsApp flow works. Don't make dashboard the sole trigger — it'll be unused.

### 22. All three tiers write dashboard content via PostgreSQL — with ownership rules
Dashboard has one generic card component. Any tier can author cards by writing to PostgreSQL. Render just displays — it's the publisher, not the author. Tier 1 cards: shallow news ("Balazs sent email"). Tier 2 cards: enriched analysis ("3 changes, covenant tightened"). Tier 3 cards: deep analysis + decisions ("Accept clause 4, reject prepayment, counter at 1.2x"). Dashboard becomes a timeline of escalating intelligence per matter: news → analysis → decision. All in one place. Over time, Tier 2 and Tier 3 cards are the valuable ones.

### 23. One signal, one evolving card — stage lifecycle
No two tiers write separate cards for the same signal. One card evolves through stages: `detected` (Tier 1) → `enriched` (Tier 2) → `decided` (Tier 3, only if escalated). signal_queue gets a `stage` field. Dashboard reads latest stage and renders accordingly. Content ownership is predetermined — no overlap, no duplication, no conflict. **PARKED: exact content-to-tier mapping requires walking through the live dashboard together tomorrow, classifying each card/section with Director.**

### 21. Specializations span all three tiers
AO PM, Movie AM, Hagenauer etc. are not Render agents — they're specializations that exist across tiers. Tier 1: fast path, PM state, signal detection. Tier 2: deep analysis, enriched cards, vault context. Tier 3: full review with Director in the room. Same specialist prompt template (`schema/specialist-{name}.md`) shared across Tier 2 and Tier 3 — same knowledge structure, same vault paths, escalating depth. Tier 1 PMs stay on Render for quick answers but know when to hand off to signal_queue. Tier 2 specialists are invoked per signal via `claude -p` with the specialist prompt. Tier 3 specialists are Director opening a session and saying "let's look at AO."

### 15. Tier 2 cannot escalate to Tier 3 directly
There is no automated Tier 2 → Tier 3 handoff. If a signal exceeds Tier 2's capacity, it flags `priority='needs_tier3'` in signal_queue and alerts Director via Slack/WhatsApp. Director opens a Tier 3 session manually. Director is the only router between Tier 2 and Tier 3 — by design, because Tier 3 is Director's decision-making time.

---

## Delivery Surfaces

Tier 2 enriched cards appear on ALL surfaces — not just dashboard:

| Surface | What it shows | Delivery |
|---|---|---|
| Dashboard | Enriched card with summary + "View full analysis" link | Direct render from PG |
| Slack (#cockpit) | Enriched alert with key findings | Tier 1 reads signal_queue result, formats Block Kit |
| WhatsApp | Short summary + "ask me for details" | Tier 1 reads result, sends via WAHA |
| Morning briefing | Includes overnight Tier 2 analyses | briefing_trigger reads completed signals |

---

## The Bridge: signal_queue

```sql
CREATE TABLE signal_queue (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    source TEXT,           -- 'email_pipeline', 'whatsapp', 'manual', 'ao_pm'
    signal_type TEXT,      -- 'new_document', 'term_sheet', 'deep_analysis_request'
    matter TEXT,           -- 'aukera', 'hagenauer', 'ao', 'morv'
    summary TEXT,          -- "Balazs sent Aukera term sheet for signing"
    payload JSONB,         -- full context (email body, attachment refs, question)
    priority TEXT DEFAULT 'normal',  -- 'critical', 'high', 'normal', 'low'
    status TEXT DEFAULT 'pending',   -- 'pending', 'processing', 'done', 'failed'
    enriched_summary TEXT, -- Tier 2's 2-3 line enriched card text
    result TEXT,           -- Tier 2's full analysis
    processed_at TIMESTAMPTZ
);
```

**Writers (Tier 1):** email pipeline, WhatsApp handler, AO PM, capability runner
**Readers (Tier 2):** Mac Mini cron jobs (Claude Code + Gemma)
**Consumers (all tiers):** dashboard, Slack notifier, briefing trigger, Tier 3 sessions

---

## Open Questions (to resolve with Director)

1. ~~**Cron frequency**~~ → RESOLVED: PG LISTEN/NOTIFY, not polling (decision #12)
2. ~~**Session management**~~ → RESOLVED: fresh `claude -p` per signal (decision #12)
3. ~~**Cost control**~~ → RESOLVED: Gemini Pro triage, Gemma 4 fallback, Opus for analysis only (decision #13)
4. ~~**Vault structure**~~ → RESOLVED: Karpathy three-layer raw/wiki/schema (decision #14a)
5. ~~**Director trigger**~~ → RESOLVED: WhatsApp primary, dashboard button as cheap add-on (decision #19)
6. ~~**Conflict resolution**~~ → RESOLVED: single-writer, vault → PG one-way sync (decision #17)
7. **Which signals auto-escalate to Tier 2?** — PARKED for tomorrow. Requires deep review of 1-2 months of real WhatsApp/email messages to distinguish genuine signals from noise. Important things may look like noise without context. Interview session with Director needed.
8. ~~**Tier 3 trigger from dashboard**~~ → RESOLVED: Tier 3 is Director opening a Claude Code session. No button needed — Director says "let's look at AO" and the specialist context loads. Same vault, same templates, deeper window.

---

## Next Steps

- [ ] Resolve open questions with Director
- [ ] Write implementation brief for signal_queue table (Phase 1B-alpha, ~3h)
- [ ] Write implementation brief for Mac Mini reasoning engine (Phase 1B-beta, ~8-10h)
- [ ] Define which Tier 1 signals auto-write to signal_queue
- [ ] Design enriched card UI for dashboard

---

*This document is being built live. Each decision locked in during the Director + AI Head session gets added to "Locked-In Decisions" above.*
