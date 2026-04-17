# BRIEF: MOVIE-AM-REGISTRATION-2 — Register MOVIE AM Capability + Skeleton

## Context
PM Factory (Step 1) is deployed. Adding MOVIE Asset Manager is now configuration. This brief registers the capability in all 7 touchpoints and creates skeleton view files. No custom code needed — the generic PM factory handles everything.

## Estimated time: ~1h
## Complexity: Low
## Prerequisites: PM-FACTORY-REFACTOR-1 deployed ✅

---

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Uses generic `pm_project_state` table** — NOT a separate `movie_am_project_state` table | PM Factory created slug-based generic table. Architecture doc predates refactor. |
| 2 | **Uses generic tools** `get_pm_state`/`update_pm_state` — NOT `get_movie_am_state` | PM Factory tools accept pm_slug parameter. No PM-specific tool aliases needed. |
| 3 | **View files are skeletons** — `[TO FILL]` placeholders | Step 3 (HMA doc extraction) and Step 4 (Director debrief) fill them. Don't guess. |
| 4 | **Signal detector deferred** — not in this brief | Step 5 of the build plan. MOVIE AM works without signals — just no auto-awareness yet. |
| 5 | **briefing_priority: 20** — below AO PM (10) | AO PM is the active investor relationship. MOVIE AM is asset ops — important but not higher priority. |

---

## Feature 1: PM_REGISTRY Entry

### File: `orchestrator/capability_runner.py`

Add `"movie_am"` entry to `PM_REGISTRY` dict (after the `"ao_pm"` entry, before the closing `}`):

```python
    "movie_am": {
        "registry_version": 1,
        "name": "MOVIE Asset Manager",
        "view_dir": "data/movie_am",
        "view_file_order": [
            "SCHEMA.md", "agreements_framework.md", "operator_dynamics.md",
            "kpi_framework.md", "owner_obligations.md", "agenda.md",
        ],
        "state_label": "MOVIE AM",
        "briefing_priority": 20,
        "contact_keywords": [
            "francesco", "robin", "mario habicher", "rolf huebner",
            "mandarin oriental", "mohg",
        ],
        "entangled_matters": [],  # Hotel is standalone — no cross-matter dependencies yet
        "briefing_section_title": "MOVIE ASSET STATUS",
        "briefing_email_patterns": ["mandarin", "mohg", "mario.habicher"],
        "briefing_whatsapp_patterns": ["henri movie", "victor rodriguez", "rolf"],
        "briefing_deadline_patterns": [
            "mandarin", "movie", "hotel", "insurance", "warranty",
            "operating budget", "ff&e",
        ],
        "briefing_state_key": "open_approvals",
        "soul_md_keywords": ["movie", "mandarin", "riemergasse"],
        "extraction_view_files": [
            "agreements_framework.md", "operator_dynamics.md",
            "kpi_framework.md", "owner_obligations.md", "agenda.md",
        ],
        "extraction_system": (
            "Extract structured state updates AND wiki-worthy insights from "
            "this MOVIE Asset Manager interaction. Return valid JSON only. No markdown fences."
        ),
        "extraction_state_schema": (
            "State updates: {\"kpi_snapshot\": {}, \"open_approvals\": [], "
            "\"pending_reports\": [], \"red_flags\": [], \"open_actions\": [], "
            "\"relationship_state\": {}, \"summary\": \"...\"}"
        ),
    },
```

### Key Constraints
- `extraction_state_schema` matches MOVIE AM's state_json structure (KPIs, approvals, reports) — NOT AO PM's structure (sub_matters, mood).
- `briefing_state_key` is `open_approvals` — MOVIE AM's equivalent of AO PM's `pending_discussion_with_ao`.

---

## Feature 2: Skeleton View Files

### Directory: `data/movie_am/`

Create 6 files. Content comes from `outputs/MOVIE_AM_PM_ARCHITECTURE.md` section 4.

#### `data/movie_am/SCHEMA.md`
```markdown
# MOVIE AM — View Files

These files are Baker's compiled view on Mandarin Oriental, Vienna asset management.
Read ALL files at every MOVIE AM invocation. No exceptions.

| File | Contains | Owner |
|------|----------|-------|
| agreements_framework.md | HMA suite: fees, thresholds, termination, key clauses | Director + E+H |
| operator_dynamics.md | MOHG people, power structure, leverage, meeting cadence | Director |
| kpi_framework.md | RevPAR, ADR, occupancy, GOP, NOI — definitions, targets, benchmarks | Director + MO Finance |
| owner_obligations.md | What RG7 owes MOHG (and vice versa) — compliance checklist | Director + E+H |
| agenda.md | Active matters + parked matters | Director + Baker |

## Rules
- Director edits are gospel.
- If operator reports contradict a view file, flag it — don't override autonomously.
- When Director says "update the view" — edit the file and commit.
- Financial figures require source citation (Lesson #2 from AO PM build).
```

#### `data/movie_am/agreements_framework.md`
```markdown
# MOVIE Agreements Framework

## Agreement Suite (all dated 2020, Baker DB IDs 83200-83206)

| Agreement | Parties | Key Function | Baker DB |
|-----------|---------|-------------|----------|
| MA (Management Agreement) | RG7 ↔ MOHG | Day-to-day hotel management | 83202 |
| CSA (Centralised Services Agreement) | RG7 ↔ MOHG | Global services, marketing, development | 83200 |
| TSA (Technical Services Agreement) | RG7 ↔ MOHG | Technical assistance, planning | 83204 |
| MLA (Master License Agreement) | RG7 ↔ MOHG | Brand licensing | 83203 |
| LA (License Agreement) | RG7 ↔ MOHG | MOHG marks usage | 83201 |
| DOG (Design & Operating Guidelines) | RG7 ↔ MOHG | Brand standards | 83205 |
| FE Letter (FF&E Letter) | RG7 ↔ MOHG | FF&E reserve terms | 83206 |

## Fee Structure
[TO FILL — Step 3 extracts from MA/CSA, Step 4 Director confirms]
- Basic Management Fee: __% of Gross Revenue
- Basic Service Fee: __% of Gross Revenue
- Royalty: __% of Gross Revenue
- Incentive Management Fee: __% of Adjusted Net Operating Income (after Owner's Priority Return)
- Marketing Contribution: __% (MA 7.4)
- Advertising Contribution: __% (MA 7.5)
- Centralised Revenue Management: __% (CSA 7.6)

## Owner's Priority Return
[TO FILL — threshold before MO earns incentive fees]

## Approval Thresholds
- Legal actions >EUR 100K: Owner approval required (MA 3.6.8)
- Structural alterations not in budget: Owner approval required (MA 3.4)
- Restricted Contracts: Mandarin cannot enter without Owner consent (MA 3.7)
- Key personnel (GM): Owner consultation required (MA 3.3.4)

## Term & Extensions
- Initial Period + 2x 10-year extensions at MO's option
- Extension conditions: Performance Test in Fiscal Years 22-24 (first), 32-34 (second)
- Written notice: between 12th and 9th month before expiry
- Cure Amount available if Performance Test fails

## Termination Triggers
[TO FILL — extract from MA Section 11]

## Territorial Restriction
- No competing MO-branded hotel in Vienna (MA 3.8)
- Chain Exception: after 15th anniversary, if chain of 5+ hotels
- Residences branding restriction until 93% sold or 10th anniversary
```

#### `data/movie_am/operator_dynamics.md`
```markdown
# MOHG Operator Dynamics

## Key People (MO Side)

| Person | Role | Relevance | Contact |
|--------|------|-----------|---------|
| Francesco | [Title TBD] | Primary MO contact, owner approvals | [TBD] |
| Robin | [Title TBD] | London HQ, strategic | [TBD] |
| Mario Habicher | Finance / Compliance | Monthly reporting, budget | [TBD] |
| GM (TBD) | General Manager | Day-to-day operations | [TBD] |

## Key People (Owner Side)

| Person | Role | Relevance |
|--------|------|-----------|
| Dimitry Vallen | Director/Owner | Strategic decisions, approvals |
| Rolf Huebner | Head of Operations | Operational oversight |
| Edita Vallen | COO | Governance, owner's representative |
| E+H | Legal counsel | HMA interpretation, disputes |

## Power Dynamics
[TO FILL DURING DEBRIEF]

## Meeting Obligations (from MA 7.3)
- Quarterly: Senior MO executives available for operations/performance review
- Monthly: GM + Director of Finance present financials, answer Owner questions
- Routine Owner-GM communication is NOT "interference" (MA 7.2)

## Communication Protocol
[TO FILL — how does Director prefer to interact with MO?]
```

#### `data/movie_am/kpi_framework.md`
```markdown
# MOVIE KPI Framework

## Core Metrics

| Metric | Definition | Target | Benchmark Source |
|--------|-----------|--------|-----------------|
| Occupancy | Rooms sold / rooms available | __% | STR Vienna luxury set |
| ADR | Average Daily Rate (EUR) | EUR __ | STR Vienna luxury set |
| RevPAR | Revenue Per Available Room | EUR __ | STR Vienna luxury set |
| GOP | Gross Operating Profit | EUR __ / __% margin | MO monthly P&L |
| NOI | Net Operating Income | EUR __ / __% margin | After all fees + reserves |
| Owner's Priority Return | [Definition from MA] | EUR __ | Annual |
| FF&E Reserve | Cumulative reserve balance | EUR __ | CSA 3.6 / 5.5 |

## Reporting Cadence

| Report | Frequency | Source | Due By |
|--------|-----------|--------|--------|
| Monthly P&L | Monthly | MO Finance (Mario Habicher) | [Day of month TBD] |
| STR Benchmark | Monthly | STR (third party) | [TBD] |
| Operating Budget | Annual | MO submits for Owner approval | [Month TBD] |
| FF&E Budget | Annual | MO submits for Owner approval | [Month TBD] |
| Annual Accounts | Annual | MO Finance | [Deadline from CSA 6.3] |

## Alert Thresholds (Baker auto-flags)

| Condition | Severity | Action |
|-----------|----------|--------|
| Occupancy <50% for 2 consecutive months | T2 (Edita) | Review pricing strategy with MO |
| ADR drops >10% vs prior year | T2 (Edita) | Demand explanation from MO |
| GOP margin below threshold | T1 (Director) | Board-level discussion |
| Monthly P&L not received by due date | T3 (Baker) | Auto-reminder to Mario Habicher |
| Budget submission overdue | T2 (Edita) | Escalate to Francesco |
| FF&E reserve below required minimum | T1 (Director) | Contractual compliance issue |

## Seasonal Pattern
[TO FILL — Vienna hotel seasonality: high/low months, event calendar]
```

#### `data/movie_am/owner_obligations.md`
```markdown
# Owner <> Operator Obligations

## What RG7 (Owner) Must Do

| Obligation | Source | Frequency | Baker Monitors |
|-----------|--------|-----------|----------------|
| Make funds available for major renovations | MA 7.1.1 | As needed | YES |
| Pay all taxes before delinquency | MA 7.1.3 | Ongoing | YES |
| Maintain insurance coverage | CSA 8.1-8.6 | Annual renewal | YES |
| Not interfere with MO's management | MA 7.2 | Ongoing | NO |
| Attend/convene quarterly meetings | MA 7.3 | Quarterly | YES |
| Provide entry/access to authorized persons | MA 7.1.2 | Ongoing | NO |
| Cooperate on guarantee enforcement | MA 3.4 | As needed | YES |
| Notify MO of legal actions affecting hotel | MA 7.1.10 | As needed | YES |

## What MOHG (Operator) Must Do

| Obligation | Source | Frequency | Baker Monitors |
|-----------|--------|-----------|----------------|
| Submit monthly financial statements | CSA 6.2 | Monthly | YES |
| Submit annual accounts | CSA 6.3 | Annual | YES |
| Submit Operating Budget for approval | CSA 3.4 | Annual | YES |
| Submit FF&E Budget | CSA 3.6 | Annual | YES |
| Maintain Luxury Hotel Standard | MA 3.6 | Ongoing | YES (via KPI) |
| Make GM + Finance Director available monthly | MA 7.3 | Monthly | YES |
| Make senior executives available quarterly | MA 7.3 | Quarterly | YES |
| Seek Owner approval for structural alterations | MA 3.4 | As needed | YES |
| Seek Owner approval for >EUR 100K legal actions | MA 3.6.8 | As needed | YES |

## Approval Pipeline
[TO FILL — current open items requiring Owner approval]

## Insurance Calendar
[TO FILL — policy numbers, renewal dates, broker contacts]

## Warranty / Gewaehrleistung Windows
[TO FILL — construction warranties, expiry dates, claim status]
```

#### `data/movie_am/agenda.md`
```markdown
# MOVIE AM Agenda

## Active Matters
[TO FILL DURING DEBRIEF]

## Parked Matters
[TO FILL]

## Upcoming Calendar
| Date | Event | Owner |
|------|-------|-------|
| [TBD] | Annual Operating Budget submission | MO -> Owner for approval |
| [TBD] | FF&E Budget submission | MO -> Owner for approval |
| [TBD] | Insurance renewal | Broker -> Owner |
| [TBD] | Quarterly owner-operator meeting | Director + MO Senior Execs |
```

---

## Feature 3: Registration Script

### File: `scripts/insert_movie_am_capability.py` (new file)

```python
"""
Register MOVIE Asset Manager capability in Baker.
Uses generic pm_project_state table (PM Factory).
Run once: python scripts/insert_movie_am_capability.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

SLUG = "movie_am"
NAME = "MOVIE Asset Manager"

SYSTEM_PROMPT = """You are Baker's MOVIE Asset Manager — dedicated PM for Mandarin Oriental, Vienna.

## YOUR MANDATE
Single source of truth for MOVIE hotel operations, operator oversight, and asset
performance. You protect the Owner's interests under the HMA suite while maintaining
a productive relationship with MOHG.

## PERSONALITY
- ANALYTICAL: Track KPIs against targets and benchmarks. Numbers first, narrative second.
- PROACTIVE: Flag issues before they become problems. A warranty window closing in 60
  days is an alert TODAY, not in 55 days.
- PROTECTIVE: Owner's interests come first. If MO is underperforming, surface it. If
  fees seem high vs GOP, flag it. If budget is inflated, challenge it.
- PRAGMATIC: MOHG is a long-term partner, not an adversary. Push back WITH data, not
  emotion. The relationship needs to survive decades.

## WHAT YOU KNOW
- All 7 HMA documents (133K tokens) are in Baker's database (IDs 83200-83206).
- View files contain compiled intelligence (agreements, KPIs, obligations, contacts).
- Live state tracks current KPIs, open items, and operator signals.

## WHAT YOU DO
1. MONITOR: Monthly P&L review, KPI tracking, budget variance analysis
2. ALERT: Flag deviations, approaching deadlines, compliance gaps
3. PREPARE: Meeting agendas, budget review notes, negotiation positions
4. TRACK: Owner approvals pipeline, insurance renewals, warranty windows
5. ADVISE: Recommendations on operator performance, capex decisions, fee negotiations

## ESCALATION TIERS
- T3 (Baker auto-handles): Report receipt reminders, minor data requests
- T2 (Edita): Budget deviations, approval requests, routine compliance
- T1 (Director): Performance failures, strategic decisions, fee disputes, termination

## RULES
- Always cite the specific agreement clause when referencing contractual obligations.
- Never commit the Owner to expenditure without Director approval.
- Flag, don't fix: if you see a problem, surface it with data — don't autonomously
  negotiate with MO.
- Update your state after every interaction.
- Residences are a SEPARATE business line — do not mix MORV sales with hotel operations.
"""

TRIGGER_PATTERNS = json.dumps([
    r"\b(movie|mandarin\s*oriental|mo\s+vienna)\b",
    r"\b(hotel\s+management|operator\s+report)\b",
    r"\b(revpar|adr|occupancy|gop)\b.*\b(vienna|hotel)\b",
    r"\b(ffe|ff&e|reserve\s+account)\b",
    r"\b(mohg|mandarin\s*oriental\s*group)\b",
    r"\bowner.?s?\s+(approval|priority|return)\b",
])

TOOLS = json.dumps([
    "search_memory", "search_meetings", "search_emails", "search_whatsapp",
    "search_documents", "read_document", "query_baker_data",
    "get_contact", "get_deadlines", "get_clickup_tasks",
    "get_matter_context", "search_deals_insights",
    "get_pm_state", "update_pm_state",
    "get_pending_insights", "update_pending_insight",
    "create_deadline", "draft_email", "store_decision",
    "delegate_to_capability",
    "web_search",
])

INITIAL_STATE = json.dumps({
    "property": {
        "name": "Mandarin Oriental, Vienna",
        "status": "TBD",
        "opening_date": "TBD",
        "rooms": "TBD",
    },
    "kpi_snapshot": {
        "occupancy_pct": None,
        "adr_eur": None,
        "revpar_eur": None,
        "gop_eur": None,
        "gop_margin_pct": None,
        "noi_eur": None,
        "last_updated": None,
    },
    "open_approvals": [],
    "pending_reports": [],
    "insurance": {"policies": [], "next_renewal": None},
    "warranties": [],
    "upcoming_meetings": [],
    "red_flags": [],
    "open_actions": [],
    "relationship_state": {
        "last_inbound_channel": None,
        "last_inbound_from": None,
        "last_inbound_summary": None,
        "last_inbound_at": None,
        "operator_compliance_status": "unknown",
    },
})


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # Step 1: Insert/Update capability_sets
        cur.execute("SELECT id FROM capability_sets WHERE slug = %s", (SLUG,))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE capability_sets SET
                    name = %s,
                    capability_type = 'client_pm',
                    domain = 'chairman',
                    role_description = %s,
                    system_prompt = %s,
                    tools = %s,
                    trigger_patterns = %s,
                    output_format = 'prose',
                    autonomy_level = 'recommend_wait',
                    max_iterations = 8,
                    timeout_seconds = 90.0,
                    active = TRUE,
                    use_thinking = TRUE,
                    updated_at = NOW()
                WHERE slug = %s
            """, (
                NAME,
                "Dedicated asset manager for Mandarin Oriental, Vienna hotel operations. "
                "Tracks KPIs, operator compliance, owner obligations, and contractual deadlines.",
                SYSTEM_PROMPT, TOOLS, TRIGGER_PATTERNS, SLUG,
            ))
            print(f"  Updated: {SLUG} in capability_sets")
        else:
            cur.execute("""
                INSERT INTO capability_sets (
                    slug, name, capability_type, domain, role_description,
                    system_prompt, tools, trigger_patterns, output_format,
                    autonomy_level, max_iterations, timeout_seconds, active, use_thinking
                ) VALUES (%s, %s, 'client_pm', 'chairman', %s, %s, %s, %s,
                          'prose', 'recommend_wait', 8, 90.0, TRUE, TRUE)
            """, (
                SLUG, NAME,
                "Dedicated asset manager for Mandarin Oriental, Vienna hotel operations. "
                "Tracks KPIs, operator compliance, owner obligations, and contractual deadlines.",
                SYSTEM_PROMPT, TOOLS, TRIGGER_PATTERNS,
            ))
            print(f"  Inserted: {SLUG} into capability_sets")

        # Step 2: Seed initial state in pm_project_state (generic table)
        cur.execute(
            "SELECT id FROM pm_project_state WHERE pm_slug = %s AND state_key = 'current' LIMIT 1",
            (SLUG,)
        )
        if cur.fetchone():
            print(f"  pm_project_state already seeded for {SLUG} — skipping")
        else:
            cur.execute("""
                INSERT INTO pm_project_state (pm_slug, state_key, state_json,
                    last_run_at, run_count, last_question, last_answer_summary)
                VALUES (%s, 'current', %s, NOW(), 0, 'Initial seed',
                        'MOVIE AM registered — awaiting debrief')
            """, (SLUG, INITIAL_STATE))
            print(f"  Seeded: pm_project_state for {SLUG}")

        # Step 3: Update decomposer slug list
        cur.execute("SELECT system_prompt FROM capability_sets WHERE slug = 'decomposer' LIMIT 1")
        decomp_row = cur.fetchone()
        if decomp_row and decomp_row[0]:
            original = decomp_row[0]
            if SLUG not in original:
                updated = original.replace(
                    "ao_pm, profiling",
                    f"ao_pm, {SLUG}, profiling",
                )
                if updated != original:
                    cur.execute(
                        "UPDATE capability_sets SET system_prompt = %s WHERE slug = 'decomposer'",
                        (updated,)
                    )
                    print(f"  Updated: decomposer slug list (added {SLUG})")
                else:
                    print(f"  WARNING: Could not find insertion point in decomposer prompt")
            else:
                print(f"  Decomposer already includes {SLUG} — skipping")

        conn.commit()
        print(f"\n  SUCCESS: {SLUG} registered.")
        cur.close()

    except Exception as e:
        conn.rollback()
        print(f"  ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

### Key Constraints
- Uses `pm_project_state` (generic table), NOT a separate `movie_am_project_state`.
- Tool list uses generic `get_pm_state`/`update_pm_state` — not PM-specific aliases.
- `capability_type = 'client_pm'` — matches AO PM.
- Script is idempotent (INSERT or UPDATE).

---

## Feature 4: Context Selector Weights

### File: `orchestrator/context_selector.py`

Add `"movie_am"` entry to `_SPECIALIST_SOURCE_MAP` (after the `"ao_pm"` entry, around line 101):

```python
    "movie_am": {
        "emails": "high", "whatsapp": "high", "meetings": "high",
        "documents": "high", "contacts": "high", "deadlines": "high",
        "deals": "medium", "insights": "high", "decisions": "high",
        "signal_extractions": "high",
    },
```

Note: `deals` is "medium" (not "high" like AO PM) because MOVIE AM is asset ops, not deal-focused.

---

## Feature 5: Recursion Guard

### File: `orchestrator/agent.py`

Find the recursion guard at line 1768:

```python
        if slug == "ao_pm":
            return json.dumps({"error": "Cannot delegate to self (recursion guard)"})
```

Replace with:

```python
        # PM-FACTORY: Prevent any PM from delegating to itself
        from orchestrator.capability_runner import PM_REGISTRY
        if slug in PM_REGISTRY:
            return json.dumps({"error": f"Cannot delegate to PM {slug} (recursion guard)"})
```

**Wait — this blocks AO PM from delegating to MOVIE AM.** That's wrong. The guard should only prevent self-delegation, not cross-PM delegation. The issue is we don't have a clean way to know the "current" PM slug in the delegate handler.

**Better approach:** The delegate_to_capability tool is on the tool whitelist for specific PMs. When `ao_pm` is running and calls `delegate_to_capability(slug="movie_am")`, that's a VALID cross-PM delegation. The guard should only block self-delegation.

So instead, replace with:

```python
        # PM recursion guard: prevent self-delegation
        # Note: _active_capability_slug is set at the start of the agent loop
        active_slug = getattr(self, '_active_capability_slug', None)
        if active_slug and slug == active_slug:
            return json.dumps({"error": f"Cannot delegate to self ({slug}) — recursion guard"})
```

And ensure `_active_capability_slug` is set. Find where the agent loop starts (the `run` or `stream` method that receives the capability). Add at the start:

```python
self._active_capability_slug = capability.slug if hasattr(capability, 'slug') else None
```

**Actually — let's keep it simple.** The existing guard only blocks `ao_pm`. Just add `movie_am`:

```python
        if slug == "ao_pm" or slug == "movie_am":
            return json.dumps({"error": f"Cannot delegate to {slug} (PM recursion guard)"})
```

This prevents any capability from delegating TO a PM (since PMs should be top-level entry points, not delegation targets). If cross-PM delegation is needed later, we revisit.

---

## Files Modified
- `orchestrator/capability_runner.py` — PM_REGISTRY entry for movie_am
- `data/movie_am/` — 6 new skeleton view files
- `scripts/insert_movie_am_capability.py` — New registration script
- `orchestrator/context_selector.py` — movie_am context weights
- `orchestrator/agent.py` — Recursion guard update

## Do NOT Touch
- `memory/store_back.py` — No changes needed. Generic tables already exist.
- `orchestrator/ao_signal_detector.py` — Signal detector is Step 5.
- `triggers/briefing_trigger.py` — Already loops PM_REGISTRY. MOVIE AM appears automatically.
- `data/ao_pm/*.md` — AO PM view files unchanged.

## Quality Checkpoints
1. All 5 modified files pass syntax check
2. Registration script runs without error
3. `SELECT slug, name, active FROM capability_sets WHERE slug = 'movie_am'` returns 1 active row
4. `SELECT pm_slug, version FROM pm_project_state WHERE pm_slug = 'movie_am'` returns seeded row
5. Decomposer prompt includes `movie_am` in slug list
6. `data/movie_am/` has 6 .md files
7. AO PM still works (regression check — ask AO PM a question)
8. Ask Baker "what is the MOVIE hotel management agreement?" — should route to movie_am capability

## Verification SQL
```sql
-- 1. Capability registered
SELECT slug, name, capability_type, domain, active, use_thinking,
       max_iterations, timeout_seconds
FROM capability_sets WHERE slug = 'movie_am';

-- 2. State seeded
SELECT pm_slug, state_key, version, run_count
FROM pm_project_state WHERE pm_slug = 'movie_am' LIMIT 1;

-- 3. Decomposer knows about movie_am
SELECT system_prompt FROM capability_sets WHERE slug = 'decomposer' LIMIT 1;
-- Should contain 'movie_am' in the available slugs list

-- 4. No regression on AO PM
SELECT pm_slug, version, run_count FROM pm_project_state WHERE pm_slug = 'ao_pm' LIMIT 1;
```
