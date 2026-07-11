---
report: BUS_AUTOWAKE_HOOK_1
to: cowork-ah1
from: b2
dispatched_by: cowork-ah1
status: SHIPPED
shipped: 2026-05-25
pr: https://github.com/vallen300-bit/brisen-lab/pull/40
branch: bus-autowake-hook-1
commit: 0ff3043b0843c7518d3d5057e87135e10254331a
brief: ~/baker-vault/_ops/briefs/BRIEF_BUS_AUTOWAKE_HOOK_1.md
---

# B2 — BUS_AUTOWAKE_HOOK_1 ship report

## PR

**brisen-lab #40** — `bus-autowake-hook-1` → `main`, commit `0ff3043`.

## Files (3, +330/-2)

- `app.py` — 1-line param add at line 92
- `bus.py` — `terminals: set[str]` param on `register()`, module-level debounce state, hook block in `_post_msg_inner` after `_insert()` (gated on `BRISEN_LAB_AUTOWAKE_ENABLED` env, default `"true"`)
- `tests/test_bus_autowake.py` — NEW, 8 unit tests

## Pytest output (literal)

### New tests — `tests/test_bus_autowake.py`

```
tests/test_bus_autowake.py::test_single_message_to_picker_fires_wake PASSED [ 12%]
tests/test_bus_autowake.py::test_burst_within_window_fires_once PASSED   [ 25%]
tests/test_bus_autowake.py::test_burst_spanning_window_fires_twice PASSED [ 37%]
tests/test_bus_autowake.py::test_wildcard_broadcast_does_not_fire_wake PASSED [ 50%]
tests/test_bus_autowake.py::test_two_distinct_slugs_both_fire PASSED     [ 62%]
tests/test_bus_autowake.py::test_non_picker_recipient_does_not_fire_wake PASSED [ 75%]
tests/test_bus_autowake.py::test_kill_switch_off_suppresses_wake PASSED  [ 87%]
tests/test_bus_autowake.py::test_kill_switch_unset_defaults_to_enabled PASSED [100%]

======================== 8 passed, 2 warnings in 58.56s ========================
```

### Regression — `tests/test_a3_a8_a9_bus.py` + `tests/test_a1_routes.py`

```
================== 28 passed, 2 warnings in 198.01s (0:03:18) ==================
```

(No `tests/test_bus_post.py` in repo; ran the closest existing bus test files instead.)

### Syntax

```
python3 -c "import py_compile; py_compile.compile('app.py', doraise=True); py_compile.compile('bus.py', doraise=True); py_compile.compile('tests/test_bus_autowake.py', doraise=True)" → OK
```

## Test DB

`TEST_DATABASE_URL_BRISEN_LAB` fetched from 1Password via `op read "op://Baker API Keys/TEST_DATABASE_URL_BRISEN_LAB/credential"` (sibling Neon DB `brisen_lab_test` on `ep-summer-sun-aih7ha4h`).

## Outstanding (post-merge, AH1 owns)

- Director-side smoke #7-9 (live `bus_post.sh` → Terminal nudge within 2-3s) — requires deploy + listener
- Kill-switch smoke: PUT `BRISEN_LAB_AUTOWAKE_ENABLED=false` → no auto-wake; `/api/wake` click still works

## Gate chain

1. b2 self-test (pytest green) ✅
2. AH2 (deputy) static review — pending
3. `/security-review` — pending
4. cowork-ah1 merge — pending

## Brief amendment incorporated

Dispatch bus #1124 (2026-05-25 19:15Z) added `BRISEN_LAB_AUTOWAKE_ENABLED` kill-switch + 2 tests (6→8). Brief re-read post-amendment; hook wrapped in env check; tests `test_kill_switch_off_suppresses_wake` + `test_kill_switch_unset_defaults_to_enabled` added.
