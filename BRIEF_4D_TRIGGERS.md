# Brief 4D — Trigger System (Automated Polling + Briefings)

**From:** Cowork (Architect)
**To:** Claude Code (Builder)
**Date:** 2026-02-19
**Status:** READY TO EXECUTE (after Briefs 4B + 4C complete)

---

## Context

Baker's pipeline runs 5 steps: Trigger → Retrieve → Augment → Generate → Store Back. The pipeline itself (Steps 2–5) is built and working. What's missing is **Step 1 — automated triggers** that fire the pipeline without manual input.

Currently, the only way to trigger Baker is via CLI:
```bash
python3 orchestrator/pipeline.py "What's happening with deal X?"
```

This brief builds the automated trigger layer that polls data sources and fires the pipeline when new content arrives.

**Config reference** (`config/settings.py` → `TriggerConfig`):
- Email: every 5 minutes
- WhatsApp: every 10 minutes
- Fireflies: every 2 hours
- Daily briefing: 06:00 UTC (08:00 CET)
- Approval reminders: every 3 hours

---

## Architecture

```
triggers/
├── scheduler.py          # APScheduler master — starts/stops all jobs
├── email_trigger.py      # Polls Gmail for new threads
├── fireflies_trigger.py  # Scans for new transcripts
├── whatsapp_trigger.py   # Checks for new WhatsApp messages
└── briefing_trigger.py   # Daily morning briefing generation
```

All triggers follow the same pattern:
1. Check for new content since last watermark
2. If new content found → create `TriggerEvent` objects
3. For each `TriggerEvent` → call `SentinelPipeline.run(trigger)`
4. Update watermark

---

## Task 1 — Scheduler (`triggers/scheduler.py`)

The central coordinator using APScheduler.

```python
"""
Sentinel Trigger Scheduler
Manages all automated data source polling and scheduled tasks.
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config.settings import config

class SentinelScheduler:
    def __init__(self):
        self.scheduler = BlockingScheduler()
        self._register_jobs()

    def _register_jobs(self):
        # Email polling — every 5 minutes
        from triggers.email_trigger import check_new_emails
        self.scheduler.add_job(
            check_new_emails,
            IntervalTrigger(seconds=config.triggers.email_check_interval),
            id="email_poll",
            name="Gmail polling",
            max_instances=1,
            coalesce=True,
        )

        # WhatsApp polling — every 10 minutes
        from triggers.whatsapp_trigger import check_new_whatsapp
        self.scheduler.add_job(
            check_new_whatsapp,
            IntervalTrigger(seconds=config.triggers.whatsapp_check_interval),
            id="whatsapp_poll",
            name="WhatsApp polling",
            max_instances=1,
            coalesce=True,
        )

        # Fireflies scanning — every 2 hours
        from triggers.fireflies_trigger import check_new_transcripts
        self.scheduler.add_job(
            check_new_transcripts,
            IntervalTrigger(seconds=config.triggers.fireflies_scan_interval),
            id="fireflies_scan",
            name="Fireflies scanning",
            max_instances=1,
            coalesce=True,
        )

        # Daily briefing — 08:00 CET (06:00 UTC)
        from triggers.briefing_trigger import generate_morning_briefing
        self.scheduler.add_job(
            generate_morning_briefing,
            CronTrigger(hour=config.triggers.daily_briefing_hour, minute=0),
            id="daily_briefing",
            name="Morning briefing",
        )

    def start(self):
        """Start the scheduler (blocking)."""
        logger.info("Sentinel Trigger Scheduler starting...")
        self.scheduler.start()

    def stop(self):
        """Graceful shutdown."""
        self.scheduler.shutdown(wait=True)
```

**CLI entry point:**
```bash
python3 -m triggers.scheduler
# or
python3 triggers/scheduler.py
```

**Dependencies:**
```bash
pip install apscheduler
```

---

## Task 2 — Email Trigger (`triggers/email_trigger.py`)

Wraps the `extract_gmail.py --mode poll` functionality into a pipeline trigger.

**Logic:**
1. Call `extract_gmail.py` poll mode (or import its poll function directly)
2. Read the incremental JSON output
3. For each new thread → create `TriggerEvent(type="email", ...)`
4. Run pipeline for high/medium priority threads
5. Queue low-priority threads for daily briefing

**State file:** `config/gmail_poll_state.json` (managed by extract_gmail.py)

**Key design:**
- Don't run the full pipeline for every single email. Apply the **noise filter** first (already in extract_gmail.py).
- Only fire pipeline for threads where Baker's contact is known OR the email seems business-substantive.
- Batch low-priority emails into the daily briefing instead of processing individually.

```python
def check_new_emails():
    """Called by scheduler every 5 minutes."""
    # 1. Run Gmail poll
    new_threads = poll_gmail()  # returns list of thread dicts

    if not new_threads:
        return

    # 2. Classify and route
    pipeline = SentinelPipeline()
    batch_for_briefing = []

    for thread in new_threads:
        trigger = TriggerEvent(
            type="email",
            content=thread["text"],
            source_id=thread["metadata"]["thread_id"],
            contact_name=thread["metadata"].get("primary_sender"),
        )
        trigger = pipeline.classify_trigger(trigger)

        if trigger.priority in ("high", "medium"):
            pipeline.run(trigger)
        else:
            batch_for_briefing.append(trigger)

    # 3. Store batch for daily briefing
    if batch_for_briefing:
        save_to_briefing_queue(batch_for_briefing)
```

---

## Task 3 — Fireflies Trigger (`triggers/fireflies_trigger.py`)

Checks for new meeting transcripts not yet ingested.

**Logic:**
1. Query Fireflies API for transcripts since last scan
2. For each new transcript → extract summary + action items
3. Create `TriggerEvent(type="meeting", ...)`
4. Run pipeline (meetings are always medium+ priority)
5. Ingest full transcript into Qdrant via `bulk_ingest.py`

**State tracking:** Use `trigger_log` table in PostgreSQL (check if `source_id` already processed).

**Note:** `extract_fireflies.py` already handles the API call and JSON formatting. Import and reuse its functions rather than rewriting.

---

## Task 4 — WhatsApp Trigger (`triggers/whatsapp_trigger.py`)

Checks for new WhatsApp messages via Wassenger API.

**Logic:**
1. Use Wassenger API to check for new messages since last watermark
2. Group messages by contact/chat
3. For substantive messages → create `TriggerEvent(type="whatsapp", ...)`
4. Run pipeline for known contacts or high-priority signals

**State tracking:** Watermark in `config/whatsapp_poll_state.json`

**Important:** The Wassenger MCP is already connected for live Cowork sessions. For the automated trigger, use the Wassenger REST API directly (the MCP won't be available in headless mode). API key is in `.env`.

---

## Task 5 — Daily Briefing (`triggers/briefing_trigger.py`)

Generates the morning briefing at 08:00 CET.

**Logic:**
1. Gather all batched low-priority triggers from the past 24 hours
2. Query PostgreSQL for pending alerts
3. Query Qdrant for recent context across all collections
4. Create a single `TriggerEvent(type="scheduled", content="Morning briefing request")`
5. Run pipeline with a special briefing prompt template
6. Deliver output to:
   - Slack #cockpit channel (via webhook)
   - Store as markdown in `analysis_outputs/`

**Briefing format** (Baker should produce):
```
BAKER MORNING BRIEFING — [Date]

🔴 IMMEDIATE (Tier 1)
- [alert summaries]

🟡 TODAY (Tier 2)
- [items needing attention within 24h]

📊 RADAR
- [deal updates, project status, people waiting]

📬 OVERNIGHT
- [summary of emails/messages received since last briefing]

📋 DECISIONS PENDING
- [any draft messages awaiting CEO approval]
```

---

## Task 6 — Watermark / State Management

Create a simple utility module `triggers/state.py`:

```python
class TriggerState:
    """Manages watermarks and state files for trigger polling."""

    def __init__(self, state_dir: str = "config/"):
        self.state_dir = Path(state_dir)

    def get_watermark(self, source: str) -> datetime:
        """Get last-processed timestamp for a source."""

    def set_watermark(self, source: str, timestamp: datetime):
        """Update watermark after successful processing."""

    def get_briefing_queue(self) -> list:
        """Get queued low-priority items for daily briefing."""

    def add_to_briefing_queue(self, items: list):
        """Add low-priority items to briefing queue."""

    def clear_briefing_queue(self):
        """Clear after morning briefing generated."""
```

State files: JSON files in `config/` (same pattern as `gmail_poll_state.json`).

---

## Dependencies

```bash
pip install apscheduler
```

APScheduler handles cron expressions, interval triggers, job persistence, and graceful shutdown. It's the standard choice for Python background scheduling.

---

## Running the System

```bash
# Start all triggers (foreground, for testing)
python3 -m triggers.scheduler

# Or run individual triggers manually
python3 -c "from triggers.email_trigger import check_new_emails; check_new_emails()"
python3 -c "from triggers.fireflies_trigger import check_new_transcripts; check_new_transcripts()"
python3 -c "from triggers.briefing_trigger import generate_morning_briefing; generate_morning_briefing()"
```

For production (Punch 5): The scheduler will run as a systemd service on Azure App Service.

---

## Success Criteria

1. ✅ Scheduler starts and registers all 4 jobs
2. ✅ Email trigger polls Gmail and fires pipeline for new substantive threads
3. ✅ Fireflies trigger detects new transcripts and ingests them
4. ✅ WhatsApp trigger detects new messages from known contacts
5. ✅ Daily briefing generates at 08:00 CET and posts to Slack
6. ✅ All triggers are fault-tolerant (one failure doesn't crash the scheduler)
7. ✅ Watermarks persist between restarts

---

## Priority Order

Task 1 (scheduler) + Task 6 (state) first — these are shared infrastructure.
Then Task 2 (email) → Task 3 (fireflies) → Task 4 (whatsapp) → Task 5 (briefing).

Email trigger is highest priority because it's the most frequent (5-min interval) and Gmail extraction is nearly ready (Brief 4B).

---

## Dependency on Other Briefs

- **Brief 4B must be complete** — extract_gmail.py needs `--mode poll` working
- **Brief 4C should be complete** — trigger_log table needs to exist for state tracking
- Can start Tasks 1 + 6 independently while waiting for 4B/4C
