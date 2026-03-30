# BRIEF: Google Calendar API Integration

**Priority:** Medium — Baker has no calendar visibility, misses meetings like Sandra's 10:30 call
**Ticket:** GOOGLE-CALENDAR-4
**Depends on:** Nothing — standalone
**Pre-requisite:** Google OAuth re-authorization with calendar scope (see below)

## Problem

Baker can't see the Director's calendar. Meetings created by external tools (Zoom invites, Sandra confirming 10:30) are invisible. Baker has to be told manually about every meeting.

## Solution

Poll Google Calendar every 5 minutes. Store events in a `calendar_events` table. Feed into the Meetings card on the dashboard landing page.

## Pre-requisite: OAuth Scope

The existing Gmail OAuth token needs the calendar scope added. This requires a one-time re-authorization.

**Option A (preferred): Run locally**
```bash
# Add calendar scope to the existing Gmail credentials
python3 scripts/extract_gmail.py --reauth --scopes "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/calendar.readonly"
```
This opens a browser for consent. After approval, upload the new token to Render.

**Option B: Manual**
1. Go to Google Cloud Console → APIs & Services → Credentials
2. Edit the existing OAuth client
3. Add `https://www.googleapis.com/auth/calendar.readonly` to scopes
4. Re-download credentials
5. Re-run auth flow to get new token with both Gmail + Calendar scopes

**IMPORTANT:** Do NOT proceed with the code changes until the OAuth token has calendar scope. The calendar trigger will fail with 403 Insufficient Permissions otherwise. Ask the Director to do the re-auth step first, or check if it can be done from Render.

Check how the current Gmail auth works:
```bash
grep -n "SCOPES\|credentials\|token" scripts/extract_gmail.py | head -20
grep -n "gmail.*credentials\|GMAIL_TOKEN\|_get_gmail_service" triggers/email_trigger.py | head -10
```

## Implementation

### Change 1: Calendar events table

**File:** `outputs/dashboard.py` (startup migration block)

```sql
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    title TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location TEXT,
    description TEXT,
    attendees JSONB,
    conference_url TEXT,
    organizer TEXT,
    status TEXT DEFAULT 'confirmed',
    source TEXT DEFAULT 'google',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cal_start ON calendar_events(start_time);
```

### Change 2: Calendar trigger

**File:** `triggers/calendar_trigger.py` (NEW FILE)

```python
"""
Sentinel Trigger — Google Calendar
Polls primary calendar every 5 minutes for events in the next 7 days.
Stores/updates events in calendar_events table.

Called by embedded_scheduler every 5 minutes.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("sentinel.calendar_trigger")


def poll_calendar():
    """Poll Google Calendar for upcoming events (next 7 days)."""
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("calendar"):
        return

    try:
        service = _get_calendar_service()
        if not service:
            logger.warning("Calendar service unavailable — skipping poll")
            return

        now = datetime.utcnow().isoformat() + 'Z'
        week_later = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=week_later,
            singleEvents=True,
            orderBy='startTime',
            maxResults=50,
        ).execute()

        events = events_result.get('items', [])
        stored = 0

        for event in events:
            try:
                _store_calendar_event(event)
                stored += 1
            except Exception as e:
                logger.debug(f"Failed to store calendar event: {e}")

        report_success("calendar")
        logger.info(f"Calendar poll: {len(events)} events found, {stored} stored/updated")

    except Exception as e:
        report_failure("calendar", str(e))
        logger.error(f"Calendar poll failed: {e}")


def _get_calendar_service():
    """Build Google Calendar API service using existing Gmail credentials."""
    try:
        # Reuse the same credential loading as Gmail
        from triggers.email_trigger import _get_gmail_service
        from googleapiclient.discovery import build

        # Get the credentials from the Gmail service
        gmail_service = _get_gmail_service()
        if not gmail_service:
            return None

        # The credentials are stored on the service object
        creds = gmail_service._http.credentials
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build calendar service: {e}")
        return None


def _store_calendar_event(event):
    """Upsert a calendar event into the database."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        import json
        event_id = event.get('id', '')
        if not event_id:
            return

        # Parse start/end times
        start = event.get('start', {})
        end = event.get('end', {})
        start_time = start.get('dateTime') or start.get('date')
        end_time = end.get('dateTime') or end.get('date')

        # Parse attendees
        attendees = []
        for att in event.get('attendees', []):
            attendees.append({
                'email': att.get('email', ''),
                'name': att.get('displayName', ''),
                'status': att.get('responseStatus', 'needsAction'),
            })

        # Extract conference URL (Zoom, Meet, etc.)
        conference_url = None
        entry_points = event.get('conferenceData', {}).get('entryPoints', [])
        for ep in entry_points:
            if ep.get('entryPointType') == 'video':
                conference_url = ep.get('uri')
                break
        # Also check description for Zoom links
        description = event.get('description', '') or ''
        if not conference_url and 'zoom.us' in description.lower():
            import re
            zoom_match = re.search(r'https://[^\s]*zoom\.us/[^\s<>"]+', description)
            if zoom_match:
                conference_url = zoom_match.group()

        organizer = event.get('organizer', {}).get('email', '')
        status = event.get('status', 'confirmed')
        title = event.get('summary', 'No title')
        location = event.get('location', '')

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO calendar_events (id, title, start_time, end_time, location, description,
                                          attendees, conference_url, organizer, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                location = EXCLUDED.location,
                description = EXCLUDED.description,
                attendees = EXCLUDED.attendees,
                conference_url = EXCLUDED.conference_url,
                organizer = EXCLUDED.organizer,
                status = EXCLUDED.status,
                updated_at = NOW()
        """, (event_id, title, start_time, end_time, location, description[:2000],
              json.dumps(attendees), conference_url, organizer, status))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"Calendar event store failed: {e}")
    finally:
        store._put_conn(conn)
```

**IMPORTANT:** The credential reuse approach (`gmail_service._http.credentials`) may not work depending on how the Gmail service is built. Check `_get_gmail_service()` in `triggers/email_trigger.py` to understand how credentials are loaded. You may need to load credentials directly from the token file/env var instead.

### Change 3: Register in scheduler

**File:** `triggers/embedded_scheduler.py`

```python
# Google Calendar poll (every 5 min)
try:
    from triggers.calendar_trigger import poll_calendar
    scheduler.add_job(
        poll_calendar,
        IntervalTrigger(minutes=5),
        id="calendar_poll", name="Google Calendar poll",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: calendar_poll (every 5 min)")
except ImportError:
    logger.info("calendar_trigger not available — skipping")
```

### Change 4: Dashboard Meetings card integration

**File:** `outputs/dashboard.py`

Find the endpoint that powers the Meetings card on the landing page. Add calendar events as an additional data source:

```python
# In the meetings/briefing endpoint, after fetching meeting_transcripts:
try:
    cur.execute("""
        SELECT id, title, start_time, end_time, attendees, conference_url, location, status
        FROM calendar_events
        WHERE start_time >= NOW()
          AND start_time < NOW() + INTERVAL '3 days'
          AND status != 'cancelled'
        ORDER BY start_time ASC
        LIMIT 10
    """)
    for row in cur.fetchall():
        meetings.append({
            "title": row[1],
            "start_time": row[2].isoformat() if row[2] else None,
            "end_time": row[3].isoformat() if row[3] else None,
            "attendees": row[4],
            "conference_url": row[5],
            "location": row[6],
            "status": row[7],
            "source": "calendar",
        })
except Exception:
    pass  # calendar_events table may not exist yet
```

**IMPORTANT:** Find the actual endpoint that powers the Meetings card. It might be in `loadMorningBrief()` → `/api/briefing` or a separate meetings endpoint. Check what the frontend expects and adapt the response format to match.

### Change 5: API endpoint for calendar events

**File:** `outputs/dashboard.py`

```python
@app.get("/api/calendar", tags=["calendar"], dependencies=[Depends(verify_api_key)])
async def list_calendar_events(days: int = 7):
    """List upcoming calendar events."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, start_time, end_time, location, attendees,
                   conference_url, organizer, status
            FROM calendar_events
            WHERE start_time >= NOW()
              AND start_time < NOW() + INTERVAL '%s days'
              AND status != 'cancelled'
            ORDER BY start_time ASC
            LIMIT 50
        """, (days,))
        rows = cur.fetchall()
        cur.close()
        return [{
            "id": r[0], "title": r[1],
            "start_time": r[2].isoformat() if r[2] else None,
            "end_time": r[3].isoformat() if r[3] else None,
            "location": r[4], "attendees": r[5],
            "conference_url": r[6], "organizer": r[7], "status": r[8],
        } for r in rows]
    finally:
        store._put_conn(conn)
```

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Table migration, meetings card integration, /api/calendar endpoint |
| `triggers/calendar_trigger.py` | NEW FILE — poll_calendar(), credential loading, event storage |
| `triggers/embedded_scheduler.py` | Register calendar_poll job |

## Pre-check

```bash
# Understand how Gmail credentials work
grep -n "SCOPES\|credentials\|token\|_get_gmail_service" triggers/email_trigger.py scripts/extract_gmail.py | head -30
```

## Verification

1. **OAuth re-auth done** (pre-requisite) — token has calendar.readonly scope
2. Deploy → scheduler starts calendar_poll
3. `/api/calendar` returns upcoming events
4. Meetings card on landing page shows calendar events alongside meeting transcripts
5. Sandra's 10:30 meeting appears (if it's in Google Calendar)

## Rules

- Do NOT start coding until OAuth re-auth is confirmed
- Check Gmail credential loading pattern — reuse, don't reinvent
- `conn.rollback()` in all except blocks
- Syntax check all modified files before commit
- Never force push
- git pull before starting
- Calendar is READ-ONLY — no creating/modifying events via API
