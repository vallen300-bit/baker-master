# BRIEF: CORTEX_BOOTSTRAP_MATTER_1 — Generic matter scaffolding generator

**Milestone:** Wave 3 enabler (post-Wave-2 close 2026-04-30)
**Dispatcher:** AI Head A — Tier A (autonomous merge on green)
**Builder:** B4
**Estimated time:** ~5–6h
**Complexity:** Medium
**Prerequisites:** HAGENAUER_WIKI_BOOTSTRAP_1 merged (precedent script `scripts/bootstrap_hagenauer_wiki.py`); Wave 2 close at baker-vault `715a115` (4 fully-wired + 3 recommend_wait matter configs + Director-ratified Project↔Owner GmbH structural map)

---

## Context

Wave 2 closed 2026-04-30 with 4 hand-written cortex-configs: `oskolkov` (fully wired, AO PM absorbed), `hagenauer-rg7`, `nvidia-corinthia`, `movie`, plus 3 recommend_wait stubs (`mrci`, `annaberg`, `mo-vie-exit`). Wave 3 has ≥8 matter candidates queued (`mo-vie-am`, `capital-call`, `franck-muller`, `mo-prague+citic`, `private-assets`, `cap-ferrat`, `lilienmatt`, `aukera`).

Hand-writing each future matter's directory + cortex-config.md takes ~45–60 min (verified Wave 2). The structure is now stable enough that a generator script captures the boilerplate in one file. Director ratified Option 2 (build bootstrap first) on 2026-04-30 in the post-V8 housekeeping window.

**Canonical reference for matter shape:** `wiki/matters/mrci/cortex-config.md` (Wave 2, Director-ratified 2026-04-30). Has the cleanest structure: full frontmatter (incl. `default_specialists`, `auto_trigger`, game-theoretic fields), Project↔Owner GmbH section, ratified Counterparty topology table, Trigger-pattern strictness note, Game-theoretic frame, Bridge-to-other-matters section.

**CHANDA #9 (mac-mini-writer):** Baker NEVER writes `baker-vault/wiki/` directly. Generator stages to `vault_scaffolding/live_mirror/v1/matters/<slug>/`; Mac Mini mirrors via the existing pipeline. Same constraint as `bootstrap_hagenauer_wiki.py`.

---

## Problem

Each new matter (Wave 3+) requires hand-writing 7+ markdown files with consistent frontmatter, structured cortex-config sections, and entity orbit. ~45–60 min/matter × 8 = 6–8h of mechanical work. Mistakes (typo'd slug, missing frontmatter field, divergent section structure) leak into Cortex's per-matter brain.

## Solution

Build **two scripts**:

1. `scripts/bootstrap_matter.py` — given a matter input config (YAML), generate the full `wiki/matters/<slug>/` skeleton: `cortex-config.md`, `_overview.md`, `_index.md`, `agenda.md`, `state.md`, `gold.md`, `proposed-gold.md`, plus empty `curated/` directory.
2. `scripts/bootstrap_entities.py` — given a list of entity slugs + descriptions, append validated rows to `baker-vault/entities.yml`.

Both scripts:
- Stage to `vault_scaffolding/live_mirror/v1/matters/<slug>/` (CHANDA #9)
- Validate every emitted frontmatter via `kbl.ingest_endpoint.validate_frontmatter`
- Are idempotent (default fail-on-exists; `--force` to overwrite)
- Are dry-runnable (`--dry-run` prints intended writes, emits 0 files)
- Default `autonomy_level: recommend_wait` per V8 ratification

---

## Input config schema

Reads a YAML file (one per new matter) at `briefs/_inputs/bootstrap_<slug>.yml`. Schema:

```yaml
matter_slug: capital-call            # required, kebab-case, must NOT exist in baker-vault yet
matter_name: "Capital Call (RG7)"    # required, human-readable
absorbed_from: "seed (Wave 3 ...)"   # required, free-text provenance
absorbed_by: "AI Head A"             # required
authority_chain: "Director ratification 2026-MM-DD..."  # required, free-text
ratified_at: 2026-MM-DD              # required, ISO date

autonomy_level: recommend_wait       # default; alternates: auto_execute, escalate
sense_sources:
  - email: matter_keywords           # list of source:match-strategy pairs
  - whatsapp: contact_phones

entities:
  primary: [<slug>, ...]             # required, ≥1
  team: [<slug>, ...]                # optional
  counterparties: [<slug>, ...]      # required, ≥1
  adjacent: [<slug>, ...]            # optional

trigger_patterns:                    # required, ≥1; raw regex strings
  - '\b(...)\b'

default_specialists: [legal, finance]    # default: [legal, finance, game-theory]
specialist_cap_per_cycle: 5              # default: 5
specialist_timeout_seconds: 60           # default: 60
specialist_retries: 2                    # default: 2
cycle_timeout_seconds: 300               # default: 300

auto_trigger:
  severity_floor: high                   # default: high
  confidence_floor: 0.8                  # default: 0.8

games_relevant: true                     # default: true
counterparty_iteration_horizon: infinite_repeated   # default: infinite_repeated
counterparty_reputation_stake: 8         # default: 8 (1-10)
counterparty_observed_strategy: cooperate_with_constraints   # default: generous_tft

# Optional body sections (free-text markdown — appended after frontmatter)
project_structure: |
  Free-text markdown describing project ↔ owner GmbH ↔ ownership %.
counterparty_topology: |
  Optional markdown table or bullets.
notes: |
  Optional free-text — use for matter-specific context (timeline, value, trigger date).
```

**Validation rules:**
- `matter_slug` rejected if it exists in `baker-vault/wiki/matters/<slug>/` or in `slugs.yml`.
- All entity slugs in `primary`/`team`/`counterparties`/`adjacent` must exist in `entities.yml` OR be passed via a parallel run of `bootstrap_entities.py` (script flags missing slugs but does not auto-create).
- `trigger_patterns` regexes compiled via `re.compile()` — invalid regex fails loud.
- `autonomy_level` ∈ {`auto_execute`, `recommend_wait`, `escalate`}.
- `counterparty_iteration_horizon` ∈ {`one_shot`, `short_finite`, `long_finite`, `infinite_repeated`}.

---

## Output structure (per matter)

```
vault_scaffolding/live_mirror/v1/matters/<slug>/
├── cortex-config.md       ← frontmatter from input + body sections (mrci template)
├── _overview.md           ← scaffold w/ "Core entities" + "Scope notes" sections
├── _index.md              ← stub TOC referencing all .md files in dir
├── agenda.md              ← skeleton (header + [NEEDS_DIRECTOR_CONTENT] marker)
├── state.md               ← skeleton (Cortex state file per architecture §2.1)
├── gold.md                ← skeleton (Director-confirmed insights)
├── proposed-gold.md       ← skeleton (agent-drafted, awaiting ratification)
└── curated/               ← empty directory (Cortex Phase 2 specialist outputs land here)
    └── .gitkeep
```

Every emitted .md file:
- Has VAULT.md §2-compliant frontmatter (`type`, `slug`, `name`, `updated`, `author: agent`, `tags`, `related`).
- Includes `[NEEDS_DIRECTOR_CONTENT]` marker (except `_index.md` and `cortex-config.md` which are populated from the input config).
- Validates against `kbl.ingest_endpoint.validate_frontmatter`.

---

## bootstrap_entities.py scope

Separate script — minimal:

- Reads input YAML at `briefs/_inputs/bootstrap_entities_<batch>.yml` with shape:

  ```yaml
  entities:
    - slug: <kebab-case-slug>
      status: active                  # or: retired, draft
      description: "..."
      aliases: [<alt>, ...]            # optional
  ```

- Validates each row (slug uniqueness vs current `entities.yml`, status enum, description ≥10 chars).
- Appends to `baker-vault/entities.yml` ONLY via staging path `vault_scaffolding/live_mirror/v1/entities.yml.append-batch-<timestamp>.yml` (CHANDA #9 — Mac Mini merges).
- Bumps `version:` field by +1 in the staged file.
- Idempotent: re-running with same batch input fails fast on duplicate slugs.

---

## Files to create

- `scripts/bootstrap_matter.py`
- `scripts/bootstrap_entities.py`
- `tests/test_bootstrap_matter.py`
- `tests/test_bootstrap_entities.py`
- `briefs/_inputs/.gitkeep` (placeholder; actual `bootstrap_*.yml` inputs are per-matter and committed alongside their dispatch)

## Files NOT to touch

- `baker-vault/wiki/matters/*/` directly (CHANDA #9 — staging only).
- `baker-vault/entities.yml` directly (staging only).
- `kbl/ingest_endpoint.py`, `kbl/slug_registry.py` (read-only references).
- Any existing matter config (read-only references for shape extraction).

---

## Architectural decisions (NOT to revisit)

1. **Reference template = `mrci/cortex-config.md`.** Not oskolkov (which has heavy AO-PM-absorbed prompt body). MRCI is Wave-2 ratified canonical scaffold.
2. **Stage-only.** No direct baker-vault writes. Mac Mini owns the mirror commit.
3. **Default `recommend_wait`.** All new matters land in this autonomy bucket; Director gold-comments unlock auto-execute later.
4. **Separate scripts.** `bootstrap_matter.py` and `bootstrap_entities.py` are independent — entities can be added without a new matter, and a matter dispatch may reference pre-existing entities.

## Architectural ambiguity to flag, NOT resolve

The script generates `cortex-config.md` body sections from input free-text markdown blocks. Director may want a stricter schema (e.g., counterparty topology as structured YAML rendered to a table) in V2. **Action:** ship V1 with free-text passthrough; flag in ship report if a structured V2 would have prevented divergence in any test fixture.

---

## Code Brief Standards (mandatory)

- **API version:** Internal Python only. Validate against `kbl.ingest_endpoint.validate_frontmatter` (current as of M0 PR #55, 2026-04-23, no deprecation since).
- **Deprecation check date:** 2026-04-30. No external APIs touched.
- **Fallback:** Idempotent. Re-running on existing staging dir fails with "skeleton exists, pass --force to overwrite". `--force` overwrites all files in the matter dir.
- **DDL drift check:** N/A — no DB writes. Verify by `grep -n "INSERT\|UPDATE\|DELETE\|conn\.\|cursor\.\|execute(" scripts/bootstrap_matter.py scripts/bootstrap_entities.py` returns 0 lines.
- **Migration-vs-bootstrap drift trap:** N/A — no schema. (Lesson: feedback_migration_bootstrap_drift.md applies to DDL only.)
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_bootstrap_matter.py tests/test_bootstrap_entities.py -v` stdout. No "passes by inspection" (per `feedback_no_ship_by_inspection.md`).
- **Worktree:** Build in `~/bm-b4` per worktree map.

## Verification criteria

1. `python scripts/bootstrap_matter.py --dry-run --input briefs/_inputs/bootstrap_capital_call.yml` lists ≥7 files; emits 0.
2. `python scripts/bootstrap_matter.py --input briefs/_inputs/bootstrap_capital_call.yml` emits exactly 7 .md files + `curated/.gitkeep` under the staging path.
3. Re-running step 2 without `--force` fails with clear stderr message and non-zero exit code.
4. Every emitted .md frontmatter passes `kbl.ingest_endpoint.validate_frontmatter` (test asserts this in-process).
5. Invalid input YAML (missing required field, bad regex, wrong enum, duplicate slug) fails fast with specific error messages — covered by ≥5 negative test cases.
6. `bootstrap_entities.py` end-to-end: stages a batch file with version bump, refuses duplicate slugs, accepts new slugs.
7. **Test fixture matter:** Use `capital-call` slug as the canonical test input. Provide `briefs/_inputs/bootstrap_capital_call.yml` populated from V8 Q29 ratification (matter critical priority — this script's first real consumer).
8. Total test count ≥20 between the two test files. All green.

## Ship report requirements

Standard ship report at `briefs/_reports/B4_cortex_bootstrap_matter_1_<YYYYMMDD>.md`:

- Literal pytest stdout.
- Output of `python scripts/bootstrap_matter.py --dry-run --input briefs/_inputs/bootstrap_capital_call.yml` (proves the test fixture works end-to-end).
- Diff summary of staged `vault_scaffolding/live_mirror/v1/matters/capital-call/` after a real run.
- Confirmation: no DB writes (grep result).
- Architectural-ambiguity section: was free-text passthrough sufficient, or did test fixtures show V2 structured-schema is needed?
- Any `feedback_*` lessons that informed the build.

---

## Branch + PR

- Branch: `feature/cortex-bootstrap-matter-1`
- PR title: `CORTEX_BOOTSTRAP_MATTER_1: generic matter scaffolding generator`
- PR body: link to this brief, ship report, deploy verification.
- Tier A — AI Head A merges on green (no Trigger-class match per RA-24).
