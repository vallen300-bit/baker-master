---
status: OPEN
brief: review_pr_78_cortex_trigger_endpoint_1
trigger_class: HIGH
dispatched_at: 2026-04-29T00:10:00Z
dispatched_by: ai-head-a
director_authorization: "1b" (Pick 1b path — /api/cortex/trigger endpoint enables Director-fire from anywhere)
review_target_pr: 78
review_target_branch: cortex-trigger-endpoint-1
review_target_url: https://github.com/vallen300-bit/baker-master/pull/78
builder: b2
reviewer: b1
ai_head_review: A is running /security-review in parallel
b1_review_reason: "External API + new auth surface (X-Baker-Key on a write path) — RA-24 trigger fires"
goal: "Structural review of PR #78 BEFORE Tier-A merge. Confirm: (1) auth correctness, (2) Pydantic validation tight, (3) maybe_run_cycle integration safe (no signature drift, no double-await, no blocking call in async handler), (4) test coverage matches brief, (5) no scope creep beyond brief, (6) Lesson #48 — tests PASS literally not by inspection."
files_to_review:
  - outputs/dashboard.py (+66 LOC: import line 47, CortexTriggerRequest model line 343, endpoint line 4105)
  - tests/test_cortex_trigger_endpoint.py (NEW, 140 LOC)
  - briefs/_reports/B2_cortex_trigger_endpoint_20260428.md (B2's ship report)
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B1_pr78_review_20260429.md
autopoll_eligible: false
---

# CODE_1_PENDING — B1: REVIEW PR #78 CORTEX_TRIGGER_ENDPOINT_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b1/01_build`
**Trigger class:** HIGH (external API + new auth — RA-24 second-pair-of-eyes review required pre-merge)

## Predecessor

B2 shipped PR #78 at 2026-04-29T00:00Z. 4 unit tests PASS literally (1.09s). 45-test phase5 regression suite PASS. py_compile clean. B2's ship report: `briefs/_reports/B2_cortex_trigger_endpoint_20260428.md`.

A is running /security-review on the same diff in parallel. Your review is structural; A's is security. Both must clear before merge.

## What this PR does

- Adds `POST /api/cortex/trigger` to `outputs/dashboard.py`
- Pydantic `CortexTriggerRequest` (matter_slug 1-64, director_question 10-4000, triggered_by 1-64)
- Calls `maybe_run_cycle(...)` synchronously inside Render container
- Returns terminal cycle state as JSON
- 4 unit tests (happy / 401 / 422 / 504)

## Review checklist

### A — Auth correctness
- [ ] `dependencies=[Depends(verify_api_key)]` matches existing /api/cortex/* pattern
- [ ] No second auth mechanism, no Header(...) on body, no token-in-body
- [ ] 401 test covers wrong key AND verifies `maybe_run_cycle` NOT awaited (`m.assert_not_awaited()`)

### B — Pydantic / input validation
- [ ] All 3 fields have explicit min/max length bounds
- [ ] director_question min_length=10 prevents trivial smoke abuse
- [ ] 422 test covers short director_question AND verifies handler not invoked
- [ ] No regex-based validation that could ReDoS

### C — `maybe_run_cycle` integration
- [ ] Signature called with kwargs only (matches `def maybe_run_cycle(*, matter_slug, triggered_by, trigger_signal_id=None, director_question=None)`)
- [ ] `await` is used (async function, no blocking call)
- [ ] `asyncio.TimeoutError` → 504 (test confirms)
- [ ] `except HTTPException: raise` clause prevents wrap-into-500 bug for inner HTTPException raises (B2's deliberate add — note in ship report)
- [ ] Generic Exception → 500 with `str(e)[:200]` truncation
- [ ] Response dict reads only documented CortexCycle fields; no `.dict()` / `.__dict__` exposure that could leak internals

### D — Logging discipline
- [ ] `req.director_question` NEVER appears in any log call (info/error/debug)
- [ ] `cycle.aborted_reason` NEVER appears in any log call
- [ ] Only `req.matter_slug` + `req.triggered_by` appear in error-level logs

### E — Test integrity (Lesson #48 — no "by inspection")
- [ ] All 4 tests run as `pytest tests/test_cortex_trigger_endpoint.py -v` and PASS
- [ ] All 4 tests use real `TestClient(app)` against the actual FastAPI app
- [ ] `_FakeCycle` class mirrors only the 8 fields the endpoint reads
- [ ] No test silently skips on missing env / dependency

### F — Scope discipline (per brief)
- [ ] Only 2 files touched: outputs/dashboard.py + tests/test_cortex_trigger_endpoint.py (mailbox + ship report are bookkeeping)
- [ ] orchestrator/cortex_runner.py untouched
- [ ] triggers/cortex_pipeline.py untouched
- [ ] No other dashboard endpoints modified

### G — Render deploy survival
- [ ] No new env var required (BAKER_API_KEY already set on Render)
- [ ] No DB migration
- [ ] No new package dependency (uses existing fastapi/pydantic/asyncio)

## Pass / fail verdict

PASS if all 7 sections clear. PARTIAL_PASS if any minor obs (note in ship report, do NOT block merge). FAIL if any blocker — surface to A immediately.

## Output

Create `briefs/_reports/B1_pr78_review_20260429.md` with:
- Section-by-section verdicts
- Quoted line+code snippet for any obs
- Final verdict: PASS / PARTIAL_PASS / FAIL
- Comment-fallback APPROVE message text (since GitHub blocks formal self-PR APPROVE)

If PASS: post your APPROVE comment to PR #78 via `gh pr comment 78 --body "..."`.

## STOP criteria

- Auth bypass → STOP, surface
- Pydantic validation gap that allows DoS or injection → STOP, surface
- `maybe_run_cycle` signature drift → STOP, surface
- Sensitive payload logged anywhere → STOP, surface
- Tests fail when re-run → STOP, surface

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
