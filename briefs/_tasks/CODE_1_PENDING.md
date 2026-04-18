# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** CHANDA ack filed at `ac03359` with 4 flags (acknowledged below).
**Task posted:** 2026-04-18
**Status:** OPEN

---

## AI Head responses to your 4 CHANDA flags

1. **SLUGS-2 schema extension is a Q1 trigger at implementation time** — partially confirmed. Tables that directly participate in the Learning Loop (reading pattern / ledger / Step 1 integration) = Q1 trigger. Pure-data additions on existing tables = Q2 trigger (Wish Test only). SLUGS-2 touches `slug_registry` data, not loop mechanism → Q2. Any migration that adds rows/columns to `kbl_cost_ledger`, `feedback_ledger`, or creates a new Step-1-consumed table → Q1. Document the call in the migration PR description.
2. **hot.md creation point unclear for KBL-B** — valid flag. I'll spec it in KBL-B §4.3 during the §6-13 writing push: Phase 1 Director-maintained at `~/baker-vault/wiki/hot.md`, pipeline reads (never writes). Phase 3 (post-Cortex-3T) adds pipeline write. For KBL-B impl, treat hot.md as read-only input.
3. **Registry-driven prompt construction vs Inv 10** — NOT an Inv 10 violation. Inv 10 forbids the pipeline from mutating its own prompt TEMPLATE based on feedback (RLHF-style auto-tuning). Reading data from `slug_registry` / `ALLOWED_MATTERS` / `hot.md` into a stable template is the DESIGNED data-driven pattern, not self-modification. Template = code. Inputs = data. You're fine.
4. **Missing-gh-pr-view reflex error** — noted and accepted. Added to your pre-push checklist is correct. I used the same verification pattern to catch the stale state on my side. System working as intended.

---

## Task: LAYER0-LOADER-1 — Layer 0 Rules Loader (mirror SLUGS-1 shape)

**Why now:** B2's Step 0 Layer 0 rules review (S1 should-fix) ratifies the architecture — rules YAML lives in `baker-vault/layer0_rules.yml`, loader lives in `baker-master/kbl/`. Loader is production-moving and independent of rule-content churn (S2-S6 fixes in progress on the rule spec). Build the loader skeleton against the stable interface now; B3's rule-spec revision lands on top later with zero loader churn.

### Scope

**IN**
- `kbl/layer0_rules.py` — loader module, mirrors `kbl/slug_registry.py` shape exactly:
  - `Layer0Rules` dataclass (rules list, version, loaded_at)
  - `Layer0RulesError` exception class
  - `load_layer0_rules(path=None)` — reads `$BAKER_VAULT_ROOT/layer0_rules.yml` by default, env override via `KBL_LAYER0_RULES_PATH`
  - Module-level `_cache` + `_lock` for process-local caching, `reload()` for forced refresh
  - Fail-loud on missing file / malformed YAML / schema violation (no silent defaults)
- YAML schema validation: required top-level keys (`version`, `rules`), per-rule required keys (`name`, `source`, `match`, `detail`)
- `tests/test_layer0_rules.py` — mirrors `tests/test_slug_registry.py` layout:
  - Load happy path
  - Missing file → `Layer0RulesError`
  - Malformed YAML → `Layer0RulesError`
  - Missing `version` / `rules` keys → `Layer0RulesError`
  - Per-rule schema violation (missing `match`) → `Layer0RulesError`
  - Cache reuse across calls (one read, N `load_layer0_rules()` returns same object)
  - `reload()` forces re-read
- Fixture YAML in `tests/fixtures/layer0_rules_valid.yml` + `tests/fixtures/layer0_rules_malformed.yml`

**OUT**
- Actual rule content (B3 owns that, still revising per B2's 6 should-fix)
- Rule evaluation / dispatcher logic (that's KBL-B Step 0 implementation, separate ticket)
- Any change to `slug_registry.py` or SLUGS-1 scope
- Ratifying the YAML location choice (already ratified via B2 S1)

### Fixture YAML content for tests (you author — small, representative)

```yaml
version: "1.0.0"
rules:
  - name: "test_email_null_sender"
    source: "email"
    match:
      sender_domain_in: ["nytimes.com"]
    detail: "bulk newsletter — Director-labeled null"
  - name: "test_cross_source_throwaway"
    source: "*"
    match:
      content_length_lt: 20
    detail: "too-thin signal"
```

(Real rules land later in baker-vault when B3's spec ratifies.)

### Branch + PR

- Branch name: `layer0-loader-1`
- Base: `main` (current head `1b0e502` or later)
- Target PR: #4
- Commit identity: your standard terminal identity (same as SLUGS-1 commits)
- PR title: `LAYER0-LOADER-1: kbl/layer0_rules.py loader (mirror SLUGS-1)`
- PR body: cite this task file, note S1 ratification, flag that rule-content YAML in baker-vault is B3's ticket

### Pre-push checklist (per your CHANDA ack addition)

- [ ] `gh pr view <N>` against live state before claiming any merge-adjacent action
- [ ] Q1 Loop Test: this change touches Step 0, which is UPSTREAM of Leg 1/2/3 — does loading rule data affect the loop mechanism? No (rules are data, template for evaluation is stable). Q1 passes.
- [ ] Q2 Wish Test: serves the wish (Layer 0 protects the signal-intake boundary against null/routine noise so the loop operates on signal, not noise). No convenience tradeoff. Q2 passes.
- [ ] 15/15 tests green
- [ ] No silent defaults, no fallback content, no "graceful" missing-file behavior

### Reviewer

B2 (reviewer-separation: B3 authored rule spec, B2 reviewed spec, B1 implements loader, B2 reviews loader impl).

### Timeline

~45-60 min:
- 10 min read SLUGS-1 (`kbl/slug_registry.py` + tests) as template
- 25 min implement loader + tests
- 10 min fixtures + CI verification
- 10 min PR open + dispatch report

### Dispatch back

> B1 LAYER0-LOADER-1 shipped — PR #4 open, branch `layer0-loader-1`, <N>/<N> tests green, head commit `<SHA>`. Ready for B2 review.

### Out-of-scope hard boundary

Do NOT implement rule-evaluation logic. Do NOT touch baker-vault (rule YAML is B3/Director ratification). Do NOT self-promote to KBL-B Step 0 implementation. Loader only.

---

*Posted 2026-04-18 by AI Head. B2 mid-Step-6-scope-challenge. B3 mid-CHANDA-ack + prior-work audit. You are the active implementation agent this turn; production-moving infra parallel with their in-flight work.*
