---
status: OPEN
brief: briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md
trigger_class: LOW
dispatched_at: 2026-04-29T00:55:00Z
dispatched_by: ai-head-a
director_authorization: "we need to allocate much more time for specialist answer, say 2 min ? or 3 min ? see if it works"
predecessor_state: "Real AO cycle fc382469 inside Render hit 300s outer cap. Phase 3a OK (19s); Phase 3b sales specialist 60s × 3 = 180s timeout. Specialist timeout too short for rich prompts."
goal: "Make SPECIALIST_TIMEOUT_S env-tunable via CORTEX_SPECIALIST_TIMEOUT_S; bump default 60→180 (3 min)."
b1_review_required: false
b1_review_reason: "LOW trigger class — config knob change, no auth/API/migration/financial path"
builder: b3
reviewer: ai-head-a (solo review acceptable per RA-24 narrowing)
ai_head_review: structural + py_compile + test PASS
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B3_specialist_timeout_tunable_20260429.md
autopoll_eligible: false
---

# CODE_3_PENDING — B3: CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Trigger class:** LOW (config knob, A solo review)

## Read full brief

`briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md` — full spec.

## Execution

```bash
cd ~/bm-b3
git checkout main && git pull -q
git checkout -b cortex-specialist-timeout-tunable-1

# Implement per brief
# - Edit orchestrator/cortex_phase3_invoker.py line 33: env-tunable + default 180
# - Create tests/test_cortex_specialist_timeout_tunable.py with the env override test
# - Verify no other module imports SPECIALIST_TIMEOUT_S directly:
grep -rn "SPECIALIST_TIMEOUT_S" --include="*.py"

# Syntax check
python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase3_invoker.py', doraise=True)"

# Tests must PASS literally
pytest tests/test_cortex_specialist_timeout_tunable.py tests/test_cortex_runner_phase3.py -v

# Commit + push
git add orchestrator/cortex_phase3_invoker.py tests/test_cortex_specialist_timeout_tunable.py briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md briefs/_tasks/CODE_3_PENDING.md
git commit -m "feat(cortex): SPECIALIST_TIMEOUT_S env-tunable + default 60→180s

Real AO cycle fc382469 hit 300s outer cap inside Render — Phase 3b sales
specialist exhausted 60s × 3 retry budget on rich Director question. Opus
on heavy reasoning + tool calls genuinely needs 60-180s; the 60s cap was
too aggressive for production prompts.

- New env: CORTEX_SPECIALIST_TIMEOUT_S (default 180, was hardcoded 60)
- Single test for env-override behavior
- No retry logic / cycle cap changes in this PR

Brief: briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md
Trigger class: LOW.

Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push -u origin cortex-specialist-timeout-tunable-1
gh pr create \
  --title "feat(cortex): SPECIALIST_TIMEOUT_S env-tunable + default 60→180s" \
  --body "Per BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1. LOW trigger class.

## Why
Real AO cycle inside Render still hit 300s outer cap. Phase 3a clean (19s) but Phase 3b sales specialist timed out at 60s × 3 = 180s. Opus needs more time for heavy reasoning. Director picked 3 min.

## What
- SPECIALIST_TIMEOUT_S now env-tunable via CORTEX_SPECIALIST_TIMEOUT_S
- Default bumped 60→180s
- 1 test confirms env override works

## Tests
- tests/test_cortex_specialist_timeout_tunable.py — PASSES literally
- tests/test_cortex_runner_phase3.py regression — PASSES literally

## Reviewers
- AI Head A solo (LOW trigger class — RA-24 narrowing applies)
"
```

## Pass criteria

- New test PASSES literally
- Phase 3 regression suite PASSES literally
- py_compile clean
- PR opened
- Only 2 listed files modified

## STOP criteria

- Tests fail → STOP, surface
- Phase 3 regression breaks → STOP, surface
- grep finds another module importing SPECIALIST_TIMEOUT_S → STOP, surface (need to update that too)

## Output

`briefs/_reports/B3_specialist_timeout_tunable_20260429.md` with PR URL + literal test stdout.

## After merge — A executes

1. Render env vars per-key PUT:
   - `CORTEX_SPECIALIST_TIMEOUT_S=180`
   - `CORTEX_CYCLE_TIMEOUT_SECONDS=900`
2. Redeploy
3. Refire AO Baden-Baden question via `/api/cortex/trigger`
4. Surface result

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
