# BRIEF: SCHEDULER_LIVENESS_REVIVE_1 — revive the per-job liveness watchdog (it stopped firing 06:31Z and did not recover on restart)

## Context
PR #273 (`SCHEDULER_JOB_LIVENESS_1`) shipped a per-job liveness watchdog (`check_scheduler_liveness`, job id `scheduler_job_liveness`, 10-min interval). PR #274 (`JOB_LISTENER_HARDEN_1`, merged main `a3d32de` 2026-05-31 10:46Z) fixed the `_job_listener` silent-skip and is **verified working** — 13 sibling interval jobs write `scheduler_executions` rows reliably post-deploy.

But the watchdog itself is **dead**: `scheduler_job_liveness` last fired 2026-05-31 **06:31:21Z** and has **zero** execution rows since — including zero after the ~11:08Z process restart, while 13 other interval jobs resumed normally on the same clock (verified via `baker_raw_query`, db_now 11:26:05Z). AC1 of the #273 re-verify therefore **FAILS**, and AC2 ("zero false-positive STALE alerts") passes only trivially because a dead watchdog cannot alert at all. This is NOT a #274 regression — the watchdog died ~4h before today's merge.

This brief diagnoses why it stopped and hardens it so a hung run or transient DB failure can never silently kill the watchdog again.

### Surface contract: N/A — pure backend scheduler internals (APScheduler job + DB liveness scan); no user-clickable surface.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: none (main already at `a3d32de` with #274 listener fix)

---

## Fix 1: Diagnose why `scheduler_job_liveness` stopped firing (do this FIRST, report before coding Fix 2)

### Problem
`check_scheduler_liveness` ran every 10 min (06:01 / 06:11 / 06:21 / 06:31Z) then stopped permanently. 13 other interval jobs resumed writing rows at 10:50Z and continue firing now; only this job is silent. Must confirm the mechanism before patching.

### Current State
`triggers/embedded_scheduler.py:582-589`:
```python
scheduler.add_job(
    check_scheduler_liveness,
    IntervalTrigger(minutes=10),
    id="scheduler_job_liveness", name="Per-job scheduler liveness check",
    coalesce=True, max_instances=1, replace_existing=True,
)
register_expected_job("scheduler_job_liveness", 10 * 60)
```
`triggers/scheduler_liveness_sentinel.py:check_scheduler_liveness()` opens a pooled conn via `store._get_conn()`, runs one `SELECT MAX(fired_at) ... WHERE job_id=%s` per expected job (~38 jobs), then `store._put_conn(conn)` in a `finally`. **None of the DB calls carry a statement timeout.**

### Leading hypothesis (confirm or refute)
`max_instances=1` + a **hung run**. The 06:31→10:50Z window was a conn-pool exhaustion (the same condition that made `_job_listener` drop writes per #274). If a `check_scheduler_liveness` run entered `_get_conn()` or `cur.execute(...)` during that window and the socket hung with no timeout, that instance **never completes** → APScheduler skips every subsequent fire with `"maximum number of running instances reached for job scheduler_job_liveness"` (logged WARNING, no execution row, no alert). A process restart clears it only if the hang does not immediately recur.

### Implementation (diagnosis only — no code change yet)
1. Read Render logs for `srv-d7q7kvlckfvc739l2e8g` and grep for:
   - `maximum number of running instances reached for job scheduler_job_liveness`
   - any traceback in `sentinel.scheduler_liveness`
   - the startup line `Registered: scheduler_job_liveness (every 10 minutes)` — confirm it printed on the most recent boot (proves registration in the running build).
2. Report which of these is true:
   - (a) **registration missing** on latest boot → job not in jobstore;
   - (b) **"max instances reached"** warnings → hung-instance confirmed (leading hypothesis);
   - (c) **repeating traceback** → firing-but-erroring before listener write;
   - (d) none of the above → escalate, deeper APScheduler jobstore inspection.

### Verification
Paste the matching log lines (redact any secrets) + the boot timestamp. Do not proceed to Fix 2's timeout values until the mechanism is named.

---

## Fix 2: Make the watchdog un-killable (timeout + self-recovery)

### Problem
A single hung DB call must never be able to permanently silence the watchdog.

### Implementation
1. **Statement-level timeout on the watchdog's DB work.** In `check_scheduler_liveness`, after acquiring the cursor and before the per-job loop, set a Postgres statement timeout so a hung server-side call aborts instead of blocking forever:
   ```python
   cur = conn.cursor()
   cur.execute("SET LOCAL statement_timeout = '20s'")
   ```
   Keep the existing `except Exception` → `conn.rollback()` path; a timeout raises `psycopg2.errors.QueryCanceled`, which the existing handler catches and returns `skipped_reason` — the function then completes normally, so `_job_listener` records a row (watchdog stays "alive" in the data).

2. **Bound the whole run.** Wrap the body so even a non-DB hang (e.g. `_get_conn()` blocking on pool acquisition) cannot exceed the interval. Acquire the conn with the pool's existing timeout if one exists; if `_get_conn()` can block unbounded, add a guarded acquire. Confirm `_get_conn()`'s blocking behavior by reading `memory/store_back.py` before choosing the mechanism — do NOT guess.

3. **Allow a second instance as a safety valve.** Change `max_instances=1` → `max_instances=2` on the `scheduler_job_liveness` add_job ONLY. Rationale: the watchdog is idempotent (read-only scan + dedupe-bucketed alerts), so a brief overlap is harmless, and it means one hung run cannot block the next tick. Keep `coalesce=True`. Do NOT change `max_instances` on any other job.

4. **`misfire_grace_time`.** Add `misfire_grace_time=300` to the `scheduler_job_liveness` add_job so a tick delayed by a slow prior run still runs rather than being dropped.

### Key Constraints
- Touch ONLY the `scheduler_job_liveness` add_job block and `check_scheduler_liveness()` internals. Do NOT alter any other job's `max_instances`, interval, or trigger.
- Preserve the `COLD_START_GRACE_SECONDS` (900s) cold-start skip and `reset_cold_start_anchor()` semantics — they are correct.
- The watchdog must ALWAYS return a dict (never raise) so EVENT_JOB_EXECUTED fires and `_job_listener` records a `scheduler_job_liveness` row every tick — that self-row is what proves the watchdog is alive.
- Keep all DB access fault-tolerant: `conn.rollback()` in except, `store._put_conn(conn)` in finally (already present).

### Verification
- Local: import `check_scheduler_liveness`, monkeypatch the cursor to sleep > timeout, assert the function returns a dict with a `skipped_reason` containing the cancel/timeout rather than hanging.
- Local: assert a normal run returns `{"checked": N, ...}` and never raises on a missing/empty `scheduler_executions`.
- `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"` + same for the sentinel.
- `pytest` for any existing scheduler-liveness tests (the #273 suite — 42 tests). All must pass on a literal run.

---

## Fix 3: Startup self-bootstrap assertion (fail loud on silent unregister) — per deputy #1441

### Problem
If mechanism (a) is the cause — the watchdog silently absent from the jobstore on a boot — nothing surfaces it today. A self-monitor that itself fails to register is the worst failure mode (it cannot report its own absence).

### Implementation
After the full register loop in `start_scheduler()` (i.e. after all `add_job(...)` calls), assert the watchdog is actually present in the live jobstore and fail loud at startup if not:
```python
if "scheduler_job_liveness" not in {j.id for j in scheduler.get_jobs()}:
    raise RuntimeError(
        "scheduler_job_liveness failed to register — liveness watchdog absent; "
        "refusing to start blind"
    )
logger.info("Self-bootstrap OK: scheduler_job_liveness present in jobstore")
```
Place AFTER `scheduler.start()` (jobs are only enumerable once the scheduler is started, depending on jobstore) — verify by reading the actual `start_scheduler()` ordering before placing; if `get_jobs()` is valid pre-start in this APScheduler version, place after the register loop instead. Do NOT guess the ordering — read it.

### Key Constraints
- Assert ONLY `scheduler_job_liveness` presence (this is the self-monitor); do not gate startup on every job.
- The raise must be reachable on boot, not swallowed by a broad `try/except` around scheduler init — confirm the surrounding handler does not catch-and-continue.

### Verification
- Local: temporarily comment out the watchdog `add_job` → assert `start_scheduler()` raises `RuntimeError`. Restore.
- Boot log shows `Self-bootstrap OK: scheduler_job_liveness present in jobstore`.

---

## Files Modified
- `triggers/scheduler_liveness_sentinel.py` — statement_timeout + bounded acquire in `check_scheduler_liveness`.
- `triggers/embedded_scheduler.py` — `scheduler_job_liveness` add_job: `max_instances=2`, `misfire_grace_time=300` (this job only); startup self-bootstrap assertion after the register loop (Fix 3).

## Do NOT Touch
- Any other `add_job(...)` block — no other job's instances/interval/trigger changes.
- `_job_listener` / `get_listener_drop_counts` — #274 already hardened these; out of scope.
- `register_expected_job`, `_TIER_OVERRIDES`, tolerance/grace constants — correct as-is.

## Quality Checkpoints
1. After deploy, confirm `Registered: scheduler_job_liveness` prints on boot.
2. Within ~25 min of deploy (one interval past the 15-min cold-start grace), confirm a `scheduler_job_liveness` row with `fired_at` after deploy exists.
3. Confirm the watchdog now self-records every 10 min for 3 consecutive ticks.
4. Confirm no NEW false-positive `SCHEDULER JOB STALE` alerts for jobs that are actually firing (the #273 AC2).
5. Render restart survival: the watchdog resumes within one interval + grace after any restart.

## Verification SQL
```sql
-- AC1: watchdog self-records again (run >25 min after deploy)
SELECT job_id, fired_at, status
FROM scheduler_executions
WHERE job_id = 'scheduler_job_liveness'
ORDER BY fired_at DESC
LIMIT 5;

-- AC2: no false-positive STALE alerts for jobs that ARE firing, post-deploy
SELECT id, source, created_at, LEFT(title, 80) AS title
FROM alerts
WHERE source = 'scheduler_job_liveness'
  AND created_at > '2026-05-31T12:00:00+00:00'
ORDER BY created_at DESC
LIMIT 20;
```

## Gate plan
Codex pre-review (read-only DB + Render log access) verifies the Fix-1 diagnosis against actual logs before B-code dispatch → fold → b-code build → G1 AH1 fold + G2 /security-review + G3 deputy → merge → re-run AC1/AC2.
