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


def poll_meetings_by_date_range(start_date_str: str, end_date_str: str) -> list:
    """
    TRIP-INTELLIGENCE-1 Batch 2: Fetch calendar events for a date range.
    start_date_str/end_date_str: ISO date strings (YYYY-MM-DD).
    Returns same format as poll_todays_meetings().
    """
    service = _get_calendar_service()
    start_dt = datetime.fromisoformat(start_date_str + "T00:00:00+00:00")
    end_dt = datetime.fromisoformat(end_date_str + "T23:59:59+00:00")

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_dt.isoformat(),
        timeMax=end_dt.isoformat(),
        singleEvents=True,
        orderBy='startTime',
        maxResults=100,
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

        meetings.append({
            'id': event.get('id', ''),
            'title': summary or 'Untitled event',
            'start': start.get('dateTime', ''),
            'end': event.get('end', {}).get('dateTime', ''),
            'attendees': [
                {'name': a.get('displayName', ''), 'email': a.get('email', '')}
                for a in event.get('attendees', [])
            ],
            'description': event.get('description', ''),
            'location': event.get('location', ''),
        })

    logger.info(f"Calendar range {start_date_str} to {end_date_str}: {len(meetings)} events")
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

IMPORTANT — Travel events (flights, trains):
- If the event is a flight/travel, do NOT generate generic filler like "confirm what you're traveling for".
- If trip context is provided (trip purpose, contacts, obligations), lead with that.
- Focus on: trip purpose, who you're meeting at the destination, key obligations, logistics that need attention.
- If there is NO trip context and NO attendees, keep the briefing very short: just flight details and a note that no trip context was found. Do NOT pad with generic advice like "prepare travel documents" or "brief absence coverage".
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

    # 1b. Trip context — check if this event is linked to a known trip
    try:
        conn = store._get_conn()
        if conn:
            try:
                import psycopg2.extras
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Match trip by date overlap and destination mention in title/location
                meeting_start = meeting.get('start', '')[:10]  # YYYY-MM-DD
                cur.execute("""
                    SELECT t.id, t.destination, t.origin, t.category, t.status, t.event_name,
                           t.strategic_objective, t.start_date, t.end_date
                    FROM trips t
                    WHERE t.status IN ('planned', 'confirmed')
                      AND t.start_date <= %s::date + INTERVAL '1 day'
                      AND COALESCE(t.end_date, t.start_date) >= %s::date - INTERVAL '1 day'
                    ORDER BY t.start_date
                    LIMIT 3
                """, (meeting_start, meeting_start))
                trips = cur.fetchall()
                for trip in trips:
                    parts.append(f"\n--- LINKED TRIP: {trip.get('destination', '')} ({trip.get('event_name') or trip.get('category', '')}) ---")
                    parts.append(f"  Status: {trip.get('status', '')} | {trip.get('start_date', '')} to {trip.get('end_date', '')}")
                    if trip.get('strategic_objective'):
                        parts.append(f"  Purpose: {trip['strategic_objective']}")

                    # Trip contacts
                    cur.execute("""
                        SELECT tc.role, tc.roi_type, tc.roi_score, tc.notes, vc.name, vc.role as contact_role
                        FROM trip_contacts tc
                        JOIN vip_contacts vc ON vc.id = tc.contact_id
                        WHERE tc.trip_id = %s
                        ORDER BY tc.roi_score DESC NULLS LAST
                        LIMIT 10
                    """, (trip['id'],))
                    trip_contacts = cur.fetchall()
                    if trip_contacts:
                        parts.append(f"  Key people ({len(trip_contacts)}):")
                        for tc in trip_contacts:
                            parts.append(f"    - {tc['name']} ({tc.get('contact_role', '')}) — {tc.get('notes', '')[:100]}")

                    # Related obligations
                    cur.execute("""
                        SELECT description, due_date, severity, priority
                        FROM deadlines
                        WHERE status = 'active'
                          AND (LOWER(description) ILIKE %s OR LOWER(description) ILIKE %s)
                        ORDER BY due_date
                        LIMIT 5
                    """, (f"%{trip.get('destination', '').lower()}%",
                          f"%{(trip.get('event_name') or '').lower()}%" if trip.get('event_name') else '%ZZZNEVERMATCH%'))
                    trip_obligations = cur.fetchall()
                    if trip_obligations:
                        parts.append(f"  Obligations ({len(trip_obligations)}):")
                        for ob in trip_obligations:
                            parts.append(f"    - [{ob.get('severity', '').upper()}] {ob['description'][:100]} (due {ob.get('due_date', '?')})")

                cur.close()
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Trip context assembly failed: {e}")

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

                    # F7: Gap detection — flag when Baker has no data about attendee
                    has_data = bool(vip) or bool(emails) or bool(wa_msgs) or bool(past_meetings)
                    if not has_data:
                        parts.append(f"  ⚠ KNOWLEDGE GAP: Baker has NO data about {name}. Consider researching before the meeting.")

                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Context assembly error for {name}: {e}")

    # 2b. Historical enrichment
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
# Travel Event Detection
# ============================================================

_TRAVEL_KEYWORDS = {"flight", "depart", "arrive", "airport", "train", "taxi", "uber", "transfer", "check-in", "check-out"}

def _is_travel_event(meeting: dict) -> bool:
    """Check if a calendar event is travel (not a real meeting)."""
    title = (meeting.get("title") or "").lower()
    return any(kw in title for kw in _TRAVEL_KEYWORDS)


# ============================================================
# Tactical Meeting Brief (Opus — for counterparty meetings)
# ============================================================

_TACTICAL_PROMPT = """You are Baker, AI Chief of Staff. Generate a TACTICAL BRIEF for this meeting.

This is NOT a summary — it's a negotiation/strategy guide. Include:

1. **YOUR POSITION**: What the Director wants from this meeting. Specific outcomes.
2. **THEIR POSITION**: What the counterparty likely wants. What they'll push for.
3. **OPENING**: How to start the conversation. First 2 minutes matter.
4. **CONCESSIONS**: Things you can offer that cost little but they'll value.
5. **RED LINES**: What to absolutely NOT agree to, and why.
6. **LEVERAGE**: Information or timing advantages you have.
7. **TALKING POINTS**: 3-5 specific points to raise, in order.

Base everything on REAL data from the context — past communications, documents, decisions.
If you don't have enough context for tactical guidance, say so briefly rather than fabricating.
Keep it to 1 page. Bottom-line first."""


def _generate_tactical_brief(meeting: dict, context: str, matter_slug: str, store) -> Optional[str]:
    """Generate tactical negotiation guidance using Opus. Returns markdown text."""
    # Enrich context with Director's past decisions on this matter
    enriched = context
    try:
        import psycopg2.extras
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Past decisions for this matter
                cur.execute("""
                    SELECT decision, reasoning, created_at
                    FROM decisions
                    WHERE project = %s OR decision ILIKE %s
                    ORDER BY created_at DESC LIMIT 5
                """, (matter_slug, f"%{matter_slug}%"))
                decisions = [dict(r) for r in cur.fetchall()]
                cur.close()
                if decisions:
                    enriched += "\n\n## PAST DECISIONS ON THIS MATTER\n"
                    for d in decisions:
                        date = d["created_at"].strftime("%Y-%m-%d") if d.get("created_at") else "?"
                        enriched += f"- [{date}] {d['decision']}: {d.get('reasoning', '')}\n"
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    # Add weekly priorities for context
    try:
        from orchestrator.priority_manager import format_priorities_for_prompt
        prio_text = format_priorities_for_prompt()
        if prio_text:
            enriched += f"\n\n{prio_text}"
    except Exception:
        pass

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model=config.claude.model,  # Opus for tactical quality
            max_tokens=2048,
            system=_TACTICAL_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Generate a tactical brief for this meeting.\n\n{enriched[:6000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, resp.usage.input_tokens,
                         resp.usage.output_tokens, source="tactical_brief")
        except Exception:
            pass
        brief = resp.content[0].text.strip()
        logger.info(f"Tactical brief generated for '{meeting['title']}' ({len(brief)} chars)")
        return brief
    except Exception as e:
        logger.error(f"Tactical brief generation failed: {e}")
        return None


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

                # Tactical brief: generate negotiation guidance for meetings with known counterparties
                if matter_slug and meeting.get('attendees') and not _is_travel_event(meeting):
                    try:
                        tactical = _generate_tactical_brief(meeting, context, matter_slug, store)
                        if tactical:
                            # Append tactical section to the alert body
                            updated_body = alert_body + f"\n\n---\n\n**TACTICAL BRIEF**\n{tactical}"
                            conn_upd = store._get_conn()
                            if conn_upd:
                                try:
                                    cur_upd = conn_upd.cursor()
                                    cur_upd.execute(
                                        "UPDATE alerts SET body = %s WHERE id = %s",
                                        (updated_body[:8000], alert_id),
                                    )
                                    conn_upd.commit()
                                    cur_upd.close()
                                    logger.info(f"Tactical brief appended to alert #{alert_id}")
                                finally:
                                    store._put_conn(conn_upd)
                    except Exception as tac_err:
                        logger.warning(f"Tactical brief failed for {meeting['title']} (non-fatal): {tac_err}")

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

