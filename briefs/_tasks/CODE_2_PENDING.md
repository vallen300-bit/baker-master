---
status: OPEN
brief: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_1.md
trigger_class: HIGH
dispatched_at: 2026-04-29T01:10:00Z
dispatched_by: ai-head-a
director_authorization: "A" (Pick Option A — URL-based pre-review gate to economize cost: cheap Slack ping with Yes/Skip links; only fire $4 cycle on Yes click)
predecessor_state: "Cortex V1 LIVE on AO matter. First real cycle 7dc3201b shipped tonight at $4.00. Director: 'in order to economize the cost' wants pre-cycle approval via Slack URL gate. Manual /api/cortex/trigger endpoint stays unchanged."
goal: "Add a URL-based cost gate between auto-dispatch and maybe_run_cycle. Cheap Slack DM with signed-token Yes/Skip URLs. Director taps Yes → fire cycle async. Taps Skip → log + no spend. Idempotent via baker_actions audit."
scope_summary:
  - "NEW triggers/cortex_pre_review_gate.py (~180 LOC) — token sign/verify + Slack DM compose + decision audit"
  - "MODIFY triggers/cortex_pipeline.py (+30 LOC) — gate-enabled fork in maybe_trigger_cortex"
  - "MODIFY outputs/dashboard.py (+70 LOC) — GET /api/cortex/gate/decide endpoint + background-fire helper"
  - "NEW tests/test_cortex_pre_review_gate.py (~200 LOC, 7 tests)"
files_modified:
  - triggers/cortex_pre_review_gate.py (NEW)
  - triggers/cortex_pipeline.py
  - outputs/dashboard.py
  - tests/test_cortex_pre_review_gate.py (NEW)
files_not_to_touch:
  - orchestrator/cortex_runner.py
  - kbl/bridge/alerts_to_signal.py
  - existing /api/cortex/trigger endpoint
b1_review_required: true
b1_review_reason: "External API + new auth surface (signed-URL token, no X-Baker-Key) + new Slack DM behavior on auto-dispatch path — RA-24 trigger fires"
builder: b2
reviewer: b1
ai_head_review: "/security-review + structural"
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B2_cortex_pre_review_gate_20260429.md
autopoll_eligible: false
---

# CODE_2_PENDING — B2: CORTEX_PRE_REVIEW_GATE_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b2/01_build`
**Trigger class:** HIGH (external API + signed-token auth + Slack DM behavior change — B1 review required pre-merge per RA-24)

## Read full brief

`briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_1.md` — complete spec + copy-pasteable code + 7 unit tests + post-deploy smoke.

## Execution

```bash
cd ~/bm-b2/01_build
git checkout main && git pull -q
git checkout -b cortex-pre-review-gate-1

# Read the brief
cat briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_1.md | less

# Implement per brief — 4 files
# 1. NEW triggers/cortex_pre_review_gate.py
# 2. MODIFY triggers/cortex_pipeline.py — add _gate_enabled() + gate fork
# 3. MODIFY outputs/dashboard.py — add /api/cortex/gate/decide endpoint
# 4. NEW tests/test_cortex_pre_review_gate.py — 7 tests

# Syntax checks
python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/cortex_pipeline.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"

# Tests must PASS literally
pytest tests/test_cortex_pre_review_gate.py -v
# Regression
pytest tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_runner_phase126.py -v

# Commit + push + PR (use the standard pattern)
```

## Pass criteria

- 7 new tests PASS literally
- Phase 1/2/6 + pipeline + bridge regression PASS literally
- py_compile clean on all 3 modified files
- PR opened, B1 + A tagged
- Only the 4 listed files changed

## STOP criteria

- Any test fails → STOP, surface
- HMAC compare_digest not used → STOP (timing attack risk)
- CORTEX_GATE_SECRET length not validated (<32 char accepted) → STOP
- Token in URL exceeds reasonable length (>1000 chars) → STOP, surface
- Existing /api/cortex/trigger or auto-dispatch regression → STOP

## Output

Create `briefs/_reports/B2_cortex_pre_review_gate_20260429.md` with: PR URL, all 4 sections of test stdout (literal), syntax-check output, file diff summary.

## After merge — A executes

1. Generate `CORTEX_GATE_SECRET` (48 random urlsafe chars) and set on Render
2. Set `CORTEX_GATE_ENABLED=true` on Render (explicit)
3. Render redeploy
4. Smoke: synthesize a fake signed URL via `sign_token` REPL, GET it, expect 200
5. Trigger a synthetic dispatch path → expect Slack DM in Director channel
6. Director can then test approve / skip flow

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
