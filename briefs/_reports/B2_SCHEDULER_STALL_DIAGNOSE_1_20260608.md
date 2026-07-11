# B2 DIAGNOSIS — SCHEDULER_STALL_DIAGNOSE_1 (read-only, no action taken)

- **Dispatch:** lead #2508 + CODE_2_PENDING.md (origin/main), 2026-06-08
- **Mode:** READ-ONLY diagnosis. No fix, no restart, no mutation. baker_raw_query is SELECT-only.
- **Verdict:** PROD scheduler is permanently stalled (job_count=0, running=false) and the
  watchdog **cannot self-heal** because the singleton advisory lock is held by an
  alive-but-orphaned connection. This is the #296 failure class, incompletely closed.

## Live evidence (literal probe/query output, ~12:13Z)

1. `GET /api/health/scheduler` → `{"alive":false,"scheduler_running":false,"job_count":0,"heartbeat_age_seconds":2307+ and aging}`.
2. `trigger_watermarks` `scheduler_heartbeat`: `last_seen=2026-06-08 11:28:37.586Z`, frozen 45+ min, re-read twice — not advancing.
3. `pg_locks` advisory `objid=8800100`: `granted=true`, `pid=343`.
4. `pg_stat_activity` pid 343: `client_addr=10.30.77.83` (app container), `backend_start=2026-06-08 05:58:31Z` (= process start), `state=idle`, last query `SELECT 1` (the lease-health probe), idle 37+ min, `wait_event=ClientRead`. **ALIVE, not dead.**
5. **Single app instance** — only one container IP (10.30.77.83; backends pid 343 = lease conn, pid 2885 = web pool, COMMIT 26s ago = web process alive & serving). All other backends are Neon-internal (127.0.0.1 / ::1). No deploy overlap, no second holder.
6. `scheduler_executions`: last row `kbl_bridge_tick fired_at=11:41:32`; **ZERO executions after 11:41:33**. `scheduler_heartbeat` rows show `status=executed` at 11:33 and 11:38 **despite** the watermark being frozen at 11:28 → `set_watermark` failing silently (state.py:245 catch) while the job still reports executed.
7. `baker_memory_log`: RSS `869 MB`@11:28, `863 MB`@11:38 → **not OOM** (warn threshold 3000 MB). `memory_watchdog` wrote at 11:38 → the general pooled-write path was healthy after the freeze, so the watermark-write failure is row/conn-specific, not global. `kbl_pipeline_tick status=error` at 11:32:32 is the likely conn-poisoning source.

## Root cause (two stages)

**Stage 1 — initiating trigger (~11:33):** `_scheduler_heartbeat`'s `set_watermark` write began failing
silently. `triggers/state.py:222-245` swallows the exception; the heartbeat job still returns normally,
so APScheduler's listener logs `status=executed`. Evidence #6+#7. Not memory; general writes worked
(memory_watchdog wrote 11:38). Likely a poisoned pooled connection after the 11:32:32
`kbl_pipeline_tick` error (no rollback before reuse), or row-lock contention on the `scheduler_heartbeat`
row. This froze the watermark at 11:28:37 while the scheduler kept running other jobs.

**Stage 2 — fatal (~11:41):** the request-time watchdog (`outputs/dashboard.py:229`) saw the watermark
stale >720s (2 consecutive reads) and fired `restart_scheduler()`. `shutdown(wait=True)` stopped all
jobs (last execution 11:41:32 ✓). Then `start_scheduler()` → `acquire_singleton_lock()` →
`pg_try_advisory_lock(8800100)` returned FALSE, because the ORIGINAL lock session (pid 343, alive since
05:58) was **never released**: `release_singleton_lock()` was a no-op — the in-process `_held_conn`
reference had already been dropped to `None` by the earlier reacquire / stand-down false-positive path,
while pid 343's PG session stayed alive holding the lock. With no lock, `start_scheduler` registers NO
jobs and leaves `_scheduler=None` → `job_count=0`, `running=false`. Every later watchdog tick and the
30s lock-retry thread re-attempt the acquire and also fail (pid 343 never releases) → permanent stall.

**Why the watchdog can't recover it:** this is the #296 (NEON_IDLE_HARDEN) class, incompletely closed.
#296 assumed a dropped lock conn releases the server-side lock. Here the conn is NOT dropped — it is
orphaned-but-alive: the Python reference was lost via a transient-probe false positive, but the socket /
PG session is alive on Neon and still holds the advisory lock. So `pg_try_advisory_lock` can never
succeed in-process, and nothing holds a handle to release pid 343. Single-instance, so there is no
legitimate other holder to wait out. The watchdog loops a restart that can never succeed.

## Remediation (NEED YOUR GO — took no action)

**Immediate recovery (deterministic, ~1 min):** restart the Render baker-master service → SIGTERM
closes pid 343 → the advisory lock auto-releases → fresh `start_scheduler()` acquires cleanly.
*Alt without redeploy:* `SELECT pg_terminate_backend(343)` frees the lock and the live 30s retry thread
re-acquires + starts jobs — but that's a mutation; deferring to you.

**Code fix (follow-up brief, my lane):**
1. Don't abandon a live lock conn on a transient probe failure — confirm the socket is truly dead
   (retry the `SELECT 1` probe) before reacquire/stand-down; and on release ALWAYS
   `pg_terminate_backend(<held_pid>)` the prior holder before dropping the reference (track the holder
   pid via `pg_backend_pid()` at acquire time).
2. Watchdog escalation backstop: if `start_scheduler()` can't acquire and job_count stays 0 for >N min
   across M restart attempts, `os._exit()` so Render restarts the dyno fresh (SIGTERM releases the lock).
   Turns a permanent outage into a ~1-min self-heal — highest-value safety net.
3. (Secondary) Stop the silent watermark-write failure masking liveness: surface `set_watermark`
   failures (counter/log-loud) and rollback poisoned pooled conns after a job error so the heartbeat
   stops false-reporting "executed".

Awaiting GO before any fix or restart.
