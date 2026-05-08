# BRIEF: BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1 — sentinel-on-success + thread-safe pool + abandoned-thread alarm + real chain test

## Context

PR #172 (`fix(backfill): swap order Plaud-first + per-step 5-min timeout`) shipped the boot-time chain reorder + per-step timeout 2026-05-08, fixing the immediate symptom (Fireflies wedge blocked Plaud). Live diagnosis the same morning surfaced 4 IMPORTANT structural findings in the surrounding subsystem that did NOT block PR #172 but matter for ongoing health:

1. **Sentinel-on-success gap** — `backfill_plaud()` ingests records but never calls `report_success("plaud")`. `sentinel_health.plaud.last_success_at` stayed at `2026-04-29T09:08:52Z` despite the 2026-05-08 boot-time backfill ingesting 3 transcripts. Same gap on `backfill_fireflies()`. Result: sentinel health alarms (T2-down threshold) cannot distinguish "polling is broken" from "backfill ran but the incremental poll has not yet found anything new".
2. **Pool not thread-safe** — `memory/store_back.py:226` uses `psycopg2.pool.SimpleConnectionPool`, which the upstream psycopg2 docs explicitly state is single-thread-only. Daemon backfill thread + main process + APScheduler workers all share this pool. Today no incident traced to it; tomorrow's harder-to-debug.
3. **Abandoned-thread silent pen** — `triggers/backfill_runner.run_backfill_with_timeout` `t.join(timeout=...)` returns; if the thread is still alive, it keeps holding `pg_advisory_lock(867532)` + `_backfill_running=True`. Periodic poller `check_new_plaud_recordings` skips on `_backfill_running=True` (line 382). A wedged daemon = silent permanent skip until next Render restart, with no alarm.
4. **Tautology test** — `test_plaud_runs_before_fireflies_in_chain` calls `run_backfill_with_timeout` twice in test code in the order it asserts. It never imports / executes `outputs/dashboard.py:_delayed_backfills`. A future rewrite of `_delayed_backfills` reversing the order would NOT fail this test.

Source: AH1 am handover `session_handover_2026-05-08_am_aihead_a_plaud_token_restored_3_transcripts.md` §"Folds 4 IMPORTANT findings".

## Estimated time: ~2.5h
## Complexity: Medium
## Prerequisites: PR #172 merged (already on main `d8ebf17`); PR #170 brief merged (`bdb6416`, doc-only — does not change code surface here).

---

## Fix 1: Sentinel report_success/failure on backfill terminal states

### Problem
`backfill_plaud()` (triggers/plaud_trigger.py:636-775) and `backfill_fireflies()` (triggers/fireflies_trigger.py:452-611) ingest records but never report to `sentinel_health`. Only the incremental pollers report. After the 2026-05-08 boot-time backfill ingested 3 transcripts, `sentinel_health.plaud.last_success_at` was still `2026-04-29T09:08:52Z` — silent ten-day stale.

### Current state
- `triggers/plaud_trigger.py:371` — incremental poller imports `report_success, report_failure, should_skip_poll`.
- Lines 400 / 429 / 624 — three `report_success("plaud")` calls in incremental code paths.
- `def backfill_plaud()` line 636 — zero `report_success` calls. Bare `try/except` at line 668 + 764, no health write in either branch.
- Same shape in `backfill_fireflies()` line 452-611.

### Implementation

**1a. `triggers/plaud_trigger.py:636-775` — `backfill_plaud()`**

Add a sentinel write at the success terminus and the failure terminus. Keep the existing advisory-lock + `_backfill_running` flow intact.

Replace the function's `try`/`except`/`finally` block (current lines 668-775) with the following terminal-state structure (the inner ingest loop body is unchanged — preserve it verbatim):

```python
    _backfill_running = True
    try:
        logger.info("Plaud backfill: starting...")
        recordings = fetch_plaud_recordings()
        if not recordings:
            logger.info("Plaud backfill: no recordings found")
            # Empty result is still a successful poll round.
            from triggers.sentinel_health import report_success
            report_success("plaud")
            return

        store = SentinelStoreBack._get_global_instance()
        ingested = 0

        for rec in recordings:
            # ... existing per-record ingest body unchanged (lines 678-760) ...

        logger.info(f"Plaud backfill complete: {ingested} recordings ingested")
        # NEW — sentinel success on clean completion of the ingest loop.
        from triggers.sentinel_health import report_success
        report_success("plaud")

    except Exception as e:
        logger.error(f"Plaud backfill failed: {e}")
        # NEW — sentinel failure on top-level except.
        try:
            from triggers.sentinel_health import report_failure
            report_failure("plaud", f"backfill: {e}")
        except Exception as _sh_e:
            logger.warning(f"sentinel report_failure crashed (non-fatal): {_sh_e}")
    finally:
        _backfill_running = False
        # Release advisory lock (existing code unchanged)
        try:
            _lock_cur = _lock_conn.cursor()
            _lock_cur.execute("SELECT pg_advisory_unlock(867532)")
            _lock_conn.commit()
            _lock_cur.close()
        except Exception:
            pass
```

**1b. `triggers/fireflies_trigger.py:452-611` — `backfill_fireflies()`**

Mirror Fix 1a. Insert `report_success("fireflies")` at the success terminus (right after the final `logger.info("Fireflies backfill complete: ...")` at line 596-599) and `report_failure("fireflies", f"backfill: {e}")` in the existing top-level `except Exception as e:` at line 601 before the `logger.error` line. Wrap the `report_failure` call in its own try/except (sentinel write must never crash the backfill itself).

### Key constraints
- Sentinel module path: `from triggers.sentinel_health import report_success, report_failure` (same as incremental code paths). Already imported at line 371 / line 274 of the two files for the incremental-poll route — do NOT collapse into a module-level import (mirror the existing local-import pattern, deliberate to avoid circular imports per `BRIEF_SENTINEL_HEALTH_1.md`).
- Empty-recordings branch (line 671-673 plaud / equivalent fireflies) is a successful round — `report_success` MUST fire. Same call shape as incremental.
- The `report_failure` call MUST be wrapped in its own try/except so a transient sentinel-table write failure does NOT mask the underlying backfill exception.

### Verification
```sql
SELECT source, last_success_at, last_failure_at, last_failure_reason
FROM sentinel_health WHERE source IN ('plaud', 'fireflies');
```
After Render redeploy, `last_success_at` for `plaud` should advance within ~70s (60s delay + backfill run). Fireflies will set `last_failure_at` (silent-dead since 2026-04-11) — expected; that flips it from "silent" to "loud broken", which is the point.

---

## Fix 2: Swap SimpleConnectionPool → ThreadedConnectionPool in store_back

### Problem
`memory/store_back.py:226` initializes `psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=5, ...)`. Per psycopg2 docs: *"Connections are not thread safe; you cannot share a single connection across threads. SimpleConnectionPool is not thread-safe."*

The pool is shared by:
- Main FastAPI thread (sync DB calls in dashboard endpoints)
- APScheduler worker threads (every poll job)
- Daemon backfill thread (`_delayed_backfills`)
- Cortex cycle execution threads

`SimpleConnectionPool.getconn()` / `putconn()` use a plain Python list with no `threading.Lock`. Concurrent get/put can corrupt the free list (silent pool drain or double-checkout). Today undiagnosed; tomorrow a debug nightmare.

### Current state
- `memory/store_back.py:14-16` — imports `psycopg2`, `psycopg2.extras`, `psycopg2.pool`.
- `_init_pool` line 223-234 — `SimpleConnectionPool(minconn=1, maxconn=5, **config.postgres.dsn_params)`.
- `_get_conn` line 236-246 / `_put_conn` line 248-259 — both call into the pool with no external lock.
- Singleton enforced via `_get_global_instance()` (referenced repeatedly in callers); pool is shared by every caller.

### Implementation

**2a. `memory/store_back.py:226`**

Single-line swap:
```python
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                **config.postgres.dsn_params,
            )
```

`ThreadedConnectionPool` has the same constructor signature and same `getconn` / `putconn` API. Internally it serializes access with `threading.Lock`. No call-site changes needed.

**2b. Add a regression test:** `tests/test_store_back_pool_threadsafe.py`

```python
"""Verify SentinelStoreBack uses a thread-safe pool (ThreadedConnectionPool).

Anchor: 2026-05-08 finding F2 — SimpleConnectionPool is single-thread-only
per psycopg2 docs, but the dashboard runs the pool from FastAPI thread +
APScheduler workers + boot-time daemon backfill threads.
"""
import psycopg2.pool


def test_store_back_uses_threaded_pool():
    """Pool class must be ThreadedConnectionPool (not SimpleConnectionPool)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    if store._pool is None:
        # Local dev w/o DATABASE_URL — pool is None; skip.
        import pytest
        pytest.skip("No PostgreSQL pool initialized (DATABASE_URL unset)")
    assert isinstance(store._pool, psycopg2.pool.ThreadedConnectionPool), (
        f"Pool must be ThreadedConnectionPool for thread safety; "
        f"got {type(store._pool).__name__}"
    )
```

### Key constraints
- Do NOT change `minconn=1, maxconn=5` — pool sizing is tuned for Render Pro 2 CPU / 4 GB and unrelated to this fix.
- Do NOT touch `_get_conn` / `_put_conn` / `_ensure_*` methods — the API is identical.
- Singleton path (`_get_global_instance`) MUST stay — CI guard `bash scripts/check_singletons.sh` enforces it.

### Verification
```bash
pytest tests/test_store_back_pool_threadsafe.py -v
# Plus full regression on existing pool callers:
pytest tests/ -k "store_back or pool" -v
```

---

## Fix 3: Abandoned-thread observability — counter + alarm + stack dump

### Problem
`triggers/backfill_runner.run_backfill_with_timeout` (line 24-44) starts a daemon thread, joins with timeout, and on `t.is_alive()` after timeout logs a warning and returns. The daemon thread keeps running indefinitely. If the thread is wedged inside `backfill_plaud`, it holds:
- `pg_advisory_lock(867532)` (line 656) — released only in the `finally` clause that may never run.
- `_backfill_running = True` — released only in the `finally` clause.

`check_new_plaud_recordings` line 382 reads `if _backfill_running: return` — i.e., a wedged backfill silently disables incremental polling for the rest of the Render instance lifetime. No alarm fires.

### Current state
`triggers/backfill_runner.py:40-43`:
```python
    if t.is_alive():
        logger.warning(
            f"{name} backfill exceeded {timeout_s}s timeout — moving on "
            f"(daemon thread still running in background)"
        )
```
Logger warning only. No counter, no alarm, no stack hint.

### Implementation

**3a. `triggers/backfill_runner.py` — extend `run_backfill_with_timeout`**

```python
"""Boot-time backfill runner with per-step timeout (2026-05-08).

Lives in `triggers/` (not in `outputs/dashboard.py`) so unit tests can
import it without pulling in FastAPI + the entire dashboard dependency
graph.

Background:
PR #168/PR #171 fixed Plaud's stale-refresh logic, but Plaud's boot-time
backfill never actually fires when Fireflies (legacy, silent-dead since
2026-04-11) hangs ahead of it in the sequential chain. This helper wraps
each backfill in a daemon thread with a hard timeout so neither source
can wedge the other.

2026-05-08 hardening (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1):
abandoned-thread alarm — if the daemon thread does not return within the
timeout, log a stack-dump and fire a sentinel report_failure so the
silent-pen state surfaces as a T2-down on the cockpit.
"""

import logging
import sys
import threading
import traceback

logger = logging.getLogger("sentinel.backfill")

BACKFILL_TIMEOUT_SEC = 300

# Module-level counter survives the function call but resets on Render restart.
# That's the right scope — abandoned threads can only accumulate within one
# Render instance lifetime, and we want the count cleared on each restart.
abandoned_backfill_count = 0


def run_backfill_with_timeout(name: str, fn, timeout_s: int = BACKFILL_TIMEOUT_SEC) -> None:
    """Run a backfill in a daemon thread; log + alarm + move on if it exceeds timeout.

    Daemon thread keeps running in background after timeout (so any in-flight
    DB writes complete cleanly), but the parent thread continues to the next
    backfill regardless. Failures are caught + logged non-fatally.
    """
    global abandoned_backfill_count

    def _wrap():
        try:
            fn()
        except Exception as e:
            logger.warning(f"{name} backfill failed (non-fatal): {e}")

    t = threading.Thread(target=_wrap, name=f"backfill-{name}", daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        abandoned_backfill_count += 1
        # Capture the wedged thread's stack frame for diagnostics.
        frames = sys._current_frames()
        wedged_frame = frames.get(t.ident)
        if wedged_frame is not None:
            stack_dump = "".join(traceback.format_stack(wedged_frame))
        else:
            stack_dump = "(stack frame not accessible)"
        logger.warning(
            f"{name} backfill exceeded {timeout_s}s timeout — moving on "
            f"(daemon thread still running in background; "
            f"abandoned_count={abandoned_backfill_count}). "
            f"Wedged stack:\n{stack_dump}"
        )
        # Fire sentinel alarm so the cockpit surfaces this rather than burying
        # it in Render logs. Wrapped in its own try so a sentinel-write failure
        # never crashes the chain.
        try:
            from triggers.sentinel_health import report_failure
            report_failure(
                f"{name}_backfill",
                f"abandoned thread after {timeout_s}s; advisory lock + "
                f"_backfill_running flag are now wedged for the rest of this "
                f"Render instance lifetime; restart required",
            )
        except Exception as _sh_e:
            logger.warning(f"sentinel report_failure crashed (non-fatal): {_sh_e}")
```

**3b. Tests in `tests/test_backfill_chain_order_and_timeout.py`** — add 2 new cases:

```python
def test_abandoned_thread_increments_counter_and_fires_sentinel_alarm():
    """Wedged backfill increments abandoned counter + fires sentinel report_failure.

    Anchor: 2026-05-08 finding F3 — silent-pen state where wedged daemon
    holds advisory lock + _backfill_running flag without alarm.
    """
    import triggers.backfill_runner as br

    initial = br.abandoned_backfill_count
    blocker = threading.Event()  # never set
    captured = {}

    def fake_report_failure(source, reason):
        captured["source"] = source
        captured["reason"] = reason

    with patch("triggers.sentinel_health.report_failure", fake_report_failure):
        br.run_backfill_with_timeout(
            "wedged_test", lambda: blocker.wait(timeout=30), timeout_s=1,
        )

    assert br.abandoned_backfill_count == initial + 1, (
        "abandoned_backfill_count must increment on timeout"
    )
    assert captured.get("source") == "wedged_test_backfill"
    assert "abandoned" in (captured.get("reason") or "").lower()
    blocker.set()  # release


def test_clean_completion_does_not_increment_abandoned_counter():
    """Fast backfill leaves the abandoned counter untouched."""
    import triggers.backfill_runner as br

    initial = br.abandoned_backfill_count
    br.run_backfill_with_timeout("fast_test", MagicMock(), timeout_s=5)
    assert br.abandoned_backfill_count == initial
```

### Key constraints
- `sys._current_frames()` is documented CPython-API; available since Python 3.0. Safe to use.
- Abandoned counter is module-level — intentional. Process-local resets on Render restart, which IS the recovery path for a wedged daemon.
- `report_failure` import is local (function scope) to avoid circular import (mirror Fix 1).
- The wedged-stack dump goes to logger.warning (long line; Render aggregates) — NOT to a sentinel field. Keeping the cockpit alarm scoped to a 1-line reason; the stack lives in logs for forensic dive only.
- Do NOT try to kill or restart the wedged thread — Python has no safe thread-cancellation primitive. Render restart is the recovery path.

### Verification
After deploy, force a wedged backfill via a temporary debug endpoint OR observe a real timeout in Render logs. `sentinel_health` should show:
```sql
SELECT source, last_failure_at, last_failure_reason
FROM sentinel_health WHERE source LIKE '%_backfill';
```

---

## Fix 4: Real chain test (kill the tautology)

### Problem
`tests/test_backfill_chain_order_and_timeout.py:64-86` `test_plaud_runs_before_fireflies_in_chain` calls `run_backfill_with_timeout` directly twice in test code in the order it asserts. Doesn't import `outputs/dashboard.py:_delayed_backfills`. A future rewrite of `_delayed_backfills` reversing the order — exactly the regression this test claims to guard against — would NOT fail.

### Current state
- `outputs/dashboard.py:553-579` — `_delayed_backfills` is a closure inside the `@app.on_event("startup")` handler `startup()`. Not directly importable.
- Test contains the chain order in test code, asserting on test-side state.

### Implementation

**4a. `triggers/backfill_runner.py` — extract a chain helper**

Add at the bottom of the existing module (after `run_backfill_with_timeout`):

```python
# Type alias for clarity
from typing import Callable, List, Optional


def run_boot_backfill_chain(
    plaud_token: Optional[str],
    plaud_fn: Optional[Callable[[], None]],
    fireflies_fn: Optional[Callable[[], None]],
    timeout_s: int = BACKFILL_TIMEOUT_SEC,
) -> List[str]:
    """Run boot-time backfill chain in canonical order.

    Returns the list of backfills actually invoked, in the order they ran.
    Used by `outputs/dashboard.py:_delayed_backfills` AND by regression tests
    so the canonical order lives in exactly ONE place.

    Order (load-bearing): Plaud first, Fireflies second. See PR #172 — pre
    2026-05-08 reverse order let a hung Fireflies block Plaud's startup.

    Each step is gated on its own credential / module presence; missing
    credentials silently skip that step (no exception).
    """
    invoked: List[str] = []

    if plaud_token and plaud_fn is not None:
        invoked.append("plaud")
        run_backfill_with_timeout("plaud", plaud_fn, timeout_s)

    if fireflies_fn is not None:
        invoked.append("fireflies")
        run_backfill_with_timeout("fireflies", fireflies_fn, timeout_s)

    return invoked
```

**4b. `outputs/dashboard.py:553-573` — call the helper**

Replace the body of `_delayed_backfills` with a single call:

```python
    def _delayed_backfills():
        time.sleep(60)
        logger.info("Starting delayed backfills (60s after startup)...")
        plaud_fn = None
        if config.plaud.api_token:
            from triggers.plaud_trigger import backfill_plaud
            plaud_fn = backfill_plaud
        fireflies_fn = None
        try:
            from triggers.fireflies_trigger import backfill_fireflies
            fireflies_fn = backfill_fireflies
        except ImportError:
            pass  # Fireflies module deletable; absence is fine

        invoked = run_boot_backfill_chain(
            plaud_token=config.plaud.api_token,
            plaud_fn=plaud_fn,
            fireflies_fn=fireflies_fn,
            timeout_s=BACKFILL_TIMEOUT_SEC,
        )
        logger.info(f"Boot backfill chain complete; invoked={invoked}")
```

Add the import at the top of `outputs/dashboard.py` (next to existing `from triggers.backfill_runner import (BACKFILL_TIMEOUT_SEC, run_backfill_with_timeout as _run_backfill_with_timeout)` at line 528-530):

```python
from triggers.backfill_runner import (
    BACKFILL_TIMEOUT_SEC,
    run_backfill_with_timeout as _run_backfill_with_timeout,  # legacy alias; remove if no other call sites
    run_boot_backfill_chain,
)
```

The `_run_backfill_with_timeout` alias is dead after this change — grep confirms only `_delayed_backfills` uses it (line 562 + 567). Remove the alias from the import; keep only `run_boot_backfill_chain` + `BACKFILL_TIMEOUT_SEC`. Verify with `grep -n "_run_backfill_with_timeout" outputs/dashboard.py` returning zero matches post-edit.

**4c. `tests/test_backfill_chain_order_and_timeout.py` — replace the tautology**

Delete `test_plaud_runs_before_fireflies_in_chain` (lines 64-86). Replace with:

```python
def test_run_boot_backfill_chain_runs_plaud_before_fireflies():
    """When both sources present, Plaud invocation precedes Fireflies.

    LOAD-BEARING REGRESSION: pre-2026-05-08 reversed order let a hung
    Fireflies block Plaud's boot-time backfill from ever running. This
    test exercises the SHARED helper run_boot_backfill_chain, which is
    also called by outputs/dashboard.py:_delayed_backfills — so a future
    code-path rewrite cannot silently regress the order.
    """
    from triggers.backfill_runner import run_boot_backfill_chain

    call_order = []
    plaud_fn = MagicMock(side_effect=lambda: call_order.append("plaud"))
    fireflies_fn = MagicMock(side_effect=lambda: call_order.append("fireflies"))

    invoked = run_boot_backfill_chain(
        plaud_token="present",
        plaud_fn=plaud_fn,
        fireflies_fn=fireflies_fn,
        timeout_s=5,
    )

    assert call_order == ["plaud", "fireflies"]
    assert invoked == ["plaud", "fireflies"]


def test_run_boot_backfill_chain_skips_plaud_when_token_missing():
    """No PLAUD_TOKEN → Plaud step skipped, Fireflies still runs."""
    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    fireflies_fn = MagicMock()

    invoked = run_boot_backfill_chain(
        plaud_token=None,
        plaud_fn=plaud_fn,
        fireflies_fn=fireflies_fn,
        timeout_s=5,
    )

    assert not plaud_fn.called
    assert fireflies_fn.called
    assert invoked == ["fireflies"]


def test_run_boot_backfill_chain_skips_fireflies_when_module_missing():
    """No fireflies_fn (module deleted/unimportable) → only Plaud runs."""
    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    invoked = run_boot_backfill_chain(
        plaud_token="present",
        plaud_fn=plaud_fn,
        fireflies_fn=None,
        timeout_s=5,
    )

    assert plaud_fn.called
    assert invoked == ["plaud"]
```

The `test_hung_fireflies_does_not_block_plaud_completion_pattern` (line 89-117) stays — it tests timeout isolation, orthogonal to chain order.

### Key constraints
- Do NOT change the canonical order (Plaud first). It is load-bearing per PR #172.
- The `_run_backfill_with_timeout` alias removal is mechanical; verify zero callers post-edit before commit.
- Helper signature uses `Optional[str]` + `Optional[Callable]` — the `if config.plaud.api_token` gate that lives in dashboard today moves into the helper as `if plaud_token and plaud_fn is not None`. Same semantics.

### Verification
```bash
pytest tests/test_backfill_chain_order_and_timeout.py -v
# Expected: 7 tests pass (3 timeout helper + 3 chain helper + 1 isolation pattern). Old 5-test count → new 7.
grep -n "_run_backfill_with_timeout" outputs/dashboard.py
# Expected: zero matches post-edit.
```

---

## Files Modified
- `triggers/plaud_trigger.py` — Fix 1a sentinel report calls in `backfill_plaud` (success + empty + failure terminuses).
- `triggers/fireflies_trigger.py` — Fix 1b mirror Plaud pattern in `backfill_fireflies`.
- `memory/store_back.py` — Fix 2 swap `SimpleConnectionPool` → `ThreadedConnectionPool` (line 226).
- `triggers/backfill_runner.py` — Fix 3 abandoned-thread alarm + counter; Fix 4 add `run_boot_backfill_chain`.
- `outputs/dashboard.py` — Fix 4 simplify `_delayed_backfills` to call `run_boot_backfill_chain`; remove `_run_backfill_with_timeout` import alias.
- `tests/test_backfill_chain_order_and_timeout.py` — Fix 3 + 4 expand to ~9 tests; replace tautology with helper-exercising version.
- `tests/test_store_back_pool_threadsafe.py` — NEW (Fix 2 regression test).

## Do NOT Touch
- `pipeline.run()` / Qdrant / LLM call sites — out of scope; backfill is PG-only by design (Lesson #25).
- Advisory lock IDs `867531` (Fireflies) + `867532` (Plaud) — stable contract; changing them would orphan locks held by other Render instances during deploy rollover.
- Incremental poller logic in `check_new_plaud_recordings` / `check_new_fireflies_transcripts` — already report sentinel; do NOT add another report_success there.
- `pg_try_advisory_lock` / `pg_advisory_unlock` flow — abandoned-thread alarm is observability-only; do NOT add a second-attempt-by-fresh-thread or any "release on timeout" logic. Render restart is the recovery path.
- `_backfill_running` flag semantics — kept process-local intentionally (per `BRIEF_FIREFLIES_OOM_FIX.md` §"Concurrent startup tasks").
- `BACKFILL_TIMEOUT_SEC = 300` — the test `test_default_timeout_constant_matches_documented_5_minutes` enforces this constant; do not change.

## Quality Checkpoints
1. `pytest tests/test_backfill_chain_order_and_timeout.py tests/test_store_back_pool_threadsafe.py -v` → all green (literal pytest output, not "by inspection").
2. `pytest tests/ -k "store_back or pool or backfill" -v` → no regression in pool / backfill suites.
3. `bash scripts/check_singletons.sh` → green (Fix 2 must NOT break singleton pattern).
4. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` and same for the other 4 modified Python files — clean.
5. `grep -n "_run_backfill_with_timeout" outputs/dashboard.py` → zero matches.
6. Post-deploy SQL verification (≥70s after Render redeploy completes):
   ```sql
   SELECT source, last_success_at, last_failure_at, last_failure_reason
   FROM sentinel_health WHERE source IN ('plaud', 'fireflies', 'plaud_backfill', 'fireflies_backfill')
   ORDER BY source;
   ```
   Expected: `plaud.last_success_at` advances to the redeploy time. `fireflies.last_failure_at` advances (silent-dead surfaces as loud-broken — that is the intended behavior change).
7. Render logs: search for `"Boot backfill chain complete; invoked="` — should appear once per restart with `invoked=['plaud', 'fireflies']` (or `['plaud']` if Fireflies module gone).
8. N1 nit folded into this brief from PR #170 Gate 1 (optional, NON-BLOCKING for V1 ship): N/A — PR #170 was a different brief; the heuristic-shippable risk lives there, not here.

## Verification SQL
```sql
-- Expected after deploy: plaud has fresh last_success_at; backfill source rows
-- only appear if a wedged-thread alarm has fired (rare path; usually empty).
SELECT source, last_success_at, last_failure_at, last_failure_reason
FROM sentinel_health
WHERE source IN ('plaud', 'fireflies', 'plaud_backfill', 'fireflies_backfill')
ORDER BY source;

-- Confirm Plaud ingestion is healthy (not the sentinel — actual data):
SELECT id, title, meeting_date, ingested_at
FROM meeting_transcripts
WHERE source='plaud'
ORDER BY ingested_at DESC LIMIT 5;
```

---

## Brief metadata

- **API version/endpoint:** N/A — internal-only changes. No external API contract touched.
- **Deprecation check date:** N/A — no external API.
- **Fallback note:** Sentinel health module API stable since `BRIEF_SENTINEL_HEALTH_1.md` ship; no upcoming migration. `psycopg2.pool.ThreadedConnectionPool` is psycopg2 stable surface — no upcoming deprecation.
- **Migration-vs-bootstrap DDL check:** N/A — no SQL migration. `sentinel_health` table already bootstrapped; this brief only writes to existing rows.
- **Ship gate:** literal `pytest` output required for merge; no "pass by inspection".
- **Singleton pattern:** Fix 2 changes the pool class but NOT the singleton pattern. `_get_global_instance()` factory unchanged. CI guard `scripts/check_singletons.sh` must still pass.
- **PL ship-report:** End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract".
