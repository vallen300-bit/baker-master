# BRIEF: PM_EXTRACTION_JSON_ROBUSTNESS_1 — make Opus extraction survive real-world JSON

## Context

Hot-fix surfaced during Phase 1 (PR #50) post-merge verification 2026-04-23. `extract_and_update_pm_state` in `orchestrator/capability_runner.py:~188` (post-refactor) inherits a **pre-existing fragility**: `json.loads(raw)` on Opus's `resp.content[0].text` fails silently on rich-content extractions. Confirmed 5/5 failures on real ao_pm conversations with error class *"Expecting property name enclosed in double quotes"* (Opus emitting unquoted keys and/or truncating at `max_tokens=700`).

**Production impact:** silent for 11+ days. Last successful `opus_auto` row in `pm_state_history` is 2026-04-12 for ao_pm; zero ever for movie_am. `logger.debug(...)` on the outer `except Exception` has been swallowing the errors since `_auto_update_pm_state` shipped.

**Program alignment:** Phase 1 plumbing (D1-D6) is live but the 14-day backfill (D4) produces 0 rows. Phase 2 (`BRIEF_CAPABILITY_THREADS_1`) drafts are gated on this hot-fix merging AND the backfill re-running successfully (Director directive 2026-04-23).

---

## Estimated time: ~2-3h Code Brisen
## Complexity: Low
## Prerequisites:
- baker-master main at `596f1861` (PR #50 MERGED) ✓
- `scripts/check_singletons.sh` green ✓
- Python env with test harness per prior PRs

---

## Scope table

| Deliverable | What | Where |
|---|---|---|
| **D0** | Grep audit of `except Exception: logger.debug(...)` in state/extraction paths — catalog only, NO fixes in this brief | `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` (NEW) |
| **D1** | Raise `max_tokens` from 700 → 1500 in `extract_and_update_pm_state` | `orchestrator/capability_runner.py` |
| **D2** | Add a robust JSON parser helper (mirrors `orchestrator/extraction_engine.py:554` `_parse_json_object` pattern) + add a JSON-repair pass for Opus's two common malformations (unquoted property names, trailing commas) | `orchestrator/capability_runner.py` |
| **D3** | Wire the robust parser into `extract_and_update_pm_state` in place of the current `json.loads(raw)` | `orchestrator/capability_runner.py` |
| **D4** | Promote log level on ALL extraction-failure paths found by D0 audit (`logger.debug → logger.warning` with error class + raw-text sample) in THIS brief's scope if <=5 sites. If >5, fold into follow-up brief and document reason in D0 appendix. | `orchestrator/capability_runner.py` (+ any other files D0 surfaces) |
| **D5** | Unit tests: 4 JSON-parse scenarios (well-formed / unquoted keys / trailing comma / truncated-mid-object) + 1 end-to-end test exercising extract_and_update_pm_state against a malformed-then-repaired fixture | `tests/test_pm_extraction_robustness.py` (NEW) |

---

## Fix/Feature 0: Step 0 audit (catalog only — no fixes)

### What to do

```bash
cd ~/bm-b3
grep -rn "except Exception" orchestrator/ triggers/ outputs/ memory/ \
    --include="*.py" -A 1 \
    | grep -B 1 "logger\.debug" \
    | grep -v "^--$"
```

Classify each hit into one of three buckets:

| Bucket | Action |
|---|---|
| **A — Extraction failure (LLM JSON parse, regex extract, prompt→JSON roundtrip)** | In scope of D4 (promote to `logger.warning`) |
| **B — State-write failure (DB write, pool acquisition, commit)** | In scope of D4 IF the function is user-visible state-writer; OUT of scope if truly non-fatal plumbing |
| **C — Non-critical ancillary failure (metrics logging, cost tracking, decomposition logging)** | OUT of scope — keep at `debug` |

Write report to `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md`. Table format:

```markdown
| file:line | function | category | fix in D4? | reason |
|---|---|---|---|---|
| orchestrator/capability_runner.py:408 | extract_correction_from_feedback | A | ... | ... |
| orchestrator/capability_runner.py:1326 | ... | ... | ... | ... |
| ... | ... | ... | ... | ... |
```

### Known seed entries (from AI Head prep grep)

These MUST appear in your audit — verify you caught them and classify:

- `orchestrator/capability_runner.py:408` — `Correction extraction failed` (likely Bucket A)
- `orchestrator/capability_runner.py:911` — `Decomposition logging failed` (likely Bucket C)
- `orchestrator/capability_runner.py:1326` — `Auto-insight extraction failed` (likely Bucket A)
- `orchestrator/capability_runner.py:1356` — `Russo document store failed` (likely Bucket B)
- `orchestrator/capability_runner.py:1900` — `Pending insight storage failed` (likely Bucket B)
- the new `extract_and_update_pm_state` (at ~line 188 post-PR-50) — Bucket A, primary target

If your grep surfaces additional Bucket A hits NOT in this list: add them to D4 in-scope. If >5 Bucket A total, stop — flag in D0 report for a follow-up brief.

### Key constraints

- **READ-ONLY in D0.** No edits to any file during D0.
- **Bucket C stays debug.** The rule is: "fail silent is OK if it's not a user-visible semantic operation." Metrics, cost tracking, decomposition logging fall here.

---

## Fix/Feature 1: Raise max_tokens

### Current (verified)

`orchestrator/capability_runner.py` — `extract_and_update_pm_state` calls `claude.messages.create(model="claude-opus-4-6", max_tokens=700, ...)`. Observed real-world responses reach ~2250 chars (~500-600 tokens) before truncation, which is enough to start valid JSON but produces a truncated final object.

### Implementation

Single-line change in the module-level `extract_and_update_pm_state` function:

```python
# Before
resp = claude.messages.create(
    model="claude-opus-4-6",
    max_tokens=700,
    ...
)

# After
resp = claude.messages.create(
    model="claude-opus-4-6",
    max_tokens=1500,
    ...
)
```

### Key constraint

- **Do NOT raise the corresponding `max_tokens=700` in the preserved `_auto_update_pm_state` delegator wrapper** — that wrapper is an 11-line delegator post-PR-50 and calls `extract_and_update_pm_state` which is the only site making the API call. Verify this before editing.
- Cost impact: ~2x output tokens × ~$0.075/1M output = negligible (~$0.001/call).

---

## Fix/Feature 2: Robust JSON parser helper

### Problem

Opus is emitting two classes of malformed JSON:
1. **Unquoted property names** — `{sub_matters: {}, red_flags: [...]}` instead of `{"sub_matters": {}, "red_flags": [...]}`
2. **Trailing commas** — `{"x": 1, "y": 2,}` instead of `{"x": 1, "y": 2}`

Markdown code fences (`\`\`\`json ... \`\`\``) are ALREADY handled by the existing strip at `capability_runner.py:~` (search for `if raw.startswith("```"):`).

`orchestrator/extraction_engine.py:554` has a `_parse_json_object(text)` pattern we should mirror (cascade: direct → code-fence → bare regex match → `{}`).

### Implementation

Add a module-level helper to `orchestrator/capability_runner.py` directly BEFORE `extract_and_update_pm_state` (so around the same location ~line 185-187). Reuse Standard library — no new pip dependencies:

```python
def _robust_json_parse_object(text: str) -> dict | None:
    """Parse a JSON object from LLM response text.

    Cascade:
      1. Direct json.loads
      2. Strip markdown code fence + json.loads
      3. Regex-extract first {...} span + json.loads
      4. Apply two repair passes (add quotes to unquoted keys,
         strip trailing commas) + json.loads
      5. Return None (caller logs at warning level with raw sample)

    Mirrors orchestrator/extraction_engine.py:554 _parse_json_object
    with an added repair pass for Opus's two common malformations.
    """
    import json as _json
    import re as _re

    if not text:
        return None

    # Pass 1 — direct
    try:
        result = _json.loads(text)
        if isinstance(result, dict):
            return result
    except _json.JSONDecodeError:
        pass

    # Pass 2 — strip markdown fence
    stripped = text
    if stripped.startswith("```"):
        stripped = "\n".join(stripped.split("\n")[1:-1])
    if stripped != text:
        try:
            result = _json.loads(stripped)
            if isinstance(result, dict):
                return result
        except _json.JSONDecodeError:
            pass

    # Pass 3 — extract first {...} span greedy
    match = _re.search(r"\{.*\}", stripped, _re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            result = _json.loads(candidate)
            if isinstance(result, dict):
                return result
        except _json.JSONDecodeError:
            # Pass 4 — repair unquoted keys + trailing commas, then retry
            repaired = candidate
            # Unquoted property names: find {key: or ,key: patterns and quote
            repaired = _re.sub(
                r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)",
                r'\1"\2"\3',
                repaired,
            )
            # Trailing commas before } or ]
            repaired = _re.sub(r",(\s*[}\]])", r"\1", repaired)
            try:
                result = _json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except _json.JSONDecodeError:
                pass

    return None
```

### Key constraints

- **Return type is `dict | None`**, NOT `{}`. Caller needs to distinguish "Opus returned empty state" from "parse failed". `{}` conflates the two.
- **No new pip deps.** `json-repair` / `json5` would add one more package to maintain. The two-rule regex repair handles the observed failure modes. If future failures need more sophisticated repair, that's a follow-up.
- **Mirror `extraction_engine.py:554` style** for code review consistency.

---

## Fix/Feature 3: Wire the helper

### Current

```python
raw = resp.content[0].text.strip()
if raw.startswith("```"):
    raw = "\n".join(raw.split("\n")[1:-1])
updates = _json.loads(raw)

wiki_insights = updates.pop("wiki_insights", [])
summary = updates.pop("summary", f"{label} interaction")
```

### After

```python
raw = resp.content[0].text.strip()
updates = _robust_json_parse_object(raw)
if updates is None:
    logger.warning(
        f"Opus extraction JSON parse failed [{pm_slug}][{mutation_source}]: "
        f"raw length={len(raw)}, preview={raw[:200]!r}"
    )
    return None

wiki_insights = updates.pop("wiki_insights", [])
summary = updates.pop("summary", f"{label} interaction")
```

### Key constraints

- **Do NOT remove the existing outer `try/except` wrapping the whole function** — it still guards against DB errors, Anthropic SDK errors, etc. Only replace the `_json.loads(raw)` site.
- **Delete the redundant markdown-fence strip** — `_robust_json_parse_object` handles it. Net diff: 3 lines removed, 6 lines added.

---

## Fix/Feature 4: Promote log level on extraction-failure paths

### Problem

D0 catalogues ≥1 Bucket A silencer. The new `extract_and_update_pm_state` already has one `logger.debug` on its outer catch; D3 already promotes the JSON-specific one to `warning`. D4 covers the remaining Bucket A sites.

### Implementation

For each Bucket A site from D0 that's ≤5 in count:

```python
# Before
except Exception as e:
    logger.debug(f"<original message>: {e}")

# After
except Exception as e:
    logger.warning(
        f"<original message> [error_class={type(e).__name__}]: {e}"
    )
```

Include `type(e).__name__` so future forensics can grep for `JSONDecodeError` vs `anthropic.APIError` vs `psycopg2.OperationalError` without reading prose.

### Key constraints

- **If D0 surfaces >5 Bucket A sites, STOP and write the overflow to a follow-up brief.** Director directive: "if you find other silent swallows in (a), promote them in this brief's scope (small enough) OR queue follow-up brief." Use judgment — 5 is the threshold. Record reason in D0 report.
- **Bucket B (state-write) and Bucket C (ancillary) are OUT of scope.** Do not touch `debug` level on those lines.

---

## Fix/Feature 5: Tests

### File

`tests/test_pm_extraction_robustness.py` — 5 tests minimum:

```python
"""Tests for BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1."""
from orchestrator.capability_runner import _robust_json_parse_object


def test_parse_well_formed_json_object():
    text = '{"sub_matters": {}, "summary": "ok"}'
    assert _robust_json_parse_object(text) == {"sub_matters": {}, "summary": "ok"}


def test_parse_json_in_markdown_fence():
    text = '```json\n{"red_flags": ["x"], "summary": "y"}\n```'
    result = _robust_json_parse_object(text)
    assert result == {"red_flags": ["x"], "summary": "y"}


def test_parse_unquoted_property_names():
    # Opus's most common malformation on dense extractions
    text = '{sub_matters: {}, red_flags: ["trust risk"], summary: "ok"}'
    result = _robust_json_parse_object(text)
    assert result is not None
    assert "red_flags" in result


def test_parse_trailing_comma():
    text = '{"a": 1, "b": 2,}'
    result = _robust_json_parse_object(text)
    assert result == {"a": 1, "b": 2}


def test_parse_unparseable_returns_none():
    text = "not even close to JSON"
    assert _robust_json_parse_object(text) is None
```

### Constraint

- 5 tests is the minimum. If you add the stretch end-to-end test (`extract_and_update_pm_state` against a fixture Anthropic response), mock `claude.messages.create` and assert `update_pm_project_state` is called with extracted fields.

---

## Files Modified

- `orchestrator/capability_runner.py` — D1 max_tokens bump + D2 helper + D3 wire + D4 log promotions
- `tests/test_pm_extraction_robustness.py` — NEW (D5)
- `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` — NEW (D0)

## Do NOT Touch

- `_auto_update_pm_state` delegator wrapper — post-PR-50 it is an 11-line shim; leave alone
- `scripts/backfill_pm_state.py` — zero changes (this brief fixes the extractor; re-run is post-merge AI Head action)
- `outputs/dashboard.py` sidebar hooks — zero changes
- Any Bucket B / Bucket C `logger.debug` line from D0 audit
- `orchestrator/extraction_engine.py` `_parse_json_object` — we mirror its pattern, don't edit it
- PM_REGISTRY, schema, Anthropic SDK version — all untouched

## Ship Gate (literal pytest)

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
# expected 5 passes:
# test_parse_well_formed_json_object
# test_parse_json_in_markdown_fence
# test_parse_unquoted_property_names
# test_parse_trailing_comma
# test_parse_unparseable_returns_none
```

Regression delta vs main @ `596f1861`:
```
$ python3 -m pytest 2>&1 | tail -3
# branch passes = main passes + 5 (new tests)
# branch failures == main failures (zero regressions)
```

## Quality Checkpoints

1. `_robust_json_parse_object` returns `None` on unparseable — NOT `{}` (per D2 constraint)
2. `max_tokens=1500` — literal integer, not env-var-sourced
3. Log promotion includes `type(e).__name__` (forensic grep anchor)
4. D0 audit report covers `orchestrator/`, `triggers/`, `outputs/`, `memory/` dirs
5. D4 site count ≤5; if >5, overflow queued in follow-up brief noted in D0 report
6. Ship-gate pytest emits literal 5/5 — no "by inspection"

## Part H compliance

This brief modifies the `client_pm` (ao_pm, movie_am) extraction path. Part H §H1–H5 still apply but the invocation-path inventory is UNCHANGED from PR #50's brief — same 6 callers, same tags. No re-audit required; cite PR #50's Part H audit by reference in the PR body.

## Post-merge sequence (AI Head executes per standing auth)

1. `/security-review` on PR diff
2. Merge on APPROVE + green ship gate (Tier A)
3. Wait Render deploy live
4. **Re-run backfill** (Director-specified acceptance gate for Phase 2 unlock):
   ```bash
   cd ~/Desktop/baker-code && git pull --rebase origin main
   source /tmp/bv312/bin/activate
   export DATABASE_URL=$(op item get t77jpmwqxwlm2x32jhcup7vjie --vault "Baker API Keys" --fields credential --reveal)
   python scripts/backfill_pm_state.py ao_pm --since 14d --dry-run
   python scripts/backfill_pm_state.py ao_pm --since 14d
   python scripts/backfill_pm_state.py movie_am --since 14d
   ```
5. Verification SQL:
   ```sql
   SELECT pm_slug, mutation_source, COUNT(*), MAX(created_at)
   FROM pm_state_history
   WHERE mutation_source LIKE 'backfill_%'
   GROUP BY pm_slug, mutation_source;
   ```
   Expected: ≥3 rows for ao_pm (Aukera + capital call + open actions), ≥0 for movie_am (depends on content match).
6. Slack push to Director with backfill row counts + Phase 2 unlock signal
7. Scratch closeout

## Observation for follow-up brief

- `orchestrator/agent.py:2031` still missing `mutation_source=` kwarg (surfaced during PR #50 B2 review). Not this brief's scope. Queue for a TEMPLATE_H_COMPLIANCE_1 follow-up if Director wants it sorted before Phase 2.

## Acceptance criteria (brief-level)

- `_robust_json_parse_object` added as module-level function, public-callable from outside the module (no leading underscore? — OK, leading underscore keeps it module-private which is correct for a helper)
- D0 report exists at `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` with filled classification table
- `max_tokens` literal constant `1500` at the extract_and_update_pm_state call site
- Ship-gate pytest shows literal 5/5 green
- Full-suite regression delta = 0 failures / 0 errors vs main
- Part H compliance by reference — no re-audit required
