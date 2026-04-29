# BRIEF: SCHEDULER_SINGLETON_HARDEN_1 — Singleton-safe scheduler across Render Pro zero-downtime deploys

## Context

B1's `SCHEDULER_DUPLICATE_INSTANCE_RCA_1` (commit `d2ce629`) confirmed: every BackgroundScheduler job fires 2× at a stable ~1.67s offset. Root cause = Render Pro's zero-downtime deploys creating a 2-3 min overlap window where OLD container (draining) and NEW container (booting) both run a full `BackgroundScheduler` against the same Neon DB.

Today's exposure surface (jobs without per-tick advisory locks, doubled silently for 6+ days):
- `email_poll` — doubled Gmail API calls
- `clickup_poll` — doubled ClickUp API calls
- `gold_audit_sentinel` — Mon 09:30 UTC, AI Head B watch → racing audit-row inserts
- `ai_head_weekly_audit` — Mon 09:00 UTC, doubled writes
- `daily_briefing` — doubled briefing posts
- `cortex_stuck_cycle_sentinel` — doubled DB load
- `cortex_pipeline.maybe_dispatch` — bridge advisory lock + cost-gate atomic-claim already cover; SAFE
- `kbl_bridge_tick` — bridge advisory lock at `kbl/bridge/alerts_to_signal.py:622` already covers; SAFE

`kbl_bridge_tick` flooding was visually obvious (60s interval × 2 = 2/min) which is why B1 noticed; pipeline (120s × 2) and heartbeat (300s × 2) hide the doubling at "expected" rates. RCA shows this has been live since 2026-04-23 06:42Z (the day `scheduler_executions` audit table was created). Pre-existing condition; instrumentation is what made it visible.

Director's API reconciliation 2026-04-29 ~16:30Z: `numInstances=1` configured, `autoscaling=null`, `preDeployCommand=null`, current `/instances` returns 1 active. Pro-plan zero-downtime is the only doubling path. Don't fight zero-downtime (lose Pro's main benefit) — harden the scheduler to be singleton-safe across the overlap.

## Estimated time: 3-4h
## Complexity: Medium
## Prerequisites: Confirm Neon direct (non-pooled) compute is enabled on Brisen's Neon project. (Required because pgbouncer transaction-mode resets session GUCs and would lose the advisory lock on every commit — see today's MCP pool-poisoning RCA at `memory/feedback_mcp_pgbouncer_pool_poisoning.md`.)

---

## Fix 1: Singleton lock via Neon direct connection

### Problem

`start_scheduler()` in `triggers/embedded_scheduler.py:1251` checks in-process state (`_scheduler is not None and _scheduler.running`) for idempotency. Two PROCESSES (OLD draining + NEW booting during deploy) each pass that check → each runs `_register_jobs()` + `_scheduler.start()` against the same Neon DB. Result: two schedulers, every job fires 2× during the overlap window.

### Current State

`triggers/embedded_scheduler.py:1251-1269`:
```python
def start_scheduler():
    """Create and start the BackgroundScheduler. Idempotent — safe to call twice."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running — skipping start")
        return
    _scheduler = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    )
    _scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    _register_jobs(_scheduler)
    _scheduler.start()
```

The in-process check is fine for in-process duplicates (e.g., watchdog calling `start_scheduler` twice). It does nothing across processes.

### Implementation

**Step 1A — Add Neon direct DSN to config**

`config/settings.py:144-169`. Append a `direct_dsn_params` property:

```python
@dataclass
class PostgresConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    host_direct: str = os.getenv("POSTGRES_HOST_DIRECT", "")  # NEW — non-pooled Neon endpoint
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    database: str = os.getenv("POSTGRES_DB", "sentinel")
    user: str = os.getenv("POSTGRES_USER", "sentinel")
    password: str = os.getenv("POSTGRES_PASSWORD", "")
    sslmode: str = os.getenv("POSTGRES_SSLMODE", "prefer")
    # ... existing connection_string + dsn_params unchanged ...

    @property
    def direct_dsn_params(self) -> dict:
        """Return connection params for the NON-POOLED Neon endpoint.

        Required for session-level advisory locks: pgbouncer transaction-mode
        resets session state on every commit, releasing the lock. Direct
        compute keeps the connection 1:1 with a backend for the process
        lifetime.

        Falls back to the pooled host if POSTGRES_HOST_DIRECT is unset —
        callers MUST handle the lock failing and retry on the next deploy.
        """
        host = self.host_direct or self.host
        params = {
            "host": host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }
        if self.sslmode and self.sslmode != "disable":
            params["sslmode"] = self.sslmode
        return params
```

**Step 1B — New module `triggers/scheduler_lease.py`**

```python
"""SCHEDULER_SINGLETON_HARDEN_1 — process-singleton lock for the BackgroundScheduler.

Held on a DEDICATED non-pooled Neon connection. The lock auto-releases when
the process dies (SIGTERM closes the connection at the OS level), giving a
clean handoff during Render Pro zero-downtime deploys.

Usage:
    from triggers.scheduler_lease import acquire_singleton_lock, release_singleton_lock

    held_conn = acquire_singleton_lock()
    if held_conn is None:
        # Another process holds the lock. Caller MUST NOT call _register_jobs.
        return
    # Caller proceeds to start scheduler.
    # held_conn must be kept alive for the process lifetime.

Lock key: hash(SCHEDULER_LOCK_NAME) % 2**31, fixed integer for advisory_lock signature.
"""
from __future__ import annotations
import logging
import threading
from typing import Optional

import psycopg2

from config.settings import config

logger = logging.getLogger(__name__)

SCHEDULER_LOCK_KEY = 8800100  # arbitrary, distinct from existing 90xx00 + 8005 + 867531
_held_conn: Optional[psycopg2.extensions.connection] = None
_lock = threading.Lock()


def acquire_singleton_lock() -> Optional[psycopg2.extensions.connection]:
    """Try to acquire the scheduler singleton lock.

    Returns the held connection on success, None on:
    - Another process holds the lock
    - DB unreachable
    - direct DSN not configured (POSTGRES_HOST_DIRECT unset → pooler fallback
      is unsafe for session locks; we refuse rather than silently proceed)

    Caller MUST keep the returned connection alive for the process lifetime.
    Do NOT pass it back to a connection pool.
    """
    global _held_conn
    with _lock:
        if _held_conn is not None:
            return _held_conn

        if not config.postgres.host_direct:
            logger.error(
                "POSTGRES_HOST_DIRECT unset — scheduler singleton lock disabled "
                "(pooler endpoint cannot hold session-level advisory locks). "
                "Set POSTGRES_HOST_DIRECT on Render to enable. Continuing without lock; "
                "duplicate scheduler firing remains possible during deploy overlap."
            )
            return None

        try:
            conn = psycopg2.connect(**config.postgres.direct_dsn_params)
            conn.autocommit = True  # advisory locks need a real session, not pgbouncer
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,))
            row = cur.fetchone()
            cur.close()
            if not row or not row[0]:
                conn.close()
                logger.info(
                    "scheduler singleton lock NOT acquired (key=%s) — another process holds it",
                    SCHEDULER_LOCK_KEY,
                )
                return None
            _held_conn = conn
            logger.info(
                "scheduler singleton lock ACQUIRED (key=%s) on direct host %s",
                SCHEDULER_LOCK_KEY,
                config.postgres.host_direct,
            )
            return conn
        except Exception as e:
            logger.error("scheduler singleton lock acquire failed: %s", e)
            return None


def release_singleton_lock() -> None:
    """Explicit release for graceful shutdown. SIGTERM-driven connection close
    also releases naturally; this is belt-and-suspenders for FastAPI lifespan."""
    global _held_conn
    with _lock:
        if _held_conn is None:
            return
        try:
            cur = _held_conn.cursor()
            cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEDULER_LOCK_KEY,))
            cur.close()
        except Exception:
            pass
        try:
            _held_conn.close()
        except Exception:
            pass
        _held_conn = None
        logger.info("scheduler singleton lock RELEASED (key=%s)", SCHEDULER_LOCK_KEY)


def is_held() -> bool:
    """Probe for tests + observability."""
    with _lock:
        return _held_conn is not None
```

**Step 1C — Wire into `start_scheduler()`**

`triggers/embedded_scheduler.py:1251-1269`. Modify:

```python
def start_scheduler():
    """Create and start the BackgroundScheduler. Singleton across processes
    via PG advisory lock on a dedicated non-pooled connection.

    During Render Pro zero-downtime deploy overlap, only one container holds
    the lock at any time. The other waits on the polling thread until the
    holder dies (SIGTERM closes its connection → lock auto-releases).
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running — skipping start")
        return

    # SCHEDULER_SINGLETON_HARDEN_1: try to acquire the singleton lock.
    from triggers.scheduler_lease import acquire_singleton_lock
    held_conn = acquire_singleton_lock()
    if held_conn is None:
        logger.warning(
            "scheduler singleton lock unavailable — registering NO jobs. "
            "Lock-poll thread will retry every 30s and start jobs on acquisition."
        )
        _spawn_lock_retry_thread()
        return

    _scheduler = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    )
    _scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    _register_jobs(_scheduler)
    _scheduler.start()
    logger.info(f"BackgroundScheduler started with {len(_scheduler.get_jobs())} jobs")


def _spawn_lock_retry_thread() -> None:
    """Background poll thread — retries singleton-lock acquisition every 30s.
    On success, calls start_scheduler() to register jobs + start.

    Idempotent: skips spawn if a retry thread is already running.
    """
    import threading
    global _lock_retry_thread
    if _lock_retry_thread is not None and _lock_retry_thread.is_alive():
        return

    def _poll():
        import time
        while True:
            time.sleep(30)
            if _scheduler is not None and _scheduler.running:
                logger.info("scheduler started by another path — retry thread exiting")
                return
            from triggers.scheduler_lease import acquire_singleton_lock
            held = acquire_singleton_lock()
            if held is not None:
                logger.info("scheduler singleton lock acquired on retry — starting jobs")
                start_scheduler()  # recursive but safe — held lock means we register
                return

    _lock_retry_thread = threading.Thread(target=_poll, name="scheduler-lock-retry", daemon=True)
    _lock_retry_thread.start()
```

Add module-level globals at the top of `embedded_scheduler.py` (near `_scheduler = None`):

```python
_lock_retry_thread = None
```

**Step 1D — Release lock on `stop_scheduler()` and `restart_scheduler()`**

`triggers/embedded_scheduler.py:1272-1278`:

```python
def stop_scheduler():
    """Graceful shutdown. Idempotent. Releases singleton lock on success."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("BackgroundScheduler stopped")
    _scheduler = None
    # Release the singleton lock so the next process can acquire on its own startup.
    try:
        from triggers.scheduler_lease import release_singleton_lock
        release_singleton_lock()
    except Exception as e:
        logger.warning(f"Singleton lock release failed (non-fatal): {e}")
```

`triggers/embedded_scheduler.py:1237-1248`:

```python
def restart_scheduler():
    """SCHEDULER-WATCHDOG-1: Force restart the scheduler. Called by request-time watchdog.

    Uses wait=True with a bounded 5s timeout — wait=False (prior behavior) leaked
    job-execution threads which then re-acquired DB connections on completion,
    creating phantom load with no scheduler reference (B1 RCA observation 2026-04-29).
    """
    global _scheduler
    logger.warning("SCHEDULER-WATCHDOG-1: Force-restarting scheduler...")
    try:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=True)  # bounded — APScheduler's shutdown blocks
            except Exception:
                pass
    except Exception:
        pass
    _scheduler = None
    # Drop the lock so re-acquire goes through the normal path
    try:
        from triggers.scheduler_lease import release_singleton_lock
        release_singleton_lock()
    except Exception:
        pass
    start_scheduler()
    logger.warning("SCHEDULER-WATCHDOG-1: Scheduler force-restarted successfully")
```

### Key Constraints

- **MUST** use `config.postgres.direct_dsn_params` — never the pooled `dsn_params` for the lock connection. Pooled connection on pgbouncer transaction-mode releases the lock on first commit.
- **MUST** keep `held_conn` alive for the process lifetime. Do NOT pass to `_put_conn()` / connection pool.
- **MUST NOT** call `pg_try_advisory_xact_lock` (transaction-scoped) — wrong primitive.
- **MUST** keep `conn.autocommit = True` on the lock connection — avoids accidental session-state drift.
- **MUST NOT** put advisory-lock acquisition in any hot path (per-tick, per-request) — only at process startup and on watchdog restart.
- The lock-poll thread MUST be daemon (so process can exit cleanly on SIGTERM regardless of poll state).

### Verification

```sql
-- After deploy, confirm singleton (run during a 5-deploy stress window):
SELECT job_id, COUNT(*) AS fires,
       COUNT(DISTINCT (EXTRACT(EPOCH FROM fired_at)::numeric % 60)::text) AS distinct_anchors
FROM scheduler_executions
WHERE fired_at > NOW() - INTERVAL '15 minutes'
GROUP BY job_id
ORDER BY fires DESC
LIMIT 20;
-- Pass: every job has distinct_anchors = 1.
-- Fail: any job has distinct_anchors >= 2.
```

```sql
-- Confirm advisory lock visible from the holding process (run from baker_raw_query):
SELECT classid, objid, granted, mode, pid
FROM pg_locks
WHERE locktype = 'advisory'
  AND objid = 8800100
LIMIT 5;
-- Pass: exactly one row, granted=true.
```

---

## Fix 2: `_watchdog_cooldown` rate-limit bug

### Problem

`outputs/dashboard.py:161` defines `_watchdog_cooldown = 300` with comment "Don't re-alert within 5 min of a restart". The check at line 189 reads:

```python
if age_seconds > _watchdog_cooldown:
    send_whatsapp(...)
```

But `age_seconds > 720` already gated us at line 184 (12 min stale heartbeat threshold). So `age_seconds > 300` at line 189 is ALWAYS True when reached. The variable is dead — it never throttles WhatsApp alerts. Repeated stale-heartbeat detections (every 60s per the middleware) would each fire a WhatsApp alert without rate-limit.

### Current State

`outputs/dashboard.py:160-199`:
```python
_watchdog_last_check = 0
_watchdog_cooldown = 300  # Don't re-alert within 5 min of a restart

@app.middleware("http")
async def scheduler_watchdog_middleware(request, call_next):
    # ... checks every 60s ...
    _check_scheduler_heartbeat()
    return await call_next(request)


def _check_scheduler_heartbeat():
    global _watchdog_cooldown
    # ... heartbeat fetch ...
    if age_seconds > 720:  # 12 minutes
        # ... restart_scheduler() ...
        if age_seconds > _watchdog_cooldown:  # ALWAYS TRUE — bug
            send_whatsapp(...)
```

### Implementation

`outputs/dashboard.py:160-161`:

```python
_watchdog_last_check = 0
_watchdog_last_alert_ts = 0  # NEW — tracks last WA alert send time
_watchdog_alert_cooldown_s = 300  # min seconds between WA alerts (rename for clarity)
```

`outputs/dashboard.py:177-199`:

```python
def _check_scheduler_heartbeat():
    """If heartbeat stale >12 min, restart scheduler + WhatsApp alert (throttled)."""
    global _watchdog_last_alert_ts
    try:
        from triggers.state import trigger_state
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age_seconds = (datetime.now(timezone.utc) - hb).total_seconds()
        if age_seconds > 720:  # 12 minutes = missed 2 heartbeat cycles
            logger.error(f"SCHEDULER-WATCHDOG-1: Heartbeat stale ({age_seconds:.0f}s). Restarting...")
            from triggers.embedded_scheduler import restart_scheduler
            restart_scheduler()
            # Throttle: only alert if last alert was >5 min ago
            now = time.time()
            if now - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                _watchdog_last_alert_ts = now
                try:
                    from outputs.whatsapp_sender import send_whatsapp
                    send_whatsapp(
                        f"Baker scheduler was dead for {int(age_seconds/60)} minutes. "
                        f"Auto-restarted. Check dashboard for missed items."
                    )
                except Exception as wa_e:
                    logger.warning(f"Watchdog WhatsApp alert failed: {wa_e}")
    except Exception as e:
        logger.debug(f"Scheduler watchdog check failed (non-fatal): {e}")
```

### Key Constraints

- Don't touch the `> 720` threshold — that's the stale-heartbeat detection threshold (correctly named).
- Rename only the alert-cooldown variable; keep behavior change minimal.
- `_watchdog_last_alert_ts` must be module-level (not function-local) so it persists across requests.

### Verification

Unit test (mocked time):

```python
# tests/test_watchdog_cooldown.py
import time
from unittest.mock import patch, MagicMock

def test_watchdog_alert_throttled():
    """Two stale-heartbeat checks within 5min → only one WA alert."""
    with patch("outputs.dashboard.send_whatsapp") as mock_wa, \
         patch("triggers.state.trigger_state.get_watermark") as mock_hb, \
         patch("triggers.embedded_scheduler.restart_scheduler"):
        from datetime import datetime, timezone, timedelta
        mock_hb.return_value = datetime.now(timezone.utc) - timedelta(seconds=900)  # 15min stale

        from outputs.dashboard import _check_scheduler_heartbeat
        _check_scheduler_heartbeat()
        assert mock_wa.call_count == 1
        _check_scheduler_heartbeat()  # immediate retry
        assert mock_wa.call_count == 1, "second alert within cooldown should be suppressed"
```

---

## Fix 3: Test — singleton enforcement (live-PG)

### Problem

No test today asserts that `start_scheduler()` is singleton-safe across processes. Future regressions (e.g., the lock-key changing accidentally, the direct DSN being misread) won't be caught until production runs.

### Current State

No `tests/test_scheduler_singleton*.py`. No `tests/test_embedded_scheduler*.py`.

### Implementation

`tests/test_scheduler_singleton.py` (NEW):

```python
"""SCHEDULER_SINGLETON_HARDEN_1 — singleton-lock enforcement tests.

Live-PG marker: skipped automatically when TEST_DATABASE_URL not set
(unit-test mode). CI auto-provisions ephemeral Neon branch via
NEON_API_KEY + NEON_PROJECT_ID per repo convention.
"""
import os
import pytest
import psycopg2

from triggers.scheduler_lease import (
    SCHEDULER_LOCK_KEY,
    acquire_singleton_lock,
    release_singleton_lock,
    is_held,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="live-PG: requires TEST_DATABASE_URL",
)


def test_first_acquire_succeeds():
    release_singleton_lock()  # clean state
    held = acquire_singleton_lock()
    assert held is not None, "first acquire on clean key should succeed"
    assert is_held() is True
    release_singleton_lock()


def test_second_acquire_from_separate_connection_blocks():
    """Simulate two-process race: first conn holds lock, second conn must NOT acquire."""
    release_singleton_lock()
    held = acquire_singleton_lock()
    assert held is not None

    # Open a SEPARATE connection (simulates the OTHER process).
    from config.settings import config
    other = psycopg2.connect(**config.postgres.direct_dsn_params)
    other.autocommit = True
    cur = other.cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s)", (SCHEDULER_LOCK_KEY,))
    got = cur.fetchone()[0]
    cur.close()
    other.close()

    assert got is False, "second connection acquired despite first holding"
    release_singleton_lock()


def test_release_then_reacquire():
    release_singleton_lock()
    h1 = acquire_singleton_lock()
    assert h1 is not None
    release_singleton_lock()
    h2 = acquire_singleton_lock()
    assert h2 is not None, "re-acquire after release should succeed"
    release_singleton_lock()
```

### Key Constraints

- Each test must call `release_singleton_lock()` first to clean state from prior test runs.
- Tests must use the DIRECT (non-pooled) DSN — `config.postgres.direct_dsn_params`.
- Mark module-level with `pytest.mark.skipif` so unit-test runs (no TEST_DATABASE_URL) auto-skip.

### Verification

```bash
pytest tests/test_scheduler_singleton.py -v
pytest tests/test_watchdog_cooldown.py -v
# Both must pass with literal stdout in §0 of B1 ship report.
```

---

---

## Fix 4: Held-connection liveness probe (edge case — Neon auto-suspend)

### Problem

`acquire_singleton_lock()` returns a held connection. If Neon's compute auto-suspends or the network drops the connection mid-life, server-side releases the advisory lock but `_held_conn` remains pointing to a dead socket. The in-process `start_scheduler()` idempotency check (`_scheduler.running`) returns True, so no re-acquire is attempted. Result: orphaned scheduler, lock now free but unclaimed → on next deploy, NEW container could acquire and run alongside the orphan (worst case, but unlikely on Render Pro).

### Implementation

Piggyback on the existing 5-min `scheduler_heartbeat` job. Add a probe at the top:

`triggers/embedded_scheduler.py:1156-1162`:

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
        from triggers.scheduler_lease import _held_conn  # module-level singleton
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
        pass  # never fail heartbeat from probe path
    try:
        from triggers.state import trigger_state
        trigger_state.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Scheduler heartbeat write failed: {e}")
```

### Key Constraints

- The probe MUST NOT raise out of `_scheduler_heartbeat` — heartbeat write is critical for the watchdog and must always run.
- The probe must NOT acquire any new connections — it only `SELECT 1`s on the held one.
- Module-level import of `_held_conn` is intentional; the singleton is by design.

### Verification

Manual test (live-PG): kill the held connection from psql:
```sql
-- From a separate session, find the held connection's pid via pg_locks (Verification SQL #2 above), then:
SELECT pg_terminate_backend(<pid>);
```

Within 5 min, `_scheduler_heartbeat` next tick should detect the dead connection, log the error, call `restart_scheduler()`, and the next deploy or watchdog probe re-acquires the lock cleanly.

---

## Files Modified

- `triggers/embedded_scheduler.py` — start_scheduler integrates singleton-lock acquire + retry-thread spawn; stop_scheduler + restart_scheduler release lock; restart_scheduler wait=True; _scheduler_heartbeat probes held connection for liveness
- `triggers/scheduler_lease.py` — NEW module: dedicated direct-DSN connection holding the singleton advisory lock
- `outputs/dashboard.py` — fix `_watchdog_cooldown` variable misuse (rate-limit, not threshold)
- `config/settings.py` — add `host_direct` field + `direct_dsn_params` property to `PostgresConfig`
- `tests/test_scheduler_singleton.py` — NEW: 3 tests for singleton-lock enforcement (live-PG marker)
- `tests/test_watchdog_cooldown.py` — NEW: unit test for WA-alert throttle

## Do NOT Touch

- `kbl/bridge/alerts_to_signal.py` — bridge `pg_try_advisory_xact_lock(900600)` pattern is correct as-is (per-tick scope)
- `triggers/cortex_pipeline.py` — Cortex dedup already covered by bridge lock + cost-gate atomic-claim (`record_decision` `INSERT ... WHERE NOT EXISTS RETURNING`)
- `migrations/*.sql` — no schema change required
- `start.sh` — single uvicorn worker is correct (per RCA brief H2)
- `triggers/embedded_scheduler.py` `_register_jobs()` — job set unchanged
- `outputs/dashboard.py` `> 720` heartbeat threshold — correctly named, leave alone

## Render env var (Director action)

Set on Render **via MCP merge mode**, NEVER raw PUT (today's 80-var wipe lesson at `memory/feedback_render_envvar_paginated_put.md`):

- `POSTGRES_HOST_DIRECT` = the Neon direct (non-pooled) endpoint hostname for the same compute that backs `POSTGRES_HOST`. Format: drop `-pooler` from the current `POSTGRES_HOST` value (`ep-summer-sun-aih7ha4h-pooler.c-4.us-east-1.aws.neon.tech` → `ep-summer-sun-aih7ha4h.c-4.us-east-1.aws.neon.tech`). Verify Neon project has direct compute exposed before setting.

If `POSTGRES_HOST_DIRECT` is unset post-deploy, the lock acquisition path logs an error and proceeds without the lock — duplicate scheduler firing remains possible, no regression vs today's state.

## Quality Checkpoints

1. `pytest tests/test_scheduler_singleton.py tests/test_watchdog_cooldown.py -v` passes (literal stdout in B1 ship report §0).
2. After deploy + 15 min: verification SQL returns `distinct_anchors = 1` for every job.
3. After deploy + 1 hour: a synthetic deploy stress test (push trivial commit twice in 5 min) — anchors stay = 1 across both deploy windows.
4. Logs at startup of NEW container during deploy overlap: `"scheduler singleton lock NOT acquired"` followed within 30s of OLD shutdown by `"scheduler singleton lock acquired on retry — starting jobs"`.
5. `pg_locks` query returns exactly 1 row for `objid=8800100` while the holder is alive, 0 rows after `stop_scheduler()` is called.
6. `outputs/whatsapp_sender.send_whatsapp` not called more than once per 5-min window during sustained stale-heartbeat conditions (verifiable via WA send-log inspection).
7. No regression in `kbl_bridge_tick` consumer cadence — `signal_queue` keeps draining at expected rate.
8. `cortex_pipeline.maybe_dispatch` continues firing once per signal post-fix (cost-gate atomic-claim was already protecting this — verify NOT regressed).

## Verification SQL

```sql
-- 1. Singleton enforcement — every job has 1 anchor over 15 min:
SELECT job_id, COUNT(*) AS fires,
       COUNT(DISTINCT (EXTRACT(EPOCH FROM fired_at)::numeric % 60)::text) AS distinct_anchors
FROM scheduler_executions
WHERE fired_at > NOW() - INTERVAL '15 minutes'
GROUP BY job_id
ORDER BY fires DESC
LIMIT 20;

-- 2. Lock visibility from a probing connection (run via baker_raw_query):
SELECT locktype, classid, objid, granted, pid
FROM pg_locks
WHERE locktype = 'advisory' AND objid = 8800100;

-- 3. Cortex dispatch-doubling regression check:
SELECT cycle_id, status, started_at,
       COUNT(*) OVER (PARTITION BY trigger_signal_id) AS dispatches_per_signal
FROM cortex_cycles
WHERE started_at > NOW() - INTERVAL '24 hours'
ORDER BY started_at DESC
LIMIT 20;
-- Pass: dispatches_per_signal = 1 for every row.

-- 4. Daily briefing / weekly audit doubled-write check (post-Mon):
SELECT action_type, target_task_id, COUNT(*)
FROM baker_actions
WHERE created_at > NOW() - INTERVAL '24 hours'
  AND action_type IN ('ai_head_weekly_audit', 'gold_audit_sentinel', 'daily_briefing')
GROUP BY 1, 2
HAVING COUNT(*) > 1
LIMIT 20;
-- Pass: 0 rows.
```

---

## Builder

**B1** (RCA author, has scheduler-territory context).

Worktree: `~/bm-b1` (flat layout post Tier 2 migration commit `084e9f1` — NO `/01_build` suffix per `memory/feedback_worktree_paths_post_tier_migration.md`).

## Trigger class

**Scheduler lifecycle = MEDIUM trigger class** (per AI Head autonomy charter § B-code dispatch). Touches FastAPI lifespan via `start_scheduler` / `stop_scheduler`. Triggers B1 situational-review by AI Head A or B before merge per ratified 2026-04-24 rule.

Pre-build authorization: Director ratified scope 2026-04-29 ~17:00Z ("Brief is unblocked. Hand that to AI Head 1 App.").

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
