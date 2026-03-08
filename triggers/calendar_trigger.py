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
                        """SELECT subject, sender_name, received_at
                           FROM email_messages
                           WHERE (LOWER(sender_email) = LOWER(%s) OR LOWER(subject) ILIKE %s)
                             AND received_at >= NOW() - INTERVAL '30 days'
                           ORDER BY received_at DESC LIMIT 5""",
                        (email, f"%{name.split('@')[0]}%"),
                    )
                    emails = cur.fetchall()
                    if emails:
                        parts.append(f"  Recent emails ({len(emails)}):")
                        for em in emails:
                            parts.append(f"    - {em['subject']} ({em['received_at'].strftime('%b %d') if em.get('received_at') else '?'})")

                    # Recent WhatsApp (last 30 days)
                    cur.execute(
                        """SELECT sender_name, body, received_at
                           FROM whatsapp_messages
                           WHERE LOWER(sender_name) ILIKE %s
                             AND received_at >= NOW() - INTERVAL '30 days'
                           ORDER BY received_at DESC LIMIT 3""",
                        (f"%{name.split('@')[0]}%",),
                    )
                    wa_msgs = cur.fetchall()
                    if wa_msgs:
                        parts.append(f"  Recent WhatsApp ({len(wa_msgs)}):")
                        for msg in wa_msgs:
                            snippet = (msg.get('body') or '')[:80]
                            parts.append(f"    - {snippet}... ({msg['received_at'].strftime('%b %d') if msg.get('received_at') else '?'})")

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
    from memory.store_back import SentinelStoreBack
    from triggers.state import trigger_state
    from orchestrator.pipeline import _match_matter_slug, _auto_tag

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
        )

        if alert_id:
            # Mark as prepped (dedup)
            trigger_state.set_watermark(watermark_key, datetime.now(timezone.utc))
            prepped_count += 1
            logger.info(f"Meeting prep alert #{alert_id} created: {meeting['title']}")

    if prepped_count:
        logger.info(f"Calendar prep complete: {prepped_count} new briefings created")
