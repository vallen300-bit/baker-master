"""
Sentinel Trigger Scheduler
Manages all automated data source polling and scheduled tasks.

Usage:
    python3 -m triggers.scheduler
    python3 triggers/scheduler.py
"""
import logging
import signal
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from config.settings import config

logger = logging.getLogger("sentinel.scheduler")


def _job_listener(event):
    """Log job execution results."""
    if event.exception:
        logger.error(
            f"Job {event.job_id} failed: {event.exception}",
            exc_info=event.traceback,
        )
    else:
        logger.info(f"Job {event.job_id} completed successfully")


class SentinelScheduler:
    """
    Central coordinator for all Sentinel automated triggers.
    Uses APScheduler with blocking mode for foreground operation.
    """

    def __init__(self):
        self.scheduler = BlockingScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            }
        )
        self.scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self._register_jobs()

    def _register_jobs(self):
        """Register all trigger jobs."""

        # -------------------------------------------------------
        # Email polling — every 5 minutes
        # -------------------------------------------------------
        from triggers.email_trigger import check_new_emails
        self.scheduler.add_job(
            check_new_emails,
            IntervalTrigger(seconds=config.triggers.email_check_interval),
            id="email_poll",
            name="Gmail polling",
        )
        logger.info(
            f"Registered: email_poll (every {config.triggers.email_check_interval}s)"
        )

        # -------------------------------------------------------
        # WhatsApp polling — every 10 minutes
        # -------------------------------------------------------
        from triggers.whatsapp_trigger import check_new_whatsapp
        self.scheduler.add_job(
            check_new_whatsapp,
            IntervalTrigger(seconds=config.triggers.whatsapp_check_interval),
            id="whatsapp_poll",
            name="WhatsApp polling",
        )
        logger.info(
            f"Registered: whatsapp_poll (every {config.triggers.whatsapp_check_interval}s)"
        )

        # -------------------------------------------------------
        # Fireflies scanning — every 2 hours
        # -------------------------------------------------------
        from triggers.fireflies_trigger import check_new_transcripts
        self.scheduler.add_job(
            check_new_transcripts,
            IntervalTrigger(seconds=config.triggers.fireflies_scan_interval),
            id="fireflies_scan",
            name="Fireflies scanning",
        )
        logger.info(
            f"Registered: fireflies_scan (every {config.triggers.fireflies_scan_interval}s)"
        )

        # -------------------------------------------------------
        # ClickUp polling — every 5 minutes
        # -------------------------------------------------------
        from triggers.clickup_trigger import run_clickup_poll
        self.scheduler.add_job(
            run_clickup_poll,
            IntervalTrigger(minutes=5),
            id="clickup_poll",
            name="ClickUp multi-workspace poll",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info("Registered: clickup_poll (every 5 minutes)")

        # -------------------------------------------------------
        # Dropbox polling — every 30 minutes
        # -------------------------------------------------------
        from triggers.dropbox_trigger import run_dropbox_poll
        self.scheduler.add_job(
            run_dropbox_poll,
            IntervalTrigger(seconds=config.triggers.dropbox_check_interval),
            id="dropbox_poll",
            name="Dropbox folder polling",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            f"Registered: dropbox_poll (every {config.triggers.dropbox_check_interval}s)"
        )

        # -------------------------------------------------------
        # Todoist polling — every 30 minutes
        # -------------------------------------------------------
        from triggers.todoist_trigger import run_todoist_poll
        self.scheduler.add_job(
            run_todoist_poll,
            IntervalTrigger(seconds=config.triggers.todoist_check_interval),
            id="todoist_poll",
            name="Todoist task polling",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            f"Registered: todoist_poll (every {config.triggers.todoist_check_interval}s)"
        )

        # -------------------------------------------------------
        # Daily briefing — 08:00 CET (06:00 UTC)
        # -------------------------------------------------------
        from triggers.briefing_trigger import generate_morning_briefing
        self.scheduler.add_job(
            generate_morning_briefing,
            CronTrigger(hour=config.triggers.daily_briefing_hour, minute=0),
            id="daily_briefing",
            name="Morning briefing",
        )
        logger.info(
            f"Registered: daily_briefing (at {config.triggers.daily_briefing_hour:02d}:00 UTC)"
        )

    def list_jobs(self):
        """Print all registered jobs."""
        jobs = self.scheduler.get_jobs()
        print(f"\nSentinel Scheduler — {len(jobs)} jobs registered:")
        print("-" * 60)
        for job in jobs:
            try:
                next_run = getattr(job, "next_run_time", None)
                next_str = next_run.strftime("%Y-%m-%d %H:%M:%S %Z") if next_run else "pending"
            except Exception:
                next_str = "pending (scheduler not started)"
            print(f"  {job.id:<20s} | {job.name:<25s} | next: {next_str}")
        print("-" * 60)

    def start(self):
        """Start the scheduler (blocking)."""
        logger.info("=" * 60)
        logger.info("Sentinel Trigger Scheduler starting...")
        logger.info("=" * 60)
        self.list_jobs()
        print("\nPress Ctrl+C to stop.\n")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler shutdown requested")
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")


def main():
    """CLI entry point."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Sentinel Trigger Scheduler")
    parser.add_argument(
        "--list", action="store_true",
        help="List registered jobs and exit (don't start scheduler)",
    )
    parser.add_argument(
        "--run-once", type=str, default=None,
        choices=["email", "whatsapp", "fireflies", "briefing", "clickup", "todoist", "dropbox"],
        help="Run a single trigger immediately and exit",
    )
    args = parser.parse_args()

    if args.run_once:
        logger.info(f"Running single trigger: {args.run_once}")
        if args.run_once == "email":
            from triggers.email_trigger import check_new_emails
            check_new_emails()
        elif args.run_once == "whatsapp":
            from triggers.whatsapp_trigger import check_new_whatsapp
            check_new_whatsapp()
        elif args.run_once == "fireflies":
            from triggers.fireflies_trigger import check_new_transcripts
            check_new_transcripts()
        elif args.run_once == "briefing":
            from triggers.briefing_trigger import generate_morning_briefing
            generate_morning_briefing()
        elif args.run_once == "clickup":
            from triggers.clickup_trigger import run_clickup_poll
            run_clickup_poll()
        elif args.run_once == "todoist":
            from triggers.todoist_trigger import run_todoist_poll
            run_todoist_poll()
        elif args.run_once == "dropbox":
            from triggers.dropbox_trigger import run_dropbox_poll
            run_dropbox_poll()
        return

    scheduler = SentinelScheduler()

    if args.list:
        scheduler.list_jobs()
        return

    # Handle SIGTERM gracefully
    def handle_sigterm(signum, frame):
        logger.info("SIGTERM received")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    scheduler.start()


if __name__ == "__main__":
    main()
