# BRIEF: AGENT-ORCHESTRATION-1 — Baker Cortex: Multi-Agent Coordination + Knowledge System

## Context
Baker has 3 agents today (AO PM, MOVIE AM, email pipeline) scaling to 15-20. They all write to shared PostgreSQL tables with zero coordination — duplicates, no attribution, no audit. The same obligation surfaces from multiple sources (phone, email, WhatsApp, Plod) creating cross-source duplicates. Agents also lack access to raw documents (contracts, spreadsheets, legal filings) and depend on manually maintained, often stale context files.

Director's requirements:
- Agents must think deeply with full access to raw documents
- No "later" — document access is Phase 1, not a future brief
- Obsidian as the human interface to the knowledge graph
- Basic Memory as the wiki engine (open source, MCP-native)
- Architecture must be a reusable workflow for onboarding agents 15-20

## Estimated time: ~30-36h (5 phases over 3-4 weeks)
## Complexity: High
## Prerequisites: Install Obsidian + Basic Memory

---

## The Problem

| Problem | Evidence |
|---|---|
| **Duplicates** | Two identical "Slack subscription renewal" deadlines created 0.2s apart |
| **Cross-source duplicates** | Same obligation from phone + email + WhatsApp = 3 records |
| **No source attribution** | Agent-created deadlines say `source_type="agent"` — which agent? |
| **MCP bypasses dedup** | `baker_add_deadline` does raw INSERT — zero dedup |
| **Silent tool failures** | `store_decision` in MOVIE AM doesn't exist in ToolExecutor |
| **No audit trail** | Only ClickUp writes go to `baker_actions` |
| **No document access** | Agents can't read contracts, spreadsheets, legal filings |
| **Stale context** | Memory files manually maintained, drift from reality |

**What success looks like:**
1. Every shared write has agent identity, goes through a single bus, deduped by Qdrant
2. Agents navigate full documents as wiki pages — not summaries, full extraction
3. Director browses the same knowledge in Obsidian — graph view, backlinks, search
4. Adding agent #15 = one config + one wiki folder. Zero custom coordination code
5. Conflicts surfaced to Director, not silently swallowed

---

## Industry Context (April 2026)

| Source | Key Insight |
|---|---|
| **Anthropic Managed Agents** (Apr 8) | Append-only event log. Agents don't own state. |
| **Harrison Chase** (Apr 11) | "Memory is the most valuable part." Own your persistence. 477K views. |
| **Karpathy LLM Wiki** (Apr 3) | Full extraction into MD. Zero retrieval cost. 95% cheaper. |
| **Sherwood / a16z** (Apr 10) | Shared agent memory race conditions. Git as coordination. |
| **Basic Memory** (Apr 12) | Open-source MD wiki + semantic search + MCP. Obsidian-native. |
| **RoboRhythms** | Unconditional Qdrant retrieval before every write. |

---

## Architecture: Three Components

```
═══════════════════════════════════════════════════════════════════
 COMPONENT 1: OBSIDIAN VAULT + BASIC MEMORY (Knowledge Layer)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  Engine: Basic Memory (open source, AGPL-3.0)                 │
 │  Storage: Markdown files in memory/wiki/                      │
 │  Search: Hybrid full-text + semantic (built into Basic Memory) │
 │  Access: MCP tools (search_notes, read_note, write_note)      │
 │  Human UI: Obsidian app — graph view, backlinks, search       │
 │  Sync: Git (repo ↔ Render ↔ local machines)                  │
 │                                                               │
 │  AGENT KNOWLEDGE (each agent owns its folder)                 │
 │    ao_pm/    movie_am/    legal_pm/    deal_analyst/           │
 │                                                               │
 │  DOCUMENTS (full extraction — NOT summaries)                  │
 │    documents/                                                 │
 │      hma-mo-vienna/          ← full contract, section by section │
 │      ftc-table-v008/         ← full spreadsheet, row by row   │
 │      hagenauer-insolvency/   ← full legal filing              │
 │      participation-agreement/ ← full contract                 │
 │                                                               │
 │  COMPILED STATE (auto-generated from DB, read-only)           │
 │    deadlines-active.md    decisions-recent.md                 │
 │    contacts-vip.md        matters-overview.md                 │
 │                                                               │
 │  All cross-linked via [[wiki-links]]                          │
 │                                                               │
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 COMPONENT 2: CORTEX EVENT BUS (Shared Write Coordination)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  Entry point: publish_event() — ALL shared writes go here     │
 │  Pre-write gate: Qdrant semantic check (cosine > 0.85)        │
 │  Storage: cortex_events table (append-only)                   │
 │  Resolution: auto-merge, auto-reject, or flag conflict        │
 │  Audit: every write logged to baker_actions                   │
 │  Post-write: triggers wiki compilation for affected pages     │
 │                                                               │
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 COMPONENT 3: TOOL ROUTER (Invisible to Agents)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  ToolExecutor.execute() classifies every tool call:           │
 │                                                               │
 │  CORTEX_TOOLS → publish_event() → PostgreSQL + Qdrant         │
 │    create_deadline, store_decision, send_email,               │
 │    send_whatsapp, clickup_create, upsert_vip_contact          │
 │                                                               │
 │  WIKI_TOOLS → Basic Memory MCP → agent's wiki folder          │
 │    write_note, update_knowledge, store_insight                │
 │                                                               │
 │  DOC_TOOLS → Basic Memory MCP → documents/ folder             │
 │    read_document, search_documents                            │
 │                                                               │
 │  Agents call tools. They never know the routing.              │
 │                                                               │
═══════════════════════════════════════════════════════════════════
```

### How an Agent Uses the System (AO PM Example)

```
1. SESSION START
   capability_runner loads context via Basic Memory MCP:
   - search_notes("ao_pm") → agent's domain pages
   - read_note("ao_pm/index.md") → master context
   - read_note("deadlines-active.md") → compiled shared state
   All injected into system prompt. Zero PostgreSQL calls.

2. DEEP THINKING
   Director: "What are AO's obligations under the Participation Agreement?"
   AO PM: search_notes("participation agreement obligations")
   → Basic Memory returns [[participation-agreement/section-4.md]]
   → AO PM reads FULL contract clause, not a summary
   → Follows [[links]] to [[capital-call]], [[dilution-risk]]
   → Reasons with complete information

3. KNOWLEDGE UPDATE
   AO PM learns: "AO reacted negatively to EUR 5.77M VAT figure"
   → Calls write_note("ao_pm/conversation-history.md", append=True)
   → Basic Memory writes to agent's wiki folder
   → Obsidian shows update. Next session, AO PM remembers.

4. SHARED WRITE
   AO PM creates: "Sources section due Sunday Apr 13"
   → Calls create_deadline(description=..., due_date=...)
   → ToolExecutor routes through Cortex
   → Qdrant checks for existing obligation → not found → creates
   → Wiki compiler updates deadlines-active.md
   → Director sees it in Obsidian immediately
```

### Full Document Extraction (Not Summaries)

When a document enters Baker's world, it gets FULLY extracted into navigable wiki pages:

**Contract → wiki pages:**
```
documents/hma-mo-vienna/
  index.md                 ← parties, dates, purpose, critical clauses summary
  section-1-definitions.md ← full text with annotations
  section-2-term.md        ← full text with annotations
  section-7-obligations.md ← full text, linked to [[mo-obligations]]
  financial-terms.md       ← every EUR figure, every %, linked
  termination-triggers.md  ← what kills the deal, linked to [[risks]]
```

**Spreadsheet → wiki pages:**
```
documents/ftc-table-v008/
  index.md                 ← structure, totals, key takeaways
  uses-2026.md             ← every row, every number, explanations
  sources-2026.md          ← fund vs LP split, row by row
  gap-analysis.md          ← what's missing, phased timeline
  formulas.md              ← how key cells are calculated
```

**Legal filing → wiki pages:**
```
documents/hagenauer-insolvency/
  index.md                 ← timeline, key facts, status
  claims-register.md       ← EUR 19M breakdown by subcontractor
  settlement-options.md    ← EUR 2M now vs litigation funder risk
```

The agent navigates these like a human: read index → go to relevant section → check specific clause → follow [[links]] to related matters. Full fidelity. No summaries.

**Ingestion trigger:** When a file lands in `Baker-Project/` on Dropbox (or Director flags it), Baker:
1. Reads raw file (PDF via vision/extraction, Excel via pandas, DOCX via python-docx)
2. Extracts FULL content into structured markdown with [[wiki-links]]
3. Writes pages to `memory/wiki/documents/{slug}/` via Basic Memory
4. Basic Memory auto-indexes for semantic search
5. Updates vault index

### Basic Memory as Wiki Engine

Instead of building wiki compilation from scratch, [Basic Memory](https://github.com/basicmachines-co/basic-memory) provides:

| Feature | Built-in | We build |
|---|---|---|
| Markdown file read/write | Yes (MCP tools) | — |
| Semantic search over wiki | Yes (hybrid full-text + vector) | — |
| [[wiki-link]] graph traversal | Yes | — |
| Obsidian compatibility | Yes (native) | — |
| Per-agent project isolation | Yes (projects) | Configure per capability |
| SQLite index for fast search | Yes | — |
| Document extraction into wiki | — | Yes (PDF, Excel, DOCX extractors) |
| Cortex event bus integration | — | Yes (publish_event → wiki update) |
| Tool routing layer | — | Yes (ToolExecutor classification) |
| Compiled state from DB | — | Yes (wiki compiler for deadlines, decisions) |

**Customization per agent:** Each agent gets a Basic Memory "project" with its own config:

```python
AGENT_WIKI_CONFIG = {
    'ao_pm': {
        'project': 'ao_pm',
        'root': 'memory/wiki/ao_pm/',
        'shared_docs': ['documents/ftc-table-v008/', 'documents/hma-mo-vienna/',
                        'documents/participation-agreement/'],
        'compiled_state': ['deadlines-active.md', 'decisions-recent.md', 'contacts-vip.md'],
        'matters': ['hagenauer', 'ao', 'morv', 'balgerstrasse'],
    },
    'movie_am': {
        'project': 'movie_am',
        'root': 'memory/wiki/movie_am/',
        'shared_docs': ['documents/hma-mo-vienna/', 'documents/mo-operations/'],
        'compiled_state': ['deadlines-active.md', 'decisions-recent.md'],
        'matters': ['movie', 'mo-vienna'],
    },
}
```

This config determines: which documents the agent can access, which compiled state it sees, which matters are relevant. The agent doesn't know about the config — it just searches and reads via Basic Memory MCP tools.

### The `cortex_events` Table

```sql
CREATE TABLE cortex_events (
  id            BIGSERIAL PRIMARY KEY,
  event_type    TEXT NOT NULL,        -- 'write_intent', 'signal', 'conflict', 'resolution'
  category      TEXT NOT NULL,        -- 'deadline', 'decision', 'contact', 'knowledge', 'document'
  source_agent  TEXT NOT NULL,        -- 'ao_pm', 'movie_am', 'email_pipeline', etc.
  source_type   TEXT NOT NULL,        -- 'agent', 'email', 'meeting', 'phone', 'whatsapp', 'cowork'
  source_ref    TEXT,                 -- email_id, transcript_id, message_id
  payload       JSONB NOT NULL,
  status        TEXT DEFAULT 'pending', -- pending → accepted | merged | rejected | conflict
  canonical_id  INTEGER,
  merged_into   INTEGER,
  qdrant_id     TEXT,
  resolved_at   TIMESTAMPTZ,
  resolved_by   TEXT,                 -- 'auto' or 'director'
  created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### Semantic Dedup (Qdrant Pre-Write Gate)

```python
COLLECTION = "cortex_obligations"

async def check_existing_obligation(description: str, category: str) -> Optional[int]:
    """Unconditional check before ANY shared write."""
    embedding = await embed_text(description)
    results = qdrant.search(
        collection_name=COLLECTION,
        query_vector=embedding,
        query_filter={"must": [{"key": "category", "match": {"value": category}}]},
        score_threshold=0.85,
        limit=1,
    )
    if results:
        return results[0].payload["canonical_id"]
    return None
```

---

## Core Design Principle: Agents Stay Dumb, Infrastructure Stays Smart

Agents call tools. They never know about Cortex, Basic Memory, Qdrant, or routing. The `ToolExecutor` and `capability_runner` handle everything invisibly.

```python
# ToolExecutor.execute() — the single routing chokepoint

CORTEX_TOOLS = {
    'create_deadline', 'store_decision', 'draft_email',
    'send_email', 'send_whatsapp', 'clickup_create', 'upsert_vip_contact',
}

WIKI_TOOLS = {
    'write_note', 'update_knowledge', 'store_insight',
}

DOC_TOOLS = {
    'read_document', 'search_documents',
}

async def execute(self, tool_name: str, tool_args: dict) -> str:
    capability = self.current_capability_name

    if tool_name in CORTEX_TOOLS:
        return await publish_event(category=..., payload=tool_args,
                                   source_agent=capability, source_type='agent')

    elif tool_name in WIKI_TOOLS:
        return await basic_memory.write_note(
            project=capability, **tool_args)

    elif tool_name in DOC_TOOLS:
        return await basic_memory.search_notes(
            project='documents', query=tool_args['query'])

    else:
        return await self._execute_tool(tool_name, tool_args)
```

---

## Agent Onboarding Workflow (Reusable for Agents 3-20)

Adding a new agent follows a standard checklist — no custom coordination code:

### Step 1: Define Capability (~30 min)
```sql
INSERT INTO capability_sets (name, description, system_prompt, tools, ...)
VALUES ('legal_pm', 'Legal matter project manager', '...', '{...}');
```

### Step 2: Create Wiki Folder (~1h)
```
memory/wiki/legal_pm/
  index.md        ← "You are Legal PM. Your matters: [[hagenauer]], [[cupial]].
                      Your contacts: [[arik]], [[e-and-h]].
                      Read [[documents/participation-agreement/]] for contract terms."
  matters.md      ← Which legal matters this agent tracks
  contacts.md     ← Key people in the legal domain
  playbook.md     ← How this agent approaches its work
```

### Step 3: Configure Wiki Access (~15 min)
```python
# Add to AGENT_WIKI_CONFIG
'legal_pm': {
    'project': 'legal_pm',
    'root': 'memory/wiki/legal_pm/',
    'shared_docs': ['documents/participation-agreement/',
                    'documents/hagenauer-insolvency/'],
    'compiled_state': ['deadlines-active.md', 'decisions-recent.md'],
    'matters': ['hagenauer', 'cupial', 'lilienmatt'],
},
```

### Step 4: Ingest Domain Documents (~2-4h per document)
Run document extractor for each key document:
```bash
python scripts/ingest_document.py \
  --source "Baker-Project/01_working/participation-agreement.pdf" \
  --slug "participation-agreement" \
  --type contract
```

### Step 5: Test (~30 min)
- Agent reads wiki at session start → verify context is loaded
- Agent creates deadline → verify routes through Cortex
- Agent searches documents → verify Basic Memory returns results
- Agent writes knowledge → verify wiki folder updated

**Total onboarding time per agent: ~3-5 hours** (mostly document ingestion).
The framework, routing, Cortex, and Basic Memory are shared infrastructure — built once, used by all.

---

## Implementation Phases

### Phase 1: Basic Memory + Obsidian + Document Extraction (~10h)

1. Install Basic Memory (self-hosted Docker on Render, or local + remote MCP)
2. Set up Obsidian vault at `memory/wiki/`
3. Create initial wiki structure: `ao_pm/`, `movie_am/`, `documents/`
4. Build document extractor (`scripts/ingest_document.py`):
   - PDF → markdown (using Claude vision or PyPDF2 + structure detection)
   - Excel → markdown tables (using pandas)
   - DOCX → markdown (using python-docx)
   - All output as wiki pages with [[links]]
5. Extract AO PM's key documents:
   - HMA (MO Vienna management agreement)
   - Participation Agreement
   - FTC Table v008 (already done as `ao-ftc-table-explanations.md` — migrate)
   - Hagenauer insolvency filing
6. Extract MOVIE AM's key documents:
   - HMA (same, shared with AO PM)
   - Hotel operating reports
   - Debrief materials
7. Populate agent wiki folders with current knowledge (migrate from existing view files + PM state)
8. Wire Basic Memory MCP into `capability_runner.py` for context loading
9. Configure `AGENT_WIKI_CONFIG` for AO PM and MOVIE AM
10. Director installs Obsidian, points vault at `memory/wiki/`, installs git plugin

**Files:** `scripts/ingest_document.py` (new), `memory/wiki/**` (new), `capability_runner.py`, Docker config for Basic Memory

### Phase 2: Cortex Event Bus + Tool Routing (~8h)

1. Create `cortex_events` table
2. Create `models/cortex.py` with `publish_event()`
3. Add `created_by_agent` column to `deadlines` and `decisions`
4. Implement tool routing in `ToolExecutor.execute()` (CORTEX / WIKI / DOC classification)
5. Rewire all shared-write tools through `publish_event()`
6. Rewire MCP `baker_add_deadline` through `publish_event()`
7. Add audit logging to `baker_actions`
8. Fix `store_decision` silent failure
9. Wire Cortex post-write → Basic Memory wiki update (compiled state pages)

**Files:** `models/cortex.py` (new), `models/deadlines.py`, `baker_mcp/baker_mcp_server.py`, `orchestrator/agent.py`, `dashboard.py`

### Phase 3: Qdrant Semantic Dedup (~6h)

1. Create `cortex_obligations` Qdrant collection
2. Implement `check_existing_obligation()` pre-write gate
3. Wire into `publish_event()` flow
4. Backfill existing active deadlines
5. Rewire email pipeline + Fireflies through `publish_event()`

**Files:** `models/cortex.py`, `triggers/email_trigger.py`, `triggers/fireflies_trigger.py`

### Phase 4: Dashboard + Conflict Resolution (~4h)

1. Dashboard "Intent Feed" card — pending/merged/conflict counts
2. Agent attribution badges on deadlines ("via AO PM", "via email")
3. Conflict resolution UI — Director resolves disagreements
4. Wiki compiled state shown in dashboard sidebar

**Files:** `dashboard.py`, `static/app.js`

### Phase 5: Plod + Agent Onboarding Template (~4h)

1. Plod webhook → `publish_event()` integration
2. Create `scripts/onboard_agent.py` — automated agent setup:
   - Creates capability_sets row from template
   - Creates wiki folder structure
   - Configures AGENT_WIKI_CONFIG entry
   - Runs initial document ingestion
   - Generates test queries
3. Document the onboarding workflow in `memory/wiki/baker-ops/onboarding.md`
4. Test: onboard a third agent (e.g., `legal_pm`) using the workflow

**Files:** `scripts/onboard_agent.py` (new), `triggers/plod_trigger.py` (new), `memory/wiki/baker-ops/onboarding.md` (new)

---

## Files Summary

### New:
- `scripts/ingest_document.py` — PDF/Excel/DOCX → wiki pages extractor
- `scripts/onboard_agent.py` — Automated agent onboarding (capability + wiki + config)
- `models/cortex.py` — Event bus, `publish_event()`, resolver
- `memory/wiki/**` — Obsidian vault (agent knowledge + documents + compiled state)
- `triggers/plod_trigger.py` — Plod integration
- `memory/wiki/baker-ops/onboarding.md` — Agent onboarding playbook

### Modified:
- `capability_runner.py` — Wiki context loading via Basic Memory MCP
- `orchestrator/agent.py` — Tool routing (CORTEX / WIKI / DOC), audit logging, fix `store_decision`
- `models/deadlines.py` — `created_by_agent` column
- `baker_mcp/baker_mcp_server.py` — Route through `publish_event()`
- `triggers/email_trigger.py` — Route through `publish_event()`
- `triggers/fireflies_trigger.py` — Route through `publish_event()`
- `dashboard.py` — Migration, Intent Feed card, agent badges
- `CLAUDE.md` — Reference wiki, onboarding workflow

### Do NOT Touch:
- `pipeline.py` — Pipeline flow unchanged
- `capability_registry.py` — Tool filtering unchanged
- Agent system prompts — Agents stay dumb about infrastructure

---

## Quality Checkpoints

**Document access (Phase 1):**
1. AO PM searches "participation agreement dilution clause" → Basic Memory returns full section text
2. AO PM reads [[ftc-table-v008/sources-2026]] → sees every row with numbers
3. Director opens Obsidian → sees graph with documents linked to matters
4. New document ingested → wiki pages created with [[links]] → searchable immediately

**Routing (Phase 2):**
5. AO PM calls `create_deadline` → routed through Cortex → `cortex_events` row created
6. AO PM calls `write_note` → routed to Basic Memory → `ao_pm/` folder updated
7. AO PM's system prompt contains wiki context but no routing instructions

**Dedup (Phase 3):**
8. Near-duplicate deadline (different words, same meaning) → Qdrant catches, status = 'merged'
9. Email + Fireflies + WhatsApp mention same obligation → one canonical deadline

**Onboarding (Phase 5):**
10. Run `onboard_agent.py legal_pm` → capability created, wiki folder ready, config set
11. New agent reads wiki at session start → full context loaded
12. New agent creates deadline → routes through Cortex without any custom code

## Verification SQL

```sql
-- Cortex event flow
SELECT id, event_type, category, source_agent, status, canonical_id
FROM cortex_events ORDER BY created_at DESC LIMIT 10;

-- Agent attribution
SELECT id, description, source_type, created_by_agent
FROM deadlines WHERE created_at > NOW() - INTERVAL '1 day'
ORDER BY created_at DESC LIMIT 10;

-- Merged duplicates
SELECT e1.payload->>'description' as original, e2.payload->>'description' as duplicate,
       e2.source_agent, e2.status
FROM cortex_events e1
JOIN cortex_events e2 ON e2.merged_into = e1.id
ORDER BY e1.created_at DESC LIMIT 10;
```

---

## Architecture Decision

**Baker Cortex** = three components:

1. **Obsidian + Basic Memory** — Knowledge layer. Full document extraction. Agent reads via MCP. Director browses in Obsidian. Karpathy pattern.
2. **PostgreSQL + Qdrant Cortex Bus** — Shared write coordination. Semantic dedup. Append-only events. Anthropic pattern.
3. **Tool Router** — Invisible to agents. Classifies every write. Routes to wiki or Cortex. Agents stay dumb.

**Agent onboarding = 3-5 hours:** capability row + wiki folder + config + document ingestion. Framework is shared. No custom coordination code per agent.

**Sources:**
- Anthropic Managed Agents (Apr 8) — append-only event log
- Harrison Chase (Apr 11) — "Memory > model." Own your persistence.
- Karpathy LLM Wiki (Apr 3) — full extraction into MD, zero retrieval cost
- Basic Memory (Apr 12) — open source wiki engine with MCP + Obsidian + semantic search
- Sherwood/a16z (Apr 10) — shared agent memory via git
- RoboRhythms — unconditional retrieval before write
