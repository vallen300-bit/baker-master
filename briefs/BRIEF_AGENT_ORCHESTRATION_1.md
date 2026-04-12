# BRIEF: AGENT-ORCHESTRATION-1 — Baker Cortex: Multi-Agent Write Coordination

## Context
Baker has 3 agents today (AO PM, MOVIE AM, email pipeline) scaling to 15-20. They all write to shared PostgreSQL tables — deadlines, decisions, actions — with zero coordination. Additionally, the same obligation surfaces from multiple ingestion sources (phone/Fireflies, email, WhatsApp, Plod) creating cross-source duplicates that keyword matching cannot catch. Director identified this as a critical architectural gap.

## Estimated time: ~20-24h (4 phases over 2-3 weeks)
## Complexity: High
## Prerequisites: None — backward-compatible, phased rollout

---

## The Problem

**What's broken:** Multiple agents and ingestion sources INSERT into shared tables independently.

| Problem | Evidence |
|---|---|
| **Duplicates** | Two identical "Slack subscription renewal" deadlines created 0.2s apart |
| **Cross-source duplicates** | Same obligation from phone call + email + WhatsApp = 3 records |
| **No source attribution** | Agent-created deadlines have `source_type="agent"` — can't tell which agent |
| **MCP bypasses dedup** | `baker_add_deadline` (Cowork path) does raw INSERT — zero dedup |
| **Silent tool failures** | `store_decision` in MOVIE AM capability doesn't exist in ToolExecutor |
| **No audit trail** | Only ClickUp writes go to `baker_actions`. Agent writes invisible |
| **No compiled knowledge** | Memory files manually maintained, often stale vs DB state |

**What causes it:** Baker evolved with one agent. PM Factory added parallel agents without coordination. Each new ingestion source (Fireflies, Bluewin, Exchange) got direct DB write access.

**What success looks like:**
1. Every shared write carries agent identity and goes through a single bus
2. Cross-source duplicates caught by semantic similarity (Qdrant) before INSERT
3. All agent writes audited
4. Compiled wiki auto-updated from DB state (Karpathy pattern) — agents start with fresh context, zero retrieval cost
5. Conflicts surfaced to Director, not silently swallowed
6. Architecture scales to 20 agents + Plod + future sources without redesign

---

## Industry Context (April 2026)

| Source | Key Insight |
|---|---|
| **Anthropic Managed Agents** (Apr 8) | Append-only event log as source of truth. Agents don't own state. |
| **Harrison Chase / LangChain** (Apr 11) | "Memory is the most valuable part of an agent system." Own your persistence layer. 477K views. |
| **Sherwood / Sazabi / a16z** (Apr 10) | "Handle race conditions where two agents update the same file." Uses git for shared state. Watching Mesa.dev. |
| **RoboRhythms production pattern** | Vector similarity dedup (Qdrant). Unconditional retrieval before every write. |
| **Karpathy LLM Wiki** (Apr 3) | MD files as compiled knowledge layer. Zero retrieval cost. LLM maintains wiki from raw sources. 95% cheaper than RAG for reads. |
| **Databricks/ZenML** | "State stored as append-only log using insert operations rather than updates." |

---

## Architecture: Two-Layer Design

```
┌───────────────────────────────────────────────────────────┐
│  LAYER 1: Compiled Wiki (Karpathy Pattern)                │
│  Purpose: Agent context — zero-cost reads                 │
│  Format: Markdown files in memory/ folder                 │
│  Contents: Matter summaries, entity pages, active         │
│    deadlines, decision history, relationship maps         │
│  Updated by: Wiki compiler (post-write hook)              │
│  Read by: Every agent at session start via CLAUDE.md      │
│  Access: ~0ms (already in context window)                 │
└────────────────────────┬──────────────────────────────────┘
                         │ auto-compiled from
┌────────────────────────▼──────────────────────────────────┐
│  LAYER 2: PostgreSQL + Qdrant (Source of Truth)           │
│  Purpose: Multi-agent writes, ACID safety, audit trail    │
│  Write path: All writes go through Cortex Event Bus       │
│  Dedup: Qdrant semantic similarity (pre-write gate)       │
│  Contents: Raw deadlines, decisions, emails, contacts     │
│  Access: ~100ms (DB query + optional Qdrant call)         │
└───────────────────────────────────────────────────────────┘
```

### Write Flow (Cortex Event Bus)

```
Agent/Pipeline wants to write (deadline, decision, contact update, etc.)
                    │
                    ▼
        ┌───────────────────────┐
        │  1. RETRIEVE FIRST    │  ← Query Qdrant: "is this already known?"
        │     (unconditional)   │     cosine similarity > 0.85 = match
        └───────────┬───────────┘
                    │
            ┌───────┴───────┐
            │               │
         KNOWN           NEW
            │               │
            ▼               ▼
     Return existing   2. INSERT into cortex_events
     canonical ID         (intent_type, payload, source_agent)
                       3. Embed in Qdrant for future dedup
                       4. Resolver creates canonical record
                       5. Audit to baker_actions
                       6. Trigger wiki compilation for affected pages
```

### The `cortex_events` Table

```sql
CREATE TABLE cortex_events (
  id            BIGSERIAL PRIMARY KEY,
  event_type    TEXT NOT NULL,        -- 'write_intent', 'signal', 'conflict', 'resolution'
  category      TEXT NOT NULL,        -- 'deadline', 'decision', 'contact', 'knowledge'
  source_agent  TEXT NOT NULL,        -- 'ao_pm', 'movie_am', 'email_pipeline', 'fireflies', 'plod'
  source_type   TEXT NOT NULL,        -- 'agent', 'email', 'meeting', 'phone', 'whatsapp', 'cowork'
  source_ref    TEXT,                 -- email_id, transcript_id, message_id for tracing
  payload       JSONB NOT NULL,       -- {description, due_date, priority, ...}
  status        TEXT DEFAULT 'pending', -- pending → accepted | merged | rejected | conflict
  canonical_id  INTEGER,              -- links to actual record (deadlines.id, decisions.id)
  merged_into   INTEGER,              -- if duplicate, points to winning event
  qdrant_id     TEXT,                 -- vector ID for future similarity checks
  resolved_at   TIMESTAMPTZ,
  resolved_by   TEXT,                 -- 'auto' or 'director'
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cortex_events_status ON cortex_events(status) WHERE status = 'pending';
CREATE INDEX idx_cortex_events_category ON cortex_events(category, created_at);
```

### Semantic Dedup (Qdrant Pre-Write Gate)

Baker already has Qdrant Cloud + Voyage AI (voyage-3, 1024d). New collection:

```python
COLLECTION = "cortex_obligations"  # deadlines, commitments, action items

async def check_existing_obligation(description: str, category: str) -> Optional[int]:
    """Check Qdrant before any shared write. Returns canonical_id if match found."""
    embedding = await embed_text(description)  # Voyage AI
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

async def register_obligation(description: str, category: str, canonical_id: int):
    """After creating canonical record, register in Qdrant for future dedup."""
    embedding = await embed_text(description)
    qdrant.upsert(
        collection_name=COLLECTION,
        points=[PointStruct(
            id=str(uuid4()),
            vector=embedding,
            payload={"canonical_id": canonical_id, "category": category, "text": description},
        )]
    )
```

This catches cross-source duplicates:
- "Send Balgerstrasse plan by Friday" (Fireflies transcript)
- "Balgerstrasse financing plan — deliver to AO by Apr 18" (email pipeline)
- Cosine similarity ~0.89 → **merged**

### Wiki Compilation (Karpathy Layer)

After the Cortex resolves a write, it triggers wiki compilation for affected pages:

```python
async def compile_wiki_page(category: str, matter_slug: str = None):
    """Recompile a wiki page from current DB state."""
    if category == "deadline":
        deadlines = await get_active_deadlines(matter_slug=matter_slug, limit=50)
        content = format_deadlines_wiki(deadlines)
        write_wiki_page(f"memory/wiki/deadlines-{matter_slug or 'all'}.md", content)
    elif category == "decision":
        decisions = await get_recent_decisions(matter_slug=matter_slug, limit=30)
        content = format_decisions_wiki(decisions)
        write_wiki_page(f"memory/wiki/decisions-{matter_slug or 'all'}.md", content)
    # ... contacts, matters, etc.

    # Update index
    rebuild_wiki_index()
```

Wiki pages are human-readable markdown:

```markdown
# Active Deadlines — Hagenauer
_Auto-compiled from Baker DB. Last updated: 2026-04-12 14:30 UTC_

## Critical
- **May 26 inspection** — Vienna commission electrical audit. EUR 250-300K needed.
  Source: AO PM + email pipeline (3 sources agree) | Created: Apr 9

## High
- **E+H formal opinion on BAO Section 22** — Due Apr 10 (OVERDUE)
  Source: Cowork session | Created: Apr 2

## Normal
- **Construction settlement — Hagenauer EUR 2M** — Negotiate while administrator cash-poor
  Source: email pipeline | Created: Mar 31
```

Agents read these at session start via `CLAUDE.md` references — zero API calls, instant context.

---

## Core Design Principle: Agents Stay Dumb, Infrastructure Stays Smart

Agents do NOT know about Cortex, MD files, or routing rules. They call tools — `create_deadline`, `store_decision`, `update_pm_state` — and the infrastructure decides what happens. This is enforced at two layers:

### Layer A: Tool Handler Routing (orchestrator/agent.py)

The `ToolExecutor.execute()` method is the single chokepoint for all agent writes. It classifies each tool call:

```python
# In ToolExecutor.execute()

# Shared-state tools → route through Cortex (PostgreSQL + Qdrant)
CORTEX_TOOLS = {
    'create_deadline',      # → publish_event(category='deadline')
    'store_decision',       # → publish_event(category='decision')
    'draft_email',          # → publish_event(category='email_draft')
    'send_email',           # → publish_event(category='email_send')
    'send_whatsapp',        # → publish_event(category='whatsapp')
    'clickup_create',       # → publish_event(category='clickup')
    'upsert_vip_contact',   # → publish_event(category='contact')
}

# Domain-knowledge tools → route to agent's own MD wiki (Karpathy layer)
WIKI_TOOLS = {
    'update_pm_state',      # → write to memory/wiki/{agent_slug}/state.md
    'store_insight',        # → write to memory/wiki/{agent_slug}/insights.md
    'update_knowledge',     # → write to memory/wiki/{agent_slug}/{topic}.md
}

async def execute(self, tool_name: str, tool_args: dict) -> str:
    capability = self.current_capability_name  # e.g. 'ao_pm', 'movie_am'

    if tool_name in CORTEX_TOOLS:
        # SHARED STATE: goes through Cortex event bus
        # Agent doesn't know this — it just called "create_deadline"
        result = await publish_event(
            category=TOOL_TO_CATEGORY[tool_name],
            payload=tool_args,
            source_agent=capability,
            source_type='agent',
        )
        # Audit automatically logged by publish_event()
        return result

    elif tool_name in WIKI_TOOLS:
        # DOMAIN KNOWLEDGE: goes to agent's own MD files
        # No DB, no Qdrant, no Cortex — just a file write
        result = await write_agent_wiki(
            agent_slug=capability,
            tool_name=tool_name,
            content=tool_args,
        )
        return result

    else:
        # Read-only tools, calculation tools, etc. — execute directly
        return await self._execute_tool(tool_name, tool_args)
```

**The agent calls `create_deadline`. It has no idea whether that goes to PostgreSQL, Qdrant, MD files, or the moon. The ToolExecutor routes it.**

### Layer B: Wiki Context Loading (capability_runner.py)

When a capability starts, the runner loads its wiki context automatically:

```python
# In capability_runner.py, run_capability()

async def run_capability(self, capability_name: str, query: str, ...):
    cap = self.registry.get(capability_name)

    # Load agent's domain wiki (Karpathy layer — zero API cost)
    wiki_context = load_agent_wiki(capability_name)
    # Returns contents of memory/wiki/{capability_name}/index.md
    # + any referenced sub-pages

    # Load compiled shared state (auto-generated from DB)
    shared_context = load_compiled_state(capability_name)
    # Returns contents of memory/wiki/deadlines-{matter}.md
    # + memory/wiki/decisions-{matter}.md
    # Relevant matters determined from PM_REGISTRY[capability_name]

    # Build system prompt with both contexts
    system = f"""{cap.system_prompt}

## Your Knowledge (domain-specific)
{wiki_context}

## Current Shared State (deadlines, decisions)
{shared_context}
"""
    # Agent sees this as plain text in its context — doesn't know the source
    return await self.agent.run(system=system, query=query, ...)
```

**The agent sees compiled knowledge in its context window. It doesn't know that part came from MD files and part was compiled from PostgreSQL.**

### Layer C: Pipeline/Ingestion Routing (triggers)

Email, Fireflies, Plod, WhatsApp pipelines also route through Cortex for shared writes:

```python
# In any trigger (email_trigger.py, fireflies_trigger.py, plod_trigger.py)

# BEFORE (direct INSERT — no dedup, no audit):
insert_deadline(description=text, due_date=date, source_type="email")

# AFTER (routed through Cortex):
await publish_event(
    category='deadline',
    payload={'description': text, 'due_date': str(date), 'priority': 'normal'},
    source_agent='email_pipeline',       # or 'fireflies', 'plod_pipeline'
    source_type='email',                 # or 'meeting', 'phone'
    source_ref=f'email:{message_id}',    # traceability
)
```

### What Each Agent's Wiki Folder Looks Like

```
memory/wiki/
  index.md                     ← Master index, referenced by CLAUDE.md

  ao_pm/                       ← AO PM's domain knowledge (Karpathy — agent owns this)
    index.md                   ← AO PM reads this first at session start
    relationship.md            ← AO personality, preferences, communication style
    capital-call.md            ← Current funding situation, numbers, phasing
    project-status.md          ← What AO knows vs doesn't know
    conversation-history.md    ← Key reactions, commitments from past meetings
    open-questions.md          ← Moscow advisers, Wertheimer, unresolved items

  movie_am/                    ← MOVIE AM's domain knowledge (agent owns this)
    index.md
    hotel-operations.md        ← F&B, staffing, MO obligations
    debrief-status.md          ← Which topics covered, which pending
    key-contacts.md            ← Mario Habicher, Francesco Cefalù, etc.
    intel.md                   ← Accumulated operational intelligence

  deadlines-hagenauer.md       ← Auto-compiled from DB (read-only for agents)
  deadlines-ao.md              ← Auto-compiled from DB
  deadlines-morv.md            ← Auto-compiled from DB
  decisions-recent.md          ← Auto-compiled from DB
  contacts-vip.md              ← Auto-compiled from DB
```

**Rule: Files inside `{agent_slug}/` are owned by that agent. Files outside are compiled from DB and read-only.**

### Adding a New Agent (Future-Proofing)

To add agent #15 (e.g., `legal_pm`):

1. Define capability in `capability_sets` table (existing pattern)
2. Create `memory/wiki/legal_pm/index.md` with initial domain knowledge
3. Done. The routing infrastructure handles everything else:
   - Tool calls auto-route through Cortex or wiki based on `CORTEX_TOOLS` / `WIKI_TOOLS`
   - Wiki context auto-loaded at session start
   - Shared state auto-compiled into readable MD
   - Qdrant dedup catches cross-agent duplicates

No prompt engineering for coordination. No teaching the agent about Cortex.

---

## Implementation Phases

### Phase 1: Cortex Event Bus + Tool Routing + Agent Identity (~8h)

1. Create `cortex_events` table (migration SQL above)
2. Create `models/cortex.py` with `publish_event()` — single entry point for all shared writes
3. Add `created_by_agent` column to `deadlines` and `decisions` tables
4. Implement tool routing in `ToolExecutor.execute()` — classify CORTEX_TOOLS vs WIKI_TOOLS
5. Rewire all CORTEX_TOOLS to route through `publish_event()`
6. Rewire MCP `baker_add_deadline` to use `publish_event()` (fixes raw INSERT bypass)
7. Add audit logging to `baker_actions` for all agent tool calls
8. Fix `store_decision` silent failure in MOVIE AM
9. Create `memory/wiki/ao_pm/` and `memory/wiki/movie_am/` with initial index.md files
10. Add `load_agent_wiki()` to `capability_runner.py` — loads agent's wiki at session start

**Files:** `models/cortex.py` (new), `models/deadlines.py`, `baker_mcp/baker_mcp_server.py`, `orchestrator/agent.py`, `capability_runner.py`, `dashboard.py` (migration), `memory/wiki/ao_pm/index.md` (new), `memory/wiki/movie_am/index.md` (new)

### Phase 2: Qdrant Semantic Dedup (~6h)

1. Create `cortex_obligations` Qdrant collection
2. Implement `check_existing_obligation()` — pre-write gate
3. Implement `register_obligation()` — post-write registration
4. Wire into `publish_event()` flow: check Qdrant → if match, merge → if new, create + register
5. Backfill: embed existing active deadlines into Qdrant collection
6. Rewire email pipeline paths (Path A + Path B) to use `publish_event()`
7. Rewire Fireflies trigger to use `publish_event()`

**Files:** `models/cortex.py`, `triggers/email_trigger.py`, `triggers/fireflies_trigger.py`

### Phase 3: Wiki Compilation Layer (~6h)

1. Create `memory/wiki/` directory structure with `index.md`
2. Implement wiki compilers for: deadlines, decisions, contacts, matters
3. Wire compilation trigger into `publish_event()` post-write hook
4. Add `CLAUDE.md` references to wiki pages
5. Implement periodic full recompilation (daily, or on `render_start`)
6. Dashboard: show "Intent Feed" card with pending/merged/conflict counts

**Files:** `models/wiki_compiler.py` (new), `memory/wiki/*.md` (new), `CLAUDE.md`, `dashboard.py`

### Phase 4: Plod + Future Sources (~4h)

1. Add Plod webhook ingestion (same pattern as Fireflies)
2. Wire Plod → `publish_event()` with `source_type="phone"`, `source_agent="plod_pipeline"`
3. Cross-source dedup automatically handled by Qdrant gate
4. Wiki auto-updates when Plod creates new obligations

**Files:** `triggers/plod_trigger.py` (new), `dashboard.py`

---

## Files Modified

### New files:
- `models/cortex.py` — Event bus: `publish_event()`, resolver, `check_existing_obligation()`
- `models/wiki_compiler.py` — Karpathy-pattern wiki compilation from DB state
- `memory/wiki/index.md` — Auto-compiled wiki index
- `memory/wiki/deadlines-*.md` — Compiled deadline pages by matter
- `memory/wiki/decisions-*.md` — Compiled decision pages
- `triggers/plod_trigger.py` — Plod ingestion (Phase 4)

### Modified files:
- `models/deadlines.py` — Add `created_by_agent`, wire through `publish_event()`
- `baker_mcp/baker_mcp_server.py` — Replace raw INSERT with `publish_event()`
- `orchestrator/agent.py` — All write tools route through `publish_event()`, add audit, fix `store_decision`
- `triggers/email_trigger.py` — Both paths route through `publish_event()`
- `triggers/fireflies_trigger.py` — Route through `publish_event()`
- `dashboard.py` — Migration SQL, agent badges, Intent Feed card
- `CLAUDE.md` — Reference wiki pages

### Modified (routing layer):
- `capability_runner.py` — Add wiki context loading at session start (`load_agent_wiki()` + `load_compiled_state()`)
- `orchestrator/agent.py` — `ToolExecutor.execute()` classifies tools into CORTEX_TOOLS vs WIKI_TOOLS and routes accordingly

### Do NOT Touch:
- `pipeline.py` — Pipeline flow unchanged
- `capability_registry.py` — Tool filtering unchanged
- Agent system prompts — No coordination logic in prompts. Agents stay dumb about infrastructure.

---

## Quality Checkpoints

**Routing (agents stay dumb):**
1. AO PM calls `create_deadline` → verify it routed through Cortex (check `cortex_events` row)
2. AO PM calls `update_pm_state` → verify it wrote to `memory/wiki/ao_pm/` (NOT to PostgreSQL)
3. AO PM's system prompt → verify it contains wiki context (no explicit Cortex/routing instructions)
4. Add new agent `legal_pm` → verify only needs: capability_sets row + `memory/wiki/legal_pm/index.md`

**Cortex event bus:**
5. Create deadline via Cowork MCP → verify `cortex_events` row + `created_by_agent = 'cowork'`
6. Create deadline via AO PM agent → verify `created_by_agent = 'ao_pm'`
7. Create near-duplicate deadline (different words, same meaning) → verify Qdrant catches it, status = 'merged'
8. Create deadline via email pipeline → verify routes through `publish_event()`
9. Check `baker_actions` after agent creates deadline → verify audit row exists

**Wiki compilation:**
10. After deadline creation → verify wiki page updated automatically
11. MOVIE AM calls `store_decision` → verify it works (was silently failing)
12. Dashboard Intent Feed → verify shows pending/merged/conflict counts
13. Reload page → verify wiki files contain fresh compiled state
14. AO PM session start → verify `memory/wiki/ao_pm/index.md` + compiled deadlines in context

## Verification SQL

```sql
-- Cortex event flow
SELECT id, event_type, category, source_agent, status, canonical_id, created_at
FROM cortex_events ORDER BY created_at DESC LIMIT 10;

-- Agent attribution
SELECT id, description, source_type, created_by_agent
FROM deadlines WHERE created_at > NOW() - INTERVAL '1 day'
ORDER BY created_at DESC LIMIT 10;

-- Merged duplicates
SELECT e1.id, e1.payload->>'description' as original,
       e2.id as merged_id, e2.payload->>'description' as duplicate,
       e2.source_agent
FROM cortex_events e1
JOIN cortex_events e2 ON e2.merged_into = e1.id
ORDER BY e1.created_at DESC LIMIT 10;

-- Audit trail
SELECT action_type, trigger_source, created_at
FROM baker_actions WHERE action_type LIKE 'agent_tool:%'
ORDER BY created_at DESC LIMIT 10;
```

---

## Architecture Decision

**Baker Cortex** = two-layer architecture combining:
- **Karpathy pattern** (compiled MD wiki for zero-cost agent reads)
- **Anthropic pattern** (append-only event log for multi-agent write safety)
- **Industry consensus** (Qdrant semantic dedup for cross-source obligation matching)

No new infrastructure required — uses existing PostgreSQL (Neon) + Qdrant Cloud + Voyage AI.

**Graduation path if needed:**
- 20+ agents with latency issues → PostgreSQL `LISTEN/NOTIFY` for async resolution
- Cross-service agents → Temporal.io for durable workflow orchestration
- Enterprise scale → Full CQRS with materialized views

**Sources:**
- Anthropic Managed Agents (Apr 8, 2026) — append-only event log architecture
- Harrison Chase "Your Harness, Your Memory" (Apr 11) — own your persistence, memory > model
- Karpathy LLM Wiki (Apr 3) — compiled MD knowledge base, zero retrieval cost
- Sherwood/Sazabi (Apr 10) — shared memory race conditions, git as coordination
- RoboRhythms — unconditional Qdrant retrieval before write (production pattern)
- Databricks/ZenML — insert-only state, no concurrent row mutation
