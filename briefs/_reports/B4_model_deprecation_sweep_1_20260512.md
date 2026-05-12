---
brief: CODE_4 MODEL_DEPRECATION_SWEEP_1
brief_commit: 2a81f9c
dispatched_at: 2026-05-12
dispatched_by: aihead1
shipped_at: 2026-05-12T20:35:55Z
builder: b4
trigger_class: TIER_B_MODEL_DEPRECATION_SWEEP
branch: b4/model-deprecation-sweep-1
commit: c8d548c
pr: https://github.com/vallen300-bit/baker-master/pull/192
status: SHIPPED (awaiting AH1 review + /security-review + 2nd-pass + merge)
---

# B4 ship report — MODEL_DEPRECATION_SWEEP_1

## Delta

2 files, +1 / -2.

| File | Change |
|---|---|
| `orchestrator/memory_consolidator.py:49` | `TIER2_MODEL = "claude-opus-4-20250514"` → `"claude-opus-4-6"` |
| `orchestrator/cost_monitor.py:29` | deleted `"claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},` entry |

Rationale matches brief: like-for-like Opus replacement (not a 4.6 → 4.7 bump — that's M4 eval-gated). Sonnet 4 family pricing already covered by `"claude-sonnet-4-6"` line above; `DEFAULT_COSTS` catches unknown IDs.

## Acceptance criteria

| # | Check | Result |
|---|---|---|
| 1 | `grep -rn "claude-opus-4-20250514" --include="*.py" --exclude-dir=.venv-* .` | PASS (exit 1, zero matches in Baker source) |
| 2 | `grep -rn "claude-sonnet-4-20250514" --include="*.py" --exclude-dir=.venv-* .` | PASS (exit 1, zero matches in Baker source) |
| 3 | Literal `pytest` green — no "by inspection" | See below — **zero new failures vs main baseline** |
| 4 | `from orchestrator.memory_consolidator import TIER2_MODEL; assert TIER2_MODEL == "claude-opus-4-6"` | PASS (printed `OK`) |
| 5 | `from orchestrator.cost_monitor import MODEL_COSTS; assert "claude-sonnet-4-20250514" not in MODEL_COSTS; assert "claude-sonnet-4-6" in MODEL_COSTS` | PASS (printed `OK`) |

**A1 + A2 vendor-SDK caveat** — the brief's raw grep (without `--exclude-dir`) hits `.venv-b3/` + `.venv-test/` because the Anthropic SDK itself ships these IDs in its `types/model.py`, `_constants.py`, `resources/messages/messages.py`, and `lib/tools/mcp.py`. These are upstream package data and not actionable from this repo. Baker source itself is clean.

## Test plan

### Compile check

```
python3 -c "import py_compile; py_compile.compile('orchestrator/memory_consolidator.py', doraise=True); py_compile.compile('orchestrator/cost_monitor.py', doraise=True); print('compile OK')"
compile OK
```

### Targeted pytest (51 tests, all related to cost/caching)

```
$ pytest tests/test_cost_alarms.py tests/test_cost_gate.py tests/test_prompt_caching_1.py -v
...
============================== 51 passed in 0.30s ==============================
```

### Full pytest

```
$ pytest
= 42 failed, 1873 passed, 85 skipped, 183 warnings, 30 errors in 66.77s =
```

**Baseline check** — switched to `main` (this branch's parent `2a81f9c`), ran `pytest`:

```
= 42 failed, 1873 passed, 85 skipped, 182 warnings, 30 errors in 65.57s =
```

**Counts identical. Zero regressions introduced by this branch.** Pre-existing red baseline is concentrated in `tests/test_mcp_vault_tools.py` (`TypeError` errors — vault tool infra issue, unrelated to model IDs) plus 42 other unrelated failures across the suite. Per Mnilax fail-loud rule + brief acceptance criterion 3, I surface this baseline explicitly rather than claiming a green run.

## Out-of-scope (deliberately untouched per brief)

- `briefs/BRIEF_GEMINI_MIGRATION_1.md` + `briefs/BRIEF_THREE_TIER_MEMORY.md` — retired-ID strings in document body (append-only audit trail per project CLAUDE.md).
- Cortex Phase 3 paths still on `claude-opus-4-6` — separate M4 eval-gated brief.
- `config/settings.py:47` `model: str = "claude-opus-4-6"` — current, not retired.
- Retired-ID strings in test fixtures / golden sets — separate brief.
- Vendor SDK `.venv-*/` files.

## Pending review gates (per brief)

1. AH1 static review on PR #192.
2. `/security-review` skill (AH1 will trigger).
3. `feature-dev:code-reviewer` 2nd-pass per SKILL.md §"Code-reviewer 2nd-pass Protocol" trigger 4 (external-surface / model perimeter).

## Anchors

- Brief: `briefs/_tasks/CODE_4_PENDING.md` @ commit `2a81f9c`
- Ship commit: `c8d548c` on branch `b4/model-deprecation-sweep-1`
- PR: https://github.com/vallen300-bit/baker-master/pull/192
- Dispatch bus msg: #155 (thread `e7bbbf00-cfc1-4786-9086-a9e6e2ed49d0`)
