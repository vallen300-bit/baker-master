# CODE_2_PENDING — PM_EXTRACTION_MAX_TOKENS_2 — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Brief:** `briefs/BRIEF_PM_EXTRACTION_MAX_TOKENS_2.md`
**Target branch:** `hotfix/pm-extraction-max-tokens-2`
**Complexity:** Trivial (~30 min)

**Supersedes:** prior `PM_EXTRACTION_JSON_ROBUSTNESS_1` task (shipped as PR #54, merged `ca75e372`). Mailbox reset.

---

## Why this follow-up

PR #54 closed the JSON-malformation class of failures. Post-merge backfill re-run still failed 3/5 ao_pm extractions — not malformation, **truncation**: Opus `stop_reason=max_tokens` on responses reaching 5254 chars (~1300 output tokens, at the 1500 ceiling). Response ends mid-string (`"aligned'`), structural incompletion the Pass-4 repair can't reconstruct.

Director directive 2026-04-24 (Option B): raise ceiling to 3000 + add output_tokens INFO logging for empirical sizing. **No** per-capability PM_REGISTRY refactor. **No** further escalation if still truncating — that's a bigger design question (structured output / tool-use) deferred.

**Phase 2 gate stays literal:** ≥3 ao_pm backfill rows post-fix unlocks `BRIEF_CAPABILITY_THREADS_1` drafting. No semantic reinterpretation.

---

## Working-tree setup (B2)

```bash
cd ~/bm-b2 && git fetch origin && git pull --rebase origin main
git checkout -b hotfix/pm-extraction-max-tokens-2
```

---

## What you implement (3 deliverables — full spec in brief)

Read `briefs/BRIEF_PM_EXTRACTION_MAX_TOKENS_2.md`. Total scope: 1 constant change + 1 log block + 1 test.

| Deliverable | One-line scope |
|---|---|
| **D1** | `orchestrator/capability_runner.py:308` — `max_tokens=1500` → `max_tokens=3000`. Literal integer. NO env-var / NO PM_REGISTRY lookup. |
| **D2** | After the `resp = claude.messages.create(...)` call and BEFORE the `raw = resp.content[0].text.strip()` site, emit `logger.info(f"PM extraction tokens [{pm_slug}][{mutation_source}]: output_tokens=<int>, stop_reason=<str>")`. Wrap in `try/except: pass` (telemetry must never break extraction). Use `getattr(getattr(resp, "usage", None), "output_tokens", None)` defensive chain. |
| **D3** | Add `test_extract_logs_output_tokens_on_success` to `tests/test_pm_extraction_robustness.py`. Full code in brief §D3. Uses `caplog` + `monkeypatch`. Assert log record contains `output_tokens=1234` and `stop_reason=end_turn` anchors. |

---

## Mandatory compliance — AI Head SKILL Rules

- **Rule 7 (file:line):** confirm line 308 with `grep -n "max_tokens=1500" orchestrator/capability_runner.py` before editing. Should return exactly one match inside `extract_and_update_pm_state`.
- **Rule 8 (singleton):** no new `SentinelStoreBack()` — the test's `_get_global_instance` monkeypatch is on the classmethod, which preserves the singleton contract.
- **Rule 10 (Part H):** cite PR #50's audit by reference in PR body — *"Part H compliance by reference to PR #50 + PR #54; zero new invocation paths."*
- **Python rules:** no bare `except: pass` where it swallows a non-telemetry error. D2's `except Exception: pass` is acceptable because it guards a log emission only.

---

## Acceptance criteria (testable)

### Syntax + hooks
```bash
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Unit tests (ship gate — 6 total after D3)
```bash
$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
```

Expected output:
1. `test_parse_well_formed_json_object` PASS (existing)
2. `test_parse_json_in_markdown_fence` PASS (existing)
3. `test_parse_unquoted_property_names` PASS (existing)
4. `test_parse_trailing_comma` PASS (existing)
5. `test_parse_unparseable_returns_none` PASS (existing)
6. `test_extract_logs_output_tokens_on_success` PASS (new D3)

### Regression delta vs main @ `ca75e372`
```bash
$ python3 -m pytest 2>&1 | tail -3
# branch passes = main passes + 1 (only the new D3 test)
# branch failures == main failures (zero)
```

### Scope discipline
- Exactly 2 files modified: `orchestrator/capability_runner.py` + `tests/test_pm_extraction_robustness.py`.
- Grep-confirm diff:
  ```bash
  git diff main..HEAD --name-only | wc -l
  # expected: 2
  ```

---

## Dispatch protocol

1. Pull main (above).
2. Branch `hotfix/pm-extraction-max-tokens-2`.
3. Single commit OR per-deliverable — your call. `Co-Authored-By` trailer standard.
4. Push branch + open PR. PR title: `PM_EXTRACTION_MAX_TOKENS_2: raise Opus ceiling 1500→3000 + output_tokens telemetry`. PR body: brief §Scope table + literal ship-gate output + Part H by-reference citation.
5. Ship report: `briefs/_reports/CODE_2_RETURN.md` on your branch (standard format).
6. Tag `@ai-head-2 ready for review`.

AI Head #2 runs `/security-review` + Tier A merge + re-runs backfill + reports row count. **Phase 2 unlock signal only if ao_pm count ≥ 3.**

---

## Hard deadline

None. Phase 2 drafts are waiting; keep moving but no pressure-cycle.

— AI Head #2
