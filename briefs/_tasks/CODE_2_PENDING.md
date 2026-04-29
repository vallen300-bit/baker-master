---
status: OPEN
brief: briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md
trigger_class: HIGH
dispatched_at: 2026-04-29T02:25:00Z
dispatched_by: ai-head-a
director_authorization: "Task 2" (Director: 'can you run these 2 tasks on your own, i will go to sleep' → 'confirm')
predecessor_state: "Task B (RCA) DONE — 9 capabilities re-enabled, RCA stored. Cortex V1 + cost gate + 18 active caps all live. Proposal-card buttons (✅✏️🔄❌) on $4-cycle output are visible but inert. Phase 5 act handlers (cortex_approve/edit/refresh/reject) already exist in orchestrator/cortex_phase5_act.py with idempotency CAS guard."
goal: "Wire the 4 proposal-card buttons to a new POST /webhook/slack/interactive endpoint with Slack HMAC signature verification. Handlers already exist; this brief is plumbing + signature verification + payload parsing + BackgroundTask dispatch + response_url update-in-place."
scope_summary:
  - "NEW triggers/slack_interactivity.py (~220 LOC) — _verify_signature + endpoint + handler dispatch + response_url update helper"
  - "MOD outputs/dashboard.py (+2 LOC) — router import + include"
  - "NEW tests/test_cortex_slack_interactivity.py (~250 LOC, 8 tests)"
files_modified:
  - triggers/slack_interactivity.py (NEW)
  - outputs/dashboard.py
  - tests/test_cortex_slack_interactivity.py (NEW)
files_not_to_touch:
  - orchestrator/cortex_phase5_act.py (handlers stay)
  - orchestrator/cortex_phase4_proposal.py (proposal builder stays)
  - triggers/slack_events.py (different surface — events vs interactivity)
b1_review_required: true
b1_review_reason: "External API + Slack HMAC auth surface + dispatches handlers that write Gold + execute structured_actions — RA-24 trigger fires"
builder: b2
reviewer: b1
ai_head_review: "/security-review + structural"
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B2_cortex_slack_interactivity_20260429.md
autopoll_eligible: false
---

# CODE_2_PENDING — B2: CORTEX_SLACK_INTERACTIVITY_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b2/01_build`
**Trigger class:** HIGH (external API + Slack HMAC auth + dispatches Gold-writing handlers — B1 review required pre-merge per RA-24)

## Read full brief

`briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md` — complete spec, copy-pasteable code, 8 unit tests, post-deploy smoke.

## Why this brief is small

Phase 5 action handlers already exist (`cortex_approve` / `cortex_edit` / `cortex_refresh` / `cortex_reject` in `orchestrator/cortex_phase5_act.py`) with idempotency CAS guard. This brief WIRES them behind a Slack interactivity endpoint — pure plumbing.

## Execution

```bash
cd ~/bm-b2/01_build
git checkout main && git pull -q
git checkout -b cortex-slack-interactivity-1

cat briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md | less

# Implement per brief — 3 files
# 1. NEW triggers/slack_interactivity.py
# 2. MODIFY outputs/dashboard.py — 2-line router include
# 3. NEW tests/test_cortex_slack_interactivity.py — 8 tests

# Syntax checks
python3 -c "import py_compile; py_compile.compile('triggers/slack_interactivity.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"

# Tests must PASS literally
pytest tests/test_cortex_slack_interactivity.py -v

# Regression
pytest tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py tests/test_cortex_pre_review_gate.py -v

# Commit + PR (standard pattern from PR #78/#80)
```

## Pass criteria

- 8 new tests PASS literally
- Phase 5 + idempotency + gate regression PASS literally
- py_compile clean on both modified files
- PR opened, B1 + A tagged
- Only the 3 listed files touched

## STOP criteria

- Tests fail → STOP, surface
- Slack signature verification not constant-time (no `hmac.compare_digest`) → STOP
- Endpoint synchronously awaits handlers (>3s response time) → STOP
- Phase 5 handlers regression breaks → STOP
- Any handler called without signature verification → STOP

## Output

`briefs/_reports/B2_cortex_slack_interactivity_20260429.md` — PR URL + literal test stdout (8 + regression) + py_compile output.

## After merge — A executes

1. Verify `SLACK_SIGNING_SECRET` env var present on Render
2. Render redeploy
3. Smoke 1: curl with bad sig → 403
4. Smoke 2: Slack App settings → Interactivity URL `https://baker-master.onrender.com/webhook/slack/interactive`
5. Real test: tap ❌ Reject on the existing `cycle_id=7dc3201b` AO proposal card → confirm card update + cycle.status='rejected' + feedback_ledger row

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
