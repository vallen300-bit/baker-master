---
status: OPEN
brief: briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md
trigger_class: HIGH
dispatched_at: 2026-04-28T22:55:00Z
dispatched_by: ai-head-a
director_authorization: "1b" (Pick 1b — add /api/cortex/trigger endpoint, V1.1 path to ship Cortex cycles tonight)
predecessor_state: "B3 first real cycle attempts 1+2 FAILED on cross-network specialist timeout. Root cause not capability-specific — it's question-weight × network-locality. Fix: run cycles inside Render container via HTTP trigger."
goal: "Add POST /api/cortex/trigger endpoint to outputs/dashboard.py guarded by X-Baker-Key. Calls maybe_run_cycle synchronously inside Render container where DB+Qdrant are localhost (no cross-network latency). Returns terminal cycle state."
scope_summary:
  - "1 new POST endpoint at /api/cortex/trigger"
  - "1 Pydantic request model"
  - "4 unit tests in tests/test_cortex_trigger_endpoint.py"
files_modified:
  - outputs/dashboard.py (~70 LOC added: import + Pydantic model + endpoint)
  - tests/test_cortex_trigger_endpoint.py (NEW, ~120 LOC, 4 tests)
files_not_to_touch:
  - orchestrator/cortex_runner.py (signature/timeouts stay)
  - triggers/cortex_pipeline.py (auto-dispatch path unchanged)
b1_review_required: true
b1_review_reason: "External API + auth surface — RA-24 trigger fires"
builder: b2
reviewer: b1
ai_head_review: "/security-review + structural"
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B2_cortex_trigger_endpoint_20260428.md
autopoll_eligible: false
---

# CODE_2_PENDING — B2: CORTEX_TRIGGER_ENDPOINT_1 — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b2/01_build` (App)
**Trigger class:** HIGH (external API + new auth surface — B1 review required pre-merge per RA-24)

## Read full brief

`briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md` — complete spec, copy-pasteable code, 4 unit tests, post-deploy smoke.

## Execution

```bash
cd ~/bm-b2/01_build
git checkout main && git pull -q
git checkout -b cortex-trigger-endpoint-1

# Read the brief
cat briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md | less

# Implement per brief
# - Add `from orchestrator.cortex_runner import maybe_run_cycle` to imports
# - Add CortexTriggerRequest Pydantic model
# - Add @app.post("/api/cortex/trigger") endpoint
# - Create tests/test_cortex_trigger_endpoint.py with 4 tests

# Syntax check
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"

# Unit tests must PASS literally
pytest tests/test_cortex_trigger_endpoint.py -v

# Commit + push
git add outputs/dashboard.py tests/test_cortex_trigger_endpoint.py briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md
git commit -m "feat(cortex): /api/cortex/trigger endpoint for inside-Render cycle invocation

Adds POST /api/cortex/trigger guarded by X-Baker-Key. Calls maybe_run_cycle
synchronously inside the Render container, where DB+Qdrant are localhost
(no cross-network latency that has been killing local-dispatch cycles).

- Pydantic request model with length/format validation
- 4 unit tests (happy path, 401, 422, 504 timeout)
- No changes to maybe_run_cycle signature or auto-dispatch path

Brief: briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md
Trigger class: HIGH (B1 situational review required pre-merge)

Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push -u origin cortex-trigger-endpoint-1
gh pr create \
  --title "feat(cortex): /api/cortex/trigger endpoint for inside-Render cycle invocation" \
  --body "Per BRIEF_CORTEX_TRIGGER_ENDPOINT_1. HIGH trigger class — B1 review required.

## Why
B3 local-dispatch real cycles fail on cross-network specialist timeouts (60s × 3 cap exceeded by vault-heavy tool chains paying network round-trip latency). Root cause is question-weight × network-locality, not capability-specific. Disabling capabilities does not fix it.

## What
POST /api/cortex/trigger that calls maybe_run_cycle inline inside the Render container, where DB+Qdrant are localhost.

## Tests
- 4 unit tests in tests/test_cortex_trigger_endpoint.py
- All 4 PASS literally (per Lesson #48 — no 'by inspection')

## Reviewers
- B1: structural + Lesson #52 walkthrough
- AI Head A: /security-review + final review

## Verification
Post-deploy smoke curl in brief — confirms endpoint returns 200 + cycle_id."
```

## Pass criteria

- 4 tests PASS literally (`pytest tests/test_cortex_trigger_endpoint.py -v`)
- `python3 -c "import py_compile; ..."` clean on `outputs/dashboard.py`
- PR opened, B1 + A tagged for review
- No changes outside the 2 listed files

## STOP criteria

- Tests fail → STOP, surface output to A
- maybe_run_cycle import causes circular import → STOP, surface
- Existing /api/cortex/* endpoint regression — STOP

## Output

Create `briefs/_reports/B2_cortex_trigger_endpoint_20260428.md` with: PR URL, test output, syntax check output, files-modified diff summary.

## After merge — A executes

1. Confirm Render deploys cleanly (deploy ID + healthy)
2. Post-deploy curl smoke
3. If 200 + cycle_id: refire AO Director question via the new endpoint (not B3 local!)
4. Surface result to Director

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
