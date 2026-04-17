# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance, KBL-A implementer)
**Previous report:** [`briefs/_reports/B1_kbl_a_implementation_20260417.md`](../_reports/B1_kbl_a_implementation_20260417.md)
**Design reference:** [`briefs/_drafts/SLUG_REGISTRY_DESIGN.md`](../_drafts/SLUG_REGISTRY_DESIGN.md) — ratified by Director 2026-04-17 (Option A: YAML in baker-vault; standalone before KBL-B; AI Head judgment on §7 opens)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution
**Supersedes:** KBL-A PR #1 revisions task (shipped, PR #1 approved by B2)

---

## Task: SLUGS-1 — Matter Slug Registry

### Purpose

Replace five inconsistent slug lists (validator / seed hints / eval prompt / aliases / labels) with one YAML source of truth in `baker-vault`. Remove drift **before** KBL-B inherits it. Design rationale in the draft — read §1 and §3 before you start. Don't re-open §2 principles or §4 option choice.

### Scope

**IN**
1. Create `baker-vault/slugs.yml` with 19 canonical slugs + aliases extracted from current code
2. Create `kbl/slug_registry.py` Python loader
3. Patch 3 existing consumers to read from the registry
4. Add load-time tests
5. Document in the KBL-A README (one-paragraph pointer)

**OUT** — do NOT touch
- KBL-B pipeline code (not yet briefed)
- The D1 eval retry (B3's thread)
- The 4 open questions in §7 of the design note (AI Head defaults noted inline below — implement those, don't debate them)
- Adding new slugs beyond the 19 already in `scripts/validate_eval_labels.py`. Extraction-only.

---

## 1. `baker-vault/slugs.yml`

**Shape:**

```yaml
version: 1
updated_at: 2026-04-17
matters:
  - slug: hagenauer-rg7
    status: active
    description: "RG7 final-account dispute, Baden bei Wien"
    aliases: [hagenauer, rg7]
  - slug: cupial
    status: active
    description: "Cupial handover dispute — Tops 4,5,6,18"
    aliases: [cupials, "cupial-zgryzek", "monika cupial"]
  # ... 17 more
```

**Extraction procedure:**

1. Union the 19 slugs from `scripts/validate_eval_labels.py` → `MATTER_ALLOWLIST` — this is the authoritative set
2. For each slug, pull aliases from `scripts/run_kbl_eval.py` → `MATTER_ALIASES` and `scripts/build_eval_seed.py` → `MATTER_HINTS`. Union and dedupe.
3. **FIX STALE ALIAS:** `MATTER_ALIASES["brisen-lp"]` currently contains `"wertheimer"`. Director split these during labeling (`wertheimer` is its own canonical slug now). **Do not carry `wertheimer` into `brisen-lp` aliases.** `wertheimer` gets its own entry with aliases `[]` (Director to annotate).
4. `status: active` for all 19 in v1.
5. `description` — use a one-line human-readable stub. Pull from the existing Director context in `CLAUDE.md` where available (hagenauer-rg7, cupial, mo-vie, ao, mrci, lilienmat, brisen-lp, wertheimer are all documented there). For slugs with no documented context (`aukera`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `balducci`, `constantinos`, `franck-muller`, `edita-russo`, `theailogy`, `baker-internal`, `personal`), use `"(Director to annotate)"`.

**Access check before you start:** confirm you have write access to the `baker-vault` repo. If not, stop and escalate to AI Head with a clear "baker-vault access missing, blocked."

---

## 2. `kbl/slug_registry.py` — loader module

**Placement:** alongside `kbl/config.py`. Do not put inside `scripts/` — this is production code, not a dev script.

**Public API** (match these exact signatures — consumers will import them):

```python
def registry_version() -> int
def canonical_slugs() -> set[str]          # all slugs regardless of status
def active_slugs() -> set[str]             # status == active only
def is_canonical(slug: str | None) -> bool # None → True (null is always valid)
def normalize(raw: str | None) -> str | None
    """Map raw model output to canonical slug or None.
    Rules:
      - None / empty / 'none' / 'null' → None
      - Exact canonical match → slug
      - Alias match (case-insensitive, whitespace-normalized) → canonical slug
      - No match → None (caller decides whether to log)
    """
def describe(slug: str) -> str             # description for a known slug; raises if unknown
```

**Loader behavior:**

- Path resolution: `os.getenv("BAKER_VAULT_PATH")` + `/slugs.yml`. Fail hard with a clear error if env unset or file missing — this is deploy-time config, not runtime-tunable
- Parse YAML with `PyYAML` (already in KBL-A deps — verify and add if not)
- Validate shape at load time: `version` is int, `matters` is list, each entry has `slug: str` + `status: str in {active, retired, draft}` + `aliases: list[str]`. Duplicate slugs → fail. Duplicate aliases across different canonical slugs → fail.
- Cache in module-level dict. Reload triggered by `slug_registry.reload()` (for tests + future SIGHUP handler). No auto-reload in v1.
- Aliases are stored lowercased + whitespace-collapsed at load time so `normalize()` is a dict lookup, not a linear scan.

**AI Head defaults on §7 open questions** (implement these, do not re-debate):

- **Alias curation flow:** §7.2 — batch ratified via PR to baker-vault. v1 only includes aliases already present in existing code. No model-output scraping in this ticket.
- **People vs projects:** §7.4 — single registry, no split. `ao` (person) and `mo-vie` (asset) coexist.
- **Retention:** §7.3 — `retired` status exists in the schema but no v1 slugs use it. Director flips manually at project close.
- **Standalone vs folded into KBL-B:** §7.1 — already ratified standalone (that's why you have this brief).

---

## 3. Patch 3 existing consumers

### 3a. `scripts/validate_eval_labels.py`

Remove the hardcoded `MATTER_ALLOWLIST` set. Import from `kbl.slug_registry` instead:

```python
from kbl.slug_registry import canonical_slugs
# ... use `slug in canonical_slugs()` where MATTER_ALLOWLIST was referenced
```

Behavior must be identical. Add one test: feed a labeled line with a known-good slug + one with a typo, confirm the same pass/fail as before the refactor.

### 3b. `scripts/run_kbl_eval.py`

Two changes:

1. **Prompt enum:** Replace the hardcoded 6-slug example in `STEP1_PROMPT` with dynamic enumeration from `active_slugs()`. Format as a bulleted list or pipe-separated, whichever reads cleaner to the model. Include the vedana rule block from B3's retry task (already specified there — don't re-invent). Include "null is valid when no matter applies" language.
2. **Aliases:** Delete `MATTER_ALIASES` dict + `normalize_matter()` function. Replace the call site with `slug_registry.normalize(raw)`.

**B3's D1 retry expects the prompt-patch + wertheimer-alias-fix as a manual edit.** Coordinate: if B3 merges first, rebase on top. If this PR merges first, B3's retry task's §2 alias-fix becomes a no-op — note that in the PR description.

### 3c. `scripts/build_eval_seed.py`

`MATTER_HINTS` is the Director-labeling hint generator — cosmetic but must align. Replace the hardcoded dict with a derived dict built from `slug_registry`:

```python
# Derive hints from registry aliases + canonical slug itself as a keyword
MATTER_HINTS = {
    slug: [slug.replace("-", " "), slug, *registry.aliases_for(slug)]
    for slug in registry.active_slugs()
}
```

Add `aliases_for(slug) -> list[str]` to the registry loader's public API (was missing from §2 — add it).

---

## 4. Tests

Add `tests/test_slug_registry.py` with:

1. **Load happy path:** `BAKER_VAULT_PATH=tests/fixtures/vault/`, reads `slugs.yml` fixture, returns 3 known slugs
2. **Duplicate slug fails loudly** (fixture with dup)
3. **Duplicate alias across slugs fails loudly** (fixture where `"mohg"` aliases to both `mo-vie` and `hagenauer-rg7`)
4. **`normalize()` — canonical pass-through, alias match, null/none/empty returns None, whitespace variations match**
5. **`active_slugs()` filters retired** (fixture with mix)
6. **`is_canonical(None)` returns True, `is_canonical("not-a-slug")` returns False**

Create `tests/fixtures/vault/slugs.yml` with 3-4 slugs + one retired for test 5.

Do NOT add a test that locks the full 19-slug production list — that's a drift-creator, defeats the whole point of the registry.

---

## 5. Documentation

Add a ~10-line section to `README.md` under "Configuration":

```markdown
### Matter slug registry

Canonical matter slugs live in `baker-vault/slugs.yml` (separate repo).
Edit there via PR — changes propagate to validator, eval runner, and
seed-hint script at next process start. Schema + loader API in
`kbl/slug_registry.py`.
```

---

## 6. Rollout sequence

1. **Pre-flight:** confirm baker-vault access (§1 access check)
2. Branch `slugs-1-impl` off main
3. Commit `slugs.yml` to baker-vault repo (separate PR — Director merges independently)
4. Commit `kbl/slug_registry.py` + `tests/test_slug_registry.py` + fixtures to baker-master
5. Commit the 3 consumer patches (one commit per file for reviewability)
6. Commit README update
7. Open PR #2 against baker-master with title `SLUGS-1: matter slug registry`
8. Link to the baker-vault PR in the description
9. Dispatch B2 for independent review (AI Head writes B2's task — you don't)
10. File report at `briefs/_reports/B1_slugs1_impl_<YYYYMMDD>.md`

---

## 7. Acceptance criteria

- All 6 tests pass locally: `.venv/bin/python3 -m pytest tests/test_slug_registry.py`
- `scripts/validate_eval_labels.py outputs/kbl_eval_set_20260417_labeled.jsonl` produces identical output to pre-refactor run (zero validation-behavior change)
- Before and after output of `.venv/bin/python3 scripts/build_eval_seed.py --seed 42 --dry-run` (or equivalent no-side-effect invocation) differs only in hint ordering, not in slug coverage
- No hardcoded slug list remains anywhere in `scripts/` or `kbl/` except: (a) test fixtures, (b) the string inside the LLM prompt itself which is built dynamically, (c) `CLAUDE.md` which is user-facing memory and outside scope

---

## 8. What to watch for

- **B3's retry runs against the current prompt** (pre-SLUGS-1). Don't block B3. If SLUGS-1 lands before B3's retry runs, B3 inherits the registry-driven prompt — that's fine and arguably better. If B3's retry lands first, SLUGS-1 subsumes B3's manual alias fix. Either order is acceptable.
- **`baker-vault` is a separate repo.** Two PRs, two merges. Deploy order: baker-vault PR merges first, then baker-master PR (else baker-master references a file that doesn't exist yet in the deployed vault).
- **`BAKER_VAULT_PATH` env var** — verify it's set on Render and on the macmini already. KBL-A's `env.mac-mini.yml` sources from the vault, so it should be. If not, flag in the report — this is deployment config, not your code to fix.

---

## 9. Estimated time

~2 hours:

- 15 min extraction + `slugs.yml` drafting
- 30 min loader module + tests
- 30 min patching 3 consumers
- 15 min README + rollout prep
- 30 min PR + report

---

*Dispatched 2026-04-17 by AI Head. Git identity: `Code Brisen 1` / `dvallen@brisengroup.com`. Fresh `/tmp/bm-draft` clone or your existing terminal clone — whichever is cleanest.*
