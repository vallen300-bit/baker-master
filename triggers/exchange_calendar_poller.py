"""
EXCHANGE-CALENDAR-POLL-1: Poll Outlook/Exchange calendar via EWS.
Temporary measure until Microsoft 365 migration.
Returns same format as calendar_trigger.poll_todays_meetings().
"""

import os
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("exchange_calendar_poller")

EXCHANGE_SERVER = "exchange.evok.ch"
EXCHANGE_USER = os.getenv("EXCHANGE_USER", "dvallen@brisengroup.com")
EXCHANGE_PASS = os.getenv("EXCHANGE_PASS", "")


def poll_exchange_todays_meetings() -> list:
    """
    Fetch today's calendar events from Exchange via EWS.
    Returns list of dicts matching Google Calendar poller format:
    {
        "id": "exchange-AAMk...",
        "title": "Minor x Brisengroup",
        "start": "2026-04-08T15:00:00+02:00",
        "end": "2026-04-08T16:00:00+02:00",
        "attendees": [{"name": "...", "email": "...", "response": "..."}],
        "description": "...",
        "location": "Microsoft Teams Meeting; - Boardroom",
        "organizer": "m.herranz@minor-hotels.com",
        "html_link": "",
        "source": "exchange"
    }
    """
    if not EXCHANGE_PASS:
        logger.warning("EXCHANGE_PASS not set — skipping Exchange calendar poll")
        return []

    try:
        from exchangelib import (
            Credentials, Account, Configuration, DELEGATE,
            EWSDateTime, EWSTimeZone,
        )
    except ImportError:
        logger.warning("exchangelib not installed — skipping Exchange calendar poll")
        return []

    try:
        creds = Credentials(EXCHANGE_USER, EXCHANGE_PASS)
        config = Configuration(server=EXCHANGE_SERVER, credentials=creds)
        account = Account(
            EXCHANGE_USER, config=config,
            autodiscover=False, access_type=DELEGATE,
        )

        # Today's events in Director's timezone
        tz = EWSTimeZone.from_timezone(EWSTimeZone.localzone())
        now = datetime.now(timezone.utc)
        start_of_day = EWSDateTime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)
        end_of_day = EWSDateTime(now.year, now.month, now.day, 23, 59, 59, tzinfo=tz)

        items = account.calendar.filter(
            start__lt=end_of_day,
            end__gt=start_of_day,
        ).order_by('start')[:30]  # Safety limit

        meetings = []
        for item in items:
            # Skip all-day events (no specific time)
            if item.is_all_day:
                continue
            # Skip Baker Prep events
            subject = item.subject or ""
            if "[Baker Prep]" in subject:
                continue

            # Map attendees to Google Calendar format
            attendees = []
            if item.required_attendees:
                for a in item.required_attendees[:10]:
                    attendees.append({
                        "name": a.mailbox.name or "",
                        "email": a.mailbox.email_address or "",
                        "response": (a.response_type or "").lower(),
                    })
            if item.optional_attendees:
                for a in item.optional_attendees[:5]:
                    attendees.append({
                        "name": a.mailbox.name or "",
                        "email": a.mailbox.email_address or "",
                        "response": (a.response_type or "").lower(),
                    })

            # Extract organizer email
            organizer_email = ""
            if item.organizer and item.organizer.email_address:
                organizer_email = item.organizer.email_address

            # Build location string
            location = ""
            if item.location:
                location = str(item.location)

            # Extract Teams/Zoom link from body if present
            html_link = ""
            body_text = ""
            if item.body:
                body_text = str(item.body)[:2000]
                # Try to find Teams link
                import re
                teams_match = re.search(r'https://teams\.microsoft\.com/\S+', body_text)
                if teams_match:
                    html_link = teams_match.group(0)

            meetings.append({
                "id": f"exchange-{item.id or ''}",
                "title": subject,
                "start": item.start.isoformat() if item.start else "",
                "end": item.end.isoformat() if item.end else "",
                "attendees": attendees,
                "description": body_text[:500],
                "location": location,
                "organizer": organizer_email,
                "html_link": html_link,
                "source": "exchange",
            })

        logger.info(f"Exchange calendar: {len(meetings)} events for today")

        # Report health
        try:
            from triggers.sentinel_health import report_success
            report_success("exchange_calendar")
        except Exception:
            pass

        return meetings

    except Exception as e:
        logger.error(f"Exchange calendar poll failed: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange_calendar", str(e))
        except Exception:
            pass
        return []
