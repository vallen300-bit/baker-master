# MOVIE Asset Management PM — Architecture Proposal

**Date:** 2026-04-06
**Author:** AI Head (Claude Code)
**For Review:** Cowork (Claude Desktop)
**Status:** APPROVED WITH CONDITIONS (Cowork review 2026-04-06)
**Reviewer:** Cowork (Claude Desktop)

---

## 1. WHAT THIS IS

A persistent, self-updating Baker capability for managing **Mandarin Oriental, Vienna (MOVIE)** — the luxury hotel operations at Riemergasse 7. **Residences are excluded** — they are a separate business line and will get their own capability slug when ready.

**Modeled after AO PM** (Baker's first persistent PM, built for investor Andrey Oskolkov), but fundamentally different in nature:

| Dimension | AO PM (Person) | MOVIE AM (Asset) |
|-----------|---------------|------------------|
| **Object** | Investor relationship | Hotel operations + operator oversight |
| **Core risk** | Silence → broken trust | Missed KPI / obligation → money leaks |
| **Time horizon** | Event-driven (capital calls, meetings) | Calendar-driven (monthly reports, annual budgets, quarterly meetings) |
| **Monitoring** | Communication gap, mood, hunting cycle | Financial performance, contractual compliance, maintenance |
| **Red lines** | What not to say to AO | What not to concede to MOHG |
| **Signals** | WhatsApp/emails from AO orbit | Monthly P&L, budget submissions, operator emails |
| **State model** | Relationship state + pending discussion items | KPI snapshots + open approvals + compliance calendar |

---

## 2. ENTITY PROFILE

| Field | Value |
|-------|-------|
| **Property** | Mandarin Oriental, Vienna |
| **Legal Owner** | Riemergasse 7 Entwicklungs und Verwertungs GmbH |
| **Operator** | Mandarin Oriental Hotel Group Limited (MOHG), Hong Kong |
| **Property Type** | Luxury hotel + branded residences |
| **Residences** | 19-20 units, ~3,800 sqm saleable area |
| **Address** | Seilergasse 3/13+14, 1010 Vienna |
| **Agreement Suite** | 7 documents (MA, CSA, TSA, MLA, LA, DOG, FE Letter) — all dated 2020 |
| **Baker DB** | IDs 83200-83206, 133K tokens ingested |

---

## 3. CAPABILITY REGISTRATION

### Slug: `movie_am`

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **slug** | `movie_am` | Short, grep-friendly, matches data/ directory |
| **name** | MOVIE Asset Manager | Descriptive |
| **capability_type** | `domain` | Same as AO PM |
| **domain** | `chairman` | Owner's direct concern, not delegated ops |
| **max_iterations** | 8 | Same as AO PM — complex multi-tool reasoning |
| **timeout_seconds** | 90 | Same as AO PM |
| **use_thinking** | TRUE | Needs reasoning over KPIs + contractual terms |
| **autonomy_level** | `recommend_wait` | Flags issues, recommends actions, waits for Director |

### Trigger Patterns
```python
MOVIE_AM_TRIGGER_PATTERNS = [
    r"\b(movie|mandarin.oriental|mo\s+vienna)\b",        # Property name
    r"\b(hotel\s+management|operator\s+report)\b",        # Operator context
    r"\b(revpar|adr|occupancy|gop)\b.*\b(vienna|hotel)\b", # KPI + property
    r"\b(ffe|ff&e|reserve\s+account)\b",                   # FF&E specific
    r"\b(mohg|mandarin.oriental.group)\b",                 # Operator name
    r"\bowner.?s?\s+(approval|priority|return)\b",          # Owner rights
]
```

### Tool Whitelist
```python
MOVIE_AM_TOOLS = [
    # Search (read existing intelligence)
    "search_memory", "search_meetings", "search_emails", "search_whatsapp",
    "search_documents", "read_document", "query_baker_data",
    # Context (people, deadlines, tasks)
    "get_contact", "get_deadlines", "get_clickup_tasks",
    "get_matter_context", "search_deals_insights",
    # State (self-managing)
    "get_movie_am_state", "update_movie_am_state",
    # Actions (create alerts, draft communications)
    "create_deadline", "draft_email", "store_decision",
    # Delegation (to legal, finance, communications)
    "delegate_to_capability",
    # External (market data, benchmarks)
    "web_search",
]
```

---

## 4. FILE ARCHITECTURE

### 4.1 View Files (Compiled Intelligence)

```
data/movie_am/
├── SCHEMA.md                    # Directory + rules + file ownership
├── agreements_framework.md      # HMA suite: key clauses, fees, thresholds, deadlines
├── operator_dynamics.md         # MOHG relationship: people, power structure, leverage points
├── kpi_framework.md             # Metrics: definitions, targets, benchmarks, reporting cadence
├── owner_obligations.md         # What RG7 owes MOHG (and vice versa) — compliance checklist
└── agenda.md                    # Active matters + parked matters (like AO PM agenda.md)
```

**Why these 6 files (same count as AO PM):**

| MOVIE AM File | AO PM Equivalent | Why Different |
|---------------|-----------------|---------------|
| `SCHEMA.md` | `SCHEMA.md` | Same pattern — directory + rules |
| `agreements_framework.md` | `investment_channels.md` | AO has money channels; MOVIE has legal agreements |
| `operator_dynamics.md` | `psychology.md` | AO has personal psychology; MOVIE has corporate operator dynamics |
| `kpi_framework.md` | *(none — replaces sensitive_issues.md slot)* | AO PM doesn't track KPIs; MOVIE AM is KPI-driven |
| `owner_obligations.md` | `communication_rules.md` | AO has comms rules; MOVIE has contractual obligations |
| `agenda.md` | `agenda.md` | Same pattern — active + parked matters |

**What's NOT here (vs AO PM):**
- No `sensitive_issues.md` — the operator relationship doesn't have the same minefield dynamics as AO. If sensitive issues emerge during debrief, we add it.
- No `communication_rules.md` as a separate file — operator comms are formal/contractual, not psychological. Rules live in `owner_obligations.md`.
- **No `residences.md`** — Cowork decision: residences are a separate business line with different stakeholders, economics, and timelines. Will get own capability slug (`movie_res` or `brisen_residences`) when ready. MORV "Final Collection" stays in its own matter context.

### 4.2 View File Content (Skeleton)

#### SCHEMA.md
```markdown
# MOVIE AM — View Files

These files are Baker's compiled view on Mandarin Oriental, Vienna asset management.
Read ALL files at every MOVIE AM invocation. No exceptions.

| File | Contains | Owner |
|------|----------|-------|
| agreements_framework.md | HMA suite: fees, thresholds, termination, key clauses | Director + E+H |
| operator_dynamics.md | MOHG people, power structure, leverage, meeting cadence | Director |
| kpi_framework.md | RevPAR, ADR, occupancy, GOP, NOI — definitions, targets, benchmarks | Director + MO Finance |
| owner_obligations.md | What RG7 must do (funding, insurance, access) and what MOHG must do | Director + E+H |
| agenda.md | Active matters + parked matters | Director + Baker |

## Rules
- Director edits are gospel.
- If operator reports contradict a view file, flag it — don't override autonomously.
- When Director says "update the view" — edit the file and commit.
- Financial figures require source citation (Lesson #2 from AO PM build).
```

#### agreements_framework.md (key sections)
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
[TO FILL DURING DEBRIEF — extract from MA/CSA]
- Basic Management Fee: __%  of Gross Revenue
- Basic Service Fee: __% of Gross Revenue
- Royalty: __% of Gross Revenue
- Incentive Management Fee: __% of Adjusted Net Operating Income (after Owner's Priority Return)
- Marketing Contribution: __% (MA 7.4)
- Advertising Contribution: __% (MA 7.5)
- Centralised Revenue Management: __% (CSA 7.6)

## Owner's Priority Return
[TO FILL — this is the threshold before MO earns incentive fees]

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

#### operator_dynamics.md (key sections)
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
- What leverage does Owner have vs MOHG?
- What does MOHG want that we can give/withhold?
- Where are friction points?
- What's the relationship temperature today?

## Meeting Obligations (from MA 7.3)
- **Quarterly:** Senior MO executives available for operations/performance review
- **Monthly:** GM + Director of Finance present financials, answer Owner questions
- Routine Owner-GM communication is NOT "interference" (MA 7.2)

## Communication Protocol
[TO FILL — how does Director prefer to interact with MO?]
```

#### kpi_framework.md (key sections)
```markdown
# MOVIE KPI Framework

## Core Metrics

| Metric | Definition | Target | Benchmark Source |
|--------|-----------|--------|-----------------|
| **Occupancy** | Rooms sold / rooms available | __% | STR Vienna luxury set |
| **ADR** | Average Daily Rate (EUR) | EUR __ | STR Vienna luxury set |
| **RevPAR** | Revenue Per Available Room | EUR __ | STR Vienna luxury set |
| **GOP** | Gross Operating Profit | EUR __ / __% margin | MO monthly P&L |
| **NOI** | Net Operating Income | EUR __ / __% margin | After all fees + reserves |
| **Owner's Priority Return** | [Definition from MA] | EUR __ | Annual |
| **FF&E Reserve** | Cumulative reserve balance | EUR __ | CSA 3.6 / 5.5 |

## Reporting Cadence

| Report | Frequency | Source | Due By |
|--------|-----------|--------|--------|
| Monthly P&L | Monthly | MO Finance (Mario Habicher) | [Day of month TBD] |
| STR Benchmark | Monthly | STR (third party) | [TBD] |
| Operating Budget | Annual | MO submits for Owner approval | [Month TBD — CSA 3.4] |
| FF&E Budget | Annual | MO submits for Owner approval | [Month TBD — CSA 3.6] |
| Annual Accounts | Annual | MO Finance | [Deadline from CSA 6.3] |

## Alert Thresholds (Baker auto-flags)

| Condition | Severity | Action |
|-----------|----------|--------|
| Occupancy <50% for 2 consecutive months | T2 (Edita) | Review pricing strategy with MO |
| ADR drops >10% vs prior year | T2 (Edita) | Demand explanation from MO |
| GOP margin <__% | T1 (Director) | Board-level discussion |
| Monthly P&L not received by Day [X] | T3 (Baker) | Auto-reminder to Mario Habicher |
| Budget submission overdue | T2 (Edita) | Escalate to Francesco |
| FF&E reserve below required minimum | T1 (Director) | Contractual compliance issue |

## Seasonal Pattern
[TO FILL — Vienna hotel seasonality: high/low months, event calendar]
```

#### owner_obligations.md (key sections)
```markdown
# Owner ↔ Operator Obligations

## What RG7 (Owner) Must Do

| Obligation | Source | Frequency | Baker Monitors |
|-----------|--------|-----------|----------------|
| Make funds available for major renovations | MA 7.1.1 | As needed | YES — flag capex requests |
| Pay all taxes before delinquency | MA 7.1.3 | Ongoing | YES — deadline tracking |
| Maintain insurance coverage | CSA 8.1-8.6 | Annual renewal | YES — expiry alert |
| Not interfere with MO's management | MA 7.2 | Ongoing | NO — behavioral |
| Attend/convene quarterly meetings | MA 7.3 | Quarterly | YES — calendar tracking |
| Provide entry/access to authorized persons | MA 7.1.2 | Ongoing | NO |
| Cooperate on guarantee enforcement | MA 3.4 | As needed | YES — warranty tracking |
| Deliver hotel plans and revisions | MA 7.1.9 | As needed | NO |
| Notify MO of legal actions affecting hotel | MA 7.1.10 | As needed | YES — signal detection |

## What MOHG (Operator) Must Do

| Obligation | Source | Frequency | Baker Monitors |
|-----------|--------|-----------|----------------|
| Submit monthly financial statements | CSA 6.2 | Monthly | YES — receipt tracking |
| Submit annual accounts | CSA 6.3 | Annual | YES — deadline |
| Submit Operating Budget for approval | CSA 3.4 | Annual | YES — submission tracking |
| Submit FF&E Budget | CSA 3.6 | Annual | YES — submission tracking |
| Maintain Luxury Hotel Standard | MA 3.6 | Ongoing | YES — via KPI monitoring |
| Make GM + Finance Director available monthly | MA 7.3 | Monthly | YES — meeting tracking |
| Make senior executives available quarterly | MA 7.3 | Quarterly | YES — meeting tracking |
| Seek Owner approval for structural alterations | MA 3.4 | As needed | YES — approval pipeline |
| Seek Owner approval for >EUR 100K legal actions | MA 3.6.8 | As needed | YES — approval pipeline |
| Invoke warranties on behalf of Owner | MA 3.4 | As needed | YES — warranty tracking |
| Maintain adequate IT security | MA 3.5 | Ongoing | NO |
| Maintain property insurance | CSA 8.1-8.6 | Annual | YES — verify with broker |

## Approval Pipeline
[TO FILL — current open items requiring Owner approval]

## Insurance Calendar
[TO FILL — policy numbers, renewal dates, broker contacts]

## Warranty / Gewaehrleistung Windows
[TO FILL — construction warranties, expiry dates, claim status]
```

#### agenda.md
```markdown
# MOVIE AM Agenda

## Active Matters

### 1. [TBD — to emerge from debrief]
- **Status:**
- **Priority:**
- **Next action:**

### 2. [TBD]

### 3. [TBD]

## Parked Matters
- [To be populated during debrief]

## Upcoming Calendar
| Date | Event | Owner |
|------|-------|-------|
| [TBD] | Annual Operating Budget submission | MO → Owner for approval |
| [TBD] | FF&E Budget submission | MO → Owner for approval |
| [TBD] | Insurance renewal | Broker → Owner |
| [TBD] | Quarterly owner-operator meeting | Director + MO Senior Execs |
```

---

## 5. DATABASE TABLES

### 5.1 Primary State Table: `movie_am_project_state`

```sql
CREATE TABLE IF NOT EXISTS movie_am_project_state (
    id              SERIAL PRIMARY KEY,
    state_key       TEXT NOT NULL DEFAULT 'current',  -- Singleton ('current')
    state_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    version         INTEGER DEFAULT 1,                -- Optimistic locking
    last_run_at     TIMESTAMPTZ,
    last_question   TEXT,
    last_answer_summary TEXT,
    run_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_movie_am_state_key ON movie_am_project_state(state_key);
```

### 5.2 Audit Trail: `movie_am_state_history`

```sql
CREATE TABLE IF NOT EXISTS movie_am_state_history (
    id                SERIAL PRIMARY KEY,
    version           INTEGER NOT NULL,
    state_json_before JSONB NOT NULL,
    mutation_source   TEXT,          -- e.g., 'opus_auto', 'movie_signal_email'
    mutation_summary  TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### 5.3 Initial State JSON Structure

```json
{
  "property": {
    "name": "Mandarin Oriental, Vienna",
    "status": "TBD",
    "opening_date": "TBD",
    "rooms": "TBD"
  },
  "kpi_snapshot": {
    "occupancy_pct": null,
    "adr_eur": null,
    "revpar_eur": null,
    "gop_eur": null,
    "gop_margin_pct": null,
    "noi_eur": null,
    "last_updated": null
  },
  "open_approvals": [],
  "pending_reports": [],
  "insurance": {
    "policies": [],
    "next_renewal": null
  },
  "warranties": [],
  "upcoming_meetings": [],
  "red_flags": [],
  "open_actions": [],
  "relationship_state": {
    "last_inbound_channel": null,
    "last_inbound_from": null,
    "last_inbound_summary": null,
    "last_inbound_at": null,
    "operator_compliance_status": "unknown"
  }
}
```

**Key difference from AO PM:** The state_json here tracks **operational metrics + compliance items**, not relationship psychology. Dynamic KPI snapshots update frequently; view files hold the stable framework.

---

## 6. SIGNAL DETECTION

### File: `orchestrator/movie_signal_detector.py`

### 6.1 MO Orbit Patterns (people whose communications trigger MOVIE AM awareness)

```python
_MOVIE_ORBIT_PATTERNS = [
    r'francesco',                     # MO primary contact
    r'robin',                         # MO London HQ
    r'mario\s*habicher',              # MO Finance
    r'rolf\s*huebner',               # Owner's Head of Ops
    r'henri\s*movie',                 # Building contact (WhatsApp)
    r'victor\s*rodriguez',            # Concierge
    r'@mohg\.',                       # MO Group domain
    r'@mandarinoriental\.',           # MO domain
]
```

### 6.2 Keyword Patterns (topics that signal MOVIE AM relevance)

```python
_MOVIE_KEYWORD_PATTERNS = [
    r'mandarin\s*oriental.*vienna',
    r'movie\b',                       # Project codename
    r'\boccupancy\b.*\b(hotel|vienna|mandarin)\b',
    r'\brevpar\b',
    r'\bgop\b.*\b(hotel|report|monthly)\b',
    r'\bff&?e\b',                     # FF&E reserve
    r'\boperating\s*budget\b',
    r'\bowner.?s?\s*approval\b',
    r'\brecovery\s*lab\b',
]
```

### 6.3 Detection Channels

| Channel | Hook Point | What It Catches |
|---------|-----------|----------------|
| **Email** | `triggers/email_trigger.py` | Monthly P&L from Mario, budget submissions, insurance notices |
| **WhatsApp** | `triggers/waha_webhook.py` | Messages from Henri, Victor Rodriguez, Rolf |
| **Meetings** | `orchestrator/meeting_pipeline.py` | Quarterly owner-operator meetings, MO finance calls |
| **Documents** | `orchestrator/document_pipeline.py` | Ingested reports, insurance policies, budgets |

### 6.4 Signal Actions

```python
def flag_movie_am_signal(channel: str, source: str, summary: str, timestamp=None):
    """Non-fatal. Updates movie_am_project_state with inbound signal."""
    # Same pattern as ao_signal_detector.flag_ao_signal()
    # Updates relationship_state.last_inbound_*
```

---

## 7. CAPABILITY RUNNER WIRING

### 7.1 System Prompt Injection (at invocation time)

When `movie_am` capability is triggered, `capability_runner.py` injects:

1. **View files** from `data/movie_am/` (all 6 files, concatenated)
2. **Live state** from `movie_am_project_state` table (KPI snapshot, open actions, red flags)
3. **Relevant deadlines** (insurance, warranty, compliance — next 90 days)

### 7.2 Auto-Update After Each Run (with Complexity Guard)

After MOVIE AM returns an answer:
- **Complexity guard:** Only auto-update if the query required tool use OR touched KPI/compliance data. Simple lookups against view files (e.g., "what's the GM's name?") skip the auto-update to save Opus costs (~$0.15-0.30 per call).
- Guard logic: check if `tool_use_count > 0` or if answer contains KPI/compliance keywords (occupancy, RevPAR, GOP, approval, insurance, warranty, capex).
- If guard passes: Opus extracts structured state updates from the Q&A, persists to `movie_am_project_state` with audit trail.
- Same pattern as `_auto_update_ao_state()` in capability_runner.py, plus the guard.

### 7.3 Methods to Add to capability_runner.py

| Method | Purpose |
|--------|---------|
| `_load_movie_am_view_files()` | Read all .md files from `data/movie_am/` in defined order |
| `_get_movie_am_project_state_context()` | Format live state for system prompt |
| `_auto_update_movie_am_state()` | Post-run state extraction via Opus |

---

## 8. BRIEFING INTEGRATION

### Daily Briefing Section: "MOVIE ASSET STATUS"

Function: `_gather_movie_am_context()` in `triggers/briefing_trigger.py`

**Checks:**
1. **Monthly P&L received?** — Has MO submitted this month's financials? If overdue, flag.
2. **Open approvals** — Any owner approval requests pending?
3. **Insurance renewals** — Any policies expiring in next 60 days?
4. **Warranty windows** — Any Gewaehrleistung periods closing in next 90 days?
5. **Meeting cadence** — Is the quarterly meeting overdue?
6. **KPI alerts** — Occupancy, ADR, GOP trending below thresholds?

**Only appears in briefing if there's something actionable.** No noise.

---

## 9. SYSTEM PROMPT (Soul of the PM)

```
You are Baker's MOVIE Asset Manager — dedicated PM for Mandarin Oriental, Vienna.

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
- All 7 HMA documents (133K tokens) are in Baker's database.
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
```

---

## 10. DEBRIEF TOPICS (For Director Session)

Following AO PM Lesson #3 (red lines first), proposed debrief sequence:

| # | Topic | Purpose | Priority |
|---|-------|---------|----------|
| 1 | **Current state** | Is hotel operating? Opening date? Current phase? | Essential |
| 2 | **Red lines** | What should Baker never say/do regarding MOHG? Confidential? | Essential |
| 3 | **Relationship health** | How's the relationship with MO? Friction areas? | Essential |
| 4 | **Key people** | Actual contacts today, who matters, who's difficult | Essential |
| 5 | **Financial baseline** | Last GOP, RevPAR, occupancy, NOI, fee burden | Essential |
| 6 | **Fee structure** | Actual fee %s, Owner's Priority Return, are fees fair? | High |
| 7 | **Budget cycle** | When does MO submit budget? Review process? Issues? | High |
| 8 | **Insurance** | Current policies, broker, renewal dates, coverage gaps | High |
| 9 | **Warranties** | Construction warranties, Gewaehrleistung, claim status | High |
| 10 | **Recovery Lab** | What is it? Status? Operator? | Medium |
| 11 | **Capex pipeline** | Open capex, deferred maintenance, FF&E reserve status | Medium |
| 12 | **Compliance** | Hotel license, fire safety, permits — any gaps? | Medium |
| 13 | **Meeting cadence** | Are quarterly/monthly meetings happening? Who attends? | Medium |
| 14 | **Open issues** | Anything else Director wants Baker to track? | Medium |

**Debrief state file:** `memory/movie-am-debrief-state.md` (per AO PM Lesson #4)

---

## 11. IMPLEMENTATION SEQUENCE

| Phase | Components | Estimate | Dependencies | Who |
|-------|-----------|----------|-------------|-----|
| **A. Skeleton** | View files directory (6 files), DB tables (2), capability registration | ~2h | None | Code Brisen |
| **B. Plumbing** | Signal detector, capability_runner wiring, briefing integration, auto-update with guard | ~3h | Phase A | Code Brisen |
| **C. Debrief** | Fill view files through Director sessions (topics 1-6 essential, 7-14 high/medium) | ~2-3 sessions | Phase A | Director + Cowork |
| **D. Activate** | Test end-to-end + auto-parse operator reports (P&L → KPI snapshots) | ~2h | Phase A + B + topics 1-6 done | Code Brisen |

**Phase A + B → Code Brisen brief.** Phase C → Director + Cowork (2-3 sessions, not all at once). Phase D only after debrief topics 1-6 filled.

---

## 12. DESIGN DECISIONS (Cowork Review — 2026-04-06)

All open questions resolved. Decisions locked.

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Scope: MOVIE-only or portfolio? | **MOVIE-only** | Each asset gets its own PM when ready. No portfolio PM until 3+ assets running. |
| 2 | Naming: `movie_am` vs generic? | **`movie_am`** | Specific slugs are greppable and unambiguous. Davos → `alpengold_am`. |
| 3 | Hagenauer overlap? | **Strict boundary** | MOVIE AM = hotel ops post-opening only. Hagenauer stays in own matter context. Cross-reference via `search_memory`, not shared state. |
| 4 | Residences sub-PM? | **Separate capability entirely** | Different stakeholders, economics, timelines. Removed from this build. Gets own slug when ready. |
| 5 | Auto-parse operator reports? | **Yes, but Phase D** | Valuable but not blocking. Get skeleton + debrief done first. |
| 6 | Opus auto-update cost? | **Justified with guard** | Complexity threshold: only auto-update if query used tools or touched KPI/compliance data. Simple lookups skip it. |
| 7 | STR benchmarks? | **Not now** | Manual ingestion fine for quarterly review. No scraping infrastructure for monthly data. Revisit in 6 months. |
| 8 | Decomposer registration? | **Yes** | Multi-capability queries like "how does MOVIE performance affect AO's return?" need both PMs. |

### Issues Fixed (from Cowork review)

1. **Residences removed** — `residences.md` deleted from view files. Separate business line, separate capability.
2. **`operator_mood` → `operator_compliance_status`** — Values: `compliant`, `minor_issues`, `material_breach`, `unknown`. Measure performance, not feelings.
3. **Auto-update complexity guard** — Only Opus auto-update if `tool_use_count > 0` or answer touches KPI/compliance keywords. Saves ~$0.15-0.30 per simple lookup.

---

## 13. RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|------|--------|-----------|
| View files stale (no debrief) | PM gives wrong advice | Phase C is mandatory before Phase D activation |
| Fee structure wrong in view file | Incorrect cost analysis | Source citation rule (Lesson #2) — every number needs document reference |
| Signal detection too broad | Noise in briefing | Start with tight orbit (Francesco, Mario, Robin only), expand after testing |
| State bloat | Slow context injection | Keep state_json lean — compiled intelligence in view files, not JSONB |
| Overlap with AO PM | Confusion on Hagenauer context | Clear scope boundary: MOVIE AM = hotel ops only. Hagenauer construction claims stay in AO PM / legal matter context |

---

## 14. LESSONS APPLIED FROM AO PM BUILD

| Lesson | Application |
|--------|------------|
| #1 JSONB is write-only for humans | View files for compiled intelligence, JSONB for dynamic state only |
| #2 Financial figures need source citations | All fee %s, KPI targets must cite agreement clause or report |
| #3 Ask about red lines first | Debrief topic #2 is red lines, before deep-diving into operations |
| #4 Debrief state file is essential | `memory/movie-am-debrief-state.md` created at debrief start |
| #5 Wire monitoring from day one | Phase B (signal detection + briefing) runs parallel to Phase C (debrief) |
| #6 Orbit people matter | Signal detector covers MO contacts, not just MOHG corporate |

---

*End of architecture proposal. Ready for Cowork critique.*
