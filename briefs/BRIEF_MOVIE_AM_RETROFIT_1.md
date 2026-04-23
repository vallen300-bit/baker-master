# BRIEF: MOVIE_AM_RETROFIT_1 — Vault-canonical MOVIE AM + learning loop + MOHG tactical addendum

## Context

Promotes ratified `_ops/ideas/2026-04-22-movie-am-retrofit.md` to implementation. Second application of `CAPABILITY_EXTENSION_TEMPLATE`; AO PM extension (`BRIEF_AO_PM_EXTENSION_1`) was first — shipped 2026-04-22. **This brief explicitly mirrors the AO PM structure** to preserve cognitive parity; divergences flagged inline.

**Current state.** MOVIE AM capability is live (123 runs as of 2026-04-22 08:43 UTC — case (d) active growth, NO blocking-gate diagnostic required). 6 view files in `data/movie_am/`, PM_REGISTRY entry at `orchestrator/capability_runner.py:110`, system prompt at `scripts/insert_movie_am_capability.py:23` (SYSTEM_PROMPT literal, 41 lines of content). Signal detector patterns already present (Mario Habicher, Rolf Huebner, Francesco Cefalu, MOHG email domains) — no signal-detector code changes in scope. `baker-vault/wiki/matters/movie/` currently has **only** `cards/2023-05-16-aukera-term-sheet.md` — no `_index.md`, no sub-matters. Gap audit (v3 Part A): (A1) no learning loop, (A2) no episodic memory, (A3) no substrate push, (A4) view files Dropbox-shadowed in `data/movie_am/`.

**Director-ratified architectural decisions merged (Part G, 2026-04-23):**
- Q1: mirror AO PM v3 structure.
- Q2: MOHG tactical — validated 3 candidate lines verbatim as system-prompt addendum (`## ON MOHG DYNAMICS — TACTICAL (MANDATORY)`): unbundle fees into 4 line items / calibrate tone per addressee (Mario / Rolf / Francesco) / operator-obligation precedence.
- Q3: sub-matters expandable.
- Q4: `movie_am_lessons.md` is Layer 2 procedural-memory.
- Q5: **inline stub creation in this brief** (Director overrode Research Agent's seed-coordination recommendation — retrofit does NOT wait for `BRIEF_KBL_SEED_1`).

**Key differences from AO PM extension (flag in each deliverable that deviates):**
- **NO blocking-gate diagnostic.** MOVIE is case (d) active growth (123 runs / 0 days stale) — routing already works.
- **Inline stubs.** MOVIE retrofit creates the full vault skeleton itself (15 new files) since almost no structure exists today. AO PM had more pre-existing layout.
- **Shorter system prompt addendum.** ~450 chars for MOHG vs AO's ~450 (both similar — mandate block + 3 rules).
- **`ingest_vault_matter.py` already supports MOVIE.** Line 30 of that script has `"movie": {"pm_slug": "movie_am", "matter_slugs": ["movie", "rg7"]}` — no code change needed to the ingest script itself. Just `python3 scripts/ingest_vault_matter.py movie` after migration.
- **Shared weekly lint cron.** Do NOT add a second scheduler job; reuse AO PM's lint cron as a multi-PM job (one touch to `triggers/embedded_scheduler.py`).

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites
- `BRIEF_AO_PM_EXTENSION_1` shipped (✓ 2026-04-22) — `_resolve_view_dir` helper + `ingest_vault_matter.py` already in production at `orchestrator/capability_runner.py:1299` and `scripts/ingest_vault_matter.py`.
- `BAKER_VAULT_PATH` env var set on Render (already set per AO PM deploy).
- Vault checkout on Render deploy target — confirmed via AO PM deploy.
- `BRIEF_CAPABILITY_THREADS_1` — soft prereq for full episodic memory. This brief stubs `interactions/` with a README; episodic population deferred until threads brief lands.

## Scope — 5 deliverables

| # | Deliverable | Files touched |
|---|---|---|
| 1 | Vault migration + skeleton creation: 6 `git mv` + 15 new files + 1 README stub | `baker-vault/wiki/matters/movie/**` + delete `data/movie_am/` |
| 2 | Runtime wiring: PM_REGISTRY `view_dir` flip + `view_file_order` update + mandatory `ingest_vault_matter.py movie` one-shot | `orchestrator/capability_runner.py` |
| 3 | System prompt MOHG tactical addendum (3 Director-ratified lines) | `scripts/insert_movie_am_capability.py` (edit SYSTEM_PROMPT literal + rerun) |
| 4 | Learning loop scaffold: `movie_am_lessons.md` with Worked / Didn't-work sections | `baker-vault/wiki/matters/movie/movie_am_lessons.md` (folded into D1 commit) |
| 5 | Extend weekly vault-lint job to cover both AO PM and MOVIE AM (shared cron, one job) | `scripts/lint_movie_am_vault.py` (new) + `triggers/embedded_scheduler.py` (add MOVIE invocation to existing weekly job) |

Substrate Slack push (v3 §A3) and Anthropic Memory-tool pilot (§B2) stay out-of-scope — tracked by AO PM's successor brief (shared with MOVIE).

---

## Deliverable 1 — Vault migration + skeleton creation

### Problem

Six MOVIE AM view files live in `data/movie_am/` under the repo root — Dropbox-shadowed legacy (Dropbox exit ratified 2026-04-19). 3-layer SoT names Obsidian `.md` as L2 primary (ratified 2026-04-22). Director edit authority requires Obsidian-native paths. Further: `baker-vault/wiki/matters/movie/` has almost no skeleton — no `_index.md`, no sub-matters, no Gold shells — so the retrofit must both migrate existing content AND create the full Karpathy 3-layer layout.

### Current state

- `data/movie_am/` contains **6 files** (verified by `ls`): `SCHEMA.md`, `agenda.md`, `agreements_framework.md`, `kpi_framework.md`, `operator_dynamics.md`, `owner_obligations.md`.
- `baker-vault/wiki/matters/movie/` contains **1 file**: `cards/2023-05-16-aukera-term-sheet.md`. No `_index.md`, no `sub-matters/`, no `decisions/`, no Gold shells.
- `baker-vault` is a separate git repo at `/Users/dimitry/baker-vault/` (MacBook) mirrored at `/opt/render/project/src/baker-vault-mirror` (Render).

### Implementation

**Step 1.1 — Migrate 6 files** (run from `~/baker-vault/`, rename underscore → hyphen to match wikilink convention):

```bash
cd ~/baker-vault
mkdir -p wiki/matters/movie/sub-matters
mkdir -p wiki/matters/movie/interactions
mkdir -p wiki/matters/movie/decisions

# From baker-master repo root:
cd ~/Desktop/baker-code
cp data/movie_am/SCHEMA.md              ~/baker-vault/wiki/matters/movie/_schema-legacy.md
cp data/movie_am/agreements_framework.md ~/baker-vault/wiki/matters/movie/agreements-framework.md
cp data/movie_am/operator_dynamics.md   ~/baker-vault/wiki/matters/movie/operator-dynamics.md
cp data/movie_am/kpi_framework.md       ~/baker-vault/wiki/matters/movie/kpi-framework.md
cp data/movie_am/owner_obligations.md   ~/baker-vault/wiki/matters/movie/owner-obligations.md
cp data/movie_am/agenda.md              ~/baker-vault/wiki/matters/movie/agenda.md
```

After copies land, **prepend frontmatter** to each migrated file (template below — edit per file so `title` reflects content). Template:

```
---
title: <file title>
matter: movie
type: <semantic|reference>   # use 'semantic' for knowledge frameworks; 'reference' for agenda
layer: 2
last_audit: 2026-04-23
owner: AI Head + Director
---
```

**Step 1.2 — Create 15 new files.** All new files live in `baker-vault/wiki/matters/movie/`. Full layout:

| File | Purpose | Initial content |
|---|---|---|
| `_index.md` | Hub file — describes View Files table, sub-matters, Gold pipeline, matter description | See Step 1.3 below (template) |
| `_overview.md` | Asset summary: property name, opening, rooms, owner-operator dynamic | Placeholder: property facts from `INITIAL_STATE` in `insert_movie_am_capability.py` |
| `red-flags.md` | Active red flags (state snapshot + narrative) | Empty scaffold |
| `financial-facts.md` | Stable structural facts — HMA fee structure, FF&E reserve %, base vs incentive fee terms | Empty scaffold |
| `mohg-dynamics.md` | Counterparty tactical — Director-validated Part G MOHG lines (3 verbatim) | See Step 1.4 (verbatim copy of Part G Q2 lines) |
| `sub-matters/hma-compliance.md` | HMA agreement compliance tracking | Empty scaffold |
| `sub-matters/kpi-monitoring.md` | Monthly variance tracking | Empty scaffold |
| `sub-matters/owner-approvals.md` | Pending Owner approvals pipeline | Empty scaffold |
| `sub-matters/warranty-windows.md` | Time-bound claims | Empty scaffold |
| `sub-matters/ffe-reserve.md` | Reserve account management | Empty scaffold |
| `sub-matters/budget-review.md` | Annual budget cycle | Empty scaffold |
| `interactions/README.md` | Stub explaining episodic memory (populated after `BRIEF_CAPABILITY_THREADS_1` ships) | See Step 1.5 |
| `decisions/.gitkeep` | Empty dir placeholder — decisions append-only log | Empty file |
| `gold.md` | Director Gold — high-confidence ratified positions | Empty scaffold with §Gold/§Candidates headers |
| `proposed-gold.md` | Capability-proposed Gold (pre-ratification) | Empty scaffold |
| `movie_am_lessons.md` | **Deliverable 4 output — folded into this commit.** Layer 2 procedural-memory | See Deliverable 4 |

**Empty scaffold template** (use for the 9 files marked "Empty scaffold" above — adjust `title` + `type`):

```
---
title: <title>
matter: movie
type: <semantic|procedural-memory|reference|state>
layer: 2
last_audit: 2026-04-23
owner: AI Head + Director
status: scaffold
---

# <title>

<one-line purpose statement>

---

## Content

_(populated as intelligence accumulates; Director edits directly in Obsidian)_
```

**Step 1.3 — `_index.md` template** (the hub file; mirror AO PM's `_index.md` structure at `~/baker-vault/wiki/matters/oskolkov/_index.md`):

```markdown
---
title: MOVIE (Mandarin Oriental, Vienna) — Matter Index
matter: movie
type: index
layer: 2
last_audit: 2026-04-23
owner: AI Head + Director
---

# MOVIE — Mandarin Oriental, Vienna

Baker's MOVIE AM capability. Asset: Mandarin Oriental Vienna (MOHG-operated). Owner: Brisen Group. Entangled matter: `rg7` (Riemergasse 7).

## View Files (read at PM invocation per `view_file_order`)

| Order | File | Purpose |
|---|---|---|
| 1 | `_index.md` | This hub |
| 2 | `_overview.md` | Asset summary + owner-operator dynamic |
| 3 | `agreements-framework.md` | HMA clause taxonomy |
| 4 | `operator-dynamics.md` | MOHG personnel + behaviour patterns |
| 5 | `kpi-framework.md` | Occupancy / ADR / RevPAR / GOP framework |
| 6 | `owner-obligations.md` | Owner-side obligations catalog |
| 7 | `agenda.md` | Current agenda items |
| 8 | `red-flags.md` | Active red flags |
| 9 | `financial-facts.md` | Stable fee structure + reserve terms |
| 10 | `mohg-dynamics.md` | Counterparty tactical (Part G validated) |

## Sub-matters (loaded on demand when flagged active in `pm_project_state.state_json.sub_matters`)

- [[sub-matters/hma-compliance]]
- [[sub-matters/kpi-monitoring]]
- [[sub-matters/owner-approvals]]
- [[sub-matters/warranty-windows]]
- [[sub-matters/ffe-reserve]]
- [[sub-matters/budget-review]]

## Memory layers

- **Layer 1 (live state)** — Postgres `pm_project_state` WHERE `pm_slug='movie_am'`
- **Layer 2 (distilled knowledge)** — files in this directory
- **Layer 3 (raw signals)** — Postgres `email_messages` / `meeting_transcripts` / `documents`

## Learning loop

- [[movie_am_lessons.md]] — Layer 2 procedural-memory (Silver → promotion)
- `baker_corrections` table — Silver corrections
- [[gold.md]] — Director Gold
- [[proposed-gold.md]] — capability-proposed Gold (awaiting Director ratify)

## Entangled matters

- `rg7` — Riemergasse 7 (shared MOVIE matter_slugs = ["movie", "rg7"])
```

**Step 1.4 — `mohg-dynamics.md` initial content** (verbatim from Part G Q2 ratified lines — keep identical to the system-prompt addendum so Director sees one source of truth in Obsidian):

```markdown
---
title: MOHG Dynamics — Counterparty Tactical
matter: movie
type: procedural-memory
layer: 2
last_audit: 2026-04-23
owner: AI Head + Director
status: ratified
---

# MOHG Dynamics — Counterparty Tactical

Director-validated counterparty-behavior intelligence for MOHG (Mandarin Oriental Hotel Group) as MOVIE's operator under the HMA suite. Ratified 2026-04-23 per `_ops/ideas/2026-04-22-movie-am-retrofit.md` Part G Q2.

## Tactical rules (MANDATORY — mirrored in capability system prompt)

1. **Unbundle fees before engaging.** Every fee discussion decomposes into 4 line items — base / incentive / FF&E / centralized services — before responding to MOHG's bundled position.
2. **Calibrate tone per addressee.**
   - **Mario Habicher** — operational, data-responsive. Lead with numbers; minimal narrative.
   - **Rolf Huebner** — commercial, push-back. Anticipate contestation; present ranges + anchors.
   - **Francesco Cefalu** — relationship-layer. Frame asks as continuations of prior dialogue; preserve relational capital.
3. **Operator-obligation precedence.** When both Operator obligations and Owner obligations are active in a dispute, surface the Operator-obligation push first; respond to Owner-obligation challenges second.

## Why these three

Director validated 2026-04-23 after Research Agent surfaced candidate patterns from MOVIE interaction history (Mario/Rolf/Francesco observed tone differentials; recurring fee bundling in MOHG correspondence; consistent Owner-obligation-first framing in disputes).

## Escalation

When a tactical rule conflicts with a specific instruction, escalate to Director (T1). Rules are defaults, not overrides.
```

**Step 1.5 — `interactions/README.md` stub:**

```markdown
---
title: MOVIE Interactions — Episodic Memory (stub)
matter: movie
type: reference
layer: 2
last_audit: 2026-04-23
owner: AI Head + Director
status: pending-BRIEF_CAPABILITY_THREADS_1
---

# MOVIE Interactions — Episodic Memory (stub)

Post-`BRIEF_CAPABILITY_THREADS_1` this directory will hold one file per significant touchpoint:

- Owner-operator calls (MOHG, Mario / Rolf / Francesco)
- Quarterly budget reviews
- Warranty-window correspondence
- Board KPI deviation reports

Filename convention: `YYYY-MM-DD-<source>.md` (e.g. `2026-03-01-owner-operator-call.md`).

Frontmatter template (to be used once threads brief lands):

\`\`\`
---
title: <one-line summary>
matter: movie
type: episodic
layer: 2
date: YYYY-MM-DD
source: <email | meeting | call | whatsapp | report>
participants: [<names>]
---
\`\`\`

Until then, this README is the placeholder.
```

**Step 1.6 — Commit to baker-vault:**

```bash
cd ~/baker-vault
git add wiki/matters/movie/
git status  # expect: 6 migrated + 15 new + interactions/README.md (= 22 paths including _schema-legacy.md and .gitkeep)
git commit -m "movie: vault migration + skeleton (BRIEF_MOVIE_AM_RETROFIT_1 D1)

6 file migration from data/movie_am/ + 15 new files + interactions/README
stub. Part G ratified 2026-04-23; inline stubs per Q5 (not KBL_SEED_1).

Paper trail:
- Research artefact: _ops/ideas/2026-04-22-movie-am-retrofit.md
- MOHG tactical addendum: Part G Q2 three lines verbatim.
- Sub-matters expandable: Part G Q3.
- movie_am_lessons.md Layer 2 procedural-memory: Part G Q4.
"
git pull --rebase && git push
```

**Step 1.7 — Delete `data/movie_am/` from baker-master** (separate commit, after Deliverable 2 PM_REGISTRY flip is tested in Deliverable 2):

```bash
cd ~/Desktop/baker-code
git rm -r data/movie_am/
```

Do NOT commit Step 1.7 until Deliverable 2 is merged — the `data/` dir is a safety net until PM_REGISTRY flip is verified working. Sequencing: D2 merges → verify wiki_pages populated → then D1.7 commits.

### Key constraints

- **Keep `SCHEMA.md` under a renamed filename (`_schema-legacy.md`).** `ingest_vault_matter.py:33` explicitly skips `_schema-legacy.md` during re-ingest — intentional (SCHEMA.md content is legacy; `_index.md` replaces its role). Do NOT delete SCHEMA content outright — rename preserves historical artifact.
- **Frontmatter is MANDATORY** on every migrated + new `.md`. Ingest script reads `title:` and section headers (`scripts/ingest_vault_matter.py:464-470`). Missing frontmatter → stale `title` from filename stem.
- **Wikilinks must resolve.** Every `[[sub-matters/hma-compliance]]`-style link needs the target file to exist. Creating all 15 files in one commit (not trickle-creation) prevents broken-link linting later.
- **15 new files are stubs, not filled content.** Director fills content in Obsidian post-merge. Acceptable to ship stubs; lint (D5) flags rules missing key sections.
- **No signal-detector change.** `pm_signal_detector.py` already has MOVIE patterns in PM_REGISTRY (lines 136-159). This brief does not touch signal detector — verified.
- **`matter_slugs` = `["movie", "rg7"]`** for all ingested pages. Already the default in `ingest_vault_matter.py:30`.

### Verification

After Step 1.6 commit lands on vault main:

```bash
cd ~/baker-vault
find wiki/matters/movie -type f -name "*.md" | wc -l
# expect: 21 (6 migrated + 15 new top/sub + 1 interactions README + 1 existing cards/aukera = 23 total; script file count = 21 md excluding .gitkeep)
grep -l "^matter: movie" wiki/matters/movie/*.md wiki/matters/movie/sub-matters/*.md | wc -l
# expect: ≥ 17 top-level + 6 sub-matter = 23 files with frontmatter; off-by-one ok for cards
```

Director smoke-test in Obsidian: `cmd+p` → `_index` → opens file → all wikilinks resolve.

---

## Deliverable 2 — Runtime wiring

### Problem

PM_REGISTRY["movie_am"].view_dir currently points at `data/movie_am/` (legacy). Runtime `_load_pm_view_files` uses `_resolve_view_dir` at `orchestrator/capability_runner.py:1341`. A flip without wiki_pages re-ingest is a silent no-op (ingest runs at startup via `_seed_wiki_from_view_files` — stale Postgres content wins over fresh vault reads). AI Head #2 caught this on AO PM; same trap applies here.

### Current state

- PM_REGISTRY["movie_am"] at `orchestrator/capability_runner.py:110`:
  - `view_dir: "data/movie_am"` (legacy) — **flip to `"wiki/matters/movie"`**
  - `view_file_order`: 6 filenames with underscores — **update to vault filenames with hyphens + 4 new files**
- `_resolve_view_dir` helper at line 1299 — already handles `wiki/` prefix (delivered by AO PM extension). No code change to helper.
- `scripts/ingest_vault_matter.py` already lists `"movie"` in `MATTER_CONFIG` (line 30). No edit to that script.
- 6 `wiki_pages` rows exist for `agent_owner='movie_am'` (per Research Agent Part E2.1) — these need to be wiped and re-inserted with fresh vault content. The ingest script handles the DELETE + INSERT atomically.

### Implementation

**Step 2.1 — Edit `orchestrator/capability_runner.py` PM_REGISTRY["movie_am"]:**

Change `view_dir` from `"data/movie_am"` to `"wiki/matters/movie"`. Change `view_file_order` to match the vault filename convention (hyphens, include new files):

```python
    "movie_am": {
        "registry_version": 1,
        "name": "MOVIE Asset Manager",
        "view_dir": "wiki/matters/movie",
        "view_file_order": [
            "_index.md",
            "_overview.md",
            "agreements-framework.md",
            "operator-dynamics.md",
            "kpi-framework.md",
            "owner-obligations.md",
            "agenda.md",
            "red-flags.md",
            "financial-facts.md",
            "mohg-dynamics.md",
        ],
        # ... rest of entry UNCHANGED (state_label, briefing_priority, contact_keywords,
        # entangled_matters, peer_pms, media_folder, briefing_section_title,
        # briefing_email_patterns, briefing_whatsapp_patterns,
        # briefing_deadline_patterns, briefing_state_key, soul_md_keywords,
        # signal_orbit_patterns, signal_keyword_patterns, signal_whatsapp_senders,
        # etc.)
    },
```

**Step 2.2 — Verify `_resolve_view_dir` still works** for the `wiki/` prefix (sanity check — no change required):

```bash
cd ~/Desktop/baker-code
python3 -c "
import os
os.environ.setdefault('BAKER_VAULT_PATH', os.path.expanduser('~/baker-vault'))
from orchestrator.capability_runner import CapabilityRunner
r = CapabilityRunner.__new__(CapabilityRunner)
print(r._resolve_view_dir('wiki/matters/movie'))
"
# expect: /Users/dimitry/baker-vault/wiki/matters/movie
```

**Step 2.3 — Syntax + smoke tests.** Before deploy:

```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
# expect: no output

# Run existing AO PM regression tests to confirm no cross-capability breakage:
pytest tests/ -k "pm_registry or capability_runner or resolve_view_dir" -v
# expect: all pass
```

**Step 2.4 — One-shot wiki_pages re-ingest** (MANDATORY — runs once after Render deploy lands):

```bash
# On Render shell (or local with BAKER_VAULT_PATH=~/baker-vault):
python3 scripts/ingest_vault_matter.py movie
# expected console: "Deleted N stale rows for movie_am / Inserted M fresh rows for movie_am"
# expect M ≥ 10 top-level + 6 sub-matter = 16 rows inserted
```

### Key constraints

- **`view_file_order` must list exact filenames** present in `baker-vault/wiki/matters/movie/`. Typo → `_load_pm_view_files` silently skips the missing file (logger.warning only). Mismatch hard-to-notice.
- **PM_REGISTRY edit is ONE dict literal** — do NOT reformat surrounding entries. Surgical edit per Principle 3.
- **`ingest_vault_matter.py` is not changed.** Only the run. If the run fails (e.g., vault checkout missing on Render), Deliverable 2 is not complete.
- **Sub-matter loader** (`_load_pm_view_files` lines 1346-1400s) already handles sub-matters via `state_json.sub_matters` flags. No code change — this deliverable only flips the directory.
- **`ingest_vault_matter.py` DELETE is matter-scoped** (`WHERE agent_owner = 'movie_am' AND page_type = 'agent_knowledge'`) — does NOT touch AO PM rows or any other capability's rows. Rollback in except already present (line 437).
- **Post-ingest**: run `scripts/ingest_vault_matter.py movie` a second time. Expected: same row count, no errors — idempotency confirmation.

### Verification

```sql
-- Verify wiki_pages populated for movie_am
SELECT slug, title, page_type, matter_slugs,
       LEFT(content, 80) AS content_head,
       updated_at
FROM wiki_pages
WHERE agent_owner = 'movie_am' AND page_type = 'agent_knowledge'
ORDER BY slug
LIMIT 25;
-- expect: ≥ 16 rows, all with matter_slugs = '{movie,rg7}', updated_at recent,
-- updated_by='ingest_vault_matter'

-- Verify no orphan old rows
SELECT COUNT(*) AS old_rows
FROM wiki_pages
WHERE agent_owner = 'movie_am'
  AND page_type = 'agent_knowledge'
  AND updated_by != 'ingest_vault_matter'
LIMIT 1;
-- expect: 0
```

Runtime smoke (Director or AI Head): invoke MOVIE AM with a MOHG-adjacent prompt → confirm `_load_wiki_context` returns rows (logger INFO `wiki pages loaded for movie_am: N`).

---

## Deliverable 3 — System prompt MOHG tactical addendum

### Problem

Per Part G Q2 ratified 2026-04-23: 3 MOHG tactical lines validated as system-prompt MANDATORY section. Current `SYSTEM_PROMPT` literal at `scripts/insert_movie_am_capability.py:23` lacks this section. Addendum arms MOVIE AM's output with operator-behavioral calibration — same pattern as AO PM's "ON DATES AND TIMESTAMPS".

### Current state

- `capability_sets.system_prompt` for slug `movie_am` set by `scripts/insert_movie_am_capability.py` (`SYSTEM_PROMPT` literal, line 23-63).
- Script is idempotent — UPDATEs existing row when re-run (line 129-147 approx.; same pattern as `insert_ao_pm_capability.py`).
- Current prompt ends at the `## RULES` section (line 56-62). Addendum goes AFTER rules, before closing `"""`.

### Implementation

**Step 3.1 — Edit `scripts/insert_movie_am_capability.py`.** Append this block to the `SYSTEM_PROMPT = """…"""` literal (before the closing triple-quote at line 63):

```

## ON MOHG DYNAMICS — TACTICAL (MANDATORY)
MOHG as MOVIE's operator shows recurrent behavioral patterns. Director has
validated these three rules (2026-04-23). Apply them by default; escalate
conflicts to Director.

- Unbundle MOHG fee discussions into four line items (base / incentive / FF&E /
  centralized services) before engaging their bundled position.
- Calibrate tone per addressee: Mario Habicher (operational, data-responsive),
  Rolf Huebner (commercial, push-back), Francesco Cefalu (relationship-layer).
- Operator-obligation pushes precede Owner-obligation challenges when both are
  active in a dispute.
```

**Step 3.2 — Idempotency check** — grep post-edit:

```bash
grep -c "ON MOHG DYNAMICS" scripts/insert_movie_am_capability.py
# expect: 1
```

The insert script sets `system_prompt` column to the entire literal each run, so re-runs won't duplicate as long as the literal contains exactly one copy.

**Step 3.3 — Syntax check + run the insert script** against prod DB:

```bash
python3 -c "import py_compile; py_compile.compile('scripts/insert_movie_am_capability.py', doraise=True)"
python3 scripts/insert_movie_am_capability.py
# expected console: "movie_am already exists — updating system_prompt and tools" (or equivalent per the script's output pattern)
```

### Key constraints

- **No separate update script.** Reuse `insert_movie_am_capability.py` per the existing idempotency pattern (matches AO PM's Deliverable 3).
- **Append only.** Do not restructure the existing prompt — keep MANDATE / PERSONALITY / WHAT YOU KNOW / WHAT YOU DO / ESCALATION TIERS / RULES sections identical.
- **Wording is verbatim from Part G Q2 + minor prose sentence-structure.** Three tactical lines are the ratified content. Do NOT paraphrase.
- **No DB migration.** `capability_sets.system_prompt` column already exists (TEXT). Just UPDATE.

### Verification

```sql
SELECT POSITION('ON MOHG DYNAMICS' IN system_prompt) > 0 AS addendum_present,
       POSITION('Mario Habicher' IN system_prompt) > 0 AS mario_present,
       POSITION('Francesco Cefalu' IN system_prompt) > 0 AS francesco_present,
       LENGTH(system_prompt) AS prompt_len
FROM capability_sets WHERE slug = 'movie_am' LIMIT 1;
-- expect: all true, prompt_len increased by ~500 chars (from ~2118 → ~2600)
```

Director-run smoke test (informal): MOVIE scan with a MOHG-fees question should surface unbundled 4-line-item response.

---

## Deliverable 4 — Learning loop scaffold (`movie_am_lessons.md`)

### Problem

Per Part G Q4 ratified 2026-04-23: `movie_am_lessons.md` sits as Layer 2 procedural-memory between Silver (`baker_corrections` rows) and Gold (`gold.md`). Currently no file exists; no promotion pipeline. Brief lands the structure; lint (D5) enforces retention/retirement.

### Current state

- `baker_corrections` table exists, populated via `store.store_correction(...)`, retrieved via `get_relevant_corrections(capability_slug, limit=3)` — already populated for capabilities including `movie_am`.
- No `movie_am_lessons.md` exists.

### Implementation

**Fold into Deliverable 1's vault commit.** Create `baker-vault/wiki/matters/movie/movie_am_lessons.md`:

```markdown
---
title: MOVIE AM Lessons
matter: movie
type: procedural-memory
layer: 2
live_state_refs: []
owner: AI Head + Director
last_audit: 2026-04-23
status: scaffold
---

# MOVIE AM Lessons

Consolidated process learnings for MOVIE AM. Sits between Silver (`baker_corrections` rows) and Gold (`gold.md`).

**Promotion rule:** a `baker_corrections` row that fires 3+ times (via `retrieval_count`) is a candidate for promotion here. AI Head reviews weekly via lint output (`_lint-report.md`).

**Demotion rule:** a lesson not referenced in 60+ days is a candidate for retirement. Lint flags.

---

## Worked — why

_(add rules here when a pattern is positively observed and ratified by Director. Format: short imperative rule + one-line why)_

---

## Didn't work — why

_(add rules here when an approach fails repeatedly. Format: short rule + one-line why)_

---

## Pending review (auto-promoted candidates)

_(weekly lint populates this section from `baker_corrections` rows meeting the promotion rule)_
```

### Key constraints

- **Layer 2 procedural-memory.** Keep the frontmatter `type: procedural-memory` per Part G Q4 — this is how ingest + lint distinguish from semantic knowledge.
- **Scaffold only.** Brief does not populate Worked/Didn't-work content — Director adds lessons over time.
- **Promotion/demotion logic lives in D5's lint**, not in runtime code.

### Verification

- File exists: `ls baker-vault/wiki/matters/movie/movie_am_lessons.md`
- Frontmatter correct: `grep -E "^type: procedural-memory" baker-vault/wiki/matters/movie/movie_am_lessons.md`
- Wikilink from `_index.md`: `grep -E "movie_am_lessons" baker-vault/wiki/matters/movie/_index.md`
- Ingest picks it up: `SELECT title FROM wiki_pages WHERE slug = 'movie_am/movie-am-lessons' LIMIT 1` returns the title.

---

## Deliverable 5 — Weekly vault lint (extend AO PM's shared job)

### Problem

Per Part F sequencing: "Weekly lint cron (shared with AO PM's cron — one job, two PMs)." AO PM extension shipped a weekly vault-lint scheduler job. This brief extends that same job to include MOVIE — one scheduler registration, two invocations.

### Current state

- AO PM's `scripts/lint_ao_pm_vault.py` exists (delivered by `BRIEF_AO_PM_EXTENSION_1` D5).
- AO PM's scheduler registration lives in `triggers/embedded_scheduler.py` under an `ao_pm_lint` job ID on Sunday 06:00 UTC.
- MOVIE-specific lint rules per Research Agent Part B1:
  - Flag Layer-2 files duplicating Layer-1 KPIs (stale occupancy % in `kpi-framework.md`)
  - Flag broken wikilinks to missing files
  - Flag `movie_am_lessons.md` rules not hit in 60 days
  - Flag `interactions/` files missing 4 required timestamps
  - **MOVIE-specific:** flag HMA clause citations that don't resolve to agreement document IDs (83200-83206)

### Implementation

**Step 5.1 — Create `scripts/lint_movie_am_vault.py`** mirroring `scripts/lint_ao_pm_vault.py`. The MOVIE-specific HMA clause check is the key departure:

```python
"""Weekly lint for MOVIE AM vault.

Mirrors scripts/lint_ao_pm_vault.py patterns. Additional MOVIE-specific
check: HMA clause citations in wiki/matters/movie/*.md must resolve to
document IDs 83200-83206 (HMA suite).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse the shared helpers from lint_ao_pm_vault if it exposes them; otherwise
# duplicate the minimal logic locally. Keep this script ≤ 200 lines.

# <full implementation: follow lint_ao_pm_vault.py structure exactly;
#  add _check_hma_clause_citations() that greps `\bclause\s+\d+\.\d+\b` in
#  agreements-framework.md + mohg-dynamics.md and verifies each cited clause
#  maps to at least one document row in documents table WHERE id BETWEEN
#  83200 AND 83206>
```

**B3 task note:** read `scripts/lint_ao_pm_vault.py` first. If it exposes reusable helpers (file scanners, stale-rule detectors, wikilink resolvers) via `from scripts.lint_ao_pm_vault import _foo, _bar`, import them. If not, extract shared helpers into `scripts/_vault_lint_common.py` (new) and update both scripts to import from there — refactor is in scope because it removes duplication introduced by this brief.

**Step 5.2 — Extend scheduler.** Edit `triggers/embedded_scheduler.py`:

- Locate the existing `ao_pm_lint` APScheduler registration (look for `id="ao_pm_lint"` around line 232 per grep of existing scheduler file).
- Either (a) add a second registration block for `movie_am_lint` on the SAME Sunday 06:00 UTC cron — OR (b) rename the AO PM job wrapper to invoke both lints sequentially inside one job. **Recommendation: (a) separate jobs** so a MOVIE lint failure doesn't mask AO PM lint or vice versa. Both jobs can share `misfire_grace_time` + `coalesce` settings.

Registration template (copy the AO PM block structure, change identifiers):

```python
    # BRIEF_MOVIE_AM_RETROFIT_1 Deliverable 5: Weekly MOVIE AM vault lint.
    _movie_lint_enabled = _os.environ.get("MOVIE_AM_LINT_ENABLED", "true").lower()
    if _movie_lint_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _run_movie_am_lint,
            CronTrigger(day_of_week="sun", hour=6, minute=5, timezone="UTC"),
            id="movie_am_lint",
            name="MOVIE AM weekly vault lint (Sunday 06:05 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: movie_am_lint (Sun 06:05 UTC)")
    else:
        logger.info("Skipped: movie_am_lint (MOVIE_AM_LINT_ENABLED=false)")
```

Note **minute=5** (not 0) — offset from AO PM job by 5 minutes to avoid contention on the vault mirror pull / any shared resource.

Add the wrapper adjacent to `_run_ao_pm_lint` (actual function name at `triggers/embedded_scheduler.py:785`; the `ao_pm_lint` job at line 233 invokes it):

```python
def _run_movie_am_lint():
    """APScheduler wrapper: Sunday MOVIE AM vault lint.

    BRIEF_MOVIE_AM_RETROFIT_1 D5. Non-fatal — log failures, don't propagate.
    Mirror of `_run_ao_pm_lint` pattern at triggers/embedded_scheduler.py:785.
    """
    try:
        from scripts.lint_movie_am_vault import main as _lint_main
    except Exception as e:
        logger.error("movie_am_lint: import failed: %s", e)
        return
    try:
        _lint_main()
    except Exception as e:
        logger.warning("movie_am_lint: run raised: %s", e)
```

Also update the scheduler registration block above to reference `_run_movie_am_lint` (not `_movie_am_lint_job`) in `scheduler.add_job(`.

**Step 5.3 — Ship gate: pytest for lint.**

Create `tests/test_lint_movie_am_vault.py` — no AO PM lint test exists as of 2026-04-23, so build fresh (minimum 3 tests). Pattern to follow: any existing `tests/test_lint_*.py` OR `tests/test_*_vault.py`; if none match, follow the AI Head audit test pattern at `tests/test_ai_head_weekly_audit.py` (uses `sys.modules` injection for mocked deps):

1. Module imports cleanly + `_movie_am_lint_job` is registerable
2. Lint on a known-good vault snapshot produces zero flags
3. Lint on a vault with an unresolved wikilink produces a flag

### Key constraints

- **Separate scheduler job, not bundled.** Keeps observability clean — one failing lint doesn't hide the other.
- **Env gate `MOVIE_AM_LINT_ENABLED`** — kill-switch without redeploy.
- **No hard dependency on `lint_ao_pm_vault.py` internals.** If B3 extracts shared helpers into a third file, AO PM lint must still work — ship-gate for AO PM lint must re-run green.
- **`misfire_grace_time=3600`** — weekly jobs tolerate an hour of Render restart overlap.
- **HMA clause check is MOVIE-specific.** Do not try to generalize into AO PM's lint — AO has no HMA clauses.

### Verification

- Grep Render logs post-deploy: `Registered: movie_am_lint (Sun 06:05 UTC)` present.
- Manual trigger smoke test (optional): `python3 scripts/lint_movie_am_vault.py` produces a report in `baker-vault/wiki/matters/movie/_lint-report.md` (or whatever convention AO PM's lint follows — match it).
- pytest green on `tests/test_lint_movie_am_vault.py`.
- AO PM lint regression green: `pytest tests/ -k "ao_pm" -v` (no dedicated AO lint test file exists as of 2026-04-23; capture whatever tests touch AO PM in the regression).

---

## Files Modified

- `orchestrator/capability_runner.py` — PM_REGISTRY["movie_am"] `view_dir` flip + `view_file_order` update (Deliverable 2)
- `scripts/insert_movie_am_capability.py` — SYSTEM_PROMPT literal appended with MOHG addendum + rerun (Deliverable 3)
- `triggers/embedded_scheduler.py` — add `movie_am_lint` registration + `_movie_am_lint_job` wrapper (Deliverable 5)
- NEW `scripts/lint_movie_am_vault.py` (Deliverable 5)
- NEW `tests/test_lint_movie_am_vault.py` (Deliverable 5 ship gate)
- `data/movie_am/` — **DELETED** in follow-up commit after Deliverable 2 verified (Step 1.7)

Vault changes (baker-vault repo):
- NEW 15 files + 6 `git mv`-equivalent `cp`+rename + frontmatter prepend (Deliverable 1)
- NEW `movie_am_lessons.md` (folded into D1 commit; Deliverable 4)

## Do NOT Touch

- `orchestrator/pm_signal_detector.py` — MOVIE patterns already present + working (case (d) active growth proves it). Zero changes.
- `scripts/ingest_vault_matter.py` — already supports `"movie"` matter slug (line 30). Do not edit.
- `scripts/insert_ao_pm_capability.py` — AO PM system prompt untouched.
- `orchestrator/capability_runner.py` PM_REGISTRY entries OTHER than `movie_am` — surgical edit.
- `_resolve_view_dir` helper — already generalized by AO PM extension. Zero changes.
- `baker-vault/wiki/matters/oskolkov/` — AO PM vault untouched.
- `baker-vault/wiki/matters/movie/cards/2023-05-16-aukera-term-sheet.md` — existing card stays in place, no edit.

## Quality Checkpoints

1. **PM_REGISTRY flip verified.** `grep -A 10 '"movie_am":' orchestrator/capability_runner.py | grep 'view_dir'` → `"wiki/matters/movie"`.
2. **`wiki_pages` has fresh `movie_am` rows.** 16+ rows, all `updated_by='ingest_vault_matter'`, `matter_slugs='{movie,rg7}'`.
3. **System prompt updated.** SQL verification query (D3) returns `addendum_present=true, mario_present=true, francesco_present=true, prompt_len` increased.
4. **Mobile rendering of any Director-read artifact** (not applicable — no Slack push in this brief; defer substrate push to follow-on).
5. **Weekly lint job registered on Render.** Log line `Registered: movie_am_lint (Sun 06:05 UTC)`.
6. **AO PM regression.** No existing AO PM behavior changed; AO PM lint + capability runs green.
7. **`data/movie_am/` deletion** committed only AFTER D2 is verified in prod.
8. **Director smoke-test.** A MOHG-adjacent scan produces output that exhibits all 3 tactical rules (unbundled fees, calibrated tone, operator-obligation precedence).

## Verification SQL

```sql
-- Confirm wiki_pages populated
SELECT COUNT(*) AS movie_pages
FROM wiki_pages
WHERE agent_owner = 'movie_am' AND page_type = 'agent_knowledge'
  AND updated_by = 'ingest_vault_matter'
LIMIT 1;
-- expect: ≥ 16

-- Confirm system prompt updated
SELECT LENGTH(system_prompt) AS prompt_len,
       POSITION('ON MOHG DYNAMICS' IN system_prompt) > 0 AS has_mohg,
       POSITION('Mario Habicher' IN system_prompt) > 0 AS has_mario
FROM capability_sets WHERE slug = 'movie_am' LIMIT 1;

-- Confirm pm_project_state still reachable
SELECT state_json->'kpi_snapshot' AS kpis,
       state_json->'open_approvals' AS approvals
FROM pm_project_state WHERE pm_slug = 'movie_am' LIMIT 1;
```

## Ship Gate (literal pytest output required in CODE_3_RETURN.md)

```bash
cd ~/bm-b3
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('scripts/insert_movie_am_capability.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('scripts/lint_movie_am_vault.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('tests/test_lint_movie_am_vault.py', doraise=True)"

pytest tests/test_lint_movie_am_vault.py -v
# expect: ≥ 3 passed, 0 failures — paste literal output

# Regression: AO PM lint + capability runner suite stay green
pytest tests/ -k "ao_pm or lint_ao_pm or capability_runner or resolve_view_dir" -v
# expect: all pass — paste tail of output
```

No "pass by inspection." Paste the literal `pytest -v` output.

## Code Brief Standards (mandatory fields)

| Field | Value |
|---|---|
| API version / endpoint | APScheduler (CronTrigger), psycopg2 (existing pool), no external APIs. |
| Deprecation check date | 2026-04-23 — all deps current. |
| Fallback | `_resolve_view_dir` falls back to legacy `data/` resolution if `BAKER_VAULT_PATH` unset (non-fatal logger warning). Re-ingest failure leaves stale rows — detectable via D2 verification SQL. Deliverables 1/3/4 can ship before D2 (vault + system prompt edits are independent). |
| Migration vs bootstrap | No DDL changes. `wiki_pages` schema unchanged. `baker_corrections` table already exists. |
| Ship gate | Literal `pytest -v` output per above. Syntax check 5 files. Data query verifications per §Verification SQL. |

## Sequencing (sub-deliverable)

1. **D1 + D4 first.** Vault migration + learning loop — low-risk, reversible via `git revert` in vault repo. Can ship any time.
2. **D3 after D1.** System prompt addendum — DB UPDATE only, no code deploy. Safe anytime after D1.
3. **D2 after D1.** Runtime wiring — requires D1 vault content to exist for the ingest run to succeed.
4. **D1.7 after D2 verified.** Delete `data/movie_am/` once PM_REGISTRY flip is validated in prod.
5. **D5 anytime (parallel with D1-4).** Lint is independent of the migration order; MOVIE-specific HMA clause check requires D1 files but test can mock them.

## Rollback

- **D1 (vault migration):** `git revert` commit in baker-vault.
- **D2 (PM_REGISTRY flip):** `git revert` commit in baker-master + re-run `ingest_vault_matter.py movie` against stale vault OR restore `data/movie_am/` from git history.
- **D3 (system prompt):** re-run `scripts/insert_movie_am_capability.py` with the addendum block removed.
- **D5 (lint job):** set `MOVIE_AM_LINT_ENABLED=false` on Render — no redeploy needed.

---

## Handoff notes for B3

- **Read AO PM extension brief first** (`briefs/BRIEF_AO_PM_EXTENSION_1.md`) for Deliverable 2 and 3 patterns — this brief explicitly mirrors them.
- **AO PM regression suite is the load-bearing regression gate** — if any AO PM test fails after your changes, you've accidentally touched shared code (likely `_resolve_view_dir` or PM_REGISTRY structure). Stop and diagnose.
- **Commit size.** D1 is one big vault commit (22 paths); D2+D3+D5 is one baker-master commit; D1.7 is a follow-up baker-master commit. Three commits total, not one.
- **PR opens against baker-master main.** Vault commit lands on baker-vault main separately. Reference vault commit SHA in the baker-master PR description for traceability.
- **No B4 involvement.** B4 is on Slack DM lane for other work today. Do not dispatch to B4.
