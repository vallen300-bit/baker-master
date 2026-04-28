---
ship_report_for: briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md
builder: b2
shipped_at: 2026-04-29T00:00:00Z
trigger_class: HIGH
branch: cortex-trigger-endpoint-1
pr_url: <opened by gh pr create after this report is committed>
review_required:
  - "B1 (formal) — external API + auth surface (RA-24 trigger)"
  - "AI Head A — /security-review + structural"
ship_gate_pass: true
---

# B2 Ship Report — CORTEX_TRIGGER_ENDPOINT_1

## What shipped

- **NEW** `POST /api/cortex/trigger` endpoint in `outputs/dashboard.py` (X-Baker-Key guarded, sync-invoke `maybe_run_cycle`).
- **NEW** `CortexTriggerRequest` Pydantic model (matter_slug 1–64 chars, director_question 10–4000 chars, triggered_by 1–64 chars default `director_manual`).
- **NEW** import `from orchestrator.cortex_runner import maybe_run_cycle` alongside other orchestrator imports.
- **NEW** `tests/test_cortex_trigger_endpoint.py` (4 tests: happy path, 401, 422, 504).

All exactly per brief — no scope creep, no secondary edits.

## Files modified / added

```
 briefs/_tasks/CODE_2_PENDING.md           # mailbox: OPEN→IN_PROGRESS, claimed_by:b2 (hygiene)
 outputs/dashboard.py                      | 66 ++++++++++++++++++++++++++++++
 tests/test_cortex_trigger_endpoint.py     | 140 ++++++++++++++++++++++++++++++ (NEW)
```

## Files NOT touched (per brief)

- `orchestrator/cortex_runner.py` — `maybe_run_cycle` signature + timeout semantics unchanged
- `triggers/cortex_pipeline.py` — auto-dispatch path unchanged
- All other dashboard endpoints — surgical addition only

## Ship gate verification (Lesson #47 — no "by inspection")

### Syntax check

```
$ cd ~/bm-b2 && python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)" && echo "SYNTAX_OK"
SYNTAX_OK
```

(Pre-existing `SyntaxWarning: invalid escape sequence '\['` at line 2530 is in unrelated SQL string literal — not introduced by this PR.)

### Unit tests — literal stdout

```
$ cd ~/bm-b2 && source .venv312/bin/activate && pytest tests/test_cortex_trigger_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b2/.venv312/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 4 items

tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_happy_path PASSED [ 25%]
tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_unauthorized PASSED [ 50%]
tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_validation_short_question PASSED [ 75%]
tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_timeout_translates_to_504 PASSED [100%]

======================== 4 passed, 5 warnings in 1.09s =========================
```

### Phase 5 / Phase 5 idempotency regression

```
$ cd ~/bm-b2 && source .venv312/bin/activate && pytest tests/test_cortex_trigger_endpoint.py tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py
======================== 45 passed, 5 warnings in 1.15s ========================
```

(45 = 4 trigger + 20 phase5_act + 21 phase5_idempotency.)

## Quality checkpoints (brief §"Quality Checkpoints")

| # | Checkpoint                                                            | Status |
|---|-----------------------------------------------------------------------|--------|
| 1 | `py_compile` clean on `outputs/dashboard.py`                          | ✅ PASS |
| 2 | `pytest tests/test_cortex_trigger_endpoint.py -v` — 4/4 PASS literal  | ✅ PASS |
| 3 | Endpoint requires X-Baker-Key (401 test)                              | ✅ PASS |
| 4 | Pydantic validation rejects short director_question (422 test)        | ✅ PASS |
| 5 | `asyncio.TimeoutError` translates to HTTP 504 (504 test)              | ✅ PASS |
| 6 | Sensitive payload not info-logged (only error-level + matter_slug + triggered_by — no director_question / aborted_reason logged) | ✅ PASS |
| 7 | Post-deploy smoke curl returns 200 + cycle_id                         | ⏳ pending Render redeploy (A executes after merge per brief) |

## Security surface review (B2 self-walkthrough — formal review by B1 + A)

| Check                                | Implementation                                                                 |
|--------------------------------------|--------------------------------------------------------------------------------|
| Auth — X-Baker-Key required          | `dependencies=[Depends(verify_api_key)]` — same pattern as 60+ existing routes |
| Auth bypass — no second mechanism    | No `Header(...)`, no token-from-body — single auth surface                     |
| Input validation — matter_slug       | Pydantic `min_length=1, max_length=64`                                         |
| Input validation — director_question | Pydantic `min_length=10, max_length=4000`                                      |
| Input validation — triggered_by      | Pydantic `min_length=1, max_length=64`, default `director_manual`              |
| SQL injection                        | N/A — endpoint does no SQL; passes args by keyword to `maybe_run_cycle`        |
| Logging discipline                   | director_question NOT logged at any level; aborted_reason NOT logged           |
| Error leakage                        | 500 truncates exception to 200 chars; 504 returns generic message              |
| Timeout DoS                          | `CYCLE_TIMEOUT_SECONDS` cap inside `maybe_run_cycle` (unchanged)               |
| Resource exhaustion                  | Sync handler — Render edge timeout > internal cap; one cycle per request       |
| HTTPException re-raise               | `except HTTPException: raise` clause prevents wrap-into-500 bug                |
| Information disclosure (cycle echo)  | Only persisted CortexCycle fields returned; no DB internals leaked             |

## Deviations from brief

**None.** Single deliberate addition: an `except HTTPException: raise` clause between the `TimeoutError` and generic `Exception` handlers, so any `HTTPException` raised inside `maybe_run_cycle` (e.g., from store layer) propagates with its real status instead of being collapsed into 500. Defensive, no functional change for the brief's stated paths (success, timeout, generic Exception).

## After merge — A executes (per brief §"After merge — A executes")

1. Confirm Render deploys cleanly (deploy ID + healthy)
2. Post-deploy smoke curl:
   ```bash
   BAKER_KEY="bakerbhavanga"
   curl -s -X POST "https://baker-master.onrender.com/api/cortex/trigger" \
     -H "Content-Type: application/json" \
     -H "X-Baker-Key: $BAKER_KEY" \
     -d '{
       "matter_slug": "oskolkov",
       "director_question": "Smoke test: confirm trigger endpoint reaches Phase 1 sense.",
       "triggered_by": "post_deploy_smoke"
     }' | jq .
   ```
3. If 200 + cycle_id: refire AO Director question via the new endpoint (not B3 local).
4. Surface result to Director.

## Next steps in pipeline

1. **B1 second-pair-of-eyes review** (RA-24 trigger — external API + auth surface). HIGH trigger class; B1 ≠ B2 by mailbox. → A dispatches.
2. **AI Head A `/security-review`** (Lesson #52 mandatory pre-merge gate).
3. Both clear → A Tier-A squash-merge → mailbox flips IN_PROGRESS → COMPLETE.
4. Post-deploy smoke + AO refire (above).

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
