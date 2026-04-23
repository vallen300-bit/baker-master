# BRIEF: KBL_SCHEMA_1 — Baker-vault schema v1 greenfield scaffolding (templates + people.yml + entities.yml + VAULT.md)

## Context

M0 quintet row 1. Baker-vault's schema is greenfield: `schema/VAULT.md` is a 1-line stub, `schema/templates/` is empty, and the registries `people.yml` / `entities.yml` do not exist. Only `slugs.yml` (v9) is authoritative — and it mixes matters, persons, and entities in one list, which the 3-way taxonomy ratified 2026-04-23 is designed to disambiguate.

**Design calls locked by Director 2026-04-23 ("default recom is fine"):**

- **Frontmatter = 7 standard fields:** `type`, `slug`, `name`, `updated`, `author`, `tags`, `related`.
- **People-slug format:** `firstname-lastname` (e.g., `andrey-oskolkov`). Collision rule: append middle-initial, then institution.
- **Taxonomy = 3-way:**
  - **matter** — things we DO (projects, disputes, initiatives, transactions). Owns action + narrative.
  - **person** — natural persons (individuals, VIPs, counterparty principals).
  - **entity** — legal / corporate actors (holdings, funds, banks, operators).
- **slugs.yml scope unchanged this brief.** Existing v9 slugs remain as-is. Re-taxonomy of legacy entries is a follow-on brief (`KBL_SLUGS_RETAXONOMY_1`) — Director-gated §4 #5 because it touches KBL schema semantics.

**What this brief ships (6 content files):**

1. `schema/VAULT.md` — comprehensive rules document (frontmatter spec, naming, lifecycle, cross-linking, lint rules).
2. `schema/templates/matter.md` — template markdown file for any new matter-type wiki page.
3. `schema/templates/person.md` — template for person-type page.
4. `schema/templates/entity.md` — template for entity-type page.
5. `people.yml` — registry file (v1, minimal seed).
6. `entities.yml` — registry file (v1, minimal seed).

**Delivery path (important):**

Baker-vault writes are Mac Mini's sole domain (CHANDA #9; Render has no push credentials). B-code works in baker-master. So this brief:

- B-code creates the 6 files under a staging path `vault_scaffolding/v1/` **in baker-master** (new top-level directory).
- Post-merge AI Head action (autonomous per charter §3): SSH Mac Mini → copy files into `~/baker-vault/` at the correct paths → commit in baker-vault with a `Director-signed:` marker carrying the ratification quote.

This mirrors PR #49 (AUTHOR_DIRECTOR_GUARD_1), where the shell script was shipped to baker-master then installed on Mac Mini vault via SSH.

**Source artefacts:**
- `OPERATING.md` row 2 (M0 quintet, design calls B/A/A locked)
- `_ops/ideas/2026-04-21-cortex3t-production-roadmap.md` M0 scope
- Director authorization: "default recom is fine" (2026-04-23)

## Estimated time: ~2–2.5h
## Complexity: Low–Medium (content-heavy, minimal logic)
## Prerequisites: None runtime. Familiarity with `baker-vault/slugs.yml` structure helps.

---

## Fix/Feature 1: `vault_scaffolding/v1/schema/VAULT.md`

### Problem

Baker-vault has no authored rules document. Agents reading / writing vault content have no single reference for frontmatter, naming, lifecycle, cross-linking, or lint behaviour. Current `baker-vault/schema/VAULT.md` is a 1-line stub (`# Vault Rules`).

### Current State

- `baker-vault/schema/VAULT.md` line-count: 2 lines (header + blank).
- Deployed slug consumer: `kbl/slug_registry.py` (baker-master) loads `slugs.yml` with schema validation. No equivalent for people/entities yet.
- `wiki/` has 26 top-level directories (matters + `people/` + `entities/` + `research/` + `_inbox/`). Most lack frontmatter consistency — reformatting existing files is OUT of scope for this brief; this brief defines forward-looking rules only.

### Implementation

**Step 1 — Create directory** `vault_scaffolding/v1/schema/` in baker-master.

**Step 2 — Write file** `vault_scaffolding/v1/schema/VAULT.md` with the following content verbatim:

````markdown
---
title: Vault Rules
type: schema
version: 1
updated: 2026-04-23
author: director
---

# Vault Rules — Baker wiki schema v1

**Purpose.** Authoritative rules for structuring, naming, and cross-linking
every file under `baker-vault/wiki/`. Read once at session start by any
agent that writes to the vault.

**Scope.** Forward-looking. Existing files without this schema are
grandfathered and audited by `_lint-report.md` rather than forcibly
rewritten. Re-taxonomy of legacy content is a follow-on brief.

## §1. Three-way taxonomy

Every vault entry belongs to exactly one of:

| Type | Meaning | Registry |
|------|---------|----------|
| `matter` | A thing we DO — project, dispute, initiative, transaction | `slugs.yml` |
| `person` | A natural person | `people.yml` |
| `entity` | A legal / corporate actor (holding, fund, bank, operator) | `entities.yml` |

The type of an entry is declared in its frontmatter `type` field and
determines its wiki directory:

- `type: matter` → `wiki/matters/<slug>/` (directory of files)
- `type: person` → `wiki/people/<slug>.md` (single file)
- `type: entity` → `wiki/entities/<slug>.md` (single file)

## §2. Frontmatter — 7 standard fields

Every `.md` file under `wiki/` MUST open with a YAML frontmatter block
containing these 7 fields, in this order:

```yaml
---
type: matter | person | entity
slug: <canonical-slug>
name: "Human-readable name"
updated: YYYY-MM-DD
author: director | agent | <agent-id>
tags: [<slug1>, <slug2>, ...]
related: ["[[wiki/path/to/other]]", ...]
---
```

Field contracts:

- **`type`** — one of the three taxonomy values. No other values allowed.
- **`slug`** — canonical slug from the matching registry. MUST exist in
  the registry (`slugs.yml` / `people.yml` / `entities.yml`). Sub-files
  in a matter directory (e.g. `agenda.md`, `psychology.md`) MAY omit `slug`
  only if the directory's `_index.md` carries it.
- **`name`** — free-form human name. Quoted if it contains special chars.
- **`updated`** — ISO 8601 date (YYYY-MM-DD) of the last meaningful edit.
  Agents updating content MUST bump this.
- **`author`** — `director` for Director-authored files (CHANDA inv #4
  protected); `agent` for generic agent writes; specific agent id (e.g.
  `ao_pm`, `movie_am`) when a capability owns the file.
- **`tags`** — list of canonical slugs for cross-matter relevance. Empty
  list `[]` allowed.
- **`related`** — list of wiki-link references `[[wiki/path/to/other]]`.
  Empty list allowed. Used by `scripts/check_wiki_links.py` (future).

Additional frontmatter fields (beyond the 7) are allowed for matter-
specific metadata (e.g. `voice: gold`, `layer: 2`, `live_state_refs: []`
used in AO PM's three-layer split). The 7 above are the mandatory floor.

## §3. Slug naming rules

### §3.1 Matter slugs (`slugs.yml`)

- Lowercase, kebab-case. Digits allowed.
- Single token for short names (`aukera`, `lilienmatt`).
- Compound for scoped matters (`hagenauer-rg7`, `mo-vie-am`, `mo-vie-exit`).
- Aliases (case-insensitive) covered in `slugs.yml` `aliases` field.

### §3.2 Person slugs (`people.yml`)

- Format: `firstname-lastname`. Lowercase, kebab-case.
- Examples: `andrey-oskolkov`, `michal-hassa`, `dennis-egorenkov`.
- Umlauts / accents: strip to ASCII (`saehn` not `sähn`, `muller` not `müller`).
- **Collision rule:** if two people share firstname + lastname, append:
  1. Middle initial: `john-a-smith` vs `john-b-smith`.
  2. Then institution: `john-smith-ubs` vs `john-smith-aukera`.
- One `person` entry per individual. Roles / affiliations go in the
  wiki page body, not the slug.

### §3.3 Entity slugs (`entities.yml`)

- Lowercase, kebab-case.
- Prefer short canonical forms (`aelio`, `aukera`, `mohg`, `bcomm`).
- Long-form allowed when needed for disambiguation (`aelio-holding-ltd`).
- No legal-form suffixes in slug (`gmbh`, `ag`, `ltd`) unless needed to
  distinguish related entities (`brisen-capital-sa` vs `brisen-development-gmbh`).

## §4. Lifecycle — same as `slugs.yml`

Every registry entry has a `status`:

| Status | Offered to model | Accepted by validator | Routed |
|--------|------------------|-----------------------|--------|
| `active` | yes | yes | yes |
| `retired` | no | yes (historical signals) | no |
| `draft` | no | no (in-session candidates only) | no |

Version bumps on any non-cosmetic change to a registry file. Consumers
record the version in output so cross-run comparisons stay honest.

## §5. Cross-linking rules

- Use Obsidian-style wiki-links: `[[wiki/path/to/file]]` (no file extension).
- Reference a matter's root via `[[wiki/matters/<slug>/_index]]`.
- Reference a person via `[[wiki/people/<slug>]]`.
- Reference an entity via `[[wiki/entities/<slug>]]`.
- Every cross-link added to a `related:` frontmatter field MUST resolve
  to an existing file. Lint catches dangling links.

## §6. Protected files — `author: director`

Files with frontmatter `author: director` are mutation-guarded by CHANDA
detector #4 (`invariant_checks/author_director_guard.sh`). Agents MAY
commit edits to these files ONLY when the commit message carries a
`Director-signed: "<quoted instruction>"` marker. See `CHANDA_enforcement.md`
§4 row #4 for enforcement mechanics.

## §7. Lifecycle of a new wiki page

1. **Register the slug first.** Edit `slugs.yml` / `people.yml` /
   `entities.yml` via PR. Bump the registry `version`.
2. **Create the file.** Copy the matching template from `schema/templates/`.
3. **Fill frontmatter.** All 7 fields required.
4. **Wire cross-links.** `related:` + body references.
5. **Commit.** Agent commits include the `Director-signed:` marker iff
   touching `author: director` files.

## §8. What this file does NOT cover

- Implementation of `people.yml` / `entities.yml` loaders — future
  `kbl/people_registry.py` + `kbl/entity_registry.py` briefs.
- Lint script (`_lint-report.md` generator) — future brief.
- Re-taxonomy of existing `slugs.yml` entries across the 3-way split —
  Director-gated, follow-on (`KBL_SLUGS_RETAXONOMY_1`).
- Sub-file frontmatter conventions inside matter directories (e.g.
  `agenda.md`, `psychology.md`, `red-flags.md`) — those inherit the
  matter's slug via `_index.md` and use matter-specific additional fields.

## §9. Amendment log

| Date | Section | Change | Authority |
|------|---------|--------|-----------|
| 2026-04-23 | all | Initial schema v1 (KBL_SCHEMA_1) — 3-way taxonomy, 7-field frontmatter, firstname-lastname people slugs. | Director "default recom is fine" 2026-04-23 |
````

### Key Constraints

- **No code yet.** This file is pure rules. Loaders for `people.yml` / `entities.yml` ship in follow-on briefs.
- **Preserve the fenced YAML block** inside the markdown body — keep triple backticks exactly. (File itself starts with frontmatter delimited by `---`.)
- **Line count: ~170 lines.** Matches the weight of `CHANDA_enforcement.md` (76 lines after amendments) but covers more rules because this is a foundational schema doc.
- **No forward-looking promises.** Anything not in `§8` scope stays out.

### Verification

1. `python3 -c "import yaml; yaml.safe_load(open('vault_scaffolding/v1/schema/VAULT.md').read().split('---')[1])"` — frontmatter parses as valid YAML.
2. `grep -c "^## §" vault_scaffolding/v1/schema/VAULT.md` — exactly 9 (§1 through §9).
3. `head -6 vault_scaffolding/v1/schema/VAULT.md | tail -5 | grep -c '^[a-z]'` — 5 frontmatter lines (type, version, updated, author, title).
4. File ends with amendment log table (no trailing content).

---

## Fix/Feature 2: `vault_scaffolding/v1/schema/templates/matter.md`

### Problem

No template exists for new matter-type wiki files. New matters get authored ad-hoc → drift. Templates standardize.

### Current State

- `baker-vault/schema/templates/` directory is empty.
- AO matter directory at `wiki/matters/oskolkov/` already uses a richer layer-2 schema (frontmatter includes `layer`, `live_state_refs`, `sources`, `updated_by`). This brief's template is the **baseline** frontmatter; AO-style extensions are allowed per VAULT.md §2.

### Implementation

**Create** `vault_scaffolding/v1/schema/templates/matter.md` with the following content verbatim:

```markdown
---
type: matter
slug: <CANONICAL-SLUG-FROM-SLUGS-YML>
name: "<Matter Human Name>"
updated: 2026-04-23
author: agent
tags: []
related: []
---

# <Matter Name>

## Status

- **Phase:** <proposal | active | dormant | closed>
- **Owner:** <agent-id or Director>
- **Last audit:** 2026-04-23

## Overview

<1–2 paragraphs. What is this matter. Why does Brisen care. Who are the
key counterparties. Current headline.>

## Key people

- [[wiki/people/<firstname-lastname>]] — <role in this matter>

## Key entities

- [[wiki/entities/<slug>]] — <role in this matter>

## Current state

<Section for the now — what's happening this week / month.>

## Open questions

- <Question 1>
- <Question 2>

## Recent activity

<Reverse-chronological log of material events. Date + 1-line summary.>

## Related matters

- [[wiki/matters/<other-slug>/_index]] — <relationship>
```

### Key Constraints

- **Placeholder literals** (`<SLUG>`, `<Matter Name>`, etc.) stay as-is — authors replace on copy.
- **`updated` field defaults to template-creation date.** Authors bump on first save.
- **`author: agent` default** — human Director authors flip to `author: director` if they want the mutation-guard (CHANDA #4) applied. Agents SHOULD NOT flip this flag themselves.
- **Tags + related empty by default** — populate on authoring.

### Verification

1. `python3 -c "import yaml; fm = open('vault_scaffolding/v1/schema/templates/matter.md').read().split('---')[1]; yaml.safe_load(fm)"` — no errors.
2. `grep -c "^## " vault_scaffolding/v1/schema/templates/matter.md` — exactly 7 (`Status`, `Overview`, `Key people`, `Key entities`, `Current state`, `Open questions`, `Recent activity`, `Related matters` = 8; adjust count expectation to 8).
3. File contains all 7 frontmatter keys: `grep -E '^(type|slug|name|updated|author|tags|related):' vault_scaffolding/v1/schema/templates/matter.md | wc -l` → 7.

---

## Fix/Feature 3: `vault_scaffolding/v1/schema/templates/person.md`

### Problem

Same — no person-type template. People entries drift in shape.

### Current State

- `baker-vault/wiki/people/` exists but is **empty** (zero `.md` files). Grandfathered people info is scattered across matter files (e.g. AO details in `wiki/matters/oskolkov/_overview.md`). This brief establishes the template for future person-type pages.

### Implementation

**Create** `vault_scaffolding/v1/schema/templates/person.md`:

```markdown
---
type: person
slug: <firstname-lastname>
name: "<Firstname Lastname>"
updated: 2026-04-23
author: agent
tags: []
related: []
---

# <Firstname Lastname>

## Role

- **Primary affiliation:** <entity slug>
- **Title / role:** <title>
- **Location:** <city, country>
- **Contact:** <email> / <phone> / <channel>

## Relationship to Brisen

<1 paragraph. How does Brisen know this person. Since when. Current
relationship state (active / dormant / contentious).>

## Matters involved

- [[wiki/matters/<slug>/_index]] — <role in this matter>

## Entities

- [[wiki/entities/<slug>]] — <relationship to entity>

## Notes

<Free-form. Director-curated personal insight that isn't in a matter file.>

## Interaction log

<Reverse-chronological. Date + channel + summary. Material interactions only.>
```

### Key Constraints

- **Slug = firstname-lastname** per VAULT.md §3.2.
- **Collision handling** documented in VAULT.md §3.2 rule; template itself carries no collision logic.
- **Body sections are optional but templated.** Authors may delete unused sections on first save.

### Verification

1. YAML frontmatter parses.
2. `grep -E '^(type|slug|name|updated|author|tags|related):' vault_scaffolding/v1/schema/templates/person.md | wc -l` → 7.
3. `grep "^## " vault_scaffolding/v1/schema/templates/person.md | wc -l` → 6 (`Role`, `Relationship to Brisen`, `Matters involved`, `Entities`, `Notes`, `Interaction log`).

---

## Fix/Feature 4: `vault_scaffolding/v1/schema/templates/entity.md`

### Problem

Same — no entity-type template.

### Current State

`baker-vault/wiki/entities/` exists but is empty.

### Implementation

**Create** `vault_scaffolding/v1/schema/templates/entity.md`:

```markdown
---
type: entity
slug: <canonical-slug>
name: "<Legal / Common Name>"
updated: 2026-04-23
author: agent
tags: []
related: []
---

# <Legal Name>

## Identity

- **Legal form:** <GmbH | SA | Ltd | LP | etc.>
- **Jurisdiction:** <country>
- **Registration:** <registry + number, if known>
- **Canonical long name:** <full legal name>

## Role in Brisen ecosystem

<1 paragraph. What does this entity do. How does Brisen interact with it.
Contractual / commercial / regulatory relationship.>

## Key people

- [[wiki/people/<firstname-lastname>]] — <role in entity>

## Matters involved

- [[wiki/matters/<slug>/_index]] — <role>

## Beneficial ownership

<If relevant: who owns this entity, key shareholders, UBO info. Reference
source documents.>

## Notes

<Free-form. Director-curated or compliance-driven context.>
```

### Key Constraints

- **Entity ≠ matter.** If confused, re-read VAULT.md §1 table. Example: `aukera` is an entity (bank); `aukera` as currently used in `slugs.yml` is a matter-slug for the Aukera-lender relationship arc. The existence of a matter slug with the same name as a future entity slug is handled by the type-prefix in wiki paths (`wiki/matters/aukera/` vs `wiki/entities/aukera`). Cross-link freely.
- **`Beneficial ownership`** section is sensitive — agents should not populate from scraped sources. Director-curated.

### Verification

1. YAML frontmatter parses.
2. 7 frontmatter keys present.
3. `grep "^## " vault_scaffolding/v1/schema/templates/entity.md | wc -l` → 6.

---

## Fix/Feature 5: `vault_scaffolding/v1/people.yml`

### Problem

No people registry. Person wiki pages can't be slug-validated. Every future `kbl/people_registry.py` needs an authoritative list; this brief creates it at v1.

### Current State

File does not exist.

### Implementation

**Create** `vault_scaffolding/v1/people.yml`:

```yaml
# Baker people registry — single source of truth for natural persons.
#
# Consumers (future, not in this brief):
#   kbl/people_registry.py                  (validator + alias index)
#   scripts/check_wiki_links.py             (resolve [[wiki/people/<slug>]])
#   Step-1 classifier + Step-5 scope filter (2-way cross-ref with matters)
#
# Schema: mirrors slugs.yml. Loaded by future kbl/people_registry.py with
# load-time validation failing loudly on any duplicate slug / alias.
#
# Slug format (VAULT.md §3.2):
#   firstname-lastname, lowercase, kebab-case, ASCII-stripped diacritics.
#   Collision: append middle-initial, then institution.
#
# Lifecycle (same as slugs.yml):
#   active  — offered to model in prompts, accepted by validator, routed
#   retired — NOT offered, still accepted (historical signals), not routed
#   draft   — NOT offered, NOT accepted (in-session candidates only)
#
# Version bumps on any non-cosmetic change.
version: 1
updated_at: 2026-04-23

people:
  - slug: dimitry-vallen
    status: active
    description: "Director of Brisen Group. Owner + principal decision-maker."
    aliases: [director, dimitry, "dimitry vallen"]

  - slug: andrey-oskolkov
    status: active
    description: "Principal investor (Aelio Holding Ltd). 22-year relationship with Director. Matter: ao."
    aliases: [ao, oskolkov, andrey, eli]
```

### Key Constraints

- **Minimal seed — 2 entries only.** Director and AI Head populate further entries by PR as new people surface in wiki content. Do NOT bulk-import from CLAUDE.md's people table — that would be overreach and invites collisions without Director review of each.
- **Aliases MUST match** normalization rule (case-insensitive, whitespace-collapsed) — same as `slug_registry.py` shape. Do not repeat the canonical slug itself in `aliases`.
- **`status: active` for both seed entries** — both are currently Brisen-active.
- **`description` is one-line.** Do not write paragraphs — the wiki page is for that.
- **Slug collisions** — in this seed, none. Future entries must follow VAULT.md §3.2 collision rule.

### Verification

1. `python3 -c "import yaml; d = yaml.safe_load(open('vault_scaffolding/v1/people.yml')); assert d['version'] == 1 and len(d['people']) == 2"` — no errors.
2. `python3 -c "import yaml; d = yaml.safe_load(open('vault_scaffolding/v1/people.yml')); slugs = [e['slug'] for e in d['people']]; assert len(slugs) == len(set(slugs)), 'duplicate slugs'"` — no errors.
3. `grep -c "^  - slug:" vault_scaffolding/v1/people.yml` → 2.

---

## Fix/Feature 6: `vault_scaffolding/v1/entities.yml`

### Problem

No entity registry.

### Current State

File does not exist.

### Implementation

**Create** `vault_scaffolding/v1/entities.yml`:

```yaml
# Baker entities registry — single source of truth for legal/corporate actors.
#
# Consumers (future, not in this brief):
#   kbl/entity_registry.py                  (validator + alias index)
#   scripts/check_wiki_links.py             (resolve [[wiki/entities/<slug>]])
#   Step-1 classifier + Step-5 scope filter (cross-ref with matters + people)
#
# Schema: mirrors slugs.yml.
#
# Slug format (VAULT.md §3.3):
#   Short canonical form preferred (aelio, aukera, mohg).
#   Long-form acceptable for disambiguation (brisen-capital-sa vs brisen-development-gmbh).
#
# Lifecycle (same as slugs.yml):
#   active | retired | draft
#
# Version bumps on any non-cosmetic change.
version: 1
updated_at: 2026-04-23

entities:
  - slug: brisen-capital-sa
    status: active
    description: "Brisen Capital SA — Geneva holding company, Brisen Group parent."
    aliases: [brisen-capital, bcsa]

  - slug: brisen-development-gmbh
    status: active
    description: "Brisen Development GmbH — Vienna operating company, real estate development."
    aliases: [brisen-development, bdgmbh]

  - slug: aelio-holding-ltd
    status: active
    description: "Aelio Holding Ltd — Cyprus-based investment vehicle linked to Andrey Oskolkov."
    aliases: [aelio, aelios]
```

### Key Constraints

- **Minimal seed — 3 entries only.** Brisen Capital SA, Brisen Development GmbH, Aelio Holding Ltd. All three appear in CLAUDE.md / known matter files as first-class entities.
- **Do NOT seed `aukera`, `mohg`, `citic`, etc.** — those exist in `slugs.yml` as matter-slugs today. Re-taxonomy decision (which slug stays matter vs. moves to entity) is Director-gated §4 #5 and out of scope.
- **`brisen-capital-sa` vs `brisen-development-gmbh`** — distinct legal entities, distinct slugs. Do not conflate.
- **Aliases** must not include the canonical slug itself.

### Verification

1. `python3 -c "import yaml; d = yaml.safe_load(open('vault_scaffolding/v1/entities.yml')); assert d['version'] == 1 and len(d['entities']) == 3"` — no errors.
2. Slug-uniqueness check analogous to people.yml.
3. `grep -c "^  - slug:" vault_scaffolding/v1/entities.yml` → 3.

---

## Files Modified

- NEW directory `vault_scaffolding/v1/`.
- NEW `vault_scaffolding/v1/schema/VAULT.md` (~170 lines).
- NEW `vault_scaffolding/v1/schema/templates/matter.md` (~40 lines).
- NEW `vault_scaffolding/v1/schema/templates/person.md` (~35 lines).
- NEW `vault_scaffolding/v1/schema/templates/entity.md` (~35 lines).
- NEW `vault_scaffolding/v1/people.yml` (~30 lines).
- NEW `vault_scaffolding/v1/entities.yml` (~35 lines).

**Total: 6 new files in baker-master, ~345 lines.**

## Do NOT Touch

- `baker-vault/*` directly — baker-vault writes are Mac Mini's domain (CHANDA #9). B-code has no vault clone; this PR only produces staging artifacts in baker-master. AI Head post-merge copies to vault via SSH.
- `slugs.yml` in baker-vault — v9 is authoritative for matters and this brief does not touch it.
- `kbl/slug_registry.py` — no loader changes in this brief. Follow-on `kbl/people_registry.py` + `kbl/entity_registry.py` briefs ship the loaders.
- `CHANDA.md` / `CHANDA_enforcement.md` — unrelated. No amendment-log entry for this brief (VAULT.md is baker-vault content, not baker-master invariant).
- Any existing `wiki/` content — retrofit is Director-gated follow-on.
- `triggers/embedded_scheduler.py`, `memory/store_back.py`, `models/cortex.py` — unrelated hotspots, avoid.

## Quality Checkpoints

Run in order. Paste literal output in ship report.

1. **YAML frontmatter parses — VAULT.md:**
   ```
   python3 -c "import yaml; raw = open('vault_scaffolding/v1/schema/VAULT.md').read(); fm = raw.split('---')[1]; d = yaml.safe_load(fm); assert d['type'] == 'schema' and d['version'] == 1"
   ```
   Expect: zero output, zero error.

2. **YAML frontmatter parses — 3 templates:**
   ```
   for f in vault_scaffolding/v1/schema/templates/*.md; do
     python3 -c "import yaml, sys; raw = open('$f').read(); fm = raw.split('---')[1]; yaml.safe_load(fm)" || { echo "FAIL: $f"; exit 1; }
   done
   echo "All 3 templates parse OK."
   ```
   Expect: `All 3 templates parse OK.`

3. **Template frontmatter has all 7 required keys:**
   ```
   for f in vault_scaffolding/v1/schema/templates/*.md; do
     n=$(grep -E '^(type|slug|name|updated|author|tags|related):' "$f" | wc -l | tr -d ' ')
     [ "$n" = "7" ] || { echo "FAIL: $f has $n keys, expected 7"; exit 1; }
   done
   echo "All 3 templates have 7 frontmatter keys."
   ```
   Expect: `All 3 templates have 7 frontmatter keys.`

4. **Registry files load + slug uniqueness:**
   ```
   python3 -c "
   import yaml
   for fn, key in [('vault_scaffolding/v1/people.yml', 'people'),
                   ('vault_scaffolding/v1/entities.yml', 'entities')]:
       d = yaml.safe_load(open(fn))
       assert d['version'] == 1, fn
       slugs = [e['slug'] for e in d[key]]
       assert len(slugs) == len(set(slugs)), f'{fn}: duplicate slugs'
       for e in d[key]:
           assert e['slug'] not in e.get('aliases', []), f'{fn}: slug in own aliases ({e[\"slug\"]})'
           assert e['status'] in ('active', 'retired', 'draft'), f'{fn}: bad status'
   print('Registry files valid.')
   "
   ```
   Expect: `Registry files valid.`

5. **VAULT.md structure counts:**
   ```
   grep -c "^## §" vault_scaffolding/v1/schema/VAULT.md   # expect 9
   ```

6. **Directory structure:**
   ```
   find vault_scaffolding -type f | sort
   ```
   Expect 6 files exactly:
   ```
   vault_scaffolding/v1/entities.yml
   vault_scaffolding/v1/people.yml
   vault_scaffolding/v1/schema/VAULT.md
   vault_scaffolding/v1/schema/templates/entity.md
   vault_scaffolding/v1/schema/templates/matter.md
   vault_scaffolding/v1/schema/templates/person.md
   ```

7. **No leaked absolute paths:**
   ```
   grep -rn "/Users/dimitry" vault_scaffolding/ || echo "OK: no absolute paths leaked."
   ```
   Expect: `OK: no absolute paths leaked.`

8. **Markdown syntax smoke** (optional — if `markdownlint` available):
   ```
   markdownlint vault_scaffolding/v1/schema/VAULT.md vault_scaffolding/v1/schema/templates/*.md || true
   ```
   Warnings allowed; errors noted in ship report but not blocking.

9. **Singleton hook still green:**
   ```
   bash scripts/check_singletons.sh
   ```
   Expect: `OK: No singleton violations found.`

10. **Full-suite regression delta:**
    ```
    pytest tests/ 2>&1 | tail -3
    ```
    No test changes in this brief; expected: same `N passed, M failed` as baseline at dispatch time. Record baseline explicitly in ship report.

## Verification SQL

N/A — no DB changes.

## Rollback

- `git revert <merge-sha>` — single-PR revert. No runtime side-effects (nothing loads `vault_scaffolding/*` yet; loaders are follow-on briefs).

---

## Ship shape

- **PR title:** `KBL_SCHEMA_1: Vault schema v1 scaffolding (templates + people.yml + entities.yml + VAULT.md)`
- **Branch:** `kbl-schema-1`
- **Files:** 6 new content files under `vault_scaffolding/v1/`.
- **Commit style:** `kbl(schema-v1): seed vault scaffolding — 3-way taxonomy, 7-field frontmatter, minimal people+entities registries`
- **Ship report:** `briefs/_reports/B{N}_kbl_schema_1_20260423.md`. Include:
  - All 10 Quality Checkpoint outputs (literal).
  - `git diff --stat` showing 6 new files.
  - Explicit line count per file.
  - Confirmation that no baker-vault files were touched by the PR.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Post-merge (AI Head, not B-code)

AI Head post-merge actions (autonomous per charter §3):

1. SSH Mac Mini. Copy scaffolding into baker-vault at canonical paths:
   ```
   ssh macmini
   cd ~/baker-vault
   git pull -q
   # Copy 6 files:
   BM=<path-to-baker-master-clone>/vault_scaffolding/v1
   cp $BM/schema/VAULT.md schema/VAULT.md
   mkdir -p schema/templates
   cp $BM/schema/templates/*.md schema/templates/
   cp $BM/people.yml people.yml
   cp $BM/entities.yml entities.yml
   git add schema/VAULT.md schema/templates/ people.yml entities.yml
   # Commit with Director-signed marker (CHANDA #4 — VAULT.md has author: director):
   git commit -m 'schema(v1): seed 3-way taxonomy, templates, people.yml, entities.yml

   Director-signed: "default recom is fine (2026-04-23)"'
   git push origin main
   ```
2. Verify vault state:
   ```
   ssh macmini "cd ~/baker-vault && ls schema/templates/ && head -10 people.yml && head -10 entities.yml"
   ```
3. Log AI Head action to `actions_log.md` (file path + commit SHA in baker-vault).

## Timebox

**2–2.5h.** If >3.5h, stop and report — content drift or mis-scope.

**Working dir:** assigned by AI Head at dispatch time (whichever Brisen is proven + idle per OPERATING.md "Don't invent lane models").
