---
status: OPEN
brief: briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md
trigger_class: HIGH
dispatched_at: 2026-04-29T~10:00Z
dispatched_by: ai-head-a
director_authorization: "B" (Director ratified Path B 2026-04-29 morning post-reject-test that exposed the defect on cycle 7dc3201b)
predecessor_state: "Cycle 7dc3201b reject completed end-to-end via manual SQL flip + forged-from-Mac Slack request. Production button path STILL broken on every new cycle: Phase 4 lands at tier_b_pending, Phase 5 expects proposed. Schema CHECK for *ing transient statuses fixed live but no migration file checked in."
goal: "Phase 5 handlers accept BOTH 'proposed' AND 'tier_b_pending' as valid pre-button state. Pin the *ing transient status CHECK in a permanent migration. Capture Render env-var paginated-PUT regression as feedback memory."
scope_summary:
  - "MOD orchestrator/cortex_phase5_act.py — _cas_lock_cycle multi-from + 4 call sites"
  - "MOD memory/store_back.py — _ensure_cortex_cycles_table CHECK includes 15 status values"
  - "NEW migrations/20260429_cortex_cycles_add_transient_statuses.sql"
  - "NEW memory/feedback_render_envvar_paginated_put.md"
  - "MOD memory/MEMORY.md — append 1 index entry"
files_modified:
  - orchestrator/cortex_phase5_act.py
  - memory/store_back.py
  - migrations/20260429_cortex_cycles_add_transient_statuses.sql (NEW)
  - memory/feedback_render_envvar_paginated_put.md (NEW)
  - memory/MEMORY.md
files_not_to_touch:
  - triggers/slack_interactivity.py
  - triggers/cortex_stuck_cycle_sentinel.py
  - All Phase 1/2/3/4 code
b1_review_required: true
b1_review_reason: "RA-24 trigger fires: DB migration + cross-capability state writes (Phase 5 state machine touches Gold-write dispatch path)"
builder: b3
reviewer: b1
ai_head_review: "/security-review + structural"
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B3_cortex_phase5_status_reconcile_20260429.md
autopoll_eligible: false
---

# CODE_3_PENDING — B3: CORTEX_PHASE5_STATUS_RECONCILE_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3/01_build`
**Trigger class:** HIGH (B1 review required pre-merge per RA-24 — DB migration + cross-cap state writes)

## Read full brief

`briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md` — complete spec, 3 bundled fixes, exact migration SQL, 2+ new tests required.

## Why bundled

Three fixes from today's Director session, all rooted in the same incident chain:
1. **Phase 4/5 status mismatch** — proven blocker on every future AO cycle
2. **Transient `*ing` statuses missing from CHECK** — fixed live by Director session, needs permanent migration
3. **Render env-var paginated-PUT regression** — needs feedback memory so it doesn't repeat

All small, all related, one PR.

## Execution

```bash
cd ~/bm-b3/01_build
git checkout main && git pull -q
git checkout -b cortex-phase5-status-reconcile-1

cat briefs/BRIEF_CORTEX_PHASE5_STATUS_RECONCILE_1.md | less

# Implement per brief — 5 files (2 mod, 3 new)

# Syntax checks
python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase5_act.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"

# Tests must PASS literally
pytest tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py -v
pytest tests/test_cortex_runner_phase126.py tests/test_cortex_pre_review_gate.py tests/test_cortex_slack_interactivity.py

# Commit + PR (standard pattern)
```

## Pass criteria

- 2+ new tests PASS literally
- Phase 5 + idempotency + runner_phase126 + pre_review_gate + slack_interactivity regression PASS literally
- py_compile clean on both modified .py files
- Migration SQL parses cleanly
- PR opened, B1 + A tagged

## STOP criteria

- Tests fail → STOP, surface
- `_cas_lock_cycle` accepts states outside `proposed`+`tier_b_pending` → STOP
- Migration runs but `\d cortex_cycles` shows mismatched CHECK → STOP
- store_back bootstrap CHECK doesn't match migration CHECK exactly → STOP
- Files outside the 5-file scope modified → STOP

## Output

`briefs/_reports/B3_cortex_phase5_status_reconcile_20260429.md` — PR URL + literal test stdout + py_compile output.

## After merge — A executes

1. /security-review (Lesson #52)
2. Verify `pg_get_constraintdef('cortex_cycles_status_check')` matches new CHECK on prod DB
3. Director-side smoke deferred — next REAL AO cycle naturally exercises the path

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
