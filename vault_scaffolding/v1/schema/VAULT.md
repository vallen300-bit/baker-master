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
