# B1 — STEP4_HOT_MD_PARSER_FIX_1 — ship report

**From:** Code Brisen #1
**To:** AI Head (reviewer: B3)
**Date:** 2026-04-22
**Branch:** `step4-hot-md-parser-fix-1`
**Head SHA:** `df13283`
**Status:** SHIPPED — PR open, reviewer B3, full-suite pytest captured, recovery SQL below.

---

## §before/after

### Before (`kbl/steps/step4_classify.py:66-73`)

```python
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_ACTIVE_SLUG_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*\s*:",
    re.MULTILINE,
)
```

Live hot.md heading is `## Actively pressing (elevate — deadline/decision this week)`. The `\s*$` anchor demands the line to end immediately after "pressing" — it does not, so `_ACTIVE_SECTION_RE.search(hot)` returned `None`. `_parse_hot_md_active()` returned `frozenset()` on every call. `allowed_scope` was therefore empty for the duration of the deploy. Rule 1 at `step4_classify.py:287` rejected all 57 live signals with non-null primary_matter as "out-of-scope" and routed them to `skip_inbox` stubs with the boilerplate title `"Layer 2 gate: matter not in current scope"`.

Combo bullets (`**lilienmatt + annaberg + aukera**:`) were also invisible because the slug-line character class `[A-Za-z0-9_\-]+` rejects whitespace and `+` inside the `**...**` fences — so even after the section fix, Lilienmatt would have stayed dark without the second edit.

### After (`kbl/steps/step4_classify.py:66-82`)

```python
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\b[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_ACTIVE_SLUG_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<inner>[^*\n]+)\*\*\s*:",
    re.MULTILINE,
)
_SLUG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
```

And `_parse_hot_md_active` now tokenizes the inner capture group on `+`, strips + lowercases each token, and filters each through `_SLUG_TOKEN_RE` before adding to the set. Non-slug-shape tokens (spaces, Unicode glyphs, orphan punctuation) are silently dropped — no YAML-injection surface and no disambiguation prompt back to the author.

### Behavioral delta against the live vault

```
$ BAKER_VAULT_PATH=/Users/dimitry/baker-vault python3 -c \
  "from kbl.steps.step4_classify import _load_allowed_scope; \
   print(sorted(_load_allowed_scope()))"

# before: []
# after:  ['annaberg', 'ao', 'aukera', 'cap-ferrat', 'corinthia',
#          'hagenauer-rg7', 'lilienmatt', 'm365', 'mo-vie-am', 'nvidia']
```

All 10 Director-declared actively-pressing matters now reach Rule 1 as in-scope. Next scheduler tick will start producing real Opus drafts for new signals in those matters.

---

## §test-matrix

5 new regressions added to `tests/test_step4_classify.py`. Each one targets a specific failure mode or guards a specific backward-compat contract.

| # | Test | Guards |
|---|------|--------|
| 1 | `test_parse_hot_md_live_parenthetical_header` | Live hot.md header shape — `## Actively pressing (...)` must parse. Reproduces the prod bug pre-fix. |
| 2 | `test_parse_hot_md_bare_header_still_parses` | Backward compat — pre-fix header shape continues to parse identically. |
| 3 | `test_parse_hot_md_single_slug_bullet_backward_compat` | Single-slug bullets across dash+underscore slug shapes round-trip unchanged (combo-split must not alter clean slugs). |
| 4 | `test_parse_hot_md_multi_slug_combo_bullet` | `**lilienmatt + annaberg + aukera**:` tokenizes to three slugs. |
| 5 | `test_parse_hot_md_mixed_single_and_multi_slug_bullets` | Live hot.md shape — parenthetical header + single + combo interleaved, honoring next-H2 boundary; leak-check on a subsequent `## Watch list` section. |

All 5 green plus the 7 pre-existing `_parse_hot_md_active` tests plus 34 downstream `_load_allowed_scope` / `_evaluate_rules` / `classify` tests:

```
$ /tmp/b1-venv/bin/pytest tests/test_step4_classify.py -q
..............................................s                          [100%]
46 passed, 1 skipped in 0.10s
```

---

## §test-results (full pytest — no-ship-by-inspection gate)

Run target: `/tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-full.log`

**Environment:** Python 3.12.12, pytest 9.0.3, asyncio mode=STRICT. Repo pins `.python-version=3.12.3`; system Python 3.9 fails collection on `memory/store_back.py` PEP-604 unions, hence the throwaway venv at `/tmp/b1-venv` (system-deps installed from `requirements.txt`).

**Result:** `13 failed, 777 passed, 21 skipped, 9 warnings in 180.11s (0:03:00)`

### Failure triage — all 13 pre-existing on main, none touch my change

```
FAILED tests/test_1m_storeback_verify.py::test_1_dry_run          (FileNotFoundError — storeback checkpoint fixture)
FAILED tests/test_1m_storeback_verify.py::test_2_mock_analysis    (ModuleNotFoundError)
FAILED tests/test_1m_storeback_verify.py::test_3_chunking         (ModuleNotFoundError)
FAILED tests/test_1m_storeback_verify.py::test_4_failure_resilience (ModuleNotFoundError)
FAILED tests/test_clickup_client.py::TestWriteSafety::test_add_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_create_task_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_post_comment_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_remove_tag_wrong_space_raises
FAILED tests/test_clickup_client.py::TestWriteSafety::test_update_task_wrong_space_raises
FAILED tests/test_scan_endpoint.py::test_scan_returns_sse_stream  (assert 401 == 200 — auth env)
FAILED tests/test_scan_endpoint.py::test_scan_rejects_empty_question
FAILED tests/test_scan_endpoint.py::test_scan_accepts_history
FAILED tests/test_scan_prompt.py::test_prompt_is_conversational_no_json_requirement
```

**Pre-existence verification:** stashed my changes, ran the same four test files against `main`:

```
$ /tmp/b1-venv/bin/pytest tests/test_1m_storeback_verify.py tests/test_clickup_client.py tests/test_scan_endpoint.py tests/test_scan_prompt.py
...
============ 13 failed, 10 passed, 4 warnings in 116.50s (0:01:56) =============
```

Identical 13 failures on main. Zero regressions introduced by this PR.

### Full log

Saved to `/tmp/b1-pytest-full.log` (352 lines) on the B1 box. Head + tail below; full log attached in the PR description for B3's audit.

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/Desktop/baker-code
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 811 items
...
tests/test_step4_classify.py ........................................... [ 81%]
...
====== 13 failed, 777 passed, 21 skipped, 9 warnings in 180.11s (0:03:00) ======
```

Our test file at 81% bar — all 46 green on this line.

---

## §recovery

Post-merge, Render auto-deploys the fix. New signals will classify correctly. The 57 pre-existing `skip_inbox` rows must be re-classified manually — AI Head runs under Tier B with Director approval.

### Signal breakdown by primary_matter (queried 2026-04-22)

```
  hagenauer-rg7:  42  ← in-scope (hot.md ACTIVE)
  annaberg:        8  ← in-scope (hot.md ACTIVE, combo bullet)
  lilienmatt:      3  ← in-scope (hot.md ACTIVE, combo bullet)
  (null):          2  ← Rule 1 first-clause; stays skip regardless
  balducci:        1  ← Watch-list only, stays skip
  wertheimer:      1  ← Watch-list only, stays skip
  ───────────────────
  total:          57
```

**Recovery candidates (in-scope only): 53 rows** — 42 Hagenauer + 8 Annaberg + 3 Lilienmatt.

### Recovery SQL (Director auth required)

Run **after** the PR merges and Render redeploys. The UPDATE rewinds state to `awaiting_classify` so the next scheduler tick re-runs Step 4 with the fixed parser, which will route them to FULL_SYNTHESIS or STUB_ONLY per their triage_score. The Silver stubs currently in `opus_draft_markdown` are overwritten by Step 5.

```sql
-- Option A (conservative): recovery for actively-pressing matters only.
UPDATE signal_queue
SET status = 'awaiting_classify',
    step_5_decision = NULL,
    cross_link_hint = FALSE,
    opus_draft_markdown = NULL
WHERE step_5_decision = 'skip_inbox'
  AND primary_matter IN ('hagenauer-rg7', 'annaberg', 'lilienmatt')
  AND status = 'completed';  -- guard: only rewind completed rows
-- Expected: 53 rows updated.

-- Option B (if Director wants the null-matter rows triaged too):
-- Include WHERE primary_matter IS NULL OR primary_matter IN (...); these
-- will re-hit Rule 1 first-clause (primary_matter is None → skip_inbox)
-- and cycle back to the same stub — not recommended unless Step 3 has
-- been hardened on matter extraction.

-- Verification post-update:
SELECT primary_matter, status, COUNT(*)
FROM signal_queue
WHERE primary_matter IN ('hagenauer-rg7', 'annaberg', 'lilienmatt')
GROUP BY primary_matter, status
ORDER BY primary_matter, status;
```

**Short-term unblock alternative (if Director wants content flowing before PR merges):** set `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7,lilienmatt,annaberg,aukera,nvidia,corinthia,ao,mo-vie-am,m365,cap-ferrat` on Render. Takes effect on next deploy. Redundant once this PR lands but useful as a bridge if the merge cycle is delayed.

---

## §delivery checklist

- [x] Branch `step4-hot-md-parser-fix-1` pushed, head `df13283`
- [x] PR opened on baker-master (reviewer B3) — see §pr-url below
- [x] 5 regression tests added per §scope items #3a-#3e
- [x] No schema / bridge / pipeline_tick / step 1-3 / step 5-7 changes
- [x] Full pytest output captured (`/tmp/b1-pytest-full.log`)
- [x] 13 pre-existing failures confirmed unrelated (same set on main)
- [x] Recovery SQL surfaced (§recovery) for AI Head Tier B post-merge
- [x] Timebox: shipped inside 90 min window

---

## §pr-url

https://github.com/vallen300-bit/baker-master/pull/37

— B1, 2026-04-22
