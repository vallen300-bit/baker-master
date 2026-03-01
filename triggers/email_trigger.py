"""
Sentinel Trigger — Email (Gmail)
Polls Gmail for new threads and fires pipeline for substantive ones.
Called by scheduler every 5 minutes.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.email")


def _get_gmail_service():
    """Authenticate and return Gmail API service object."""
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build
    creds = authenticate()
    return build("gmail", "v1", credentials=creds)


def poll_gmail() -> list:
    """
    Poll Gmail for new threads since last watermark.
    Returns list of {text, metadata} dicts.
    Reuses extract_gmail.py's poll logic.
    """
    from scripts.extract_gmail import extract_poll
    service = _get_gmail_service()
    return extract_poll(service)


def check_new_emails():
    """
    Main entry point — called by scheduler every 5 minutes.
    1. Polls Gmail for new threads
    2. Classifies each by priority
    3. Runs pipeline immediately for high/medium priority
    4. Queues low-priority for daily briefing
    """
    logger.info("Email trigger: checking for new threads...")

    try:
        new_threads = poll_gmail()
    except Exception as e:
        logger.error(f"Email trigger: Gmail poll failed: {e}")
        return

    if not new_threads:
        logger.info("Email trigger: no new threads")
        # Gap detection: alert if no email activity for 48+ hours
        wm = trigger_state.get_watermark("email_poll")
        if wm:
            gap_hours = (datetime.now(timezone.utc) - wm).total_seconds() / 3600
            if gap_hours > 48:
                gap_title = f"Email gap alert: {gap_hours:.0f}h since last email"
                gap_body = f"Watermark stuck at {wm.isoformat()}. Check Gmail auth and poll health."
                logger.warning(gap_title)
                try:
                    from memory.store_back import store
                    store.create_alert(tier=1, title=gap_title, body=gap_body)
                    from outputs.slack_notifier import SlackNotifier
                    SlackNotifier().post_alert(gap_title, gap_body)
                except Exception as e:
                    logger.error(f"Gap alert dispatch failed: {e}")
        return

    logger.info(f"Email trigger: {len(new_threads)} new threads found")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    batch_for_briefing = []
    processed = 0
    skipped = 0
    latest_seen_dt = None  # F4: track max received_date across ALL seen threads

    for thread in new_threads:
        metadata = thread.get("metadata", {})
        thread_id = metadata.get("thread_id", "unknown")

        # F4: Track received_date of every seen thread (processed + skipped)
        received_date_str = metadata.get("received_date", "")
        if received_date_str and received_date_str != "unknown":
            try:
                rd = datetime.fromisoformat(received_date_str)
                if rd.tzinfo is None:
                    rd = rd.replace(tzinfo=timezone.utc)
                if latest_seen_dt is None or rd > latest_seen_dt:
                    latest_seen_dt = rd
            except (ValueError, TypeError):
                pass

        # F1: Dedup on ALL message IDs in thread — skip only if every message was seen before
        all_message_ids = metadata.get("all_message_ids") or [metadata.get("message_id", thread_id)]
        new_ids = [mid for mid in all_message_ids if not trigger_state.is_processed("email", mid)]
        if not new_ids:
            skipped += 1
            continue

        # Use latest message ID as pipeline source_id (logged in trigger_log for future dedup)
        message_id = all_message_ids[-1]

        trigger = TriggerEvent(
            type="email",
            content=thread["text"],
            source_id=message_id,
            contact_name=metadata.get("primary_sender"),
        )
        trigger = pipeline.classify_trigger(trigger)

        # DEADLINE-SYSTEM-1: Extract deadlines from email content
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=thread["text"],
                source_type="email",
                source_id=message_id,
                sender_name=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
            )
        except Exception as _e:
            logger.debug(f"Deadline extraction failed for email {message_id}: {_e}")

        if trigger.priority in ("high", "medium"):
            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"Email trigger: pipeline failed for message {message_id} (thread {thread_id}): {e}")
        else:
            # Queue low-priority for daily briefing
            batch_for_briefing.append({
                "type": "email",
                "source_id": message_id,
                "content": thread["text"][:500],
                "contact_name": metadata.get("primary_sender"),
                "subject": metadata.get("subject", ""),
                "priority": trigger.priority,
            })

    # Store low-priority batch for briefing
    if batch_for_briefing:
        trigger_state.add_to_briefing_queue(batch_for_briefing)

    # F4: Advance watermark to the newest received_date seen this cycle
    # (covers both processed and deduped threads — prevents re-fetching old batches)
    if latest_seen_dt:
        now_utc = datetime.now(timezone.utc)
        if latest_seen_dt > now_utc:
            logger.warning(
                f"Email watermark ceiling hit: {latest_seen_dt.isoformat()} > now "
                f"({now_utc.isoformat()}). Capping at now."
            )
            latest_seen_dt = now_utc
        trigger_state.set_watermark("email_poll", latest_seen_dt)
        logger.info(f"Email watermark advanced to {latest_seen_dt.isoformat()}")

    logger.info(
        f"Email trigger complete: {processed} processed, "
        f"{len(batch_for_briefing)} queued for briefing, {skipped} skipped (dedup)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    check_new_emails()
