---
brief: JOB_LISTENER_HARDEN_1
to: b1
from: lead
authored: 2026-05-31
target_repo: baker-master
estimated_time: ~2h
complexity: Low-Medium
codex_pre_review: PENDING (bus to fire same turn)
parent_codex_thread: deputy bus #1418 (PR #273 AC1 FAIL — scheduler_job_liveness has 0 rows in scheduler_executions; root cause = `_job_listener` early-returns silently on `if not conn`)
director_authorization: 2026-05-31 chat — "go" (after PINNED top-pick recommendation)
anchor_chat: Director 2026-05-31 — resume after PR #273 (SCHEDULER_JOB_LIVENESS_1) merged 522775f; deputy probe found `scheduler_job_liveness` AND `slack_poll` fired (Render logs prove it) but zero rows landed in `scheduler_executions`. Root cause traced to `triggers/embedded_scheduler.py::_job_listener` line 49-50 silent early-return when `store._get_conn()` returns None. No log, no retry, no counter — pure swallow. Pre-existing bug, not introduced by PR #273.
---

# BRIEF: JOB_LISTENER_HARDEN_1 — Stop the silent-skip in `_job_listener` (DB pool exhaustion swallow)

## Context

### Surface contract: N/A — pure backend observability fix. No clickable UI, no new dashboard panel, no email/Slack send. Outputs land in (a) existing `logger.warning` stream (Render logs), (b) existing `scheduler_executions` table (no schema change), (c) one additive line appended to `triggers/scheduler_liveness_sentinel.py` alert body (existing alerts table, existing rendering).

`triggers/embedded_scheduler.py::_job_listener` (line 24-76) is APScheduler's listener registered for `EVENT_JOB_EXECUTED | EVENT_JOB_ERROR` (registered at line 1642). On every job fire, it appends a row to `scheduler_executions` (table defined at `memory/store_back.py:859`). SCHEDULER_JOB_LIVENESS_1 (PR #273, merged 522775f) relies on this table to detect silent per-job death.

**Failure surfaced on 2026-05-30 by deputy bus #1418:**

After PR #273 deploy, `scheduler_job_liveness` itself fired at 15:53:26Z (Render log: "Job scheduler_job_liveness completed successfully") yet `SELECT COUNT(*) FROM scheduler_executions WHERE job_id='scheduler_job_liveness'` returned 0. `slack_poll` at the same timestamp also had no rows. Other jobs (`scheduler_heartbeat`, `kbl_bridge_tick`) did land rows in the same window.

**Root cause** — `triggers/embedded_scheduler.py` lines 47-50 today:

```python
store = SentinelStoreBack._get_global_instance()
conn = store._get_conn()
if not conn:
    return  # SILENT. No log. No retry. No counter.
```

`store._get_conn()` (`memory/store_back.py:316-326`) returns `None` when (a) the pool failed to initialize, or (b) `pool.getconn()` raised (logged at store_back side but the listener has no visibility). The pool is `ThreadedConnectionPool(minconn=1, maxconn=5)` shared across the FastAPI thread, ~40 APScheduler workers, the boot-time daemon backfill thread, and Cortex cycle threads. Saturation under spike is plausible; transient None is plausible.

When `_job_listener` hits the silent-skip, the row is permanently lost — APScheduler does not retry listener callbacks. The downstream consequence is that PR #273's liveness sentinel cannot distinguish "job didn't fire" from "job fired but listener dropped the write." Today the sentinel will (correctly per its own contract) alert on the missing row, but the operator has no signal that this is a listener-drop class vs a real job-death class.

**Out of scope (V1):**
- Switching `_get_conn()` to a non-pool path (direct `psycopg2.connect`) — pool exists for capacity reasons; bypassing it during spike risks worse exhaustion. Defer.
- Increasing `maxconn` from 5 — orthogonal capacity tuning. Defer to a separate brief.
- Persistent (DB-backed) listener-drop audit table — in-memory counter is sufficient for V1 since drops are operator-diagnostic, not Director-visible. Defer to V2.

**Anchor:** deputy bus #1418 (2026-05-30 16:06:54Z) — "AC1 FAIL — `scheduler_job_liveness` has 0 rows in `scheduler_executions`. Render logs prove job fired at 15:53:26Z. Same timestamp also missing `slack_poll`. Pre-existing infra bug, not introduced by PR #273."

## Estimated time: ~2h
## Complexity: Low-Medium
## Prerequisites: PR #273 (SCHEDULER_JOB_LIVENESS_1, merged 522775f) deployed.

---

## Fix 1: Log + count silent conn=None drops

### Problem
Line 49-50 silently returns on `conn is None`. Operator has zero signal this is happening; the only evidence today is downstream alerts from `scheduler_liveness_sentinel`.

### Current state
`triggers/embedded_scheduler.py:24-76` — `_job_listener` is the only consumer of `_get_conn()` in this file. `scheduler_executions` rows are written exclusively from here. `_listener_drop_count` / `get_listener_drop_counts` do not exist yet (`grep -n "_listener_drop_count" triggers/ memory/` returns nothing).

### Implementation

**Step 1.1** — Add module-level drop counter at top of `triggers/embedded_scheduler.py`. Insert AFTER existing imports (after the `Optional` import at line 10) and BEFORE the `_scheduler` declaration at line 20:

```python
import threading

# JOB_LISTENER_HARDEN_1: in-memory per-job-id counter of silent listener drops
# (conn-pool exhaustion / init-failure). Read by scheduler_liveness_sentinel
# alert body to differentiate "job didn't fire" vs "listener dropped write".
# Process-local; replica-local; resets on Render restart. Acceptable for V1.
_listener_drop_count: dict[str, int] = {}
_listener_drop_lock = threading.Lock()


def get_listener_drop_counts() -> dict[str, int]:
    """Snapshot of per-job listener drop counts since process start.
    Returns a shallow copy so callers cannot mutate the live dict.
    """
    with _listener_drop_lock:
        return dict(_listener_drop_count)


def _record_listener_drop(job_id: str) -> None:
    """Thread-safe increment of drop counter + structured WARNING log."""
    with _listener_drop_lock:
        _listener_drop_count[job_id] = _listener_drop_count.get(job_id, 0) + 1
        count = _listener_drop_count[job_id]
    logger.warning(
        f"JOB_LISTENER_SILENT_SKIP job_id={job_id} reason=conn_pool_none "
        f"process_drop_count={count}"
    )
```

**Step 1.2** — Replace lines 47-50 of `_job_listener`. Today:

```python
store = SentinelStoreBack._get_global_instance()
conn = store._get_conn()
if not conn:
    return
```

After Fix 1 (Fix 2 retry layered next, final shape in §Fix 2 Step 2.1):

```python
store = SentinelStoreBack._get_global_instance()
conn = store._get_conn()
if not conn:
    _record_listener_drop(event.job_id)
    return
```

### Key constraints
- Counter dict must be module-level so it survives across listener fires (process-local).
- Lock-guarded — BackgroundScheduler runs jobs in a worker pool; listener can be invoked concurrently from multiple workers.
- Logger name stays `sentinel.embedded_scheduler` (existing logger at line 18). No new logger.
- Structured log line is grep-friendly on Render: `JOB_LISTENER_SILENT_SKIP job_id=X reason=Y process_drop_count=N`.

### Verification (Fix 1)
- `grep -n "_listener_drop_count" triggers/embedded_scheduler.py` returns the new dict + helpers.
- `grep -n "JOB_LISTENER_SILENT_SKIP" triggers/embedded_scheduler.py` returns the WARNING template.
- Test 1.1 (below) passes on a literal pytest run.

---

## Fix 2: One retry on transient conn=None

### Problem
Pool exhaustion is often transient (race between pool capacity refresh and listener fire). Failing on the first None is needlessly fragile.

### Current state
Today there is no retry — first None → return.

### Implementation

**Step 2.1** — Insert retry between the first `_get_conn()` and the drop-record. Final shape of `_job_listener` lines 46-50 + retry block:

```python
store = SentinelStoreBack._get_global_instance()
conn = store._get_conn()
if not conn:
    # JOB_LISTENER_HARDEN_1: brief sleep + one retry — transient pool
    # exhaustion is common under spike (40+ jobs + FastAPI + Cortex share
    # maxconn=5 pool). 100ms is well below APScheduler misfire_grace_time
    # (300s) so listener cannot back-pressure the scheduler.
    import time
    time.sleep(0.1)
    conn = store._get_conn()
    if not conn:
        _record_listener_drop(event.job_id)
        return
```

### Key constraints
- 100ms hard limit — DO NOT loop more than once. If the pool is genuinely saturated for >100ms, retrying indefinitely makes contention worse.
- `import time` may be hoisted to top of file at b1's discretion (currently absent — `grep -n "^import time" triggers/embedded_scheduler.py` returns nothing). Keep `import time` inline if cleaner, since this is the only call site.
- Sleep + retry preserves the listener's "must not crash scheduler" contract — still wrapped by outer `try/except` at line 73-76.

### Verification (Fix 2)
- Test 2.1 (transient None then success): retry path returns a real conn, INSERT executes, counter NOT incremented.
- Test 2.2 (persistent None): both `_get_conn()` calls return None, counter incremented to 1, WARNING logged.

---

## Fix 3: Surface drop counts in liveness-sentinel alert body

### Problem
When `triggers/scheduler_liveness_sentinel.check_scheduler_liveness()` emits a stale-job alert, the operator cannot tell whether the job genuinely stopped firing or whether the listener dropped writes. Today's alert body says "investigate Render logs"; we can do better.

### Current state
`triggers/scheduler_liveness_sentinel.py` alert-emit block lives at lines 218-251 (the `try` block that calls `st.create_alert(...)`). Two branches construct `body`: line 228 (age is None) and line 234 (age + window). Neither today references listener-drop state.

### Implementation

**Step 3.1** — At the top of `triggers/scheduler_liveness_sentinel.py::check_scheduler_liveness` alert-emit `try` block (around line 218, immediately after `st = store` and before the `for entry in summary["stale"]:` loop), add:

```python
# JOB_LISTENER_HARDEN_1: surface listener-drop hint in alert body
try:
    from triggers.embedded_scheduler import get_listener_drop_counts
    drop_counts = get_listener_drop_counts()
except Exception:
    drop_counts = {}
```

**Step 3.2** — Inside the for-loop, after `body` is constructed (after line 238 in the existing file), append:

```python
drop_n = drop_counts.get(job_id, 0)
if drop_n > 0:
    body += (
        f"\n\nNOTE: _job_listener silently dropped {drop_n} write(s) for "
        f"this job this process. The job may have fired; the listener could "
        f"not persist. Check Render logs for JOB_LISTENER_SILENT_SKIP."
    )
```

This append happens for BOTH branches (the `age is None` branch and the staleness branch) because it runs after the `if age is None: body = ... else: body = ...` block.

### Key constraints
- Read-only call (`get_listener_drop_counts()`) — sentinel must never block on the drop counter; lock contention is microseconds.
- Hint is additive; existing alert body wording is preserved verbatim.
- Process-local counter caveat: if a DIFFERENT replica's listener dropped the write, this replica's sentinel will not show the count. Acceptable for V1 — Render Standard plan single-replica is current config. Document the caveat in the inserted code comment (already in the snippet above via "this process" wording).
- Do NOT add a `from triggers.embedded_scheduler import ...` at module-top of the sentinel — local import inside the `try` avoids a circular-import risk if the sentinel is ever imported before `embedded_scheduler`.

### Verification (Fix 3)
- Test 3.1 (drop count > 0): patch `get_listener_drop_counts()` to return `{"waha_session_poll": 3}`. Assert alert body contains `JOB_LISTENER_SILENT_SKIP` AND `dropped 3 write(s)`.
- Test 3.2 (drop count 0): assert body does NOT contain `JOB_LISTENER_SILENT_SKIP` substring.

---

## Tests (new file: `tests/test_job_listener_harden.py`)

Standard pytest. Mock `SentinelStoreBack._get_global_instance()` and a synthetic `apscheduler.events.JobExecutionEvent`. Four tests:

1. **`test_silent_skip_logs_and_counts`** — Patch `_get_conn()` to return None on both calls. Fire `_job_listener` twice. Assert `get_listener_drop_counts()["test_job"] == 2` AND `caplog` contains two WARNINGs matching `JOB_LISTENER_SILENT_SKIP job_id=test_job`.

2. **`test_retry_succeeds_on_transient_none`** — Patch `_get_conn()` to return None on first call, a stub conn on second. The stub conn must provide `.cursor()` returning a stub with `.execute()` + `.close()`, and `.commit()`. Fire `_job_listener`. Assert `get_listener_drop_counts()` returns `{}` (or job_id absent) AND stub cursor `.execute()` was called once with INSERT SQL.

3. **`test_retry_exhausts_records_drop`** — Patch `_get_conn()` to return None on both calls. Fire `_job_listener`. Assert `get_listener_drop_counts()["test_job"] == 1` AND one WARNING logged.

4. **`test_alert_body_includes_drop_hint`** — In `triggers/scheduler_liveness_sentinel.py`, mock `get_listener_drop_counts()` to return `{"waha_session_poll": 3}`. Construct a stale-job summary entry for `waha_session_poll` (age=900s, staleness_window=600s, tier=1). Mock `store.create_alert(...)`. Run `check_scheduler_liveness()` against a stub DB that yields one stale row. Assert `create_alert` was called with a body containing both substrings: `JOB_LISTENER_SILENT_SKIP` AND `dropped 3 write(s)`.

**Test runner:** `pytest tests/test_job_listener_harden.py -v` — literal output mandatory in ship report. NO "by inspection."

**Test reset hook:** each test must clear `_listener_drop_count` at setup (use `pytest` fixture: `triggers.embedded_scheduler._listener_drop_count.clear()`). Process-local counter would otherwise leak between tests.

---

## Acceptance criteria

**AC1 — Listener silent-skip is no longer silent (operator-verifiable in Render logs).**
After deploy of this brief, run any one of:
- (a) Wait one full `scheduler_job_liveness` interval (10 min). Query `SELECT COUNT(*) FROM scheduler_executions WHERE job_id='scheduler_job_liveness' AND fired_at > NOW() - INTERVAL '15 minutes'`; result MUST be ≥ 1 (listener wrote the row). OR:
- (b) If conn-pool exhausts in the window, Render logs MUST contain at least one `JOB_LISTENER_SILENT_SKIP job_id=<X> reason=conn_pool_none process_drop_count=<N>` line — proving the silent-skip path is now observable.
Pass criterion: at least one of (a) or (b) is verifiable within 30 minutes of deploy. Today (pre-fix), neither (a) nor (b) is true — the bug is fully silent.

**AC2 — PR #273 AC1 re-runnable.**
After JOB_LISTENER_HARDEN_1 ships AND ≥ 1 full `scheduler_job_liveness` interval has elapsed post-deploy, the deputy AC1 query from bus #1418 — `SELECT MAX(fired_at) FROM scheduler_executions WHERE job_id='scheduler_job_liveness'` — MUST return a timestamp within the last 15 minutes. This re-validates SCHEDULER_JOB_LIVENESS_1.

**AC3 — pytest green (literal output, not "by inspection").**
`pytest tests/test_job_listener_harden.py -v` — all 4 new tests pass on a literal run. Paste the literal pytest tail (≥ 4 PASSED) into the ship report. NO "pass by inspection."

---

## Files Modified
- `triggers/embedded_scheduler.py` — add `_listener_drop_count` dict + `_listener_drop_lock` + `get_listener_drop_counts()` + `_record_listener_drop()` (Fix 1, ~25 LOC). Replace `_job_listener` lines 47-50 with retry + drop-record (Fix 2, ~10 LOC).
- `triggers/scheduler_liveness_sentinel.py` — local import of `get_listener_drop_counts` inside alert-emit `try` block + append drop-hint to `body` for both branches (Fix 3, ~10 LOC).
- `tests/test_job_listener_harden.py` — NEW; ~120 LOC; 4 tests covering Fixes 1/2/3.

No DB migration. No schema change. No requirements pin update. No new endpoint. No new env var.

## Do NOT Touch
- `memory/store_back.py::_get_conn` / `_put_conn` — pool semantics unchanged.
- `memory/store_back.py:859` `scheduler_executions` CREATE TABLE — schema unchanged.
- `triggers/scheduler.py` — old standalone scheduler, never runs on Render (file docs line 4-5).
- `triggers/scheduler_liveness_sentinel.py` registry / cold-start / tier logic — only the alert-body construction is touched.
- `triggers/audit_sentinel.py` — orthogonal sentinel (single-job `ai_head_weekly_audit`), out of scope.
- ALL existing `scheduler_executions` rows — read-only from this brief's code paths.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"` returns 0.
2. `python3 -c "import py_compile; py_compile.compile('triggers/scheduler_liveness_sentinel.py', doraise=True)"` returns 0.
3. `pytest tests/test_job_listener_harden.py -v` literal output: 4 PASSED.
4. `grep -n "_listener_drop_count\|JOB_LISTENER_SILENT_SKIP\|get_listener_drop_counts" triggers/embedded_scheduler.py` returns ≥ 6 matches.
5. `grep -n "JOB_LISTENER_SILENT_SKIP\|dropped.*write" triggers/scheduler_liveness_sentinel.py` returns ≥ 2 matches.
6. Manual smoke (post-deploy, AH1 lane): tail Render logs 10 min after deploy. Expect either zero `JOB_LISTENER_SILENT_SKIP` lines (pool healthy) OR clear structured WARNING lines naming job_id + count. NO silent gaps.

## Verification SQL
```sql
-- AC1 (a): listener wrote scheduler_job_liveness row in last 15 min
SELECT COUNT(*) FROM scheduler_executions
WHERE job_id='scheduler_job_liveness'
  AND fired_at > NOW() - INTERVAL '15 minutes'
LIMIT 1;
-- Expect: 1 (post-deploy, after one full 10-min cycle elapsed)

-- AC2: re-verify PR #273 AC1
SELECT job_id, MAX(fired_at) AS last_fire
FROM scheduler_executions
WHERE job_id IN ('scheduler_job_liveness','slack_poll','waha_session_poll')
GROUP BY job_id
LIMIT 10;
-- Expect: all three rows present, last_fire within last 1× interval per job
```

## Ship contract

Standard b1 flow:
1. Branch `b1/job-listener-harden-1` off main HEAD (522775f or later).
2. Implement Fix 1 → Fix 2 → Fix 3 in order; literal `pytest tests/test_job_listener_harden.py -v` MUST pass.
3. Commit with subject `JOB_LISTENER_HARDEN_1: stop silent-skip in _job_listener (#<PR>)`.
4. Open PR; tag for `/security-review` (Tier-A). AH1 fold gate G1; `/security-review` gate G2; deputy gate G3.
5. Ship report MUST include: PR # + commit hash + literal pytest tail + post-deploy AC1 (a) or (b) verdict.
6. Same-turn bus-post `ship/job-listener-harden-1` to `lead`.
