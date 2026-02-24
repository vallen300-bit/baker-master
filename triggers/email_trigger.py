"""
Sentinel Trigger — Email (Gmail)
Polls Gmail for new threads and fires pipeline for substantive ones.
Called by scheduler every 5 minutes.
"""
import logging
import sys
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
        return

    logger.info(f"Email trigger: {len(new_threads)} new threads found")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    batch_for_briefing = []
    processed = 0
    skipped = 0

    for thread in new_threads:
        metadata = thread.get("metadata", {})
        thread_id = metadata.get("thread_id", "unknown")
        # Dedup on message_id (unique per reply), not thread_id (reused across replies)
        message_id = metadata.get("message_id", thread_id)

        # Skip if already processed
        if trigger_state.is_processed("email", message_id):
            skipped += 1
            continue

        trigger = TriggerEvent(
            type="email",
            content=thread["text"],
            source_id=message_id,
            contact_name=metadata.get("primary_sender"),
        )
        trigger = pipeline.classify_trigger(trigger)

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

    logger.info(
        f"Email trigger complete: {processed} processed, "
        f"{len(batch_for_briefing)} queued for briefing, {skipped} skipped (dedup)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    check_new_emails()
