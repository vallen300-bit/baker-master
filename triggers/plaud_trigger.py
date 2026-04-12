"""
Sentinel Trigger — Plaud Note Pro (Meeting Recordings)
PLAUD-INGESTION-1: Polls Plaud web API for new transcripts and runs
the same pipeline as Fireflies.
"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.plaud")

_backfill_running = False


# ---------------------------------------------------------------------------
# Plaud API client
# ---------------------------------------------------------------------------

def _plaud_headers() -> dict:
    """Auth headers for Plaud API. Token already includes 'bearer ' prefix."""
    token = config.plaud.api_token
    if not token:
        return {}
    # Token from localStorage includes "bearer " prefix — use as-is
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return {
        "Authorization": auth,
        "Content-Type": "application/json",
    }


def _plaud_api(path: str, timeout: int = 30) -> dict | None:
    """Make a GET request to Plaud API. Returns parsed JSON or None."""
    import httpx

    domain = config.plaud.api_domain
    if not domain:
        logger.warning("PLAUD_API_DOMAIN not set")
        return None

    headers = _plaud_headers()
    if not headers:
        logger.warning("PLAUD_TOKEN not set — Plaud trigger disabled")
        return None

    url = f"{domain}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Plaud API HTTP error: {e.response.status_code} for {path}")
        if e.response.status_code == 401:
            logger.error("Plaud token expired or invalid — regenerate from web.plaud.ai")
        return None
    except Exception as e:
        logger.error(f"Plaud API request failed for {path}: {e}")
        return None


def fetch_plaud_recordings() -> list[dict]:
    """Fetch all recordings from Plaud.
    API response: {"status": 0, "data_file_list": [...], "data_file_total": N}
    Each item has: id, filename, start_time (epoch ms), duration (ms), is_trans, is_summary
    """
    data = _plaud_api("/file/simple/web")
    if not data or not isinstance(data, dict):
        return []
    return data.get("data_file_list", [])


def fetch_plaud_detail(file_id: str) -> dict | None:
    """Fetch recording detail including signed S3 URLs for transcript + summary.
    API response: {"status": 0, "data": {"file_id": ..., "content_list": [...]}}
    content_list items have data_type ("transaction" = transcript, "auto_sum_note" = summary)
    and data_link (signed S3 URL to .json.gz or .md.gz).
    """
    data = _plaud_api(f"/file/detail/{file_id}", timeout=60)
    if not data or not isinstance(data, dict):
        return None
    return data.get("data", data)


def _fetch_s3_content(url: str, is_json: bool = True):
    """Fetch gzipped content from Plaud's signed S3 URL.
    Returns parsed JSON (list/dict) if is_json=True, else raw text.
    """
    import httpx

    if not url:
        return None
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers={"Accept-Encoding": "gzip"})
            resp.raise_for_status()
            if is_json:
                return resp.json()
            return resp.text
    except Exception as e:
        logger.warning(f"Failed to fetch Plaud S3 content: {e}")
        return None


def _get_content_url(detail: dict, data_type: str) -> str:
    """Extract signed S3 URL from detail's content_list by data_type.
    data_type: 'transaction' (transcript) or 'auto_sum_note' (summary)
    """
    content_list = detail.get("content_list") or []
    for item in content_list:
        if item.get("data_type") == data_type and item.get("task_status") == 1:
            return item.get("data_link", "")
    return ""


def _extract_transcript_text(detail: dict) -> str:
    """Extract formatted transcript from Plaud recording.
    Fetches trans_result.json.gz from S3.
    Format: [{"start_time": ms, "end_time": ms, "content": "text", "speaker": "Speaker 1"}]
    """
    url = _get_content_url(detail, "transaction")
    if not url:
        return ""

    segments = _fetch_s3_content(url, is_json=True)
    if not segments or not isinstance(segments, list):
        return ""

    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "Speaker")
        text = (seg.get("content") or seg.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")

    return "\n".join(lines)


def _extract_summary(detail: dict) -> str:
    """Extract AI-generated summary from Plaud recording.
    Fetches ai_content.md.gz from S3. Returns markdown text.
    """
    url = _get_content_url(detail, "auto_sum_note")
    if not url:
        return ""

    text = _fetch_s3_content(url, is_json=False)
    return text.strip() if text else ""


def _extract_participants(detail: dict) -> str:
    """Extract speaker names from detail's embeddings keys (no extra S3 fetch needed).
    The /file/detail response includes {"embeddings": {"Speaker 1": [...], "Speaker 2": [...]}}
    """
    embeddings = detail.get("embeddings") or {}
    if embeddings:
        return ", ".join(sorted(embeddings.keys()))
    return ""


def _recording_date(rec: dict) -> datetime | None:
    """Extract recording date as timezone-aware UTC datetime.
    API field: start_time (epoch milliseconds).
    """
    # Primary: start_time (epoch ms)
    val = rec.get("start_time") or rec.get("edit_time") or rec.get("version")
    if not val:
        return None
    if isinstance(val, (int, float)):
        ts = val / 1000 if val > 1e12 else val
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _recording_title(rec: dict) -> str:
    """Extract recording title. API field: filename."""
    return (rec.get("filename") or rec.get("file_name") or "Plaud Recording").strip()


def _recording_id(rec: dict) -> str:
    """Extract file ID. API field: id (32-char hex)."""
    return rec.get("id") or rec.get("file_id") or ""


def _recording_duration(rec: dict) -> str:
    """Extract duration as human-readable string. API field: duration (milliseconds)."""
    dur = rec.get("duration")
    if isinstance(dur, (int, float)):
        secs = int(dur / 1000) if dur > 1000 else int(dur)
        mins = secs // 60
        remaining = secs % 60
        if mins > 0:
            return f"{mins}m {remaining}s" if remaining else f"{mins}min"
        return f"{secs}s"
    return ""


def format_plaud_transcript(rec: dict, detail: dict) -> dict:
    """Format a Plaud recording into the same structure as Fireflies transcripts.
    Returns {text, metadata, raw_id} matching fireflies_trigger expectations.
    """
    title = _recording_title(rec)
    date_str = ""
    rec_date = _recording_date(rec)
    if rec_date:
        date_str = rec_date.strftime("%Y-%m-%d %H:%M UTC")

    transcript_text = _extract_transcript_text(detail)
    summary = _extract_summary(detail)
    participants = _extract_participants(detail)
    duration = _recording_duration(rec)

    # Build full text block matching Fireflies format
    text_parts = [
        f"Meeting: {title}",
        f"Date: {date_str}" if date_str else "",
        f"Duration: {duration}" if duration else "",
        f"Participants: {participants}" if participants else "",
        "",
    ]
    if summary:
        text_parts.append(f"Summary:\n{summary}\n")
    if transcript_text:
        text_parts.append(f"Transcript:\n{transcript_text}")

    full_text = "\n".join(p for p in text_parts if p is not None)

    return {
        "text": full_text,
        "metadata": {
            "transcript_id": _recording_id(rec),
            "meeting_title": title,
            "date": date_str,
            "duration": duration,
            "organizer": "",  # Plaud doesn't have organizer concept
            "participants": participants,
        },
        "raw_id": _recording_id(rec),
    }


# ---------------------------------------------------------------------------
# Main poll function (mirrors check_new_transcripts)
# ---------------------------------------------------------------------------

def check_new_plaud_recordings():
    """
    Main entry point — called by scheduler every 15 minutes.
    1. Fetches recordings list from Plaud
    2. Filters to recordings newer than watermark
    3. Fetches detail (transcript + summary) for each new recording
    4. Stores in meeting_transcripts + runs extraction pipeline
    5. Updates watermark
    """
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("plaud"):
        return

    token = config.plaud.api_token
    if not token:
        # Silent skip — not an error, just not configured
        return

    try:
        if _backfill_running:
            logger.info("Plaud trigger: skipping — backfill in progress")
            return

        logger.info("Plaud trigger: scanning for new recordings...")

        watermark = trigger_state.get_watermark("plaud")
        logger.info(f"Plaud watermark: {watermark.isoformat()}")

        try:
            recordings = fetch_plaud_recordings()
        except Exception as e:
            logger.error(f"Plaud trigger: fetch failed: {e}")
            report_failure("plaud", str(e))
            return

        if not recordings:
            logger.info("Plaud trigger: no recordings returned")
            report_success("plaud")
            return

        # Filter to recordings newer than watermark + transcription complete
        new_recordings = []
        for rec in recordings:
            if not rec.get("is_trans"):
                continue  # Skip recordings still being transcribed
            rec_date = _recording_date(rec)
            if rec_date and rec_date > watermark:
                new_recordings.append(rec)

        if not new_recordings:
            logger.info("Plaud trigger: no new recordings since watermark")
            report_success("plaud")
            return

        logger.info(f"Plaud trigger: {len(new_recordings)} new recordings found")

        from orchestrator.pipeline import SentinelPipeline, TriggerEvent
        pipeline = SentinelPipeline()
        processed = 0

        for rec in new_recordings:
            file_id = _recording_id(rec)
            if not file_id:
                continue

            source_id = f"plaud_{file_id}"

            # Skip if already processed
            if trigger_state.is_processed("meeting", source_id):
                continue

            # Fetch full transcript detail
            detail = fetch_plaud_detail(file_id)
            if not detail:
                logger.warning(f"Plaud trigger: could not fetch detail for {file_id}")
                continue

            formatted = format_plaud_transcript(rec, detail)
            metadata = formatted["metadata"]

            # COST-OPT-WAVE1: Pre-mark as processed BEFORE expensive pipeline work
            trigger_state.mark_processed("meeting", source_id)

            trigger = TriggerEvent(
                type="meeting",
                content=formatted["text"],
                source_id=source_id,
                contact_name="",
                priority="medium",
            )

            # Store full transcript in meeting_transcripts (same table as Fireflies)
            try:
                from memory.store_back import SentinelStoreBack
                store = SentinelStoreBack._get_global_instance()
                store.store_meeting_transcript(
                    transcript_id=source_id,
                    title=metadata.get("meeting_title", "Untitled"),
                    meeting_date=metadata.get("date"),
                    duration=metadata.get("duration"),
                    organizer=metadata.get("organizer"),
                    participants=metadata.get("participants"),
                    summary=formatted["text"] if "Summary:" in formatted["text"] else None,
                    full_transcript=formatted["text"],
                    source="plaud",
                )
            except Exception as _e:
                logger.warning(f"Failed to store Plaud transcript {source_id} in PostgreSQL (non-fatal): {_e}")

            # Record contact interactions from participants
            try:
                from memory.store_back import SentinelStoreBack
                _store_ip = SentinelStoreBack._get_global_instance()
                _participants_str = metadata.get("participants", "")
                for _pname in _participants_str.split(","):
                    _pname = _pname.strip()
                    if not _pname or len(_pname) < 2:
                        continue
                    _cid = _store_ip.match_contact_by_name(name=_pname)
                    if _cid:
                        _store_ip.record_interaction(
                            contact_id=_cid, channel="meeting",
                            direction="bidirectional",
                            timestamp=metadata.get("date"),
                            subject=metadata.get("meeting_title", "")[:200],
                            source_ref=f"meeting:{source_id}:{_cid}",
                        )
            except Exception:
                pass  # Non-fatal

            # Extract deadlines
            try:
                from orchestrator.deadline_manager import extract_deadlines
                extract_deadlines(
                    content=formatted["text"],
                    source_type="plaud",
                    source_id=source_id,
                    sender_name="",
                )
            except Exception as _e:
                logger.debug(f"Deadline extraction failed for Plaud {source_id}: {_e}")

            # Extract commitments (same as Fireflies)
            try:
                from triggers.fireflies_trigger import _extract_commitments_from_meeting
                _extract_commitments_from_meeting(
                    transcript_text=formatted["text"],
                    meeting_title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    source_id=source_id,
                )
            except Exception as _e:
                logger.debug(f"Commitment extraction failed for Plaud {source_id}: {_e}")

            # Extract Director's personal commitments as deadlines
            try:
                from triggers.fireflies_trigger import _extract_director_commitments_as_deadlines
                _extract_director_commitments_as_deadlines(
                    transcript_text=formatted["text"],
                    meeting_title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    source_id=source_id,
                    meeting_date=metadata.get("date", ""),
                )
            except Exception as _e:
                logger.debug(f"Director commitment extraction failed for Plaud {source_id}: {_e}")

            # Run Sentinel pipeline
            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"Plaud trigger: pipeline failed for {source_id}: {e}")

            # Post-meeting auto-pipeline (non-blocking)
            try:
                from orchestrator.meeting_pipeline import process_meeting_async
                process_meeting_async(
                    transcript_id=source_id,
                    title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    meeting_date=metadata.get("date", ""),
                    full_transcript=formatted["text"],
                )
            except Exception as _mp_err:
                logger.warning(f"Meeting pipeline hook failed for Plaud (non-fatal): {_mp_err}")

        # Update watermark
        trigger_state.set_watermark("plaud")

        report_success("plaud")
        logger.info(f"Plaud trigger complete: {processed} recordings processed")

    except Exception as e:
        report_failure("plaud", str(e))
        logger.error(f"Plaud poll failed: {e}")


# ---------------------------------------------------------------------------
# Startup backfill (PG-only — no LLM, no pipeline.run)
# ---------------------------------------------------------------------------

def backfill_plaud():
    """
    One-time catch-up on startup.
    Fetches all recordings from Plaud and stores any not yet in meeting_transcripts.
    PG-only — no pipeline.run(), no LLM calls (Lesson #25).
    """
    global _backfill_running

    token = config.plaud.api_token
    if not token:
        logger.info("Plaud backfill: PLAUD_TOKEN not set, skipping")
        return

    # Advisory lock — different ID from Fireflies (867531)
    from memory.store_back import SentinelStoreBack
    _lock_store = SentinelStoreBack._get_global_instance()
    _lock_conn = _lock_store._get_conn()
    if _lock_conn:
        try:
            _lock_cur = _lock_conn.cursor()
            _lock_cur.execute("SELECT pg_try_advisory_lock(867532)")
            if not _lock_cur.fetchone()[0]:
                logger.info("Plaud backfill: another instance holds lock, skipping")
                _lock_store._put_conn(_lock_conn)
                return
        except Exception:
            _lock_store._put_conn(_lock_conn)
            return
    else:
        return

    _backfill_running = True
    try:
        logger.info("Plaud backfill: starting...")
        recordings = fetch_plaud_recordings()
        if not recordings:
            logger.info("Plaud backfill: no recordings found")
            return

        store = SentinelStoreBack._get_global_instance()
        ingested = 0

        for rec in recordings:
            file_id = _recording_id(rec)
            if not file_id:
                continue

            source_id = f"plaud_{file_id}"

            # Skip if already processed
            if trigger_state.is_processed("meeting", source_id):
                continue

            detail = fetch_plaud_detail(file_id)
            if not detail:
                continue

            formatted = format_plaud_transcript(rec, detail)
            metadata = formatted["metadata"]

            # PG-only store — no pipeline.run(), no LLM (Lesson #25)
            store.store_meeting_transcript(
                transcript_id=source_id,
                title=metadata.get("meeting_title", "Untitled"),
                meeting_date=metadata.get("date"),
                duration=metadata.get("duration"),
                organizer=metadata.get("organizer"),
                participants=metadata.get("participants"),
                summary=formatted["text"] if "Summary:" in formatted["text"] else None,
                full_transcript=formatted["text"],
                source="plaud",
            )
            trigger_state.mark_processed("meeting", source_id)
            ingested += 1

            # Deadline extraction is cheap (no LLM) — safe for backfill
            try:
                from orchestrator.deadline_manager import extract_deadlines
                extract_deadlines(
                    content=formatted["text"],
                    source_type="plaud",
                    source_id=source_id,
                    sender_name="",
                )
            except Exception:
                pass

        logger.info(f"Plaud backfill complete: {ingested} recordings ingested")

    except Exception as e:
        logger.error(f"Plaud backfill failed: {e}")
    finally:
        _backfill_running = False
        # Release advisory lock
        try:
            _lock_cur = _lock_conn.cursor()
            _lock_cur.execute("SELECT pg_advisory_unlock(867532)")
            _lock_conn.commit()
            _lock_cur.close()
        except Exception:
            pass
        _lock_store._put_conn(_lock_conn)
