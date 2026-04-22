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

    # Plaud Note Pro scanning — every 15 minutes
    if config.plaud.api_token:
        from triggers.plaud_trigger import check_new_plaud_recordings
        scheduler.add_job(
            check_new_plaud_recordings,
            IntervalTrigger(seconds=config.triggers.plaud_scan_interval),
            id="plaud_scan", name="Plaud Note Pro scanning",
            coalesce=True, max_instances=1, replace_existing=True,
        )
        logger.info(f"Registered: plaud_scan (every {config.triggers.plaud_scan_interval}s)")
    else:
        logger.info("Plaud trigger: PLAUD_TOKEN not set — skipping registration")

    # ClickUp polling — every 5 minutes
    # DEPLOY-FIX-2: Defer first run by 90s to avoid rate-limit sleeps blocking
    # Render's deploy timeout window (ClickUp 5-workspace sync can take 2+ min)
    from triggers.clickup_trigger import run_clickup_poll
    from datetime import timedelta
    scheduler.add_job(
        run_clickup_poll,
        IntervalTrigger(minutes=5),
        id="clickup_poll", name="ClickUp multi-workspace poll",
        coalesce=True, max_instances=1, replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
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

    # WEALTH-MANAGER: Edita's Dropbox feed — every 30 minutes
    from triggers.dropbox_trigger import run_edita_dropbox_poll
    scheduler.add_job(
        run_edita_dropbox_poll,
        IntervalTrigger(seconds=config.triggers.dropbox_check_interval),
        id="dropbox_edita_poll", name="Edita Dropbox folder polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: dropbox_edita_poll (Edita-Feed)")

    # Todoist polling — every 30 minutes
    from triggers.todoist_trigger import run_todoist_poll
    scheduler.add_job(
        run_todoist_poll,
        IntervalTrigger(seconds=config.triggers.todoist_check_interval),
        id="todoist_poll", name="Todoist task polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info(f"Registered: todoist_poll (every {config.triggers.todoist_check_interval}s)")

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
    logger.info("Registered: calendar_prep (every 15 minutes)")

    # Alert auto-expiry — every 6 hours (COCKPIT-V3 Phase C)
    from orchestrator.pipeline import run_alert_expiry_check, auto_dismiss_past_travel
    scheduler.add_job(
        run_alert_expiry_check,
        IntervalTrigger(hours=1),
        id="alert_expiry", name="Alert expiry + snooze reactivation (hourly)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: alert_expiry (every 1 hour — includes snooze reactivation)")

    # TRAVEL-HYGIENE-1: Auto-dismiss travel alerts after midnight CET on departure day
    scheduler.add_job(
        auto_dismiss_past_travel,
        IntervalTrigger(hours=1),
        id="dismiss_past_travel", name="Dismiss past travel alerts (hourly, midnight CET)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: dismiss_past_travel (every 1 hour — midnight CET expiry)")

    # Proactive signal scanner — every 30 minutes (PROACTIVE-FLAG-AO)
    from triggers.proactive_scanner import run_proactive_scan
    scheduler.add_job(
        run_proactive_scan,
        IntervalTrigger(minutes=30),
        id="proactive_scan", name="Proactive signal scanner",
        coalesce=True, max_instances=1, replace_existing=True,
    )
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
    logger.info("Registered: stale_watermark_check (every 6 hours)")

    # F1: Compounding risk detector — every 2 hours (Session 26)
    from orchestrator.risk_detector import run_risk_detection
    scheduler.add_job(
        run_risk_detection,
        IntervalTrigger(hours=2),
        id="risk_detection", name="Compounding risk detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
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
    logger.info("Registered: cadence_tracker (every 6 hours)")

    # G5: Health watchdog — every 2 hours (Session 27)
    from triggers.sentinel_health import run_health_watchdog
    scheduler.add_job(
        run_health_watchdog,
        IntervalTrigger(hours=2),
        id="health_watchdog", name="Health watchdog (WA alert if stuck)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: health_watchdog (every 2 hours)")

    # WAHA-SILENT-GUARD-1: Detect WhatsApp inbound silence
    from triggers.sentinel_health import check_waha_silence
    scheduler.add_job(
        check_waha_silence,
        IntervalTrigger(hours=2),
        id="waha_silence_check", name="WAHA inbound silence detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_silence_check (every 2 hours)")

    # WAHA-SILENT-GUARD-1: Active WAHA session health poll
    from triggers.sentinel_health import poll_waha_session
    scheduler.add_job(
        poll_waha_session,
        IntervalTrigger(minutes=30),
        id="waha_session_poll", name="WAHA session health poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: waha_session_poll (every 30 minutes)")

    # F4: Financial signal detector — every 6 hours (Session 27)
    from orchestrator.financial_detector import run_financial_detection
    scheduler.add_job(
        run_financial_detection,
        IntervalTrigger(hours=6),
        id="financial_detector", name="Financial signal detector",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: financial_detector (every 6 hours)")

    # Document pipeline job queue drain — every 2 minutes (PIPELINE-JOBQUEUE-1)
    from tools.document_pipeline import drain_doc_pipeline
    scheduler.add_job(
        drain_doc_pipeline,
        IntervalTrigger(minutes=2),
        id="doc_pipeline_drain", name="Document pipeline job queue",
        coalesce=True, max_instances=1, replace_existing=True,
    )
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
    logger.info("Registered: expire_browser_actions (every 5 min)")

    # SCHEDULER-WATCHDOG-1: Heartbeat — proof of life every 5 min
    scheduler.add_job(
        _scheduler_heartbeat,
        IntervalTrigger(minutes=5),
        id="scheduler_heartbeat", name="Scheduler heartbeat",
        coalesce=True, max_instances=1, replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # Run immediately on startup
    )
    logger.info("Registered: scheduler_heartbeat (every 5 min)")

    # OOM-PHASE3: Memory watchdog — log RSS every 5 min, alert on thresholds
    scheduler.add_job(
        _memory_watchdog,
        IntervalTrigger(minutes=5),
        id="memory_watchdog", name="Memory watchdog",
        coalesce=True, max_instances=1, replace_existing=True,
    )
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

    # SOT_OBSIDIAN_1_PHASE_D: pull the baker-vault mirror so Cowork's
    # MCP vault-read tools stay fresh. Default 300 s, floor 60 s
    # enforced inside ``vault_mirror.sync_interval_seconds``.
    try:
        from vault_mirror import sync_interval_seconds as _vault_interval
        _vault_sync_seconds = _vault_interval()
    except Exception:
        _vault_sync_seconds = 300
    scheduler.add_job(
        _vault_sync_tick_job,
        IntervalTrigger(seconds=_vault_sync_seconds),
        id="vault_sync_tick", name="Vault mirror pull (baker-vault _ops/)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info(f"Registered: vault_sync_tick (every {_vault_sync_seconds}s)")


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
        ok = send_whatsapp(HOT_MD_NUDGE_TEXT)
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


def _vault_sync_tick_job():
    """APScheduler wrapper around ``vault_mirror.sync_tick``.

    ``sync_tick`` already swallows pull failures as WARN; any raise
    here is genuinely unexpected (git binary missing, disk full, etc.)
    — let APScheduler's listener surface it.
    """
    try:
        from vault_mirror import sync_tick
        sync_tick()
    except Exception as e:
        logger.error("vault_sync_tick raised: %s", e, exc_info=True)
        raise


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
    """SCHEDULER-WATCHDOG-1: Write proof-of-life timestamp to DB every 5 min."""
    try:
        from triggers.state import trigger_state
        trigger_state.set_watermark("scheduler_heartbeat", datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Scheduler heartbeat write failed: {e}")


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


def restart_scheduler():
    """SCHEDULER-WATCHDOG-1: Force restart the scheduler. Called by request-time watchdog."""
    global _scheduler
    logger.warning("SCHEDULER-WATCHDOG-1: Force-restarting scheduler...")
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None
    start_scheduler()
    logger.warning("SCHEDULER-WATCHDOG-1: Scheduler force-restarted successfully")


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
