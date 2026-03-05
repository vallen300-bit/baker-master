# BRIEF: Step 3 — Agentic Onboarding

**Author:** Code 300 (Supervisor/Architect)
**Builder:** Code Brisen
**Date:** 2026-03-05
**Depends on:** STEP1C (baker_tasks) + RETRIEVAL-FIX-1 (matter_registry) — both shipped
**Transition Plan ref:** Step 3 of Baker_Agentic_RAG_Transition_Plan.docx

---

## Goal

Baker interviews the Director (~30 min) via Scan to populate VIP profiles, expand the matter registry, and store strategic preferences. After onboarding, the Decision Engine scores triggers using real Director data instead of hardcoded defaults.

**One sentence:** Turn Baker from a generic Chief of Staff into *Dimitry's* Chief of Staff.

---

## What Ships

1. **`/onboard` Scan command** — 6-stage conversational interview
2. **`director_preferences` table** — key-value store for Director's strategic context
3. **VIP profile enrichment** — 3 new columns on `vip_contacts`
4. **6 API endpoints** — CRUD for preferences + onboarding status
5. **Decision Engine reads real data** — VIP tiers, domains, preferences from DB instead of hardcoded defaults

---

## Architecture

### New Table: `director_preferences`

```sql
CREATE TABLE IF NOT EXISTS director_preferences (
    id          SERIAL PRIMARY KEY,
    category    TEXT NOT NULL,       -- 'strategic_priority' | 'communication' | 'standing_order' | 'domain_context' | 'general'
    pref_key    TEXT NOT NULL,       -- e.g. 'top_priority_1', 'email_style', 'chairman_context'
    pref_value  TEXT NOT NULL,       -- free text value
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

### VIP Table Changes: 3 new columns on `vip_contacts`

```sql
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS role_context TEXT;
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS communication_pref TEXT DEFAULT 'email';
ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS expertise TEXT;
```

- `role_context` — Free text: "CFO at Brisen, handles all financial approvals, reports to Dimitry"
- `communication_pref` — `email` | `whatsapp` | `slack` | `phone` — how Director prefers to communicate with this person
- `expertise` — Free text: "Construction law, Austrian regulatory, Hagenauer permit disputes"

### No New Tables Beyond These Two Changes

Everything else uses existing infrastructure:
- `matter_registry` — already has CRUD + API endpoints
- `vip_contacts` — already has tier + domain columns
- `baker_tasks` — already tracks Director feedback

---

## Onboarding Flow: 6 Stages

The `/onboard` command in Scan starts a stateful conversation. Each stage:
1. Baker presents current data + asks structured questions
2. Director answers in natural language
3. Baker parses, confirms ("I'll set Edita to Tier 1, domain: chairman. Correct?")
4. Director confirms or corrects
5. Baker writes to DB and moves to next stage

### Stage 1: VIP Review (~5 min)

Baker shows the current 11 VIPs in a formatted table:

```
Here are your current VIP contacts:

| # | Name                  | Tier | Domain  | Role |
|---|-----------------------|------|---------|------|
| 1 | Edita Vallen          | 1    | network | COO  |
| 2 | Balazs Csepregi       | 2    | network | —    |
| ...                                               |

For each person, I need:
- **Tier** (1 = WhatsApp alert within 15 min, 2 = Slack within 4h)
- **Domain** (chairman / projects / network / private / travel)
- **Role context** (one line: what they do, why they matter)

You can answer like: "Edita: Tier 1, chairman, COO and board member — handles all governance"
Or just say "looks good" if defaults are fine for someone.
```

Baker processes batch answers. Writes `UPDATE vip_contacts SET tier=X, domain=Y, role_context=Z WHERE name = ...`.

### Stage 2: Missing VIPs (~3 min)

```
Anyone missing from the VIP list? I should track people whose messages
deserve priority treatment.

Current Tier 1 (WhatsApp alert): Edita, Ofenheimer, Buchwalder, Oskolkov, Pohanis, Merz
Current Tier 2 (Slack alert): everyone else

Who else should I add? Give me: Name, email, WhatsApp (if known), tier, domain.
```

Baker parses and INSERTs new VIPs. Handles partial data gracefully (email only, WhatsApp only, etc.).

### Stage 3: Matter Expansion (~5 min)

Baker shows current 5 matters:

```
Active matters I'm tracking:

1. **Cupial** — Handover & defect dispute (People: Hassa, Ofenheimer, Caroly, ...)
2. **Hagenauer** — Construction permit/final account (People: Hagenauer, Ofenheimer, Arndt)
3. **Wertheimer LP** — Chanel family office LP (People: Wertheimer, Christophe)
4. **FX Mayr** — Acquisition/Lilienmatt (People: Oskolkov, Buchwalder, Edita)
5. **ClaimsMax** — Claims management AI (People: Philip)

What other active matters should I track? For each, tell me:
- **Name** (short label)
- **Description** (one sentence)
- **Key people** (names)
- **Keywords** (terms that signal this matter in emails/messages)
```

Baker parses and calls `POST /api/matters` for each new matter.

### Stage 4: Strategic Priorities (~5 min)

```
What are your top 3-5 business priorities right now?
These help me know what to flag as urgent and what context to bring into answers.

Example: "Close Wertheimer LP fundraise by Q2 2026"
```

Baker stores each as `director_preferences(category='strategic_priority', pref_key='priority_1', pref_value='...')`.

### Stage 5: Domain Context (~5 min)

```
I use 5 domains to classify incoming signals:
1. **Chairman** — board governance, compliance, regulatory
2. **Projects** — construction, development, active deals
3. **Network** — investors, LPs, fund placements, relationships
4. **Private** — personal, family, health, property
5. **Travel** — logistics, reservations, itineraries

For each domain, is there anything specific I should know?
Example: "Chairman — I'm chairman of Brisen Holding AG, board meets quarterly,
key governance issue right now is the Hagenauer supervisory board seat"

Just skip any domain where the default context is fine.
```

Baker stores each as `director_preferences(category='domain_context', pref_key='chairman', pref_value='...')`.

### Stage 6: Communication & Summary (~3 min)

```
Quick preferences:
1. When I draft emails for you, what tone? (formal / warm-professional / casual)
2. Working hours for scheduling? (e.g., 08:00-19:00 CET)
3. Should I include a proposal/recommendation in every morning briefing, or only when action is needed?

Then I'll show you a summary of everything we set up.
```

Baker stores answers, then outputs a complete summary table of all onboarding data. Director confirms or requests edits.

---

## Implementation Details

### File: `orchestrator/onboarding.py` (NEW)

**OnboardingSession class:**

```python
@dataclass
class OnboardingSession:
    stage: int = 1                    # 1-6
    vip_updates: list = field(...)    # queued VIP changes
    new_vips: list = field(...)       # queued new VIPs
    new_matters: list = field(...)    # queued new matters
    preferences: dict = field(...)    # queued preference writes
    completed: bool = False

# In-memory dict keyed by user session / API key
_active_sessions: Dict[str, OnboardingSession] = {}
```

**Key functions:**
- `start_onboarding(session_id) -> str` — Returns Stage 1 prompt
- `process_onboarding_response(session_id, user_message) -> str` — Parses Director's response, advances stage, returns next prompt or confirmation
- `get_onboarding_status(session_id) -> dict` — Current stage + collected data
- `_parse_vip_updates(message) -> List[dict]` — NLP parsing of VIP edits (Claude Haiku)
- `_parse_matters(message) -> List[dict]` — NLP parsing of matter descriptions (Claude Haiku)
- `_parse_preferences(message) -> List[dict]` — NLP parsing of preference answers (Claude Haiku)
- `_write_onboarding_data(session) -> dict` — Batch-writes all collected data to DB

**Parsing approach:** Use Claude Haiku to extract structured data from Director's natural-language answers. Cheap (~$0.01/call), reliable. Prompt returns JSON. Example:

```python
PARSE_VIP_PROMPT = """Extract VIP updates from this message. Return JSON array:
[{"name": "Edita Vallen", "tier": 1, "domain": "chairman", "role_context": "COO and board member"}]
Only include fields that were explicitly mentioned. Current VIPs for reference: {vip_list}"""
```

### File: `memory/store_back.py` — additions

```python
# director_preferences CRUD
def upsert_preference(category: str, key: str, value: str) -> None
def get_preferences(category: str = None) -> List[dict]
def delete_preference(category: str, key: str) -> None

# vip_contacts update (extend existing)
def update_vip_profile(name: str, updates: dict) -> None  # tier, domain, role_context, communication_pref, expertise
```

### File: `outputs/dashboard.py` — changes

1. New intent `onboarding` in `classify_intent()` — triggers on `/onboard` or "start onboarding" or "let's set up"
2. `_handle_onboarding()` function — routes to `onboarding.py`, streams responses via SSE
3. Onboarding state persists in-memory per session (simple dict, not DB — onboarding is a one-time event)

### File: `orchestrator/scan_prompt.py` — changes

1. `build_mode_aware_prompt()` now checks `director_preferences` for domain_context overrides
2. If `director_preferences` has a `domain_context` entry for the current domain, use it instead of the generic DOMAIN_EXPERTISE dict
3. Inject strategic priorities into the system prompt when available:

```python
# After domain context, before mode extension:
priorities = get_preferences(category='strategic_priority')
if priorities:
    prompt += "\n\n## CURRENT STRATEGIC PRIORITIES\n"
    for p in priorities:
        prompt += f"- {p['pref_value']}\n"
```

### File: `orchestrator/decision_engine.py` — changes

No structural changes needed. The decision engine already:
- Reads `tier` and `domain` from `vip_contacts` (via VIP cache with 5-min TTL)
- Uses keyword patterns for domain classification

After onboarding populates real tier/domain values, the engine automatically uses them on next cache refresh.

**One small addition:** If `director_preferences` has domain_context entries, use them as additional keyword sources for the domain classifier (optional, low priority).

### API Endpoints (in dashboard.py)

```
GET  /api/preferences                    — all preferences (optional ?category= filter)
POST /api/preferences                    — upsert a preference {category, key, value}
DELETE /api/preferences/{category}/{key}  — delete a preference

GET  /api/onboarding/status              — current onboarding stage + data collected
POST /api/onboarding/start               — begin onboarding (returns Stage 1 prompt)
POST /api/onboarding/respond             — send Director's response, get next stage
```

---

## Acceptance Criteria

1. **`/onboard` in Scan** starts the 6-stage interview. Each stage shows current data and asks structured questions.
2. **Director's natural-language answers** are parsed by Haiku into structured updates. Baker confirms before writing.
3. **VIP profiles** updated with real tier, domain, role_context, communication_pref, expertise.
4. **New VIPs** can be added during onboarding (INSERT into vip_contacts).
5. **New matters** can be added during onboarding (POST /api/matters).
6. **Strategic priorities** stored in `director_preferences` and injected into Scan prompts.
7. **Domain context** overrides generic prompts in `scan_prompt.py` when Director provides specific context.
8. **All writes are confirmed** — Baker shows "I'll set X to Y" and waits for Director's OK before writing.
9. **Onboarding can be resumed** — if Director leaves mid-interview, `/onboard` picks up where they left off.
10. **`director_preferences` table** created with proper UNIQUE constraint and CRUD functions.
11. **3 new columns** added to `vip_contacts` (role_context, communication_pref, expertise) via ALTER TABLE IF NOT EXISTS.
12. **Summary at end** — Stage 6 shows a complete formatted summary of all onboarding data.

---

## Out of Scope (Deferred)

- **Learning loop** (feedback → tuning Decision Engine weights) — Step 4+
- **Delegation routing** (which expert handles which query type) — needs more operational data first
- **Team role mapping table** — VIP role_context covers this for now
- **Refactoring hardcoded Director identity** to config — infrastructure cleanup, separate PR
- **WhatsApp onboarding channel** — Scan only for MVP. Can add WA later.
- **Cost monitoring** — Step 4 (separate brief)
- **Frontend onboarding UI** — text-based in Scan is sufficient

---

## Files to Create/Modify

| File | Action | What |
|------|--------|------|
| `orchestrator/onboarding.py` | **CREATE** | OnboardingSession, 6 stages, Haiku parsing |
| `memory/store_back.py` | MODIFY | Add director_preferences table + CRUD, update_vip_profile(), 3 new VIP columns |
| `outputs/dashboard.py` | MODIFY | New `onboarding` intent, `_handle_onboarding()`, 6 API endpoints |
| `orchestrator/scan_prompt.py` | MODIFY | Read preferences for domain context + strategic priorities |
| `models/deadlines.py` | MODIFY | 3 new columns in vip_contacts CREATE TABLE (for fresh installs) |

---

## Implementation Order

1. **DB layer first** — `store_back.py`: director_preferences table + CRUD, vip update function, ALTER TABLE for 3 new columns
2. **Onboarding engine** — `onboarding.py`: session state, 6 stages, Haiku parsing functions
3. **Wire into Scan** — `dashboard.py`: onboarding intent + handler + API endpoints
4. **Prompt enrichment** — `scan_prompt.py`: read preferences, inject into prompts
5. **Seed table schema** — `deadlines.py`: add 3 columns to CREATE TABLE for clean installs
6. **Syntax check all 5 files**, commit locally, do NOT push

---

## Code Brisen Opening Prompt

```
Read CLAUDE.md. Read briefs/BRIEF_STEP3_AGENTIC_ONBOARDING.md.
Implement in the order specified (DB layer → onboarding engine → Scan wiring → prompt enrichment → seed schema).
Syntax-check all 5 files. Commit locally, do NOT push.
```

---

## Architect Review Checklist (Code 300)

Before approving push:
- [ ] director_preferences table has UNIQUE(category, pref_key) constraint
- [ ] ALTER TABLE uses IF NOT EXISTS for all 3 new VIP columns
- [ ] Haiku parsing prompts return valid JSON (test with edge cases)
- [ ] Onboarding state doesn't leak between sessions
- [ ] All DB writes wrapped in try/except (fault-tolerant)
- [ ] No SQL injection — all queries use parameterized statements
- [ ] SSE streaming works during onboarding (no blocking calls without keepalive)
- [ ] `/onboard` resume works (stage persisted correctly)
- [ ] Strategic priorities actually appear in Scan prompts after onboarding
- [ ] VIP tier changes reflect in Decision Engine within 5 min (cache TTL)
