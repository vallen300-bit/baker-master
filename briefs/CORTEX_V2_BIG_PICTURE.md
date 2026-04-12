# Baker Cortex v2 — Big Picture Architecture

## The Insight

Baker has two kinds of work. They need different infrastructure.

| | Alerting | Reasoning |
|---|---|---|
| **What** | Detect signals, extract facts, send alerts, quick responses | Analyze documents, build strategy, cross-reference, maintain knowledge |
| **Speed** | Fast (seconds) | Deep (minutes) |
| **LLM** | Flash/Pro (cheap, fast) | Opus + Gemma (powerful, rich context) |
| **Availability** | 24/7 non-negotiable | Scheduled + on-demand |
| **Context needed** | Recent signals, PM state, last 2 turns | Full document vault, historical patterns, cross-matter connections |

Trying to do both on Render is a compromise. Render agents are fast but context-poor. They can't hold a 200-page legal analysis while cross-referencing 3 matters.

## Two-Tier Architecture

```
══════════════════════════════════════════════════════════════════
 TIER 1: NERVE CENTER (Render — always on)
══════════════════════════════════════════════════════════════════

  Sources                    Baker Core              Outputs
  ─────────                  ──────────              ───────
  Gmail/Bluewin/Exchange ─┐                     ┌─→ WhatsApp alerts
  WhatsApp (WAHA) ────────┤                     ├─→ Slack notifications
  Calendar (Google+EWS) ──┤  Pollers            ├─→ ClickUp updates
  Fireflies/Plaud ────────┤  Webhooks    ───→   ├─→ Email drafts
  RSS feeds ──────────────┤  Classifiers        ├─→ Dashboard SSE
  Dropbox changes ────────┤  Extractors         ├─→ Briefing queue
  Browser sentinel ───────┘  PM fast-path       └─→ signal_queue (PG)
                                                         │
                             PostgreSQL (Neon)            │
                             Qdrant Cloud                 │
                                  ▲                      │
                                  │                      │
══════════════════════════════════│══════════════════════│═══════
                                  │                      │
                                  │    ┌─────────────────┘
                                  │    ▼
══════════════════════════════════════════════════════════════════
 TIER 2: REASONING ENGINE (Mac Mini — always on, scheduled)
══════════════════════════════════════════════════════════════════

  Obsidian Vault                Claude Code            Gemma 4
  ──────────────                ───────────            ───────
  /wiki/matters/               Scheduled runs:         Free local LLM
    hagenauer.md               • Every 1h: check       for research,
    ao-portfolio.md              signal_queue           drafts,
    morv-collection.md         • Every 4h: wiki lint   brainstorming
    movie-am.md                • Every 24h: deep
  /wiki/people/                  synthesis
    ao-profile.md
    martin-hagenauer.md        On-demand:
  /wiki/documents/             • Director triggers
    ftc-table-v008.md            via Baker command
    hma-analysis.md            • "Deep analyze X"
    participation-agreement.md   → queued to Mac Mini
  /wiki/index.md
  /wiki/log.md                 Reads: Obsidian vault
                                      + PostgreSQL
                               Writes: PostgreSQL
                                      + Obsidian vault
                                      + Dropbox
══════════════════════════════════════════════════════════════════
```

## How They Talk: The Signal Queue

The bridge between tiers is a PostgreSQL table. Simple, reliable, no new infrastructure.

```sql
CREATE TABLE signal_queue (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    source TEXT,           -- 'ao_pm', 'email_pipeline', 'whatsapp', 'manual'
    signal_type TEXT,      -- 'new_document', 'contradiction', 'deep_analysis_request', 'strategy_question'
    matter TEXT,           -- 'hagenauer', 'ao', 'morv', 'movie-am'
    summary TEXT,          -- one-line description
    payload JSONB,         -- full context (email body, document ref, question text)
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'done', 'failed'
    result TEXT,           -- reasoning engine's output (written back)
    processed_at TIMESTAMPTZ
);
```

**Tier 1 writes signals:**
- AO PM detects a new document in email → writes to signal_queue
- Email pipeline finds a legal notice → writes to signal_queue
- Director says "deep analyze Hagenauer insolvency options" → writes to signal_queue
- PM knowledge compounding finds a contradiction → writes to signal_queue

**Tier 2 reads and processes:**
- Cron on Mac Mini runs Claude Code every hour
- Claude Code reads pending signals from signal_queue
- For each signal: reads relevant Obsidian pages + PostgreSQL data
- Produces deep analysis, updates wiki pages, writes conclusions back
- Marks signal as done, result available for Tier 1 to surface

## What Lives Where

### Tier 1 — Render (unchanged, enhanced)
Everything Baker does today, plus:
- **signal_queue writer** — AO PM, email pipeline, WhatsApp handler write signals when they detect something needing deep thought
- **Result surfacer** — morning briefing, dashboard, WhatsApp pull processed results from signal_queue
- **Quick PM responses** — "What's the status of Hagenauer?" answered from PM state (fast path stays fast)

### Tier 2 — Mac Mini (new)
- **Obsidian vault** — the knowledge wiki. Markdown files organized by matter/people/documents
- **Claude Code scheduled runs** — cron triggers with specific prompts:
  - `hourly.md`: "Check signal_queue for pending items. Process each one using vault context."
  - `lint.md`: "Review wiki for contradictions, orphans, stale claims. Update."
  - `synthesis.md`: "Cross-reference recent signals across all matters. Surface connections."
- **Gemma 4** — free preprocessing. Summarize before Opus analyzes. Research before Claude writes.
- **Document ingestion** — PDFs, Excel files → extracted to wiki pages locally (no Render compute cost)
- **On-demand deep work** — Director or Baker triggers: "Deep analyze X" → Mac Mini processes with full context

### PostgreSQL — The Shared Brain
- `wiki_pages` — structured wiki content (agents on Render read this)
- `signal_queue` — handoff between tiers
- All existing tables (pm_project_state, whatsapp_messages, meeting_transcripts, etc.)
- Source of truth. Both tiers read/write.

### Obsidian Vault — The Human-Readable Mirror
- Generated from wiki_pages (sync script on Mac Mini)
- Code Brisen reads/writes directly (Karpathy pattern)
- Director browses via screen share / VNC if curious
- Graph view shows matter connections visually
- NOT the source of truth — PostgreSQL is

## Example Flows

### Flow 1: New Legal Document Arrives
```
1. Gmail poller (Render) detects email with PDF attachment
2. Email pipeline extracts: "Hagenauer insolvency court filing, 12 pages"
3. AO PM (Render) writes signal_queue: type='new_document', matter='hagenauer'
4. T1 alert sent to Director: "New Hagenauer court filing received"
5. --- 30 min later ---
6. Mac Mini cron fires Claude Code
7. Claude Code reads signal, downloads PDF from Dropbox
8. Extracts full text, creates/updates wiki pages:
   - wiki/documents/hagenauer-court-filing-20260412.md
   - Updates wiki/matters/hagenauer.md with new deadlines
   - Updates wiki/people/martin-hagenauer.md
9. Writes analysis back to signal_queue.result
10. Updates wiki_pages in PostgreSQL
11. --- Next morning ---
12. Baker briefing includes: "Hagenauer court filing analyzed. 3 new deadlines found. Key risk: [summary]"
```

### Flow 2: Director Asks a Complex Question
```
1. Director via WhatsApp: "What's our total exposure across all Hagenauer entities?"
2. WAHA webhook (Render) → AO PM fast path
3. AO PM checks: this needs cross-matter analysis → writes signal_queue: type='strategy_question'
4. AO PM responds immediately: "Complex question — routing to deep analysis. I'll have an answer within the hour."
5. --- Mac Mini picks up ---
6. Claude Code reads Obsidian vault:
   - wiki/matters/hagenauer.md (all entities, claims, amounts)
   - wiki/documents/hagenauer-*.md (all related docs)
   - wiki/people/martin-hagenauer.md (personal liability angle)
7. Cross-references with PostgreSQL (recent emails, WhatsApp messages, deadlines)
8. Produces structured analysis with amounts, entities, risk ratings
9. Writes to signal_queue.result + updates wiki
10. Baker surfaces via WhatsApp: "Analysis complete: [summary]. Full report: [dashboard link]"
```

### Flow 3: Weekly Wiki Lint
```
1. Sunday cron on Mac Mini runs Claude Code with lint.md prompt
2. Claude Code scans all wiki pages:
   - Finds: MORV page says "9 units released" but recent email mentions "10th unit discussion"
   - Finds: No wiki page for "Wertheimer" despite 4 mentions across AO and Hagenauer pages
   - Finds: FTC table page last updated 2 weeks ago, 3 new emails since
3. Creates lint report in wiki/log.md
4. Writes to signal_queue: type='lint_findings'
5. Monday briefing: "Wiki lint found 3 issues: [list]. Should I update?"
```

## Implementation Phases (Revised)

### Phase 0: Signal Queue (2-3h) — FIRST
- Create `signal_queue` table
- Add signal_queue writer to AO PM and email pipeline
- Dashboard shows pending/processed signals
- No Mac Mini work yet — just the bridge

### Phase 1A: Wiki Pages Table (4-5h) — SAME AS BEFORE
- `wiki_pages` table in PostgreSQL
- Agent context loading from wiki_pages
- Feature flags (WIKI_ENABLED, TOOL_ROUTER_ENABLED)

### Phase 1B: Mac Mini Reasoning Engine (8-10h) — REPLACES OLD 1B
- Install Obsidian on Mac Mini
- Create vault structure (matters/, people/, documents/, index.md, log.md)
- Write sync script: PostgreSQL wiki_pages → Obsidian .md files
- Write Claude Code prompt templates (hourly.md, lint.md, synthesis.md)
- Set up cron jobs on Mac Mini
- Test: signal_queue → Claude Code processes → result surfaces in Baker

### Phase 2: Document Ingestion (10-12h)
- PDF/Excel/DOCX → wiki pages extraction (runs on Mac Mini)
- Start with FTC Table (Excel, predictable), then HMA, then Hagenauer docs
- Each document → wiki pages + cross-references + index update

### Phase 3: Cortex Event Bus + Dedup (12-14h) — SAME AS BEFORE
- cortex_events table, Qdrant dedup gate
- Tool router with feature flags
- Multi-agent coordination

### Phase 4: Knowledge Compounding (6-8h)
- Wiki lint automation (contradiction detection, orphan finding)
- PM insight → wiki page promotion
- Cross-matter synthesis (weekly deep pass)

## What We Dropped

- ~~Obsidian REST API tunnel~~ — not needed, Code Brisen reads vault directly
- ~~Obsidian reverse sync (file watcher)~~ — manual via sync script
- ~~Obsidian as source of truth~~ — PostgreSQL is truth, Obsidian is mirror
- ~~Complex bidirectional sync~~ — one direction: PG → Obsidian. Code Brisen writes to PG.

## What We Gained

- **Separation of concerns** — alerting stays fast, reasoning gets depth
- **Full document context** — Claude Code on Mac Mini reads entire vault, not 8K token summaries
- **Free compute** — Gemma 4 for research/preprocessing, no API cost
- **Karpathy pattern** — Code Brisen + Obsidian vault = exactly his setup, but automated
- **Scalability** — add more matters to vault without touching Render code
- **Director visibility** — Obsidian graph view available anytime via Mac Mini

## Key Principle

> **Render agents are sensors. Mac Mini is the brain. PostgreSQL is the nervous system.**

Tier 1 never tries to be smart. It detects, extracts, alerts, responds quickly.
Tier 2 never tries to be fast. It thinks deeply, cross-references, builds knowledge.
PostgreSQL connects them. Both tiers read and write. No new infrastructure needed.

## Open Questions for Tomorrow

1. **Cron frequency** — hourly for signal processing? Or event-driven (Mac Mini polls signal_queue every 5 min)?
2. **Claude Code session management** — each cron run = new session? Or persistent session via tmux?
3. **Cost control** — Opus on Mac Mini uses Director's API key. Budget cap? Gemma-first routing?
4. **Vault structure** — flat by matter? Or Karpathy's sources/wiki/schema three-layer?
5. **Director trigger** — how does Director say "deep analyze X"? WhatsApp command? Dashboard button? Both?
6. **Conflict resolution** — if Code Brisen updates a wiki page while AO PM writes to wiki_pages, who wins?
