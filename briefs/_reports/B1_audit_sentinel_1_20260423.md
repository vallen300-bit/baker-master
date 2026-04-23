# Ship Report — B1 AUDIT_SENTINEL_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_AUDIT_SENTINEL_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/48
**Branch:** `audit-sentinel-1`
**Commit:** `audit-sentinel: scheduler_executions table + listener extension + Mon 10:00 UTC sentinel cron`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge
**Hard deadline:** 2026-04-26T23:59Z — met with 3.5d margin.

---

## Scope

First-fire observability for `ai_head_weekly_audit` (first fires Mon 2026-04-27 09:00 UTC). Phase 1 only — Part-G Q1–Q5 as ratified 2026-04-23 in `_ops/ideas/2026-04-23-first-fire-observability.md`.

- `scheduler_executions` PG table bootstrap (+ __init__ wiring)
- Extended `_job_listener` writes a durable row per APScheduler event (fault-tolerant, singleton-safe)
- New weekly cron `ai_head_audit_sentinel` (Mon 10:00 UTC) — SELECTs both `ai_head_audits` + `scheduler_executions`; either missing → Slack DM to `D0AFY28N030`
- Dedupe via `status='alerted'` self-write
- Env gate `AI_HEAD_AUDIT_SENTINEL_ENABLED` (default `true`)

## `__init__` wiring — 1-line diff (Quality Checkpoint §6)

```diff
@@ -147,6 +147,9 @@ class SentinelStoreBack:
         # BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Weekly AI Head self-audit records
         self._ensure_ai_head_audits_table()

+        # BRIEF_AUDIT_SENTINEL_1: Persistent APScheduler job execution log
+        self._ensure_scheduler_executions_table()
+
         # CORRECTION-MEMORY-1: Learned corrections from Director feedback
         self._ensure_baker_corrections_table()
```

`_ensure_scheduler_executions_table()` is wired in `__init__` immediately after `_ensure_ai_head_audits_table()` — confirmed via diff above.

## Ship gate — literal outputs (per `feedback_no_ship_by_inspection.md`)

### 1. py_compile (4 files, zero-output expected)

```
$ python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
(no errors)
$ python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
(no errors)
$ python3 -c "import py_compile; py_compile.compile('triggers/audit_sentinel.py', doraise=True)"
(no errors)
$ python3 -c "import py_compile; py_compile.compile('tests/test_audit_sentinel.py', doraise=True)"
(no errors)
```

**PASS — all 4 files compile cleanly.**

### 2. Singleton pre-push hook (PR #46)

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

**PASS.** Both `SentinelStoreBack._get_global_instance()` (listener + sentinel) use the enforced singleton accessor.

### 3. `pytest tests/test_audit_sentinel.py -v` — 6 tests

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 6 items

tests/test_audit_sentinel.py::test_listener_writes_executed_row PASSED   [ 16%]
tests/test_audit_sentinel.py::test_listener_writes_error_row PASSED      [ 33%]
tests/test_audit_sentinel.py::test_listener_survives_db_unavailable PASSED [ 50%]
tests/test_audit_sentinel.py::test_sentinel_clean_path PASSED            [ 66%]
tests/test_audit_sentinel.py::test_sentinel_miss_alerts PASSED           [ 83%]
tests/test_audit_sentinel.py::test_sentinel_deduped PASSED               [100%]

============================== 6 passed in 0.79s ===============================
```

**PASS — 6/6 as specified.**

### 4. Full-suite regression gate — main vs branch

**Baseline (`main`):**
```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 802 passed, 21 skipped, 8 warnings, 19 errors in 10.42s ======
```

**Branch (`audit-sentinel-1`):**
```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 808 passed, 21 skipped, 8 warnings, 19 errors in 10.05s ======
```

**Delta:** `passed` +6 (802 → 808), `failed` 0 change (19 → 19), `errors` 0 change (19 → 19).
**PASS — +6 passes, 0 regressions.**

*Note on baseline drift:* Brief predicted baseline on `b1d566f`. Actual main today is 19 failed / 802 passed / 19 errors (not 16/818/21). The 19 errors all come from `test_mcp_vault_tools.py` and pre-exist this PR. Whether they're environmental (bm-b2 venv fixture compat) or a real regression on main is out of scope — the relevant signal for THIS ship is identical error/fail counts between main and branch, confirming zero regression introduced.

## Test coverage (6 tests)

| Test | Scenario | Asserts |
|---|---|---|
| `test_listener_writes_executed_row` | Clean `EVENT_JOB_EXECUTED` | SQL is INSERT into scheduler_executions; `status='executed'`; `error_msg=None`; `conn.commit()` called |
| `test_listener_writes_error_row` | `EVENT_JOB_ERROR` with `ValueError("boom...")` | `status='error'`; `error_msg` contains `"boom"`; `conn.commit()` called |
| `test_listener_survives_db_unavailable` | `_get_conn()` returns `None` | No exception raised; no commit attempted |
| `test_sentinel_clean_path` | `audit_count=1`, `exec_count=1` | `alerted=False`, `reason='clean'` |
| `test_sentinel_miss_alerts` | Both counts 0, no prior alert, Slack OK | `alerted=True`, `slack_ok=True`, dedupe-anchor INSERT with `'alerted'` executed, Slack called with `DIRECTOR_DM_CHANNEL` |
| `test_sentinel_deduped` | Miss detected, prior-alert count=1 | `alerted=False`, `reason='deduped'`, Slack NOT called |

## Files

- **M** `memory/store_back.py` — new `_ensure_scheduler_executions_table` method (40 lines) + 1-line `__init__` wiring
- **M** `triggers/embedded_scheduler.py` — extended `_job_listener` (+41 lines, ADD-ONLY), new sentinel cron registration (22 lines), new `_ai_head_audit_sentinel_job` wrapper (18 lines)
- **A** `triggers/audit_sentinel.py` — `run_sentinel_check()` (NEW, 135 lines)
- **A** `tests/test_audit_sentinel.py` — 6 unit tests (NEW, 174 lines)

Total: **458 insertions, 1 deletion** across 4 files.

## Out of scope (confirmed)

- ✅ Did NOT generalize listener across 12+ jobs (Phase 2 brief — separate)
- ✅ Did NOT touch `outputs/slack_notifier.py` — used `post_to_channel` as-is
- ✅ Did NOT touch `triggers/ai_head_audit.py` — PR #46 hotfix stays
- ✅ Did NOT add 90-day retention cleanup cron — Phase 2 brief
- ✅ Did NOT add `EVENT_JOB_SUBMITTED` listener — Phase 1 uses only EXECUTED+ERROR

## Timebox

Target: 1.5–2h. Actual: **~1h15** (inspection + edits + tests + CI gates + PR + report). Well within tolerance.

## Post-deploy verification (Director-facing, Mon 2026-04-27 ~10:05 UTC)

```sql
-- Was the new table bootstrapped on startup?
SELECT table_name FROM information_schema.tables WHERE table_name='scheduler_executions';
-- Expect: 1 row.

-- First-fire sanity check:
SELECT job_id, fired_at, completed_at, status, error_msg
  FROM scheduler_executions
 WHERE job_id IN ('ai_head_weekly_audit', 'ai_head_audit_sentinel')
   AND fired_at >= NOW() - INTERVAL '24 hours'
 ORDER BY fired_at DESC LIMIT 10;
-- Clean: 2 rows, both status='executed', no 'alerted'.
-- Problem: row missing or status='error' / 'alerted'.
```

Render log line to confirm registration: `Registered: ai_head_audit_sentinel (Mon 10:00 UTC)`.

## Ship shape

- Tier A — auto-merge on B3 APPROVE
- Single squash-ready commit
- Env kill-switch available (`AI_HEAD_AUDIT_SENTINEL_ENABLED=false`)
- Clean revert path

---

**Dispatch ack:** received 2026-04-23, Team 1 second brief this session. Ready for B3 review.
