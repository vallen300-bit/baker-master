# B2 CODE-FIX PROPOSAL — SCHEDULER_STALL permanent fix (for lead's gate)

- **Lineage:** SCHEDULER_STALL_DIAGNOSE_1 (diagnosis `B2_SCHEDULER_STALL_DIAGNOSE_1_20260608.md`); lead GO #2512; recovery report #2515.
- **Status:** PROPOSAL — not implemented. Lead gates the approach before I open a PR. PROD scheduler is currently healthy (self-recovered 12:22:58Z, 66 jobs firing); this is the durable fix so the next occurrence self-heals in ~1 min instead of staying dark until a human notices.
- **Class:** #296 (NEON_IDLE_HARDEN) incompletely closed — orphaned-but-alive lock holder the watchdog cannot evict.

## What actually failed (grounded in code)

Three independent gaps chained into a permanent outage:

1. **Orphaned lock holder is never evicted.** `triggers/scheduler_lease.py:181` `reacquire_singleton_lock()` and `:266` `release_singleton_lock()` both assume `conn.close()` releases the server-side advisory lock. On Neon's pooler the server session can survive the client `close()` (idle-but-alive) and keep holding lock `8800100`. Once `_held_conn` is set to `None` (reacquire TRANSIENT path, `:205`) while the old server session lives, `release_singleton_lock()` is a no-op (`:274` `if _held_conn is None: return`) and `acquire_singleton_lock()` can never win `pg_try_advisory_lock` (`:153`) because nothing in-process holds a handle to the orphan. **No code path terminates the orphan.**
2. **Watchdog loops a restart that can never succeed.** `outputs/dashboard.py:241` fires `restart_scheduler()` on stale heartbeat. If acquire keeps returning `None`, `_scheduler` stays `None`, `job_count=0`, and every later tick re-restarts to the same dead end. **No escalation backstop** (no dyno-level exit) → permanent stall until a human restarts Render.
3. **Silent watermark-write masking.** `triggers/state.py:218` `set_watermark()` swallows the exception (`:244`) AND returns the poisoned pooled conn without `conn.rollback()` (the `finally` at `:242` runs `_put_conn` even on failure — violates `.claude/rules/python-backend.md` "MUST rollback in except before any new query"). The heartbeat job still returns normally, so APScheduler logs `status=executed` while the watermark is frozen → liveness is false-reported, delaying watchdog detection and poisoning the next user of that pooled conn.

## Proposed fix (3 parts, my lane — `triggers/` + watchdog)

### Fix 1 — track the holder PID + actively evict the orphan (`triggers/scheduler_lease.py`)
- At every successful acquire/reacquire, capture the server PID: `SELECT pg_backend_pid()` on the lock session; store module-level `_held_pid` alongside `_held_conn`.
- Before abandoning a lock conn on the reacquire path, **confirm the socket is truly dead** — retry `SELECT 1` once on the existing `_held_conn`; if it answers, the conn is alive and we must NOT drop it (this transient-probe false-positive is what dropped the reference while the session lived).
- When we DO reconnect (genuine drop), from the FRESH session run `SELECT pg_terminate_backend(_held_pid)` for the prior holder **before** `pg_try_advisory_lock`, guaranteeing the orphan's lock is released so reacquire can win. Bounded by the existing `connect_timeout` / `statement_timeout`; wrap in try/except (terminate failure is non-fatal — the new session still attempts the lock).
- `release_singleton_lock()` likewise terminates `_held_pid` if the graceful `pg_advisory_unlock` + `close()` path can't confirm release.

### Fix 2 — watchdog `os._exit()` backstop (`outputs/dashboard.py:_check_scheduler_heartbeat`)
- Add a counter: consecutive watchdog fires where `restart_scheduler()` ran but `job_count` is still `0`.
- After **M** consecutive failed restarts (propose M=3, ~3–6 min at the 60s throttle) with `job_count==0`, call `os._exit(1)`. Render restarts the dyno; SIGTERM closes the lock socket at the OS level → the orphan's lock auto-releases → fresh `start_scheduler()` acquires cleanly. **This is the highest-value net:** turns a permanent outage into a ~1-min self-heal even if Fix 1 misses an edge. Guard so a healthy `job_count>0` resets the counter; log loud before exit.

### Fix 3 — stop the silent watermark masking (`triggers/state.py:set_watermark`)
- In the except block (`:244`): `conn.rollback()` before the conn returns to the pool (move/guard around the `finally` `_put_conn`), so a failed INSERT doesn't poison the pooled conn.
- Increment a module counter + `logger.error` loud on failure (already errors, but add a counter surfaced in `/api/health/scheduler` so a frozen watermark is visible before it trips the 12-min watchdog).
- (Optional, lead's call) propagate the failure to the heartbeat job so it does NOT report `executed` when the watermark write failed — stops the false "executed" rows.

## Acceptance criteria
- **AC1 (Fix 1):** simulate an orphaned holder (open a direct session, `pg_advisory_lock(8800100)`, drop the client ref without unlock) → reacquire path terminates that PID and re-owns the lock; `is_held()` true, `job_count>0`. Literal before/after PID + terminate result in the PR.
- **AC2 (Fix 1 false-positive guard):** a transient probe blip on a STILL-ALIVE lock conn does NOT drop/terminate it (`SELECT 1` retry catches it) — proves we don't evict a healthy lease.
- **AC3 (Fix 2):** with the lock force-held by an external session that the test does NOT terminate, watchdog fires M times then `os._exit(1)` is invoked (assert via injected exit hook, not a real exit in test).
- **AC4 (Fix 3):** a forced `set_watermark` failure leaves the pooled conn usable (next query on it succeeds — proves rollback) and increments the surfaced failure counter.
- **AC5:** `git diff` touches only `triggers/scheduler_lease.py`, `outputs/dashboard.py`, `triggers/state.py` (+ tests). No migration, no env change.
- **AC6:** `python3 -c "import py_compile; ..."` clean on all three; `pytest tests/` green; `bash scripts/check_singletons.sh` PASS.
- **AC7 (post-merge live):** trigger a real stale-heartbeat on PROD (or wait for natural) → confirm self-heal to `job_count>0` without human action; literal `/api/health/scheduler` before/after to lead.

## Risk / guardrails
- `pg_terminate_backend` is a mutation on the lock session only — never on pooled/web conns. Targets only the tracked `_held_pid` we ourselves acquired. Bounded by existing timeouts.
- `os._exit(1)` is deliberate — it's the documented "let Render restart the dyno" recovery, gated behind M consecutive proven-failed restarts + `job_count==0` so it can't fire on a healthy or transient state.
- HARD: do not touch `glance_state` / SSE / wake paths (unrelated). Scope is the three files above.
- Tests must run under the live-PG harness (`TEST_DATABASE_URL`) for the lock-eviction AC; mock the terminate for unit-level.

## Open question for lead
- M threshold for the `os._exit` backstop: propose **3** consecutive failed restarts. Lower = faster self-heal, higher = more tolerant of a legitimate slow handoff during a Render deploy. Lead's call before I implement.
