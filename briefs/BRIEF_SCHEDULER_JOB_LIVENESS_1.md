---
brief: SCHEDULER_JOB_LIVENESS_1
to: b1
from: lead
authored: 2026-05-30
target_repo: baker-master
estimated_time: ~4h
complexity: Medium
codex_pre_review: PENDING (bus to fire same turn)
parent_codex_thread: bus #1362 / #1364 (codex flagged class as "needs its own design" in nit #2 on WAHA brief)
director_authorization: 2026-05-30 chat — "author brief for scheduler"
anchor_chat: Director 2026-05-30 — after PR #271 (WAHA_SESSION_POLL_HARDEN_1) shipped, codex's earlier hint + deputy bus #1383 surfaced the silent-per-job-death class. Pre-merge irregular cadence on waha_session_poll (09:42Z → 19:19Z prior day → 12:59Z) shows scheduler jobs can silently stop firing between deploys; only deploy-reset clears them.
---

# BRIEF: SCHEDULER_JOB_LIVENESS_1 — Data-driven liveness sentinel for embedded scheduler interval jobs

## Context

### Surface contract: N/A — pure backend sentinel; no clickable UI. Alert outputs land in the existing `alerts` table consumed by dashboard alert rendering already shipped. No new UI route, panel, button, or anchor.

The Sentinel embedded scheduler (`triggers/embedded_scheduler.py`) registers 40+ APScheduler jobs at process start. Some are interval-based (5 min → 6 h), some are cron-based (daily/weekly). The `_job_listener` writes a row to `scheduler_executions` on every fire (success or error).

**Failure mode this brief addresses:** A specific job stops firing while the scheduler itself stays alive. Surfaced concretely on 2026-05-30 during PR #271 AC verification: `waha_session_poll` last fired 2026-05-29 19:19Z, then 2026-05-30 09:42Z, then silent for 92+ minutes — while `scheduler_heartbeat`, `kbl_bridge_tick`, and 60+ other jobs fired on cadence. Pattern repeats across days. Only Render redeploy (which reinitializes APScheduler) reset the affected job.

Existing `triggers/audit_sentinel.py` covers ONE job (`ai_head_weekly_audit`) via `scheduler_executions` recency check. This brief generalizes the same pattern to all interval jobs.

**Out of scope (V1):**
- Cron jobs (daily/weekly) — different expected-fire calculation; defer to V2.
- Self-health (who watches the watcher) — the liveness sentinel itself can silently die. Bootstrap via a dashboard `/api/health/scheduler_liveness` endpoint reporting last self-fire; deferred to V2.
- Root-cause auto-recovery — alert only, no auto-restart of stuck jobs.

**Anchor:** codex pre-review #1364 nit #2 on PR #271 explicitly flagged this class: "A generic all-job liveness check needs its own design: expected-job registry + per-job intervals + singleton/replica semantics, not just current-process registered jobs."

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites: PR #271 (WAHA_SESSION_POLL_HARDEN_1, merged 2f2a1a9) deployed.

---

## Fix 1: New sentinel `triggers/scheduler_liveness_sentinel.py`

### Problem

No mechanism today detects a specific scheduler job going silent while other jobs continue firing. Only `audit_sentinel.py` covers one job (`ai_head_weekly_audit`). Adding the same pattern per job by hand is unscalable.

### Implementation

**Step 1.1** — Create `triggers/scheduler_liveness_sentinel.py`:

```python
"""SCHEDULER_JOB_LIVENESS_1: Data-driven liveness sentinel for interval jobs.

Reads scheduler_executions (written by triggers/embedded_scheduler.py:_job_listener)
and alerts on any expected job whose MAX(fired_at) is older than its registered
interval × tolerance factor. DB-driven so replica/singleton state doesn't matter.

V1 scope: interval jobs only. Cron jobs deferred to V2. See brief Out-of-scope.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sentinel.scheduler_liveness")


# ---------------------------------------------------------------------------
# REGISTRY pattern (revised per codex FAIL-LIGHT #1395 findings 1, 3, 4):
# The registry is BUILT DYNAMICALLY at startup by embedded_scheduler.py calling
# register_expected_job(...) after each IntervalTrigger add_job. This avoids:
#   - Stale literal intervals diverging from config/env values (Finding 1).
#   - Drift between registry and actually-registered jobs (Finding 3).
#   - Env-gated jobs incorrectly listed when their gate is off (Finding 3).
#   - Dynamic-interval jobs (kbl_*, phase6_*) hardcoded wrong (Finding 4).
# Trade-off: requires a 1-line call after every add_job in embedded_scheduler.py.
# Cron jobs are intentionally NOT registered (V1 = interval only).
# ---------------------------------------------------------------------------

# Process-local cold-start anchor — captured at module import. Since the
# sentinel module is imported during scheduler startup, this approximates
# process start time within a few ms. Replica-local; no DB lookup.
# NIT #3 fix (codex #1401): exposed via reset_cold_start_anchor() so
# in-process restart_scheduler() also re-honors grace; not just Render
# restart. Caveat documented: anchor reset is opt-in via caller, not auto.
_MODULE_LOAD_TIME = datetime.now(timezone.utc)


def reset_cold_start_anchor() -> None:
    """Re-stamp the cold-start anchor to NOW. Called from start_scheduler()
    so that an in-process scheduler restart (restart_scheduler() at
    embedded_scheduler.py:~1514) re-applies the COLD_START_GRACE_SECONDS
    window, matching the semantics of a fresh Render restart.
    """
    global _MODULE_LOAD_TIME
    _MODULE_LOAD_TIME = datetime.now(timezone.utc)

# Tier overrides — hand-curated criticality assignment. Anything not listed
# defaults to TIER 2 on registration.
_TIER_OVERRIDES: dict[str, int] = {
    "email_poll":            1,  # Gmail polling — silent miss = inbox blind
    "scheduler_heartbeat":   1,  # Self-heartbeat
    "health_watchdog":       1,  # G5 — Director-visible signals
    "waha_silence_check":    1,
    "waha_session_poll":     1,  # post-WAHA_SESSION_POLL_HARDEN_1
    "memory_watchdog":       1,  # OOM detection
    "scheduler_job_liveness": 1,  # self-monitor
}

# Populated by register_expected_job() at startup. Format: job_id → (interval_s, tier).
EXPECTED_JOBS: dict[str, tuple[int, int]] = {}


def register_expected_job(job_id: str, interval_seconds: int) -> None:
    """Called by triggers/embedded_scheduler.py after each IntervalTrigger add_job.

    Records the live interval (including config/env overrides). Cron jobs MUST
    NOT call this — V1 scope is interval jobs only. The pre-flight test verifies
    no CronTrigger job_id leaks in.
    """
    tier = _TIER_OVERRIDES.get(job_id, 2)
    EXPECTED_JOBS[job_id] = (int(interval_seconds), tier)


# Tolerance factor: a job is "stale" if its last fire is older than
# interval × TOLERANCE_FACTOR. Default 2x.
TOLERANCE_FACTOR = 2.0

# Minimum staleness window: even a 60s job needs at least 10 min of silence
# before alerting, to absorb single skipped ticks (e.g. the listener DB-write
# fail seen at 11:21Z on waha_session_poll during PR #271 smoke).
MIN_STALENESS_SECONDS = 600

# Cold-start grace: skip ALL checks while module-load is younger than this.
# Process-local, NOT DB-based — Finding 2 (MIN(fired_at) over 24h could hit
# a prior process's row and bypass grace on fresh restart).
COLD_START_GRACE_SECONDS = 900  # 15 min


def check_scheduler_liveness() -> dict:
    """SCHEDULER_JOB_LIVENESS_1: scan scheduler_executions for stale jobs.

    Returns a summary dict: {"checked": N, "stale": [...], "alerted": [...],
                              "skipped_cold_start": bool, "skipped_reason": str}.
    Side effects: T1/T2 alerts in `alerts` table on stale jobs (hourly-bucketed
    source_id for dedupe).
    """
    summary: dict = {"checked": 0, "stale": [], "alerted": [], "skipped_cold_start": False}

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            summary["skipped_reason"] = "no DB connection"
            return summary
    except Exception as e:
        summary["skipped_reason"] = f"store_back unreachable: {e}"
        return summary

    try:
        cur = conn.cursor()

        # ---- Cold-start check (process-local; Finding 2 fix) -----
        # _MODULE_LOAD_TIME is captured at import inside THIS replica's process.
        # Render fresh restart → module re-import → new _MODULE_LOAD_TIME →
        # grace honored. No reliance on global scheduler_executions history.
        module_age = (datetime.now(timezone.utc) - _MODULE_LOAD_TIME).total_seconds()
        if module_age < COLD_START_GRACE_SECONDS:
            summary["skipped_cold_start"] = True
            summary["skipped_reason"] = f"module age {module_age:.0f}s < {COLD_START_GRACE_SECONDS}s grace"
            cur.close()
            return summary

        # ---- Per-job staleness ------------------------------------------
        for job_id, (interval, tier) in EXPECTED_JOBS.items():
            staleness_window = max(interval * TOLERANCE_FACTOR, MIN_STALENESS_SECONDS)
            cur.execute(
                "SELECT MAX(fired_at) FROM scheduler_executions WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            last_fired = row[0] if row else None
            summary["checked"] += 1

            if last_fired is None:
                # Job never fired — only alert if process is past cold-start AND
                # this is a T1 job (T2 may not exist yet; fail-open).
                if tier == 1:
                    summary["stale"].append({"job_id": job_id, "last_fired": None,
                                              "age": None, "tier": 1})
                continue

            age = (datetime.now(timezone.utc) - last_fired).total_seconds()
            if age > staleness_window:
                summary["stale"].append({
                    "job_id": job_id, "last_fired": last_fired.isoformat(),
                    "age": age, "tier": tier,
                    "staleness_window": staleness_window,
                })

        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        summary["skipped_reason"] = f"DB error: {e}"
        return summary
    finally:
        store._put_conn(conn)

    # ---- Emit alerts (hourly-bucketed source_id dedupe) -----------------
    if not summary["stale"]:
        return summary

    try:
        st = store
        hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d-%H")
        for entry in summary["stale"]:
            job_id = entry["job_id"]
            tier = entry["tier"]
            age = entry.get("age")
            window = entry.get("staleness_window")
            title = f"SCHEDULER JOB STALE: {job_id}"
            if age is None:
                body = (
                    f"Scheduler job '{job_id}' has NO row in scheduler_executions "
                    f"within last 24h. Listed in EXPECTED_JOBS registry as tier {tier}. "
                    f"Investigate Render logs or jobstore state."
                )
            else:
                body = (
                    f"Scheduler job '{job_id}' last fired {age:.0f}s ago; "
                    f"staleness window is {window:.0f}s (interval × tolerance). "
                    f"Tier {tier} job — investigate."
                )
            try:
                st.create_alert(
                    tier=tier,
                    title=title,
                    body=body,
                    source="scheduler_job_liveness",
                    source_id=f"stale-{job_id}-{hour_bucket}",
                )
                summary["alerted"].append(job_id)
            except Exception as e:
                logger.warning(f"create_alert failed for {job_id}: {e}")
    except Exception as e:
        logger.warning(f"alert emit phase failed: {e}")

    return summary
```

**Step 1.2** — Register in `triggers/embedded_scheduler.py` (immediately after `waha_session_poll` block at line ~509). Import BOTH the check function AND `register_expected_job` (NIT #1 fix from codex #1401):

```python
    # SCHEDULER_JOB_LIVENESS_1: Generic per-job liveness check
    from triggers.scheduler_liveness_sentinel import (
        check_scheduler_liveness,
        register_expected_job,
        reset_cold_start_anchor,
    )
    scheduler.add_job(
        check_scheduler_liveness,
        IntervalTrigger(minutes=10),
        id="scheduler_job_liveness", name="Per-job scheduler liveness check",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("scheduler_job_liveness", 10 * 60)
    logger.info("Registered: scheduler_job_liveness (every 10 minutes)")
```

Also wire `reset_cold_start_anchor()` at the top of `start_scheduler()` (so in-process `restart_scheduler()` re-honors the grace — NIT #3 fix from codex #1401):

```python
def start_scheduler():
    # Reset cold-start anchor so in-process restarts (restart_scheduler) re-honor grace.
    from triggers.scheduler_liveness_sentinel import reset_cold_start_anchor
    reset_cold_start_anchor()
    # ...existing body...
```

**Step 1.3** — After EVERY `IntervalTrigger` add_job in `triggers/embedded_scheduler.py`, add a one-line registration call. Example for the WAHA poll (line 510):

```python
    scheduler.add_job(
        poll_waha_session,
        IntervalTrigger(minutes=5),
        id="waha_session_poll", name="WAHA session health poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("waha_session_poll", 5 * 60)
    logger.info("Registered: waha_session_poll (every 5 minutes)")
```

For env-derived intervals (kbl_pipeline_tick, kbl_bridge_tick, phase6_reflector_sweep, phase6_reconciler), pass the **already-computed live value**:

```python
    register_expected_job("kbl_pipeline_tick", _kbl_tick_seconds)
    register_expected_job("phase6_reflector_sweep", _reflector_minutes * 60)
```

For config-derived intervals (email_poll, fireflies_scan, dropbox_poll, etc.), pass the config attribute live:

```python
    register_expected_job("email_poll", config.triggers.email_check_interval)
```

**Cron jobs MUST NOT call `register_expected_job`** — V1 scope is interval only. Pre-flight test verifies no cron job_id leaks into `EXPECTED_JOBS`.

Self-registration of the liveness sentinel itself:

```python
    register_expected_job("scheduler_job_liveness", 10 * 60)
```

### Key Constraints

- **DB-driven, replica-agnostic** — query reads `scheduler_executions` (global table written by whichever replica holds the singleton lease). No reliance on in-process `_scheduler.get_jobs()` (codex flagged that as broken for non-leader replicas in PR #271 review).
- **Cold-start grace process-local** — `_MODULE_LOAD_TIME` captured at module import inside this replica. Fresh Render restart → fresh module load → grace honored. **NOT** based on `MIN(fired_at)` over scheduler_executions (Finding 2 fix).
- **MIN_STALENESS_SECONDS = 600** — even fast jobs (60s) get ≥10 min before alerting. Absorbs single-tick skip seen on waha_session_poll at 11:21Z during PR #271 smoke (listener DB-write failed once, job fired fine).
- **Dynamic registry built at startup** — embedded_scheduler.py calls `register_expected_job(job_id, live_interval_seconds)` after each interval add_job. Eliminates Finding 1 (wrong literals), Finding 3 (registry drift), and Finding 4 (dynamic-interval jobs hardcoded). Env-gated jobs that don't get registered also don't enter the registry — auto-correct.
- **Tier overrides hand-curated** — `_TIER_OVERRIDES` dict in sentinel module. Defaults to T2 unless explicitly T1.
- **Hourly bucket dedupe** — `source_id = f"stale-{job_id}-{hour_bucket}"`. Re-emitting same source_id within hour collapses at store_back.
- **No auto-recovery** — alert only. Restarting jobs at runtime risks state corruption (mirror of WAHA brief Lesson #27).
- **Cron jobs OUT of V1** — pre-flight test enforces no cron_id leaks into `EXPECTED_JOBS`.

### Verification

Pytest cases (`tests/test_scheduler_liveness_sentinel.py`):

1. Cold-start: `_MODULE_LOAD_TIME` < 15 min ago → skipped_cold_start=True, no alerts. (Patch `_MODULE_LOAD_TIME` via monkeypatch.)
2. Post-cold-start: `_MODULE_LOAD_TIME` > 15 min ago + empty registry → checked=0, no alerts.
3. Clean: every registered job has fresh fired_at → checked=N, stale=[], alerts=0.
4. Single stale job (T1): registered with interval=300s, last_fired = NOW - 30 min → 1 T1 alert with correct title + body + source_id template.
5. Single stale job (T2): registered with interval=3600s, last_fired = NOW - 8h → 1 T2 alert.
6. Multiple stale jobs: 2 stale → 2 alerts; counts match.
7. Job registered but never fired (T1) → 1 T1 alert noting "no row in 24h".
8. Job registered but never fired (T2) → no alert (fail-open until first fire).
9. DB connection unavailable → returns skipped_reason="no DB connection", no crash.
10. create_alert raises mid-loop → loop continues for remaining jobs; no crash.
11. Hourly-bucket source_id stable: 3 calls within same hour-bucket emit identical source_id.
12. **No-cron invariant** — call `register_expected_job` for a job_id that is registered as CronTrigger in embedded_scheduler.py (e.g. `clickup_poll`); assert via grep that no such registration line exists in embedded_scheduler.py for any of the 19 cron job IDs (parametrize test over the cron ID list).
13. Dynamic-interval correctness — set env `KBL_PIPELINE_TICK_INTERVAL_SECONDS=200`, re-import embedded_scheduler, assert `EXPECTED_JOBS["kbl_pipeline_tick"] == (200, 2)`.
14. Below-floor clamp — set env `KBL_PIPELINE_TICK_INTERVAL_SECONDS=10`, assert `EXPECTED_JOBS["kbl_pipeline_tick"] == (30, 2)` (clamped per embedded_scheduler.py:683-688).

Use monkeypatching for `SentinelStoreBack._get_global_instance()`, `_MODULE_LOAD_TIME`, and a fake `conn.cursor()` returning canned rows per test.

Pre-flight registry verification (b1 must run before opening PR) — **NIT #2 fix from codex #1401**: pure AST pairing check; NEVER boot `_register_jobs()` (`vault_scanner.startup_catchup()` writes mirror files + sends a consolidated Slack DM as a side effect).

```bash
python3 - <<'PY'
"""AST pairing check: every IntervalTrigger add_job MUST be followed by a
register_expected_job(...) call with the same job_id within the next 5
statements of the same function body. CronTrigger add_jobs must NOT have
register_expected_job calls anywhere referencing their id.
"""
import ast, pathlib, sys

src = pathlib.Path("triggers/embedded_scheduler.py").read_text()
tree = ast.parse(src)

# Walk function bodies; for each, scan statements pair-wise.
errors = []

def get_job_id(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None

def get_trigger_kind(call: ast.Call) -> str | None:
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Call):
        f = call.args[1].func
        if isinstance(f, ast.Name):
            return f.id
    for kw in call.keywords:
        if kw.arg == "trigger" and isinstance(kw.value, ast.Call):
            f = kw.value.func
            if isinstance(f, ast.Name):
                return f.id
    return None

interval_ids = []
cron_ids = []
register_calls = []

for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        # add_job calls
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "add_job"):
            jid = get_job_id(node)
            kind = get_trigger_kind(node)
            if jid and kind == "IntervalTrigger":
                interval_ids.append((node.lineno, jid))
            elif jid and kind == "CronTrigger":
                cron_ids.append((node.lineno, jid))
        # register_expected_job calls
        elif (isinstance(node.func, ast.Name) and node.func.id == "register_expected_job"):
            if node.args and isinstance(node.args[0], ast.Constant):
                register_calls.append((node.lineno, node.args[0].value))

reg_ids = {jid for _, jid in register_calls}

# Every interval id must have a register_expected_job
for lineno, jid in interval_ids:
    if jid not in reg_ids:
        errors.append(f"MISSING register_expected_job for IntervalTrigger '{jid}' (line {lineno})")

# No cron id may have a register_expected_job
for lineno, jid in cron_ids:
    if jid in reg_ids:
        errors.append(f"FORBIDDEN register_expected_job for CronTrigger '{jid}' (line {lineno})")

if errors:
    print("FAIL")
    for e in errors:
        print("  " + e)
    sys.exit(1)

print(f"OK: {len(interval_ids)} interval jobs paired, {len(cron_ids)} cron jobs cleanly skipped")
PY
```

Output goes in ship report. Script MUST print `OK: N interval jobs paired, M cron jobs cleanly skipped` and exit 0. Any FAIL = bug to fix before opening PR.

**Dynamic-interval correctness** is verified by pytest Case 13+14 (env override + below-floor clamp). The AST check alone cannot verify the interval VALUE is correct — those tests do.

---

## Files Modified

- `triggers/scheduler_liveness_sentinel.py` — new file.
- `triggers/embedded_scheduler.py` — register `scheduler_job_liveness` at 10-min cadence (~8 LOC + log line).
- `tests/test_scheduler_liveness_sentinel.py` — new file, 12 cases per Verification list.

## Do NOT Touch

- `triggers/audit_sentinel.py` — pre-existing single-job sentinel for `ai_head_weekly_audit`; this brief is generic interval-job class, doesn't replace.
- `triggers/sentinel_health.py` — unrelated; do not touch `poll_waha_session` (just landed in PR #271).
- `triggers/embedded_scheduler.py:_job_listener` — the DB-write path is the source of truth this sentinel reads; do not modify.
- `migrations/` — `scheduler_executions` table schema already correct (columns `job_id, fired_at, completed_at, status, error_msg` confirmed via codex prod probe in PR #271).

## Quality Checkpoints

1. Pytest passes literally: `python3.12 -m pytest tests/test_scheduler_liveness_sentinel.py -v` — paste actual stdout.
2. Compile-clean: `python3 -c "import py_compile; py_compile.compile('triggers/scheduler_liveness_sentinel.py', doraise=True); py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`.
3. Singleton guard green: `bash scripts/check_singletons.sh`.
4. Registry-vs-scheduler diff: paste the `diff /tmp/_registered.txt /tmp/_expected.txt` output (must explicitly enumerate any intentional skip).
5. PR opened; AC1 post-deploy: `SELECT MAX(fired_at) FROM scheduler_executions WHERE job_id='scheduler_job_liveness'` within 12 min.
6. AC2 post-deploy + 30 min: no false-positive stale alerts on healthy production (cold-start grace should suppress everything for first 15 min, then nothing should be stale).

## Verification SQL

```sql
-- AC 1: liveness sentinel is itself firing
SELECT job_id, MAX(fired_at), COUNT(*)
FROM scheduler_executions
WHERE job_id = 'scheduler_job_liveness'
  AND fired_at >= NOW() - INTERVAL '24 hours'
GROUP BY job_id;

-- AC 2: no false-positive stale alerts after first hour
SELECT title, source_id, created_at
FROM alerts
WHERE source = 'scheduler_job_liveness'
  AND created_at >= NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC LIMIT 20;
```

## Trade-offs Documented

- **Cron jobs out of V1** — modelling "expected fire" for `CronTrigger` requires parsing the cron expression and computing the next-fire-due. Possible but heavier; defer.
- **Self-monitor circularity** — `scheduler_job_liveness` is in its own EXPECTED_JOBS. If it stops firing, no one alerts (because it IS the alerter). V2: dashboard endpoint reports its own liveness.
- **Fail-open on registry gaps** — newly-added scheduler jobs that the registry forgets are silently un-monitored. Trade-off: simpler code + no false positives vs occasional missed coverage. Mitigated by the pre-flight registry diff check (Quality Checkpoint #4).
- **15-min cold-start grace** — too short (10) risks false-positives on slow boot; too long (30) hides early failures. 15 covers Render's observed cold-start window without delaying detection.

## Anchor

- Director "go" authorization: 2026-05-30 chat — "author brief for scheduler".
- Parent thread: codex review #1364 nit #2 on PR #271 — explicit "needs its own design" hint.
- Concrete failure mode: deputy bus #1383 → `waha_session_poll` silent 92 min while 60+ other jobs fired fine; pattern visible in `scheduler_executions` going back to 2026-05-29 19:19Z F6 anchor.
- Lesson #27 (WAHA recreation w/o store config — same alert-only-no-auto-recovery posture preserved).
- Existing pattern: `triggers/audit_sentinel.py` — single-job version this brief generalizes.
