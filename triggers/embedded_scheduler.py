"""
Embedded Sentinel Scheduler — BackgroundScheduler for FastAPI integration.

Replaces the standalone BlockingScheduler (triggers/scheduler.py) which
never ran on Render because uvicorn only starts dashboard.py.

Called by dashboard.py on startup/shutdown events.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

logger = logging.getLogger("sentinel.embedded_scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def _job_listener(event):
    """Log job execution results."""
    if event.exception:
        logger.error(
            f"Job {event.job_id} failed: {event.exception}",
            exc_info=event.traceback,
        )
    else:
        logger.info(f"Job {event.job_id} completed successfully")


def _register_jobs(scheduler: BackgroundScheduler):
    """Register all Sentinel trigger jobs.

    Mirrors triggers/scheduler.py SentinelScheduler._register_jobs() exactly.
    All imports are lazy (inside function) to avoid circular imports.
    """
    from config.settings import config

    # Email polling — every 5 minutes
    from triggers.email_trigger import check_new_emails
    scheduler.add_job(
        check_new_emails,
        IntervalTrigger(seconds=config.triggers.email_check_interval),
        id="email_poll", name="Gmail polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: email_poll (every {config.triggers.email_check_interval}s)")

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
    logger.info(f"Registered: fireflies_scan (every {config.triggers.fireflies_scan_interval}s)")

    # ClickUp polling — every 5 minutes
    from triggers.clickup_trigger import run_clickup_poll
    scheduler.add_job(
        run_clickup_poll,
        IntervalTrigger(minutes=5),
        id="clickup_poll", name="ClickUp multi-workspace poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: clickup_poll (every 5 minutes)")

    # Dropbox polling — every 30 minutes
    from triggers.dropbox_trigger import run_dropbox_poll
    scheduler.add_job(
        run_dropbox_poll,
        IntervalTrigger(seconds=config.triggers.dropbox_check_interval),
        id="dropbox_poll", name="Dropbox folder polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: dropbox_poll (every {config.triggers.dropbox_check_interval}s)")

    # Todoist polling — every 30 minutes
    from triggers.todoist_trigger import run_todoist_poll
    scheduler.add_job(
        run_todoist_poll,
        IntervalTrigger(seconds=config.triggers.todoist_check_interval),
        id="todoist_poll", name="Todoist task polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: todoist_poll (every {config.triggers.todoist_check_interval}s)")

    # Whoop polling — every 24 hours (daily health data)
    # next_run_time=now ensures first poll fires on startup, not after 24h.
    # Without this, every redeploy resets the 24h timer and poll never fires.
    from triggers.whoop_trigger import run_whoop_poll
    scheduler.add_job(
        run_whoop_poll,
        IntervalTrigger(seconds=config.triggers.whoop_check_interval),
        id="whoop_poll", name="Whoop health polling",
        coalesce=True, max_instances=1, replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info(f"Registered: whoop_poll (every {config.triggers.whoop_check_interval}s, first run: NOW)")

    # RSS polling — every 60 minutes (RSS-1)
    from triggers.rss_trigger import run_rss_poll
    scheduler.add_job(
        run_rss_poll,
        IntervalTrigger(seconds=config.triggers.rss_check_interval),
        id="rss_poll", name="RSS feed polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: rss_poll (every {config.triggers.rss_check_interval}s)")

    # Slack polling — every 5 minutes (SLACK-1 S2)
    from triggers.slack_trigger import run_slack_poll
    scheduler.add_job(
        run_slack_poll,
        IntervalTrigger(seconds=config.triggers.slack_check_interval),
        id="slack_poll", name="Slack channel polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: slack_poll (every {config.triggers.slack_check_interval}s)")

    # Browser task polling — every 30 minutes (BROWSER-1)
    from triggers.browser_trigger import run_browser_poll
    scheduler.add_job(
        run_browser_poll,
        IntervalTrigger(seconds=config.triggers.browser_check_interval),
        id="browser_poll", name="Browser task polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: browser_poll (every {config.triggers.browser_check_interval}s)")

    # WhatsApp re-sync — every 6 hours (catch missed webhook messages)
    from scripts.extract_whatsapp import backfill_whatsapp
    scheduler.add_job(
        backfill_whatsapp,
        IntervalTrigger(seconds=21600),
        id="whatsapp_resync", name="WhatsApp periodic re-sync",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: whatsapp_resync (every 6 hours)")

    # Daily briefing — 06:00 UTC (08:00 CET)
    from triggers.briefing_trigger import generate_morning_briefing
    scheduler.add_job(
        generate_morning_briefing,
        CronTrigger(hour=config.triggers.daily_briefing_hour, minute=0),
        id="daily_briefing", name="Morning briefing",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: daily_briefing (at {config.triggers.daily_briefing_hour:02d}:00 UTC)")

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
    logger.info("Registered: deadline_cadence (every 60 minutes)")

    # VIP SLA monitoring — every 5 minutes (DECISION-ENGINE-1A)
    from orchestrator.decision_engine import run_vip_sla_check
    scheduler.add_job(
        run_vip_sla_check,
        IntervalTrigger(minutes=5),
        id="vip_sla_check", name="VIP SLA monitoring",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: vip_sla_check (every 5 minutes)")

    # Commitment overdue check — every 6 hours (Phase 3C)
    from orchestrator.commitment_checker import run_commitment_check
    scheduler.add_job(
        run_commitment_check,
        IntervalTrigger(hours=6),
        id="commitment_check", name="Commitment overdue check",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: commitment_check (every 6 hours)")

    # Calendar polling + meeting prep — every 15 minutes (Phase 3A)
    from triggers.calendar_trigger import check_calendar_and_prep
    scheduler.add_job(
        check_calendar_and_prep,
        IntervalTrigger(minutes=15),
        id="calendar_prep", name="Calendar meeting prep",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: calendar_prep (every 15 minutes)")

    # Alert auto-expiry — every 6 hours (COCKPIT-V3 Phase C)
    from orchestrator.pipeline import run_alert_expiry_check
    scheduler.add_job(
        run_alert_expiry_check,
        IntervalTrigger(hours=6),
        id="alert_expiry", name="Alert auto-expiry (T2-T4, 3-day rule)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: alert_expiry (every 6 hours)")

    # Proactive signal scanner — every 30 minutes (PROACTIVE-FLAG-AO)
    from triggers.proactive_scanner import run_proactive_scan
    scheduler.add_job(
        run_proactive_scan,
        IntervalTrigger(minutes=30),
        id="proactive_scan", name="Proactive signal scanner",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: proactive_scan (every 30 minutes)")

    # Communication gap tracker — every 6 hours (PROACTIVE-FLAG-AO)
    from triggers.proactive_scanner import run_communication_gap_check
    scheduler.add_job(
        run_communication_gap_check,
        IntervalTrigger(hours=6),
        id="communication_gap_check", name="Communication gap tracker",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: communication_gap_check (every 6 hours)")


def start_scheduler():
    """Create and start the BackgroundScheduler. Idempotent — safe to call twice."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running — skipping start")
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
    _scheduler.start()
    logger.info(f"BackgroundScheduler started with {len(_scheduler.get_jobs())} jobs")


def stop_scheduler():
    """Graceful shutdown. Idempotent."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("BackgroundScheduler stopped")
    _scheduler = None


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
