# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** SLUGS-1 S1+S2 shipped on `slugs-1-impl` (commit `4468b68`)
**Task posted:** 2026-04-18
**Status:** OPEN — urgent (unblocks SLUGS-1 merge)
**Supersedes:** S1+S2 task (shipped)

---

## Task: Rebase `slugs-1-impl` on main + resolve `run_kbl_eval.py` 3-way merge

### Context

Director and AI Head pushed merges through KBL-A + baker-vault first. SLUGS-1 PR #2 (`slugs-1-impl`) is now **CONFLICTING** on `scripts/run_kbl_eval.py`. Blocks merge.

The conflict:

- **Main** has commit `aba04d6` — B3's v3 eval prompt (semantic glossary, 18-slug list, vedana rule, null-handling fix). `STEP1_PROMPT` is static.
- **Your branch `slugs-1-impl`** has commit `5f53ee0` — refactored `STEP1_PROMPT` into dynamic `_build_step1_prompt()` that enumerates from `slug_registry`.

Both edits land on the same prompt region. Rebase needs 3-way merge.

### Desired result

`_build_step1_prompt()` on rebased branch must produce a prompt functionally equivalent to B3's v3 static glossary prompt — dynamic from registry, containing:

1. **Full slug enumeration** via `active_slugs()` (already in your function)
2. **Per-slug descriptions** via `registry.describe(slug)` — forms the semantic glossary (this is the v3 addition — pull from main's `STEP1_PROMPT` content + migrate to `registry.describe()` calls)
3. **Verbatim vedana rule block** — copy from main's `STEP1_PROMPT` verbatim as a static string inside the function
4. **Disambiguation rules** — copy from main's `STEP1_PROMPT` (e.g., "brisengroup.com header ≠ brisen-lp", "hagenauer-rg7 vs cupial", "kitzbuhel-six-senses vs steininger")
5. **Generic-category reject list** — copy from main (`"hospitality"`, `"investment"`, `"legal"`)
6. **`null` permitted** explicit language
7. **Null-handling fix** (string `"null"`/`"none"` → Python None) — must survive the rebase (should already be in `slug_registry.normalize()`; verify)

Your `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` is the production reference — aligned with what B3 had in mind. The eval runner prompt should match that spec.

### Procedure

```bash
git fetch origin
git checkout slugs-1-impl
git rebase origin/main
# When conflict hits in scripts/run_kbl_eval.py:
# - Accept your _build_step1_prompt() structure as base
# - Port v3's glossary + vedana + disambiguation into the function body
# - git add scripts/run_kbl_eval.py
# - git rebase --continue
```

Run tests:

```bash
.venv/bin/python3 -m pytest tests/test_slug_registry.py tests/test_score_row.py -v
# All 15 should remain green
```

Verify prompt output:

```python
# Quick smoke: _build_step1_prompt() output contains all 19 slug descriptions
from kbl.slug_registry import active_slugs
from scripts.run_kbl_eval import _build_step1_prompt  # or wherever it lives
p = _build_step1_prompt()
assert len(active_slugs()) == 19
for slug in active_slugs():
    assert slug in p  # every slug mentioned
    # ideally: assert registry.describe(slug) is somewhere in p
assert "opportunity" in p and "threat" in p and "routine" in p  # vedana rule present
assert "brisen-lp" in p  # disambiguation content
```

### Push

```bash
git push --force-with-lease origin slugs-1-impl
```

**`--force-with-lease`** not `--force` — safety against racing pushes.

### Deliverable

- PR #2 becomes `mergeable: CLEAN` again
- 15/15 tests green
- `_build_step1_prompt()` produces glossary-rich content

### Report

One-liner:

> B1 slugs-1-impl rebased — conflict resolved on scripts/run_kbl_eval.py, PR #2 now CLEAN, 15/15 tests green, commit `<SHA>`. Ready for Director merge.

Short report at `briefs/_reports/B1_slugs1_rebase_20260418.md` only if anything unexpected surfaced.

### Scope guardrails

- **Do NOT** add N1-N4 nice-to-haves. Rebase + conflict resolution only.
- **Do NOT** re-run D1 eval against the rebased code (B3 is stood down, D1 ratified).
- **Do NOT** touch any other file during rebase other than the conflict.

---

## Est. time

~15 min.

---

*Dispatched 2026-04-18 by AI Head.*
