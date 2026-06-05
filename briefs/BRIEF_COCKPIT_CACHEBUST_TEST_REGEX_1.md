# BRIEF — COCKPIT_CACHEBUST_TEST_REGEX_1

**Task class:** test refactor (test-only, no app/runtime change)
**Complexity:** trivial
**Priority:** tier-b, low-pri
**Target repo:** baker-master
**Anchor:** b1 flag in POST_DEPLOY_AC_VERDICT (bus #1926) — COCKPIT_UX_S4_S3_FIX_1 had to hand-bump pinned version literals; test re-breaks on every future cache-bust.

## Context
During COCKPIT_UX_S4_S3_FIX_1 (PR #299), b1 found `test_pending_tab_button_in_static_index_html` RED at HEAD because it pins exact cache-bust versions, and the prior bump left stale literals (v77/v118 vs committed v79/v123). b1 hand-edited them to v80/v123 to ship, then flagged the pattern: the test mis-fires on every cache-bust and forces an unrelated edit into otherwise-clean PRs. This brief converts the assertion to be version-agnostic.

### Surface contract: N/A — test-only refactor, no rendered UI surface touched.

## Problem
`tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html` (lines ~120-126) pins **exact** cache-bust versions:
```python
assert "app.js?v=123" in src
assert "style.css?v=80" in src
```
Every CSS/JS cache-bust bump turns this test RED until someone hand-edits the literals. The test's real intent is "a cache-bust param is present on each asset," not "the param equals exactly v80/v123."

## Current State
`tests/test_dashboard_cortex_ratify.py` lines 120-126 (verified on origin/main):
```python
def test_pending_tab_button_in_static_index_html():
    src = Path("outputs/static/index.html").read_text()
    assert 'id="cortexTabPending"' in src
    assert "_cortexTab('pending')" in src
    # Cache-bust present (literals updated by COCKPIT_UX_S4_S3_FIX_1: style.css->v80; app.js at v123)
    assert "app.js?v=123" in src
    assert "style.css?v=80" in src
```

## Implementation
Replace ONLY the two exact-equality version asserts with version-agnostic regex assertions. Keep the two presence asserts (`id="cortexTabPending"`, `_cortexTab('pending')`) unchanged.

```python
import re  # add at TOP of file (module-scoped) if not already imported — check the import block first
...
    # Cache-bust param present on each asset (version-agnostic — survives future bumps)
    assert re.search(r"app\.js\?v=\d+", src), "app.js cache-bust param missing"
    assert re.search(r"style\.css\?v=\d+", src), "style.css cache-bust param missing"
```

## Key Constraints
- Test-only. Do NOT touch `outputs/static/index.html`, `app.js`, `style.css`, or any runtime file.
- Do NOT weaken or remove the two existing presence asserts.
- Regex must still FAIL if the `?v=` cache-bust is absent entirely (it guards presence, not just format).
- `import re` module-scoped at top of file if the file style favors top imports — verify the existing import block first; do not add a function-local import if a top-level one already exists.

## Verification
1. `python3.12 -m pytest tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html -v` → PASS against current `index.html` (v80/v123).
2. Negative check: in a LOCAL scratch copy of `index.html`, strip `?v=80` from the style.css ref → confirm the test FAILS (proves it still guards presence). Revert — do not commit the scratch edit.
3. Future-proof: a hypothetical bump to `?v=81` / `?v=124` would PASS with no test edit (reason about the regex; no code change needed to prove).
4. Full file collects + runs clean: `python3.12 -m pytest tests/test_dashboard_cortex_ratify.py` → no new failures.
5. `git diff --stat` shows ONLY `tests/test_dashboard_cortex_ratify.py` changed.

## Files Modified
- `tests/test_dashboard_cortex_ratify.py` — two version-pinned asserts → regex; comment updated; `import re` if absent.

## Do NOT Touch
- `outputs/static/index.html`, `outputs/static/app.js`, `outputs/static/style.css` — runtime assets, out of scope.
- Any other test or the two non-version asserts in the same function.

## Gate plan
G1 lead literal pytest (Verification #1) → light G2 → ship PR. Test-only; no deploy-surface change, so no POST_DEPLOY_AC required.

## Return
`briefs/_reports/CODE_1_RETURN.md` + PR number on bus to lead. Heads-up: default `python3` here is 3.9 and breaks collection (`int|None`) — use `python3.12`.
