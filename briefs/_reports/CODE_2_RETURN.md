# CODE_2_RETURN — PM_EXTRACTION_MAX_TOKENS_2 — 2026-04-24

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `hotfix/pm-extraction-max-tokens-2`
**Brief:** `briefs/BRIEF_PM_EXTRACTION_MAX_TOKENS_2.md`
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `03d02db`)
**Base:** main @ `03d02db` (4 commits ahead of PR #54 merge `ca75e372`, all unrelated to the extractor path)

---

## 8-check format

### 1. Ship gate — literal output

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
collected 6 items

tests/test_pm_extraction_robustness.py::test_parse_well_formed_json_object PASSED [ 16%]
tests/test_pm_extraction_robustness.py::test_parse_json_in_markdown_fence PASSED [ 33%]
tests/test_pm_extraction_robustness.py::test_parse_unquoted_property_names PASSED [ 50%]
tests/test_pm_extraction_robustness.py::test_parse_trailing_comma PASSED [ 66%]
tests/test_pm_extraction_robustness.py::test_parse_unparseable_returns_none PASSED [ 83%]
tests/test_pm_extraction_robustness.py::test_extract_logs_output_tokens_on_success PASSED [100%]

============================== 6 passed in 0.23s ===============================
```

### 2. Full-suite regression delta

```
Baseline (main @ 03d02db, excluding tests/test_tier_normalization.py collection-only TypeError bug):
  816 passed, 24 failed, 21 skipped, 31 errors

Branch (hotfix/pm-extraction-max-tokens-2):
  817 passed, 24 failed, 21 skipped, 31 errors

Delta: +1 pass = 1 new test (test_extract_logs_output_tokens_on_success).
Failures: 24 == 24 (zero regressions).
Errors:   31 == 31 (zero regressions).
```

Measurement method: `git stash -u` branch, ran pytest on pristine main, captured baseline, `git stash pop`, re-verified ship gate on restored branch.

### 3. Per-deliverable summary

| Deliverable | File | Change |
|---|---|---|
| **D1** | `orchestrator/capability_runner.py:308` | Literal integer `max_tokens=1500` → `max_tokens=3000`. Only this one site changed; the other 8 `max_tokens=` sites in the file (line 445 correction extraction = 300; line 1352 Russo extraction = 500; 6 `_force_synthesis` pass-throughs) were not touched. |
| **D2** | `orchestrator/capability_runner.py` | Inserted 10-line telemetry block immediately after the `resp = claude.messages.create(...)` close-paren and BEFORE `raw = resp.content[0].text.strip()`. Uses defensive `getattr(getattr(resp, "usage", None), "output_tokens", None)` + `getattr(resp, "stop_reason", None)` chain. Wrapped in `try: ... except Exception: pass` so telemetry never breaks extraction. Log format: `PM extraction tokens [{pm_slug}][{mutation_source}]: output_tokens={_ot}, stop_reason={_stop}`. Emitted at `logger.info` so production tail-f sees it without filter. |
| **D3** | `tests/test_pm_extraction_robustness.py` | Added `test_extract_logs_output_tokens_on_success` as 6th test. 5 existing tests untouched. New test uses `caplog.at_level(logging.INFO, logger="baker.capability_runner")` + `monkeypatch.setattr(capability_runner, "anthropic", ...)` with a fake `_FakeResp` carrying `usage.output_tokens=1234` + `stop_reason="end_turn"`. Asserts the log record contains both anchor substrings. `memory.store_back` injected via `sys.modules` fake to sidestep the PEP-604 `int \| None` annotation in `create_cross_pm_signal` that breaks type evaluation on the test runner's Python 3.9. `CapabilityRunner.__init__` stubbed to no-op per the existing pattern in `tests/test_pm_state_write.py`. |

### 4. Files modified vs Files Modified list

| Brief §Files Modified entry | This PR? | Notes |
|---|---|---|
| `orchestrator/capability_runner.py` | ✅ | D1 + D2 |
| `tests/test_pm_extraction_robustness.py` | ✅ | D3 (append-only) |

```
$ git diff main..HEAD --name-only | wc -l
2
```

Exactly 2 files. Brief §Scope discipline satisfied.

### 5. Do NOT Touch — verified untouched

- `scripts/backfill_pm_state.py` — 0 diff
- `outputs/dashboard.py` sidebar hooks — 0 diff
- PM_REGISTRY — 0 diff
- `_robust_json_parse_object` — 0 diff (brief explicitly excludes)
- `_auto_update_pm_state` 11-line delegator — 0 diff
- Every other `max_tokens=` call site (8 total, lines 445 / 569 / 599 / 712 / 768 / 804 / 925 / 1352) — 0 diff
- 5 existing parser tests — 0 semantic change (only docstring header updated to reflect new 6-test count)

### 6. Rule compliance (SKILL Rules 7 / 8 / 10 / python-backend)

- **Rule 7 (file:line verify).** Pre-edit grep confirmed exactly one `max_tokens=1500` at `orchestrator/capability_runner.py:308`:
  ```
  $ grep -n "max_tokens=" orchestrator/capability_runner.py | grep 1500
  308:            max_tokens=1500,
  ```
  Post-edit confirmed it's now `max_tokens=3000` on the same line with no other numeric literal touched.
- **Rule 8 (singleton).** `bash scripts/check_singletons.sh` green. No new `SentinelStoreBack()` calls; the test's `_NoopStoreClass._get_global_instance` is a classmethod-shaped fake via `sys.modules` injection — preserves the singleton contract.
- **Rule 10 (Part H).** Invocation path unchanged from PR #50 + PR #54 — same 6 callers, same `mutation_source` tags, zero new paths. PR body cites both prior audits by reference.
- **Python rules.** `re.IGNORECASE` not used (no regex added). `except Exception: pass` in D2 is telemetry-only (wraps log emission) — acceptable under the brief's `python-backend.md` §"Fault-tolerant writes" standard. Syntax check green.

### 7. Python-backend quality checks

- **No new SQL.** D1-D3 are Python-only.
- **No `conn.rollback()` changes.** No DB code touched.
- **Model-client-response triple preserved** (Lesson #13): `claude-opus-4-6` + `anthropic.Anthropic(...).messages.create(...)` + `resp.content[0].text`. Only the `max_tokens` literal changed and a telemetry `getattr` chain was added after the call — the call itself is intact.
- **Telemetry emits on both success and failure paths.** D2 block is positioned before `raw = resp.content[0].text.strip()`, which is before `_robust_json_parse_object(raw)`. So `stop_reason=max_tokens` cases (the ones that motivated this hot-fix) log on their way to parse-failure too. This is the empirical data point the brief wants.
- **Cost impact.** Worst-case 2× output tokens; current traffic ~5 sidebar-scans/day × ~$0.0003/call ≈ $0.0015/day. Negligible per brief §D1 math.

### 8. Observations for follow-up (non-blocking)

- **Python-version note on D3.** The fake for `memory.store_back` is injected via `sys.modules` rather than `from memory import store_back` because the real module's `create_cross_pm_signal` signature uses PEP-604 `int | None` which fails runtime type evaluation on Python 3.9. This follows the existing pattern in `tests/test_pm_state_write.py`. If the project ever standardizes to a newer minimum Python, the test could be simplified to a direct `monkeypatch.setattr(store_back.SentinelStoreBack, "_get_global_instance", ...)`. Not this brief's scope.
- **Carryover:** `orchestrator/agent.py:2031` still calls `update_pm_project_state(...)` without `mutation_source=`. Still queued for a `TEMPLATE_H_COMPLIANCE_1` follow-up. Unchanged.
- **Carryover:** 9 trigger-layer Bucket-A `logger.debug` silencers documented in `briefs/_reports/EXCEPT_DEBUG_AUDIT_20260423.md` still queued for `LOGGER_LEVEL_PROMOTE_TRIGGERS_1`. Unchanged.
- **Baseline** carries 24 pre-existing failing tests + 31 collection errors + the `tests/test_tier_normalization.py` TypeError. Unchanged.

---

**Handoff:** `@ai-head-2 ready for review`. Tier A post-merge sequence
per brief §Post-merge sequence: `/security-review` → merge on APPROVE +
green ship gate → re-run backfill → count `ao_pm` rows. Phase 2 unlock
signal **only if `COUNT(*) ≥ 3`** per Director's literal directive. If
`< 3`, report-only — do not auto-escalate (structural design question
deferred by Director 2026-04-24).

— B2
