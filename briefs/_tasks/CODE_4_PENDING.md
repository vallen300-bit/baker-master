---
status: COMPLETE
brief: inline
trigger_class: TIER_B_MODEL_DEPRECATION_SWEEP
dispatched_at: 2026-05-12
dispatched_by: aihead1
estimated_effort: 30-45 min
shipped_at: 2026-05-12
shipped_pr: 192
merged_commit: 31454dc
ship_report: briefs/_reports/B4_model_deprecation_sweep_1_20260512.md
gates_cleared: ah1_static + inline_security_review + code_reviewer_2nd_pass (PASS, 1 MEDIUM non-blocking)
---

# CODE_4 — MODEL_DEPRECATION_SWEEP_1 — 2026-05-12

## Problem

Anthropic deprecated Claude Opus 4 (`claude-opus-4-20250514`) and Claude Sonnet 4 (`claude-sonnet-4-20250514`) on 2026-04-14. Retirement: **2026-06-15** (34 days from dispatch). Any live API call to these IDs after that date will hard-error.

Baker codebase still references both retired IDs. Sweep them.

Source: https://platform.claude.com/docs/en/release-notes/api entry "Apr 14, 2026" + https://platform.claude.com/docs/en/about-claude/model-deprecations.

## Scope — exhaustive (verified via grep before dispatch)

**File 1: `orchestrator/memory_consolidator.py` line 49**

Current:
```python
# Model for Tier 2 compression (Opus — lossless critical details)
TIER2_MODEL = "claude-opus-4-20250514"
```

Replace with:
```python
# Model for Tier 2 compression (Opus — lossless critical details)
TIER2_MODEL = "claude-opus-4-6"
```

Rationale: like-for-like Opus replacement. Matches surrounding production Cortex paths (`PHASE3A_MODEL` / `PHASE3B_MODEL_FOR_COST` / `PHASE3C_MODEL` / `capability_runner.py:317` all `claude-opus-4-6`). This is NOT a 4.6→4.7 model bump — that's a separate eval-gated brief on the Cortex roadmap (M4).

`TIER3_MODEL` on line 51 (`gemini-2.5-pro`) is already migrated — no action.

**File 2: `orchestrator/cost_monitor.py` line 29**

Current (inside `MODEL_COSTS` dict, lines 25-34):
```python
MODEL_COSTS = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},   # ← DELETE THIS LINE
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # Gemini
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}
```

Action: **delete the `"claude-sonnet-4-20250514"` line entirely**. `claude-sonnet-4-6` entry (line 28) covers current Sonnet 4 family pricing; `DEFAULT_COSTS` on line 35 is the fallback if any code still references an unknown ID.

## Out of scope — DO NOT TOUCH

- `briefs/BRIEF_GEMINI_MIGRATION_1.md` + `briefs/BRIEF_THREE_TIER_MEMORY.md` — reference retired IDs in document body. **Append-only audit trail per project CLAUDE.md.** Leave alone.
- Cortex Phase 3 paths still on `claude-opus-4-6` — separate brief (M4 eval-gated).
- Main config `config/settings.py:47` `model: str = "claude-opus-4-6"` — current, not retired.
- Any `_20250514`-suffixed references in test fixtures / golden sets — leave; tests asserting on retired-ID strings are their own brief.

## Acceptance criteria

1. `grep -rn "claude-opus-4-20250514" --include="*.py" .` returns **zero matches**
2. `grep -rn "claude-sonnet-4-20250514" --include="*.py" .` returns **zero matches**
3. Literal `pytest` green — no "by inspection"
4. `python3 -c "from orchestrator.memory_consolidator import TIER2_MODEL; assert TIER2_MODEL == 'claude-opus-4-6'; print('OK')"` prints `OK`
5. `python3 -c "from orchestrator.cost_monitor import MODEL_COSTS; assert 'claude-sonnet-4-20250514' not in MODEL_COSTS; assert 'claude-sonnet-4-6' in MODEL_COSTS; print('OK')"` prints `OK`

## Test plan

1. Run targeted: `pytest tests/test_memory_consolidator.py tests/test_cost_monitor.py -v` (or whatever exists)
2. Run full: `pytest`
3. Smoke compile: `python3 -c "import py_compile; py_compile.compile('orchestrator/memory_consolidator.py', doraise=True); py_compile.compile('orchestrator/cost_monitor.py', doraise=True)"`

## Ship gate

- Literal `pytest` green output pasted in ship report
- `/security-review` clean (will be triggered by AH1 on PR)
- Commit message: `fix(model-deprecation): retire claude-opus-4 + claude-sonnet-4 references (MODEL_DEPRECATION_SWEEP_1)`
- PR title: `fix(model-deprecation): retire June 15 model IDs (MODEL_DEPRECATION_SWEEP_1)`

## Code Brief Standards verification

- **API version:** Anthropic Messages API, current
- **Deprecation check date:** 2026-05-12 (this brief)
- **Fallback note:** none required — replacement IDs are current GA; cost_monitor delete falls through to `DEFAULT_COSTS` if any code path still calls the retired ID
- **Migration-vs-bootstrap DDL check:** N/A (no schema change)
- **Singleton pattern `_get_global_instance()`:** N/A (no instantiation touched)
- **`file:line` citation:** both line refs verified by AH1 Read tool 2026-05-12 before dispatch (memory_consolidator.py:49 + cost_monitor.py:29)
- **Post-merge script handoff:** N/A (no script invocation)
- **Invocation-path audit (Amendment H):** N/A (no capability_sets touched)

## Tier classification

**Tier B** — production code change touching model API surface + cost-tracking dict. PR triggers:
1. AH1 static review
2. `/security-review` skill
3. `feature-dev:code-reviewer` 2nd-pass (per SKILL.md §"Code-reviewer 2nd-pass Protocol", trigger 4: PR touches external-surface API or model perimeter)

## Bus-post on ship

Per `_ops/processes/agent-bus-posting-contract.md` (ratified 2026-05-11): post `ship/MODEL_DEPRECATION_SWEEP_1` to `lead` bus topic with PR# + commit anchor when merged.

## Heartbeat cadence

Per AH1 SKILL.md §B-code stall chase: heartbeat every 12h minimum while building. This brief should ship same-day; expect single heartbeat on PR-open.
