# CODE_2_RETURN — PM_EXTRACTION_JSON_ROBUSTNESS_1 — 2026-04-23

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `hotfix/pm-extraction-json-robustness-1`
**Brief:** `briefs/BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1.md`
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `1cd2480`)
**Base:** main @ `f054da7` (13 commits ahead of PR #50 merge `596f1861`, all unrelated to the extractor path)

---

## 8-check format

### 1. Ship gate — literal output

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
collected 5 items

tests/test_pm_extraction_robustness.py::test_parse_well_formed_json_object PASSED [ 20%]
tests/test_pm_extraction_robustness.py::test_parse_json_in_markdown_fence PASSED [ 40%]
tests/test_pm_extraction_robustness.py::test_parse_unquoted_property_names PASSED [ 60%]
tests/test_pm_extraction_robustness.py::test_parse_trailing_comma PASSED [ 80%]
tests/test_pm_extraction_robustness.py::test_parse_unparseable_returns_none PASSED [100%]

============================== 5 passed in 0.17s ===============================
```

### 2. Full-suite regression delta

```
Baseline (main @ f054da7, excluding tests/test_tier_normalization.py collection-only TypeError bug):
  810 passed, 24 failed, 21 skipped, 31 errors

Branch (hotfix/pm-extraction-json-robustness-1):
  815 passed, 24 failed, 21 skipped, 31 errors

Delta: +5 passes = 5 new tests in tests/test_pm_extraction_robustness.py.
Failures: 24 == 24 (zero regressions).
Errors:   31 == 31 (zero regressions).
```

Measurement method: `git stash -u` the branch's working tree, ran pytest on main HEAD files, captured baseline, then `git stash pop` and re-ran ship gate on the restored branch state. Re-verified new-test green count post-restore.

### 3. Per-deliverable summary

| Deliverable | File | Change |
|---|---|---|
| D0 | `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` (NEW) | Grep audit table covering `orchestrator/`, `triggers/`, `outputs/`, `memory/`. 3 Bucket A in `capability_runner.py` (all in D4); 9 additional Bucket A overflow (trigger layer) queued for `LOGGER_LEVEL_PROMOTE_TRIGGERS_1` follow-up per brief §D4 rule (`>5 total → overflow`). Bucket B / C untouched. |
| D1 | `orchestrator/capability_runner.py` | Single-token change `max_tokens=700` → `max_tokens=1500` in `extract_and_update_pm_state` claude.messages.create call (current line 309). `_auto_update_pm_state` delegator untouched (it has no API call — it forwards to the extractor). |
| D2 | `orchestrator/capability_runner.py` | New module-level helper `_robust_json_parse_object(text) -> dict \| None` inserted immediately before `extract_and_update_pm_state`. 4-pass cascade: direct / fence-strip / `{...}` regex / Pass-4 repair (quote unquoted keys + strip trailing commas). Returns `None` on total failure, NOT `{}`. Mirrors `orchestrator/extraction_engine.py:554` style. Uses `re.IGNORECASE`-free repair regex (no inline flags). Zero new pip deps. |
| D3 | `orchestrator/capability_runner.py` | Replaced `updates = _json.loads(raw)` with `updates = _robust_json_parse_object(raw)` + `if updates is None: logger.warning(...); return None`. Deleted the now-redundant `if raw.startswith("```"): raw = "\n".join(raw.split("\n")[1:-1])` — the helper handles fences. Deleted the now-unused function-level `import json as _json`. Outer try/except preserved. |
| D4 | `orchestrator/capability_runner.py` | 3 Bucket-A sites promoted `logger.debug` → `logger.warning` with `[error_class={type(e).__name__}]` forensic anchor: (i) `extract_and_update_pm_state` outer catch, (ii) `extract_correction_from_feedback` outer catch, (iii) `CapabilityRunner._maybe_store_insight` outer catch. Bucket B (Russo document store, pending-insight storage) + Bucket C (decomposition logging) left at `debug` per brief rule. |
| D5 | `tests/test_pm_extraction_robustness.py` (NEW) | 5 tests per brief §D5 — well-formed / markdown-fence / unquoted keys / trailing comma / unparseable-returns-None. All 5 green in 0.17s. |

### 4. Files modified vs Files Modified list

| Brief §Files Modified entry | This PR? | Notes |
|---|---|---|
| `orchestrator/capability_runner.py` | ✅ | D1 + D2 + D3 + D4 |
| `tests/test_pm_extraction_robustness.py` (NEW) | ✅ | D5 |
| `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` (NEW) | ✅ | D0 |

Zero other files touched.

### 5. Do NOT Touch — verified untouched

```
$ git diff main..hotfix/pm-extraction-json-robustness-1 -- \
    scripts/backfill_pm_state.py outputs/dashboard.py \
    orchestrator/extraction_engine.py memory/store_back.py | wc -l
0
```

`_auto_update_pm_state` 11-line delegator wrapper: confirmed unchanged (it
forwards to `extract_and_update_pm_state` and carries no `max_tokens`
literal of its own). PM_REGISTRY, schema, Anthropic SDK version: all
untouched.

### 6. Rule compliance (SKILL Rules 7 / 8 / 10 / python-backend)

- **Rule 7 (file:line verify).** Every cited line verified pre-edit:
  - `orchestrator/extraction_engine.py:554` style mirror confirmed ✓ (cascade shape + `re.DOTALL` + graceful fall-through)
  - `capability_runner.py` current-state anchors confirmed: `extract_and_update_pm_state` at line 188 (post-PR-50) ✓; claude.messages.create `max_tokens=700` at line 236 ✓; outer except at line 314-318 ✓; `extract_correction_from_feedback` outer except at 407-408 ✓; `_maybe_store_insight` outer except at 1325-1326 ✓
  - Seed list from brief §D0 `911 / 1326 / 1356 / 1900` all confirmed + classified ✓
- **Rule 8 (singleton).** `bash scripts/check_singletons.sh` green. No new `SentinelStoreBack()` constructs; the existing `_get_global_instance()` path inside `extract_and_update_pm_state` is untouched.
- **Rule 10 (Part H).** Invocation path unchanged from PR #50 — same 6 callers, same `mutation_source` tags. PR body cites PR #50's Part H audit by reference per brief instruction.
- **Python regex (python-backend.md).** Both Pass-4 repair regexes use the Python `flags=` arg (`_re.DOTALL`) or no flags; no inline `(?i)` used. Forensic-anchor messages include `type(e).__name__` — the grep token the brief specified.

### 7. Python-backend quality checks

- **No new SQL.** D0 audit is read-only; D1-D4 edit Python only.
- **No `conn.rollback()` changes needed.** Bucket B state-write sites (Russo + pending-insight) were left at `debug` per brief scope rule; the inner DB try/excepts there already rollback.
- **Parser returns `None`, not `{}`** — verified by `test_parse_unparseable_returns_none`. Callers can distinguish "Opus emitted empty state" from "parse failed."
- **Model-client-response triple preserved** (Lesson #13): `claude-opus-4-6` + `anthropic.Anthropic(...).messages.create(...)` + `resp.content[0].text`. Only `max_tokens` literal changed.
- **No new pip deps.** `_robust_json_parse_object` uses stdlib only (`json`, `re`).

### 8. Observations for follow-up (non-blocking)

- **9 trigger-layer Bucket-A silencers queued** for a follow-up brief `LOGGER_LEVEL_PROMOTE_TRIGGERS_1` — catalogued in `EXCEPT_DEBUG_AUDIT_20260423.md` §Overflow. Covers Plaud deadline/commitment/Director-commitment extraction, ClickUp deadline extraction, YouTube meeting signal detection, dashboard duplicate correction silencer. Promoting them all here would have pushed scope past the brief's ≤5-site threshold and mixed the PM-state-extraction failure class with the trigger-ingest failure class.
- **`orchestrator/agent.py:2031`** still calls `store.update_pm_project_state(pm_slug, updates, summary)` without `mutation_source=` kwarg (carryover from PR #50 B2 return). Not this brief's scope. Queue for `TEMPLATE_H_COMPLIANCE_1` if Director wants it sorted before Phase 2.
- **Baseline** has 24 pre-existing failing tests + 31 collection errors + `tests/test_tier_normalization.py` TypeError. Unchanged by this hot-fix. Zero regressions introduced.

---

**Handoff:** `@ai-head-2 ready for review`. Tier A: AI Head #2 runs
`/security-review`, merges on APPROVE + green ship gate, then executes the
post-merge sequence per brief §"Post-merge sequence" — **critically, the
Phase 2 unlock depends on the backfill re-running and extracting ≥3 rows
for ao_pm**, which validates the fix end-to-end against live Opus output.

— B2
