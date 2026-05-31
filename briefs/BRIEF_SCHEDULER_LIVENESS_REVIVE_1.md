# BRIEF: SCHEDULER_LIVENESS_REVIVE_1 (RECUT v2) — harden `_job_listener` persistence so execution rows survive conn-pool exhaustion

> **RECUT NOTE (2026-05-31, after codex FAIL-LIGHT #1444).** v1 of this brief misdiagnosed the cause as a hung/unregistered watchdog. Codex disproved that with Render logs: `scheduler_job_liveness` **registers and executes successfully every 10 min** (11:18:02 "Running" → 11:18:04 "executed successfully"), then `_job_listener` logs `JOB_LISTENER_SILENT_SKIP job_id=scheduler_job_liveness reason=conn_pool_none` and drops the row. The watchdog is ALIVE; its `scheduler_executions` self-row is lost under pool pressure. v2 below targets the real cause. The old max_instances=2 idea is DROPPED (codex Finding 2: non-atomic hourly dedupe → duplicate-alert race).

## Context
`_job_listener` (`triggers/embedded_scheduler.py:51-105`) persists one `scheduler_executions` row per job completion. It draws from the shared `ThreadedConnectionPool` (`memory/store_back.py:306-310`, **maxconn=5**) used by FastAPI + ~40 scheduler jobs + Cortex threads. PR #274 (`JOB_LISTENER_HARDEN_1`) made the skip non-silent (logs `JOB_LISTENER_SILENT_SKIP` + a 100ms single retry) — but a 100ms retry against an exhausted 5-connection pool still fails under sustained pressure, so rows are still dropped. `scheduler_job_liveness` is the visible victim (0 rows since 06:31Z while it executes fine), but the drop is generic — any job's observability row can be lost under spike, which silently corrupts the very table the liveness watchdog reads.

### Surface contract: N/A — pure backend scheduler/DB persistence; no user-clickable surface.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: main at `4ff5b7d` (#274 listener fix + this brief). Codex evidence in bus #1444.

---

## Fix 1 (root cause): dedicated connection path for execution-row writes

### Problem
`_job_listener`'s INSERT competes with the whole app for 5 pooled connections. When the pool is exhausted at the moment a job completes, the row is dropped. Observability writes must not depend on the shared pool having a free slot.

### Current State
`triggers/embedded_scheduler.py:69-99` (post-#274):
```python
conn = store._get_conn()
if not conn:
    import time
    time.sleep(0.1)
    conn = store._get_conn()      # one 100ms retry against the SAME maxconn=5 pool
    if not conn:
        _record_listener_drop(event.job_id)
        return                    # row dropped
# ... INSERT INTO scheduler_executions ...
```
`memory/store_back.py:319-326`: `_get_conn()` returns `self._pool.getconn()` or None on `PoolError` (exhaustion raises, does not wait).

### Implementation
1. Add a dedicated fallback that bypasses the shared pool for this one tiny INSERT. When `_get_conn()` returns None after a short bounded retry, open a **direct short-lived connection** and write the row, then close it:
   ```python
   # after pooled attempts fail:
   import psycopg2
   from config import config  # verify the actual import path used elsewhere in this file first
   direct = None
   try:
       direct = psycopg2.connect(connect_timeout=5, **config.postgres.dsn_params)
       cur = direct.cursor()
       cur.execute(
           """INSERT INTO scheduler_executions (job_id, fired_at, completed_at, status, error_msg)
              VALUES (%s, %s, NOW(), %s, %s)""",
           (event.job_id, event.scheduled_run_time, status, error_msg),
       )
       direct.commit(); cur.close()
   except Exception as e:
       _record_listener_drop(event.job_id)   # only NOW is it a true drop
       logger.warning(f"JOB_LISTENER direct-conn fallback failed job_id={event.job_id}: {e}")
   finally:
       if direct is not None:
           try: direct.close()
           except Exception: pass
   ```
   - Verify `config.postgres.dsn_params` is the exact attribute used by `_init_pool` (`memory/store_back.py:307-310`) — reuse the same params; do NOT hand-build a DSN.
   - `connect_timeout=5` so the fallback itself cannot hang.
2. Strengthen the pooled attempt before falling back: replace the single 100ms retry with a short bounded backoff (e.g. 3 attempts at 100/200/400ms). Keep total well under `misfire_grace_time` (300s) so the listener never back-pressures the scheduler.
3. Keep `_record_listener_drop` ONLY for the case where BOTH pooled retries AND the direct fallback fail — a true, now-rare drop.

### Key Constraints
- Scheduler must NEVER crash on an observability write — keep the whole block in try/except; a failed row is logged, not raised.
- Direct connection is short-lived: open → INSERT → commit → close in a `finally`. Never leak it into the pool, never reuse it.
- Do not raise the shared-pool `maxconn` as the primary fix (see Fix 2 — secondary only).
- Touch ONLY `_job_listener`'s persistence block. Do NOT change the watchdog's logic, intervals, or any `add_job(...)`.

### Verification
- Local: monkeypatch `store._get_conn` to always return None; assert the row still lands via the direct path (against a test DB or a mocked `psycopg2.connect`).
- Local: monkeypatch both pooled and direct to fail; assert `_record_listener_drop` increments and the scheduler thread does not raise.
- `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`.
- `pytest` — the #274 listener tests + #273 liveness suite (42) must pass on a literal run.

---

## Fix 2 (secondary, defensive): widen the shared pool + bound the watchdog's own SELECTs

### Problem
maxconn=5 is tight for FastAPI + ~40 jobs + Cortex. Even with Fix 1, easing pool pressure reduces how often the fallback is needed.

### Implementation
1. Bump `maxconn` `5 → 8` in `memory/store_back.py:307-310`. **Cost flag:** Neon connection budget — confirm the plan's connection ceiling before raising; note it in the ship report. If uncertain, leave at 5 and rely on Fix 1.
2. Add `cur.execute("SET LOCAL statement_timeout = '20s'")` at the top of `check_scheduler_liveness`'s cursor block (`triggers/scheduler_liveness_sentinel.py`) so a slow server-side SELECT cannot hold a pooled connection open and worsen exhaustion. (Codex #1444: useful hardening, not the root cause — keep it scoped as such.)

### Key Constraints
- maxconn change is a one-line constant; do not refactor the pool.
- `SET LOCAL` only inside the watchdog's existing transaction; the existing `conn.rollback()` (`scheduler_liveness_sentinel.py:166-172`) already handles `QueryCanceled`.

### Verification
- Confirm pool still initializes (`PostgreSQL connection pool initialized` in boot log).
- Liveness suite still green.

---

## Optional (defense-in-depth, low priority): startup self-presence log
Codex confirmed the watchdog IS registered, so the v1 hard-`raise` assertion is unnecessary. Keep only a non-fatal startup log after the register loop: `logger.info("Self-bootstrap OK: scheduler_job_liveness present")` if `"scheduler_job_liveness" in {j.id for j in scheduler.get_jobs()}` else `logger.error(...)`. No `raise` (avoid making a future unrelated registration issue crash boot). Skip entirely if it complicates the diff.

## Files Modified
- `triggers/embedded_scheduler.py` — `_job_listener`: bounded pooled backoff + direct-connection fallback for the execution-row INSERT (Fix 1); optional startup self-presence log.
- `memory/store_back.py` — `maxconn` 5→8 (Fix 2, conditional on Neon budget).
- `triggers/scheduler_liveness_sentinel.py` — `SET LOCAL statement_timeout` in the watchdog cursor block (Fix 2).

## Do NOT Touch
- Any `add_job(...)` block — no interval/trigger/`max_instances` changes. (max_instances=2 idea DROPPED per codex Finding 2.)
- `_record_listener_drop` / `get_listener_drop_counts` semantics — reuse as-is.
- Watchdog staleness logic, tolerance/grace constants, `_TIER_OVERRIDES`.

## Quality Checkpoints
1. After deploy, within ~25 min confirm a `scheduler_job_liveness` row with `fired_at` after deploy lands (proves the fallback path works under real pressure).
2. Confirm `JOB_LISTENER_SILENT_SKIP ... scheduler_job_liveness` stops appearing in logs (or the direct-fallback succeeds where the pool failed).
3. Confirm no NEW false `SCHEDULER JOB STALE` alerts for jobs that ARE firing (#273 AC2).
4. Confirm direct connections are closed (no Neon connection leak — watch active connection count).

## Verification SQL
```sql
-- AC1: liveness self-row resumes (run >25 min after deploy)
SELECT job_id, fired_at, status FROM scheduler_executions
WHERE job_id = 'scheduler_job_liveness' ORDER BY fired_at DESC LIMIT 5;

-- AC2: no false STALE alerts for live jobs, post-deploy
SELECT id, source, created_at, LEFT(title,80) AS title FROM alerts
WHERE source = 'scheduler_job_liveness' AND created_at > '2026-05-31T13:00:00+00:00'
ORDER BY created_at DESC LIMIT 20;
```

## Gate plan
Codex re-review of this RECUT v2 (it found the root cause; confirm the fix matches the evidence + no Neon-budget foot-gun on maxconn) → fold → b-code build → G1 AH1 fold + G2 /security-review + G3 deputy → merge → re-run AC1/AC2.
