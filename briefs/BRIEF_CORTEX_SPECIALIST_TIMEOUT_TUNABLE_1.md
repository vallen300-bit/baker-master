# BRIEF: CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1 — Make specialist timeout env-tunable + bump default

## Context

Real AO Cortex cycle (`fc382469`) failed inside Render at 300s wall-time. Phase 3a clean (19s), Phase 3b `sales` specialist hit `60s × 3 attempts = 180s` retry budget, outer cycle cap fired. RCA: specialist timeout (hardcoded at `cortex_phase3_invoker.py:33`) is too short for rich Director questions where Opus needs 60-180s of thinking + tool calls. NOT a network issue.

Director: "we need to allocate much more time for specialist answer, say 2 min ? or 3 min ? see if it works"

## Estimated time: ~15min (4-line code change + 1 test + PR)
## Complexity: Trivial
## Trigger class: LOW (config knob change, no auth/API/migration)
## B1 review: NOT required (LOW trigger class)

## Fix

### Problem

`orchestrator/cortex_phase3_invoker.py:33`:
```python
SPECIALIST_TIMEOUT_S = 60          # RA-23 Q5
```

Hardcoded. Cannot tune via Render env without a code change every time.

### Implementation

**File:** `orchestrator/cortex_phase3_invoker.py`

**Change line 33 from:**
```python
SPECIALIST_TIMEOUT_S = 60          # RA-23 Q5
```

**To:**
```python
import os as _os_specialist_timeout
SPECIALIST_TIMEOUT_S = int(_os_specialist_timeout.getenv("CORTEX_SPECIALIST_TIMEOUT_S", "180"))  # RA-23 Q5; env-tunable post-2026-04-29
```

(If `os` is already imported at module level, just use `os.getenv` directly — re-grep imports at top of file to confirm. The above local import is a safe fallback.)

**Default bumped 60→180** (3 min). Director picked the upper end of "2 or 3 min".

### Test

Add to `tests/test_cortex_phase3_invoker.py` (or create `tests/test_cortex_specialist_timeout_tunable.py` if cleaner):

```python
def test_specialist_timeout_env_override(monkeypatch):
    """CORTEX_SPECIALIST_TIMEOUT_S env var overrides hardcoded default."""
    import importlib
    import orchestrator.cortex_phase3_invoker as inv

    # Default (no env set) should be 180 post-this-PR
    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
    importlib.reload(inv)
    assert inv.SPECIALIST_TIMEOUT_S == 180

    # Env override
    monkeypatch.setenv("CORTEX_SPECIALIST_TIMEOUT_S", "240")
    importlib.reload(inv)
    assert inv.SPECIALIST_TIMEOUT_S == 240

    # Reload back to default for other tests
    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
    importlib.reload(inv)
```

**Run:**
```bash
pytest tests/test_cortex_phase3_invoker.py tests/test_cortex_specialist_timeout_tunable.py -v
```

(or whichever file path you use — both must pass)

### Files Modified

- `orchestrator/cortex_phase3_invoker.py` — ~3 LOC change
- `tests/test_cortex_specialist_timeout_tunable.py` — NEW, ~25 LOC, 1 test

### Files NOT to touch

- `orchestrator/cortex_runner.py` — `CYCLE_TIMEOUT_SECONDS` already env-tunable (`CORTEX_CYCLE_TIMEOUT_SECONDS`), no change needed
- All Phase 3 retry / scheduling logic — out of scope

## Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase3_invoker.py', doraise=True)"` clean
2. New test PASSES literally (no "by inspection")
3. Existing `tests/test_cortex_runner_phase3.py` still PASSES after the change (regression check)
4. No other module imports `SPECIALIST_TIMEOUT_S` directly — `grep -rn "SPECIALIST_TIMEOUT_S" --include="*.py"` shows only `cortex_phase3_invoker.py` and tests

## Post-merge — A executes

1. Render env vars (PUT per-key, NOT raw replace):
   - `CORTEX_SPECIALIST_TIMEOUT_S=180`
   - `CORTEX_CYCLE_TIMEOUT_SECONDS=900`
2. Render redeploy
3. Refire real AO Baden-Baden question via `/api/cortex/trigger`
4. Surface result

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
