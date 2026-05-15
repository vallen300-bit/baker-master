---
brief: briefs/BRIEF_SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1.md
status: SHIPPED (pending AH2 review + merge + 24h post-deploy verification)
ship_date: 2026-05-15
author: B4
dispatch_thread: (continuation of d7bbae22-b24d-47f8-9b32-49ef11b9c79d)
pr: 207
branch: b4/scheduler-watchdog-false-positive-fix-1
head_sha: c7633b2
trigger_class: LOW (single-file behaviour-narrow, no auth/DB/external surface)
mandatory_2nd_pass: FALSE
prior_brief_complete: |
  SCHEDULER_WATCHDOG_WA_KILL_1 (Phase A — PR #206 merged ac8f707 @ 15:57Z;
  ship report 3f38d02). SCHEDULER_CRASHLOOP_RCA_2 (Phase B — ship report
  b50a424). This PR implements the §6 fix proposal from that RCA.
---

# B4 ship report — SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1

## Hard ship gate (3 of 5 PASS; 2 deferred to AH2 review + 24h post-deploy)

### Gate 1 — Compile clean

```
$ python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True); py_compile.compile('outputs/dashboard.py', doraise=True); print('COMPILE OK')"
COMPILE OK
```

### Gate 2+3 — Literal pytest output (under repo `.venv-test`, Python 3.12)

```
$ .venv-test/bin/pytest tests/test_scheduler_heartbeat_order.py tests/test_watchdog_cooldown.py -v
============================= test session starts ==============================
tests/test_scheduler_heartbeat_order.py::test_watermark_written_before_probe PASSED [ 11%]
tests/test_scheduler_heartbeat_order.py::test_probe_failure_does_not_restart PASSED [ 22%]
tests/test_scheduler_heartbeat_order.py::test_watermark_written_when_no_held_conn PASSED [ 33%]
tests/test_watchdog_cooldown.py::test_watchdog_alert_throttled PASSED    [ 44%]
tests/test_watchdog_cooldown.py::test_watchdog_alert_fires_again_after_cooldown PASSED [ 55%]
tests/test_watchdog_cooldown.py::test_watchdog_no_alert_when_heartbeat_fresh PASSED [ 66%]
tests/test_watchdog_cooldown.py::test_single_stale_does_not_restart PASSED [ 77%]
tests/test_watchdog_cooldown.py::test_two_consecutive_stale_restart PASSED [ 88%]
tests/test_watchdog_cooldown.py::test_fresh_read_resets_counter PASSED   [100%]
======================== 9 passed, 6 warnings in 0.34s =========================
```

### Gate 4 — AH2 cross-lane review + `/security-review`

PENDING — AH2 to run on PR #207. Trigger class LOW (single-file behaviour-narrow, no auth/DB/external surface).

### Gate 5 — Post-deploy 24h verification

DEFERRED — runs ~2026-05-16T20:30Z. Query + pass criteria per brief §"Post-deploy verification". Ship-report addendum appended here at that time.

## Implementation summary

### Fix 1 — `triggers/embedded_scheduler.py:1372-1407`

`_scheduler_heartbeat` reordered: watermark write FIRST, singleton-lock probe AFTER. Probe is now diagnostic-only — WARN log on failure, NO `restart_scheduler()` call from inside the heartbeat job thread (reentrancy-hostile: `_scheduler.shutdown(wait=True)` joins worker threads, a thread cannot join itself). The middleware watchdog at `outputs/dashboard.py:185` is the sole restarter going forward.

Module-style import (`import triggers.scheduler_lease as _lease; held = _lease._held_conn`) preserved from the prior implementation — required so `patch("triggers.scheduler_lease._held_conn", ...)` in tests rebinds the live module attribute on each probe.

### Fix 2 — `outputs/dashboard.py:165-220`

Added `_watchdog_consecutive_stale` module-level counter. `_check_scheduler_heartbeat` now requires TWO consecutive stale reads (≥720s, 60s apart per middleware throttle) before firing `restart_scheduler()`. Single stale read logs INFO ("on read #1/2. Waiting one more tick.") and returns early. Counter resets to 0 on fresh-read OR on restart. 720s stale threshold + 60s middleware throttle + 300s WARN cooldown all unchanged.

## Files modified

- `triggers/embedded_scheduler.py` — `_scheduler_heartbeat` reorder + in-job restart removal (1372-1407)
- `outputs/dashboard.py` — `_watchdog_consecutive_stale` state + 2-consecutive-stale gate (170, 185-225)
- `tests/test_scheduler_heartbeat_order.py` (NEW) — 3 tests covering Fix 1
- `tests/test_watchdog_cooldown.py` — 3 existing tests updated for new gate semantics + 3 new tests for Fix 2

## Not touched (per brief §"Do NOT Touch")

- `triggers/scheduler_lease.py` — singleton-harden logic correct, not this fix's scope
- `outputs/dashboard.py:202-204` — Phase A WATCHDOG_RESTART log line preserved
- 720s stale threshold (`outputs/dashboard.py:198`) — gate is orthogonal to threshold
- 300s heartbeat interval (`triggers/embedded_scheduler.py` registration site)

## Post-deploy verification (planned, addendum follows after 24h)

Per brief, will run this SQL 24h after merge and append the literal output here:

```sql
SELECT job_id,
       COUNT(*) AS n_fired,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap) AS p50_gap,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY gap) AS p90_gap,
       MAX(gap) AS max_gap,
       COUNT(*) FILTER (WHERE gap > 720) AS n_over_720s
FROM (
  SELECT job_id, fired_at,
         EXTRACT(EPOCH FROM (fired_at - LAG(fired_at) OVER (PARTITION BY job_id ORDER BY fired_at))) AS gap
  FROM scheduler_executions
  WHERE fired_at > NOW() - INTERVAL '24 hours'
) t
WHERE gap IS NOT NULL
GROUP BY job_id
ORDER BY p90_gap DESC;
```

Pass criteria:
1. `scheduler_heartbeat` p90 gap < 500s (current pre-fix: 746s)
2. `scheduler_heartbeat` `n_over_720s` = 0
3. `pg_stat_activity` oldest `backend_start` for lock-holder > 1h (no 12-min rotation)
4. 0 `WATCHDOG_RESTART` log lines in Render logs over 24h

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
