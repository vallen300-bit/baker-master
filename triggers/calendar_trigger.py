"""
Sentinel Trigger — Google Calendar
Polls for upcoming meetings and triggers auto-prep briefings.
Called by scheduler every 15 minutes.

Phase 3A: Standing Order #1 — "No surprises in meetings."
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import anthropic

from config.settings import config

logger = logging.getLogger("sentinel.trigger.calendar")


# ============================================================
# Calendar Client
# ============================================================

def _get_calendar_service():
    """Authenticate and return Google Calendar API service object.
    Reuses the same OAuth token as Gmail (now includes calendar scope).
    """
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build
    creds = authenticate()
    return build("calendar", "v3", credentials=creds)


def poll_upcoming_meetings(hours_ahead: int = 24) -> list:
    """
    Poll Google Calendar for meetings in the next N hours.
    Returns list of meeting dicts with id, title, start, end, attendees, etc.
    Skips all-day events (only timed meetings).
    """
    service = _get_calendar_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(hours=hours_ahead)

    events_result = service.events().list(
        calendarId='primary',
        timeMin=now.isoformat(),
        timeMax=time_max.isoformat(),
        singleEvents=True,
        orderBy='startTime',
        maxResults=20,
    ).execute()

    events = events_result.get('items', [])
    meetings = []
    for event in events:
        # Skip all-day events (not meetings)
        start = event.get('start', {})
        if 'date' in start and 'dateTime' not in start:
            continue

        # Skip Baker-created prep blocks to prevent cascade
        # (_block_prep_time creates "[Baker Prep] ..." events)
        summary = event.get('summary', '')
        if '[Baker Prep]' in summary:
            continue

        attendees = event.get('attendees', [])
        meetings.append({
            'id': event.get('id', ''),
            'title': event.get('summary', 'Untitled meeting'),
            'start': start.get('dateTime', ''),
            'end': event.get('end', {}).get('dateTime', ''),
            'attendees': [
                {
                    'name': a.get('displayName', ''),
                    'email': a.get('email', ''),
                    'response': a.get('responseStatus', ''),
                }
                for a in attendees
            ],
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'organizer': event.get('organizer', {}).get('email', ''),
            'html_link': event.get('htmlLink', ''),
        })

    logger.info(f"Calendar poll: {len(meetings)} upcoming meetings in next {hours_ahead}h")
    return meetings


def poll_todays_meetings() -> list:
    """
    Fetch ALL of today's timed events (past + future).
    Used by dashboard landing grid so flights/meetings don't vanish once started.
    Same output format as poll_upcoming_meetings().
    """
    service = _get_calendar_service()
    now = datetime.now(timezone.utc)
    # Start of today (UTC midnight)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(hours=24)

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy='startTime',
        maxResults=30,
    ).execute()

    events = events_result.get('items', [])
    meetings = []
    for event in events:
        start = event.get('start', {})
        if 'date' in start and 'dateTime' not in start:
            continue
        summary = event.get('summary', '')
        if '[Baker Prep]' in summary:
            continue

        attendees = event.get('attendees', [])
        meetings.append({
            'id': event.get('id', ''),
            'title': event.get('summary', 'Untitled event'),
            'start': start.get('dateTime', ''),
            'end': event.get('end', {}).get('dateTime', ''),
            'attendees': [
                {
                    'name': a.get('displayName', ''),
                    'email': a.get('email', ''),
                    'response': a.get('responseStatus', ''),
                }
                for a in attendees
            ],
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'organizer': event.get('organizer', {}).get('email', ''),
            'html_link': event.get('htmlLink', ''),
        })

    logger.info(f"Calendar today: {len(meetings)} events for {start_of_day.date()}")
    return meetings


# ============================================================
# Meeting Prep Prompt
# ============================================================

MEETING_PREP_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

Generate a meeting briefing. Include:
1. **WHO**: Each attendee — role, relationship to Director, last interaction, key context
2. **WHAT**: Meeting purpose (inferred from title + description + attendee context)
3. **CONTEXT**: Related matters, recent activity, pending items with attendees
4. **WATCH**: Key points to raise, potential risks, decisions needed
5. **ACTIONS**: What Director should prepare, review, or bring

Be specific — reference real names, projects, dates from the context provided.
Keep it concise and actionable. No filler. Bottom-line first.

If you have no context on an attendee, say so — don't fabricate.
"""


# ============================================================
# Context Assembly
# ============================================================

def _assemble_meeting_context(meeting: dict, store) -> str:
    """Gather all relevant context for a meeting briefing from Baker's memory."""
    parts = []

    # 1. Meeting basics
    parts.append(f"Meeting: {meeting['title']}")
    parts.append(f"Time: {meeting['start']} to {meeting['end']}")
    if meeting.get('location'):
        parts.append(f"Location: {meeting['location']}")
    if meeting.get('description'):
        parts.append(f"Description: {meeting['description']}")

    # 2. Attendee context
    for att in meeting.get('attendees', []):
        name = att.get('name', '') or att.get('email', '')
        if not name:
            continue
        email = att.get('email', '')
        parts.append(f"\n--- Attendee: {name} ({email}) ---")

        # Check VIP contacts
        try:
            conn = store._get_conn()
            if conn:
                try:
                    import psycopg2.extras
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                    # VIP contact lookup
                    cur.execute(
                        "SELECT * FROM vip_contacts WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(email) = LOWER(%s) LIMIT 1",
                        (f"%{name.split('@')[0]}%", email),
                    )
                    vip = cur.fetchone()
                    if vip:
                        parts.append(f"  VIP: {vip.get('name', '')} — {vip.get('role', '')} (tier {vip.get('tier', '?')})")
                        if vip.get('role_context'):
                            parts.append(f"  Context: {vip['role_context']}")
                        if vip.get('expertise'):
                            parts.append(f"  Expertise: {vip['expertise']}")

                    # Recent emails (last 30 days)
                    cur.execute(
                        """SELECT subject, sender_name, received_date
                           FROM email_messages
                           WHERE (LOWER(sender_email) = LOWER(%s) OR LOWER(subject) ILIKE %s)
                             AND received_date >= NOW() - INTERVAL '30 days'
                           ORDER BY received_date DESC LIMIT 5""",
                        (email, f"%{name.split('@')[0]}%"),
                    )
                    emails = cur.fetchall()
                    if emails:
                        parts.append(f"  Recent emails ({len(emails)}):")
                        for em in emails:
                            parts.append(f"    - {em['subject']} ({em['received_date'].strftime('%b %d') if em.get('received_date') else '?'})")

                    # Recent WhatsApp (last 30 days)
                    cur.execute(
                        """SELECT sender_name, full_text, timestamp
                           FROM whatsapp_messages
                           WHERE LOWER(sender_name) ILIKE %s
                             AND timestamp >= NOW() - INTERVAL '30 days'
                           ORDER BY timestamp DESC LIMIT 3""",
                        (f"%{name.split('@')[0]}%",),
                    )
                    wa_msgs = cur.fetchall()
                    if wa_msgs:
                        parts.append(f"  Recent WhatsApp ({len(wa_msgs)}):")
                        for msg in wa_msgs:
                            snippet = (msg.get('full_text') or '')[:80]
                            parts.append(f"    - {snippet}... ({msg['timestamp'].strftime('%b %d') if msg.get('timestamp') else '?'})")

                    # Past meetings with this person
                    cur.execute(
                        """SELECT title, meeting_date
                           FROM meeting_transcripts
                           WHERE LOWER(participants) ILIKE %s
                           ORDER BY meeting_date DESC LIMIT 3""",
                        (f"%{name.split('@')[0]}%",),
                    )
                    past_meetings = cur.fetchall()
                    if past_meetings:
                        parts.append(f"  Past meetings ({len(past_meetings)}):")
                        for pm in past_meetings:
                            parts.append(f"    - {pm['title']} ({pm['meeting_date'].strftime('%b %d') if pm.get('meeting_date') else '?'})")

                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Context assembly error for {name}: {e}")

    # 2b. AO-specific enrichment: mood context for AO meetings
    ao_keywords = ["oskolkov", "andrey", "aelio", "ao ", "andrej"]
    attendee_names = [a.get('name', '') or a.get('email', '') for a in meeting.get('attendees', [])]
    meeting_text = (meeting.get('title', '') + " " + " ".join(attendee_names)).lower()
    is_ao_meeting = any(k in meeting_text for k in ao_keywords)

    if is_ao_meeting:
        try:
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT full_text FROM whatsapp_messages
                        WHERE (sender_name ILIKE '%oskolkov%' OR sender_name ILIKE '%andrey%')
                          AND timestamp > NOW() - INTERVAL '7 days'
                        ORDER BY timestamp DESC LIMIT 5
                    """)
                    ao_msgs = [r[0] for r in cur.fetchall() if r[0]]
                    if ao_msgs:
                        from triggers.proactive_scanner import classify_ao_mood
                        combined = " ".join(ao_msgs)
                        mood = classify_ao_mood(combined)
                        parts.append(
                            f"\n--- AO PROFILING CONTEXT ---\n"
                            f"Recent mood: {mood.upper()}\n"
                            f"Last {len(ao_msgs)} messages analyzed.\n"
                            f"Approach: {'Collaborative, reinforce partnership' if mood == 'positive' else 'Careful, address concerns first' if mood == 'negative' else 'Neutral — standard engagement'}\n"
                        )
                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception as e:
            logger.warning(f"AO meeting enrichment failed: {e}")

    # 3. Related matters (check if meeting title matches any matter keywords)
    try:
        from orchestrator.pipeline import _match_matter_slug
        slug = _match_matter_slug(meeting['title'], meeting.get('description', ''), store)
        if slug:
            parts.append(f"\nRelated matter: {slug}")
    except Exception:
        pass

    context = "\n".join(parts)
    # Limit to ~4000 tokens (~16000 chars)
    if len(context) > 16000:
        context = context[:16000] + "\n\n[Context truncated]"

    return context


# ============================================================
# Briefing Generation (direct Haiku call — NOT /api/scan)
# ============================================================

def _generate_meeting_briefing(meeting: dict, context: str) -> Optional[str]:
    """Generate a meeting prep briefing using Haiku. Returns markdown text."""
    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=MEETING_PREP_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Prepare a briefing for this meeting.\n\n{context}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_prep")
        except Exception:
            pass
        briefing = resp.content[0].text.strip()
        logger.info(f"Generated meeting briefing for '{meeting['title']}' ({len(briefing)} chars)")
        return briefing
    except Exception as e:
        logger.error(f"Meeting briefing generation failed for '{meeting['title']}': {e}")
        return None


# ============================================================
# Main Entry Point (called by scheduler every 15 minutes)
# ============================================================

def check_calendar_and_prep():
    """
    Main entry point — called by scheduler every 15 minutes.
    1. Poll upcoming meetings (next 24 hours)
    2. For each meeting not yet prepped → generate briefing
    3. Store briefing as T2 alert card
    """
    from triggers.sentinel_health import report_success, report_failure
    from memory.store_back import SentinelStoreBack
    from triggers.state import trigger_state
    from orchestrator.pipeline import _match_matter_slug, _auto_tag


    try:
        try:
            meetings = poll_upcoming_meetings(hours_ahead=24)
        except Exception as e:
            logger.warning(f"Calendar poll failed (API unreachable or token expired): {e}")
            return  # Graceful failure — don't crash scheduler

        if not meetings:
            logger.info("No upcoming meetings — nothing to prep")
            return

        store = SentinelStoreBack._get_global_instance()
        prepped_count = 0

        for meeting in meetings:
            event_id = meeting.get('id', '')
            if not event_id:
                continue

            # Dedup: check if already prepped
            watermark_key = f"calendar_prep_{event_id}"
            if trigger_state.watermark_exists(watermark_key):
                logger.debug(f"Already prepped: {meeting['title']} ({event_id})")
                continue

            # Assemble context from Baker's memory
            context = _assemble_meeting_context(meeting, store)

            # Generate briefing via Haiku
            briefing = _generate_meeting_briefing(meeting, context)
            if not briefing:
                continue

            # Build alert title + body
            start_str = meeting.get('start', '')
            try:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                time_label = start_dt.strftime('%H:%M %b %d')
            except (ValueError, AttributeError):
                time_label = start_str

            attendee_names = [a.get('name', '') or a.get('email', '') for a in meeting.get('attendees', [])]
            attendee_str = ", ".join(attendee_names[:5])
            if len(attendee_names) > 5:
                attendee_str += f" +{len(attendee_names) - 5} more"

            alert_title = f"Meeting prep: {meeting['title']}"
            alert_body = f"**{time_label}**"
            if attendee_str:
                alert_body += f" | {attendee_str}"
            if meeting.get('location'):
                alert_body += f" | {meeting['location']}"
            alert_body += f"\n\n{briefing}"

            # Auto-assign matter + tags
            matter_slug = _match_matter_slug(alert_title, alert_body, store)
            tags = _auto_tag(alert_title, alert_body)
            if "meeting" not in tags:
                tags.append("meeting")

            # Create T2 alert
            alert_id = store.create_alert(
                tier=2,
                title=alert_title,
                body=alert_body,
                action_required=False,
                matter_slug=matter_slug,
                tags=tags,
                source="calendar_prep",
            )

            if alert_id:
                # Mark as prepped (dedup)
                trigger_state.set_watermark(watermark_key, datetime.now(timezone.utc))
                prepped_count += 1
                logger.info(f"Meeting prep alert #{alert_id} created: {meeting['title']}")

                # Phase 3C: Block 15 min prep time on calendar
                _block_prep_time(meeting)

        # Phase 3C: Detect calendar conflicts
        _detect_and_alert_conflicts(meetings, store, trigger_state)

        report_success("calendar")
        logger.info(f"Calendar prep complete: {prepped_count} new briefings created from {len(meetings)} upcoming meetings")

    except Exception as e:
        report_failure("calendar", str(e))
        logger.error(f"calendar poll failed: {e}")


def _block_prep_time(meeting: dict):
    """Create a 15-minute prep block before a meeting on the Director's calendar.
    Uses Google Calendar API write (calendar scope is already authorized).
    """
    start_str = meeting.get('start', '')
    if not start_str:
        return

    try:
        service = _get_calendar_service()
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        prep_start = start - timedelta(minutes=15)
        prep_end = start

        event = {
            'summary': f'[Baker Prep] {meeting["title"]}',
            'description': 'Auto-blocked by Baker for meeting preparation.',
            'start': {'dateTime': prep_start.isoformat(), 'timeZone': 'Europe/Zurich'},
            'end': {'dateTime': prep_end.isoformat(), 'timeZone': 'Europe/Zurich'},
            'reminders': {'useDefault': False},
            'transparency': 'opaque',
        }

        service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"Prep block created: {prep_start.strftime('%H:%M')}-{prep_end.strftime('%H:%M')} for '{meeting['title']}'")
    except Exception as e:
        logger.warning(f"Failed to create prep block for '{meeting['title']}': {e}")


def _detect_conflicts(meetings: list) -> list:
    """Detect overlapping meetings. Returns list of (meeting_a, meeting_b) tuples."""
    conflicts = []
    for i in range(len(meetings)):
        for j in range(i + 1, len(meetings)):
            a_end = meetings[i].get('end', '')
            b_start = meetings[j].get('start', '')
            if a_end and b_start and a_end > b_start:
                conflicts.append((meetings[i], meetings[j]))
    return conflicts


def _detect_and_alert_conflicts(meetings: list, store, trigger_state):
    """Detect calendar conflicts and create T2 alerts. Dedup via watermarks."""
    conflicts = _detect_conflicts(meetings)
    for a, b in conflicts:
        a_id = a.get('id', '')
        b_id = b.get('id', '')
        # Consistent key regardless of order
        ids = sorted([a_id, b_id])
        wk = f"calendar_conflict_{ids[0]}_{ids[1]}"
        if trigger_state.watermark_exists(wk):
            continue

        store.create_alert(
            tier=2,
            title=f"Calendar conflict: {a['title'][:40]} overlaps {b['title'][:40]}",
            body=(
                f"**{a['title']}** ({a.get('start', '?')})\n"
                f"overlaps with\n"
                f"**{b['title']}** ({b.get('start', '?')})\n\n"
                f"Consider rescheduling one of these meetings."
            ),
            action_required=True,
            tags=["calendar", "conflict"],
            source="calendar_protection",
        )
        trigger_state.set_watermark(wk, datetime.now(timezone.utc))
        logger.info(f"Calendar conflict alert: '{a['title']}' vs '{b['title']}'")

