# BRIEF: BUS_CONGESTION_KEEPALIVE_FIX_1 — background pool warmer kills the stale-probe 503 wall

```yaml
brief_id: BUS_CONGESTION_KEEPALIVE_FIX_1
dispatched_by: lead
assigned_to: b1
repo: brisen-lab (worktree ~/bm-b1/brisen-lab; branch b1/bus-keepalive-fix-1 from origin/main)
status: PENDING
```

## Context

Follow-up to BUS_CONGESTION_503_DIAGNOSIS_1 (your build @f950c98, merged @e24a104;
findings bus #14402, lead POST_DEPLOY_AC_VERDICT PASS + findings ratified same
thread). Root cause is PROVEN, exclusive, and yours:

- 3 soak pulls: `stale_probe_budget` = **100.0%** of all 503s (475 / 2,636 / 4,376);
  `acquire_timeout` = 0, `all_stale` = 0, `other` = 0.
- Pool near-idle every pull (used 6-9/40). NOT saturation. A pool bump changes nothing.
- Mechanism: Neon ~300s autosuspend leaves pooled conns half-open. `get_conn()`
  (db.py ~L399-467) probes any conn idle > `_PROBE_IDLE_THRESHOLD_S` (60s, db.py:89)
  under ONE shared `_PROBE_TIMEOUT_S=2.0s` budget (db.py:101, deadline set db.py:421).
  Budget spent walking stale conns → `BusPoolExhausted(cause="stale_probe_budget")` →
  503 — and the unprobed stale conn is `putconn`'d BACK, so the pool stays poisoned
  and the next request pays again.

This brief ships the ONE fix you recommended in #14402: a background keepalive/
recycler that keeps pooled connections warm so request-path checkouts never
inherit a stale pool and never pay the probe tax. Attacks the root (stale conns),
not the symptom.

### Surface contract: N/A — backend-only (background task + gauge field; no user-clickable surface)

## Estimated time: ~2-4h
## Complexity: Medium (Small-Medium per your own sizing)
## Prerequisites: none (instrument already live @e24a104)

## Harness V2

- **Context Contract:** read before building: this brief (whole); `db.py`
  (`get_conn` probe loop L399-467, `_probe_live` ~L301-330, `_mark_used`,
  `_idle_seconds`, `pool_stats` ~L375-397, `_PROBE_IDLE_THRESHOLD_S`:89,
  `_PROBE_TIMEOUT_S`:101, keepalive connect opts L264-267); `app.py` startup
  block L285-390 (existing `asyncio.create_task` loop pattern — copy its shape);
  `tests/test_db_conn_harden.py` (existing probe/pool test harness incl. frozen
  `_now()` pattern). Nothing else required.
- **Task class:** small-fix-production (brisen-lab, production).
- **Done rubric:** terminal = Merged + Deployed + post-deploy AC passed +
  writeback. Post-deploy AC (lead runs): after ≥30 min live soak,
  `pool_stats.bus_503.by_cause.stale_probe_budget` rate collapses vs the
  5.3k/hr baseline (target: >95% reduction in the 1h window) AND
  `pool_stats.warmer` shows live cycles. Writeback: ship report on bus with
  before/after by_cause pulls.
- **Gate plan:** b1 self-test (pytest + monkeypatched warm-cycle unit tests) →
  push branch → blocking codex gate on pushed SHA → lead merge → Render
  auto-deploy → ≥30 min soak → lead POST_DEPLOY_AC_VERDICT.

---

## Fix 1: background pool warmer (`db.py` + `app.py` startup)

### Problem
Stale conns sit in the free list until a request pays the probe tax; the 2.0s
shared budget makes sustained-load checkouts 503 while the pool is near-idle.

### Current State
- Probe only happens ON CHECKOUT (db.py L399+); budget-exhausted checkouts
  return the stale conn to the pool unprobed (db.py ~L441-449) — poison persists.
- TCP keepalives (db.py L264-267) do NOT prevent Neon autosuspend half-opens.
- No background task touches the pool; `app.py` startup already spawns ~12
  `asyncio.create_task(...)` loops (L339-386) — the pattern to copy.

### Engineering Craft Gates
- Diagnose: DONE in the parent brief — instrument live, cause exclusive, no
  further hypotheses needed.
- Prototype: N/A — mechanism fully understood from the diagnosis; the warm
  loop reuses existing `_probe_live` machinery.
- TDD/verification: applies — public seam = `warm_pool_once()` (new, importable,
  synchronous core so tests call it without the asyncio loop). First vertical
  test: pool with one artificially idle-aged conn → `warm_pool_once()` →
  next `get_conn()` checkout hot-trusts (`last_checkout_meta()["probed"] is
  False`). Reuse the frozen-`_now()` harness from `tests/test_db_conn_harden.py`.

### Implementation (contract — you own the detail; you know this file better than anyone)

1. **`db.py` — `warm_pool_once()`** (sync, called from the async loop via
   `asyncio.to_thread`): temporarily check out up to `free`-count conns
   (non-blocking `getconn`; stop early if pool contention), and for each:
   - idle age ≤ threshold → `putconn` untouched (hot, skip);
   - idle age > `_WARM_IDLE_TRIGGER_S` (default 45.0s — BELOW the 60s checkout
     threshold, so conns are re-warmed before they ever look stale to
     `get_conn`) → `_probe_live(conn, pool, _WARM_PROBE_TIMEOUT_S)` (2.0s):
     live → `_mark_used(conn)` + `putconn` (idle stamp refreshed → next
     checkout hot-trusts); dead → `_probe_live` already discarded it; pool
     refills lazily.
   - Per-cycle wall budget (default 10s): stop probing when spent; never
     block the loop indefinitely.
   - NEVER raises (gauge/warmer discipline, same as `pool_stats`); every
     conn checked out here MUST be returned or discarded in a `finally`.
2. **Warmer gauge:** extend `pool_stats()` with
   `"warmer": {"last_cycle_ts", "cycles", "probed", "refreshed", "discarded", "skipped_hot"}`
   (module-level counters; best-effort, never raises).
3. **`app.py` startup:** `asyncio.create_task(_pool_warm_loop())` alongside the
   existing loops; loop = `while True: await asyncio.to_thread(warm_pool_once);
   await asyncio.sleep(_WARM_INTERVAL_S)` with a broad try/except that logs and
   continues (one bad cycle must not kill the loop).
4. **Env knobs (all read once at import, same style as `BRISEN_LAB_POOL_MAXCONN`):**
   `BRISEN_LAB_WARM_INTERVAL_S` (default 45; `0` = warmer disabled — the kill
   switch), `BRISEN_LAB_WARM_IDLE_TRIGGER_S` (default 45),
   `BRISEN_LAB_WARM_PROBE_TIMEOUT_S` (default 2.0),
   `BRISEN_LAB_WARM_CYCLE_BUDGET_S` (default 10).

### Key Constraints
- **Do NOT change** the checkout-path semantics: `_PROBE_TIMEOUT_S`,
  `_PROBE_IDLE_THRESHOLD_S`, the bounded loop, the 503 body, `by_cause`
  accounting — all stay byte-identical. The warmer makes the probe path RARE;
  it does not replace it.
- **Do NOT touch Neon config** (autosuspend stays; ruled out in #14402).
- **Do NOT bump pool size** (proven irrelevant).
- Warmer must be starvation-safe: non-blocking getconn, early-exit on
  contention, hard cycle budget. Under a burst it should do nothing, not queue.
- Double-instance safe (Render deploy roll): two warmers running concurrently
  must be harmless (they are — probing/refreshing is idempotent; discards just
  refill). No advisory lock needed; say so in the ship report if you disagree.

### Verification
- pytest: warm cycle refreshes idle stamp → checkout hot-trusts; dead conn
  discarded + counted; cycle budget respected (monkeypatch `_probe_live` to
  sleep); `BRISEN_LAB_WARM_INTERVAL_S=0` spawns nothing; `warm_pool_once` never
  raises with a broken pool (monkeypatch getconn to throw).
- Local: run app, watch `pool_stats.warmer` counters advance.
- Live (lead, post-merge): ≥30 min soak → by_cause pull vs your #14402 baseline.

---

## Files Modified
- `db.py` — `warm_pool_once()`, warmer counters, env knobs, `pool_stats()` warmer block
- `app.py` — one `asyncio.create_task(_pool_warm_loop())` in startup
- `tests/test_db_conn_harden.py` (or new `tests/test_pool_warmer.py`) — warm-cycle tests

## Do NOT Touch
- `get_conn()` checkout loop / raise sites / 503 body — the diagnosis contract depends on them staying stable
- `_acquire_conn` / db_gate — proven not the wall
- Neon settings, `render.yaml` pool env values

## Quality Checkpoints
1. All existing db/bus tests green (no checkout-semantics drift).
2. `pool_stats` JSON shape backward-compatible (warmer block is additive).
3. Kill switch verified: `BRISEN_LAB_WARM_INTERVAL_S=0` → no task, no counters.
4. Post-deploy: stale_probe_budget rate collapse >95% vs 5.3k/hr baseline; warmer cycles visible.
5. No new 503 cause values introduced.
