"""
Sentinel Trigger — Fireflies (Meeting Transcripts)
Scans for new meeting transcripts every 2 hours and fires pipeline.
FIREFLIES-FETCH-1: Adds startup backfill (30 days) and concurrency guard.
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

logger = logging.getLogger("sentinel.trigger.fireflies")

# FIREFLIES-FETCH-1: Concurrency guard — prevents backfill and poll from running simultaneously
_backfill_running = False


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


# -------------------------------------------------------
# Phase 3C: Commitment extraction from meetings
# -------------------------------------------------------

_COMMITMENT_EXTRACT_PROMPT = """You are Baker. Extract action items and commitments from this meeting transcript.

For each commitment found, return:
- description: What was promised or agreed to do
- assigned_to: Who is responsible (use their name as spoken in the meeting)
- due_date: When it's due (YYYY-MM-DD format, or null if no date mentioned)
- urgency: high/medium/low

Rules:
- Only extract EXPLICIT commitments — someone clearly agreed to do something
- Don't fabricate commitments from general discussion
- If "we" agreed, assign to "director" (Dimitry is the decision-maker)
- Include verbal promises: "I'll send you...", "We'll prepare...", "Let me follow up on..."
- Skip vague statements like "we should consider..."

Return ONLY valid JSON:
{"commitments": [
    {"description": "...", "assigned_to": "...", "due_date": "YYYY-MM-DD or null", "urgency": "high|medium|low"}
]}

If no clear commitments found, return {"commitments": []}
"""


def _extract_commitments_from_meeting(transcript_text: str, meeting_title: str,
                                       participants: str, source_id: str):
    """Extract commitments from a meeting transcript using Flash. Fault-tolerant."""
    import json
    from memory.store_back import SentinelStoreBack

    if not transcript_text or len(transcript_text.strip()) < 50:
        return

    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Today: {today}\nMeeting: {meeting_title}\nParticipants: {participants}\n\n{transcript_text[:8000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="commitment_extract")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        parsed = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Commitment extraction failed for meeting {source_id}: {e}")
        return

    commitments = parsed.get("commitments", [])
    if not commitments:
        return

    store = SentinelStoreBack._get_global_instance()
    inserted = 0
    for c in commitments:
        desc = (c.get("description") or "").strip()
        if not desc:
            continue
        due_date = c.get("due_date")
        if due_date == "null" or not due_date:
            due_date = None

        # Auto-assign matter
        matter_slug = None
        try:
            from orchestrator.pipeline import _match_matter_slug
            matter_slug = _match_matter_slug(desc, meeting_title, store)
        except Exception:
            pass

        cid = store.store_commitment(
            description=desc,
            assigned_to=c.get("assigned_to", ""),
            due_date=due_date,
            source_type="meeting",
            source_id=source_id,
            source_context=f"Meeting: {meeting_title}",
            matter_slug=matter_slug,
        )
        if cid:
            inserted += 1

    if inserted:
        logger.info(f"Extracted {inserted} commitments from meeting '{meeting_title}'")


def _extract_director_commitments_as_deadlines(transcript_text: str, meeting_title: str,
                                                participants: str, source_id: str,
                                                meeting_date: str = ""):
    """OBLIGATIONS-DETECT-1: Extract Director's personal commitments from meeting and store as deadlines."""
    import json

    if not transcript_text or len(transcript_text.strip()) < 100:
        return

    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Review this meeting transcript and extract action items that Dimitry Vallen personally committed to.

Meeting: {meeting_title}
Date: {meeting_date or today}
Participants: {participants}

Transcript (excerpt):
{transcript_text[:3000]}

Return JSON only (no markdown):
{{
  "commitments": [
    {{
      "description": "what Dimitry committed to do",
      "to_whom": "who he promised it to",
      "due_date": "YYYY-MM-DD or null",
      "urgency": "high" | "normal" | "low"
    }}
  ]
}}

Rules:
- Only include things Dimitry personally agreed to do ("I will", "I'll", "let me", "my action")
- NOT tasks assigned to others
- Return {{"commitments": []}} if none found"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="commitment_meeting_detect")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning(f"OBLIGATIONS-DETECT-1: meeting commitment extraction failed: {e}")
        return

    commitments = parsed.get("commitments", [])
    if not commitments:
        return

    from models.deadlines import insert_deadline
    inserted = 0
    for c in commitments:
        desc = (c.get("description") or "").strip()
        to_whom = (c.get("to_whom") or "").strip()
        if not desc:
            continue
        due_date = c.get("due_date")
        if not due_date or due_date == "null":
            due_date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            _dd = datetime.strptime(due_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            _dd = datetime.now(timezone.utc) + timedelta(days=3)
        priority = "high" if c.get("urgency") == "high" else "normal"
        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _cstore = SentinelStoreBack._get_global_instance()
            _use_cortex = _cstore.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        _dl_desc = f"[Commitment to {to_whom}] {desc}" if to_whom else f"[Meeting commitment] {desc}"
        if _use_cortex:
            from models.cortex import cortex_create_deadline
            did = cortex_create_deadline(
                description=_dl_desc,
                due_date=_dd,
                source_type="meeting",
                source_agent="meeting_pipeline",
                confidence="medium",
                priority=priority,
                source_id=f"commitment-meeting:{source_id}",
                source_snippet=f"Meeting: {meeting_title}\nParticipants: {participants}",
            )
        else:
            did = insert_deadline(
                description=_dl_desc,
                due_date=_dd,
                source_type="meeting",
                source_id=f"commitment-meeting:{source_id}",
                confidence="medium",
                priority=priority,
                source_snippet=f"Meeting: {meeting_title}\nParticipants: {participants}",
            )
        if did:
            inserted += 1

    if inserted:
        logger.info(f"OBLIGATIONS-DETECT-1: {inserted} Director commitments from meeting '{meeting_title}'")


def check_new_transcripts():
    """
    Main entry point — called by scheduler every 2 hours.
    1. Fetches transcripts since last watermark
    2. Skips already-processed (via trigger_log)
    3. Runs pipeline for each new transcript
    4. Updates watermark
    """
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("fireflies"):
        return

    try:
        # FIREFLIES-FETCH-1: Skip if backfill is running
        if _backfill_running:
            logger.info("Fireflies trigger: skipping — backfill in progress")
            return

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

            # COST-OPT-WAVE1: Pre-mark as processed BEFORE expensive pipeline work
            # to prevent race condition with overlapping poll cycles.
            trigger_state.mark_processed("meeting", source_id)

            trigger = TriggerEvent(
                type="meeting",
                content=transcript["text"],
                source_id=source_id,
                contact_name=metadata.get("organizer"),
                priority="medium",
            )

            # ARCH-3: Store full transcript in PostgreSQL
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
                    summary=transcript["text"] if "Summary:" in transcript["text"] else None,
                    full_transcript=transcript["text"],
                )
            except Exception as _e:
                logger.warning(f"Failed to store transcript {source_id} in PostgreSQL (non-fatal): {_e}")

            # INTERACTION-PIPELINE-1: Record contact interactions from meeting participants
            try:
                from memory.store_back import SentinelStoreBack
                _store_ip = SentinelStoreBack._get_global_instance()
                _participants_str = metadata.get("participants", "")
                # Parse participants — typically comma-separated names
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

            # DEADLINE-SYSTEM-1: Extract deadlines from transcript
            try:
                from orchestrator.deadline_manager import extract_deadlines
                extract_deadlines(
                    content=transcript["text"],
                    source_type="fireflies",
                    source_id=source_id,
                    sender_name=metadata.get("organizer", ""),
                    source_agent="meeting_pipeline",
                )
            except Exception as _e:
                logger.debug(f"Deadline extraction failed for transcript {source_id}: {_e}")

            # Phase 3C: Extract commitments from meeting transcript
            try:
                _extract_commitments_from_meeting(
                    transcript_text=transcript["text"],
                    meeting_title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    source_id=source_id,
                )
            except Exception as _e:
                logger.debug(f"Commitment extraction failed for transcript {source_id}: {_e}")

            # OBLIGATIONS-DETECT-1: Extract Director's personal commitments as deadlines
            try:
                _extract_director_commitments_as_deadlines(
                    transcript_text=transcript["text"],
                    meeting_title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    source_id=source_id,
                    meeting_date=metadata.get("date", ""),
                )
            except Exception as _e:
                logger.debug(f"Director commitment extraction failed for transcript {source_id}: {_e}")

            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"Fireflies trigger: pipeline failed for transcript {source_id}: {e}")

            # Baker 3.0 Item 3: Post-meeting auto-pipeline (non-blocking)
            try:
                from orchestrator.meeting_pipeline import process_meeting_async
                process_meeting_async(
                    transcript_id=source_id,
                    title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    meeting_date=metadata.get("date", ""),
                    full_transcript=transcript["text"],
                )
            except Exception as _mp_err:
                logger.warning(f"Meeting pipeline hook failed (non-fatal): {_mp_err}")

        # Update watermark
        trigger_state.set_watermark("fireflies")

        report_success("fireflies")
        logger.info(f"Fireflies trigger complete: {processed} transcripts processed")

    except Exception as e:
        report_failure("fireflies", str(e))
        logger.error(f"fireflies poll failed: {e}")



def backfill_fireflies():
    """
    FIREFLIES-FETCH-1: One-time catch-up on startup.
    Fetches last 30 days of Fireflies transcripts and ingests any not yet processed.
    Safe to run repeatedly — dedup via trigger_log skips already-processed transcripts.
    """
    global _backfill_running

    api_key = config.fireflies.api_key
    if not api_key:
        logger.info("Fireflies backfill: FIREFLIES_API_KEY not set, skipping")
        return

    # OOM-FIX: Prevent concurrent backfills across Render deploy overlap
    from memory.store_back import SentinelStoreBack
    _lock_store = SentinelStoreBack._get_global_instance()
    _lock_conn = _lock_store._get_conn()
    if _lock_conn:
        try:
            _lock_cur = _lock_conn.cursor()
            _lock_cur.execute("SELECT pg_try_advisory_lock(867531)")
            if not _lock_cur.fetchone()[0]:
                logger.info("Fireflies backfill: another instance holds the lock, skipping")
                _lock_cur.close()
                _lock_store._put_conn(_lock_conn)
                return
            _lock_cur.close()
        except Exception as _e:
            logger.warning(f"Advisory lock check failed (proceeding anyway): {_e}")
            _lock_store._put_conn(_lock_conn)
            _lock_conn = None

    _backfill_running = True
    logger.info("Fireflies backfill: starting 30-day catch-up...")

    # ARCH-3: Also backfill full transcripts to PostgreSQL (upsert, safe to repeat)
    try:
        backfill_transcripts_only()
    except Exception as _e:
        logger.warning(f"Transcript PostgreSQL backfill failed (non-fatal): {_e}")

    try:
        from scripts.extract_fireflies import fetch_transcripts, format_transcript, transcript_date

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        raw = fetch_transcripts(api_key, limit=50)

        if not raw:
            logger.info("Fireflies backfill: no transcripts returned from API")
            return

        ingested = 0
        skipped = 0

        for t in raw:
            t_date = transcript_date(t)
            if t_date is None:
                continue
            t_date_aware = t_date.replace(tzinfo=timezone.utc)

            # Skip transcripts older than 30 days
            if t_date_aware < cutoff:
                continue

            source_id = t.get("id", "")
            if not source_id:
                continue

            # Dedup check
            if trigger_state.is_processed("meeting", source_id):
                skipped += 1
                continue

            # Format and store to PostgreSQL
            formatted = format_transcript(t)
            metadata = formatted.get("metadata", {})

            # ARCH-3: Store full transcript in PostgreSQL
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
                )
            except Exception as _e:
                logger.warning(f"Backfill: failed to store transcript {source_id} in PostgreSQL (non-fatal): {_e}")

            # OOM-FIX: Skip pipeline.run() for backfill transcripts.
            # Month-old meetings don't need real-time Claude/Gemini analysis.
            # New transcripts get full pipeline via 15-min check_new_transcripts() poll.
            trigger_state.mark_processed("meeting", source_id)
            ingested += 1

            # Deadline extraction
            try:
                from orchestrator.deadline_manager import extract_deadlines
                extract_deadlines(
                    content=formatted["text"],
                    source_type="fireflies",
                    source_id=source_id,
                    sender_name=formatted.get("metadata", {}).get("organizer", ""),
                    source_agent="meeting_pipeline",
                )
            except Exception:
                pass

            # Phase 3C: Extract commitments from meeting transcript (was missing from backfill)
            try:
                _extract_commitments_from_meeting(
                    transcript_text=formatted["text"],
                    meeting_title=metadata.get("meeting_title", "Untitled"),
                    participants=metadata.get("participants", ""),
                    source_id=source_id,
                )
            except Exception as _e:
                logger.warning(f"Backfill commitment extraction failed for {source_id}: {_e}")

        logger.info(
            f"Fireflies backfill complete: ingested {ingested} of {ingested + skipped} "
            f"transcripts (skipped {skipped} duplicates)"
        )

    except Exception as e:
        logger.error(f"Fireflies backfill failed: {e}")
    finally:
        _backfill_running = False
        # Release advisory lock
        if _lock_conn:
            try:
                _lc = _lock_conn.cursor()
                _lc.execute("SELECT pg_advisory_unlock(867531)")
                _lc.close()
                _lock_store._put_conn(_lock_conn)
            except Exception:
                pass


def backfill_transcripts_only():
    """
    ARCH-3: One-time backfill — stores full transcripts to PostgreSQL only.
    No dedup check, no pipeline re-run. Safe to run repeatedly (upsert on conflict).
    Call this once to populate meeting_transcripts for all existing Fireflies data.
    """
    api_key = config.fireflies.api_key
    if not api_key:
        logger.info("Transcript backfill: FIREFLIES_API_KEY not set, skipping")
        return

    logger.info("Transcript backfill: fetching all transcripts from Fireflies API...")

    try:
        from scripts.extract_fireflies import fetch_transcripts, format_transcript
        from memory.store_back import SentinelStoreBack

        raw = fetch_transcripts(api_key, limit=50)
        if not raw:
            logger.info("Transcript backfill: no transcripts returned")
            return

        store = SentinelStoreBack._get_global_instance()
        stored = 0

        for t in raw:
            source_id = t.get("id", "")
            if not source_id:
                continue

            formatted = format_transcript(t)
            metadata = formatted.get("metadata", {})

            success = store.store_meeting_transcript(
                transcript_id=source_id,
                title=metadata.get("meeting_title", "Untitled"),
                meeting_date=metadata.get("date"),
                duration=metadata.get("duration"),
                organizer=metadata.get("organizer"),
                participants=metadata.get("participants"),
                summary=formatted["text"] if "Summary:" in formatted["text"] else None,
                full_transcript=formatted["text"],
            )
            if success:
                stored += 1

        logger.info(f"Transcript backfill complete: {stored} of {len(raw)} transcripts stored to PostgreSQL")

    except Exception as e:
        logger.error(f"Transcript backfill failed: {e}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-transcripts", action="store_true",
                        help="One-time: store all Fireflies transcripts to PostgreSQL")
    args = parser.parse_args()

    if args.backfill_transcripts:
        backfill_transcripts_only()
    else:
        check_new_transcripts()
