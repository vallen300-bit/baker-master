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

## Fix 2: bound the probe so it FAILS FAST, then self-heal the lock connection (codex G0 REVISE #1815/#1855 fold)
**Why "self-heal" alone is insufficient (the fold):** the watermark is already written FIRST
(`embedded_scheduler.py:1546-1551`), so a *single* heartbeat run's proof-of-life is independent
of probe latency. BUT the heartbeat job is `IntervalTrigger(minutes=5)` with **`max_instances=1`**
(`:782-785`). If the probe `cur.execute("SELECT 1")` (`:1560`) **HANGS** on a half-open / idle-dropped
TCP socket — which it can, because the held conn has no socket-read bound and no `statement_timeout`
— the job thread stays alive. The next 5-min fire is then **skipped** ("maximum number of running
instances reached"), so no new watermark is written, the watermark ages past the 720s / 2-cycle
threshold, and the watchdog (`dashboard.py:188`) restarts the whole scheduler **even though the
watermark was written first**. A blocking probe defeats watermark-first. So Fix 2 must make the
probe **timeout-bounded** (fail in seconds, not minutes), THEN self-heal.

**2a — bound the probe (load-bearing):**
- TCP-dead detection: the Fix 1 keepalives (`keepalives_idle=30, interval=10, count=5`) bound a
  half-open socket to ~80s of detection — comfortably under the 300s next-fire, so a hung
  instance always clears before the next heartbeat. This is the primary bound for the idle-drop case.
- Server-stall detection: set a **`statement_timeout` on the scheduler lock SESSION** so a
  server-side stall also fails fast. Set it at acquire time **inside `scheduler_lease.py` only**
  (e.g. `cur.execute("SET statement_timeout = '10s'")` right after `conn.autocommit = True` in
  `acquire_singleton_lock`, before `pg_try_advisory_lock`) — **NOT** in the shared `direct_dsn_params`,
  to avoid changing reingest/OCR lock-conn behavior. statement_timeout bounds the server-busy case;
  keepalives bound the TCP-dead case; together the probe cannot block the heartbeat job thread.
- **Connect-bound (codex G0 REVISE #1869 Finding 1, HIGH):** keepalives do NOT bound the *initial
  TCP connect*, and `statement_timeout` only applies once a session exists — so the **self-heal
  reconnect itself can hang** on a dead network, re-introducing the exact block we're removing. Pass
  **`connect_timeout=5`** as an explicit kwarg on BOTH the `acquire_singleton_lock` and the new
  `reacquire_singleton_lock` `psycopg2.connect(...)` calls in `scheduler_lease.py` (mirror the
  existing direct-connect precedent at `embedded_scheduler.py:127` which already passes
  `connect_timeout=5, **config.postgres.direct_dsn_params`). Keep it on the scheduler-lock connect
  calls (not in shared `direct_dsn_params`) per the reviewer's scoping.

**2b — self-heal with correct failure-mode split (codex G0 REVISE #1869 Finding 2, HIGH):** when the
(now fast-failing) probe raises, call a new `reacquire_singleton_lock()` helper in `scheduler_lease.py`
(mirror `acquire_singleton_lock` — close the dead `_held_conn` first, then `connect_timeout=5` +
keepalives + `autocommit` + `SET statement_timeout` + `pg_try_advisory_lock`). It returns a **3-state
result** the heartbeat acts on — because the singleton contract is *no jobs may run without the lock*
(`embedded_scheduler.py:1699-1707` registers NO jobs when `acquire_singleton_lock()` returns None;
`scheduler_lease.py:39-46` requires the caller hold the conn for process lifetime). The naive
"reconnect, set `_held_conn`, continue" path is wrong: if **another process grabbed the freed lock**
(deploy overlap), this process would keep firing its already-registered jobs **with no lock held** →
duplicate scheduler. Split it:

| Outcome of reacquire | Meaning | Heartbeat action |
|---|---|---|
| reconnect OK + `pg_try_advisory_lock` **TRUE** | we re-own the same lock; no other holder | set `_held_conn`, log INFO, **continue firing** (the win path — conn died, we re-grabbed it, NO teardown) |
| reconnect OK + `pg_try_advisory_lock` **FALSE** | another container owns the lock now → we are a zombie duplicate | close the conn, `_held_conn=None`, **request stand-down** (see below) — must STOP firing |
| reconnect FAILS (connect_timeout / DB unreachable) | ownership indeterminate, transient | `_held_conn=None`, log WARN, **return** (next heartbeat retries; watchdog backstop). Do NOT stand down on a transient — if DB is unreachable to us it is generally unreachable to all, so no other process can grab the lock |

**Stand-down via a non-self-join path:** never call `restart_scheduler()` / `shutdown(wait=True)`
from the heartbeat *job thread* (a thread cannot join itself). Instead set a module-level flag in
`scheduler_lease` (`request_standdown()` → sets `_standdown_requested`; `consume_standdown()` →
test-and-clear). The **request-thread** middleware watchdog `_check_scheduler_heartbeat()`
(`dashboard.py:188`, runs on request threads, NOT the job thread) checks `consume_standdown()` FIRST
each tick and, if set, calls `restart_scheduler()`. `restart_scheduler()` → `release_singleton_lock()`
→ `start_scheduler()` → `acquire_singleton_lock()` returns None (other holder) → registers NO jobs +
spawns the existing 30s lock-retry thread → clean stand-down, no self-join. (If by then the other
holder is gone, the retry thread re-starts jobs — existing behavior.) Watermark stays written FIRST.

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
- `triggers/scheduler_lease.py` — `connect_timeout=5` + `SET statement_timeout` on acquire; new `reacquire_singleton_lock()` (3-state) + `request_standdown()`/`consume_standdown()` flag.
- `triggers/embedded_scheduler.py` — heartbeat probe calls `reacquire_singleton_lock()` + acts on the 3-state result (continue / request stand-down / transient retry) + restart-reason log.
- `outputs/dashboard.py` — `_check_scheduler_heartbeat()` checks `consume_standdown()` FIRST each tick → `restart_scheduler()` (non-self-join executor).
- `tests/test_scheduler_*.py` — see Verification.

## Do NOT Touch
- The reingest/OCR advisory-lock endpoints (they benefit from the keepalive change for free; don't alter their logic).
- The in-memory jobstore choice.

## Verification
- `pytest tests/test_scheduler_liveness*.py tests/test_scheduler_lease*.py -v` (literal).
- New unit: `direct_dsn_params` includes the 4 keepalive keys.
- New unit: `acquire_singleton_lock` issues `SET statement_timeout` on the lock session (assert the
  `SET statement_timeout` call is made on the cursor; mock psycopg2.connect).
- New unit: heartbeat probe whose `_held_conn` cursor **raises** triggers `reacquire_singleton_lock`
  (assert called, not a no-op), and the watermark is still written FIRST (assert set_watermark called
  before the probe).
- New unit: `acquire_singleton_lock` AND `reacquire_singleton_lock` pass `connect_timeout=5` to
  `psycopg2.connect` (assert the kwarg; mock connect).
- New unit (3-state split): (a) reconnect OK + advisory-lock TRUE → `_held_conn` set, NO stand-down
  requested, heartbeat continues; (b) reconnect OK + advisory-lock FALSE → `_held_conn=None`, conn
  closed, `request_standdown()` called; (c) reconnect raises (connect_timeout) → `_held_conn=None`,
  WARN, NO stand-down, heartbeat returns without raising.
- New unit: `_check_scheduler_heartbeat()` with `_standdown_requested` set calls `restart_scheduler()`
  and clears the flag (test-and-clear is idempotent — second tick does not re-restart).
- Live: the Done-rubric ≥40-min window.

## POST_DEPLOY_AC_VERDICT v1 (B-code fills on prod)
- AC1 no-restart-loop: PASS/FAIL + ZERO restart lines over ≥40 min.
- AC2 heartbeat-fresh: PASS/FAIL + watermark-age timeline (max <10 min).
- AC3 health-steady: PASS/FAIL + 5 spot reads all `running/64`.
