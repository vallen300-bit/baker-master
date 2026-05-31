"""SCHEDULER_JOB_LIVENESS_1: Data-driven liveness sentinel for interval jobs.

Reads scheduler_executions (written by triggers/embedded_scheduler.py:_job_listener)
and alerts on any expected job whose MAX(fired_at) is older than its registered
interval x tolerance factor. DB-driven so replica/singleton state doesn't matter.

V1 scope: interval jobs only. Cron jobs deferred to V2. See brief Out-of-scope.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.scheduler_liveness")


# ---------------------------------------------------------------------------
# REGISTRY pattern (per codex FAIL-LIGHT #1395 + PASS-WITH-NITS #1401):
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
# restart. Caveat: anchor reset is opt-in via caller, not auto.
_MODULE_LOAD_TIME = datetime.now(timezone.utc)


def reset_cold_start_anchor() -> None:
    """Re-stamp the cold-start anchor to NOW. Called from start_scheduler()
    so that an in-process scheduler restart (restart_scheduler() at
    embedded_scheduler.py) re-applies the COLD_START_GRACE_SECONDS
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

# Populated by register_expected_job() at startup. Format: job_id -> (interval_s, tier).
EXPECTED_JOBS: dict[str, tuple[int, int]] = {}


def register_expected_job(job_id: str, interval_seconds: int) -> None:
    """Called by triggers/embedded_scheduler.py after each IntervalTrigger add_job.

    Records the live interval (including config/env overrides). Cron jobs MUST
    NOT call this — V1 scope is interval jobs only. The pre-flight AST check
    verifies no CronTrigger job_id pairs with this function.
    """
    tier = _TIER_OVERRIDES.get(job_id, 2)
    EXPECTED_JOBS[job_id] = (int(interval_seconds), tier)


# Tolerance factor: a job is "stale" if its last fire is older than
# interval x TOLERANCE_FACTOR. Default 2x.
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
    summary: dict = {
        "checked": 0,
        "stale": [],
        "alerted": [],
        "skipped_cold_start": False,
    }

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
        # Render fresh restart -> module re-import -> new _MODULE_LOAD_TIME ->
        # grace honored. No reliance on global scheduler_executions history.
        module_age = (datetime.now(timezone.utc) - _MODULE_LOAD_TIME).total_seconds()
        if module_age < COLD_START_GRACE_SECONDS:
            summary["skipped_cold_start"] = True
            summary["skipped_reason"] = (
                f"module age {module_age:.0f}s < {COLD_START_GRACE_SECONDS}s grace"
            )
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
                # Job never fired — only alert if T1 (T2 may not exist yet; fail-open).
                if tier == 1:
                    summary["stale"].append({
                        "job_id": job_id,
                        "last_fired": None,
                        "age": None,
                        "tier": 1,
                        "staleness_window": staleness_window,
                    })
                continue

            age = (datetime.now(timezone.utc) - last_fired).total_seconds()
            if age > staleness_window:
                summary["stale"].append({
                    "job_id": job_id,
                    "last_fired": last_fired.isoformat(),
                    "age": age,
                    "tier": tier,
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
        hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d-%H")
        # JOB_LISTENER_HARDEN_1: surface listener-drop hint in alert body
        try:
            from triggers.embedded_scheduler import get_listener_drop_counts
            drop_counts = get_listener_drop_counts()
        except Exception:
            drop_counts = {}
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
                    f"staleness window is {window:.0f}s (interval x tolerance). "
                    f"Tier {tier} job — investigate."
                )
            drop_n = drop_counts.get(job_id, 0)
            if drop_n > 0:
                body += (
                    f"\n\nNOTE: _job_listener silently dropped {drop_n} write(s) for "
                    f"this job this process. The job may have fired; the listener could "
                    f"not persist. Check Render logs for JOB_LISTENER_SILENT_SKIP."
                )
            try:
                store.create_alert(
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
