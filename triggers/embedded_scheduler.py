"""
Embedded Sentinel Scheduler — BackgroundScheduler for FastAPI integration.

Replaces the standalone BlockingScheduler (triggers/scheduler.py) which
never ran on Render because uvicorn only starts dashboard.py.

Called by dashboard.py on startup/shutdown events.
"""
import logging
import threading
from typing import Optional
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

logger = logging.getLogger("sentinel.embedded_scheduler")

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


_scheduler: Optional[BackgroundScheduler] = None
_lock_retry_thread: Optional["threading.Thread"] = None


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

        status = "error" if event.exception else "executed"
        error_msg = str(event.exception)[:1000] if event.exception else None
        _row = (event.job_id, event.scheduled_run_time, status, error_msg)
        _insert_sql = """
            INSERT INTO scheduler_executions
                (job_id, fired_at, completed_at, status, error_msg)
            VALUES (%s, %s, NOW(), %s, %s)
        """

        # SCHEDULER_LIVENESS_REVIVE_1 Fix 1: bounded pooled backoff. Replaces the
        # single 100ms retry (JOB_LISTENER_HARDEN_1) with one immediate attempt +
        # up to 3 retries at 100/200/400ms. Total worst-case 700ms is far below
        # APScheduler misfire_grace_time (300s), so the listener never
        # back-pressures the scheduler. Transient exhaustion of the shared
        # maxconn=5 pool (FastAPI + ~40 jobs + Cortex) usually clears in that window.
        import time
        conn = store._get_conn()
        for _backoff in (0.1, 0.2, 0.4):
            if conn:
                break
            time.sleep(_backoff)
            conn = store._get_conn()

        if conn:
            # Pooled path — return the connection to the shared pool when done.
            try:
                cur = conn.cursor()
                cur.execute(_insert_sql, _row)
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
        else:
            # SCHEDULER_LIVENESS_REVIVE_1 Fix 1: pooled path exhausted. Open a
            # dedicated short-lived connection on the NON-POOLED Neon endpoint so
            # this tiny observability INSERT does not depend on the shared
            # maxconn=5 pool having a free slot. Per-event + short-lived; opened →
            # INSERT → commit → closed in finally, never reused, never returned to
            # the pool. Counts against Neon's raw connection ceiling (not the
            # pooler) — acceptable for a single small INSERT under pool pressure.
            import psycopg2
            from config.settings import config
            direct = None
            try:
                direct = psycopg2.connect(
                    connect_timeout=5, **config.postgres.direct_dsn_params
                )
                cur = direct.cursor()
                cur.execute(_insert_sql, _row)
                direct.commit()
                cur.close()
            except Exception as e:
                # Pooled retries AND the direct fallback both failed — only NOW
                # is it a true, now-rare drop of the execution row.
                _record_listener_drop(event.job_id)
                logger.warning(
                    f"JOB_LISTENER direct-conn fallback failed job_id={event.job_id}: {e}"
                )
            finally:
                if direct is not None:
                    try:
                        direct.close()
                    except Exception:
                        pass
    except Exception as e:
        # Catastrophic failure (import, singleton, etc.) — log and continue.
        # Scheduler must not crash because of observability.
        logger.warning(f"_job_listener DB path failed ({event.job_id}): {e}")


def _register_jobs(scheduler: BackgroundScheduler):
    """Register all Sentinel trigger jobs.

    Mirrors triggers/scheduler.py SentinelScheduler._register_jobs() exactly.
    All imports are lazy (inside function) to avoid circular imports.
    """
    from config.settings import config

    # SCHEDULER_JOB_LIVENESS_1: dynamic registry built at startup. Every
    # IntervalTrigger add_job below pairs with a register_expected_job(...)
    # call. CronTrigger jobs MUST NOT pair (V1 = interval only). The AST
    # pre-flight check in tests verifies this invariant before merge.
    from triggers.scheduler_liveness_sentinel import (
        check_scheduler_liveness,
        register_expected_job,
    )

    # Email polling — every 5 minutes
    from triggers.email_trigger import check_new_emails
    scheduler.add_job(
        check_new_emails,
        IntervalTrigger(seconds=config.triggers.email_check_interval),
        id="email_poll", name="Gmail polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("email_poll", config.triggers.email_check_interval)
    logger.info(f"Registered: email_poll (every {config.triggers.email_check_interval}s)")

    # M365 Graph mail polling — every GRAPH_MAIL_CHECK_INTERVAL seconds.
    # Independent source adapter; inert unless BAKER_USE_GRAPH=true (the
    # check_new_graph_messages entrypoint returns with zero side effects when
    # GraphClient.is_ready() is False). Mirrors triggers/scheduler.py #292;
    # this is the LIVE registration (BlockingScheduler version never runs in prod).
    from triggers.graph_mail_trigger import check_new_graph_messages
    scheduler.add_job(
        check_new_graph_messages,
        IntervalTrigger(seconds=config.triggers.graph_mail_check_interval),
        id="graph_mail_poll", name="Microsoft Graph mail polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("graph_mail_poll", config.triggers.graph_mail_check_interval)
    logger.info(f"Registered: graph_mail_poll (every {config.triggers.graph_mail_check_interval}s)")

    # WhatsApp: migrated from Wassenger polling to WAHA webhook (Session 26)
    # whatsapp_poll job removed — inbound messages now arrive via POST /api/webhook/whatsapp

    # Fireflies scanning — every 15 minutes, fires immediately on startup
    # Fireflies scanning — regular interval (DEPLOY-FIX-1: removed next_run_time=now;
    # backfill thread handles startup catch-up, no need for immediate duplicate run)
    from triggers.fireflies_trigger import check_new_transcripts
    scheduler.add_job(
        check_new_transcripts,
        IntervalTrigger(seconds=config.triggers.fireflies_scan_interval),
        id="fireflies_scan", name="Fireflies scanning",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("fireflies_scan", config.triggers.fireflies_scan_interval)
    logger.info(f"Registered: fireflies_scan (every {config.triggers.fireflies_scan_interval}s)")

    # Plaud Note Pro scanning — every 15 minutes
    if config.plaud.api_token:
        from triggers.plaud_trigger import check_new_plaud_recordings
        scheduler.add_job(
            check_new_plaud_recordings,
            IntervalTrigger(seconds=config.triggers.plaud_scan_interval),
            id="plaud_scan", name="Plaud Note Pro scanning",
            coalesce=True, max_instances=1, replace_existing=True,
        )
        register_expected_job("plaud_scan", config.triggers.plaud_scan_interval)
        logger.info(f"Registered: plaud_scan (every {config.triggers.plaud_scan_interval}s)")
    else:
        logger.info("Plaud trigger: PLAUD_TOKEN not set — skipping registration")

    # ClickUp polling — once a day at 04:30 UTC (Director rule 2026-04-30:
    # 5-min cadence was over-polling; once-a-day is sufficient for Brisen's
    # ClickUp use cases per priority pivot — channels are last-stage work).
    # Override via CLICKUP_POLL_CRON_HOUR + CLICKUP_POLL_CRON_MINUTE if needed.
    # Manual fire still available via direct python invocation.
    import os as _os_clickup
    from triggers.clickup_trigger import run_clickup_poll
    try:
        _clickup_hour = int(_os_clickup.environ.get("CLICKUP_POLL_CRON_HOUR", "4"))
        _clickup_minute = int(_os_clickup.environ.get("CLICKUP_POLL_CRON_MINUTE", "30"))
    except (TypeError, ValueError):
        _clickup_hour, _clickup_minute = 4, 30
    scheduler.add_job(
        run_clickup_poll,
        CronTrigger(hour=_clickup_hour, minute=_clickup_minute, timezone="UTC"),
        id="clickup_poll", name="ClickUp multi-workspace poll (daily)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        f"Registered: clickup_poll (daily at {_clickup_hour:02d}:{_clickup_minute:02d} UTC)"
    )

    # STATE_FILE_REFRESH_1: nightly drift audit at 03:00 UTC (3h before vault_scanner
    # at 06:00 UTC to spread filesystem load + ClickUp writes across the night).
    # Singleton via scheduler_lease. Job is fault-tolerant — any exception
    # is logged but does not crash scheduler (try/except inside run_state_drift_audit).
    from triggers.state_drift_audit import run_state_drift_audit
    scheduler.add_job(
        run_state_drift_audit,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="state_drift_audit",
        name="State drift audit — cortex-config vs decisions_log",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Registered: state_drift_audit (daily at 03:00 UTC)")

    # Dropbox polling — every 30 minutes
    from triggers.dropbox_trigger import run_dropbox_poll
    scheduler.add_job(
        run_dropbox_poll,
        IntervalTrigger(seconds=config.triggers.dropbox_check_interval),
        id="dropbox_poll", name="Dropbox folder polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("dropbox_poll", config.triggers.dropbox_check_interval)
    logger.info(f"Registered: dropbox_poll (every {config.triggers.dropbox_check_interval}s)")

    # WEALTH-MANAGER: Edita's Dropbox feed — every 30 minutes
    from triggers.dropbox_trigger import run_edita_dropbox_poll
    scheduler.add_job(
        run_edita_dropbox_poll,
        IntervalTrigger(seconds=config.triggers.dropbox_check_interval),
        id="dropbox_edita_poll", name="Edita Dropbox folder polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("dropbox_edita_poll", config.triggers.dropbox_check_interval)
    logger.info("Registered: dropbox_edita_poll (Edita-Feed)")

    # Todoist polling — every 30 minutes
    from triggers.todoist_trigger import run_todoist_poll
    scheduler.add_job(
        run_todoist_poll,
        IntervalTrigger(seconds=config.triggers.todoist_check_interval),
        id="todoist_poll", name="Todoist task polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("todoist_poll", config.triggers.todoist_check_interval)
    logger.info(f"Registered: todoist_poll (every {config.triggers.todoist_check_interval}s)")

    # RSS polling — every 60 minutes (RSS-1)
    from triggers.rss_trigger import run_rss_poll
    scheduler.add_job(
        run_rss_poll,
        IntervalTrigger(seconds=config.triggers.rss_check_interval),
        id="rss_poll", name="RSS feed polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("rss_poll", config.triggers.rss_check_interval)
    logger.info(f"Registered: rss_poll (every {config.triggers.rss_check_interval}s)")

    # Slack polling — every 5 minutes (SLACK-1 S2)
    from triggers.slack_trigger import run_slack_poll
    scheduler.add_job(
        run_slack_poll,
        IntervalTrigger(seconds=config.triggers.slack_check_interval),
        id="slack_poll", name="Slack channel polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("slack_poll", config.triggers.slack_check_interval)
    logger.info(f"Registered: slack_poll (every {config.triggers.slack_check_interval}s)")

    # Browser task polling — every 30 minutes (BROWSER-1)
    from triggers.browser_trigger import run_browser_poll
    scheduler.add_job(
        run_browser_poll,
        IntervalTrigger(seconds=config.triggers.browser_check_interval),
        id="browser_poll", name="Browser task polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("browser_poll", config.triggers.browser_check_interval)
    logger.info(f"Registered: browser_poll (every {config.triggers.browser_check_interval}s)")

    # WhatsApp re-sync — every 6 hours (catch missed webhook messages)
    from scripts.extract_whatsapp import backfill_whatsapp
    scheduler.add_job(
        backfill_whatsapp,
        IntervalTrigger(seconds=21600),
        id="whatsapp_resync", name="WhatsApp periodic re-sync",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("whatsapp_resync", 21600)
    logger.info("Registered: whatsapp_resync (every 6 hours)")

    # WAHA-HEALTH-FIXES-1: Weekly WAHA restart — prevents memory accumulation
    def _restart_waha_service():
        import os, requests
        render_api_key = os.getenv("RENDER_API_KEY", "")
        waha_service_id = "srv-d6hiiff5r7bs73euhd4g"
        if not render_api_key:
            logger.warning("WAHA restart: RENDER_API_KEY not set — skipping")
            return
        try:
            resp = requests.post(
                f"https://api.render.com/v1/services/{waha_service_id}/deploys",
                headers={"Authorization": f"Bearer {render_api_key}"},
                json={"clearCache": "do_not_clear"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                logger.info("WAHA restart: deploy triggered successfully")
                try:
                    from triggers.sentinel_health import report_success
                    report_success("waha_restart")
                except Exception:
                    pass
            else:
                logger.warning(f"WAHA restart failed: {resp.status_code} {resp.text[:200]}")
                try:
                    from triggers.sentinel_health import report_failure
                    report_failure("waha_restart", f"HTTP {resp.status_code}")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"WAHA restart exception: {e}")
            try:
                from triggers.sentinel_health import report_failure
                report_failure("waha_restart", str(e))
            except Exception:
                pass

    scheduler.add_job(
        _restart_waha_service,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="waha_weekly_restart", name="WAHA weekly restart",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_weekly_restart (Sunday 04:00 UTC)")

    # Daily briefing — 06:00 UTC (08:00 CET)
    from triggers.briefing_trigger import generate_morning_briefing
    scheduler.add_job(
        generate_morning_briefing,
        CronTrigger(hour=config.triggers.daily_briefing_hour, minute=0),
        id="daily_briefing", name="Morning briefing",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: daily_briefing (at {config.triggers.daily_briefing_hour:02d}:00 UTC)")

    # STALE_CYCLE_NUDGE_SENTINEL_1: daily 07:00 UTC stale tier_b_pending nudge.
    # Lands after daily_briefing (06:00 UTC) + wiki_lint (06:30 UTC) so the
    # morning brief surface is rendered first, and before 09:00 CET workday
    # start so any new ClickUp tasks appear on Director's board on arrival.
    from triggers.stale_cycle_nudge_sentinel import run_stale_cycle_nudge_sentinel
    scheduler.add_job(
        run_stale_cycle_nudge_sentinel,
        CronTrigger(hour=7, minute=0, timezone="UTC"),
        id="stale_cycle_nudge", name="Stale tier_b_pending cycle nudge",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: stale_cycle_nudge (daily 07:00 UTC)")

    # Wiki lint — daily 06:30 UTC (before morning brief) (CORTEX-PHASE-3)
    scheduler.add_job(
        _run_wiki_lint,
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="wiki_lint",
        name="wiki_lint",
        replace_existing=True,
    )
    logger.info("Registered: wiki_lint (daily 06:30 UTC)")

    # AO PM matter lint — weekly Sunday 06:00 UTC (BRIEF_AO_PM_EXTENSION_1 §5)
    scheduler.add_job(
        _run_ao_pm_lint,
        CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="UTC"),
        id="ao_pm_lint",
        name="ao_pm_lint",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("Registered: ao_pm_lint (Sunday 06:00 UTC)")

    # BRANCH_HYGIENE_1: weekly remote-branch prune — Mon 10:30 UTC
    def _run_branch_hygiene_weekly():
        try:
            from scripts.branch_hygiene import (
                run_classification, execute_deletions, DEFAULT_REPO,
                DEFAULT_BASE, DEFAULT_STALENESS_DAYS, DEFAULT_PROTECT_PATTERNS,
            )
            buckets = run_classification(
                repo=DEFAULT_REPO,
                base=DEFAULT_BASE,
                staleness_days=DEFAULT_STALENESS_DAYS,
                protect_patterns=DEFAULT_PROTECT_PATTERNS,
            )
            execute_deletions(
                buckets.get("L1", []),
                repo=DEFAULT_REPO,
                layer="L1",
                dry_run=False,
            )
            logger.info(
                "branch_hygiene_weekly: L1=%d MOBILE=%d L2_FLAGGED=%d KEEP=%d",
                len(buckets.get("L1", [])),
                len(buckets.get("MOBILE_CLUSTER", [])),
                len(buckets.get("L2_FLAGGED", [])),
                len(buckets.get("KEEP", [])),
            )
        except Exception as e:
            logger.warning("branch_hygiene_weekly failed (non-fatal): %s", e)

    scheduler.add_job(
        _run_branch_hygiene_weekly,
        CronTrigger(day_of_week="mon", hour=10, minute=30, timezone="UTC"),
        id="branch_hygiene_weekly",
        name="branch_hygiene_weekly",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("Registered: branch_hygiene_weekly (Monday 10:30 UTC)")

    # ALERT-DEDUP-1: Alert digest flush DISABLED.
    # Was sending ~48 digest emails/day. Slack (with dedup) + daily briefing email
    # now cover all alerting. Re-enable by uncommenting.
    # from orchestrator.digest_manager import flush_digest
    # scheduler.add_job(
    #     flush_digest,
    #     IntervalTrigger(seconds=1800),
    #     id="digest_flush", name="Alert digest flush",
    #     coalesce=True, max_instances=1, replace_existing=True,
    # )
    logger.info("digest_flush DISABLED (ALERT-DEDUP-1 — Slack + daily briefing replaces digest)")

    # Deadline cadence check — every hour (DEADLINE-SYSTEM-1)
    from orchestrator.deadline_manager import run_cadence_check
    scheduler.add_job(
        run_cadence_check,
        IntervalTrigger(seconds=3600),
        id="deadline_cadence", name="Deadline escalation cadence",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("deadline_cadence", 3600)
    logger.info("Registered: deadline_cadence (every 60 minutes)")

    # VIP SLA monitoring — KILLED (Director decision, Session 21).
    # Unanswered message tracking is not helpful — creates noise, not value.
    logger.info("vip_sla_check REMOVED (Director decision — not helpful)")

    # Commitment overdue check — DISABLED (Session 26)
    # All commitments migrated to deadlines table (OBLIGATIONS-UNIFY-1).
    # Deadline cadence (run_cadence_check) handles reminders now.
    # from orchestrator.commitment_checker import run_commitment_check
    logger.info("Skipped: commitment_check (disabled — migrated to deadlines)")

    # Calendar polling + meeting prep — every 15 minutes (Phase 3A)
    from triggers.calendar_trigger import check_calendar_and_prep
    scheduler.add_job(
        check_calendar_and_prep,
        IntervalTrigger(minutes=15),
        id="calendar_prep", name="Calendar meeting prep",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("calendar_prep", 15 * 60)
    logger.info("Registered: calendar_prep (every 15 minutes)")

    # Alert auto-expiry — every 6 hours (COCKPIT-V3 Phase C)
    from orchestrator.pipeline import run_alert_expiry_check, auto_dismiss_past_travel
    scheduler.add_job(
        run_alert_expiry_check,
        IntervalTrigger(hours=1),
        id="alert_expiry", name="Alert expiry + snooze reactivation (hourly)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("alert_expiry", 60 * 60)
    logger.info("Registered: alert_expiry (every 1 hour — includes snooze reactivation)")

    # TRAVEL-HYGIENE-1: Auto-dismiss travel alerts after midnight CET on departure day
    scheduler.add_job(
        auto_dismiss_past_travel,
        IntervalTrigger(hours=1),
        id="dismiss_past_travel", name="Dismiss past travel alerts (hourly, midnight CET)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("dismiss_past_travel", 60 * 60)
    logger.info("Registered: dismiss_past_travel (every 1 hour — midnight CET expiry)")

    # Proactive signal scanner — every 30 minutes (PROACTIVE-FLAG-AO)
    from triggers.proactive_scanner import run_proactive_scan
    scheduler.add_job(
        run_proactive_scan,
        IntervalTrigger(minutes=30),
        id="proactive_scan", name="Proactive signal scanner",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("proactive_scan", 30 * 60)
    logger.info("Registered: proactive_scan (every 30 minutes)")

    # Communication gap tracker — DISABLED (Session 26, Director decision)
    # All contacts treated equally — no VIP-specific gap monitoring.
    # from triggers.proactive_scanner import run_communication_gap_check
    logger.info("Skipped: communication_gap_check (disabled — all contacts equal)")

    # SENTINEL-SAFETY-1: Stale watermark detector — every 6 hours
    from triggers.sentinel_health import check_stale_watermarks
    scheduler.add_job(
        check_stale_watermarks,
        IntervalTrigger(hours=6),
        id="stale_watermark_check", name="Stale watermark detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("stale_watermark_check", 6 * 60 * 60)
    logger.info("Registered: stale_watermark_check (every 6 hours)")

    # F1: Compounding risk detector — every 2 hours (Session 26)
    from orchestrator.risk_detector import run_risk_detection
    scheduler.add_job(
        run_risk_detection,
        IntervalTrigger(hours=2),
        id="risk_detection", name="Compounding risk detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("risk_detection", 2 * 60 * 60)
    logger.info("Registered: risk_detection (every 2 hours)")

    # F5: Weekly intelligence digest — Sundays 18:00 UTC (Session 26)
    from orchestrator.weekly_digest import run_weekly_digest
    scheduler.add_job(
        run_weekly_digest,
        CronTrigger(day_of_week="sun", hour=18, minute=0),
        id="weekly_digest", name="Weekly intelligence digest",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: weekly_digest (Sundays 18:00 UTC)")

    # F3: Communication cadence tracker — every 6 hours (Session 27)
    from orchestrator.cadence_tracker import run_cadence_tracker
    scheduler.add_job(
        run_cadence_tracker,
        IntervalTrigger(hours=6),
        id="cadence_tracker", name="Communication cadence tracker",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("cadence_tracker", 6 * 60 * 60)
    logger.info("Registered: cadence_tracker (every 6 hours)")

    # G5: Health watchdog — every 2 hours (Session 27)
    from triggers.sentinel_health import run_health_watchdog
    scheduler.add_job(
        run_health_watchdog,
        IntervalTrigger(hours=2),
        id="health_watchdog", name="Health watchdog (WA alert if stuck)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("health_watchdog", 2 * 60 * 60)
    logger.info("Registered: health_watchdog (every 2 hours)")

    # WAHA-SILENT-GUARD-1: Detect WhatsApp inbound silence
    from triggers.sentinel_health import check_waha_silence
    scheduler.add_job(
        check_waha_silence,
        IntervalTrigger(hours=2),
        id="waha_silence_check", name="WAHA inbound silence detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("waha_silence_check", 2 * 60 * 60)
    logger.info("Registered: waha_silence_check (every 2 hours)")

    # WAHA-SILENT-GUARD-1 / WAHA_SESSION_POLL_HARDEN_1: Active WAHA session health poll
    from triggers.sentinel_health import poll_waha_session
    scheduler.add_job(
        poll_waha_session,
        IntervalTrigger(minutes=5),
        id="waha_session_poll", name="WAHA session health poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("waha_session_poll", 5 * 60)
    logger.info("Registered: waha_session_poll (every 5 minutes)")

    # SCHEDULER_JOB_LIVENESS_1: Generic per-job liveness check.
    # Reads scheduler_executions and alerts on any EXPECTED_JOBS entry whose
    # last fire is older than interval x tolerance. Self-registers as a T1
    # job so a missing scheduler_job_liveness row is itself surfaced.
    scheduler.add_job(
        check_scheduler_liveness,
        IntervalTrigger(minutes=10),
        id="scheduler_job_liveness", name="Per-job scheduler liveness check",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("scheduler_job_liveness", 10 * 60)
    logger.info("Registered: scheduler_job_liveness (every 10 minutes)")

    # F4: Financial signal detector — every 6 hours (Session 27)
    from orchestrator.financial_detector import run_financial_detection
    scheduler.add_job(
        run_financial_detection,
        IntervalTrigger(hours=6),
        id="financial_detector", name="Financial signal detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("financial_detector", 6 * 60 * 60)
    logger.info("Registered: financial_detector (every 6 hours)")

    # Document pipeline job queue drain — every 2 minutes (PIPELINE-JOBQUEUE-1)
    from tools.document_pipeline import drain_doc_pipeline
    scheduler.add_job(
        drain_doc_pipeline,
        IntervalTrigger(minutes=2),
        id="doc_pipeline_drain", name="Document pipeline job queue",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("doc_pipeline_drain", 2 * 60)
    logger.info("Registered: doc_pipeline_drain (every 2 minutes)")

    # INTERACTION-PIPELINE-1: Daily last_contact_date sync from contact_interactions
    def _sync_contact_dates():
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.sync_last_contact_dates()
        except Exception as e:
            logger.warning(f"sync_last_contact_dates failed: {e}")

    scheduler.add_job(
        _sync_contact_dates,
        CronTrigger(hour=5, minute=0),
        id="sync_contact_dates", name="Sync last_contact_date from interactions",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: sync_contact_dates (daily at 05:00 UTC)")

    # THREE-TIER-MEMORY: Tier 1→2 compression — weekly (Sundays 04:00 UTC, Opus)
    from orchestrator.memory_consolidator import run_memory_consolidation, run_institutional_consolidation
    scheduler.add_job(
        run_memory_consolidation,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="memory_consolidation", name="Weekly Tier 1→2 Opus compression",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: memory_consolidation (Sundays 04:00 UTC — Opus)")

    # THREE-TIER-MEMORY: Tier 2→3 institutional — monthly (1st of month, 04:30 UTC, Sonnet)
    scheduler.add_job(
        run_institutional_consolidation,
        CronTrigger(day=1, hour=4, minute=30),
        id="institutional_consolidation", name="Monthly Tier 2→3 institutional compression",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: institutional_consolidation (1st of month 04:30 UTC — Sonnet)")

    # F6: Trend detection — monthly (1st of month, 05:00 UTC)
    from orchestrator.trend_detector import run_trend_detection
    scheduler.add_job(
        run_trend_detection,
        CronTrigger(day=1, hour=5, minute=0),
        id="trend_detection", name="Monthly trend detection",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: trend_detection (1st of month 05:00 UTC)")

    # ACTION-COMPLETION-DETECTOR: Auto-mark approved actions as done — every 6h
    from orchestrator.action_completion_detector import run_action_completion_detector
    scheduler.add_job(
        run_action_completion_detector,
        IntervalTrigger(hours=6),
        id="action_completion_detector", name="Action completion detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("action_completion_detector", 6 * 60 * 60)
    logger.info("Registered: action_completion_detector (every 6 hours)")

    # OBLIGATION-GENERATOR: Morning triage actions — 06:50 UTC (08:50 CET)
    from orchestrator.obligation_generator import run_obligation_generator
    scheduler.add_job(
        run_obligation_generator,
        CronTrigger(hour=6, minute=50),
        id="obligation_generator", name="Obligation generator + morning push",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: obligation_generator (daily 06:50 UTC)")

    # PROACTIVE-INITIATIVE-1: Daily initiative engine — 07:00 UTC (09:00 CET)
    from orchestrator.initiative_engine import run_initiative_engine
    scheduler.add_job(
        run_initiative_engine,
        CronTrigger(hour=7, minute=0),
        id="initiative_engine", name="Proactive initiative engine",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: initiative_engine (daily 07:00 UTC)")

    # SENTIMENT-TRAJECTORY-1: Sentiment backfill — every 6 hours
    from orchestrator.sentiment_scorer import run_sentiment_backfill
    scheduler.add_job(
        run_sentiment_backfill,
        IntervalTrigger(hours=6),
        id="sentiment_backfill", name="Sentiment scoring backfill",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("sentiment_backfill", 6 * 60 * 60)
    logger.info("Registered: sentiment_backfill (every 6 hours)")

    # CROSS-MATTER-CONVERGENCE-1: Weekly convergence detection — Wednesdays 06:00 UTC
    from orchestrator.convergence_detector import run_convergence_detection
    scheduler.add_job(
        run_convergence_detection,
        CronTrigger(day_of_week="wed", hour=6, minute=0),
        id="convergence_detection", name="Cross-matter convergence detection",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: convergence_detection (Wednesdays 06:00 UTC)")

    # Baker 3.0: Morning push digest — 07:00 UTC daily
    from outputs.push_sender import send_morning_digest
    scheduler.add_job(
        send_morning_digest,
        CronTrigger(hour=7, minute=0),
        id="morning_push_digest", name="Morning push digest",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Registered: morning_push_digest (daily 07:00 UTC)")

    # Baker 3.0: Evening push digest — 18:00 UTC daily
    from outputs.push_sender import send_evening_digest
    scheduler.add_job(
        send_evening_digest,
        CronTrigger(hour=18, minute=0),
        id="evening_push_digest", name="Evening push digest",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("Registered: evening_push_digest (daily 18:00 UTC)")

    # BROWSER-AGENT-1 Phase 3: Expire stale browser actions — every 5 minutes
    scheduler.add_job(
        _expire_browser_actions,
        IntervalTrigger(minutes=5),
        id="expire_browser_actions", name="Expire browser actions",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("expire_browser_actions", 5 * 60)
    logger.info("Registered: expire_browser_actions (every 5 min)")

    # SCHEDULER-WATCHDOG-1: Heartbeat — proof of life every 5 min
    scheduler.add_job(
        _scheduler_heartbeat,
        IntervalTrigger(minutes=5),
        id="scheduler_heartbeat", name="Scheduler heartbeat",
        coalesce=True, max_instances=1, replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # Run immediately on startup
    )
    register_expected_job("scheduler_heartbeat", 5 * 60)
    logger.info("Registered: scheduler_heartbeat (every 5 min)")

    # OOM-PHASE3: Memory watchdog — log RSS every 5 min, alert on thresholds
    scheduler.add_job(
        _memory_watchdog,
        IntervalTrigger(minutes=5),
        id="memory_watchdog", name="Memory watchdog",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("memory_watchdog", 5 * 60)
    logger.info("Registered: memory_watchdog (every 5 min)")

    # KBL_PIPELINE_SCHEDULER_WIRING: KBL-B Steps 1-6 orchestrator.
    # Env-gated inside main() on KBL_FLAGS_PIPELINE_ENABLED (default
    # closed) — safe to register unconditionally. Mac Mini poller owns
    # Step 7 (CHANDA Inv 9). Default 120 s; override via
    # KBL_PIPELINE_TICK_INTERVAL_SECONDS.
    import os as _os
    try:
        _kbl_tick_seconds = int(_os.environ.get("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "120"))
    except (TypeError, ValueError):
        _kbl_tick_seconds = 120
    if _kbl_tick_seconds < 30:
        logger.warning(
            "KBL_PIPELINE_TICK_INTERVAL_SECONDS=%s below 30s floor; clamping to 30",
            _kbl_tick_seconds,
        )
        _kbl_tick_seconds = 30
    scheduler.add_job(
        _kbl_pipeline_tick_job,
        IntervalTrigger(seconds=_kbl_tick_seconds),
        id="kbl_pipeline_tick", name="KBL-B pipeline tick (Steps 1-6)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=60,
    )
    register_expected_job("kbl_pipeline_tick", _kbl_tick_seconds)
    logger.info(f"Registered: kbl_pipeline_tick (every {_kbl_tick_seconds}s — env-gated)")

    # ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1: Producer for signal_queue.
    # Reads new alerts → applies 4-axis filter + stop-list → maps to
    # signal_queue rows so kbl_pipeline_tick has something to claim.
    # Default 60 s; override via BRIDGE_TICK_INTERVAL_SECONDS. 30 s floor
    # matches kbl_pipeline_tick to keep the producer/consumer cadence
    # similar (bridge fires twice per consumer tick at default).
    try:
        _bridge_tick_seconds = int(_os.environ.get("BRIDGE_TICK_INTERVAL_SECONDS", "60"))
    except (TypeError, ValueError):
        _bridge_tick_seconds = 60
    if _bridge_tick_seconds < 30:
        logger.warning(
            "BRIDGE_TICK_INTERVAL_SECONDS=%s below 30s floor; clamping to 30",
            _bridge_tick_seconds,
        )
        _bridge_tick_seconds = 30
    scheduler.add_job(
        _kbl_bridge_tick_job,
        IntervalTrigger(seconds=_bridge_tick_seconds),
        id="kbl_bridge_tick", name="KBL bridge: alerts → signal_queue",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=30,
    )
    register_expected_job("kbl_bridge_tick", _bridge_tick_seconds)
    logger.info(f"Registered: kbl_bridge_tick (every {_bridge_tick_seconds}s)")

    # BRIDGE_HOT_MD_AND_TUNING_1: Saturday morning hot.md nudge.
    # Fires once weekly (Sat 06:00 UTC / 07:00 CET / 08:00 CEST). Sends a
    # short, action-oriented WhatsApp via the existing
    # ``outputs/whatsapp_sender.py`` helper (§9 rule #4 — alerts rare +
    # earned, not chatty). Env gate ``HOT_MD_NUDGE_ENABLED`` (default
    # ``true``) allows quick disable without redeploy. Fire-and-forget —
    # WAHA-down is swallowed by the wrapper per substrate-push contract.
    # Retires when ``BRIEF_MORNING_DIGEST_FANOUT_1`` consolidates
    # Saturday substrate pushes into the morning digest.
    _nudge_enabled = _os.environ.get("HOT_MD_NUDGE_ENABLED", "true").lower()
    if _nudge_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _hot_md_weekly_nudge_job,
            CronTrigger(day_of_week="sat", hour=6, minute=0),
            id="hot_md_weekly_nudge",
            name="Hot.md weekly nudge (Saturday 06:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: hot_md_weekly_nudge (Sat 06:00 UTC)")
    else:
        logger.info("Skipped: hot_md_weekly_nudge (HOT_MD_NUDGE_ENABLED=false)")

    # BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Monday morning AI Head self-audit.
    # Scans baker-vault/_ops/agents/ai-head/ triplet for drift; reviews
    # past-week ARCHIVE Lessons blocks for patterns; writes to PG
    # ai_head_audits table; pushes plain-English summary to #cockpit
    # + Director DM (D0AFY28N030). Fires Mon 09:00 UTC (10:00 CET /
    # 11:00 CEST). Env gate ``AI_HEAD_AUDIT_ENABLED`` (default ``true``).
    _audit_enabled = _os.environ.get("AI_HEAD_AUDIT_ENABLED", "true").lower()
    if _audit_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _ai_head_weekly_audit_job,
            CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
            id="ai_head_weekly_audit",
            name="AI Head weekly self-audit (Monday 09:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: ai_head_weekly_audit (Mon 09:00 UTC)")
    else:
        logger.info("Skipped: ai_head_weekly_audit (AI_HEAD_AUDIT_ENABLED=false)")

    # GOLD_COMMENT_WORKFLOW_1 D6: weekly Gold corpus audit.
    # Mon 09:30 UTC — slot between ai_head_weekly_audit (09:00) +
    # ai_head_audit_sentinel (10:00). Env gate ``GOLD_AUDIT_ENABLED``
    # (default ``true``).
    _gold_audit_enabled = _os.environ.get("GOLD_AUDIT_ENABLED", "true").lower()
    if _gold_audit_enabled not in ("false", "0", "no", "off"):
        from orchestrator.gold_audit_job import _gold_audit_sentinel_job
        scheduler.add_job(
            _gold_audit_sentinel_job,
            CronTrigger(day_of_week="mon", hour=9, minute=30, timezone="UTC"),
            id="gold_audit_sentinel",
            name="Gold corpus weekly audit (Monday 09:30 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: gold_audit_sentinel (Mon 09:30 UTC)")
    else:
        logger.info("Skipped: gold_audit_sentinel (GOLD_AUDIT_ENABLED=false)")

    # CORTEX_3T_FORMALIZE_1C (RA-23 Q6): weekly cortex-config drift audit.
    # Mon 11:00 UTC — slot 1h after ai_head_audit_sentinel (10:00). Walks
    # ``BAKER_VAULT_PATH/wiki/matters/*/cortex-config.md`` and flags any
    # config older than ``CORTEX_DRIFT_THRESHOLD_DAYS`` (default 30). Env
    # gate ``CORTEX_DRIFT_AUDIT_ENABLED`` (default ``true``).
    _cortex_drift_enabled = _os.environ.get("CORTEX_DRIFT_AUDIT_ENABLED", "true").lower()
    if _cortex_drift_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _matter_config_drift_weekly_job,
            CronTrigger(day_of_week="mon", hour=11, minute=0, timezone="UTC"),
            id="matter_config_drift_weekly",
            name="Cortex matter-config drift audit (Monday 11:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: matter_config_drift_weekly (Mon 11:00 UTC)")
    else:
        logger.info("Skipped: matter_config_drift_weekly (CORTEX_DRIFT_AUDIT_ENABLED=false)")

    # BAKER-COST-INSTRUMENTATION-1: daily cost summary post to #cockpit at
    # 23:55 UTC. Posts a per-source / per-matter / per-model breakdown for
    # the closing UTC day. Idempotent via cost_alert_state row keyed on
    # (alert_date, 'daily_summary'). Suppressed when
    # ``BAKER_COST_ALARMS_ENABLED=false`` (job runs but exits early). Env
    # gate ``BAKER_COST_DAILY_SUMMARY_ENABLED`` (default ``true``) lets ops
    # disable the job registration entirely without redeploy.
    _cost_summary_enabled = _os.environ.get(
        "BAKER_COST_DAILY_SUMMARY_ENABLED", "true"
    ).lower()
    if _cost_summary_enabled not in ("false", "0", "no", "off"):
        from orchestrator.cost_monitor import post_daily_cost_summary
        scheduler.add_job(
            post_daily_cost_summary,
            CronTrigger(hour=23, minute=55, timezone="UTC"),
            id="daily_cost_summary",
            name="Baker daily cost summary (23:55 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: daily_cost_summary (23:55 UTC)")
    else:
        logger.info("Skipped: daily_cost_summary (BAKER_COST_DAILY_SUMMARY_ENABLED=false)")

    # CORTEX_ARCHIVE_FAILURE_ALERTING_1: every 5 min stuck-cycle + archive-failure
    # sentinel. Detects (A) cortex_cycles in machine-transient status past 15-min
    # threshold (in_flight / awaiting_reason / proposed) and (B) terminal
    # status='archive_failed' from Phase 6 self-fail path. Posts Director DM with
    # baker_actions dedup so one alert per (cycle_id × failure-mode). Env gate
    # ``CORTEX_STUCK_CYCLE_SENTINEL_ENABLED`` (default ``true``).
    _cortex_stuck_enabled = _os.environ.get("CORTEX_STUCK_CYCLE_SENTINEL_ENABLED", "true").lower()
    if _cortex_stuck_enabled not in ("false", "0", "no", "off"):
        from triggers.cortex_stuck_cycle_sentinel import run_cortex_stuck_cycle_sentinel
        scheduler.add_job(
            run_cortex_stuck_cycle_sentinel,
            IntervalTrigger(minutes=5),
            id="cortex_stuck_cycle_sentinel",
            name="Cortex stuck-cycle + archive-failure sentinel (every 5 min)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=300,
        )
        register_expected_job("cortex_stuck_cycle_sentinel", 5 * 60)
        logger.info("Registered: cortex_stuck_cycle_sentinel (every 5 min)")
    else:
        logger.info("Skipped: cortex_stuck_cycle_sentinel (CORTEX_STUCK_CYCLE_SENTINEL_ENABLED=false)")

    # CORTEX_PHASE6_REFLECTOR_1 (Brief 3): hourly Phase 6 Reflector sweep.
    # Trigger B (deferred) per brief §3.5 — finds Reflector-eligible cycles
    # that either (a) have a Triaga decision since last sweep, or (b) have
    # aged past TRIAGA_TTL_DAYS without a decision; updates counters on
    # cited directives + writes proposed-config-deltas.md to vault staging.
    # Idempotent via cortex_phase_outputs partial unique idx on
    # artifact_type='reflector_complete' (Brief 4 migration §3.1).
    # Env gate ``CORTEX_PHASE6_REFLECTOR_ENABLED`` (default ``true``).
    # Cadence override via REFLECTOR_SWEEP_CRON_HOUR / *_MINUTE (cron) or
    # REFLECTOR_SWEEP_INTERVAL_MINUTES (default 60 = hourly).
    _reflector_enabled = _os.environ.get(
        "CORTEX_PHASE6_REFLECTOR_ENABLED", "true"
    ).lower()
    if _reflector_enabled not in ("false", "0", "no", "off"):
        from orchestrator.cortex_phase6_reflector import sweep_pending_cycles_sync
        try:
            _reflector_minutes = int(
                _os.environ.get("REFLECTOR_SWEEP_INTERVAL_MINUTES", "60")
            )
        except (TypeError, ValueError):
            _reflector_minutes = 60
        if _reflector_minutes < 5:
            logger.warning(
                "REFLECTOR_SWEEP_INTERVAL_MINUTES=%s below 5min floor; clamping to 5",
                _reflector_minutes,
            )
            _reflector_minutes = 5
        scheduler.add_job(
            sweep_pending_cycles_sync,
            IntervalTrigger(minutes=_reflector_minutes),
            id="phase6_reflector_sweep",
            name=f"Cortex Phase 6 Reflector sweep (every {_reflector_minutes} min)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        register_expected_job("phase6_reflector_sweep", _reflector_minutes * 60)
        logger.info(
            f"Registered: phase6_reflector_sweep (every {_reflector_minutes} min)"
        )
    else:
        logger.info(
            "Skipped: phase6_reflector_sweep (CORTEX_PHASE6_REFLECTOR_ENABLED=false)"
        )

    # CORTEX_PHASE6_VAULT_RECONCILER_1: Phase 6 reconciler — drift detector
    # for the vault-write-outside-counter-txn gap. Reads cortex_phase_outputs
    # reflector_complete markers and re-emits the vault block when
    # proposed-config-deltas.md is missing or lacks the cycle's block (gap
    # from Reflector vault write happening outside the counter-update txn at
    # cortex_phase6_reflector.py:694 -> :724-737).
    # Env gate ``CORTEX_PHASE6_RECONCILER_ENABLED`` (default ``true``).
    # Cadence: REFLECTOR_RECONCILER_INTERVAL_MINUTES (default 65 min,
    # 5-min stagger from sweep to reduce collision; floor 15 min).
    _reconciler_enabled = _os.environ.get(
        "CORTEX_PHASE6_RECONCILER_ENABLED", "true"
    ).lower()
    if _reconciler_enabled not in ("false", "0", "no", "off"):
        from orchestrator.cortex_phase6_reconciler import reconcile_vault_writes_sync
        try:
            _reconciler_minutes = int(
                _os.environ.get("REFLECTOR_RECONCILER_INTERVAL_MINUTES", "65")
            )
        except (TypeError, ValueError):
            _reconciler_minutes = 65
        if _reconciler_minutes < 15:
            logger.warning(
                "REFLECTOR_RECONCILER_INTERVAL_MINUTES=%s below 15min floor; clamping to 15",
                _reconciler_minutes,
            )
            _reconciler_minutes = 15
        scheduler.add_job(
            reconcile_vault_writes_sync,
            IntervalTrigger(minutes=_reconciler_minutes),
            id="phase6_reconciler",
            name=f"Cortex Phase 6 vault reconciler (every {_reconciler_minutes} min)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        register_expected_job("phase6_reconciler", _reconciler_minutes * 60)
        logger.info(
            f"Registered: phase6_reconciler (every {_reconciler_minutes} min)"
        )
    else:
        logger.info(
            "Skipped: phase6_reconciler (CORTEX_PHASE6_RECONCILER_ENABLED=false)"
        )

    # BRIEF_MOVIE_AM_RETROFIT_1 D5: weekly MOVIE AM vault lint.
    # Sunday 06:05 UTC — offset 5 min from ao_pm_lint to avoid vault-mirror
    # contention. Env gate ``MOVIE_AM_LINT_ENABLED`` (default ``true``)
    # allows kill-switch without redeploy. Separate job from ao_pm_lint so
    # a failure on one doesn't mask the other.
    _movie_lint_enabled = _os.environ.get("MOVIE_AM_LINT_ENABLED", "true").lower()
    if _movie_lint_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _run_movie_am_lint,
            CronTrigger(day_of_week="sun", hour=6, minute=5, timezone="UTC"),
            id="movie_am_lint",
            name="MOVIE AM weekly vault lint (Sunday 06:05 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: movie_am_lint (Sun 06:05 UTC)")
    else:
        logger.info("Skipped: movie_am_lint (MOVIE_AM_LINT_ENABLED=false)")

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

    # WIKI_LINT_1: Karpathy-style weekly wiki health check.
    # 7 checks (4 deterministic, 1 hybrid filesystem+Postgres, 2 LLM-assisted
    # via Gemini 2.5 Pro). Mon 05:00 UTC per spec. Default OFF — first ship
    # is dormant until Director flips ``WIKI_LINT_ENABLED=true`` after a
    # clean dry-run. When BAKER_VAULT_PATH is unset on the host, the runner
    # logs + skips (does not crash the scheduler — mirrors the
    # ``_ai_head_weekly_audit_job`` pattern).
    _wiki_lint_enabled = _os.environ.get("WIKI_LINT_ENABLED", "false").lower()
    if _wiki_lint_enabled in ("true", "1", "yes", "on"):
        scheduler.add_job(
            _wiki_lint_weekly_job,
            CronTrigger(day_of_week="mon", hour=5, minute=0, timezone="UTC"),
            id="wiki_lint_weekly",
            name="Wiki lint weekly (Monday 05:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: wiki_lint_weekly (Mon 05:00 UTC)")
    else:
        logger.info("Skipped: wiki_lint_weekly (WIKI_LINT_ENABLED=false)")

    # VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1 (2026-05-13): vault mirror refresh
    # is now a per-process daemon thread spawned in ``vault_mirror.start_sync_thread``
    # at FastAPI startup. It is NOT registered here because the
    # ``BackgroundScheduler`` is gated by the cross-process singleton lock —
    # only the lock-holding Render replica would run the job, leaving every
    # other replica with a stale local FS mirror (the bug this brief fixed).

    # ROADMAP_DRIFT_CLICKUP_SENTINEL_1: daily 06:00 UTC drift sentinel.
    # Compares cortex-roadmap-current.yml last-edit vs PR merge cadence on
    # baker-vault + baker-master. >=5 PRs since YAML touch -> ClickUp comment
    # on recurring task 86c9k6kau (NO Slack — Director rule 2026-04-30).
    # Env gate ``ROADMAP_DRIFT_SENTINEL_ENABLED`` (default ``true``).
    _roadmap_drift_enabled = _os.environ.get(
        "ROADMAP_DRIFT_SENTINEL_ENABLED", "true"
    ).lower()
    if _roadmap_drift_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _roadmap_drift_sentinel_job,
            CronTrigger(hour=6, minute=0, timezone="UTC"),
            id="roadmap_drift_sentinel",
            name="Roadmap drift sentinel (daily 06:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: roadmap_drift_sentinel (daily 06:00 UTC)")
    else:
        logger.info(
            "Skipped: roadmap_drift_sentinel (ROADMAP_DRIFT_SENTINEL_ENABLED=false)"
        )

    # BRIEF_PROACTIVE_PM_SENTINEL_1: proactive sentinels (env-gated kill-switch).
    # Default enabled; set PROACTIVE_SENTINEL_ENABLED=false to disable both jobs.
    import os as _os
    if _os.environ.get("PROACTIVE_SENTINEL_ENABLED", "true").lower() not in ("0", "false", "off"):
        # Upgrade 1 + core: quiet-thread detection (respects alerts.snoozed_until)
        from orchestrator.proactive_pm_sentinel import detect_quiet_threads as _sentinel_quiet
        scheduler.add_job(
            _sentinel_quiet,
            IntervalTrigger(minutes=30),
            id="sentinel_quiet_thread",
            name="Proactive sentinel — quiet-thread detection",
            coalesce=True, max_instances=1, replace_existing=True,
        )
        register_expected_job("sentinel_quiet_thread", 30 * 60)
        logger.info("Registered: sentinel_quiet_thread (every 30 minutes)")

        # Upgrade 2: dismiss-pattern surface (14-day rolling aggregation)
        from orchestrator.proactive_pm_sentinel import detect_dismiss_patterns as _sentinel_dismiss_patterns
        scheduler.add_job(
            _sentinel_dismiss_patterns,
            IntervalTrigger(hours=6),
            id="sentinel_dismiss_patterns",
            name="Proactive sentinel — dismiss pattern surface",
            coalesce=True, max_instances=1, replace_existing=True,
        )
        register_expected_job("sentinel_dismiss_patterns", 6 * 60 * 60)
        logger.info("Registered: sentinel_dismiss_patterns (every 6 hours)")
    else:
        logger.info("Proactive sentinels DISABLED (PROACTIVE_SENTINEL_ENABLED=false)")

    # CORTEX_TIER_B_RUNTIME_V1: calendar-month Tier B counter-reset audit.
    # Fires 1st of each month at 00:00 UTC. Reset is logical (counters are
    # read-driven from baker_actions); the audit row proves the boundary fired.
    from triggers.tier_b_reset import tier_b_counter_reset
    scheduler.add_job(
        tier_b_counter_reset,
        CronTrigger(day=1, hour=0, minute=0, timezone="UTC"),
        id="tier_b_counter_reset",
        name="Tier B counter reset (calendar-month, UTC)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: tier_b_counter_reset (cron: 1st of month 00:00 UTC)")

    # BRIEF_CORTEX_TIER_B_ATOMICITY_V1: Pattern B sweep.
    # Every 5 min, delete orphan reservations past the 15-min TTL so
    # crashed callers don't leave budget tied up forever.
    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    scheduler.add_job(
        tier_b_reservation_sweep,
        IntervalTrigger(minutes=5),
        id="tier_b_reservation_sweep",
        name="Tier B reservation sweep (orphan reaper)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("tier_b_reservation_sweep", 5 * 60)
    logger.info("Registered: tier_b_reservation_sweep (every 5 min)")

    # BRIEF_APSCHEDULER_VAULT_SCANNER_V1: daily 06:00 UTC vault soft-task +
    # hard-deadline scanner. Writes per-desk today-YYYY-MM-DD.md + today.md +
    # upcoming-deadlines.md mirror files; pushes ONE consolidated Slack DM to
    # Director (per-desk urgent DM only on critical-priority overdue or
    # is_critical hard deadline overdue). Singleton-replica execution via
    # the existing scheduler_lease.py advisory lock. Env gate
    # VAULT_SCANNER_ENABLED (default true) for kill-switch without redeploy.
    _vault_scanner_enabled = _os.environ.get("VAULT_SCANNER_ENABLED", "true").lower()
    if _vault_scanner_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _vault_scanner_job,
            CronTrigger(hour=6, minute=0, timezone="UTC"),
            id="vault_scanner_daily",
            name="Vault task + deadline scanner (06:00 UTC daily)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: vault_scanner_daily (06:00 UTC)")

        # Idempotent startup catch-up: if Render restarted/deployed after
        # 06:00 UTC and no marker file exists for today, fire once now.
        try:
            from triggers.vault_scanner import startup_catchup
            if startup_catchup():
                logger.info("vault_scanner_daily: startup catch-up fired")
        except Exception:
            logger.exception("vault_scanner_daily: startup catch-up raised")
    else:
        logger.info("Skipped: vault_scanner_daily (VAULT_SCANNER_ENABLED=false)")


def _kbl_pipeline_tick_job():
    """APScheduler wrapper around ``kbl.pipeline_tick.main``.

    Lazy import keeps the `kbl.*` stack out of module-load time. Any
    non-zero return (ops-visibility signal) is logged at WARN; the
    job-level listener already handles exceptions.
    """
    try:
        from kbl.pipeline_tick import main as _kbl_main
        rc = _kbl_main()
        if rc != 0:
            logger.warning("kbl_pipeline_tick returned non-zero: %s", rc)
    except Exception as e:
        logger.error("kbl_pipeline_tick raised: %s", e, exc_info=True)
        raise


def _kbl_bridge_tick_job():
    """APScheduler wrapper around ``kbl.bridge.alerts_to_signal.run_bridge_tick``.

    Lazy import mirrors ``_kbl_pipeline_tick_job``. Counts dict goes
    to logger at INFO; any raise propagates so APScheduler's listener
    surfaces the failure.
    """
    try:
        from kbl.bridge.alerts_to_signal import run_bridge_tick
        counts = run_bridge_tick()
        logger.info("kbl_bridge_tick: %s", counts)
    except Exception as e:
        logger.error("kbl_bridge_tick raised: %s", e, exc_info=True)
        raise


HOT_MD_NUDGE_TEXT = (
    "Saturday hot.md refresh.\n\n"
    "Edit baker-vault/_ops/hot.md with this week's focus areas. "
    "Baker syncs within 5 min; matches boost signal priority through the bridge."
)


def _hot_md_weekly_nudge_job():
    """APScheduler wrapper: Saturday hot.md nudge to Director.

    Uses the existing ``outputs/whatsapp_sender.py`` helper — deliberately
    not a parallel WAHA caller (brief §5). Fire-and-forget: if WAHA is
    down, the helper returns ``False`` and we log + swallow per the
    substrate-push contract (brief §5: "don't block on delivery").
    """
    try:
        from outputs.whatsapp_sender import send_whatsapp
    except Exception as e:
        logger.error("hot_md_weekly_nudge: whatsapp_sender import failed: %s", e)
        return

    try:
        # BAKER_WA_DIRECTOR_FILTER_1: Saturday hot.md nudge is a calendar-shaped
        # reminder for Director to edit his weekly focus file — deadline-class.
        ok = send_whatsapp(HOT_MD_NUDGE_TEXT, kind="deadline")
    except Exception as e:
        # Defensive: send_whatsapp already has its own try/except, but a
        # config-level blow-up (e.g., module init on an imported constant)
        # shouldn't propagate out of a scheduler job.
        logger.warning("hot_md_weekly_nudge: send_whatsapp raised: %s", e)
        return

    if ok:
        logger.info("hot_md_weekly_nudge: delivered")
    else:
        logger.warning("hot_md_weekly_nudge: send_whatsapp returned False (WAHA down?)")


def _ai_head_weekly_audit_job():
    """APScheduler wrapper: Monday AI Head self-audit.

    BRIEF_AI_HEAD_WEEKLY_AUDIT_1. Lazy-imports the audit module; swallows
    top-level exceptions as WARN so a single bad week doesn't knock out
    the scheduler. ``run_weekly_audit`` is already non-fatal per step,
    so reaching the outer except here genuinely indicates module-load
    or config failure.
    """
    try:
        from triggers.ai_head_audit import run_weekly_audit
    except Exception as e:
        logger.error("ai_head_weekly_audit: import failed: %s", e)
        return
    try:
        result = run_weekly_audit()
        logger.info("ai_head_weekly_audit: %s", result)
    except Exception as e:
        logger.warning("ai_head_weekly_audit: run raised: %s", e)


def _vault_scanner_job():
    """APScheduler wrapper: daily 06:00 UTC vault scanner.

    BRIEF_APSCHEDULER_VAULT_SCANNER_V1. Lazy-imports the runner; swallows
    top-level exceptions as WARN so a single bad day doesn't knock out
    the scheduler. ``run_scan`` is internally fault-tolerant per step
    (DB unavailable, malformed frontmatter, Slack failure all degrade
    gracefully without raising).
    """
    try:
        from triggers.vault_scanner import run_scan
    except Exception as e:
        logger.error("vault_scanner_daily: import failed: %s", e)
        return
    try:
        result = run_scan()
        logger.info("vault_scanner_daily: %s", result)
    except Exception as e:
        logger.warning("vault_scanner_daily: run raised: %s", e)


def _matter_config_drift_weekly_job():
    """APScheduler wrapper: Monday 11:00 UTC matter-config drift audit.

    CORTEX_3T_FORMALIZE_1C (RA-23 Q6). Mirrors ``_ai_head_weekly_audit_job``:
    lazy-imports the runner, swallows top-level exceptions as WARN so a
    single bad week doesn't knock out the scheduler.
    """
    try:
        from orchestrator.cortex_drift_audit import run_drift_audit
    except Exception as e:
        logger.error("matter_config_drift_weekly: import failed: %s", e)
        return
    try:
        result = run_drift_audit()
        logger.info(
            "matter_config_drift_weekly: %s flagged of %s checked",
            result.get("flagged_count"), result.get("checked"),
        )
    except Exception as e:
        logger.warning("matter_config_drift_weekly: run raised: %s", e)


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


def _roadmap_drift_sentinel_job():
    """APScheduler wrapper: daily 06:00 UTC roadmap drift sentinel.

    ROADMAP_DRIFT_CLICKUP_SENTINEL_1. Lazy-imports the runner; swallows
    top-level exceptions as WARN so a single bad day doesn't knock out
    the scheduler. The runner itself is non-fatal per step (graceful
    no-op on GitHub or ClickUp API failure).
    """
    try:
        from orchestrator.roadmap_drift_sentinel import (
            run_roadmap_drift_sentinel,
        )
    except Exception as e:
        logger.error("roadmap_drift_sentinel: import failed: %s", e)
        return
    try:
        result = run_roadmap_drift_sentinel()
        logger.info("roadmap_drift_sentinel: %s", result)
    except Exception as e:
        logger.warning("roadmap_drift_sentinel: run raised: %s", e)


def _wiki_lint_weekly_job():
    """APScheduler wrapper: Monday 05:00 UTC weekly wiki lint.

    WIKI_LINT_1. Lazy-imports the runner; swallows top-level exceptions
    so a single bad week doesn't knock out the scheduler. The runner
    itself is non-fatal per check and gracefully no-ops when
    ``BAKER_VAULT_PATH`` is unset.
    """
    try:
        from kbl.wiki_lint import run as run_wiki_lint
    except Exception as e:
        logger.error("wiki_lint_weekly: import failed: %s", e)
        return
    try:
        result = run_wiki_lint()
        logger.info("wiki_lint_weekly: %s", result)
    except Exception as e:
        logger.warning("wiki_lint_weekly: run raised: %s", e)


def _run_wiki_lint():
    """CORTEX-PHASE-3: Run wiki lint and log results."""
    try:
        from models.cortex import run_wiki_lint
        findings = run_wiki_lint()
        logger.info("wiki_lint: completed with %d findings", len(findings))
        if findings:
            try:
                from triggers.sentinel_health import report_success
                report_success("wiki_lint", {"findings_count": len(findings)})
            except Exception:
                pass
    except Exception as e:
        logger.error("wiki_lint scheduler failed: %s", e)


def _run_ao_pm_lint():
    """BRIEF_AO_PM_EXTENSION_1: Run AO PM vault lint and log results."""
    try:
        from scripts.lint_ao_pm_vault import main as _ao_lint_main
        _ao_lint_main()
        logger.info("ao_pm_lint: completed")
        try:
            from triggers.sentinel_health import report_success
            report_success("ao_pm_lint", {})
        except Exception:
            pass
    except Exception as e:
        logger.error("ao_pm_lint failed: %s", e)
        try:
            from triggers.sentinel_health import report_failure
            report_failure("ao_pm_lint", str(e))
        except Exception:
            pass


def _run_movie_am_lint():
    """BRIEF_MOVIE_AM_RETROFIT_1 D5: Run MOVIE AM vault lint and log results."""
    try:
        from scripts.lint_movie_am_vault import main as _movie_lint_main
        _movie_lint_main()
        logger.info("movie_am_lint: completed")
        try:
            from triggers.sentinel_health import report_success
            report_success("movie_am_lint", {})
        except Exception:
            pass
    except Exception as e:
        logger.error("movie_am_lint failed: %s", e)
        try:
            from triggers.sentinel_health import report_failure
            report_failure("movie_am_lint", str(e))
        except Exception:
            pass


def _expire_browser_actions():
    """Cancel browser actions that hit the 10-minute timeout. Dismiss linked alerts."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # Find and expire pending actions past their deadline
        cur.execute("""
            UPDATE browser_actions SET status = 'expired', completed_at = NOW()
            WHERE status = 'pending_confirmation' AND expires_at < NOW()
            RETURNING id, alert_id
        """)
        expired = cur.fetchall()
        # Dismiss linked alerts
        for row in expired:
            action_id, alert_id = row
            if alert_id:
                cur.execute("UPDATE alerts SET status = 'dismissed' WHERE id = %s", (alert_id,))
            logger.info(f"Expired browser action #{action_id}")
        conn.commit()
        cur.close()
        if expired:
            logger.info(f"Expired {len(expired)} browser action(s)")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"expire_browser_actions failed: {e}")
    finally:
        store._put_conn(conn)


def _scheduler_heartbeat():
    """SCHEDULER-WATCHDOG-1: Write proof-of-life timestamp to DB every 5 min.

    SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (2026-05-15): watermark is written
    FIRST, before any IO probe. The probe is now diagnostic only — it logs WARN
    on failure but never calls restart_scheduler() from inside the heartbeat
    job thread (reentrancy-hostile: shutdown(wait=True) joins worker threads,
    a thread cannot join itself). The middleware watchdog at
    outputs/dashboard.py is the sole restarter.
    """
    # 1) Write watermark FIRST — proof-of-life is independent of probe latency.
    try:
        from triggers.state import trigger_state
        trigger_state.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Scheduler heartbeat write failed: {e}")

    # 2) Lock-health step (SCHEDULER_NEON_IDLE_HARDEN_1). The heartbeat job is
    # registered ONLY when start_scheduler() acquired the lock (embedded_scheduler
    # :1699-1707 registers NO jobs without it) — so if the heartbeat is running at
    # all, this process is an active scheduler that MUST hold the lock. Therefore a
    # None/dead lock conn means "recover or stand down", NEVER "skip": skipping would
    # let a transient-dropped process keep firing lock-less with a fresh watermark
    # forever (watchdog never trips). Watermark is already written FIRST above, so
    # this step never gates proof-of-life; the bounded probe/reconnect (connect_timeout
    # + keepalives + statement_timeout) cannot hang the job thread past the next fire.
    try:
        import triggers.scheduler_lease as _lease
        held = _lease._held_conn
        need_reacquire = held is None  # lost conn on a prior transient → must recover
        if held is not None:
            try:
                cur = held.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            except Exception as probe_err:
                logger.warning(
                    "scheduler singleton-lock connection probe failed (%s) — "
                    "attempting self-heal reacquire.",
                    probe_err,
                )
                need_reacquire = True
        if need_reacquire:
            outcome = _lease.reacquire_singleton_lock()
            if outcome == _lease.REACQUIRE_REOWNED:
                logger.info(
                    "scheduler singleton-lock reacquired by heartbeat — "
                    "continuing without teardown."
                )
            elif outcome == _lease.REACQUIRE_LOST:
                logger.error(
                    "scheduler singleton-lock now held by another process — "
                    "requesting stand-down (request-thread watchdog restarts off "
                    "the job thread; no self-join)."
                )
                _lease.request_standdown()
            else:  # REACQUIRE_TRANSIENT — indeterminate, retry next heartbeat
                logger.warning(
                    "scheduler singleton-lock reacquire transient-failed — will "
                    "retry next heartbeat (held stays None → routes to reacquire "
                    "again, not skip; watchdog backstop active)."
                )
    except Exception:
        pass  # never fail heartbeat from the lock-health path


def _get_rss_mb():
    """Get current process RSS in MB. Linux: /proc/self/status. Fallback: resource module."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # KB → MB
    except FileNotFoundError:
        pass
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS returns bytes, Linux returns KB
    import sys
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def _memory_watchdog():
    """OOM-PHASE3: Log RSS to baker_memory_log, alert on thresholds."""
    try:
        rss_mb = _get_rss_mb()
        note = None

        # Threshold alerts
        if rss_mb > 3700:
            logger.critical(f"MEMORY EMERGENCY: {rss_mb:.0f} MB (92% of 4 GB) — forcing GC")
            import gc
            gc.collect()
            note = "EMERGENCY — forced GC"
        elif rss_mb > 3400:
            logger.critical(f"MEMORY CRITICAL: {rss_mb:.0f} MB (85% of 4 GB)")
            note = "CRITICAL"
        elif rss_mb > 3000:
            logger.warning(f"MEMORY WARNING: {rss_mb:.0f} MB (75% of 4 GB)")
            note = "WARNING"
        else:
            logger.info(f"Memory watchdog: {rss_mb:.0f} MB RSS")

        # Log to PostgreSQL
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                # Ensure table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS baker_memory_log (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMPTZ DEFAULT NOW(),
                        rss_mb INTEGER,
                        note TEXT
                    )
                """)
                # Log current reading
                cur.execute(
                    "INSERT INTO baker_memory_log (rss_mb, note) VALUES (%s, %s)",
                    (int(rss_mb), note),
                )
                # Purge entries older than 7 days
                cur.execute("DELETE FROM baker_memory_log WHERE timestamp < NOW() - INTERVAL '7 days'")
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning(f"Memory log write failed: {e}")
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Memory watchdog failed (non-fatal): {e}")


def restart_scheduler(reason: str = "unspecified"):
    """SCHEDULER-WATCHDOG-1: Force restart the scheduler. Called by request-time watchdog.

    Uses ``wait=True`` (B1 RCA 2026-04-29 — ``wait=False`` left job-execution
    threads firing without a scheduler reference). Drops the singleton lock
    so the re-acquire path runs cleanly through ``start_scheduler()``.

    SCHEDULER_NEON_IDLE_HARDEN_1: emits a single greppable
    ``SCHEDULER_RESTART reason=<...>`` line so the restart cadence is observable
    and a regression (the ~18-min loop) is caught immediately.
    """
    global _scheduler
    logger.warning("SCHEDULER_RESTART reason=%s — force-restarting scheduler...", reason)
    try:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=True)
            except Exception:
                pass
    except Exception:
        pass
    _scheduler = None
    try:
        from triggers.scheduler_lease import release_singleton_lock
        release_singleton_lock()
    except Exception:
        pass
    start_scheduler()
    logger.warning("SCHEDULER-WATCHDOG-1: Scheduler force-restarted successfully")


def start_scheduler():
    """Create and start the BackgroundScheduler.

    Singleton across processes via PG advisory lock on a dedicated non-pooled
    connection (``triggers.scheduler_lease``). During Render Pro zero-downtime
    deploy overlap, only one container holds the lock at any time. The other
    waits on a 30 s polling thread until the holder dies (SIGTERM closes its
    connection → server-side lock auto-release).

    In-process idempotent — safe to call twice.
    """
    global _scheduler

    # SCHEDULER_JOB_LIVENESS_1 NIT #3: re-stamp the sentinel's cold-start anchor
    # so an in-process restart_scheduler() re-applies the 15-min grace window
    # (mirrors fresh Render restart semantics).
    try:
        from triggers.scheduler_liveness_sentinel import reset_cold_start_anchor
        reset_cold_start_anchor()
    except Exception:
        pass

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running — skipping start")
        return

    from triggers.scheduler_lease import acquire_singleton_lock
    held_conn = acquire_singleton_lock()
    if held_conn is None:
        logger.warning(
            "scheduler singleton lock unavailable — registering NO jobs. "
            "Lock-poll thread will retry every 30s and start jobs on acquisition."
        )
        _spawn_lock_retry_thread()
        return

    _scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        }
    )
    _scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    _register_jobs(_scheduler)
    # SCHEDULER_LIVENESS_REVIVE_1 (optional, defense-in-depth): non-fatal
    # self-presence check. get_jobs() is valid pre-start. Log-not-raise: the
    # _start_scheduler() wrapper (outputs/dashboard.py) only logs on failure and
    # continues boot, so a raise here would NOT abort — it would silently boot
    # scheduler-less. So we surface absence loudly in logs without aborting.
    if "scheduler_job_liveness" in {j.id for j in _scheduler.get_jobs()}:
        logger.info("Self-bootstrap OK: scheduler_job_liveness present")
    else:
        logger.error("Self-bootstrap WARNING: scheduler_job_liveness NOT registered")
    _scheduler.start()
    logger.info(f"BackgroundScheduler started with {len(_scheduler.get_jobs())} jobs")


def _spawn_lock_retry_thread() -> None:
    """Background poll thread — retries singleton-lock acquisition every 30 s.

    On success, calls ``start_scheduler()`` to register jobs + start. Daemon
    thread so SIGTERM never blocks on the poller. Idempotent: skips spawn if
    a retry thread is already alive.
    """
    import threading
    global _lock_retry_thread
    if _lock_retry_thread is not None and _lock_retry_thread.is_alive():
        return

    def _poll():
        import time
        while True:
            time.sleep(30)
            if _scheduler is not None and _scheduler.running:
                logger.info(
                    "scheduler started by another path — retry thread exiting"
                )
                return
            from triggers.scheduler_lease import acquire_singleton_lock
            held = acquire_singleton_lock()
            if held is not None:
                logger.info(
                    "scheduler singleton lock acquired on retry — starting jobs"
                )
                start_scheduler()
                return

    _lock_retry_thread = threading.Thread(
        target=_poll, name="scheduler-lock-retry", daemon=True
    )
    _lock_retry_thread.start()


def stop_scheduler():
    """Graceful shutdown. Idempotent. Releases singleton lock on success."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("BackgroundScheduler stopped")
    _scheduler = None
    try:
        from triggers.scheduler_lease import release_singleton_lock
        release_singleton_lock()
    except Exception as e:
        logger.warning(f"Singleton lock release failed (non-fatal): {e}")


def get_scheduler_status() -> dict:
    """Return scheduler health for /api/scheduler-status endpoint."""
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": [], "job_count": 0}

    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })

    return {
        "running": True,
        "job_count": len(jobs),
        "jobs": jobs,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
