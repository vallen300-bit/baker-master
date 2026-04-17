# BRIEF: EXCHANGE-CALENDAR-POLL-1 — Poll Outlook Calendar via EWS

## Context
Director's primary calendar is Outlook/Exchange on `exchange.evok.ch`. Meeting invites from external contacts (Minor Hotels, legal counsel, etc.) land there, not in Google Calendar. Baker only polls Google Calendar today — Director missed a Minor Hotels meeting invite because of this.

EWS endpoint tested and confirmed working: `exchange.evok.ch/EWS/Exchange.asmx` (401 = exists, needs auth). Full calendar read test succeeded — returned "Minor x Brisengroup" meeting with correct time, location, organizer, attendees.

**Temporary measure** until Microsoft 365 migration. Uses same `EXCHANGE_USER`/`EXCHANGE_PASS` env vars already set on Render.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: `exchangelib` in requirements.txt, `EXCHANGE_USER`/`EXCHANGE_PASS` on Render (already set)

---

## Feature 1: Exchange Calendar Poller Module

### Problem
Baker has no visibility into Outlook/Exchange calendar. Meeting invites from external contacts are invisible.

### Current State
- `triggers/calendar_trigger.py` → `poll_todays_meetings()` (lines 91-145) — Google Calendar only
- Returns list of dicts: `{id, title, start, end, attendees, description, location, organizer, html_link}`
- `outputs/dashboard.py` lines 2355-2409 — consumes `poll_todays_meetings()`, classifies as meeting vs travel
- No EWS/Exchange calendar code exists anywhere in the codebase
- `exchangelib` not in requirements.txt

### Implementation

**Add to `requirements.txt`:**
```
exchangelib>=5.5.0
```

**Create:** `triggers/exchange_calendar_poller.py`

```python
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
```

### Key Constraints
- **Read-only** — only reads calendar, never creates/modifies events
- **Max 30 events per poll** — safety limit via slice `[:30]`
- **Skips all-day events** — only timed meetings
- **Skips `[Baker Prep]`** — matches Google Calendar filter
- **Non-fatal** — if EWS fails, returns empty list, dashboard still works with Google Calendar
- **Same output format** as `poll_todays_meetings()` — `{id, title, start, end, attendees, description, location, organizer, html_link}`
- **Extra field `source: "exchange"`** — enables dedup against Google Calendar
- **Temporary** — will be replaced by M365 Graph API

---

## Feature 2: Merge Into Morning Brief

### Problem
Exchange calendar events need to appear in the Meetings card alongside Google Calendar events.

### Current State
`outputs/dashboard.py` lines 2355-2409 — calls `poll_todays_meetings()` and classifies results.

### Implementation

**File:** `outputs/dashboard.py`

After the existing Google Calendar block (after line 2409), add:

```python
        # EXCHANGE-CALENDAR-POLL-1: Merge Exchange/Outlook calendar events
        try:
            from triggers.exchange_calendar_poller import poll_exchange_todays_meetings
            exchange_events = poll_exchange_todays_meetings()
            for m in exchange_events:
                # Dedup: skip if same title + same start time already in meetings_today or travel_today
                m_title = (m.get('title', '') or '').lower().strip()
                m_start = (m.get('start', '') or '')[:16]  # Compare to minute precision
                already_exists = False
                for existing in meetings_today + travel_today:
                    if (existing.get('title', '') or '').lower().strip() == m_title and \
                       (existing.get('start', '') or '')[:16] == m_start:
                        already_exists = True
                        break
                if already_exists:
                    continue

                attendee_names = [a.get('name', '') or a.get('email', '') for a in m.get('attendees', [])]
                event_data = {
                    "title": m['title'],
                    "start": m['start'],
                    "end": m.get('end', ''),
                    "location": m.get('location', ''),
                    "attendees": attendee_names[:5],
                    "prepped": False,
                    "prep_notes": "",
                    "source": "exchange",
                }

                if _is_travel_event(m['title'], m.get('location', '')):
                    event_data["event_type"] = "travel"
                    travel_today.append(event_data)
                else:
                    event_data["event_type"] = "meeting"
                    meetings_today.append(event_data)

            if exchange_events:
                logger.info(f"Exchange calendar: merged {len(exchange_events)} events into morning brief")
        except Exception as e:
            logger.warning(f"Morning brief: Exchange calendar unavailable (non-fatal): {e}")
```

### Key Constraints
- **Dedup by title + start time** — prevents showing same meeting twice if it's in both Google and Exchange calendars
- **Same classification logic** — uses existing `_is_travel_event()` to split meetings vs travel
- **Non-fatal wrapper** — Exchange failure never breaks the morning brief
- **`prepped: False`** — Exchange events start as unprepped (Baker can prep them like Google events)
- Insert **after** Google Calendar block so Google events take priority in dedup

---

## Feature 3: Sentinel Health Monitoring

### Problem
Exchange calendar poller must report health like all other integrations.

### Implementation

Already handled in Feature 1 code — `report_success("exchange_calendar")` and `report_failure("exchange_calendar", ...)` calls are in `poll_exchange_todays_meetings()`.

**File: `triggers/sentinel_health.py`**

Add to `_WATERMARK_MAX_AGE` dict (not strictly needed since this polls on-demand from the morning brief endpoint, not via scheduler — but useful for the stale watermark detector if we later add a scheduled job):

No change needed — health reporting is sufficient without watermark monitoring since this runs on-demand, not on a timer.

---

## Files Modified
- `triggers/exchange_calendar_poller.py` — **NEW** — EWS calendar poller
- `outputs/dashboard.py` — Add ~30 lines after Google Calendar block to merge Exchange events
- `requirements.txt` — Add `exchangelib>=5.5.0`

## Do NOT Touch
- `triggers/calendar_trigger.py` — Google Calendar poller, unchanged
- `triggers/exchange_poller.py` — Email IMAP poller, unrelated
- `triggers/embedded_scheduler.py` — No separate scheduler job needed
- `outputs/static/app.js` — Frontend already renders any meeting in `meetings_today`, no changes needed

## Quality Checkpoints
1. Syntax check: `python3 -c "import py_compile; py_compile.compile('triggers/exchange_calendar_poller.py', doraise=True)"`
2. Verify `exchangelib` added to requirements.txt
3. After deploy, reload Baker dashboard — Minor Hotels meeting should appear in Meetings card
4. Verify dedup: if same meeting is in both Google and Exchange calendars, it appears only once
5. Verify travel classification: flight-related Exchange events go to Travel card, not Meetings
6. Check Render logs for: `Exchange calendar: N events for today`
7. Check sentinel health: `SELECT * FROM sentinel_health WHERE source = 'exchange_calendar' LIMIT 1`
8. Verify non-fatal: if Exchange is down, Google Calendar meetings still show

## Verification SQL
```sql
-- Check Exchange calendar health
SELECT source, status, last_success_at, last_error_at, LEFT(last_error_msg, 200) as error
FROM sentinel_health
WHERE source = 'exchange_calendar' LIMIT 1;
```

## Deprecation Note
This poller is **temporary**. When Brisengroup migrates to Microsoft 365:
1. Replace `exchangelib` EWS with Microsoft Graph API (`/me/calendarview`)
2. Remove `exchangelib` from requirements.txt
3. Update `exchange_calendar_poller.py` to use Graph API (or merge into `calendar_trigger.py`)
