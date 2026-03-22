# BRIEF: Baker 3.0 — Item W: Wealth Manager (Edita's Global Asset Tracker)

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** HIGH — opens Baker to a second user
**Effort:** 2 sessions
**Assigned to:** Code 300
**Depends on:** None (independent, uses existing Baker infrastructure)

---

## What We're Building

A new specialist capability + MCP server that gives Edita her own AI-powered wealth management tool, running on Baker's existing infrastructure. She uses Claude Code on her Mac terminal. No web interface, no authentication — her macOS login is the security.

---

## Session 1: Wealth Specialist + Data Model

### 1. Wealth Specialist (Capability #14)

Add to `capability_sets` table:

```sql
INSERT INTO capability_sets (
    slug, name, domain, description, system_prompt,
    tools, autonomy_level, active
) VALUES (
    'wealth',
    'Global Wealth Manager',
    'chairman',
    'Tracks and analyzes the Vallen family complete asset portfolio — real estate, equity, financial investments, bank accounts, insurance, tax obligations, and liabilities across jurisdictions.',
    $$You are the Vallen family Global Wealth Manager. You provide clear, accurate information about the family's complete financial position — both company assets (Brisen Group) and private assets.

Your expertise:
- Real estate portfolio valuation and tracking (MO Vienna, Annaberg, Baden-Baden, FX Mayr, private properties)
- Equity stakes and LP positions (Brisen Group entities, Fund 52%, Aelio/AO positions)
- Bank accounts and cash positions across jurisdictions (Switzerland, Austria, Cyprus)
- Insurance portfolio management (property, liability, D&O, health)
- Tax calendar and obligations across jurisdictions
- Liabilities, loan facilities, and guarantees
- Estate planning context

Rules:
- Always cite which document or source your data comes from
- When data is stale (>30 days old), flag it: "Note: this figure is from [date], may need updating"
- For tax deadlines, always include the jurisdiction and statutory basis
- Round amounts to nearest EUR 1,000 for readability
- When asked about net worth, always show assets, liabilities, and net position
- Never speculate about asset values — use documented figures or say "no current valuation on file"
- Protect privacy — never mention other family members' personal data unless directly relevant
$$,
    '["search_documents", "search_emails", "get_deadlines", "search_memory", "get_contact", "query_baker_data"]',
    'recommend_wait',
    true
);
```

### 2. Owner Column on Documents

```sql
-- Add owner column
ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner VARCHAR(20) DEFAULT 'shared';

-- Tag existing documents
-- Company documents (MO Vienna, Annaberg, etc.) → shared
UPDATE documents SET owner = 'shared' WHERE owner IS NULL OR owner = 'shared';

-- Documents from Baker-Feed that are clearly Dimitry's operational docs
-- (This is a best-effort tagging — manual review may be needed later)
UPDATE documents SET owner = 'dimitry'
WHERE source_path LIKE '%/legal/%' OR source_path LIKE '%/hagenauer/%'
   OR source_path LIKE '%/disputes/%';

CREATE INDEX IF NOT EXISTS idx_docs_owner ON documents(owner);
```

### 3. Edita's Dropbox Folder

Modify `triggers/dropbox_trigger.py` to also poll `/Edita-Feed/`:

```python
# In the polling function, add second folder:
WATCHED_FOLDERS = [
    {"path": "/Baker-Feed", "owner": "dimitry"},
    {"path": "/Edita-Feed", "owner": "edita"},
]

# When ingesting, pass owner to document storage:
def _ingest_file(file_path, dropbox_path, owner="shared"):
    # ... existing ingestion logic ...
    # Add owner when storing:
    store.store_document(..., owner=owner)
```

The owner is determined by which watched folder the file came from:
- `/Baker-Feed/*` → owner = "dimitry" (default, existing behavior)
- `/Edita-Feed/*` → owner = "edita"
- Company documents (manually tagged) → owner = "shared"

### 4. Wealth-Specific Data Tables (Optional)

For structured wealth tracking beyond documents:

```sql
-- Portfolio positions (manual entry or extracted from statements)
CREATE TABLE IF NOT EXISTS wealth_positions (
    id SERIAL PRIMARY KEY,
    owner VARCHAR(20) DEFAULT 'shared',
    category VARCHAR(30),  -- real_estate, equity, financial, cash, liability, insurance
    name TEXT NOT NULL,     -- "MO Vienna" or "UBS Account CHF"
    current_value NUMERIC(15,2),
    currency VARCHAR(3) DEFAULT 'EUR',
    valuation_date DATE,
    valuation_source TEXT,  -- "Q4 2025 appraisal" or "bank statement Feb 2026"
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tax calendar
CREATE TABLE IF NOT EXISTS wealth_tax_calendar (
    id SERIAL PRIMARY KEY,
    owner VARCHAR(20) DEFAULT 'shared',
    jurisdiction VARCHAR(30),   -- AT, CH, CY, DE
    obligation TEXT NOT NULL,   -- "Q1 VAT filing"
    due_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'upcoming',  -- upcoming, filed, overdue
    advisor TEXT,              -- "Constantinos" or "Thomas Leitner"
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

These tables can be populated manually initially, then auto-populated from document extractions as Edita uploads bank statements and tax docs.

---

## Session 2: Wealth MCP Server + Edita's Setup

### 5. Wealth MCP Server

Create `baker-wealth-mcp/baker_wealth_mcp_server.py` (NEW directory):

```python
"""
Baker Wealth MCP Server — Edita's interface to Baker.
Exposes wealth-relevant tools only. Filters by owner = edita | shared.
"""

# Tools exposed:

@tool("wealth_portfolio")
def wealth_portfolio(category: str = None) -> str:
    """Get portfolio overview or filter by category (real_estate, equity, financial, cash, liability, insurance)."""
    # Query wealth_positions table WHERE owner IN ('edita', 'shared')
    # Format as clean table

@tool("wealth_properties")
def wealth_properties() -> str:
    """Get real estate portfolio with current valuations."""
    # Query wealth_positions WHERE category = 'real_estate' AND owner IN ('edita', 'shared')
    # Also pull from Baker's deals table for company properties

@tool("wealth_cashflow")
def wealth_cashflow(months: int = 3) -> str:
    """Get cash flow summary — inflows and outflows."""
    # Query financial extractions from signal_extractions
    # + wealth_positions WHERE category = 'cash'

@tool("wealth_deadlines")
def wealth_deadlines(days: int = 90) -> str:
    """Get upcoming tax, insurance, loan payment deadlines."""
    # Query wealth_tax_calendar + deadlines table
    # WHERE owner IN ('edita', 'shared')

@tool("wealth_documents")
def wealth_documents(search: str = None, doc_type: str = None) -> str:
    """Search Edita's documents — bank statements, tax filings, policies."""
    # Query documents table WHERE owner IN ('edita', 'shared')
    # Optional filter by document_type and search text

@tool("wealth_ask")
def wealth_ask(question: str) -> str:
    """Ask the wealth specialist a question. Routes to Baker's wealth capability."""
    # Call Baker's /api/scan endpoint with capability_task=wealth
    # Filter context to owner IN ('edita', 'shared')
```

### 6. MCP Server Configuration

The server connects to Baker's PostgreSQL (same connection) but filters all queries by owner.

```python
# Connection: same POSTGRES_* env vars as Baker
# No Render deployment needed — runs locally on Edita's Mac
# Env vars loaded from ~/.baker-wealth/.env on Edita's machine
```

### 7. Edita's Claude Code Setup

On Edita's Mac:

**Install Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```

**Create project directory:**
```bash
mkdir -p ~/Baker-Wealth
```

**Create `~/Baker-Wealth/CLAUDE.md`:**
```markdown
# Baker Wealth Manager — Edita's Global Asset Tracker

You are Edita's Global Wealth Manager. You help track and manage
the Vallen family's complete asset portfolio.

## What You Can Do
- Portfolio overview (net worth, asset breakdown)
- Property valuations and status
- Cash flow tracking
- Tax calendar and deadlines
- Insurance policy management
- Document search (bank statements, tax filings)

## How To Use
- Ask any question about the family's finances
- Upload documents by dropping them into /Edita-Feed/ in Dropbox
- Baker processes them automatically within 30 minutes

## Important
- All financial figures are from the most recent documents on file
- Flag any figure older than 30 days as potentially stale
- For tax advice, always recommend consulting the relevant advisor
```

**Create `~/Baker-Wealth/.mcp.json`:**
```json
{
  "mcpServers": {
    "baker-wealth": {
      "command": "python3",
      "args": ["/path/to/baker-wealth-mcp/baker_wealth_mcp_server.py"],
      "env": {
        "POSTGRES_HOST": "...",
        "POSTGRES_DB": "...",
        "POSTGRES_USER": "...",
        "POSTGRES_PASSWORD": "...",
        "BAKER_API_URL": "https://baker-master.onrender.com",
        "BAKER_API_KEY": "bakerbhavanga"
      }
    }
  }
}
```

**Edita opens terminal:**
```bash
cd ~/Baker-Wealth
claude
```

She's in. No login, no password. Her Mac login is the security.

---

## Data Seeding (Initial Setup)

Before Edita starts using it, seed the wealth_positions table with known assets:

```sql
-- Company real estate (shared)
INSERT INTO wealth_positions (owner, category, name, current_value, currency, valuation_date, valuation_source) VALUES
('shared', 'real_estate', 'MO Vienna (Hotel + Residences)', 32000000, 'EUR', '2025-12-01', 'Project valuation'),
('shared', 'real_estate', 'Residenz Annaberg', 8500000, 'EUR', '2026-03-01', 'Sales pipeline'),
('shared', 'real_estate', 'Baden-Baden Portfolio', 5200000, 'EUR', '2025-09-01', 'Appraisal'),
('shared', 'equity', 'Fund 52%', 4100000, 'EUR', '2026-01-01', 'NAV calculation'),
-- Add more as Director provides data
;
```

This gives immediate answers to "what's our net worth?" on day one, before Edita uploads any documents.

---

## Access Control (Cowork Pushback #5 — Accepted)

Three-value model for launch: `dimitry`, `edita`, `shared`.

- Baker MCP: `WHERE owner IN ('dimitry', 'shared')`
- Wealth MCP: `WHERE owner IN ('edita', 'shared')`

**Flagged for 3.1:** Add `access_override` mechanism for ad-hoc sharing of specific documents across boundaries.

---

## Files Created/Modified

| File | Change |
|------|--------|
| `baker-wealth-mcp/baker_wealth_mcp_server.py` | NEW — wealth MCP server |
| `baker-wealth-mcp/requirements.txt` | NEW — MCP server dependencies |
| `triggers/dropbox_trigger.py` | Add /Edita-Feed/ to watched folders |
| `memory/store_back.py` | Add owner parameter to document storage |
| DB migration | wealth_positions, wealth_tax_calendar tables, owner column on documents |
| Capability seed | INSERT wealth specialist into capability_sets |

---

## Testing

1. **Specialist test:** Ask Baker "What's our real estate portfolio?" with wealth capability → verify answer
2. **MCP server test:** Run locally, call wealth_portfolio tool → verify filtered results
3. **Owner filtering:** Upload a doc to /Edita-Feed/ → verify owner='edita'. Upload to /Baker-Feed/ → verify owner='dimitry'
4. **Access control:** Query wealth MCP → verify NO dimitry-only docs returned
5. **Claude Code test:** Open terminal as Edita setup → ask "What's our net worth?" → verify answer from seeded data
6. **Dropbox test:** Drop a PDF into /Edita-Feed/bank-statements/ → verify ingested within 30 min with owner='edita'

---

## What This Brief Does NOT Cover

- Web interface for Edita (deferred — terminal is sufficient for launch)
- Telegram channel for phone access (deferred — noted for future)
- TOTP/2FA authentication (not needed for terminal; add when web interface built)
- Automatic portfolio valuation updates (manual or document-extracted for now)
