# BRIEF: BRISEN_LAB_F503_BOUNDED_ACQUIRE_1 — bounded getconn retry so pool-exhaustion 503s stop flapping

> Authored by deputy (AH2) per lead ruling #9454 (GO Option A). Dispatch-ready.
> Route: free builder, **deputy-codex first if free** (lead new routing rule); independent
> codex gate; **lead merges** (no self-certified merge — standing rule #9255).

dispatched_by: lead
assigned_to: <builder — deputy-codex first if free, else b-code>
task_class: backend-reliability (brisen-lab daemon, DB connection acquisition)
Harness-V2: Context Contract + done rubric + gate plan inline below.
effort: low (~1h)

## Context

**Context Contract.** Target repo: brisen-lab (`vallen300-bit/brisen-lab`), checkout `~/bm-b<N>-brisen-lab`. Single file of real change: `db.py` (`get_conn` acquisition). No schema change, no API-surface change, no client-script change. maxconn stays 10 (Neon connection-budget is unchanged — this is the whole point of Option A vs raising the pool).

F-503 (live-defect evidence log, 2026-07-12): POST/GET against the daemon returns `{"detail":"bus_busy_retry"}` (HTTP 503) intermittently on **both read and write** paths, ~5–60% of calls under fleet burst, masking the real response. The client must blind-retry — which in turn drives the E2 duplicate-post class and compounds the E1 ack pain.

**F-503 is NOT a bug.** It is `BRISEN_LAB_DB_CONN_HARDEN_1` Fix 3 working exactly as designed: `db.py get_conn()` calls `pool.getconn()`, which raises `psycopg2.pool.PoolError` **immediately** when the `ThreadedConnectionPool` is at `maxconn=10`; `get_conn` maps that to `BusPoolExhausted`, and `app.py`'s `_pool_exhausted_handler` returns 503 `bus_busy_retry` (verified: `app.py:117-124`, `db.py:238-300`). The 503 replaced the old 30s hang — correct. The residual problem is that the acquire is **non-blocking**: a *transient* burst (FastAPI runs the sync handlers via `asyncio.to_thread`'s default executor, which can spawn more worker threads than 10) instantly 503s even though bus/jobs calls are sub-100ms and a connection frees almost immediately.

Lead ruling #9454: **GO Option A** — add a short bounded wait before surfacing the 503. Option C (fold into the inter-agent-comms redesign) is logged separately as a redesign input; this brief is the cheap now-fix.

## Problem

`get_conn()` surfaces `BusPoolExhausted` (→503) on the *first* `PoolError`, with zero wait. Under a sub-second concurrency spike this rejects requests that would have succeeded ~10–50ms later. Result: 5–60% flap, forcing every client onto blind-retry, which (a) doubles bus load, (b) manufactures E2 duplicate posts, (c) makes E1 ack failures look worse. We want *real backpressure* — briefly wait for a slot, and 503 only when the pool is genuinely saturated for longer than a small budget.

## Fix (Option A — bounded acquisition retry)

In `db.py get_conn()`, wrap the `pool.getconn()` call so that a `PoolError` (pool at maxconn) does **not** immediately raise `BusPoolExhausted`. Instead:

1. Retry `pool.getconn()` in a loop until a total **acquire budget** expires (default **300 ms**, env-overridable `BRISEN_LAB_POOL_ACQUIRE_BUDGET_MS`, clamp to a sane range e.g. 0–2000 ms; 0 preserves today's fail-fast behaviour for tests/rollback).
2. Between attempts, sleep a **short jittered** interval (e.g. 10–30 ms randomised) to avoid a thundering herd. Use `time.monotonic()` for the deadline (same discipline as the existing stale-probe budget — do NOT use `_now()`, which tests freeze).
3. If a connection is obtained within budget, continue into the **existing** stale-probe / liveness loop unchanged (the acquire-retry wraps *around* it; the two budgets are independent — acquire budget for "pool full", probe budget for "stale conns after autosuspend").
4. If the budget expires still at `PoolError`, raise `BusPoolExhausted` exactly as today → 503 `bus_busy_retry`. Backpressure is preserved; we only absorbed the transient spike.

Design constraints (must hold):
- **The wait must NOT hold a connection.** `getconn()` raised — nothing is checked out during the wait. Correct by construction; keep it that way (do not pre-acquire).
- **Blocking sleep is safe here** — `get_conn` runs inside `asyncio.to_thread`, so `time.sleep` blocks only the worker thread, never the event loop. (State this in a code comment so a future reader doesn't "fix" it to `asyncio.sleep`.)
- **`try_acquire_refresh_lock()` (db.py:303+) has the SAME immediate-`PoolError`→`BusPoolExhausted` pattern.** Decide explicitly: either factor the bounded-acquire into a shared helper both call, or leave the refresh-lock path fail-fast and note why. Do not silently diverge (surface-conflicts rule).
- Worst-case added latency = the acquire budget (~300 ms) and ONLY when the pool is saturated; the happy path (`getconn` succeeds first try) adds nothing.

## Files Modified

- `db.py` — `get_conn()` bounded-acquire retry (+ shared helper if `try_acquire_refresh_lock` is folded in); new env knob `BRISEN_LAB_POOL_ACQUIRE_BUDGET_MS`.
- `tests/test_db_conn_harden.py` (extend) or new `tests/test_pool_bounded_acquire.py`.

## Verification

1. **Unit — absorbs a transient spike:** monkeypatch/fake pool so `getconn()` raises `PoolError` for the first K attempts then returns a live conn; assert `get_conn()` returns that conn within the budget and does NOT raise. Assert total elapsed ≤ budget.
2. **Unit — genuine saturation still 503s:** fake pool raises `PoolError` for the entire budget window; assert `BusPoolExhausted` is raised (→ app handler 503) and elapsed ≈ budget (bounded, no unbounded spin).
3. **Unit — budget=0 preserves fail-fast:** with `BRISEN_LAB_POOL_ACQUIRE_BUDGET_MS=0`, first `PoolError` raises immediately (today's contract; rollback safety).
4. **Unit — jitter/no-thundering-herd:** attempts are spaced (sleep called between retries); deadline uses `time.monotonic`, not `_now()` (prove tests that freeze `_now()` still bound the loop).
5. **Regression:** existing stale-probe tests still pass (acquire-retry must not perturb the probe loop).
6. **Post-deploy AC (live):** after lead merges + Render deploys, re-run the b1 queue-soak drill (`briefs/_reports/B1_queue_soak_drill_postdeploy_ac_20260712.md` methodology) and measure the 503 rate on read+write; **target: from 5–60% down to <5%** under the same drill. Emit `POST_DEPLOY_AC_VERDICT v1` to lead. If still >5%, escalate — Option B (semaphore-cap the to_thread executor to maxconn) becomes the follow-up.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) transient-spike test green; (2) saturation-still-503 test green; (3) budget=0 fail-fast test green; (4) monotonic-deadline proven; (5) refresh-lock path decision documented; (6) regression suite green; (7) live soak 503 rate <5% with `POST_DEPLOY_AC_VERDICT v1` posted. maxconn unchanged (grep-assert still 10).
- **done-state class:** production daemon change → requires live post-deploy AC verdict, not just unit-green.
- **gate plan:** author (this brief) → builder implements → **independent codex verify (G-gate) BEFORE merge** (standing rule #9255; cross-vendor preferred; deputy-codex may build but the gate agent must be independent of the author) → lead merges → deploy → deputy re-runs soak drill for the live AC.
- **Harness-V2:** covered inline (Context Contract, task class, done rubric, done-state class, gate plan).

## Redesign note (Option C, logged not actioned)

The masked-503-then-blind-retry pattern is a transport-design smell. Logged as an input to the inter-agent-comms redesign (`wiki/matters/flight-academy/.../2026-07-12-live-defect-evidence-log.md`, F-503): the real end-state is explicit backpressure/queueing with a client-visible "retry-after", not a 503 the caller papers over. Option A buys time; it does not close the design question.
