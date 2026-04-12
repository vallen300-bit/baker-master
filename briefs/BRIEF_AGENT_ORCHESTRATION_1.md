# BRIEF: AGENT-ORCHESTRATION-1 — Baker Cortex v2: Multi-Agent Coordination + Knowledge System

## Context
Baker has 3 agents today (AO PM, MOVIE AM, email pipeline) scaling to 15-20. They all write to shared PostgreSQL tables with zero coordination. The same obligation surfaces from multiple sources (phone, email, WhatsApp, Plod) creating cross-source duplicates. Agents lack access to raw documents and depend on stale context files. Director requires: full document access in Phase 1, Obsidian as human interface, reusable onboarding for agents 3-20.

## Estimated time: ~36-40h (Phase 0 hotfix + 4 phases over 3-4 weeks)
## Complexity: High
## Prerequisites: Install Obsidian on Director's MacBook

---

## The Problem

| Problem | Evidence |
|---|---|
| **Duplicates** | Two "Slack subscription renewal" deadlines created 0.2s apart |
| **Cross-source duplicates** | Same obligation from phone + email + WhatsApp = 3 records |
| **No attribution** | `source_type="agent"` — which of 15 agents? |
| **MCP bypasses dedup** | `baker_add_deadline` does raw INSERT — zero dedup |
| **Silent tool failure** | `store_decision` in MOVIE AM doesn't exist in ToolExecutor — decisions lost since deployment |
| **No audit trail** | Only ClickUp writes go to `baker_actions` |
| **No document access** | Agents can't read contracts, spreadsheets, legal filings |
| **Stale context** | Memory files manually maintained, drift from DB state |
| **No lint** | Contradictions, orphans, stale pages never detected |

**Assumptions** (verified unless marked):
- PostgreSQL (Neon) can handle 20 concurrent agent sessions — **verified** (Neon scales to 100+ connections)
- Qdrant Cloud has capacity for a new collection — **verified** (current usage well under limits)
- Voyage AI embedding cost is acceptable for dedup gate — **assumed** (~$0.0001 per embed, ~1000/day = $0.10/day)
- Render persistent disk is NOT available for wiki storage — **verified** (ephemeral disk wipes on deploy)
- Director will install Obsidian — **confirmed by Director**

**What success looks like:**
1. Every shared write has agent identity, goes through Cortex, deduped by Qdrant
2. Agents navigate full documents as wiki pages — full extraction, not summaries
3. Director browses the same knowledge in Obsidian — graph view, backlinks, search
4. Adding agent #15 = one DB row + one wiki config. Zero custom coordination code
5. Wiki lint catches contradictions, orphans, staleness automatically
6. Conflicts surfaced to Director, not silently swallowed

---

## Industry Context (April 2026)

| Source | Key Insight | Applied Where |
|---|---|---|
| **Anthropic Managed Agents** (Apr 8) | Append-only event log. Permission system (auto/approval). | cortex_events, tool permissions |
| **Harrison Chase** (Apr 11) | "Memory > model." Own your persistence. | PostgreSQL as source of truth |
| **Karpathy LLM Wiki** (Apr 3) | Full extraction into MD. Three operations: ingest, query, lint. | wiki_pages, document extraction, lint job |
| **Karpathy Claude Skills** (Apr 11) | Assumption surfacing. Step→verify format. | Brief template, CLAUDE.md update |
| **Sherwood / a16z** (Apr 10) | Shared agent memory race conditions. Git is fragile. | PostgreSQL over git for source of truth |
| **RoboRhythms** | Unconditional retrieval before write. Qdrant dedup. | Pre-write gate |
| **Apify / @deveshsingh93** | "Knowing when to fetch vs reason from context" | Context budget — wiki first, fetch as fallback |

---

## Architecture: Three Components

```
═══════════════════════════════════════════════════════════════════
 COMPONENT 1: KNOWLEDGE LAYER (PostgreSQL + Obsidian)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  Source of truth: wiki_pages table (PostgreSQL)               │
 │  Search: Qdrant (same Voyage AI pipeline as Cortex dedup)     │
 │  Human UI: Obsidian vault (generated from wiki_pages)         │
 │  Sync: periodic sync script → generates .md files             │
 │  Director edits in Obsidian → API writes back to wiki_pages   │
 │                                                               │
 │  THREE PAGE TYPES:                                            │
 │                                                               │
 │  agent_knowledge — each agent owns its pages                  │
 │    ao_pm/*    movie_am/*    legal_pm/*                        │
 │                                                               │
 │  document — full extraction, NOT summaries                    │
 │    documents/hma-mo-vienna/*                                  │
 │    documents/ftc-table-v008/*                                 │
 │    documents/hagenauer-insolvency/*                           │
 │                                                               │
 │  compiled_state — auto-generated from DB, read-only           │
 │    deadlines-active    decisions-recent    contacts-vip       │
 │    (debounced: max 1 recompile per 30s, generation counter)   │
 │                                                               │
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 COMPONENT 2: CORTEX EVENT BUS (Shared Write Coordination)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  Entry: publish_event() — ALL shared writes                   │
 │  Pre-write: Qdrant semantic check (cosine > 0.92 = auto-merge)│
 │  Maybe zone: 0.85-0.92 → human review queue                  │
 │  Field check: dates/amounts differ → NEVER auto-merge         │
 │  Shadow mode: first 2 weeks log-only, don't block             │
 │  Storage: cortex_events (append-only — status changes are     │
 │           NEW events, not mutations)                          │
 │  Post-write: audit to baker_actions + trigger wiki recompile  │
 │                                                               │
═══════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════
 COMPONENT 3: TOOL ROUTER + PERMISSIONS (Invisible to Agents)
═══════════════════════════════════════════════════════════════════
 │                                                               │
 │  ToolExecutor.execute() classifies every tool call:           │
 │                                                               │
 │  CORTEX_TOOLS → publish_event() → PostgreSQL + Qdrant         │
 │  WIKI_TOOLS → wiki_pages table → agent's own pages            │
 │  DOC_TOOLS → wiki_pages table → documents/ namespace          │
 │                                                               │
 │  PERMISSION LAYER (per tool):                                 │
 │    auto:     create_deadline, store_decision, write_note      │
 │    approval: send_email, send_whatsapp                        │
 │    gated:    clickup_create (BAKER space only, 10/cycle max)  │
 │                                                               │
 │  Agents call tools. They never know the routing or            │
 │  permission logic. Infrastructure decides.                    │
 │                                                               │
═══════════════════════════════════════════════════════════════════
```

### The `wiki_pages` Table

```sql
CREATE TABLE wiki_pages (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,          -- 'ao_pm/index', 'documents/hma-mo-vienna/section-7'
    title TEXT NOT NULL,
    content TEXT NOT NULL,              -- full markdown with [[wiki-links]]
    agent_owner TEXT,                   -- null = shared, 'ao_pm' = agent-owned
    page_type TEXT NOT NULL,            -- 'agent_knowledge', 'document', 'compiled_state'
    matter_slugs TEXT[],               -- ['hagenauer', 'ao'] for cross-referencing
    backlinks TEXT[],                   -- auto-computed: pages that link to this one
    generation INT DEFAULT 1,          -- increments on each update (cache invalidation)
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by TEXT                     -- 'ao_pm', 'wiki_compiler', 'director'
);

CREATE INDEX idx_wiki_pages_type ON wiki_pages(page_type);
CREATE INDEX idx_wiki_pages_owner ON wiki_pages(agent_owner);
CREATE INDEX idx_wiki_pages_matter ON wiki_pages USING GIN(matter_slugs);
```

### The `cortex_events` Table (Append-Only)

```sql
CREATE TABLE cortex_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,           -- 'write_intent', 'accepted', 'merged', 'rejected',
                                       --  'conflict', 'resolution', 'split'
    category TEXT NOT NULL,             -- 'deadline', 'decision', 'contact', 'email', 'whatsapp',
                                       --  'clickup', 'document'
    source_agent TEXT NOT NULL,         -- 'ao_pm', 'movie_am', 'email_pipeline', etc.
    source_type TEXT NOT NULL,          -- 'agent', 'email', 'meeting', 'phone', 'whatsapp', 'cowork'
    source_ref TEXT,                    -- email_id, transcript_id — traceability
    payload JSONB NOT NULL,
    refers_to BIGINT,                  -- links to prior event (for status transitions)
    canonical_id INTEGER,              -- links to actual record (deadlines.id, etc.)
    qdrant_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Status is NOT a mutable column. Each state change = new event:
-- write_intent(id=1) → accepted(id=2, refers_to=1) → resolution(id=5, refers_to=2)
-- This preserves full audit trail for every state transition.

CREATE INDEX idx_cortex_events_type ON cortex_events(event_type, created_at);
CREATE INDEX idx_cortex_events_category ON cortex_events(category, created_at);
CREATE INDEX idx_cortex_events_refers ON cortex_events(refers_to) WHERE refers_to IS NOT NULL;
```

### Semantic Dedup (Qdrant Pre-Write Gate)

```python
COLLECTION = "cortex_obligations"

async def check_existing_obligation(description: str, category: str,
                                     due_date: str = None, amount: float = None
                                     ) -> tuple[str, Optional[int]]:
    """
    Unconditional check before ANY shared write.
    Returns: ('new', None) | ('auto_merge', canonical_id) | ('review', canonical_id)
    """
    embedding = await embed_text(description)  # Voyage AI — same pipeline as wiki search
    results = qdrant.search(
        collection_name=COLLECTION,
        query_vector=embedding,
        query_filter={"must": [{"key": "category", "match": {"value": category}}]},
        score_threshold=0.85,  # floor — below this, definitely new
        limit=3,
    )
    if not results:
        return ('new', None)

    best = results[0]
    score = best.score
    existing = best.payload

    # NEVER auto-merge if structured fields differ
    if due_date and existing.get('due_date') and due_date != existing['due_date']:
        return ('new', None)  # different dates = different obligation
    if amount and existing.get('amount') and abs(amount - existing['amount']) > 0.01:
        return ('new', None)  # different amounts = different obligation

    if score >= 0.92:
        return ('auto_merge', existing['canonical_id'])
    elif score >= 0.85:
        return ('review', existing['canonical_id'])  # human review queue
    else:
        return ('new', None)
```

### Tool Router + Permission Layer

```python
# Tool classification + permission in ToolExecutor.execute()

TOOL_CONFIG = {
    # tool_name:        (route,    permission, category)
    'create_deadline':   ('cortex', 'auto',     'deadline'),
    'store_decision':    ('cortex', 'auto',     'decision'),
    'draft_email':       ('cortex', 'auto',     'email_draft'),
    'send_email':        ('cortex', 'approval', 'email_send'),
    'send_whatsapp':     ('cortex', 'approval', 'whatsapp'),
    'clickup_create':    ('cortex', 'gated',    'clickup'),
    'upsert_vip_contact':('cortex', 'auto',     'contact'),
    'write_note':        ('wiki',   'auto',     None),
    'update_knowledge':  ('wiki',   'auto',     None),
    'store_insight':     ('wiki',   'auto',     None),
    'read_document':     ('doc',    'auto',     None),
    'search_documents':  ('doc',    'auto',     None),
}

async def execute(self, tool_name: str, tool_args: dict) -> str:
    config = TOOL_CONFIG.get(tool_name)
    if not config:
        return await self._execute_tool(tool_name, tool_args)

    route, permission, category = config
    capability = self.current_capability_name

    # Permission check
    if permission == 'approval':
        # Queue for Director approval, return draft ID
        return await queue_for_approval(tool_name, tool_args, capability)
    elif permission == 'gated':
        if not check_gate(tool_name):  # e.g., 10 writes/cycle for ClickUp
            return json.dumps({"error": "Write limit reached"})

    # Route
    if route == 'cortex':
        return await publish_event(
            category=category, payload=tool_args,
            source_agent=capability, source_type='agent')
    elif route == 'wiki':
        return await write_wiki_page(
            agent_slug=capability, **tool_args)
    elif route == 'doc':
        return await search_wiki_pages(
            page_type='document', query=tool_args.get('query', ''))
```

### Context Loading (Budget: ~8K tokens at session start)

```python
async def load_agent_context(capability_name: str) -> str:
    """Load wiki context for agent. Budget: ~8K tokens.
    Wiki first, fetch as fallback during conversation."""
    config = get_wiki_config(capability_name)  # from capability_sets.wiki_config JSONB

    # 1. Agent's index page (~1-2K tokens)
    index = await get_wiki_page(f"{capability_name}/index")

    # 2. Compiled shared state (~2-3K tokens)
    deadlines = await get_wiki_page("deadlines-active")
    decisions = await get_wiki_page("decisions-recent")

    # 3. Matter summaries relevant to this agent (~2-3K tokens)
    matter_context = []
    for matter in config.get('matters', []):
        page = await get_wiki_page(f"matters/{matter}")
        if page:
            matter_context.append(page.content[:500])  # first 500 chars per matter

    # Documents are NOT pre-loaded. Agent retrieves on-demand via search_documents tool.
    # This keeps session start fast and context budget under control.

    return f"""## Your Knowledge
{index.content if index else '(no index page)'}

## Active Deadlines & Decisions
{deadlines.content if deadlines else '(none)'}
{decisions.content if decisions else ''}

## Matters
{''.join(matter_context)}

## Documents
You have access to full documents via the search_documents tool.
Search when you need specific clauses, numbers, or details.
Do NOT ask the Director for information that may be in your documents — search first."""
```

### Wiki Lint Job (Karpathy Pattern)

```python
async def lint_wiki():
    """Periodic health-check. Run daily or on briefing cycle."""
    findings = []

    # 1. CONTRADICTIONS — compiled state vs source DB
    for page in await get_wiki_pages(page_type='compiled_state'):
        if page.slug == 'deadlines-active':
            db_deadlines = await get_active_deadlines(limit=100)
            wiki_count = page.content.count('- **')
            if abs(len(db_deadlines) - wiki_count) > 2:
                findings.append(f"STALE: {page.slug} shows {wiki_count} items, DB has {len(db_deadlines)}")

    # 2. ORPHANS — VIP contacts with no backlinks from any wiki page
    vips = await get_vip_contacts(limit=100)
    all_content = await get_all_wiki_content()
    for vip in vips:
        if vip.name.lower() not in all_content.lower():
            findings.append(f"ORPHAN: VIP '{vip.name}' not mentioned in any wiki page")

    # 3. STALENESS — pages not updated in >14 days with active matters
    for page in await get_wiki_pages(page_type='agent_knowledge'):
        if page.updated_at < now() - timedelta(days=14):
            findings.append(f"STALE: {page.slug} last updated {page.updated_at.date()}")

    # 4. GENERATION MISMATCH — compiled page outdated vs DB writes
    for page in await get_wiki_pages(page_type='compiled_state'):
        latest_event = await get_latest_cortex_event(category=page_category(page))
        if latest_event and latest_event.created_at > page.updated_at:
            findings.append(f"BEHIND: {page.slug} older than latest Cortex event")

    return findings  # surfaced in morning briefing or dashboard
```

### Obsidian Sync (Bidirectional)

```python
# Direction 1: PostgreSQL → Obsidian (periodic, runs on Director's machine or cron)
async def sync_wiki_to_obsidian(vault_path: str = "memory/wiki/"):
    """Generate .md files from wiki_pages table for Obsidian."""
    pages = await get_all_wiki_pages()
    for page in pages:
        file_path = os.path.join(vault_path, page.slug + '.md')
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        header = f"---\ngeneration: {page.generation}\nupdated: {page.updated_at}\n---\n"
        write_file(file_path, header + page.content)

# Direction 2: Obsidian → PostgreSQL (file watcher on Director's machine)
async def sync_obsidian_edit_to_db(file_path: str, vault_path: str):
    """When Director edits a file in Obsidian, write back to wiki_pages."""
    slug = file_path.replace(vault_path, '').replace('.md', '').strip('/')
    content = read_file(file_path)
    # Strip frontmatter
    if content.startswith('---'):
        content = content.split('---', 2)[2].strip()
    await upsert_wiki_page(slug=slug, content=content, updated_by='director')
```

### Document Extraction

```python
# scripts/ingest_document.py — Full extraction, NOT summaries

async def ingest_document(source_path: str, slug: str, doc_type: str):
    """Extract full document into wiki pages with [[links]]."""

    if doc_type == 'contract':
        # PDF → structured markdown via Claude vision
        pages = await extract_contract(source_path)
        # Returns: [('index', overview), ('section-1', full_text), ...]

    elif doc_type == 'spreadsheet':
        # Excel → markdown tables via pandas
        pages = await extract_spreadsheet(source_path)
        # Returns: [('index', summary), ('sheet-1', full_table), ...]

    elif doc_type == 'legal':
        # PDF → structured legal extraction
        pages = await extract_legal_filing(source_path)

    elif doc_type == 'report':
        # PDF/DOCX → structured report
        pages = await extract_report(source_path)

    # Write all pages to wiki_pages table
    for page_slug, content in pages:
        full_slug = f"documents/{slug}/{page_slug}"
        await upsert_wiki_page(
            slug=full_slug,
            title=page_slug.replace('-', ' ').title(),
            content=content,  # full text with [[wiki-links]]
            page_type='document',
            updated_by='document_pipeline',
        )

    # Embed all pages in Qdrant for semantic search
    for page_slug, content in pages:
        full_slug = f"documents/{slug}/{page_slug}"
        embedding = await embed_text(content[:2000])  # first 2000 chars
        await qdrant_upsert('wiki_search', full_slug, embedding, {
            'slug': full_slug, 'type': 'document', 'doc_slug': slug
        })

    log.info(f"Ingested {len(pages)} pages for documents/{slug}")
```

### Agent Wiki Config (Database, Not Hardcoded)

```sql
-- Add to capability_sets table
ALTER TABLE capability_sets ADD COLUMN IF NOT EXISTS wiki_config JSONB DEFAULT '{}';

-- Example for AO PM:
UPDATE capability_sets SET wiki_config = '{
    "matters": ["hagenauer", "ao", "morv", "balgerstrasse"],
    "shared_docs": [
        "documents/hma-mo-vienna",
        "documents/ftc-table-v008",
        "documents/participation-agreement",
        "documents/hagenauer-insolvency"
    ],
    "compiled_state": ["deadlines-active", "decisions-recent", "contacts-vip"]
}'::jsonb WHERE name = 'ao_pm';
```

New agents get their config at onboarding time — no code change, no redeploy.

---

## Failure Modes

| Scenario | Behavior | Recovery |
|---|---|---|
| **PG write succeeds, Qdrant embed fails** | Mark cortex_event as `qdrant_pending`. Async retry. Deadline exists but unprotected from dedup until Qdrant catches up. | Background job retries pending embeds every 60s. |
| **Wrong auto-merge (0.92 was too aggressive)** | Director sees merged item in Intent Feed. | "Split" action in dashboard → creates new cortex_event `event_type='split'`, re-creates the dropped obligation. |
| **Cortex bus down (PG connection exhausted)** | `publish_event()` raises `CortexUnavailable`. ToolExecutor falls back to direct INSERT with `source_type='agent_fallback'`. | Degraded but not silent. Dashboard shows "Cortex degraded" banner. Fallback writes lack dedup but don't lose data. |
| **Wiki recompilation race (two agents trigger simultaneously)** | Debounce: max 1 recompile per 30s per page. Second trigger queues. Generation counter prevents stale reads. | Agent checks `generation` in page header. If stale (>5 min), falls back to direct DB query. |
| **Director edits Obsidian while wiki recompiles** | Director edit has `updated_by='director'`. Recompile has `updated_by='wiki_compiler'`. Director wins — `director` updates are never overwritten by compiler. | Compiler skips pages where `updated_by='director'` AND `updated_at` is within last hour. |
| **Document extraction produces bad output** | Extraction runs through validation (page count, [[link]] integrity, minimum content length). Bad extractions flagged, not committed. | Manual re-extraction with different parameters. |

---

## Implementation Phases

### Phase 0: Hotfix — Fix `store_decision` (~1h)
**Do this NOW before any Cortex work.**

MOVIE AM has been silently dropping every `store_decision` call since deployment. One-line fix in `ToolExecutor.execute()` — add the tool to the handler, wire to `store_back.log_decision()`.

→ verify: MOVIE AM calls store_decision → check decisions table has new row

**File:** `orchestrator/agent.py`

### Phase 1: Knowledge Layer — wiki_pages + Document Extraction + Obsidian (~16-20h)

1. Create `wiki_pages` table (migration SQL above)
   → verify: `\d wiki_pages` shows all columns
2. Create `scripts/ingest_document.py` with PDF, Excel, DOCX extractors
   → verify: run on test PDF, check wiki_pages has structured pages with [[links]]
3. Extract AO PM's key documents (HMA, Participation Agreement, FTC Table, Hagenauer filing)
   → verify: `SELECT slug FROM wiki_pages WHERE slug LIKE 'documents/%' LIMIT 20` shows all pages
4. Extract MOVIE AM's key documents (HMA shared, hotel reports, debrief materials)
   → verify: same query, MOVIE AM documents present
5. Populate agent wiki folders — migrate existing view files + PM state to wiki_pages
   → verify: `SELECT slug FROM wiki_pages WHERE agent_owner = 'ao_pm'` returns index + domain pages
6. Add `wiki_config` JSONB column to `capability_sets`. Populate for AO PM and MOVIE AM
   → verify: `SELECT name, wiki_config FROM capability_sets WHERE name IN ('ao_pm','movie_am')`
7. Implement `load_agent_context()` in `capability_runner.py` (~8K token budget)
   → verify: AO PM session start includes wiki context in system prompt
8. Implement Obsidian sync script (`sync_wiki_to_obsidian.py`)
   → verify: run script, open Obsidian vault, see pages with [[links]] and graph
9. Implement reverse sync (Obsidian → DB via file watcher or manual trigger)
   → verify: edit page in Obsidian, run sync, check wiki_pages updated_by='director'
10. Director installs Obsidian, points vault at `memory/wiki/`, installs git community plugin
    → verify: Director sees graph view with documents linked to matters

**Files:** `wiki_pages` migration in `dashboard.py`, `scripts/ingest_document.py` (new), `scripts/sync_wiki_to_obsidian.py` (new), `capability_runner.py`, `memory/wiki/` (generated)

### Phase 2: Cortex Event Bus + Qdrant Dedup + Tool Router (~12-14h)

Ship bus and dedup gate together — never ship one without the other.

1. Create `cortex_events` table (migration SQL above)
   → verify: `\d cortex_events` shows all columns
2. Create `models/cortex.py` with `publish_event()` + Qdrant dedup gate
   → verify: call publish_event with test data, check cortex_events + Qdrant collection
3. Add `created_by_agent` column to `deadlines` and `decisions`
   → verify: `\d deadlines` shows column
4. Create `cortex_obligations` Qdrant collection
   → verify: Qdrant dashboard shows collection
5. Implement tool router in `ToolExecutor.execute()` with TOOL_CONFIG + permission layer
   → verify: AO PM calls create_deadline → cortex_events row with source_agent='ao_pm'
   → verify: AO PM calls write_note → wiki_pages row, NOT cortex_events
   → verify: AO PM calls send_email → queued for approval, NOT sent
6. Rewire MCP `baker_add_deadline` through `publish_event()`
   → verify: Cowork creates deadline → cortex_events row with source_agent='cowork'
7. Rewire email pipeline (both paths) through `publish_event()`
   → verify: email with commitment → cortex_events with source_agent='email_pipeline'
8. Rewire Fireflies trigger through `publish_event()`
   → verify: meeting commitment → cortex_events with source_agent='meeting_pipeline'
9. Add audit logging — every Cortex write → baker_actions
   → verify: `SELECT * FROM baker_actions WHERE action_type LIKE 'cortex:%' LIMIT 5`
10. Wire Cortex post-write → compiled state recompilation (debounced, 30s, generation counter)
    → verify: create deadline → deadlines-active wiki page updated within 30s
11. Deploy in SHADOW MODE — log dedup decisions but don't block writes for first 2 weeks
    → verify: check cortex_events for 'would_merge' entries, review threshold accuracy
12. Backfill: embed existing active deadlines into Qdrant collection
    → verify: `SELECT COUNT(*) FROM deadlines WHERE status='active'` matches Qdrant point count

**Files:** `models/cortex.py` (new), `models/deadlines.py`, `baker_mcp/baker_mcp_server.py`, `orchestrator/agent.py`, `triggers/email_trigger.py`, `triggers/fireflies_trigger.py`, `dashboard.py`

### Phase 3: Wiki Lint + Dashboard (~4-6h)

1. Implement wiki lint job (contradictions, orphans, staleness, generation mismatch)
   → verify: run lint, check findings list includes known stale items
2. Wire lint into morning briefing cycle
   → verify: briefing includes "Wiki health: 2 stale, 1 orphan"
3. Dashboard "Intent Feed" card — recent events, merged count, conflict count
   → verify: dashboard shows events with agent badges
4. Dashboard conflict resolution UI — Director resolves via "approve" or "split"
   → verify: resolve a conflict → new cortex_event with event_type='resolution'

**Files:** `models/wiki_lint.py` (new), `dashboard.py`, `static/app.js`

### Phase 4: Onboarding Workflow + Plod (~4h)

1. Create `scripts/onboard_agent.py`:
   - Creates capability_sets row from template
   - Populates wiki_config JSONB
   - Creates initial wiki_pages (index + domain pages)
   - Runs document ingestion for assigned docs
   - Generates test queries
   → verify: `python scripts/onboard_agent.py legal_pm` → capability + wiki + config ready
2. Plod webhook → `publish_event()` integration
   → verify: Plod transcript → cortex_events with source_agent='plod_pipeline'
3. Document onboarding playbook in wiki: `baker-ops/onboarding`
   → verify: wiki page exists with step-by-step checklist
4. Test: onboard `legal_pm` using the workflow. Full cycle.
   → verify: legal_pm reads wiki, creates deadline through Cortex, searches documents

**Files:** `scripts/onboard_agent.py` (new), `triggers/plod_trigger.py` (new)

---

## Files Summary

### New:
- `models/cortex.py` — Event bus, `publish_event()`, Qdrant dedup gate, resolver
- `models/wiki_lint.py` — Lint job (contradictions, orphans, staleness)
- `scripts/ingest_document.py` — PDF/Excel/DOCX → wiki pages extractor
- `scripts/sync_wiki_to_obsidian.py` — PostgreSQL → Obsidian markdown generator
- `scripts/onboard_agent.py` — Automated agent onboarding
- `triggers/plod_trigger.py` — Plod integration
- `memory/wiki/` — Generated Obsidian vault

### Modified:
- `capability_runner.py` — Wiki context loading via `load_agent_context()` (8K budget)
- `orchestrator/agent.py` — Tool router (CORTEX/WIKI/DOC), permission layer, audit, fix `store_decision`
- `models/deadlines.py` — `created_by_agent` column
- `baker_mcp/baker_mcp_server.py` — Route through `publish_event()`
- `triggers/email_trigger.py` — Route through `publish_event()`
- `triggers/fireflies_trigger.py` — Route through `publish_event()`
- `dashboard.py` — Migrations, Intent Feed, agent badges, conflict resolution, lint display
- `CLAUDE.md` — Add assumption surfacing rule, reference wiki

### Do NOT Touch:
- `pipeline.py` — Pipeline flow unchanged
- `capability_registry.py` — Tool filtering unchanged
- Agent system prompts — Agents stay dumb about infrastructure

---

## Quality Checkpoints

**Phase 0:**
1. MOVIE AM store_decision → decisions table has new row ✓

**Phase 1 (Knowledge):**
2. AO PM searches "participation agreement dilution" → full section text returned
3. AO PM reads documents/ftc-table-v008/sources-2026 → every row with numbers
4. Director opens Obsidian → graph shows documents linked to matters via [[links]]
5. New document ingested → wiki pages created → searchable immediately
6. AO PM session start context ≤ 8K tokens, includes index + deadlines + matter summaries
7. Director edits page in Obsidian → wiki_pages table updated via reverse sync

**Phase 2 (Cortex):**
8. AO PM create_deadline → cortex_events row, source_agent='ao_pm'
9. AO PM write_note → wiki_pages row, NOT cortex_events
10. AO PM send_email → queued for approval, not sent
11. Near-duplicate (score 0.92+) → auto-merged
12. Similar (0.85-0.92) → review queue, Director resolves
13. Same text but different dates → NOT merged (field check)
14. Shadow mode: dedup logs decisions without blocking for 2 weeks
15. Email + Fireflies mention same obligation → one canonical deadline

**Phase 3 (Lint):**
16. Lint finds stale compiled page → flagged in briefing
17. Lint finds orphan VIP → flagged
18. Dashboard Intent Feed shows events with agent badges
19. Director resolves conflict → new cortex_event, split obligation created

**Phase 4 (Onboarding):**
20. `onboard_agent.py legal_pm` → capability + wiki + config created
21. legal_pm reads wiki → context loaded, documents searchable
22. legal_pm creates deadline → routes through Cortex, no custom code

---

## Architecture Decision

**Baker Cortex v2** = three components:

1. **Knowledge Layer** (PostgreSQL `wiki_pages` + Qdrant search + Obsidian read view) — Full document extraction. Agent reads via SQL/tools. Director browses in Obsidian. Karpathy pattern with database backing.
2. **Cortex Event Bus** (PostgreSQL `cortex_events` + Qdrant dedup gate) — Append-only events. Semantic dedup with calibrated thresholds. Shadow mode. Anthropic pattern.
3. **Tool Router** (ToolExecutor classification + permission layer) — Invisible to agents. Routes shared writes to Cortex, domain knowledge to wiki, documents to search. Enforces auto/approval/gated permissions. Anthropic permission pattern.

**Agent onboarding = 3-5h:** DB row + wiki_config JSONB + document ingestion. Framework is shared. `onboard_agent.py` automates it.

**Wiki lint** (Karpathy pattern): daily health-check for contradictions, orphans, staleness. Surfaces in briefing.

**Sources:**
- Anthropic Managed Agents (Apr 8) — append-only events, permission system
- Harrison Chase (Apr 11) — own your persistence, memory > model
- Karpathy LLM Wiki (Apr 3) — full extraction, ingest/query/lint operations
- Karpathy Claude Skills (Apr 11) — assumption surfacing, step→verify format
- Sherwood/a16z (Apr 10) — PostgreSQL over git for shared agent state
- RoboRhythms — unconditional Qdrant retrieval before write
- Apify/deveshsingh93 — "knowing when to fetch vs reason from context" → context budget
- Architecture reviewer — 14 corrections incorporated (see git history)
