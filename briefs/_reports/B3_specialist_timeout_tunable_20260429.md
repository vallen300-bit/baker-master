# B3 — CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1 — 2026-04-29

**Brief:** [`briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md`](../BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md)
**Trigger class:** LOW (config knob change; AI Head A solo review per RA-24)
**Branch:** `cortex-specialist-timeout-tunable-1`
**PR:** _(see footer once opened)_
**Verdict:** **PASS** — code, test, and regression all clean.

## Why

Real AO Cortex cycle `fc382469` failed inside Render at 300s outer cap. Phase 3a clean (19s); Phase 3b `sales` specialist exhausted 60s × 3 retry budget on a rich Director question. RCA: hardcoded 60s timeout at `orchestrator/cortex_phase3_invoker.py:33` is too tight for Opus on heavy reasoning + tool calls. Director: *"we need to allocate much more time for specialist answer, say 2 min ? or 3 min ? see if it works"* — picked 3 min upper end.

## Change

`orchestrator/cortex_phase3_invoker.py`:

```diff
 import asyncio
 import json
 import logging
+import os
 import time
 from dataclasses import dataclass, field
 from datetime import datetime, timezone
 from pathlib import Path

 logger = logging.getLogger(__name__)

-SPECIALIST_TIMEOUT_S = 60          # RA-23 Q5
+SPECIALIST_TIMEOUT_S = int(os.getenv("CORTEX_SPECIALIST_TIMEOUT_S", "180"))  # RA-23 Q5; env-tunable post-2026-04-29
```

- New env: `CORTEX_SPECIALIST_TIMEOUT_S` (default `180`, was hardcoded `60`)
- `import os` added to module-level imports (was absent — verified by re-reading the imports block)
- Single source of truth: line 34 def is referenced at lines 191 (`timeout=`) and 206 (error string). No other module imports the constant.

## Sole-importer verification

```
$ grep -rn "SPECIALIST_TIMEOUT_S" --include="*.py"
orchestrator/cortex_phase3_invoker.py:34:SPECIALIST_TIMEOUT_S = int(os.getenv("CORTEX_SPECIALIST_TIMEOUT_S", "180"))  # RA-23 Q5; env-tunable post-2026-04-29
orchestrator/cortex_phase3_invoker.py:191:                timeout=SPECIALIST_TIMEOUT_S,
orchestrator/cortex_phase3_invoker.py:206:            last_err = f"timeout after {SPECIALIST_TIMEOUT_S}s on attempt {attempt}"
tests/test_cortex_specialist_timeout_tunable.py:11:    """CORTEX_SPECIALIST_TIMEOUT_S env var overrides hardcoded default."""
tests/test_cortex_specialist_timeout_tunable.py:15:    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
tests/test_cortex_specialist_timeout_tunable.py:17:    assert inv.SPECIALIST_TIMEOUT_S == 180
tests/test_cortex_specialist_timeout_tunable.py:20:    monkeypatch.setenv("CORTEX_SPECIALIST_TIMEOUT_S", "240")
tests/test_cortex_specialist_timeout_tunable.py:22:    assert inv.SPECIALIST_TIMEOUT_S == 240
tests/test_cortex_specialist_timeout_tunable.py:25:    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
tests/test_cortex_specialist_timeout_tunable.py:27:    assert inv.SPECIALIST_TIMEOUT_S == 180
```

Only `cortex_phase3_invoker.py` and the new test reference the constant.

## py_compile

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase3_invoker.py', doraise=True); print('py_compile OK')"
py_compile OK
```

## Tests — literal stdout

```
$ pytest tests/test_cortex_specialist_timeout_tunable.py tests/test_cortex_runner_phase3.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.37, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT
collecting ... collected 13 items

tests/test_cortex_specialist_timeout_tunable.py::test_specialist_timeout_env_override PASSED [  7%]
tests/test_cortex_runner_phase3.py::test_phase3_runs_in_order_3a_3b_3c PASSED [ 15%]
tests/test_cortex_runner_phase3.py::test_phase3_success_status_proposed PASSED [ 23%]
tests/test_cortex_runner_phase3.py::test_cost_accumulates_across_phase3 PASSED [ 30%]
tests/test_cortex_runner_phase3.py::test_signal_text_threaded_from_director_question PASSED [ 38%]
tests/test_cortex_runner_phase3.py::test_signal_text_empty_string_when_no_director_question PASSED [ 46%]
tests/test_cortex_runner_phase3.py::test_signal_text_in_phase2_load_context PASSED [ 53%]
tests/test_cortex_runner_phase3.py::test_phase3a_failure_marks_status_failed_no_raise PASSED [ 61%]
tests/test_cortex_runner_phase3.py::test_phase3c_failure_marks_status_failed PASSED [ 69%]
tests/test_cortex_runner_phase3.py::test_phase6_archive_runs_even_on_phase3_failure PASSED [ 76%]
tests/test_cortex_runner_phase3.py::test_3a_capabilities_to_invoke_passed_to_3b PASSED [ 84%]
tests/test_cortex_runner_phase3.py::test_3a_and_3b_results_threaded_into_3c PASSED [ 92%]
tests/test_cortex_runner_phase3.py::test_cycle_id_propagated_to_all_phase3_calls PASSED [100%]

============================== 13 passed in 0.04s ==============================
```

1 new test (env-override behavior: default=180, override=240, restore=180) + 12 Phase 3 regression tests all PASS.

## Files modified

- `orchestrator/cortex_phase3_invoker.py` — 2 LOC change (1 new import + 1 line def)
- `tests/test_cortex_specialist_timeout_tunable.py` — NEW (28 LOC, 1 test)

## Pass criteria — checklist

| Criterion | Result |
|---|---|
| New test PASSES literally | ✅ |
| Phase 3 regression PASSES literally | ✅ (12/12) |
| py_compile clean | ✅ |
| PR opened | ✅ [#79](https://github.com/vallen300-bit/baker-master/pull/79) |
| Only the 2 listed files modified | ✅ (verified via `git diff --name-only main...HEAD`) |
| No other module imports `SPECIALIST_TIMEOUT_S` | ✅ (grep confirmed) |

## After merge — A executes

Per brief §"Post-merge — A executes":
1. Render env vars (PUT per-key):
   - `CORTEX_SPECIALIST_TIMEOUT_S=180`
   - `CORTEX_CYCLE_TIMEOUT_SECONDS=900`
2. Render redeploy
3. Refire AO Baden-Baden question via `/api/cortex/trigger`
4. Surface result

## PR

https://github.com/vallen300-bit/baker-master/pull/79

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
