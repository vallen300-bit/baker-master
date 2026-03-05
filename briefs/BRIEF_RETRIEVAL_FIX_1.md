# BRIEF: RETRIEVAL-FIX-1 — Matter Registry + Expanded Search

**Priority:** Immediate (before Step 3)
**Owner:** Code Brisen
**Reviewer:** Code 300 (architect review before push)
**Date:** 2026-03-05

## Problem

Baker's agentic search tools miss relevant emails and messages because they rely on exact keyword matching. When the Director asks about "Cupial", the agent searches for the literal word "Cupial" in emails. But the lawyer (Hassa) sends emails about "defect rectification Top 4" or "escrow release MOVIE residences" — same matter, different words. Baker misses them.

This was confirmed live: Baker produced an excellent 1669-token Cupial analysis (7 tool calls, 4 iterations) referencing Hassa from meeting transcripts, but then said "I have no emails about Cupials in recent weeks" — while a Hassa email about the exact same issues arrived yesterday and triggered a Slack alert.

The email trigger FOUND the email (Slack alert worked). The agentic search tools MISSED the same email. The gap is in retrieval, not ingestion.

## What A Chief of Staff Does

A human Chief of Staff knows that when the lawyer emails about "apartment Top 4 defect rectification", that's the Cupial dispute. Baker needs the same capability: **subject-matter linking** across people, keywords, and projects.

## Solution: Matter Registry

### 1. New PostgreSQL table: `matter_registry`

```sql
CREATE TABLE IF NOT EXISTS matter_registry (
    id              SERIAL PRIMARY KEY,
    matter_name     TEXT NOT NULL UNIQUE,
    description     TEXT,
    people          TEXT[] NOT NULL DEFAULT '{}',
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    projects        TEXT[] NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matter_registry_name ON matter_registry(matter_name);
CREATE INDEX IF NOT EXISTS idx_matter_registry_status ON matter_registry(status);
```

Example row:
```
matter_name: "Cupial"
description: "Handover & defect dispute on MOVIE Residences Tops 4, 5, 6, 18. Escrow release. HEC commission."
people: ["Hassa", "Ofenheimer", "Caroly", "Cupial-Zgryzek", "Groschl", "Leitner"]
keywords: ["cupial", "kupial", "snagging", "escrow", "defect", "top 4", "top 5", "top 6", "top 18", "handover", "movie residences", "hec commission"]
projects: ["hagenauer"]
status: "active"
```

### 2. Seed data — initial matters

Populate from Baker's existing knowledge. At minimum these matters based on what Baker already knows:

| Matter | People | Keywords |
|--------|--------|----------|
| Cupial | Hassa, Ofenheimer, Caroly, Cupial-Zgryzek, Groschl, Leitner | cupial, kupial, snagging, escrow, defect, top 4, top 5, top 6, top 18, handover, movie residences, hec commission |
| Hagenauer | Hagenauer, Ofenheimer, Arndt | hagenauer, permit, baubewilligung, final account, schlussrechnung |
| Wertheimer LP | Wertheimer, Christophe | wertheimer, sfo, chanel, lp, fundraise, family office |
| FX Mayr | Oskolkov, Buchwalder, Edita | fx mayr, acquisition, lilienmatt, mrci |
| ClaimsMax | Philip | claimsmax, claims, ubm, jurkovic |

The Director will expand this during Step 3 (Agentic Onboarding). This is the starter set.

### 3. Expand search in agent tools

**`memory/retriever.py`** — new method:

```python
def expand_query_via_matters(self, query: str) -> list[str]:
    """Look up the matter registry. If query matches a matter name or keyword,
    return all associated people + keywords as additional search terms."""
```

Logic:
1. Query `matter_registry` where `matter_name ILIKE %query%` OR `query = ANY(keywords)` OR `query = ANY(people)`
2. If match found, return the union of all `people` + `keywords` for matched matters
3. Caller uses these expanded terms for additional searches

**`orchestrator/agent.py`** — update `search_emails` and `search_whatsapp` tool implementations:

When the agent calls `search_emails(query="Cupial")`:
1. Do the existing ILIKE search for "Cupial"
2. Also call `expand_query_via_matters("Cupial")` → gets ["Hassa", "Ofenheimer", "escrow", "top 4", ...]
3. Do additional ILIKE searches for the top people names (max 3 extra queries to keep it fast)
4. Merge and deduplicate results

This way, searching for "Cupial" automatically also finds emails from Hassa, about escrow, mentioning Top 4, etc.

### 4. CRUD methods in `store_back.py`

- `create_matter(matter_name, description, people, keywords, projects)` → INSERT
- `update_matter(matter_id, ...)` → UPDATE with explicit field whitelist
- `get_matters(status='active')` → SELECT all active matters
- `get_matter_by_name(name)` → SELECT single matter by name

### 5. API endpoints in `dashboard.py`

- `GET /api/matters` — list all matters (for future dashboard panel)
- `POST /api/matters` — create a matter (used by onboarding agent in Step 3)
- `PUT /api/matters/{id}` — update a matter

### 6. New agent tool: `get_matter_context`

Add a 9th tool to the agent's TOOL_DEFINITIONS:

```python
{
    "name": "get_matter_context",
    "description": "Look up a business matter/issue by name to get all connected people, "
                   "keywords, and context. Use this when a question mentions a deal, dispute, "
                   "project, or person to understand the full picture before searching.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Matter name or keyword to look up."}
        },
        "required": ["query"]
    }
}
```

This lets Claude explicitly ask "what do I know about this matter?" before deciding what to search for. The tool returns the matter record with all connected people and keywords, enabling Claude to do targeted multi-hop searches.

## Acceptance Criteria

1. `matter_registry` table exists with 5 seed matters
2. Agent searching for "Cupial" also finds emails from Hassa (even if "Cupial" isn't in the email)
3. Agent searching for "Hagenauer" also finds emails from Ofenheimer about permits
4. `get_matter_context` tool works — agent can look up a matter and get all connected entities
5. `GET /api/matters` returns the matter list
6. Existing behavior unchanged — matters are additive, not replacing any existing search logic

## Files to Change

| File | Change |
|------|--------|
| `memory/store_back.py` | `_ensure_matter_registry_table()`, seed data, CRUD methods |
| `memory/retriever.py` | `expand_query_via_matters()`, wire into email/WA search |
| `orchestrator/agent.py` | Add `get_matter_context` tool (tool #9), wire into ToolExecutor |
| `outputs/dashboard.py` | `GET/POST/PUT /api/matters` endpoints |
| `orchestrator/scan_prompt.py` | Add `get_matter_context` to MEMORY ACCESS list |

## What Is NOT In This Brief

- **Auto-populating matters from incoming signals** — that's RETRIEVAL-FIX-2 (background trigger tagging)
- **Director populating matters via conversation** — that's Step 3 (Agentic Onboarding)
- **Full entity resolution / knowledge graph** — that's Phase 3

## Verification

1. Syntax check all modified files
2. Deploy, then ask Baker: "What's the latest on Cupial?" — answer must include recent Hassa email
3. Ask Baker: "Any emails from people involved in the Cupial dispute?" — must find Hassa emails
4. Check `GET /api/matters` returns 5 seed matters
5. Check Render logs for matter registry expansion in tool calls

## Architect Review Checklist (Code 300)

- [ ] No SQL injection in matter registry queries (parameterized queries only)
- [ ] Matter expansion doesn't blow up search time (cap at 3 extra queries per tool call)
- [ ] Seed data is accurate (cross-reference with Baker's existing knowledge)
- [ ] New tool properly registered in TOOL_DEFINITIONS and ToolExecutor
- [ ] MEMORY ACCESS in scan_prompt.py updated to list 9 tools
- [ ] All fallback paths non-fatal (matter registry down → normal search continues)
