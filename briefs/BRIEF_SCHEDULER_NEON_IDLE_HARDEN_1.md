# BRIEF: SCHEDULER_NEON_IDLE_HARDEN_1 — stop the ~18-min scheduler teardown-rebuild loop

## Context
baker-master's Sentinel scheduler enters a periodic teardown→rebuild loop (~18 min cadence;
cowork-ah1 logs 2026-06-04: clean "BackgroundScheduler started with 64 jobs" at 14:42/15:00/
15:18/15:36/15:55Z, no Render restart/OOM between). `/health` intermittently reports
`scheduler: stopped, jobs: 0` in the gap between teardown and rebuild. Background polls
(email/sentinels) run in the up-windows but drop during each gap — degraded, not dead.

**Verified mechanism (not a guess — read from the live code at HEAD):**
1. Jobstore is **in-memory** (`BackgroundScheduler()` with no jobstore arg, `triggers/embedded_scheduler.py:1709`) — so this is NOT a jobstore-conn drop.
2. The **dashboard middleware watchdog** is the sole restarter (`outputs/dashboard.py:175 scheduler_watchdog_middleware` → `:188 _check_scheduler_heartbeat`): if the `scheduler_heartbeat` watermark is stale **>720s (12 min)** on **2 consecutive** 60s-throttled reads, it calls `restart_scheduler()`.
3. The heartbeat is written every 5 min by `_scheduler_heartbeat()` (`embedded_scheduler.py:1536`), which also probes the **singleton-lock direct connection** (`_lease._held_conn.execute("SELECT 1")`).
4. The singleton-lock connection is opened on the **non-pooled Neon endpoint with NO TCP keepalives** (`triggers/scheduler_lease.py:64` `psycopg2.connect(**config.postgres.direct_dsn_params)`; `direct_dsn_params`, `config/settings.py:195-211`, sets only host/port/dbname/user/password/sslmode). Neon idle-disconnects non-pooled connections after inactivity → the held lock conn dies between 5-min probes → heartbeat/lock path degrades → watermark goes stale → watchdog restarts the whole scheduler. Loop repeats.

### Surface contract: N/A — backend scheduler/DB-connection hardening; no clickable surface.

## Harness V2
- **Routed owner:** B-code (b1 or b3, whichever idle).
- **Task class:** production reliability fix (availability of background polls).
- **Context Contract:** mechanism + file:line + the connect-param fix are below; no discovery needed beyond AC0 log-confirm.
- **Done rubric (literal):** over a ≥40-min live window post-deploy, `scheduler_heartbeat` watermark age never exceeds ~10 min, `/health` shows `scheduler: running, jobs: 64` on ≥5 spot checks with NO `stopped/0` reading, and the Render logs show ZERO `restart_scheduler` / watchdog-restart lines in that window (the loop is gone). Paste the watermark-age timeline + the 5 health reads.
- **Gate plan:** G0 codex-arch (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (PR) → merge → POST_DEPLOY_AC_VERDICT v1 (the ≥40-min window).

## Estimated time: ~1.5h
## Complexity: Medium
## Prerequisites: none.

---

## Fix 0 (AC0): confirm the trigger from logs (do FIRST, ~10 min)
Before coding, confirm the loop is watchdog-driven: grep baker-master logs since 13:35Z for
`restart_scheduler` / the `_check_scheduler_heartbeat` WARN line / "BackgroundScheduler started".
Expect: periodic restart lines ~18 min apart preceded by a stale-heartbeat WARN. Record the
exact restart reason string. If the trigger is NOT the heartbeat-stale watchdog, STOP and bus AH1
(the fix below targets that path). (Render log access: ask AH1/cowork-ah1 if API creds needed.)

## Fix 1: TCP keepalives on the direct (non-pooled) connection — primary fix
`config/settings.py` `direct_dsn_params` (~:195-211): add libpq keepalive params so Neon does
not idle-drop the long-lived singleton-lock connection:

```python
        params = {
            "host": host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            # SCHEDULER_NEON_IDLE_HARDEN_1: keep the long-lived non-pooled lock
            # connection alive so Neon does not idle-disconnect it between the
            # 5-min heartbeat probes (root of the ~18-min scheduler restart loop).
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
        if self.sslmode and self.sslmode != "disable":
            params["sslmode"] = self.sslmode
```
NOTE: this also flows into every other `direct_dsn_params` consumer (reingest lock, OCR lock,
scheduler_lease) — all want keepalives, so this is the right single place. Verify no consumer
passes a conflicting keepalive kwarg.

## Fix 2: heartbeat self-heals the lock connection instead of dying — defense in depth
In `_scheduler_heartbeat()` (`embedded_scheduler.py:1536+`), when the `_held_conn` `SELECT 1`
probe raises (dead conn), **reconnect + re-acquire the advisory lock in place** (call the
`scheduler_lease` re-acquire path) rather than leaving `_held_conn` dead until the watchdog
tears down the whole scheduler. Keep it diagnostic-only re: NOT calling `restart_scheduler()`
from the job thread (reentrancy hazard, per the existing comment) — just repair the connection.
If a clean re-acquire helper doesn't exist in `scheduler_lease.py`, add one (mirror
`acquire_singleton_lock` with keepalives) and call it here. Watermark is still written FIRST
(unchanged) so proof-of-life never depends on probe latency.

## Fix 3: log the teardown reason loudly — observability
Ensure `restart_scheduler()` and the watchdog restart path log a single greppable line
(`SCHEDULER_RESTART reason=<...>`) so the cadence is observable and a regression is caught.
(The `dashboard.py:540` swallow is real but not the active failure here — leave it, just add the
restart-reason log.)

## Key Constraints
- Do NOT switch the jobstore to a DB jobstore (in-memory is intentional; a DB jobstore would re-introduce a Neon-idle dependency).
- Do NOT remove the watchdog (it's the backstop) — make it stop FIRING by keeping the conn alive.
- Advisory-lock semantics unchanged (key 8800100, autocommit direct conn).
- All DB ops fault-tolerant (rollback/close); no secrets.

## Files Modified
- `config/settings.py` — keepalives in `direct_dsn_params`.
- `triggers/scheduler_lease.py` — re-acquire helper (if needed) for Fix 2.
- `triggers/embedded_scheduler.py` — heartbeat self-heals lock conn + restart-reason log.
- `tests/test_scheduler_*.py` — see Verification.

## Do NOT Touch
- The reingest/OCR advisory-lock endpoints (they benefit from the keepalive change for free; don't alter their logic).
- The in-memory jobstore choice.

## Verification
- `pytest tests/test_scheduler_liveness*.py tests/test_scheduler_lease*.py -v` (literal).
- New unit: `direct_dsn_params` includes the 4 keepalive keys.
- New unit: heartbeat with a mocked-dead `_held_conn` triggers a re-acquire (not a no-op), watermark still written.
- Live: the Done-rubric ≥40-min window.

## POST_DEPLOY_AC_VERDICT v1 (B-code fills on prod)
- AC1 no-restart-loop: PASS/FAIL + ZERO restart lines over ≥40 min.
- AC2 heartbeat-fresh: PASS/FAIL + watermark-age timeline (max <10 min).
- AC3 health-steady: PASS/FAIL + 5 spot reads all `running/64`.
