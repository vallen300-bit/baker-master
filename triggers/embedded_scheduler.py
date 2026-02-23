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

    # WhatsApp polling — every 10 minutes
    from triggers.whatsapp_trigger import check_new_whatsapp
    scheduler.add_job(
        check_new_whatsapp,
        IntervalTrigger(seconds=config.triggers.whatsapp_check_interval),
        id="whatsapp_poll", name="WhatsApp polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: whatsapp_poll (every {config.triggers.whatsapp_check_interval}s)")

    # Fireflies scanning — every 2 hours
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
    from triggers.whoop_trigger import run_whoop_poll
    scheduler.add_job(
        run_whoop_poll,
        IntervalTrigger(seconds=config.triggers.whoop_check_interval),
        id="whoop_poll", name="Whoop health polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: whoop_poll (every {config.triggers.whoop_check_interval}s)")

    # Daily briefing — 06:00 UTC (08:00 CET)
    from triggers.briefing_trigger import generate_morning_briefing
    scheduler.add_job(
        generate_morning_briefing,
        CronTrigger(hour=config.triggers.daily_briefing_hour, minute=0),
        id="daily_briefing", name="Morning briefing",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: daily_briefing (at {config.triggers.daily_briefing_hour:02d}:00 UTC)")


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
