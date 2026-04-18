# SLUGS-1 Independent PR Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) — SLUGS-1 reviewer-separation review
**PRs reviewed:**
- baker-master [PR #2](https://github.com/vallen300-bit/baker-master/pull/2) — branch `slugs-1-impl` @ `b24b686` (5 code commits)
- baker-vault [PR #1](https://github.com/vallen300-bit/baker-vault/pull/1) — branch `slugs-1-vault` @ `367b7de`
**B1's report:** `briefs/_reports/B1_slugs1_impl_20260417.md` (on `slugs-1-impl`)
**Date:** 2026-04-18
**Method:** fresh clones at `/tmp/bm-b2`, `/tmp/bv-b2` from `origin`. Identity `Code Brisen 2 / dvallen@brisengroup.com`.

---

## 1. Verdict

**APPROVE** — merge in deploy order (baker-vault PR #1 first, then baker-master PR #2).

No blockers. Two should-fix items below are post-merge follow-ups (one is a missing test for B1's most consequential semantic change; the other is a residual-inventory completeness ask). Code is correct, well-bounded, parity-verified.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

### S1 — No unit test for `score_row` `unknown_non_canonical` guard

**Location:** `scripts/run_kbl_eval.py:226-235`, `tests/test_slug_registry.py` (none — and no `tests/test_run_kbl_eval.py` exists).

**Issue.** The guard is the single most consequential semantic change in this PR. It exists because the registry's `normalize()` returns `None` for unknown inputs (sane registry contract), but the pre-refactor `normalize_matter()` returned `raw.lower().strip()` (so `"hospitality"` stayed `"hospitality"`, never matching `None` labels). Without the guard, a model emitting a non-canonical category string against a `None`-labeled signal would spuriously score True. The guard correctly converts that back to False. **But the guard is not tested.** A future refactor of `slug_registry.normalize()` (e.g. someone "simplifies" by returning the raw input on no-match) silently breaks the guard's premise and inflates eval scores.

**Counter-examples I traced manually (all pass with current code):**

| `out_matter_raw` | `label_pm` | Pre-refactor | Post-refactor | Verdict |
|---|---|---|---|---|
| `"hospitality"` | `None` | False | False (guard fires) | ✓ parity |
| `"Hagenauer"` | `None` | False | False (matter=hagenauer-rg7 ≠ None) | ✓ parity |
| `"Hagenauer"` | `"hagenauer-rg7"` | True (alias norm) | True (alias norm) | ✓ parity |
| `None` | `None` | True | True | ✓ parity |
| `"none"` | `None` | True (`"none"` == None? No — but `None == None` after explicit allowlist) | True (`null`-ish handled) | ✓ parity |

**Fix.** Add `tests/test_score_row.py` with the four cases above. ~30 lines. Small, completes the structural-vs-integration verification per Lesson #34. Same PR ideal; follow-up acceptable.

**Note on task author's stated expectation.** The task brief §"Semantic invariants" parenthetical claims `out_matter_raw="Hagenauer"` against `label_pm=None` "should be True — the model is right in a weird way." I disagree, and B1's implementation also returns False here. `matter_ok` measures *agreement with label*, not *structural validity of the model's output*. A label of `None` and a model output of `hagenauer-rg7` disagree; matter_ok=False is the right answer. The implementation is correct; the brief's parenthetical is the confused side.

### S2 — Residual hardcoded slug inventory is incomplete

**Locations:**
- `tools/document_pipeline.py:103-118` — `PATH_MATTER_HINTS` dict mapping Dropbox folder substrings to display names (`"14_HAGENAUER" → "Hagenauer"`).
- `orchestrator/context_selector.py:215-221` — `PATTERNS` dict with regex-based entity detection using non-canonical keys (`"mandarin-oriental"`, `"annaberg"`, `"baden-baden"`).
- `memory/store_back.py:~3141+` — embedded matter knowledge dict with rich metadata per matter (people, keywords, projects fields).

**Issue.** B1's "Residual hardcoded slugs" section in their report enumerates only 3 `scripts/` files. The three above are real residuals in `tools/`, `orchestrator/`, and `memory/`. They use **different vocabularies** (display names, regex keys, rich-metadata) so they're legitimately not in the SLUGS-1 task's "patch 3 consumers" scope, but they're also not legitimately invisible. When KBL-B touches the orchestrator/memory layer, the team will trip over them.

**Fix.** Either (a) extend B1's "Residual" section in their report with these three — explicit deferred-list, or (b) open a follow-up ticket SLUGS-2 enumerating them. Take 5 minutes; preserves the registry-as-single-source-of-truth invariant intent without scope-creeping this PR.

**Also stale:** B1 listed `scripts/benchmark_ollama_triage.py` as a residual, but that file is not in `slugs-1-impl` (or `main`). Either renamed/removed earlier, or B1 was working from memory. Drop from the residual list.

---

## 4. Nice-to-have

### N1 — `sys.path.insert` convention inconsistency

`scripts/validate_eval_labels.py:31` and `scripts/run_kbl_eval.py:39` use `Path(__file__).resolve().parent.parent` (B1's "more robust" pattern, per their hint #5). `scripts/build_eval_seed.py:38` retained the legacy `sys.path.insert(0, ".")`. B1 said in their hint they "used the more robust" pattern — but only in the new files; the third script kept the old form. Unify to one approach (Path-based). Trivial.

### N2 — No test for malformed YAML

Existing tests cover duplicate slug, duplicate alias, missing env var, missing file, status-enum, shape. Missing: actually broken YAML (truncated, BOM, tab-indented). The loader's `except yaml.YAMLError` path is therefore untested. A 5-line fixture (`vault_malformed/slugs.yml`) and 1 test would harden the error path and catch regressions if `yaml.safe_load` is ever swapped for a stricter loader.

### N3 — Prompt template is process-lifetime cached

`run_model()` calls `_build_step1_prompt()` once per process start (line 328). If `slug_registry.reload()` is invoked mid-process and signals continue processing across that boundary, the prompt wouldn't reflect the new active-slugs list. Today no SIGHUP-style reload trigger exists, so this is theoretical. Worth a comment at the call site, or rebuild the template per `run_model()` invocation. Leave for KBL-B if reload is wired then.

### N4 — 11 of 19 slugs have placeholder description

`baker-vault/slugs.yml` ships with `"(Director to annotate)"` for `aukera`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `balducci`, `constantinos`, `franck-muller`, `edita-russo`, `theailogy`. Doesn't break anything (description is informational, not validated). But the registry is intended as the single source of truth and ~58% placeholder descriptions reads as unfinished. Director can fill these in via separate PR; flag for next labeling session.

---

## 5. B1 hints assessment

| # | Hint | My read |
|---|---|---|
| 1 | `unknown_non_canonical` guard semantics | **AGREE** with implementation. Guard is correct and necessary. Disagree with task brief's "should be True" framing — see §3 S1 trace table. The guard preserves pre-refactor parity exactly. |
| 2 | Hint coverage expansion (9 → 19) per §3c literal spec | **AGREE.** §3c spec literally iterates `active_slugs()`. The 9 originals retain every prior keyword. Coverage expansion is per-design, not regression. |
| 3 | Prompt enum sort = alphabetical | **AGREE.** Deterministic, registry-order-independent. Usage-frequency sort is premature optimization without an A/B baseline. |
| 4 | Seeded `kbl/__init__.py` matches `kbl-a-impl` exactly | **VERIFIED BYTE-EQUAL** via `diff -u origin/kbl-a-impl:kbl/__init__.py vs slugs-1-impl:kbl/__init__.py` — clean, zero diff. Rebase will auto-resolve. |
| 5 | `sys.path.insert(Path(__file__).resolve().parent.parent)` convention | **ACCEPTABLE** approach but **inconsistently applied** — see §4 N1. |

---

## 6. Deviations assessment

### D1 — README.md → CLAUDE.md (commit `b24b686`)

**ACCEPT.** No top-level `README.md` exists in the repo (only nested ones under `briefs/_reports/`, `briefs/_tasks/`, `.pytest_cache/`). `CLAUDE.md` is the de-facto project primer used at session start (per the repo's own bootstrap convention). The 8-line addition under "Stack" is correctly scoped: registry location, edit flow, schema/loader pointer, env var, consumer list, version. No follow-up needed unless AI Head specifically wants a top-level README.md.

### D2 — Seeded `kbl/__init__.py` from `kbl-a-impl`

**ACCEPT.** Byte-equality verified (Hint 4 above). Documented in:
- Commit `8c7ba12` body
- B1's report §"D2"
- PR #2 description (per task brief)

Rebase post-KBL-A-merge will auto-resolve cleanly. This is the right move — the alternative (waiting for KBL-A merge first) would block SLUGS-1 unnecessarily.

---

## 7. Residual hardcoded slugs — verdict

| Site | B1's call | My call | Reasoning |
|---|---|---|---|
| `scripts/benchmark_ollama_triage.py` | Defer | **N/A — file does not exist in tree.** Drop from residual list. | Not present in `slugs-1-impl` or `origin/main`. B1 listed it from memory. |
| `scripts/present_signal.py` MATTERS keypress map | Defer | **DEFER.** | UI input shorthand (`"1" → "hagenauer-rg7"`). Different consumer; not a canonical-list source of truth. Has the full 19 slugs (8 numbered + 11 in `EXTRA_MATTERS_BY_NAME`), so it's already aligned to the registry — just by hand. |
| `scripts/apply_label.py` MATTER_MENU keypress map | Defer | **DEFER** (with note). | Same UI-shorthand pattern. Already includes the comment "wertheimer removed — now its own slug" so B1 already touched it for SLUGS-1's alias fix awareness. |
| **`tools/document_pipeline.py` PATH_MATTER_HINTS** | Not flagged | **DEFER + ENUMERATE.** | Different vocabulary (display names, not slugs). Maps Dropbox paths to LLM hints. Conceivably foldable into registry as a `paths` field, but that's a registry-schema change, not in scope. Must be flagged for KBL-B. |
| **`orchestrator/context_selector.py` PATTERNS** | Not flagged | **DEFER + ENUMERATE.** | Pre-KBL regex entity detector. Keys (`mandarin-oriental`, `annaberg`, `baden-baden`) don't match canonical slugs. Likely deprecated by KBL pipeline; confirm at KBL-B time. |
| **`memory/store_back.py` matter knowledge dict** | Not flagged | **DEFER + ENUMERATE.** | Large embedded knowledge structure with per-matter people/keywords/projects fields. A different data model (richer than registry). Folding requires schema design, not in SLUGS-1 scope. |

**My overall verdict on residuals:** the three B1 flagged are correctly scoped as deferred (one of which doesn't exist). Three additional residuals were missed. None are SLUGS-1 blockers, but the inventory needs to be complete before KBL-B briefing — see §3 S2.

---

## 8. Test re-run evidence

Fresh clones, isolated venv (`/tmp/bm-b2/.venv`, Python 3.12.12), no contamination from other branches.

```
$ /tmp/bm-b2/.venv/bin/python3 -m pytest tests/test_slug_registry.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 9 items

tests/test_slug_registry.py::test_load_happy_path                         PASSED
tests/test_slug_registry.py::test_duplicate_slug_fails_loudly             PASSED
tests/test_slug_registry.py::test_duplicate_alias_across_slugs_fails_loudly PASSED
tests/test_slug_registry.py::test_normalize_rules                         PASSED
tests/test_slug_registry.py::test_active_slugs_filters_retired            PASSED
tests/test_slug_registry.py::test_is_canonical                            PASSED
tests/test_slug_registry.py::test_missing_env_var_raises                  PASSED
tests/test_slug_registry.py::test_missing_file_raises                     PASSED
tests/test_slug_registry.py::test_describe_and_aliases_for                PASSED

============================== 9 passed in 0.23s ===============================
```

```
# Validator parity (post-refactor, fresh clone, paired baker-vault checkout)
$ BAKER_VAULT_PATH=/tmp/bv-b2 .venv/bin/python3 \
    scripts/validate_eval_labels.py outputs/kbl_eval_set_20260417_labeled.jsonl
50/50 valid

# Pre-refactor (origin/main:scripts/validate_eval_labels.py, no registry)
$ /opt/homebrew/bin/python3.12 /tmp/validate_pre.py outputs/kbl_eval_set_20260417_labeled.jsonl
50/50 valid

# Both 50/50 — IDENTICAL pass set ✓
```

```
# Syntax compile
$ python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in
    ['kbl/slug_registry.py','scripts/validate_eval_labels.py',
     'scripts/run_kbl_eval.py','scripts/build_eval_seed.py',
     'tests/test_slug_registry.py']]; print('all compile clean')"
all compile clean
```

```
# kbl/__init__.py byte-equal verification
$ git show origin/kbl-a-impl:kbl/__init__.py > /tmp/kbla_init.py
$ diff -u /tmp/kbla_init.py /tmp/bm-b2/kbl/__init__.py
(no output)
BYTE-EQUAL ✓
```

---

## 9. Additional verifications

- **Deploy-order failure mode:** `_resolve_yaml_path()` raises `SlugRegistryError` (a `RuntimeError` subclass) on missing env var or missing file. `_get_registry()` is lazy — first public-API call triggers it, not import. **No upstream `try/except` swallow path** in current SLUGS-1 callers (3 manual scripts only). Safe for SLUGS-1; revisit when KBL-B wires automated callers (e.g., scheduler-triggered pipeline_tick.py — flag at brief time).

- **`wertheimer` no longer aliased to `brisen-lp`:** verified in `baker-vault/slugs.yml` — `brisen-lp.aliases = [brisen, "epi bond"]` (no `wertheimer`); `wertheimer` is its own canonical slug. The labeled eval row that previously miscompared (model: "wertheimer", label: "wertheimer") will now correctly match True. Net: SLUGS-1 alone improves matter score by ≥1 row.

- **Hint tiebreak determinism:** `_build_matter_hints()` iterates `sorted(active_slugs())`; `guess_matter_hint()` returns the first match in dict-insertion order (Python 3.7+ guarantee). Alphabetical = stable. Future alias collisions are caught at registry load time, so the tiebreak space is bounded.

- **Alias normalization parity:** `_normalize_key(raw)` is `" ".join(raw.lower().split())` — applied identically to both load-time alias indexing and runtime `normalize()` lookups. Whitespace, case, multi-space all collapse to the same key. Tab characters are split by `.split()` (default whitespace) so they normalize correctly. Unicode: not explicitly handled — German umlauts (`Mü` vs `Mu`) would not auto-fold; if a hypothetical future slug needs umlaut tolerance, add `unicodedata.normalize("NFKD", ...)` then. Not a SLUGS-1 issue.

- **YAML safe_load:** `yaml.safe_load` used (not `yaml.load`), so YAML injection / object-construction attacks are mitigated. Lock invalidation on exception path: `_get_registry()` only sets `_cache` on success — a parse exception leaves `_cache=None`, next call retries cleanly. ✓ thread-safe.

---

## 10. Summary

- **Verdict:** APPROVE.
- **Blockers:** 0.
- **Should-fix:** 2 (S1 missing test for guard; S2 incomplete residual inventory).
- **Nice-to-have:** 4 (sys.path consistency, malformed-YAML test, prompt-cache lifetime note, placeholder descriptions).
- **B1 hints:** 5/5 verified or accepted.
- **Deviations:** 2/2 acceptable as-is.
- **Tests:** 9/9 PASSED. Validator parity 50/50 ↔ 50/50. Compile clean. Byte-equal `kbl/__init__.py` confirmed.

Pattern discipline maintained. Reviewer-separation worked: the missing test (S1) is exactly the kind of thing the implementer wouldn't catch — they wrote the guard correctly, but tests exercise the registry, not the runner that depends on the registry's contract. Same Lesson #34 shape.

Director can merge baker-vault PR #1, then baker-master PR #2, then watch Render redeploy.

---

*Reviewed 2026-04-18 by Code Brisen #2. Fresh clones at `/tmp/bm-b2` (baker-master @ `b24b686`) and `/tmp/bv-b2` (baker-vault @ `367b7de`).*
