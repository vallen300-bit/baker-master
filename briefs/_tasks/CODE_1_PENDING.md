# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** TCC fix + DATABASE_URL shipped (PR #3 in review, 1P item live)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** TCC + DB_URL task (shipped)

---

## Task: SLUGS-1 S1 + S2 Cleanup

Should-fix items B2 flagged in the original SLUGS-1 review (`briefs/_reports/B2_slugs1_review_20260417.md`). Small cleanup before they rot. ~30 min combined.

### Deliverable 1 — S1: test for `score_row` `unknown_non_canonical` guard

**Context:** `kbl/slug_registry.py` has `normalize()` returning None for unknown slugs. But `run_kbl_eval.py`'s `score_row` has an explicit `unknown_non_canonical` guard that prevents a model outputting an unknown slug like `"hospitality"` from spuriously matching a label of `None`. The registry tests don't cover this contract dependence — it's a runtime invariant that lives in the eval runner, not the registry.

**Fix:** Add a test at `tests/test_run_kbl_eval.py` (new file) that exercises the invariant:

```python
# pseudocode
def test_unknown_non_canonical_scores_false():
    # model outputs "hospitality" (unknown), label says primary_matter is None
    # expected: matter_ok = False (because model hallucinated a matter where truth is null)
    result = score_row(
        label={"primary_matter_expected": None, ...},
        parsed={"matter": "hospitality", ...}  # unknown string
    )
    assert result["matter_ok"] is False

def test_unknown_non_canonical_still_catches_legitimate_nulls():
    # model outputs None, label is None
    # expected: matter_ok = True (both null, aligned)
    ...

def test_alias_normalization_still_works():
    # model outputs "Hagenauer" (alias), label is "hagenauer-rg7"
    # expected: matter_ok = True (normalize() resolves alias)
    ...
```

Aim for 3-4 cases covering: unknown-string-vs-null-label, null-vs-null, alias-match, canonical-match.

### Deliverable 2 — S2: catalogue 3 residual hardcoded slug sites

**Context:** B2 noted B1's original SLUGS-1 residual list missed 3 sites in `tools/`, `orchestrator/`, `memory/`. The original task-brief scope was the 3 explicit consumers (`validate_eval_labels.py`, `run_kbl_eval.py`, `build_eval_seed.py`) — those 3 are clean. The other 3 may or may not need registry migration.

**Fix:**

1. Grep the 3 directories for hardcoded slug references:

```bash
grep -rn "hagenauer-rg7\|cupial\|mo-vie\|brisen-lp\|wertheimer\|aukera" tools/ orchestrator/ memory/ 2>&1 | grep -v __pycache__ | head -30
```

2. For each hit, classify:
   - **UI/keypress map** (like `present_signal.py` 1→hagenauer-rg7): stays as-is, not a registry concern
   - **Canonical-list duplication**: migrate to `kbl.slug_registry.canonical_slugs()` — open follow-up PR
   - **Documentation/comment**: leave alone

3. File a catalogue at `briefs/_drafts/SLUGS_2_RESIDUAL_CATALOGUE.md`:
   - Table: file:line, current reference, classification, action (keep / migrate / delete)
   - Summary: count per classification, total migrate-needed
   - Recommendation: fold migrations into one small follow-up PR OR defer to per-file basis

**Do NOT** actually migrate in this task. Catalogue + recommendation only. Migration is a separate dispatch.

### Report

File: `briefs/_reports/B1_slugs1_s1_s2_20260418.md`

- Deliverable 1: test file PR URL + pytest output showing new tests green
- Deliverable 2: catalogue file path + count-per-classification summary + recommendation (fold-all-in-one vs per-file)

### Dispatch back

> B1 S1+S2 done — see `briefs/_reports/B1_slugs1_s1_s2_20260418.md`, commit `<SHA>`. Test PR: `<URL>`. Catalogue: `<N>` sites in 3 dirs, `<M>` need migrate.

### Scope guardrails

- **Do NOT** migrate residual hardcoded slugs in this task. Catalogue only.
- **Do NOT** touch KBL-B files (that's the §6-13 authoring in flight).

---

## Est. time

~30 min:

- 15 min S1 test file
- 10 min S2 grep + catalogue
- 5 min report + PR

---

*Dispatched 2026-04-18 by AI Head.*
