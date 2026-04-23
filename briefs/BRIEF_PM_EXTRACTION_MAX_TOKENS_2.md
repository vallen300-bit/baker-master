# BRIEF: PM_EXTRACTION_MAX_TOKENS_2 — raise Opus extraction ceiling + log output_tokens

## Context

Follow-up to `BRIEF_PM_EXTRACTION_JSON_ROBUSTNESS_1` (PR #54 merged 2026-04-23 `ca75e372`). Post-merge backfill re-run yielded 2/5 ao_pm rows — below Director's literal Phase 2 gate (≥3 ao_pm). Diagnosis surfaced by AI Head #2 replay against `conv#397`: Opus `stop_reason=max_tokens` on raw output 5254 chars. Response truncated mid-string (`"aligned'` end). Pass-4 regex repair cannot reconstruct unterminated JSON — structural, not syntactic.

**Anchor incident facts currently captured (semantic):** conv#398 (EUR 5M RG7 balance), conv#399 (Patrick Zuckner Aukera response), plus earlier test_run (Patrick warning red flag). Missed (truncated): conv#387 (open actions enumeration), conv#396 (capital call history), conv#397 (Aukera release setup).

**Director directive 2026-04-24:** Option B accepted. Surgical 1500→3000. No PM_REGISTRY refactor. Phase 2 literal gate stays ≥3 ao_pm. Don't escalate if still truncating — structural design question is out of scope.

---

## Estimated time: ~30 min Code Brisen
## Complexity: Trivial
## Prerequisites:
- baker-master main at `ca75e372` (PR #54 merged) ✓
- `scripts/check_singletons.sh` green ✓

---

## Scope table

| Deliverable | What | Where |
|---|---|---|
| **D1** | `max_tokens=1500` → `max_tokens=3000` | `orchestrator/capability_runner.py:308` |
| **D2** | After the `claude.messages.create(...)` returns, emit `logger.info` with `response.usage.output_tokens` + `pm_slug` + `mutation_source` for empirical sizing data | `orchestrator/capability_runner.py` after line 326 (after the `resp = claude.messages.create(...)` block) |
| **D3** | Update the existing `test_parse_well_formed_json_object` + add 1 new test `test_extract_logs_output_tokens_on_success` using `monkeypatch` of `anthropic.Anthropic` | `tests/test_pm_extraction_robustness.py` |

---

## Fix/Feature 1: Raise max_tokens ceiling

### Current (verified)

`orchestrator/capability_runner.py:308`:
```python
resp = claude.messages.create(
    model="claude-opus-4-6",
    max_tokens=1500,
    system=extraction_system,
    ...
)
```

### After

```python
resp = claude.messages.create(
    model="claude-opus-4-6",
    max_tokens=3000,
    system=extraction_system,
    ...
)
```

**Empirical data point:** `conv#397` real-world truncation was at raw_length=5254 chars (~1300 output tokens, near the 1500 ceiling). Head-room for rich ao_pm extractions with nested `sub_matters` / `relationship_state` / `red_flags` structures.

### Key constraints

- **Literal integer `3000`.** Do NOT refactor to env-var or PM_REGISTRY lookup. Director directive: defer per-capability config to a follow-up brief if output_tokens logs (D2) show meaningful variance across capabilities over next 2 weeks.
- **Do NOT touch any other `max_tokens=` site** in the file. Grep for `max_tokens=` before making the change to confirm you're editing line 308, not a different call.
- **Cost impact:** output tokens doubled worst-case. At current traffic (~5 sidebar scans/day across ao_pm + movie_am + backfill), ~$0.0003/call × 5 = ~$0.0015/day. Negligible.

---

## Fix/Feature 2: Log output_tokens per extraction

### Problem

No empirical data on how much output-token budget each capability's extraction actually uses. Required to make the next-iteration decision (per-capability config vs. further ceiling raise vs. structured output) on evidence, not guess.

### Implementation

Immediately after the `resp = claude.messages.create(...)` call (so AFTER line 326 block closes, BEFORE `raw = resp.content[0].text.strip()`):

```python
        try:
            _ot = getattr(getattr(resp, "usage", None), "output_tokens", None)
            _stop = getattr(resp, "stop_reason", None)
            logger.info(
                f"PM extraction tokens [{pm_slug}][{mutation_source}]: "
                f"output_tokens={_ot}, stop_reason={_stop}"
            )
        except Exception:
            pass  # telemetry only — never break extraction on log failure
```

**Why INFO not DEBUG:** Director directive. This is empirical sizing data to inform future decisions; needs to be visible in production logs without a filter.

### Key constraints

- **Fault-tolerant.** `getattr` chain + bare `except Exception: pass`. Logging must never break the extraction flow (this is exactly the class of silent swallow we're trying to AVOID for actual errors, but log emission failure genuinely is ancillary).
- **Place BEFORE the parse.** So the log fires even when JSON parsing fails downstream — we want the metric on every completed API call, success or failure.
- **Format anchor:** `output_tokens=<int>, stop_reason=<str>` so future grep can parse. `stop_reason` values of interest: `end_turn` (happy path), `max_tokens` (truncated — the class we're sizing against).

### Verification

After a week of production traffic, grep logs:

```
grep "PM extraction tokens" <log-source> \
    | awk -F'output_tokens=' '{print $2}' \
    | awk -F',' '{print $1}' \
    | sort -n | uniq -c
```

Expected distribution: mostly <1500 (fast sidebar extractions), some approaching 3000 (rich backfill/delegate extractions).

---

## Fix/Feature 3: Tests

### File

`tests/test_pm_extraction_robustness.py` (EXISTING — add 1 test, don't rewrite existing 5)

### New test

```python
def test_extract_logs_output_tokens_on_success(caplog, monkeypatch):
    """D2: output_tokens logged at INFO level on every extraction call."""
    import logging
    from orchestrator import capability_runner

    class _FakeUsage:
        output_tokens = 1234

    class _FakeContentBlock:
        text = '{"sub_matters": {}, "summary": "ok"}'

    class _FakeResp:
        content = [_FakeContentBlock()]
        usage = _FakeUsage()
        stop_reason = "end_turn"

    class _FakeClient:
        def __init__(self, api_key=None):
            pass
        class messages:
            @staticmethod
            def create(**kwargs):
                return _FakeResp()

    # Patch Anthropic client construction site
    monkeypatch.setattr(capability_runner, "anthropic", type("M", (), {"Anthropic": _FakeClient}))
    # Patch SentinelStoreBack to a no-op so we don't touch DB
    class _NoopStore:
        def update_pm_project_state(self, *a, **k): pass
        def _get_conn(self): return None
        def _put_conn(self, c): pass
        def create_cross_pm_signal(self, *a, **k): pass
    from memory import store_back
    monkeypatch.setattr(store_back.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: _NoopStore()))
    # Patch _get_extraction_dedup_context to return empty
    monkeypatch.setattr(capability_runner.CapabilityRunner,
                        "_get_extraction_dedup_context", lambda self, slug: "")
    monkeypatch.setattr(capability_runner.CapabilityRunner,
                        "_store_pending_insights", lambda self, *a, **k: None)

    with caplog.at_level(logging.INFO, logger="baker.capability_runner"):
        result = capability_runner.extract_and_update_pm_state(
            pm_slug="ao_pm",
            question="test",
            answer="test",
            mutation_source="test_unit",
        )

    assert result is not None
    assert any(
        "output_tokens=1234" in rec.message and "stop_reason=end_turn" in rec.message
        for rec in caplog.records
    )
```

### Existing tests — leave alone

Do NOT edit `test_parse_well_formed_json_object`, `test_parse_json_in_markdown_fence`, `test_parse_unquoted_property_names`, `test_parse_trailing_comma`, `test_parse_unparseable_returns_none`. They still pass — no semantic change from D1.

---

## Files Modified

- `orchestrator/capability_runner.py` — D1 (one-line) + D2 (~10 line log block)
- `tests/test_pm_extraction_robustness.py` — D3 (add 1 test, keep 5 existing)

## Do NOT Touch

- Any other `max_tokens=` site — only line 308 inside `extract_and_update_pm_state`
- `_robust_json_parse_object` — no changes needed
- `scripts/backfill_pm_state.py` — no changes (AI Head re-runs post-merge)
- PM_REGISTRY — directive explicitly declines per-capability config
- Any other capability's extraction or any non-extraction call site

## Ship Gate (literal)

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True); print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_extraction_robustness.py -v
# expected 6 passes (5 existing + 1 new D3 test)
```

Regression delta vs main @ `ca75e372`:
```
$ python3 -m pytest 2>&1 | tail -3
# branch passes = main passes + 1 (only the new D3 test)
# branch failures == main failures (zero)
```

## Quality Checkpoints

1. Line 308 `max_tokens` literal is `3000` (integer, not string, not env-var)
2. `logger.info` emits `output_tokens=` and `stop_reason=` anchors for future grep
3. Log block is BEFORE parse, so fires on parse-failure calls too
4. Test count 5→6 in the file; no existing test removed
5. No other file touched

## Part H compliance

Compliance by reference to PR #50's Part H §H1–H5 audit. No new invocation paths, no new tags. Cite in PR body.

## Post-merge sequence (AI Head executes)

1. `/security-review` on PR diff (per SKILL.md mandatory protocol — Director reinforced 2026-04-24)
2. Tier A merge on APPROVE + green ship gate
3. Render deploy wait → live confirmation
4. `git pull --rebase origin main` on AI Head working tree
5. Re-run backfill:
   ```bash
   python scripts/backfill_pm_state.py ao_pm --since 14d --dry-run
   python scripts/backfill_pm_state.py ao_pm --since 14d
   python scripts/backfill_pm_state.py movie_am --since 14d
   ```
6. Count ao_pm rows:
   ```sql
   SELECT COUNT(*) FROM pm_backfill_processed WHERE pm_slug = 'ao_pm';
   ```
7. If ≥3 → Phase 2 gate MET → unlock `BRIEF_CAPABILITY_THREADS_1` drafting.
8. If <3 → report diagnosis; **DO NOT auto-escalate** to further hot-fix (Director directive 2026-04-24: bigger design question deferred).
9. Slack push to Director DM with row count + Phase 2 unlock signal (or non-unlock status).
10. Scratch closeout.

## Acceptance criteria (brief-level)

- D1 literal integer 3000 at capability_runner.py:308
- D2 log emits on SUCCESS path with non-null output_tokens value
- D2 log emits on FAILURE path with stop_reason='max_tokens' when truncated (derives from D2 placement BEFORE parse)
- D3 new test asserts INFO-level log capture with `output_tokens=<int>` and `stop_reason=<str>`
- Ship-gate pytest shows literal 6/6 green
- Zero regressions vs `ca75e372`
