# SLUGS-2 Residual Catalogue

**Author:** Code Brisen #1
**Date:** 2026-04-18
**Source task:** `briefs/_tasks/CODE_1_PENDING.md` §Deliverable 2
**Related:** `briefs/_reports/B2_slugs1_review_20260417.md` §3 S2
**Status:** Catalogue only — no migrations executed here.

---

## 1. Purpose

Enumerate every hardcoded matter-slug-like reference in `tools/`, `orchestrator/`, `memory/` and classify each as **keep as-is** or **migrate to `kbl.slug_registry`**. Feeds a future SLUGS-2 dispatch decision (fold-all-in-one follow-up PR vs. per-file dispatches).

---

## 2. Method

Task-spec grep, run from repo root on `main` @ `1c054d8`:

```bash
grep -rn "hagenauer-rg7\|cupial\|mo-vie\|brisen-lp\|wertheimer\|aukera" \
    tools/ orchestrator/ memory/ 2>&1 | grep -v __pycache__
```

**Raw output — 14 hits across 6 files:**

```
orchestrator/extraction_engine.py:241:- Link items to the correct matter (hagenauer, cupial, annaberg, etc.)
orchestrator/decision_engine.py:123:        r"construction|handover|gew.hrleistung|cupial|scorpio|"
orchestrator/decision_engine.py:358:    "soulier", "yurkovich", "ubm", "wertheimer",
orchestrator/context_selector.py:7:2. Matter (hagenauer, cupial, annaberg, etc.)
orchestrator/context_selector.py:218:        "cupial": re.compile(r"\b(cupial|scorpio|sonderwunsch|sonderwünsch)", re.IGNORECASE),
orchestrator/capability_runner.py:56:        "contact_keywords": ["oskolkov", "andrey", "aelio", "aukera"],
orchestrator/capability_runner.py:62:            "oskolkov", "aelio", "aukera", "rg7", "capital call",
orchestrator/capability_runner.py:71:            r"aukera",
memory/store_back.py:2338:                    "documents/hma-mo-vienna",
memory/store_back.py:2352:                    "documents/hma-mo-vienna",
memory/store_back.py:3156:                "keywords": ["cupial", "kupial", ...],
memory/store_back.py:3170:                "keywords": ["wertheimer", ...],
memory/store_back.py:3171:                "projects": ["brisen-lp"],
tools/ingest/classifier.py:32:    (r"(?i)(project|hagenauer|rg7|cupial|movie|mo.vie|mandarin|mrci|lilienmat)", "baker-projects"),
```

**Classification scheme:**

- **UI/Keyword-map** → not a canonical-list surface (keyword regex / keyword list / user-input shorthand); shape is fundamentally different from the slug registry. **Keep.**
- **Doc/Comment** → prose mention of matters inside docstrings / prompt text. **Keep.**
- **Path/ID string** → the grep pattern matches a substring of a path or identifier that isn't a slug reference at all. **Keep (false positive).**
- **Canonical-list-duplication** → a dict / list whose intent is "the canonical set of matters". **Migrate.**
- **Rich-metadata DB seed** → parallel data structure keyed by non-canonical matter names, enriched with `people`/`keywords`/`projects`. Same intent as the registry but richer shape. **Defer to SLUGS-2 schema design.**

---

## 3. Per-hit classification

| # | File | Line | Reference | Classification | Action |
|---|---|---|---|---|---|
| 1 | `orchestrator/extraction_engine.py` | 241 | Prompt text: "Link items to the correct matter (hagenauer, cupial, annaberg, etc.)" | Doc/Comment | **KEEP** |
| 2 | `orchestrator/decision_engine.py` | 123 | Regex inside `_DOMAIN_PATTERNS["projects"]` — domain-relevance keywords, not a slug list | UI/Keyword-map | **KEEP** |
| 3 | `orchestrator/decision_engine.py` | 358 | `_OWNER_NETWORK_CONTACTS = ["soulier", ..., "wertheimer", ...]` — 8 strategic **contacts** (people, not matters, even though the string `wertheimer` collides with a canonical slug) | UI/Keyword-map (contacts) | **KEEP** |
| 4 | `orchestrator/context_selector.py` | 7 | Module docstring enumeration | Doc/Comment | **KEEP** |
| 5 | `orchestrator/context_selector.py` | 218 | Single entry in `_MATTER_PATTERNS` dict (lines 214-224; 9 non-canonical keys total) | SLUGS-2 schema ([see §4.2](#42-structural-residuals-dictionary-level)) | **DEFER to SLUGS-2** |
| 6 | `orchestrator/capability_runner.py` | 56 | `PM_REGISTRY["ao_pm"].contact_keywords` — keyword list for contact detection (`aukera` here is a *keyword to match in free text*, not a slug reference) | UI/Keyword-map | **KEEP** |
| 7 | `orchestrator/capability_runner.py` | 62 | `PM_REGISTRY["ao_pm"].briefing_deadline_patterns` — keyword list | UI/Keyword-map | **KEEP** |
| 8 | `orchestrator/capability_runner.py` | 71 | Regex inside `signal_orbit_patterns` | UI/Keyword-map | **KEEP** |
| 9 | `memory/store_back.py` | 2338 | Path string `"documents/hma-mo-vienna"` — grep matched `mo-vie` as substring of `mo-vienna` | Path/ID (false positive) | **KEEP** |
| 10 | `memory/store_back.py` | 2352 | Same path string | Path/ID (false positive) | **KEEP** |
| 11 | `memory/store_back.py` | 3156 | `_seed_matter_registry` Cupial entry `keywords` field | SLUGS-2 schema ([see §4.3](#43-structural-residuals-dictionary-level-continued)) | **DEFER to SLUGS-2** |
| 12 | `memory/store_back.py` | 3170 | Same dict, Wertheimer LP entry `keywords` | SLUGS-2 schema ([see §4.3](#43-structural-residuals-dictionary-level-continued)) | **DEFER to SLUGS-2** |
| 13 | `memory/store_back.py` | 3171 | Same dict, `projects: ["brisen-lp"]` | SLUGS-2 schema ([see §4.3](#43-structural-residuals-dictionary-level-continued)) | **DEFER to SLUGS-2** |
| 14 | `tools/ingest/classifier.py` | 32 | `_PATTERNS` tuple — regex `(project\|hagenauer\|rg7\|cupial\|movie\|mo.vie\|mandarin\|mrci\|lilienmat)` → Qdrant collection `"baker-projects"`. File-classification routing heuristic, not a matter slug list | UI/Keyword-map (Qdrant routing) | **KEEP** |

---

## 4. Summary

### 4.1 Count per classification

| Classification | Count | Disposition |
|---|---|---|
| UI/Keyword-map | 7 | KEEP (different data shape) |
| Doc/Comment | 2 | KEEP |
| Path/ID (false positive) | 2 | KEEP |
| SLUGS-2 schema (structural residuals) | 3 of 14 grep hits — but these hits are each *one literal inside a larger dict/list*. The real structural surfaces are 3 dicts (catalogued in §4.2-4.3) | DEFER |
| Canonical-list-duplication requiring migration | **0** | — |

**Migrate count under the task-spec grep: 0.**

The grep pattern catches slug-like *substrings* but doesn't distinguish "a canonical-list surface" from "a keyword-match regex". The real migration candidates are structural (dict-level), not literal-level — and they need schema design, not simple substitution.

### 4.2 Structural residuals (dictionary-level — not fully captured by the narrow grep)

The task grep pattern missed two important surfaces because their keys don't contain the canonical-slug substrings:

**`tools/document_pipeline.py:103-128` — `PATH_MATTER_HINTS`** (missed by grep; `'13_CUPIAL'` matches but the other 24 entries use non-slug keys like `'14_HAGENAUER'`, `'Baden-Baden'`, `'Mandarin'`, `'Kempinski'`).

- **Shape:** dict from Dropbox folder substring → display name (not slug).
- **Purpose:** feeds LLM document-classification hints.
- **Drift:** Adding a new matter requires editing both `slugs.yml` AND this dict. 25 entries; 11 entries have no canonical slug counterpart (`Baden-Baden Projects`, `Mandarin Oriental Sales`, `Cap Ferrat Villa`, `Kempinski Kitzbühel Acquisition`, `Davos-AlpenGold`, etc.).
- **Migration shape:** add `paths: [substring, ...]` field to `slugs.yml` entries; derive `PATH_MATTER_HINTS` at runtime. Requires registry schema v2.

**`orchestrator/context_selector.py:214-224` — `_MATTER_PATTERNS`** (partially caught — only the `cupial` key matches; the other 8 keys don't).

- **Shape:** dict from non-canonical key → regex for entity detection.
- **Keys:** `hagenauer`, `mandarin-oriental`, `annaberg`, `cupial`, `oskolkov`, `kempinski`, `baden-baden`, `fx-mayr`, `brisen-ai`.
- **Drift:** `mandarin-oriental` vs canonical `mo-vie`; `kempinski` vs `kitz-kempinski`; `hagenauer` vs `hagenauer-rg7`; `annaberg` / `baden-baden` / `fx-mayr` / `brisen-ai` have no canonical slug at all.
- **Migration shape:** KBL-B's triage pipeline is the structural replacement. Fold at KBL-B landing, or retire outright.

### 4.3 Structural residuals (dictionary-level, continued)

**`memory/store_back.py:3137-3175` — `_seed_matter_registry()`** (partial grep match: 3 hits of 5 entries).

- **Shape:** Python list of dicts seeded into PostgreSQL `matter_registry` table.
- **Fields per entry:** `matter_name` (display name), `description`, `people`, `keywords`, `projects`.
- **Drift (subtle):** `matter_name` is a display name (`"Cupial"`, `"Hagenauer"`, `"Wertheimer LP"`), but the `projects` field uses canonical slugs (`"brisen-lp"`, `"hagenauer"`, `"fx-mayr"`, `"claimsmax"`) — an internal inconsistency in the same dict. `"FX Mayr"` has no canonical slug (closest: `lilienmat`). `"ClaimsMax"` has no canonical slug.
- **Migration shape:** add `canonical_slug` column to `matter_registry` table; backfill. Decide whether YAML registry absorbs the rich metadata (`people`, `keywords`, `projects` fields in `slugs.yml`) or whether DB table is retained as extended metadata joined to YAML by canonical slug FK.

---

## 5. Recommendation — fold-all vs per-file

**Recommendation: neither fold-all-in-one NOR per-file migration now. Open SLUGS-2 as a design ticket first.**

### Why not fold-all-in-one

The 3 structural residuals share ONE root problem (vocabulary drift between YAML registry and other matter-keyed surfaces) but require THREE distinct schema decisions:

1. Do we extend `slugs.yml` with a `paths: [...]` field? (affects `PATH_MATTER_HINTS`)
2. Do we retire `_MATTER_PATTERNS` with KBL-B, or fold it into the registry first?
3. Does the rich DB `matter_registry` absorb into `slugs.yml`, or get joined by `canonical_slug` FK?

Each is a design call. Folding all three migrations into a single PR without those decisions upfront would either (a) commit to schema choices under time pressure, or (b) ship a PR that touches 3 files but has no coherent migration arc.

### Why not per-file now

Two of the three sites have a better replacement on the horizon:
- `_MATTER_PATTERNS` → KBL-B triage router replaces it wholesale. Migrating now = throwaway work.
- `_seed_matter_registry` → Director review needed on whether 5 non-canonical names (`FX Mayr`, `ClaimsMax`, `Lanas`, `Alric`, `NVIDIA-GTC-2026` — these appear in the `_project_matters` tuple at line 3103-3112) should become canonical slugs or retire. No design consensus → no safe migration.

`PATH_MATTER_HINTS` is the cleanest candidate for standalone migration (purely additive: new `paths:` field on YAML, derive dict from it), but doing it in isolation would leave 2/3 of the drift in place.

### Proposed SLUGS-2 dispatch

One ticket, three phases:

1. **Design (Director + AI Head):** fix schema calls for (a) YAML `paths` field, (b) DB `canonical_slug` FK vs. full absorption, (c) KBL-B timing for `_MATTER_PATTERNS` retirement.
2. **Director labeling:** decide fate of the 5 non-canonical display names in `_project_matters` and `_seed_matter_registry` — promote to canonical slug or retire.
3. **Implementation:** fold-all-in-one PR, since the schema is pinned before code.

Est. time: 2-3 hr design session + ~4-6 hr implementation + tests. Not a 30-min task.

---

## 6. Out-of-scope observations (flagged for Director awareness, not SLUGS-2)

1. **`_project_matters` tuple** at `memory/store_back.py:3103-3112` uses display names to seed the `matter_registry.category='projects'` update. This is adjacent to `_seed_matter_registry` but a different surface (updates category, doesn't seed rows). Fix scope = same as §4.3.
2. **`orchestrator/capability_runner.py` PM_REGISTRY entries** contain repeated keyword lists (`["oskolkov", "aelio", ...]`) across multiple sub-fields (`contact_keywords`, `briefing_email_patterns`, `briefing_whatsapp_patterns`, etc.). These are UI/keyword-map shape — not slug migrations. But they repeat. Opportunity for a PM-registry refactor independent of SLUGS-2.
3. **`orchestrator/agent.py` prompt examples** mention `Wertheimer`, `Cupial`, `Hagenauer` as query examples. Prose inside prompts. No migration needed.

---

*Filed 2026-04-18 by Code Brisen #1. Next step: AI Head decides whether to open SLUGS-2 as a design ticket now or defer until KBL-B lands.*
