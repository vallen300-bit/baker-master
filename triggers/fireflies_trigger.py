"""
Sentinel Trigger — Fireflies (Meeting Transcripts)
Scans for new meeting transcripts every 2 hours and fires pipeline.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.fireflies")


def fetch_new_transcripts(since: datetime) -> list:
    """
    Fetch transcripts from Fireflies that are newer than `since`.
    Reuses extract_fireflies.py functions.
    Returns list of {text, metadata} formatted dicts.
    """
    from scripts.extract_fireflies import fetch_transcripts, format_transcript, transcript_date

    api_key = config.fireflies.api_key
    if not api_key:
        logger.warning("Fireflies trigger: FIREFLIES_API_KEY not set, skipping")
        return []

    raw = fetch_transcripts(api_key, limit=50)
    if not raw:
        return []

    # Filter to only transcripts newer than watermark
    new_transcripts = []
    for t in raw:
        t_date = transcript_date(t)
        if t_date is None:
            continue
        # transcript_date returns naive UTC — make it aware for comparison
        t_date_aware = t_date.replace(tzinfo=timezone.utc)
        if t_date_aware > since:
            formatted = format_transcript(t)
            formatted["raw_id"] = t.get("id", "")
            new_transcripts.append(formatted)

    return new_transcripts


def check_new_transcripts():
    """
    Main entry point — called by scheduler every 2 hours.
    1. Fetches transcripts since last watermark
    2. Skips already-processed (via trigger_log)
    3. Runs pipeline for each new transcript
    4. Updates watermark
    """
    logger.info("Fireflies trigger: scanning for new transcripts...")

    watermark = trigger_state.get_watermark("fireflies")
    logger.info(f"Fireflies watermark: {watermark.isoformat()}")

    try:
        new_transcripts = fetch_new_transcripts(watermark)
    except Exception as e:
        logger.error(f"Fireflies trigger: fetch failed: {e}")
        return

    if not new_transcripts:
        logger.info("Fireflies trigger: no new transcripts")
        return

    logger.info(f"Fireflies trigger: {len(new_transcripts)} new transcripts found")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    processed = 0

    for transcript in new_transcripts:
        metadata = transcript.get("metadata", {})
        source_id = transcript.get("raw_id") or metadata.get("transcript_id", "unknown")

        # Skip if already processed
        if trigger_state.is_processed("meeting", source_id):
            continue

        trigger = TriggerEvent(
            type="meeting",
            content=transcript["text"],
            source_id=source_id,
            contact_name=metadata.get("organizer"),
            priority="medium",
        )

        try:
            pipeline.run(trigger)
            processed += 1
        except Exception as e:
            logger.error(f"Fireflies trigger: pipeline failed for transcript {source_id}: {e}")

    # Update watermark
    trigger_state.set_watermark("fireflies")

    logger.info(f"Fireflies trigger complete: {processed} transcripts processed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    check_new_transcripts()
