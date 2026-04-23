# Ship Report — B1 LEDGER_ATOMIC_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_LEDGER_ATOMIC_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/51
**Branch:** `ledger-atomic-1`
**Commit:** `chanda(detector#2): ledger_atomic context manager + cortex.publish_event migration`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge
**Sequence:** CHANDA_ENFORCEMENT_1 (PR #45) → AUTHOR_DIRECTOR_GUARD_1 (PR #49) → **LEDGER_ATOMIC_1 (this)** → MAC_MINI_WRITER_AUDIT_1 (docs)

---

## Scope

CHANDA invariant #2 detector ships. Primary Director-action write and `baker_actions` ledger row now land in ONE DB transaction. `cortex.publish_event()` is the first caller migrated; dead `_audit_to_baker_actions` function + its section header removed.

## `git diff --stat`

```
 CHANDA_enforcement.md |  1 +
 models/cortex.py      | 99 +++++++++++++++++----------------------------------
 2 files changed, 34 insertions(+), 66 deletions(-)
```

Plus 2 new files:
- `invariant_checks/ledger_atomic.py` (148 lines)
- `tests/test_ledger_atomic.py` (225 lines)

Total: **4 files touched — 409 insertions, 66 deletions.**

## cortex.py line-count delta

| | Lines |
|---|---|
| Before (main) | 771 |
| After (branch) | 738 |
| **Delta** | **-33 net** |

Brief estimated ~-30 net. Actual -33. Primary contribution: deletion of 34-line `_audit_to_baker_actions` helper + its section header; new atomic-block body replaces previous body with similar LOC.

## Main baseline pytest (pre-branching)

```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 819 passed, 21 skipped, 8 warnings, 19 errors in 11.14s ======
```

Recorded on main `679a684` (post-PR #49 merge) before creating `ledger-atomic-1`.

## 10 Quality Checkpoints — literal outputs

### 1. py_compile helper

```
$ python3 -c "import py_compile; py_compile.compile('invariant_checks/ledger_atomic.py', doraise=True)"
(clean — zero output)
```
**PASS.**

### 2. py_compile cortex.py

```
$ python3 -c "import py_compile; py_compile.compile('models/cortex.py', doraise=True)"
(clean — zero output)
```
**PASS.**

### 3. py_compile test

```
$ python3 -c "import py_compile; py_compile.compile('tests/test_ledger_atomic.py', doraise=True)"
(clean — zero output)
```
**PASS.**

### 4. Import smoke

```
$ python3 -c "from invariant_checks.ledger_atomic import atomic_director_action; assert callable(atomic_director_action)"
(clean — zero output, zero error)
```
**PASS.**

### 5. Dead-code sweep

```
$ grep -n "_audit_to_baker_actions" models/cortex.py
(zero matches)
```
**PASS — dead function fully removed.**

### 6. New-helper reference count

```
$ grep -n "atomic_director_action" models/cortex.py
239:    from invariant_checks.ledger_atomic import atomic_director_action
248:        with atomic_director_action(
```
**PASS — exactly 2 matches (inline import + with statement).**

### 7. New tests pass

```
$ pytest tests/test_ledger_atomic.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 6 items

tests/test_ledger_atomic.py::test_happy_path_both_rows_land PASSED       [ 16%]
tests/test_ledger_atomic.py::test_primary_raises_both_rows_rolled_back PASSED [ 33%]
tests/test_ledger_atomic.py::test_ledger_raises_primary_rolled_back PASSED [ 50%]
tests/test_ledger_atomic.py::test_no_conn_raises_runtime_error PASSED    [ 66%]
tests/test_ledger_atomic.py::test_payload_serialized_as_json PASSED      [ 83%]
tests/test_ledger_atomic.py::test_multiple_writes_each_atomic PASSED     [100%]

============================== 6 passed in 0.01s ===============================
```
**PASS — 6/6.**

### 8. Full-suite regression

**Main (pre-branching, baseline):**
```
19 failed, 819 passed, 21 skipped, 8 warnings, 19 errors in 11.14s
```

**Branch (post-change):**
```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 825 passed, 21 skipped, 8 warnings, 19 errors in 10.94s ======
```

**Delta:** `passed` +6 (819 → 825), `failed` 0, `errors` 0. **PASS — +6, 0 regressions.**

### 9. Amendment log checks

```
$ grep -c "^| 2026-04" CHANDA_enforcement.md
3

$ grep "ledger_atomic.py" CHANDA_enforcement.md
| #2 Ledger atomicity | `invariant_checks/ledger_atomic.py` | runtime DB txn wrapper | all Director-action handlers |
| 2026-04-23 | §4 row #2 + §6 | Detector #2 shipped: `invariant_checks/ledger_atomic.py` context manager binds Director-action primary write and `baker_actions` ledger row into one DB transaction. First caller: `cortex.publish_event()` (LEDGER_ATOMIC_1, PR TBD). Follow-on briefs migrate remaining call sites. | "default recom is fine" (2026-04-21) |

$ tail -1 CHANDA_enforcement.md
| 2026-04-23 | §4 row #2 + §6 | Detector #2 shipped: ... | "default recom is fine" (2026-04-21) |
```

**PASS — count=3 (2026-04-21 initial + 2026-04-23 #4 + 2026-04-23 #2), `ledger_atomic.py` present (2 hits: §6 detector pointer pre-existed + new amendment row), new row at tail.**

### 10. Singleton hook still green

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```
**PASS.**

## Test coverage (6 scenarios, hermetic sqlite3)

| # | Test | Scenario | Invariant exercised |
|---|---|---|---|
| 1 | `test_happy_path_both_rows_land` | Primary INSERT + ledger INSERT both commit | Atomic COMMIT — count(cortex_events)=1 + count(baker_actions)=1 |
| 2 | `test_primary_raises_both_rows_rolled_back` | Caller raises `sqlite3.OperationalError` (invalid SQL) | Atomic ROLLBACK on primary failure — both counts 0 |
| 3 | `test_ledger_raises_primary_rolled_back` | Fault-injected cm variant raises after primary executes | Atomic ROLLBACK on ledger failure — both counts 0 |
| 4 | `test_no_conn_raises_runtime_error` | `conn=None` | `RuntimeError: conn is None` raised — programmer error surfaced, not swallowed |
| 5 | `test_payload_serialized_as_json` | `payload={"k":"v","n":42}` | JSON roundtrip correct in `baker_actions.payload` |
| 6 | `test_multiple_writes_each_atomic` | Two sequential atomic blocks | Both counts = 2 — no state bleed between invocations |

## Files

- **A** `invariant_checks/ledger_atomic.py` (NEW, 148 lines) — `@contextmanager atomic_director_action`
- **A** `tests/test_ledger_atomic.py` (NEW, 225 lines) — 6 fault-injection scenarios
- **M** `models/cortex.py` (-33 lines net: 34 ins, 67 del) — migrate publish_event + delete dead helper
- **M** `CHANDA_enforcement.md` (+1 line) — §7 amendment log entry

## Out of scope (confirmed)

- ✅ No `clickup_client.py:146` migration (follow-on: `LEDGER_ATOMIC_CLICKUP_1`)
- ✅ No `StoreBack.log_baker_action()` call-site changes elsewhere
- ✅ No touch to `memory/store_back.py:3360-3397` (standalone callers still need current behaviour)
- ✅ No touch to `_log_dedup_event` (informational shadow log, not a ledger write)
- ✅ No touch to dedup gate (lines 189-236 of cortex.py, unchanged)
- ✅ No live-PG test lane (hermetic sqlite3 is standard)
- ✅ No touch to `CHANDA.md`, `triggers/embedded_scheduler.py`, `memory/store_back.py`, `clickup_client.py`
- ✅ No §8 added to CHANDA_enforcement.md — single row append only
- ✅ No env kill-switch (code-only helper; rollback via `git revert`)

## Timebox

Target: 2–2.5h. Actual: **~1h25** (inspection + helper + migration + 6 tests + 10 checkpoints + PR + report). Well within tolerance.

## Post-merge AI Head actions (per brief §Post-merge — NOT B-code scope)

1. **Live-DB smoke** (10 min): fire `cortex.publish_event()` with distinctive `source_agent` (`ai-head-smoke-<timestamp>`); verify paired `cortex_events.id` + `baker_actions.id` rows via:
   ```sql
   SELECT e.id AS event_id, a.id AS action_id, a.trigger_source, a.created_at
   FROM cortex_events e
   JOIN baker_actions a ON a.trigger_source = e.source_agent
   WHERE e.source_agent LIKE 'ai-head-smoke-%'
   ORDER BY e.id DESC LIMIT 5;
   ```
   Expect: matching event_id + action_id pair, timestamps within seconds.
2. **7-day orphan watch:** count of `cortex_events` without matching `baker_actions` trigger_source/timestamp should stay at 0.
3. Log AI Head actions to `_ops/agents/ai-head/actions_log.md`.
4. Queue follow-on brief `LEDGER_ATOMIC_CLICKUP_1` after 30-day observation window (per Research matrix §Recommendation step 5).

## Rollback

`git revert <merge-sha>` — single PR, clean. No schema changes, no data migrations. No env gate.

---

**Dispatch ack:** received 2026-04-23, Team 1 fourth brief this session. Ready for B3 review.
