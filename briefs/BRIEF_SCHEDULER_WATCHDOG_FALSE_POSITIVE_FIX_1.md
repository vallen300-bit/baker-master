# BRIEF: SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 — Stop the 12-min false-restart loop

## Context

`B4_scheduler_crashloop_rca2_20260515.md` (commit `b50a424`) RCA: the scheduler is not dying. The watchdog is firing on a false positive. High-frequency jobs (60s/120s) run cleanly with sub-3× interval drift; only the 5-min jobs that do multi-step DB writes / network probes have recurring >720s gaps. `scheduler_heartbeat` specifically probes the singleton-lock connection (`SELECT 1`) **before** writing the watermark — when the probe blocks (Neon serverless cold-start latency or transient network), the watermark write is delayed past 720s, the middleware watchdog reads stale, calls `restart_scheduler()`, which tears down the lock connection and creates a new one. Cycle resets every ~12 min. `pg_stat_activity` confirms: the lock-holding backend's `backend_start` rotates exactly on the 12-min cadence.

Secondary footgun: `_scheduler_heartbeat` ALSO calls `restart_scheduler()` from inside its own job thread when the probe fails (`triggers/embedded_scheduler.py:1395`). `_scheduler.shutdown(wait=True)` joins worker threads — a thread cannot join itself. Two restart call sites; at least one is reentrancy-hostile.

H1 (HOST_DIRECT unset), H3 (orphan lock), H4 (job exception), H5 (OOM) all falsified by DB evidence in the RCA. H2 (Neon auto-suspend on held conn) inconclusive — needs Render logs — but this fix neutralizes H2's *contribution to the false-positive loop* regardless.

## Estimated time: ~1h
## Complexity: Low (single-file behaviour-narrow, plus one optional file)
## Prerequisites: Read `briefs/_reports/B4_scheduler_crashloop_rca2_20260515.md` §1-§6 first

---

## Fix 1: Write watermark FIRST, before any IO probe

### Problem

`triggers/embedded_scheduler.py:1372-1403` runs the singleton-lock liveness probe (`SELECT 1` on `_lease._held_conn`) at the top of the heartbeat function. Probe is synchronous over the network. When the probe blocks, the watermark write at line 1401 is delayed. The middleware watchdog reads the stale watermark and fires `restart_scheduler()`.

Proof-of-life (the watermark) should NEVER depend on the outcome of a separate diagnostic probe. The heartbeat job ran; the watermark should be written.

### Current State (`triggers/embedded_scheduler.py:1372-1403`)

```python
def _scheduler_heartbeat():
    """SCHEDULER-WATCHDOG-1: Write proof-of-life timestamp to DB every 5 min.

    SCHEDULER_SINGLETON_HARDEN_1: also probe the held singleton-lock connection
    for liveness. If the connection died (Neon auto-suspend, network drop), the
    advisory lock is already server-side released — we restart the scheduler so
    the lock-acquire path runs cleanly and reclaims the lock (or yields to a
    sibling that beat us to it).
    """
    try:
        from triggers.scheduler_lease import _held_conn
        if _held_conn is not None:
            try:
                cur = _held_conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            except Exception as probe_err:
                logger.error(
                    "scheduler singleton-lock connection dead (%s) — forcing restart_scheduler()",
                    probe_err,
                )
                restart_scheduler()
                return  # restart will re-write heartbeat next cycle
    except Exception:
        pass
    try:
        from triggers.state import trigger_state
        trigger_state.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Scheduler heartbeat write failed: {e}")
```

### Implementation

Reorder: watermark write FIRST, probe AFTER. Probe failure logs WARN but **does NOT call `restart_scheduler()`** — middleware watchdog is the sole restarter.

```python
def _scheduler_heartbeat():
    """SCHEDULER-WATCHDOG-1: Write proof-of-life timestamp to DB every 5 min.

    SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (2026-05-15): watermark is written
    FIRST, before any IO probe. The probe is now diagnostic only — it logs WARN
    on failure but never calls restart_scheduler() from inside the heartbeat
    job thread (reentrancy-hostile: shutdown(wait=True) joins worker threads,
    a thread cannot join itself). The middleware watchdog at
    outputs/dashboard.py is the sole restarter.
    """
    # 1) Write watermark FIRST — proof-of-life is independent of probe latency.
    try:
        from triggers.state import trigger_state
        trigger_state.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Scheduler heartbeat write failed: {e}")

    # 2) Probe singleton-lock connection — diagnostic only, NO restart from here.
    try:
        from triggers.scheduler_lease import _held_conn
        if _held_conn is not None:
            try:
                cur = _held_conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            except Exception as probe_err:
                logger.warning(
                    "scheduler singleton-lock connection probe failed (%s). "
                    "Watchdog will restart on next stale-watermark detection; "
                    "this job does NOT self-restart (reentrancy-hostile).",
                    probe_err,
                )
    except Exception:
        pass
```

### Key Constraints

- Watermark write MUST be first. Any IO between function entry and watermark write reintroduces the bug.
- The probe stays but is now LOG-ONLY. Removing it entirely is a regression in observability — keep it for the WARN signal, drop only the auto-restart.
- DO NOT change the heartbeat interval (300s) or `next_run_time` at registration.
- DO NOT modify `triggers/scheduler_lease.py` — singleton-harden logic is correct; this fix is about WHEN we probe, not HOW.

### Verification

```python
# tests/test_scheduler_heartbeat_order.py (NEW)
"""SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 — heartbeat writes watermark before probe."""
from unittest.mock import patch, MagicMock, call

def test_watermark_written_before_probe():
    """If the lock-conn probe raises, the watermark is STILL written."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("Neon timed out")

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn):
        sched._scheduler_heartbeat()

    fake_state.set_watermark.assert_called_once()
    # Confirm watermark was set BEFORE the probe raised:
    # set_watermark must appear in the call trace; the test passes if it was called.


def test_probe_failure_does_not_restart():
    """Probe failure logs WARN but does NOT call restart_scheduler()."""
    import triggers.embedded_scheduler as sched

    fake_state = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = ConnectionError("dead")
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.scheduler_lease._held_conn", fake_conn), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        sched._scheduler_heartbeat()

    fake_restart.assert_not_called()
    fake_state.set_watermark.assert_called_once()
```

---

## Fix 2 (OPTIONAL but recommended): Two-consecutive-stale gate in middleware watchdog

### Problem

`outputs/dashboard.py:185-209` calls `restart_scheduler()` on a SINGLE stale-watermark read (`age_seconds > 720`). Combined with Fix 1, false positives should be eliminated — but a single transient blip (rare DB write delay) could still trigger an unnecessary restart. Two consecutive reads 60s apart eliminate single-blip noise at the cost of one extra 60s before legitimate restart.

### Implementation

`outputs/dashboard.py:165-171`:

```python
_watchdog_last_check = 0
_watchdog_last_alert_ts = 0
_watchdog_alert_cooldown_s = 300  # min seconds between WARN log entries
_watchdog_consecutive_stale = 0   # NEW — count of consecutive stale reads
```

`outputs/dashboard.py:185-209`:

```python
def _check_scheduler_heartbeat():
    """If heartbeat stale >12 min on TWO consecutive reads (60s apart),
    restart scheduler + log warning (throttled).

    SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1: require TWO consecutive stale
    reads to avoid restart on single-blip watermark writes that ran late.
    """
    global _watchdog_last_alert_ts, _watchdog_consecutive_stale
    try:
        from triggers.state import trigger_state
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age_seconds = (datetime.now(timezone.utc) - hb).total_seconds()
        if age_seconds > 720:
            _watchdog_consecutive_stale += 1
            if _watchdog_consecutive_stale < 2:
                logger.info(
                    f"SCHEDULER-WATCHDOG-1: heartbeat stale ({age_seconds:.0f}s) "
                    f"on read #{_watchdog_consecutive_stale}/2. Waiting one more tick."
                )
                return
            logger.error(f"SCHEDULER-WATCHDOG-1: Heartbeat stale ({age_seconds:.0f}s) for 2 consecutive reads. Restarting...")
            from triggers.embedded_scheduler import restart_scheduler
            restart_scheduler()
            _watchdog_consecutive_stale = 0
            now_ts = time.time()
            if now_ts - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                _watchdog_last_alert_ts = now_ts
                logger.warning(
                    f"WATCHDOG_RESTART: scheduler was dead {int(age_seconds/60)} min. "
                    f"Auto-restart fired. WA push disabled pending CRASHLOOP_RCA_2."
                )
        else:
            # Fresh heartbeat → reset counter
            _watchdog_consecutive_stale = 0
    except Exception as e:
        logger.debug(f"Scheduler watchdog check failed (non-fatal): {e}")
```

### Key Constraints

- Reset the counter on fresh-heartbeat reads, not just on restart.
- DO NOT increase the 720s threshold — that's the stale detection threshold; the 2-read gate is orthogonal.
- DO NOT increase middleware check cadence below 60s — `_watchdog_last_check` throttle stays.

### Verification

Add to `tests/test_watchdog_cooldown.py`:

```python
def test_single_stale_does_not_restart():
    """One stale read → wait, no restart."""
    import outputs.dashboard as dash
    dash._watchdog_consecutive_stale = 0
    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()

    fake_restart.assert_not_called()
    assert dash._watchdog_consecutive_stale == 1


def test_two_consecutive_stale_restart():
    """Two stale reads → restart."""
    import outputs.dashboard as dash
    dash._watchdog_consecutive_stale = 0
    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(900)
    fake_restart = MagicMock()

    with patch("triggers.state.trigger_state", fake_state), \
         patch("triggers.embedded_scheduler.restart_scheduler", fake_restart):
        dash._check_scheduler_heartbeat()
        dash._check_scheduler_heartbeat()

    fake_restart.assert_called_once()
    assert dash._watchdog_consecutive_stale == 0  # reset after restart


def test_fresh_read_resets_counter():
    import outputs.dashboard as dash
    dash._watchdog_consecutive_stale = 1
    fake_state = MagicMock()
    fake_state.get_watermark.return_value = _stale_hb(60)  # fresh

    with patch("triggers.state.trigger_state", fake_state):
        dash._check_scheduler_heartbeat()

    assert dash._watchdog_consecutive_stale == 0
```

---

## Post-deploy verification (24h)

Re-run B4 RCA §4 query 24h after merge:

```sql
SELECT job_id,
       COUNT(*) AS n_fired,
       PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY gap) AS p50_gap,
       PERCENTILE_CONT(0.9)  WITHIN GROUP (ORDER BY gap) AS p90_gap,
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

**Pass criteria:**
1. `scheduler_heartbeat` p90 gap < 500s (vs current 746s).
2. `scheduler_heartbeat` `n_over_720s` = 0.
3. `pg_stat_activity` oldest `backend_start` for the lock-holder exceeds 1h (no 12-min rotation).
4. 0 `WATCHDOG_RESTART` log lines in Render logs over 24h (Phase A's log target).

## Files Modified

- `triggers/embedded_scheduler.py:1372-1403` — `_scheduler_heartbeat` reorder + remove in-job restart
- `outputs/dashboard.py:165-209` — 2-consecutive-stale gate (Fix 2, optional but recommended)
- `tests/test_scheduler_heartbeat_order.py` (NEW) — Fix 1 tests
- `tests/test_watchdog_cooldown.py` — append 3 tests for Fix 2

## Do NOT Touch

- `triggers/scheduler_lease.py` — singleton-harden logic is correct
- `outputs/dashboard.py:202-204` (Phase A log line) — already correct
- The 720s stale threshold or 300s heartbeat interval

## Ship gate

Literal `pytest tests/test_scheduler_heartbeat_order.py tests/test_watchdog_cooldown.py -v` green in ship report.

## Trigger class

LOW (single-file behaviour-narrow, no auth, no DB, no external surface). 2nd-pass code-reviewer NOT mandatory per trigger criteria; AH2 static + `/security-review` sufficient.

## Builder

**B4** (RCA author, has full scheduler context). Continuation of Phase B of the scheduler-wa-kill-and-rca dispatch.

Worktree: `~/bm-b4`.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
