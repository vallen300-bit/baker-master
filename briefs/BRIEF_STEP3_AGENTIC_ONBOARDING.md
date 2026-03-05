# BRIEF: Step 3 — Agentic Onboarding (Slim — Cowork-Driven)

**Author:** Code 300 (Supervisor/Architect)
**Builder:** Code Brisen
**Date:** 2026-03-05
**Depends on:** STEP1C (baker_tasks) + RETRIEVAL-FIX-1 (matter_registry) — both shipped
**Transition Plan ref:** Step 3 of Baker_Agentic_RAG_Transition_Plan.docx

---

## Goal

The Director runs a ~30 min onboarding interview with **Cowork PM** (not Scan). Cowork already has Baker MCP access — it just needs the right write tools and DB tables to store answers. After onboarding, the Decision Engine and Scan prompts use real Director data instead of hardcoded defaults.

**One sentence:** Build the plumbing so Cowork PM can turn Baker into *Dimitry's* Chief of Staff.

---

## What Ships

1. **`director_preferences` table** — key-value store for strategic context
2. **3 new columns on `vip_contacts`** — role_context, communication_pref, expertise
3. **2 new MCP write tools** — `baker_upsert_preference` + `baker_update_vip_profile`
4. **1 MCP read tool update** — `baker_vip_contacts` returns the 3 new columns
5. **1 new MCP read tool** — `baker_get_preferences` to read back stored preferences
6. **Prompt enrichment** — `scan_prompt.py` reads preferences from DB, injects into prompts
7. **3 API endpoints** — CRUD for preferences (dashboard access)

---

## What We DON'T Build

- ~~`orchestrator/onboarding.py`~~ — Cowork IS the interview engine
- ~~Onboarding intent in dashboard.py~~ — no `/onboard` command needed
- ~~Haiku parsing of natural language~~ — Cowork does this natively
- ~~Session state management~~ — Cowork holds conversation context
- ~~Onboarding API endpoints~~ — Cowork writes directly via MCP

---

## Architecture

### New Table: `director_preferences`

```sql
CREATE TABLE IF NOT EXISTS director_preferences (
    id          SERIAL PRIMARY KEY,
    category    TEXT NOT NULL,
    pref_key    TEXT NOT NULL,
    pref_value  TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category, pref_key)
);
```

**Categories:**
- `strategic_priority` — Director's current top 3-5 business priorities (injected into domain prompts)
- `communication` — Style preferences (tone, formality, language rules)
- `standing_order` — The 7 standing orders (stored for reference + prompt injection)
- `domain_context` — Director-specific context per domain (replaces generic prompts in scan_prompt.py)
- `general` — Catch-all (timezone, working hours, delegation threshold, etc.)

### VIP Table Changes: 3 new columns

```sql
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS role_context TEXT;
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS communication_pref TEXT DEFAULT 'email';
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS expertise TEXT;
```

- `role_context` — "CFO at Brisen, handles all financial approvals, reports to Dimitry"
- `communication_pref` — `email` | `whatsapp` | `slack` | `phone`
- `expertise` — "Construction law, Austrian regulatory, Hagenauer permit disputes"

---

## MCP Tools (Baker MCP Server)

### New Tool 1: `baker_upsert_preference`

```python
@mcp.tool()
async def baker_upsert_preference(
    category: str,      # strategic_priority | communication | standing_order | domain_context | general
    pref_key: str,      # e.g. 'priority_1', 'email_tone', 'chairman'
    pref_value: str     # free text value
) -> str:
    """Store or update a Director preference. Categories: strategic_priority, communication,
    standing_order, domain_context, general. Uses UPSERT — same category+key overwrites."""
```

Calls `store_back.upsert_preference()`. Returns confirmation string.

### New Tool 2: `baker_update_vip_profile`

```python
@mcp.tool()
async def baker_update_vip_profile(
    name: str,                          # VIP name (matched case-insensitive)
    tier: int | None = None,            # 1 or 2
    domain: str | None = None,          # chairman | projects | network | private | travel
    role_context: str | None = None,    # free text
    communication_pref: str | None = None,  # email | whatsapp | slack | phone
    expertise: str | None = None        # free text
) -> str:
    """Update a VIP contact's profile. Only provided fields are updated; others preserved.
    Use this during onboarding to set tier, domain, role context, and expertise for each VIP."""
```

Calls `store_back.update_vip_profile()`. Returns confirmation with updated fields.

### Updated Tool: `baker_vip_contacts` (read)

Add the 3 new columns to the SELECT query so Cowork can see current profiles:

```sql
SELECT name, role, email, whatsapp_id, fireflies_speaker_label,
       tier, domain, role_context, communication_pref, expertise
FROM vip_contacts ORDER BY name
```

### New Tool 3: `baker_get_preferences` (read)

```python
@mcp.tool()
async def baker_get_preferences(
    category: str | None = None     # optional filter by category
) -> str:
    """Read Director preferences. Optionally filter by category:
    strategic_priority, communication, standing_order, domain_context, general."""
```

Calls `store_back.get_preferences()`. Returns formatted list.

---

## Store Back Functions (memory/store_back.py)

### New Functions

```python
# --- director_preferences ---

def ensure_director_preferences_table() -> None:
    """CREATE TABLE IF NOT EXISTS + UNIQUE constraint. Called at startup."""

def upsert_preference(category: str, key: str, value: str) -> None:
    """INSERT ... ON CONFLICT (category, pref_key) DO UPDATE SET pref_value = ..., updated_at = NOW()"""

def get_preferences(category: str = None) -> List[dict]:
    """SELECT * FROM director_preferences WHERE category = ... (or all if None)"""

def delete_preference(category: str, key: str) -> None:
    """DELETE FROM director_preferences WHERE category = ... AND pref_key = ..."""

# --- vip profile update ---

def update_vip_profile(name: str, updates: dict) -> dict:
    """UPDATE vip_contacts SET <only provided fields> WHERE LOWER(name) = LOWER(...)
    Whitelist: tier, domain, role_context, communication_pref, expertise.
    Returns the updated row."""
```

### Startup Addition

`ensure_director_preferences_table()` called alongside existing `ensure_*` functions in store_back.py module init.

---

## Prompt Enrichment (scan_prompt.py)

### Change 1: Domain context from DB

In `build_mode_aware_prompt()`, after selecting from `DOMAIN_EXPERTISE` dict:

```python
from memory.store_back import get_preferences

def build_mode_aware_prompt(base_prompt, domain=None, mode=None):
    prompt = base_prompt

    if domain:
        # Check DB first, fall back to hardcoded
        db_context = get_preferences(category='domain_context')
        db_domain = next((p for p in db_context if p['pref_key'] == domain), None)
        if db_domain:
            prompt += f"\n\n## DOMAIN CONTEXT\n{db_domain['pref_value']}"
        elif domain in DOMAIN_EXPERTISE:
            prompt += f"\n\n## DOMAIN CONTEXT\n{DOMAIN_EXPERTISE[domain]}"

    # Inject strategic priorities (always, regardless of domain)
    priorities = get_preferences(category='strategic_priority')
    if priorities:
        prompt += "\n\n## CURRENT STRATEGIC PRIORITIES\n"
        for p in sorted(priorities, key=lambda x: x['pref_key']):
            prompt += f"- {p['pref_value']}\n"

    if mode and mode in MODE_EXTENSIONS:
        prompt += f"\n\n{MODE_EXTENSIONS[mode]}"

    return prompt
```

### Change 2: Communication style

If `get_preferences(category='communication')` has entries, append to the base system prompt:

```python
comm_prefs = get_preferences(category='communication')
if comm_prefs:
    prompt += "\n\n## COMMUNICATION STYLE\n"
    for p in comm_prefs:
        prompt += f"- {p['pref_key']}: {p['pref_value']}\n"
```

---

## API Endpoints (dashboard.py)

Minimal — just enough for debugging and the CEO Cockpit if needed later:

```
GET  /api/preferences                    — all preferences (optional ?category= query param)
POST /api/preferences                    — upsert {category, key, value}
DELETE /api/preferences/{category}/{key} — delete a preference
```

Auth: `X-Baker-Key` header (same as all other /api/* routes).

---

## Onboarding Interview Guide (for Cowork PM)

Cowork doesn't need code — it needs a script. This is the interview guide that Cowork PM follows when the Director says "let's do onboarding":

### Stage 1: VIP Review (~5 min)
- Call `baker_vip_contacts` to show current list
- For each VIP, ask Director to confirm/update: tier (1/2), domain, role context
- Call `baker_update_vip_profile` for each change

### Stage 2: Missing VIPs (~3 min)
- Ask "Anyone missing?"
- Call `baker_upsert_vip` for new contacts (existing tool)
- Then `baker_update_vip_profile` to set tier/domain/role

### Stage 3: Matter Expansion (~5 min)
- Call `baker_raw_query` to show current matters: `SELECT matter_name, description, people, keywords FROM matter_registry WHERE status = 'active'`
- Ask Director about missing matters
- Use Baker API via `baker_raw_query` or store via direct API call

### Stage 4: Strategic Priorities (~5 min)
- Ask "Top 3-5 priorities right now?"
- Call `baker_upsert_preference(category='strategic_priority', pref_key='priority_1', pref_value='...')` for each

### Stage 5: Domain Context (~5 min)
- Ask about each of 5 domains
- Call `baker_upsert_preference(category='domain_context', pref_key='chairman', pref_value='...')` for each

### Stage 6: Communication & Summary (~3 min)
- Ask tone, hours, briefing preferences
- Call `baker_upsert_preference(category='communication', ...)` for each
- Call `baker_vip_contacts` + `baker_get_preferences` to show final summary

---

## Files to Create/Modify

| File | Action | What |
|------|--------|------|
| `memory/store_back.py` | MODIFY | director_preferences table + CRUD, update_vip_profile(), 3 new VIP columns |
| `outputs/dashboard.py` | MODIFY | 3 API endpoints for preferences |
| `orchestrator/scan_prompt.py` | MODIFY | Read preferences, inject into prompts |
| `models/deadlines.py` | MODIFY | 3 new columns in vip_contacts CREATE TABLE (fresh installs) |
| `baker_mcp_server.py`* | MODIFY | 2 new write tools + 1 new read tool + update vip_contacts read |

*MCP server is in Dropbox (`Baker-Project/baker-mcp/baker_mcp_server.py`), not in this repo. Code 300 will update it separately after Code Brisen ships the backend.

---

## Implementation Order

1. **DB layer** — `store_back.py`: director_preferences table + CRUD, update_vip_profile(), ALTER TABLE for 3 new VIP columns
2. **API endpoints** — `dashboard.py`: 3 preference endpoints
3. **Prompt enrichment** — `scan_prompt.py`: read preferences, inject into prompts
4. **Seed schema** — `deadlines.py`: add 3 columns to CREATE TABLE
5. **Syntax check all 4 files**, commit locally, do NOT push

MCP server update (step 6) is done by Code 300 on the Dropbox file after backend ships.

---

## Code Brisen Opening Prompt

```
Read CLAUDE.md. Read briefs/BRIEF_STEP3_AGENTIC_ONBOARDING.md.
Implement in order: DB layer → API endpoints → prompt enrichment → seed schema.
4 files to modify (store_back.py, dashboard.py, scan_prompt.py, deadlines.py). No new files.
Syntax-check all 4 files. Commit locally, do NOT push.
```

---

## Architect Review Checklist (Code 300)

Before approving push:
- [ ] director_preferences table has UNIQUE(category, pref_key) constraint
- [ ] UPSERT uses ON CONFLICT ... DO UPDATE (not INSERT + separate UPDATE)
- [ ] ALTER TABLE uses IF NOT EXISTS for all 3 new VIP columns
- [ ] update_vip_profile() uses explicit column whitelist (no SQL injection)
- [ ] update_vip_profile() only updates provided fields (None = skip)
- [ ] All DB writes wrapped in try/except (fault-tolerant)
- [ ] No SQL injection — all queries use parameterized statements (%s placeholders)
- [ ] get_preferences() returns stable sort order (by category, pref_key)
- [ ] Strategic priorities appear in Scan prompts after preferences are stored
- [ ] Domain context from DB overrides hardcoded DOMAIN_EXPERTISE dict
- [ ] VIP tier changes reflect in Decision Engine within 5 min (cache TTL)
- [ ] API endpoints require X-Baker-Key auth
- [ ] ensure_director_preferences_table() called at startup

---

## After Code Ships — Code 300 Follow-up

1. Update `baker_mcp_server.py` in Dropbox with 2 new write tools + 1 new read tool + updated vip_contacts read
2. Restart MCP server (Cowork + Claude Code will pick up new tools)
3. Write Cowork PM onboarding session instructions (paste the Interview Guide above into Cowork opening prompt)
4. Director runs onboarding with Cowork PM
5. Verify data: `curl -H "X-Baker-Key: bakerbhavanga" "https://baker-master.onrender.com/api/preferences"`
