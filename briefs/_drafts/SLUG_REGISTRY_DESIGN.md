# Matter Slug Registry — Design Note

**Status:** DRAFT — for Director ratification
**Author:** AI Head
**Date:** 2026-04-17
**Context:** B3 D1 labeling session surfaced "slugs are a living body" architecture concern. Drift is live and measurable. This note designs the single-source-of-truth fix before KBL-B is briefed.

---

## 1. Problem — observed drift, not theoretical

Slugs surface in **five** places in the current codebase. They disagree.

| # | Surface | Slug count | Source |
|---|---|---|---|
| 1 | `scripts/validate_eval_labels.py` → `MATTER_ALLOWLIST` | **19** | B2-authored, most canonical |
| 2 | `scripts/build_eval_seed.py` → `MATTER_HINTS` | **9** | Director-labeling hint helper |
| 3 | `scripts/run_kbl_eval.py` → `STEP1_PROMPT` inline example | **6** | Model-facing prompt |
| 4 | `scripts/run_kbl_eval.py` → `MATTER_ALIASES` | **5 families** | Model-output normalization |
| 5 | `outputs/kbl_eval_set_20260417_labeled.jsonl` → `primary_matter_expected` | **14** distinct + `null` | Director-labeled ground truth |

Additional consumers that **will** need slugs once KBL-B ships (not yet in code):

- D3 Layer 1: entity-map pre-filter (ingest-side matter detection)
- D3 Layer 2: Step-1 classifier prompt enum (eval-runner is the proxy; production version will be a sibling)
- D3 Layer 3: `KBL_MATTER_SCOPE_ALLOWED` env filter at Step 5 (already wired in KBL-A brief §cfg, currently `hagenauer-rg7` for Phase 1)
- Vault directory tree: `wiki/<slug>/...` path convention
- Signal-queue indexes: `primary_matter TEXT`, `related_matters JSONB` (KBL-A schema §279-296)

### Concrete drift cases (observed, not hypothetical)

- 7 slugs in validator are **absent from seed-script hints**: `aukera`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `balducci`, `constantinos`, `franck-muller`
- `wertheimer` is a **canonical slug** in validator, but seed-script hints and eval-runner aliases both fold it into `brisen-lp` — the stale alias B3's eval retry must patch
- `edita-russo` and `theailogy` exist in validator + seed hints but have **never appeared in labels** — they may be speculative
- 2 slugs appeared in labels but have **no entry in seed hints**: `baker-internal`, `personal`
- Eval-runner prompt shows 6 of 19 slugs to the model → 50% matter-miss rate is mechanically explained

B3's first eval report §4a attributes the bulk of the 70% matter-miss rate to this drift, not to model capability. Fixing the prompt for one retry is a tactical patch; the registry is the structural fix.

---

## 2. Design principles

1. **Single source of truth.** One file, five consumers, zero forked lists.
2. **Director-editable with audit trail.** Adding a slug during labeling must be a one-line change, reviewable via git history.
3. **No schema migration to add a slug.** Adding `"six-senses-gstaad"` cannot require a Render redeploy or a PG ALTER.
4. **Versioned.** Eval runs record which registry version they ran against, so "Gemma 70% v1 vs 94% v2" honest-compares.
5. **Alias-aware.** Model outputs drift ("cupials" / "mandarin oriental" / "hagenauer"). The registry owns canonical ↔ alias mapping alongside the slug list, not in a separate file.
6. **Lifecycle-aware.** Slugs get retired (project closes), not deleted. Historical signals keep referencing them.

---

## 3. Options

### Option A — YAML in `baker-vault` repo *(recommended)*

`baker-vault/slugs.yml`:

```yaml
version: 3
updated_at: 2026-04-17
matters:
  - slug: hagenauer-rg7
    status: active
    description: "RG7 final-account dispute, Baden bei Wien"
    aliases: [hagenauer, rg7]
  - slug: cupial
    status: active
    description: "Cupial handover dispute (Tops 4,5,6,18)"
    aliases: [cupials, "cupial-zgryzek", "monika cupial"]
  - slug: mo-vie
    status: active
    description: "Mandarin Oriental Vienna, asset mgmt"
    aliases: [movie, "mo vienna", mandarin, "mandarin oriental", mohg]
  # … 16 more
```

**Pros**
- Matches D13 precedent — `env.mac-mini.yml` in baker-vault already deploys config via yq-flatten
- Director edits via PR to baker-vault → git history is the audit log
- Render pulls baker-vault at deploy; Mac Mini pulls at cron-tick — both already wired
- Adding a slug is a one-line PR, no migration, no redeploy
- Aliases live alongside canonical — atomic add/rename
- Can be loaded once at process start, cached in-memory; re-load on SIGHUP or per-tick

**Cons**
- YAML → no type-check; typos possible → mitigate with a load-time validator (`kbl/slug_registry.py` asserts shape + uniqueness + reserved-words)
- baker-vault is a **separate repo from baker-master** — consumers must pull it. The production deploy already does this for config; eval scripts currently don't. Small one-time lift.

### Option B — Postgres table `matter_slug_registry`

Row per slug: `(slug PK, status, aliases JSONB, description, created_at, retired_at)`.

**Pros**
- DB is already the source for signal data; querying slugs is trivial
- Mac Mini + Render both query same PG instance

**Cons**
- Adding a slug during labeling requires DB write (via script or admin UI) — higher friction than a YAML edit
- Audit trail requires triggers or app-side logging; git history in baker-vault is free
- Offline scripts (eval runner, validator) need DB creds just to know "is 'aukera' a slug?" — currently they don't
- Doesn't match established config pattern (D13 went to YAML explicitly)

### Option C — Python module constant `kbl/slugs.py`

Single `MATTER_REGISTRY: dict[str, dict]` at module level, imported everywhere.

**Pros**
- Type-checkable, IDE-completable
- Zero runtime dependency

**Cons**
- Requires a code PR + Render redeploy to add a slug → Director can't self-serve during a labeling session
- Fails principle #2 (audit trail is fine, editability is bad)

---

## 4. Recommendation — **Option A**

Specifically:

- **Location:** `baker-vault/slugs.yml` (new file in existing repo)
- **Loader:** `kbl/slug_registry.py` (new module in baker-master)
  - `load_registry() -> SlugRegistry` — reads YAML, validates shape, caches
  - `canonical_slugs() -> set[str]` — replaces `MATTER_ALLOWLIST`
  - `active_slugs() -> set[str]` — subset where `status == active`
  - `normalize(raw: str) -> Optional[str]` — replaces `normalize_matter` + alias map
  - `registry_version() -> int` — embed in eval results for version-aware comparison
- **Migration:** one-shot extraction script reads validator + seed hints + eval aliases, produces initial `slugs.yml` for Director review
- **Consumers patched in order:**
  1. `validate_eval_labels.py` (ingest-side: validates labels against registry)
  2. `run_kbl_eval.py` prompt + aliases (model-facing)
  3. `build_eval_seed.py` hints (helper only)
  4. KBL-B entity-map pre-filter (when briefed)
  5. KBL-B Step-1 production classifier (when briefed)

### Lifecycle conventions

| Status | Offered to model in prompt? | Accepted in validator? | Router reads? |
|---|---|---|---|
| `active` | yes | yes | yes |
| `retired` | no | yes (historical signals) | no — falls through to inbox |
| `draft` | no | no | no — reserved for Director-flagged candidates during labeling |

Retiring a slug never breaks old signals. Draft lets Director jot `constantinos` during a session before the full prompt propagates.

### Versioning

`version: N` in YAML (monotonic). Eval results JSON gains a `slugs_version: N` field. Comparing Gemma v1 @ version 2 vs v2 @ version 3 is honest — the numbers literally ran against different registries.

---

## 5. KBL-B integration points

1. **Step 1 prompt construction** — reads `active_slugs()`, formats as enum
2. **Entity-map pre-filter (D3 Layer 1)** — registry drives keyword→slug map via aliases
3. **Step 5 ALLOWED_MATTERS check** — intersects `cfg_list("matter_scope_allowed")` with `active_slugs()`; warn on unknown
4. **Vault path validation** — `wiki/<slug>/...` rejects paths where `<slug>` is not in registry
5. **Signal-queue writes** — trigger or app-check that `primary_matter` ∈ registry ∪ {NULL}

Bakes in once, feeds five consumers. Compresses KBL-B brief by removing five "how do we enumerate matters here" paragraphs.

---

## 6. Migration plan

Ratification triggers (≤1 hour of Code work total):

1. AI Head writes SLUGS-1 code brief (separate from KBL-B)
2. Code Brisen (B1 or B2) runs one-shot extraction → seeds `baker-vault/slugs.yml` with validator + seed-hint + alias union, with `status: active` default
3. Director reviews file, approves via PR merge
4. Code Brisen implements `kbl/slug_registry.py` loader
5. Code Brisen patches 3 current consumers (validator, eval runner, seed hints) to import from loader
6. B3 re-runs eval against `slugs.yml v1` — sanity check, not gated
7. KBL-B brief then references the registry as pre-existing infrastructure

---

## 7. Open questions for Director

1. **Fold SLUGS-1 into KBL-B or ratify standalone?** Standalone is cleaner (smaller blast radius, testable in isolation) but delays KBL-B by ~2 days. AI Head's weak preference: **standalone**, so KBL-B inherits a stable registry.
2. **Who curates aliases?** During labeling, Director adds canonical slugs. But aliases (`"mandarin oriental"` → `mo-vie`) often reveal themselves post-hoc when a model outputs something new. Proposal: aliases accumulate via PR after each eval run; Director only ratifies batch updates, not individual aliases.
3. **Retention of retired slugs?** Do closed projects (e.g., once Hagenauer settles) stay `active` or move to `retired`? Default: Director flips status manually at project close. No automation.
4. **Separate slug-registry for people vs projects?** Current list mixes `ao` (person) with `mo-vie` (asset). Is this a registry problem or a non-problem? Bias: non-problem — matter = "thing Baker routes to". But flagging for Director.

---

## 8. What this note is NOT

- Not a code brief. Ratification → AI Head writes SLUGS-1 brief → Code Brisen implements.
- Not an attempt to re-open the slug list. Today's 19-slug set is the extraction target; additions happen in a normal PR flow thereafter.
- Not gated on B3's D1 retry result. This design stands regardless of Gemma's retry score — if Gemma passes, the registry still removes drift for KBL-B; if it fails, the registry is a precondition for honest comparison of alternatives.

---

## 9. Decision needed

Director, three asks:

1. Ratify **Option A** (YAML in baker-vault) vs B/C
2. Standalone SLUGS-1 brief **before** KBL-B — yes/no
3. Pick a side on each open question in §7 (or "defer to AI Head judgment")

Upon ratification, AI Head writes SLUGS-1 code brief next. Estimated implementation: 1-2 hours of Code work.

---

*Prepared 2026-04-17. B3 retry is orthogonal and proceeds in parallel.*
