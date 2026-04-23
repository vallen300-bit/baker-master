# BRIEF: AUDIT_SENTINEL_1 — First-fire observability for `ai_head_weekly_audit`

## Context

`ai_head_weekly_audit` first-fires **Mon 2026-04-27 09:00 UTC** (3.5d from now). Today there is **no external observability** on any APScheduler job — they can silently fail in 4 modes (see Research artefact §Problem at `_ops/ideas/2026-04-23-first-fire-observability.md`):

1. Scheduler not running (env gate / deploy wedge)
2. Job raises uncaught exception (logged only, no alert)
3. Job fires but inner logic short-circuits — indistinguishable from clean run
4. Render rolling-deploy misses the cron window

**Without this brief, a silent first-fire miss is undetectable.** Director's DM gets nothing → drift detection silently dies.

**Ship deadline:** Sun 2026-04-26 23:59 UTC (24h margin before first fire).

**Ratified Research artefact (all 5 Part-G calls):** `/Users/dimitry/baker-vault/_ops/ideas/2026-04-23-first-fire-observability.md` (status=ratified, ratified_at=2026-04-23). Phase 1 scope only. Phase 2 (generalized decorator pattern across 12+ jobs) deferred post-Cortex-3T M0.

## Estimated time: ~1.5–2h
## Complexity: Medium
## Prerequisites: PR #44 (`ai_head_weekly_audit` job) + PR #46 (SentinelStoreBack singleton hotfix) — both merged.

---

## Fix/Feature 1: `scheduler_executions` PG table + DDL bootstrap

### Problem

No persistent record of scheduler job executions. APScheduler's `EVENT_JOB_EXECUTED` / `EVENT_JOB_ERROR` listeners currently log to stdout only (`_job_listener` at `triggers/embedded_scheduler.py:23-31`). Logs rotate; no durable audit trail; impossible to answer "did job X fire at time Y?" post-hoc.

### Current State

- **Listener registered once** at `triggers/embedded_scheduler.py:951`: `_scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)` — extends, don't replace.
- **EVENT_JOB_ERROR / EVENT_JOB_EXECUTED imported** at `triggers/embedded_scheduler.py:16` — no new imports needed.
- **Template for DDL bootstrap:** `_ensure_ai_head_audits_table` at `memory/store_back.py:502-539` — copy pattern exactly, including rollback-on-exception and connection return in `finally`.
- **Bootstrap wiring:** `__init__` at `memory/store_back.py:148` calls `self._ensure_ai_head_audits_table()` — add a sibling call for the new table.
- **Singleton rule (enforced by `scripts/check_singletons.sh` pre-push hook, per PR #46):** use `SentinelStoreBack._get_global_instance()`. Never `SentinelStoreBack()` direct.

**DDL drift trap pre-flight (per MEMORY.md):** ran `grep -rn "scheduler_executions" --include="*.py" --include="*.sql"` from repo root. **Zero hits.** No pre-existing bootstrap to collide with. Safe to add.

### Implementation

**Step 1 — `memory/store_back.py` — add new bootstrap method** (mirror `_ensure_ai_head_audits_table`):

```python
def _ensure_scheduler_executions_table(self):
    """BRIEF_AUDIT_SENTINEL_1: Persistent log of APScheduler job executions.

    Populated by the extended embedded_scheduler._job_listener on every
    EVENT_JOB_EXECUTED / EVENT_JOB_ERROR. One row per fire. Used by
    ai_head_audit_sentinel (Mon 10:00 UTC) to verify weekly audit fired.

    Retention: 90-day delete in nightly cleanup (Phase 2 brief; not this one).
    """
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_executions (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                status TEXT NOT NULL,
                error_msg TEXT,
                outputs_summary JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduler_executions_job_fired "
            "ON scheduler_executions(job_id, fired_at DESC)"
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure scheduler_executions table: {e}")
    finally:
        self._put_conn(conn)
```

**Status values** (enum convention, no DB constraint — keep flexible):
- `"executed"` — clean EVENT_JOB_EXECUTED, no exception
- `"error"` — EVENT_JOB_ERROR fired, `error_msg` populated
- `"alerted"` — sentinel self-write when it posts a Slack alert (dedupe anchor; see Fix/Feature 3)

**Step 2 — Wire in `__init__`** — add right after `self._ensure_ai_head_audits_table()` call at line 148:

```python
self._ensure_scheduler_executions_table()
```

### Key Constraints

- DDL uses `CREATE TABLE IF NOT EXISTS` — idempotent, safe on every startup.
- Index on `(job_id, fired_at DESC)` — sentinel's main query pattern.
- `outputs_summary` is JSONB so future Phase 2 decorator can stash `expected_outputs` payload without schema change.
- `conn.rollback()` on exception per `.claude/rules/python-backend.md`.
- `finally: self._put_conn(conn)` — connection pool return.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` — zero errors.
2. Fresh Postgres table inspection (add to test): `SELECT table_name FROM information_schema.tables WHERE table_name='scheduler_executions'` — returns 1 row.
3. Column list matches: `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='scheduler_executions'` — expect 7 cols (`id`, `job_id`, `fired_at`, `completed_at`, `status`, `error_msg`, `outputs_summary`).

---

## Fix/Feature 2: Extend `_job_listener` to write execution rows

### Problem

Current listener is log-only (`triggers/embedded_scheduler.py:23-31`). Every APScheduler event needs a durable row in `scheduler_executions` so the sentinel can verify `ai_head_weekly_audit` (and every future job) actually ran.

### Current State

```python
# triggers/embedded_scheduler.py:23-31
def _job_listener(event):
    """Log job execution results."""
    if event.exception:
        logger.error(
            f"Job {event.job_id} failed: {event.exception}",
            exc_info=event.traceback,
        )
    else:
        logger.info(f"Job {event.job_id} completed successfully")
```

### Implementation

**Extend (do NOT replace) `_job_listener`:**

```python
def _job_listener(event):
    """Log job execution results AND persist to scheduler_executions.

    BRIEF_AUDIT_SENTINEL_1: every EVENT_JOB_EXECUTED / EVENT_JOB_ERROR
    writes a row to scheduler_executions. The sentinel uses this table
    to verify ai_head_weekly_audit (and, Phase 2, every other job) fired
    in its expected window.

    DB write is wrapped in try/except — scheduler must never crash on
    observability side-effect. Silent log + continue on DB unavailable.
    """
    # Existing log behavior — KEEP as-is
    if event.exception:
        logger.error(
            f"Job {event.job_id} failed: {event.exception}",
            exc_info=event.traceback,
        )
    else:
        logger.info(f"Job {event.job_id} completed successfully")

    # New: persist to scheduler_executions (fault-tolerant)
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            status = "error" if event.exception else "executed"
            error_msg = str(event.exception)[:1000] if event.exception else None
            cur.execute(
                """
                INSERT INTO scheduler_executions
                    (job_id, fired_at, completed_at, status, error_msg)
                VALUES (%s, %s, NOW(), %s, %s)
                """,
                (event.job_id, event.scheduled_run_time, status, error_msg),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"scheduler_executions write failed for {event.job_id}: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        # Catastrophic failure (import, singleton, etc.) — log and continue.
        # Scheduler must not crash because of observability.
        logger.warning(f"_job_listener DB path failed ({event.job_id}): {e}")
```

### Key Constraints

- **Singleton rule:** `SentinelStoreBack._get_global_instance()` — enforced by `scripts/check_singletons.sh` pre-push hook. Direct `SentinelStoreBack()` call will fail the push.
- **Two-level try/except:** outer catches import/singleton failure; inner catches DB failure. Both logger.warning + continue.
- **Listener is synchronous on APScheduler executor thread** — `conn.commit()` is fast (indexed insert), acceptable.
- **Error message truncated to 1000 chars** — avoids bloat on stack traces; full stack is already in logger.error via `exc_info=event.traceback`.
- **`event.scheduled_run_time`** — APScheduler attribute; this is `fired_at`. `completed_at = NOW()` in DB (since listener fires at completion).

### Verification

1. Unit test with mocked scheduler event: call `_job_listener(event)` with `job_id="test_job"`, `exception=None`, `scheduled_run_time=datetime.now(tz=timezone.utc)`. Assert row exists with status=`"executed"`.
2. Unit test with `exception=ValueError("boom")`. Assert row exists with status=`"error"`, `error_msg` starts with `"boom"`.
3. Unit test with DB unavailable (mock `_get_conn` → `None`). Assert no exception raised; assert logger.warning called.

---

## Fix/Feature 3: `ai_head_audit_sentinel` cron + Slack alert path

### Problem

Need a weekly sentinel that fires 1h after `ai_head_weekly_audit` and verifies both (a) a row landed in `ai_head_audits` and (b) a row landed in `scheduler_executions` for `job_id='ai_head_weekly_audit'`. Either missing → Slack DM.

### Current State

- **Registration pattern precedent** at `triggers/embedded_scheduler.py:632-644` (`AI_HEAD_AUDIT_ENABLED` env gate). Copy shape.
- **Job wrapper pattern** at `triggers/embedded_scheduler.py:733-751` (`_ai_head_weekly_audit_job`) — lazy import, logger.warning on raise. Copy shape.
- **Slack helper verified:** `outputs/slack_notifier.post_to_channel(channel_id: str, text: str) -> bool` at `outputs/slack_notifier.py:111`. Plain text only, returns `False` on failure (non-fatal).

### Implementation

**Step 1 — Add cron registration** in `_register_jobs` (sibling of `ai_head_weekly_audit` block, immediately after line 644):

```python
    # BRIEF_AUDIT_SENTINEL_1: sentinel for ai_head_weekly_audit first-fire
    # observability. Fires Mon 10:00 UTC (1h after audit). Verifies that
    # (a) a row landed in ai_head_audits today, and (b) a row landed in
    # scheduler_executions for job_id='ai_head_weekly_audit'. Either
    # missing → Slack DM to D0AFY28N030. Env gate AI_HEAD_AUDIT_SENTINEL_ENABLED
    # (default true).
    _sentinel_enabled = _os.environ.get(
        "AI_HEAD_AUDIT_SENTINEL_ENABLED", "true"
    ).lower()
    if _sentinel_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _ai_head_audit_sentinel_job,
            CronTrigger(day_of_week="mon", hour=10, minute=0, timezone="UTC"),
            id="ai_head_audit_sentinel",
            name="AI Head weekly audit sentinel (Monday 10:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: ai_head_audit_sentinel (Mon 10:00 UTC)")
    else:
        logger.info("Skipped: ai_head_audit_sentinel (AI_HEAD_AUDIT_SENTINEL_ENABLED=false)")
```

**Step 2 — Add sentinel job function** (sibling of `_ai_head_weekly_audit_job`, after line 751):

```python
def _ai_head_audit_sentinel_job():
    """APScheduler wrapper: Monday 10:00 UTC sentinel for ai_head_weekly_audit.

    BRIEF_AUDIT_SENTINEL_1. Runs the sentinel check logic; swallows top-
    level exceptions as WARN so a single bad week doesn't knock out the
    scheduler. Dedupe: checks scheduler_executions for prior 'alerted'
    row in last 24h for this sentinel's own job_id before posting again.
    """
    try:
        from triggers.audit_sentinel import run_sentinel_check
    except Exception as e:
        logger.error("ai_head_audit_sentinel: import failed: %s", e)
        return
    try:
        result = run_sentinel_check()
        logger.info("ai_head_audit_sentinel: %s", result)
    except Exception as e:
        logger.warning("ai_head_audit_sentinel: run raised: %s", e)
```

**Step 3 — NEW file `triggers/audit_sentinel.py`** with the check logic:

```python
"""AI Head weekly audit sentinel — BRIEF_AUDIT_SENTINEL_1.

Runs Mon 10:00 UTC (1h after ai_head_weekly_audit). Verifies both:
  (a) a row landed in ai_head_audits today
  (b) a row landed in scheduler_executions for
      job_id='ai_head_weekly_audit' with status='executed' today

Either missing → Slack DM to D0AFY28N030 (Director substrate channel).

Dedupe: before alerting, checks scheduler_executions for an 'alerted'
row from this sentinel in the last 24h. If present, no double-alert.
Otherwise, alert + write own 'alerted' row for dedupe anchor.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger("sentinel.audit_sentinel")

DIRECTOR_DM_CHANNEL = "D0AFY28N030"


def run_sentinel_check() -> Dict[str, Any]:
    """Return {'audit_found': bool, 'execution_found': bool, 'alerted': bool}."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.warning("sentinel: DB unavailable — skipping check")
        return {"audit_found": None, "execution_found": None, "alerted": False,
                "reason": "db_unavailable"}

    try:
        cur = conn.cursor()

        # (a) Did the audit actually write a row?
        cur.execute(
            "SELECT COUNT(*) FROM ai_head_audits "
            "WHERE ran_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        audit_count = cur.fetchone()[0]
        audit_found = audit_count > 0

        # (b) Did APScheduler record the execution?
        cur.execute(
            "SELECT COUNT(*) FROM scheduler_executions "
            "WHERE job_id = 'ai_head_weekly_audit' "
            "  AND status = 'executed' "
            "  AND fired_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        exec_count = cur.fetchone()[0]
        execution_found = exec_count > 0

        if audit_found and execution_found:
            cur.close()
            return {"audit_found": True, "execution_found": True,
                    "alerted": False, "reason": "clean"}

        # (c) Dedupe check — prior alert in last 24h?
        cur.execute(
            "SELECT COUNT(*) FROM scheduler_executions "
            "WHERE job_id = 'ai_head_audit_sentinel' "
            "  AND status = 'alerted' "
            "  AND fired_at >= NOW() - INTERVAL '24 hours' LIMIT 1"
        )
        prior_alert_count = cur.fetchone()[0]
        if prior_alert_count > 0:
            cur.close()
            logger.info("sentinel: miss detected but deduped (prior alert in 24h)")
            return {"audit_found": audit_found, "execution_found": execution_found,
                    "alerted": False, "reason": "deduped"}

        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"sentinel: DB read failed: {e}")
        return {"audit_found": None, "execution_found": None, "alerted": False,
                "reason": f"db_error: {e}"}
    finally:
        store._put_conn(conn)

    # (d) Miss detected + not deduped → Slack alert + dedupe-anchor write
    missing_parts = []
    if not audit_found:
        missing_parts.append("ai_head_audits row")
    if not execution_found:
        missing_parts.append("scheduler_executions row for ai_head_weekly_audit")
    alert_text = (
        "⚠️ AI Head weekly audit sentinel — MISS\n\n"
        f"Missing: {', '.join(missing_parts)}\n\n"
        "Expected both to appear within 24h of Mon 09:00 UTC audit cron. "
        "Check Render logs for scheduler errors or ai_head_audit.run_weekly_audit failures."
    )
    slack_ok = False
    try:
        from outputs.slack_notifier import post_to_channel
        slack_ok = post_to_channel(DIRECTOR_DM_CHANNEL, alert_text)
    except Exception as e:
        logger.warning(f"sentinel: Slack post raised: {e}")

    # (e) Write dedupe anchor regardless of Slack success
    conn2 = store._get_conn()
    if conn2:
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                """
                INSERT INTO scheduler_executions
                    (job_id, fired_at, completed_at, status, error_msg, outputs_summary)
                VALUES (%s, NOW(), NOW(), 'alerted', %s, %s::jsonb)
                """,
                (
                    "ai_head_audit_sentinel",
                    f"missing: {', '.join(missing_parts)}",
                    f'{{"slack_ok": {str(slack_ok).lower()}, "missing": "{", ".join(missing_parts)}"}}',
                ),
            )
            conn2.commit()
            cur2.close()
        except Exception as e:
            try:
                conn2.rollback()
            except Exception:
                pass
            logger.warning(f"sentinel: dedupe-anchor write failed: {e}")
        finally:
            store._put_conn(conn2)

    return {"audit_found": audit_found, "execution_found": execution_found,
            "alerted": True, "slack_ok": slack_ok,
            "reason": f"miss: {', '.join(missing_parts)}"}
```

### Key Constraints

- **Channel ID `D0AFY28N030`** — Director DM, hardcoded per ratified Q3 (AI Head substrate channel). Matches Step 10 DM from PR #44 ship.
- **Dedupe via SELECT-before-alert** — no DB uniqueness constraint needed; sentinel is single-fire per week.
- **Dedupe-anchor write uses a FRESH connection** (`conn2`) — the first connection was closed in the `finally`.
- **Fault-tolerant:** DB failure, Slack failure, import failure — all logger.warning + continue. Sentinel never crashes scheduler.
- **JSONB construction:** literal f-string into `%s::jsonb` is fine for this tiny payload; real JSONB usage (`json.dumps(...)`) is cleaner but adds import weight. Acceptable for a simple 2-key object.
- **No `_write_audit_record` / `_update_slack_outcomes` equivalents** — sentinel is stand-alone, doesn't pollute `SentinelStoreBack` with new methods (Phase 2 refactor may elevate; not this brief).

### Verification

1. Mock both queries returning >0 → expect `audit_found=True, execution_found=True, alerted=False, reason='clean'`.
2. Mock audit query returning 0, execution query returning >0, prior-alert query returning 0, Slack mocked `True` → expect `alerted=True, slack_ok=True, reason='miss: ai_head_audits row'`.
3. Mock both queries returning 0, prior-alert returning 1 → expect `alerted=False, reason='deduped'`.
4. Mock `_get_conn` → `None` → expect `reason='db_unavailable'`, no Slack post, no DB write.
5. Mock post_to_channel raising `Exception` → expect `alerted=True, slack_ok=False`, dedupe anchor still written.

---

## Files Modified

- `memory/store_back.py` — add `_ensure_scheduler_executions_table` method + call in `__init__`.
- `triggers/embedded_scheduler.py` — extend `_job_listener` (DB write), register `ai_head_audit_sentinel` cron, add `_ai_head_audit_sentinel_job` wrapper.
- `triggers/audit_sentinel.py` — **NEW** — `run_sentinel_check()` logic.
- `tests/test_audit_sentinel.py` — **NEW** — 6 tests (see Quality Checkpoints).

## Do NOT Touch

- `outputs/slack_notifier.py` — use `post_to_channel` as-is.
- `triggers/ai_head_audit.py` — recent PR #46 singleton hotfix stays untouched.
- Any OTHER scheduled job's registration or wrapper. Phase 2 generalization is a separate brief.
- `scripts/check_singletons.sh` — pre-push hook; let it enforce.

## Quality Checkpoints

Run these in order. Paste literal output in ship report.

1. **Syntax**:
   ```
   python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
   python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
   python3 -c "import py_compile; py_compile.compile('triggers/audit_sentinel.py', doraise=True)"
   ```
   Expect: zero output (no errors).

2. **Singleton-pattern pre-push hook (per PR #46):**
   ```
   bash scripts/check_singletons.sh
   ```
   Expect: PASS (no `SentinelStoreBack()` direct-instantiation hits).

3. **New tests:**
   ```
   pytest tests/test_audit_sentinel.py -v
   ```
   Expect: 6 passed.

   Tests required:
   - `test_listener_writes_executed_row` — mock APScheduler event (success), assert row status='executed'
   - `test_listener_writes_error_row` — mock event with exception, assert row status='error', error_msg populated
   - `test_listener_survives_db_unavailable` — mock `_get_conn` → None, assert no exception, assert logger.warning called
   - `test_sentinel_clean_path` — both counts >0 → alerted=False, reason='clean'
   - `test_sentinel_miss_alerts` — audit count=0, prior-alert count=0, Slack mocked True → alerted=True, dedupe row written
   - `test_sentinel_deduped` — miss detected but prior-alert count>0 → alerted=False, reason='deduped'

4. **Full-suite regression gate:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Baseline post-PR #46 hotfix (current main `b1d566f`). Your PR should add +6 passes (the new tests), zero new failures. If baseline differs at dispatch time, recompute.

5. **Startup sanity** (optional local; not gating):
   ```
   python3 -c "from triggers.embedded_scheduler import _register_jobs"
   ```
   Expect: zero output, zero import error.

6. **DDL idempotency** (optional local; not gating): start then stop Baker twice locally; `scheduler_executions` table should persist (not recreate) on second startup.

## Verification SQL (post-deploy, Director-facing)

```sql
-- Was the new table bootstrapped on startup?
SELECT table_name FROM information_schema.tables WHERE table_name='scheduler_executions';
-- Expect: 1 row.

-- Did the sentinel cron register?
-- (no direct SQL — check Render logs for "Registered: ai_head_audit_sentinel (Mon 10:00 UTC)")

-- Post-Monday-first-fire sanity (manually, Mon 2026-04-27 ~10:05 UTC):
SELECT job_id, fired_at, completed_at, status, error_msg
  FROM scheduler_executions
 WHERE job_id IN ('ai_head_weekly_audit', 'ai_head_audit_sentinel')
   AND fired_at >= NOW() - INTERVAL '24 hours'
 ORDER BY fired_at DESC LIMIT 10;
-- Clean: 2 rows, both status='executed', no 'alerted'.
-- Problem: check whichever row is missing or status='error' / 'alerted'.
```

## Rollback

- Revert single PR — `git revert <merge-sha>` is clean.
- Env kill-switch: `AI_HEAD_AUDIT_SENTINEL_ENABLED=false` on Render → sentinel skips registration next deploy; listener DB write remains (inert; table exists, no consumers).
- DDL rollback (only if truly needed): `DROP TABLE scheduler_executions;` — no dependent FKs.

---

## Ship shape

- **PR title:** `AUDIT_SENTINEL_1: first-fire observability for ai_head_weekly_audit`
- **Branch:** `audit-sentinel-1`
- **Files:** 3 modified (`memory/store_back.py`, `triggers/embedded_scheduler.py`, NEW `triggers/audit_sentinel.py`) + 1 new test file.
- **Commit style:** match recent scheduler/audit commits (e.g. `audit-sentinel: ...` or `brief(sentinel): ...`).
- **Ship report:** `briefs/_reports/B1_audit_sentinel_1_20260423.md`. Include:
  - Literal `pytest tests/test_audit_sentinel.py -v` (6 passed expected)
  - Literal `pytest tests/ 2>&1 | tail -3` on main vs branch (delta should be +6 passes, 0 regressions)
  - Literal `bash scripts/check_singletons.sh` (PASS)
  - All 4 py_compile outputs (empty)
  - Verify in ship report that `_ensure_scheduler_executions_table` is wired in `__init__` (quote the 1-line diff)

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Timebox

**1.5–2h.** If it's taking >3h, stop and report back — something's wrong.

**Working dir:** `~/bm-b1` (TEAM-1 default).
