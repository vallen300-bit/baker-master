# BRIEF: VAULT-PHASE1 — Schema First + Real Content on Mac Mini

**STATUS: REQUIRES DIRECTOR + AI HEAD DISCUSSION BEFORE IMPLEMENTATION**

Three open questions must be resolved before Code Brisen acts:
1. MacBook writes to vault — allowed with hooks, or always through wiki_staging?
2. OpenClaw as Tier 2 model gateway — integrate in Phase 1 or defer?
3. Active matter list — Director confirms which 8-12 get folders

## Context

Baker's knowledge is scattered: `data/ao_pm/` (8 files), `data/movie_am/` (6 files), `outputs/` (27 .md files), `wiki_pages` PG table (14 rows), Dropbox (hundreds of files). No unified store. This is the foundation for the three-tier architecture (decision #7: "Obsidian is Tier 2's brain").

Phase 1 creates the vault structure, writes templates, and migrates the first real content. Everything else (Phase 2-3.5) depends on this.

**Source plan:** `Baker-Project/PLAN_BAKER_VAULT_OBSIDIAN.md` v2.0 (9 Cowork amendments)

## Estimated time: ~8-10h
## Complexity: Medium
## Prerequisites: Mac Mini SSH access (confirmed working), git on Mac Mini

---

## Feature 1: Create Vault Structure + Git Init

### Problem
No `~/baker-vault/` directory exists on Mac Mini. Need the Karpathy three-layer structure with CEO horizontal inside wiki/.

### Current State
Mac Mini has `~/Desktop/baker-code/` (the repo). No vault directory. Git and SSH confirmed working.

### Implementation

**Run on Mac Mini via SSH:**

```bash
# Create vault root
mkdir -p ~/baker-vault

cd ~/baker-vault

# KARPATHY LAYER 1 — raw/ (immutable originals, new intake only)
mkdir -p raw/{contracts,financials,correspondence,transcripts,filings,media,clippings}

# KARPATHY LAYER 2 — wiki/ (synthesized knowledge, CEO horizontal)
mkdir -p wiki/_inbox
mkdir -p wiki/matters
mkdir -p wiki/people
mkdir -p wiki/entities
mkdir -p wiki/research

# KARPATHY LAYER 3 — schema/ (templates only, NO runtime config)
mkdir -p schema/templates
mkdir -p schema/agents
mkdir -p schema/sync

# Obsidian config
mkdir -p .obsidian/plugins
mkdir -p .obsidian/snippets

# Git init
git init
```

**Create `.gitignore`:**

```
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache/
.DS_Store
*.tmp
```

**Create `.obsidian/app.json`** (minimal Obsidian config):

```json
{
  "attachmentFolderPath": "raw/media",
  "newFileLocation": "folder",
  "newFileFolderPath": "wiki/_inbox",
  "showLineNumber": true,
  "strictLineBreaks": true
}
```

### `raw/` Intake Sources (what goes where)

| Source | `raw/` subfolder | Volume | Intake method |
|---|---|---|---|
| Contracts, term sheets, agreements | `contracts/` | Low (~2-5/month) | Tier 2 files from signal_queue |
| Financial tables, Excel extracts | `financials/` | Low (~5-10/month) | Tier 2 files from signal_queue |
| Formal letters, legal notices | `correspondence/` | Low | Tier 2 files from signal_queue |
| Fireflies / Plaud / YouTube transcripts | `transcripts/` | ~5-10/week | Tier 1 signals → Tier 2 files + source summary |
| Court filings, regulatory docs | `filings/` | Rare | Tier 2 files from signal_queue |
| Images, attachments | `media/` | Low | Tier 2 files from signal_queue |
| Director browser clippings | `clippings/` | Director-driven | Bookmarklet → `/api/clip` → signal_queue → Tier 2 |

**What does NOT go into `raw/`:**
- Emails → PostgreSQL `emails` table (high volume, operational)
- WhatsApp messages → PostgreSQL `whatsapp_messages` table (high volume, operational)
- Signals extracted from emails/WhatsApp → `wiki/matters/*/cards/` (knowledge, not raw data)

### Key Constraints
- Mac Mini only. Do NOT create vault on MacBook or Render.
- `raw/` subdirectories are by document TYPE, not by matter (Karpathy rule — one document, one place)
- Every `raw/` document gets a companion source summary in `wiki/` (Amendment #10)
- No empty matter folders yet — that's Feature 3

---

## Feature 2: Schema Layer — Templates + Rules

### Problem
Without templates, every wiki page will have inconsistent structure. Schema must exist BEFORE any content is migrated.

### Implementation

**File: `~/baker-vault/schema/VAULT.md`**

```markdown
# Baker Vault — Rules & Conventions

## Structure
- `raw/` — Immutable originals. One copy per document. Organized by type.
- `wiki/` — Synthesized knowledge. Agents read this first.
- `schema/` — Templates and prompt templates only. No runtime config.

## Link Format
- Internal: `[[wiki/matters/oskolkov/_overview]]` (full path from vault root)
- To raw: `[[raw/contracts/participation-agreement-aelio-lcg.pdf]]`
- To Dropbox: `[Source](dropbox://Baker-Project/01_Projects/Oskolkov/03_Source_Of_Truth/)`

## Frontmatter
Every wiki page MUST have YAML frontmatter. See schema/templates/ for required fields.

## Naming
- Lowercase, hyphens: `financing-to-completion.md` not `Financing To Completion.md`
- Matter folders: short slug (`oskolkov`, `movie`, `hagenauer`)
- People files: `firstname-lastname.md`
- Card files: `YYYY-MM-DD-topic.md`

## Confidence
- `high` — verified by Director or primary source document
- `medium` — extracted by Baker, not yet verified
- `low` — inferred, stale (>30 days untouched), or single-source

## Routing
- Items routed with confidence < 0.7 go to `wiki/_inbox/`
- ALL routing decisions logged to `schema/sync/routing-log.md`

## Ownership
- `director` — Director wrote or confirmed this content
- `seed_migration` — migrated from baker-code or PG during Phase 1
- `vault_daemon` — auto-written by Tier 2 processing
- `tier3_session` — written during Tier 3 analysis session

## Context Loading Hierarchy (mandatory for all agents)
Every agent session — Tier 2 signal processing or Tier 3 Director session — follows this exact read order:
1. `wiki/hot.md` — what's happening NOW (updated after every signal cycle)
2. `wiki/index.md` — what exists in the vault
3. `wiki/matters/{matter}/_index.md` — matter sub-index (if signal is matter-specific)
4. Specific pages as needed
NOT: scan everything. NOT: grep the whole vault. Follow the hierarchy.

## Contradiction Callouts
When lint or any agent finds conflicting data between pages, use Obsidian's native callout:
```
> [!contradiction]
> This page says AO's share is EUR 6.9M but [[wiki/matters/oskolkov/financing-to-completion]]
> says EUR 6.0M. Last updated: 2026-04-13. Needs Director resolution.
```
These render as colored warning boxes in Obsidian and are searchable via `grep "[!contradiction]"`.

## Source Summaries
Every document ingested into `raw/` MUST have a companion summary page in `wiki/`. The raw file is immutable; the summary is the wiki entry. Summary page follows `schema/templates/source-summary-template.md`. This is how Karpathy's pattern works: source → summary → cross-links.

## Vault Lint (8 categories — runs nightly in Phase 3)
1. Orphan pages — no incoming `[[links]]`
2. Dead links — references to non-existent pages
3. Gap detection — missing cross-references between related matters
4. Stale claims — contradictions between pages (insert `[!contradiction]`)
5. Source attribution — facts not linked to a source in `raw/` or Dropbox
6. Title consistency — duplicate or ambiguous page names
7. Index coherence — `index.md` catalog vs actual vault files
8. Graph fragmentation — disconnected clusters in the link graph

## Rules
1. Never modify files in `raw/` — they are immutable originals
2. Wiki pages link to raw documents, never duplicate content
3. One document, one location — no copies across matter folders
4. Financial figures require source citation (lesson #17)
5. `schema/` is templates only — runtime config stays in PostgreSQL
6. Every `raw/` document gets a wiki summary page (source summary rule)
7. Contradictions flagged with `[!contradiction]` callout — never silently overwritten
```

**File: `~/baker-vault/schema/templates/matter-template.md`**

```markdown
---
title: "{MATTER_NAME}"
type: matter
confidence: medium
sources: []
related: []
created: "{DATE}"
updated: "{DATE}"
updated_by: seed_migration
---

# {MATTER_NAME}

## Status
- **Phase:** {active | dormant | closed}
- **Last activity:** {DATE}
- **Key contact:** [[wiki/people/{PERSON}]]

## Summary
{2-3 sentences: what this matter is, what Baker needs to know}

## Active Threads
1. {Thread with status}

## Key Documents
- [[raw/{type}/{filename}]] — {description}
- [Dropbox: {path}](dropbox://{path}) — {description}

## Red Flags
- {Active risks, if any}

## Decision Log
See `decisions/` subfolder for full history.
```

**File: `~/baker-vault/schema/templates/person-template.md`**

```markdown
---
title: "{FULL_NAME}"
type: person
confidence: medium
sources:
  - "vip_contacts PG (tier {TIER})"
related: []
created: "{DATE}"
updated: "{DATE}"
updated_by: seed_migration
---

# {FULL_NAME}

## Role
{role from vip_contacts}

## Contact
- WhatsApp: {whatsapp_id}
- Email: {email}
- Tier: {1|2|3}

## Matters
- [[wiki/matters/{MATTER}/_overview]] — {relationship to matter}

## Key Context
{What Baker needs to know about this person — from Director knowledge, meeting history, communication patterns}

## Communication Notes
{Preferences, sensitivities, decision-making style}
```

**File: `~/baker-vault/schema/templates/entity-template.md`**

```markdown
---
title: "{ENTITY_NAME}"
type: entity
confidence: medium
sources: []
related: []
created: "{DATE}"
updated: "{DATE}"
updated_by: seed_migration
---

# {ENTITY_NAME}

## Type
{company | fund | SPV | trust | government_body}

## Jurisdiction
{Country / registration}

## Key People
- [[wiki/people/{PERSON}]] — {role at entity}

## Connected Matters
- [[wiki/matters/{MATTER}/_overview]] — {relationship}

## Key Facts
{Registration, ownership, key dates, financial position}
```

**File: `~/baker-vault/schema/templates/card-template.md`**

```markdown
---
title: "{MATTER} — {TOPIC}"
type: card
confidence: medium
sources:
  - "{signal source — email, WhatsApp, document}"
related:
  - "[[wiki/matters/{MATTER}/_overview]]"
created: "{DATE}"
updated: "{DATE}"
updated_by: vault_daemon
signal_id: {signal_queue ID, if applicable}
stage: "{detected | enriched | decided}"
---

# {MATTER} — {TOPIC}

## Summary (2-3 lines)
{What happened and what it means}

## Analysis
{Full analysis — cross-references, comparisons, implications}

## Recommended Actions
1. {Action with owner and deadline}

## Open Questions
- {Questions requiring Director decision}

## Previous Cards
- [[wiki/matters/{MATTER}/cards/{PREV_CARD}]] — {what was known before}
```

**File: `~/baker-vault/schema/templates/decision-template.md`**

```markdown
---
title: "Decision: {TOPIC}"
type: decision
confidence: high
sources: []
related: []
created: "{DATE}"
updated: "{DATE}"
updated_by: director
---

# Decision: {TOPIC}

## Decision
{What was decided, in one clear sentence}

## Context
{Why this decision was needed}

## Alternatives Considered
1. {Alternative and why rejected}

## Consequences
- {What changes as a result}

## Review Date
{When to revisit, if applicable}
```

**File: `~/baker-vault/schema/templates/source-summary-template.md`**

```markdown
---
title: "{DOCUMENT_NAME} — Summary"
type: source_summary
confidence: medium
sources:
  - "[[raw/{type}/{filename}]]"
related:
  - "[[wiki/matters/{MATTER}/_overview]]"
created: "{DATE}"
updated: "{DATE}"
updated_by: vault_daemon
---

# {DOCUMENT_NAME} — Summary

## Document
- **Original:** [[raw/{type}/{filename}]]
- **Type:** {contract | financial | correspondence | transcript | filing}
- **Date:** {document date}
- **Parties:** {who is involved}

## Key Takeaways
1. {Most important finding}
2. {Second finding}
3. {Third finding}

## Entities Mentioned
- [[wiki/people/{PERSON}]] — {role in document}
- [[wiki/entities/{ENTITY}]] — {role in document}

## Key Figures
| Item | Value | Source Page/Section |
|------|-------|-------------------|
| {metric} | {value} | p.{X} |

## Cross-References
- Contradicts: {link to conflicting page, if any}
- Supersedes: {link to older version, if any}
- Related: {links to related wiki pages}
```

### Key Constraints
- Templates use `{PLACEHOLDERS}` — not real data. Migration scripts replace them.
- `schema/agents/` prompt templates written in Feature 7 (after matter content exists)
- No runtime config in schema/ — feature flags, API keys, PM state all stay in PostgreSQL
- Every template includes `confidence` + `sources` fields (decision #26)
- Source summary template is mandatory — every `raw/` document gets one in `wiki/` (Karpathy rule #7)

---

## Feature 3: Migrate AO PM Content

### Problem
AO PM has 8 view files in `baker-code/data/ao_pm/`. Also 14 `wiki_pages` rows in PostgreSQL. Need to migrate to vault with proper frontmatter and cross-links.

### Current State
- `data/ao_pm/`: SCHEMA.md (941B), agenda.md (6.3K), communication_rules.md (4.2K), financing_to_completion.md (5.9K), ftc-table-explanations.md (18K), investment_channels.md (5.1K), psychology.md (5.2K), sensitive_issues.md (1.8K)
- `wiki_pages` PG: 7 AO PM pages (slug: `ao_pm/*`)
- Total: ~47K of AO content

### Implementation

**Step 1: Create matter folder**
```bash
mkdir -p ~/baker-vault/wiki/matters/oskolkov/{cards,decisions}
```

**Step 2: Create `_index.md`**

```markdown
---
title: "Oskolkov Matter Index"
type: matter
confidence: high
sources:
  - "data/ao_pm/ (baker-code repo)"
  - "wiki_pages PG table"
related:
  - "[[wiki/entities/aelio-holding]]"
  - "[[wiki/entities/rg7]]"
  - "[[wiki/people/andrey-oskolkov]]"
created: "2026-04-15"
updated: "2026-04-15"
updated_by: seed_migration
---

# Oskolkov — Matter Index

| File | Contains | Source |
|------|----------|--------|
| [[wiki/matters/oskolkov/_overview]] | Status, threads, key links | seed_migration |
| [[wiki/matters/oskolkov/psychology]] | Hunter archetype, 11 drivers, loyalty algorithm | Director |
| [[wiki/matters/oskolkov/investment-channels]] | Channel 1 (Hayford), Channel 2 (Cyprus) | Director + Constantinos |
| [[wiki/matters/oskolkov/financing-to-completion]] | Baker v009 — uses, sources, AO position | Edita + Baker |
| [[wiki/matters/oskolkov/agenda]] | Active + parked matters | Director + Baker |
| [[wiki/matters/oskolkov/sensitive-issues]] | Minefields and dance instructions | Director only |
| [[wiki/matters/oskolkov/communication-rules]] | Rule Zero, hunting cycle, framing | Director |
| [[wiki/matters/oskolkov/ftc-table-explanations]] | Row-by-row v009 table explanations | Baker |
```

**Step 3: Migrate each file**

For each of the 7 content files (excluding SCHEMA.md which becomes `_index.md`):
1. Read from `data/ao_pm/{file}.md`
2. Add YAML frontmatter per template
3. Convert internal references to `[[wiki links]]`
4. Write to `~/baker-vault/wiki/matters/oskolkov/{file}.md`

Example for `psychology.md`:

```markdown
---
title: "AO — Psychology Profile"
type: matter
confidence: high
sources:
  - "Director knowledge (multi-session debrief)"
related:
  - "[[wiki/matters/oskolkov/_overview]]"
  - "[[wiki/people/andrey-oskolkov]]"
  - "[[wiki/matters/oskolkov/communication-rules]]"
created: "2026-04-15"
updated: "2026-04-15"
updated_by: seed_migration
---

{EXISTING CONTENT FROM data/ao_pm/psychology.md — preserved verbatim}
```

**Step 4: Create `_overview.md`** (new file — synthesized from agenda + existing knowledge)

```markdown
---
title: "Oskolkov — Overview"
type: matter
confidence: high
sources:
  - "[[wiki/matters/oskolkov/agenda]]"
  - "[[wiki/matters/oskolkov/financing-to-completion]]"
related:
  - "[[wiki/entities/aelio-holding]]"
  - "[[wiki/entities/rg7]]"
  - "[[wiki/entities/lcg]]"
  - "[[wiki/people/andrey-oskolkov]]"
  - "[[wiki/people/edita-vallen]]"
  - "[[wiki/people/constantinos-pohanis]]"
created: "2026-04-15"
updated: "2026-04-15"
updated_by: seed_migration
---

# Oskolkov — Overview

## Status
- **Phase:** active
- **Last activity:** 2026-04-14
- **Key contact:** [[wiki/people/andrey-oskolkov]]

## Summary
Andrey Oskolkov (AO) is principal investor in RG7/MO Vienna (25% via Aelio Holding) and Lilienmatt/Baden-Baden co-owner. 22-year relationship with Director. Baker manages the relationship via AO PM specialization.

## Active Threads
1. Capital call execution (EUR 2M/2M/3M phased Apr-Jun) — [[wiki/matters/oskolkov/financing-to-completion]]
2. Participation Agreement (LCG↔Aelio) — UNSIGNED, must sign by May 31
3. Val d'Isère — new target, early stage
4. MO Prague (CITIC Group) — new target via AO

## Key Documents
- [Dropbox: 009_MOVIE_AO_Financing_Final_Reported.xlsx](dropbox://Baker-Project/01_Projects/Oskolkov/03_Source_Of_Truth/The_Actual_Position/) — THE authoritative table
- [Dropbox: LCG_Drawdown_Requests_AO_April2026.docx](dropbox://Baker-Project/01_Projects/Oskolkov/02_final/) — 3 formal drawdown requests

## Red Flags
- Participation Agreement unsigned — dilution risk if not signed by May 31
- AO withholding ~EUR 1M+ residence fees as leverage (MO Vienna)
```

### Key Constraints
- Preserve ALL existing content verbatim — only ADD frontmatter and links
- `sensitive-issues.md` migrates as-is — it's already Director-only content, no redaction needed
- `ftc-table-explanations.md` (18K) is the largest file — migrate in full, it's essential context
- `SCHEMA.md` does NOT migrate as a wiki page — its content becomes `_index.md`

---

## Feature 4: Migrate Movie AM Content

### Problem
Movie AM has 6 view files in `baker-code/data/movie_am/`. Same migration pattern as AO PM.

### Current State
- `data/movie_am/`: SCHEMA.md (982B), agenda.md (6.2K), agreements_framework.md (9.8K), kpi_framework.md (4.5K), operator_dynamics.md (4.2K), owner_obligations.md (5.4K)
- `wiki_pages` PG: 6 Movie AM pages
- Total: ~31K of Movie content

### Implementation

**Same pattern as Feature 3:**

```bash
mkdir -p ~/baker-vault/wiki/matters/movie/{cards,decisions}
```

Migrate 5 content files (excluding SCHEMA.md) with frontmatter. Create `_index.md` and `_overview.md`.

`_overview.md` key content:
- Phase: active (hotel opened Nov 2025, FY1)
- Key contacts: Mario Habicher (GM), Francesco Cefalù (CDO), Laurent Kleitman (CEO MOHG)
- Active threads: F&B losing 4x budget (EUR 1.57M swing), HMA fee disputes, capital call
- Red flags: Owner withholding ~EUR 1M+ residence fees as leverage

### Key Constraints
- `agreements_framework.md` (9.8K) is legally sensitive — financial figures need source citations (lesson #17 from pm_lessons)
- Cross-link to `[[wiki/matters/oskolkov/_overview]]` — these matters are deeply connected (AO owns 25% of MO Vienna via Aelio)

---

## Feature 5: Migrate Research Outputs

### Problem
27 `.md` files in `outputs/` totaling 511K. Mix of research reports, dossiers, meeting briefs, architecture docs. Should live in `wiki/research/`.

### Implementation

**Classify and migrate selectively.** Not all 27 are vault-worthy. Categories:

**Migrate to `wiki/research/` (research reports + dossiers):**
- `EUROPEAN_LUXURY_HOTEL_AI_MARKET_ANALYSIS.md`
- `MARKET_GAP_ANALYSIS_AI_HOTEL_DEVELOPMENT_8APR2026.md`
- `RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md`
- `BORIS_SCHRAN_PEAKSIDE_DOSSIER.md`
- `NEUBAUER_MICHAEL_PROFILE_BRIEF.md`
- `MARTIN_HAGENAUER_EXTERNAL_DOSSIER.md`
- `KARPATHY_LLM_KNOWLEDGE_WIKI_REFERENCE.md`

**Migrate to `wiki/matters/{matter}/cards/` (matter-specific analyses):**
- `HAGENAUER_INSOLVENCY_LEGAL_STRATEGY_MEMO_PART1.md` → `wiki/matters/hagenauer/cards/`
- `HAGENAUER_PR_STRATEGY_PART2_INSOLVENCY.md` → `wiki/matters/hagenauer/cards/`
- `HAGENAUER_PR_BRIEFING_FOR_SANDRA.md` → `wiki/matters/hagenauer/cards/`
- `MORV_FINAL_COLLECTION_STRATEGY.md` → `wiki/matters/morv/cards/`
- `LILIENMATT_TAX_RESTRUCTURING_MEMO_KPMG.md` → `wiki/matters/lilienmatt/cards/`
- `MOVIE_AM_PM_ARCHITECTURE.md` → `wiki/matters/movie/cards/`

**Migrate to `wiki/people/` (people dossiers — convert to person template):**
- `SANDRA_LUGER_MEETING_BRIEF_30MAR2026.md` + `SANDRA_MEETING_BRIEF_MERGED_30MAR2026.md` → merge into `wiki/people/sandra-luger.md`

**DO NOT migrate (internal/technical/transient):**
- `EDITA_RUSSO_AI_SETUP.md` — internal setup doc
- `WAHA_WHATSAPP_INGESTION_FAILURE_REPORT_8APR2026.md` — incident report, stays in repo
- `YOUTUBE_INGESTION_ARCHITECTURE.md` — engineering doc
- `CLAUDE_CODE_ULTRAPLAN_REFERENCE.md` — reference doc
- `CLAUDE_MANAGED_AGENTS_REFERENCE.md` — reference doc
- `APIFY_AGENT_SKILLS_WEB_PARSING_REFERENCE.md` — reference doc
- Build scripts (`build_*.py`, `convert_*.py`, `generate_*.py`)
- Meeting intel that's matter-specific → cards/ under the right matter

Each migrated file gets YAML frontmatter. Cross-links where obvious (e.g., Hagenauer dossier links to Hagenauer matter).

### Key Constraints
- Migration creates ADDITIONAL matter folders: `hagenauer/`, `morv/`, `lilienmatt/` — confirm with Director these are in the active 8-12
- Original files stay in `outputs/` (they're in the baker-code repo, not the vault)
- Large files (>15K) migrate in full — don't truncate research reports

---

## Feature 6: Create Master Index + Hot Cache

### Problem
Agents need to know what exists before they can find anything. `hot.md` = what's happening NOW. `index.md` = catalog of everything.

### Implementation

**File: `~/baker-vault/wiki/hot.md`**

```markdown
---
title: "Hot Cache"
type: system
confidence: high
created: "2026-04-15"
updated: "2026-04-15"
updated_by: seed_migration
---

# Hot Cache — Read First Every Session

## Active Right Now
- **AO Capital Call:** EUR 2M/2M/3M phased Apr-Jun. Participation Agreement UNSIGNED → May 31 deadline.
- **Hagenauer:** Insolvency filed Mar 27. Durchgriffshaftung risk. Acquisition strategy in play.
- **Movie (MO Vienna):** FY1 since Nov 2025. F&B losing 4x budget. Owner withholding residence fees.
- **MORV:** "Final Collection" — 9 released, never discount.

## Recent Decisions
{populated from baker_decisions PG table — last 5 decisions}

## Pending Signals
{placeholder — populated by Tier 2 daemon in Phase 3}
```

**File: `~/baker-vault/wiki/index.md`**

```markdown
---
title: "Vault Index"
type: system
confidence: high
created: "2026-04-15"
updated: "2026-04-15"
updated_by: seed_migration
---

# Baker Vault — Master Index

## Matters (active)
| Matter | Folder | Status | Last Updated |
|--------|--------|--------|-------------|
| Oskolkov/AO | [[wiki/matters/oskolkov/_index]] | active | 2026-04-15 |
| Movie/MO Vienna | [[wiki/matters/movie/_index]] | active | 2026-04-15 |
| Hagenauer | [[wiki/matters/hagenauer/_index]] | active | 2026-04-15 |
| MORV | [[wiki/matters/morv/_index]] | active | 2026-04-15 |
| Lilienmatt | [[wiki/matters/lilienmatt/_index]] | active | 2026-04-15 |
| Cupial | [[wiki/matters/cupial/_index]] | active | TBD |
{Director confirms full list during discussion}

## Matters (dormant — Dropbox archive)
| Matter | Dropbox Path | Last Active |
|--------|-------------|-------------|
{To be populated with Director during discussion}

## People
See [[wiki/people/_index]] — ~80 Tier 1+2 VIP profiles (Phase 2)

## Entities
See [[wiki/entities/_index]] — ~15-20 companies/funds/SPVs (Phase 2)

## Research
See [[wiki/research/_index]] — analysis reports and references
```

**File: `~/baker-vault/wiki/log.md`**

```markdown
---
title: "Vault Log"
type: system
created: "2026-04-15"
---

# Vault Log — Append Only

## 2026-04-15
- SEED: Vault created. Schema templates written.
- SEED: Oskolkov matter migrated (8 files from data/ao_pm/)
- SEED: Movie matter migrated (6 files from data/movie_am/)
- SEED: Research outputs migrated (7 reports, 6 matter cards, 1 person merge)
- SEED: hot.md, index.md, log.md created
```

### Key Constraints
- `hot.md` is manually maintained during Phase 1. Becomes auto-updated in Phase 3.
- `index.md` uses `[[wiki links]]` — will resolve once Obsidian opens the vault
- `log.md` is append-only — never edit past entries

---

## Feature 7: Agent Prompt Templates

### Problem
Decision #21: Specializations span all three tiers. Shared prompt templates in `schema/agents/` tell each tier how to operate the specialist.

### Implementation

**File: `~/baker-vault/schema/agents/specialist-ao.md`**

```markdown
# AO PM — Specialist Prompt Template

## Identity
You are AO PM — Baker's Project Manager for the Andrey Oskolkov relationship.

## Context Loading
1. Read [[wiki/hot.md]] — what's happening NOW
2. Read [[wiki/matters/oskolkov/_index]] — all AO files
3. Read ALL files in [[wiki/matters/oskolkov/]] — no exceptions
4. Check [[wiki/matters/oskolkov/cards/]] — most recent card first

## Rules
- Director edits are gospel
- If data contradicts a view file, flag it — don't override autonomously
- Financial figures require source citation
- AO = Eli (alias in personal/financial contexts). Same person.
- AO's company = Aelio Holding Ltd, referred to as "Aelios" in financial tables

## Key Relationships
- [[wiki/people/andrey-oskolkov]] — the principal
- [[wiki/people/edita-vallen]] — Director's partner, handles financial tables
- [[wiki/people/constantinos-pohanis]] — Channel 2 (Cyprus) operations
- [[wiki/matters/movie/_overview]] — AO owns 25% of MO Vienna via Aelio

## Communication Style
See [[wiki/matters/oskolkov/communication-rules]] — Rule Zero applies always.
```

**File: `~/baker-vault/schema/agents/specialist-movie-am.md`**

Similar structure. References Movie matter files, key people (Mario Habicher, Francesco Cefalù, Laurent Kleitman), operator dynamics.

**File: `~/baker-vault/schema/agents/specialist-hagenauer.md`**

Similar structure. References Hagenauer matter files, insolvency context, legal contacts (Arndt Blaschka at E+H).

### Key Constraints
- These are TEMPLATES — not the actual runtime prompts. Tier 1 (capability_runner.py) and Tier 2 (claude -p) both read these to build their system prompts.
- Prompt templates link to vault pages with `[[wiki links]]` — the agent resolves them to file paths at runtime
- Phase 1 writes templates for the 3 matters with real content (AO, Movie, Hagenauer). Others added as matters are populated.

---

## Feature 8: Initial Git Commit + Remote

### Problem
Vault must be version-controlled from day one (decision #20: git snapshots for recovery).

### Implementation

```bash
cd ~/baker-vault
git add -A
git commit -m "Phase 1: Schema first + AO/Movie/Hagenauer content seed

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

# Create private GitHub repo (Code Brisen has gh CLI)
gh repo create vallen300-bit/baker-vault --private --source=. --push
```

### Key Constraints
- PRIVATE repo — contains sensitive business intelligence
- Do NOT add to baker-code repo — vault is a separate git repository
- Obsidian Git plugin (Phase 1 step 13 in plan) auto-commits every 15 min after Obsidian is opened

---

## Files Modified
- None in baker-code repo. All work happens in `~/baker-vault/` on Mac Mini.

## Do NOT Touch
- `baker-code/data/ao_pm/` — source files stay, wiki_pages PG still serves Tier 1
- `baker-code/data/movie_am/` — same
- `baker-code/outputs/` — originals stay, vault gets copies
- `baker-code/orchestrator/capability_runner.py` — Tier 1 continues reading from PG wiki_pages (rewired in Phase 3)
- `baker-code/memory/store_back.py` — no PG schema changes in Phase 1

## Quality Checkpoints
1. `ssh macmini "find ~/baker-vault -name '*.md' | wc -l"` → should be 50+ files
2. `ssh macmini "cat ~/baker-vault/schema/VAULT.md"` → rules doc exists
3. `ssh macmini "cat ~/baker-vault/schema/templates/matter-template.md"` → template exists BEFORE content
4. `ssh macmini "cat ~/baker-vault/wiki/matters/oskolkov/_overview.md"` → has YAML frontmatter + `[[wiki links]]`
5. `ssh macmini "cat ~/baker-vault/wiki/matters/movie/_overview.md"` → same
6. `ssh macmini "cat ~/baker-vault/wiki/hot.md"` → hot cache populated
7. `ssh macmini "cd ~/baker-vault && git log --oneline -3"` → committed and pushed
8. `ssh macmini "cd ~/baker-vault && git remote -v"` → private GitHub repo configured
9. Every frontmatter block has `confidence`, `sources`, `updated_by` fields
10. No empty folders — every directory has at least one real file

## Verification
```bash
# On Mac Mini
cd ~/baker-vault

# Structure check
find . -type d | sort

# Content check
find wiki/matters -name "*.md" | wc -l   # Should be ~25-30
find schema -name "*.md" | wc -l          # Should be ~10
cat wiki/index.md                          # Master catalog exists

# Git check
git status                                 # Clean working tree
git log --oneline -1                       # Phase 1 commit exists
git remote -v                              # GitHub remote configured

# Link check (basic)
grep -r "\[\[" wiki/ | wc -l              # Cross-links exist
grep -r "\[\[" wiki/ | grep -v "wiki/" | head  # Flag any broken link patterns
```

---

## Discussion Items for Director + AI Head (RESOLVE BEFORE IMPLEMENTATION)

### Q1: MacBook Vault Writes
Architecture decision #17 says "only Mac Mini writes vault." Cowork Amendment #2 allows MacBook writes with hooks. During Tier 3 sessions, AI Head may need to update wiki pages directly.

**Options:**
- A) MacBook writes allowed with pre-commit hooks (Amendment #2 approach)
- B) MacBook always writes through wiki_staging → Mac Mini daemon promotes
- C) MacBook can write wiki/ but not raw/ or schema/

### Q2: OpenClaw Integration
OpenClaw is installed on Mac Mini. It can serve as Tier 2's model gateway (Gemma 4 primary → Gemini Pro fallback). Not needed for Phase 1 (no daemon yet), but architecture should account for it.

**Decision needed:** Wire OpenClaw into Phase 3 vault daemon, or keep model routing manual?

### Q3: Active Matter List
Plan says 8-12 active matters get folders. Currently confirmed active: oskolkov, movie, hagenauer, cupial, morv, lilienmatt. Director must confirm:
- Which additional matters get folders?
- Which are dormant (Dropbox pointer only)?

### Q4: Obsidian Installation
Is Obsidian already installed on Mac Mini? If not, Code Brisen needs to install it (`brew install --cask obsidian`). Obsidian Git plugin also needed.
