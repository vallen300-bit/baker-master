"""
Sentinel Trigger — Plaud Note Pro (Meeting Recordings)
PLAUD-INGESTION-1: Polls Plaud web API for new transcripts and runs
the same pipeline as Fireflies.
"""
# PEP 563: lazy annotations so PEP 604 unions (X | None) in signatures don't
# evaluate at import time on Python 3.9 (PY39_UNION_IMPORT_SWEEP_1).
from __future__ import annotations

import logging
import sys
from contextlib import ExitStack, contextmanager
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
        logger.warning(f"_extract_transcript_text: no transaction URL in detail (file_id={detail.get('id', '?')})")
        return ""

    segments = _fetch_s3_content(url, is_json=True)
    if not segments or not isinstance(segments, list):
        logger.warning(f"_extract_transcript_text: empty/invalid S3 segments for {detail.get('id', '?')} (url-tail={url.split('?')[0][-40:]})")
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


def _has_empty_db_row(source_id: str, threshold: int = 200) -> bool:
    """Returns True if meeting_transcripts has a row for source_id with full_transcript shorter than threshold.

    Used by stale-refresh path: a row from the broken-backfill era has length(full_transcript)
    well below 200 chars (header-only shell). A real transcript is typically >> 200 chars even
    for short recordings.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT length(full_transcript) FROM meeting_transcripts WHERE id = %s LIMIT 1",
            (source_id,),
        )
        row = cur.fetchone()
        cur.close()
        return bool(row) and (row[0] or 0) < threshold
    except Exception as e:
        conn.rollback()
        logger.debug(f"_has_empty_db_row probe failed for {source_id} (non-fatal): {e}")
        return False
    finally:
        store._put_conn(conn)


def _maybe_report_empty_body_alarm(rec: dict, source_id: str, body: str) -> None:
    """Fire empty-body sentinel exactly once per source_id per UTC day.

    With ~4 known-stuck recordings polled every 15 min, an unbounded sentinel
    floods #cockpit Slack. UTC-day bucketed dedup via trigger_log gives
    once-per-recording-per-day cadence + full audit trail. Also coalesces both
    backfill + incremental call sites into a single dedup check (cycle-aware
    via DB state — second call hits is_processed and short-circuits).
    """
    try:
        from triggers.sentinel_health import report_failure as _report_failure
        dur_ms = rec.get("duration") or 0
        if not (dur_ms > 300_000 and len(body) < 200 and rec.get("is_trans")):
            return
        utc_day = datetime.now(timezone.utc).strftime("%Y%m%d")
        dedup_key = f"plaud_empty_alarm_{source_id}_{utc_day}"
        if trigger_state.is_processed("plaud_alarm", dedup_key):
            return
        _report_failure(
            "plaud",
            f"empty-body-after-transcription: {source_id} dur={dur_ms}ms body={len(body)}chars",
        )
        trigger_state.mark_processed("plaud_alarm", dedup_key)
    except Exception as _se:
        logger.debug(f"empty-body alarm dedup helper failed (non-fatal): {_se}")


@contextmanager
def _stale_refresh_advisory_lock(source_id: str):
    """Per-source_id advisory lock for stale-refresh re-ingest. Yields bool acquired.

    Render rolling deploy runs 2 instances concurrently. Without serialization,
    both can fire fetch_plaud_detail + store_meeting_transcript on the same stale
    source_id; PG dedupes via ON CONFLICT but Qdrant uses fresh uuid4 per point
    (duplicate Voyage embedding calls + duplicate Qdrant points). Lock is held
    for the duration of the iteration body and auto-released when the txn ends
    (pg_try_advisory_xact_lock semantics).
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        # No DB conn — fail closed (skip iteration so we don't double-write Qdrant).
        yield False
        return
    acquired = False
    try:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (source_id,),
            )
            row = cur.fetchone()
            cur.close()
            acquired = bool(row and row[0])
        except Exception as e:
            conn.rollback()
            logger.debug(f"stale-refresh lock probe failed for {source_id} (non-fatal): {e}")
            acquired = False
        yield acquired
    finally:
        try:
            # Either commit (releases xact lock) or rollback (also releases).
            if acquired:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        store._put_conn(conn)


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

        # Filter to recordings newer than watermark + transcription complete.
        # STALE-REFRESH (PR #168 fix completion 2026-05-08): also include recordings
        # whose DB row is a shell (length < 200) regardless of watermark — without this,
        # PR #168's stale-refresh logic at line ~439 never fires for files older than
        # the watermark (the original 25-day silent failure repeated). Confirmed via
        # 8 stuck files (Apr 12-28) sitting at body_len 71-177 chars even after PR #168
        # deployed — Plaud-side is_trans=True, but watermark gate excluded them from
        # the loop body where the stale-refresh re-ingest lives.
        new_recordings = []
        for rec in recordings:
            if not rec.get("is_trans"):
                continue  # Skip recordings still being transcribed
            rec_date = _recording_date(rec)
            if rec_date and rec_date > watermark:
                new_recordings.append(rec)
                continue
            # Past-watermark stale-refresh gate: re-ingest if a shell exists in DB.
            file_id = _recording_id(rec)
            if not file_id:
                continue
            source_id = f"plaud_{file_id}"
            if trigger_state.is_processed("meeting", source_id) and _has_empty_db_row(source_id, threshold=200):
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

            # Skip if already processed AND DB body is non-empty.
            # Stale-refresh: if Plaud previously returned is_trans=False (broken backfill
            # pre-fix landed shells), allow re-ingest once Plaud reports is_trans=True.
            # store_meeting_transcript ON CONFLICT (id) DO UPDATE handles upsert cleanly.
            #
            # I2: stale-refresh acquires per-source pg_try_advisory_xact_lock(hashtext(source_id))
            # so concurrent Render instances don't double-write Qdrant (PG dedupes via ON CONFLICT,
            # Qdrant uses fresh uuid4). Lock held across iteration body, released at finally.
            _stale_lock_cm = None
            if trigger_state.is_processed("meeting", source_id):
                if not _has_empty_db_row(source_id, threshold=200):
                    continue
                logger.info(
                    f"Plaud trigger: stale-refresh re-ingesting {source_id} "
                    f"(DB body < 200 chars, is_trans now True)"
                )
                _stale_lock_cm = _stale_refresh_advisory_lock(source_id)
                if not _stale_lock_cm.__enter__():
                    logger.info(
                        f"Plaud trigger: stale-refresh lock held by peer instance for "
                        f"{source_id}, skipping (will retry next cycle)"
                    )
                    try:
                        _stale_lock_cm.__exit__(None, None, None)
                    except Exception:
                        pass
                    continue

            try:
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

                # I1 dedup: empty-body sentinel fires once per source_id per UTC day to
                # prevent #cockpit alarm-flood (4 stuck recordings × 15-min polls).
                _maybe_report_empty_body_alarm(rec, source_id, formatted.get("text") or "")

                # BRIEF_PM_SIDEBAR_STATE_WRITE_1 D6: relevance-on-ingest sentinel.
                try:
                    from orchestrator.pm_signal_detector import (
                        detect_relevant_pms_meeting, flag_pm_signal,
                    )
                    _title = metadata.get("meeting_title", "") or ""
                    _participants = metadata.get("participants", "") or ""
                    for _pm_slug in detect_relevant_pms_meeting(
                        title=_title, participants=_participants,
                    ):
                        flag_pm_signal(
                            _pm_slug, "meeting",
                            source=f"plaud: {_title[:120]}",
                            summary=(formatted.get("text") or "")[:280],
                            push_slack=True,
                        )
                except Exception as _pm_e:
                    logger.debug(f"meeting signal detection failed (non-fatal): {_pm_e}")

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
                        source_agent="meeting_pipeline",
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
            finally:
                # I2: release advisory lock if we acquired it (commits txn → releases pg_advisory_xact_lock).
                if _stale_lock_cm is not None:
                    try:
                        _stale_lock_cm.__exit__(None, None, None)
                    except Exception:
                        pass

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
            # Empty result is still a successful poll round (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1
            # Fix 1a — sentinel must advance on no-op coverage paths, not stay stale).
            try:
                from triggers.sentinel_health import report_success
                report_success("plaud")
            except Exception as _sh_e:
                logger.warning(f"sentinel report_success crashed (non-fatal): {_sh_e}")
            return

        store = SentinelStoreBack._get_global_instance()
        ingested = 0

        for rec in recordings:
            file_id = _recording_id(rec)
            if not file_id:
                continue

            # Mirror incremental-path filter (line 297-299): skip un-transcribed recordings.
            # Without this, header-only shells get stored + source_id locked, breaking re-ingest
            # after Plaud completes transcription.
            if not rec.get("is_trans"):
                continue

            source_id = f"plaud_{file_id}"

            # Skip if already processed AND DB has a real body (not a broken-backfill shell).
            # Stale-refresh (PR #168 follow-up 2026-05-08): if Plaud now reports is_trans=True
            # but our DB row is a header-only shell (<200 chars) from the broken backfill era,
            # re-ingest. store_meeting_transcript ON CONFLICT (id) DO UPDATE handles upsert.
            if trigger_state.is_processed("meeting", source_id):
                if not _has_empty_db_row(source_id, threshold=200):
                    continue
                logger.info(
                    f"Plaud backfill: stale-refresh re-ingesting {source_id} "
                    f"(DB body < 200 chars, is_trans now True)"
                )

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

            # I1 dedup: same helper as incremental path — coalesces backfill + incremental
            # alarm sites into a single per-source_id-per-UTC-day fire.
            _maybe_report_empty_body_alarm(rec, source_id, formatted.get("text") or "")

            # BRIEF_PM_SIDEBAR_STATE_WRITE_1 D6: relevance-on-ingest sentinel
            # (backfill path — regex-only, no LLM; Lesson #25 respected).
            try:
                from orchestrator.pm_signal_detector import (
                    detect_relevant_pms_meeting, flag_pm_signal,
                )
                _title = metadata.get("meeting_title", "") or ""
                _participants = metadata.get("participants", "") or ""
                for _pm_slug in detect_relevant_pms_meeting(
                    title=_title, participants=_participants,
                ):
                    flag_pm_signal(
                        _pm_slug, "meeting",
                        source=f"plaud: {_title[:120]}",
                        summary=(formatted.get("text") or "")[:280],
                        push_slack=True,
                    )
            except Exception as _pm_e:
                logger.debug(f"meeting signal detection failed (non-fatal): {_pm_e}")

            # Deadline extraction is cheap (no LLM) — safe for backfill
            try:
                from orchestrator.deadline_manager import extract_deadlines
                extract_deadlines(
                    content=formatted["text"],
                    source_type="plaud",
                    source_id=source_id,
                    sender_name="",
                    source_agent="meeting_pipeline",
                )
            except Exception:
                pass

        logger.info(f"Plaud backfill complete: {ingested} recordings ingested")
        # Sentinel success on clean completion of the ingest loop
        # (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1 Fix 1a).
        try:
            from triggers.sentinel_health import report_success
            report_success("plaud")
        except Exception as _sh_e:
            logger.warning(f"sentinel report_success crashed (non-fatal): {_sh_e}")

    except Exception as e:
        logger.error(f"Plaud backfill failed: {e}")
        # Sentinel failure on top-level except so the cockpit surfaces it
        # (BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1 Fix 1a).
        try:
            from triggers.sentinel_health import report_failure
            report_failure("plaud", f"backfill: {e}")
        except Exception as _sh_e:
            logger.warning(f"sentinel report_failure crashed (non-fatal): {_sh_e}")
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
