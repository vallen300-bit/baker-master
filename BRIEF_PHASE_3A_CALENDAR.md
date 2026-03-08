# Phase 3A — Calendar Trigger + Meeting Auto-Prep

**Author:** Code 300 (architect)
**Date:** 2026-03-08
**Branch:** `feat/phase-3a-calendar`
**Builds on:** COCKPIT-V3 (complete), AGENT-FRAMEWORK-1 (capabilities deployed)

---

## What This Does

Baker proactively prepares meeting briefings. When a meeting is detected within the next 24 hours, Baker:
1. Extracts meeting title, attendees, time, description
2. Searches memory for context on attendees and related matters
3. Runs the Research capability to build a briefing
4. Creates a T2 alert card with the briefing — appears in Fires tab
5. Director sees the briefing before the meeting, not after

This implements **Standing Order #1: "No surprises in meetings."**

---

## Prerequisites (Director must do before code runs)

### 1. Enable Google Calendar API

In Google Cloud Console (same project as Gmail):
1. Go to APIs & Services → Library
2. Search "Google Calendar API"
3. Click Enable

### 2. Re-authenticate with Calendar scope

The existing Gmail token only has `gmail.readonly`. We need to add `calendar` scope (full read/write).

**On local machine (not Render):**
1. Delete existing token: `rm config/gmail_token.json`
2. Baker will run OAuth flow on next start, now requesting both scopes
3. Approve in browser — this creates a new token with both Gmail + Calendar
4. Upload new token to Render: Secret Files → replace `gmail_token.json`

**The `gmail_credentials.json` (OAuth app) stays the same — no changes needed.**

---

## Implementation — 4 Steps

### Step 1: Config + Calendar Client

**Where:** `config/settings.py`

Add Calendar scope to GmailConfig (reuse same OAuth app):

```python
scopes: List[str] = field(default_factory=lambda: [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
])
```

**Where:** `triggers/calendar_trigger.py` (NEW file)

```python
"""
Sentinel Trigger — Google Calendar
Polls for upcoming meetings and triggers auto-prep briefings.
Called by scheduler every 15 minutes.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("sentinel.trigger.calendar")


def _get_calendar_service():
    """Authenticate and return Google Calendar API service object."""
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build
    creds = authenticate()
    return build("calendar", "v3", credentials=creds)


def poll_upcoming_meetings(hours_ahead: int = 24) -> list:
    """
    Poll Google Calendar for meetings in the next N hours.
    Returns list of meeting dicts: {id, title, start, end, attendees, description, location}
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

    return meetings
```

### Step 2: Meeting Prep Logic

**Where:** `triggers/calendar_trigger.py` (same file, new function)

```python
def check_calendar_and_prep():
    """
    Main entry point — called by scheduler every 15 minutes.
    1. Poll upcoming meetings (next 24 hours)
    2. For each meeting not yet prepped → generate briefing
    3. Store briefing as T2 alert card
    """
```

Implementation:
1. Call `poll_upcoming_meetings(hours_ahead=24)`
2. For each meeting, check if already prepped:
   - Query `trigger_watermarks` or `alerts` for a meeting prep marker
   - Use the Google Calendar event `id` as dedup key
   - Store prepped meeting IDs in `trigger_watermarks` table with `type='calendar_prep'` and `source_id=event_id`
3. For each unprepped meeting:
   - Build a prep prompt with meeting context
   - Route through the existing pipeline (scan_chat or capability framework)
   - **OR** simpler approach: use Haiku to generate a structured briefing (same pattern as `_generate_structured_actions`)
4. Create T2 alert with:
   - `title`: "Meeting prep: {meeting_title}"
   - `body`: Generated briefing (attendee context, related matters, key points)
   - `tier`: 2
   - `tags`: `["meeting"]`
   - `matter_slug`: auto-assigned via existing `_match_matter_slug()`
   - `structured_actions`: Baker recommends actions (review docs, draft talking points, etc.)

**Briefing generation approach — use Haiku (fast + cheap):**

```python
MEETING_PREP_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

Generate a meeting briefing. Include:
1. WHO: Each attendee — role, relationship to Director, last interaction, key context
2. WHAT: Meeting purpose (inferred from title + description + attendee context)
3. CONTEXT: Related matters, recent activity, pending items with attendees
4. WATCH: Key points to raise, potential risks, decisions needed
5. ACTIONS: What Director should prepare, review, or bring

Be specific — reference real names, projects, dates from the context provided.
"""
```

For attendee context, search Baker's memory:
- For each attendee name: query `contacts` + `vip_contacts` for profile
- Query `email_messages` for recent emails from/to each attendee (last 30 days)
- Query `whatsapp_messages` for recent messages
- Query `meeting_transcripts` for past meetings with this person
- Query `alerts` for related active matters

Pass all this context to Haiku along with the meeting details. Haiku generates the briefing.

**CRITICAL: The briefing generation does NOT route through /api/scan or the full agentic pipeline.** This is a background job, not an interactive session. Use a direct Haiku call with assembled context, same pattern as `_generate_structured_actions()` in pipeline.py.

### Step 3: Scheduler Registration

**Where:** `triggers/embedded_scheduler.py`

```python
# Calendar polling + meeting prep — every 15 minutes
from triggers.calendar_trigger import check_calendar_and_prep
scheduler.add_job(
    check_calendar_and_prep,
    IntervalTrigger(minutes=15),
    id="calendar_prep", name="Calendar meeting prep",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: calendar_prep (every 15 minutes)")
```

### Step 4: Dashboard — Meeting Prep View Enhancement

**Where:** `outputs/dashboard.py`, `outputs/static/app.js`

Meeting prep alerts show up automatically in Fires tab (they're T2 alerts). But add a small enhancement:

**New endpoint: `GET /api/calendar/upcoming`**

Returns upcoming meetings (next 48 hours) with prep status. For the Morning Brief to show "3 meetings today, 2 prepped, 1 pending."

```python
@app.get("/api/calendar/upcoming", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_upcoming_meetings(hours: int = Query(48, ge=1, le=168)):
```

Response:
```json
{
  "meetings": [
    {
      "title": "Hagenauer review with Ofenheimer",
      "start": "2026-03-09T10:00:00+01:00",
      "attendees": ["Alric Ofenheimer", "Thomas Leitner"],
      "prepped": true,
      "alert_id": 456
    }
  ],
  "count": 3,
  "prepped_count": 2
}
```

**Morning Brief integration:** In `GET /api/dashboard/morning-brief`, add a `meetings_today` section that shows today's meetings with prep status. Frontend renders this in the Morning Brief view.

---

## Dedup Strategy

The calendar trigger runs every 15 minutes. It must not create duplicate briefings.

**Approach:** Use `trigger_watermarks` table (already exists for email/WhatsApp dedup).

```python
# Check if meeting already prepped
watermark = store.get_watermark('calendar_prep', event_id)
if watermark:
    continue  # Already prepped

# After creating the alert:
store.set_watermark('calendar_prep', event_id, {'prepped_at': now.isoformat()})
```

**Verify** `get_watermark` and `set_watermark` methods exist on store, or use the trigger_watermarks table directly.

---

## Context Assembly for Briefing

For each meeting, assemble context before calling Haiku:

```python
def _assemble_meeting_context(meeting: dict, store) -> str:
    """Gather all relevant context for a meeting briefing."""
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
        name = att.get('name', att.get('email', ''))
        if not name:
            continue
        parts.append(f"\n--- Attendee: {name} ({att.get('email', '')}) ---")

        # Check VIP contacts + contacts
        # (query DB for name match — reuse existing contact lookup)

        # Recent emails (last 30 days)
        # (query email_messages WHERE sender_name/sender_email ILIKE name)

        # Recent WhatsApp (last 30 days)
        # (query whatsapp_messages WHERE sender_name ILIKE name)

        # Past meetings with this person
        # (query meeting_transcripts WHERE participants ILIKE name)

    # 3. Related matters
    # (query alerts WHERE title/body mentions any attendee name)

    return "\n".join(parts)
```

Limit total context to ~4000 tokens (Haiku context window is generous, but keep focused).

---

## Files Summary

| File | Type | What |
|------|------|------|
| `config/settings.py` | Modify | Add `calendar` scope to GmailConfig scopes |
| `triggers/calendar_trigger.py` | **New** | Calendar polling + meeting prep generation |
| `triggers/embedded_scheduler.py` | Modify | Register calendar_prep job |
| `outputs/dashboard.py` | Modify | `GET /api/calendar/upcoming` endpoint |
| `outputs/static/app.js` | Modify | Morning Brief meetings section |

---

## CRITICAL Rules

1. **Briefing uses direct Haiku call, NOT /api/scan.** This is a background job, not interactive. No agentic RAG loop. Assemble context manually, call Haiku, store result. Same pattern as `_generate_structured_actions()`.

2. **Dedup on Google Calendar event ID.** Never create two briefings for the same meeting. Check trigger_watermarks before generating.

3. **Skip all-day events.** Only prep timed meetings (with `dateTime`, not just `date`).

4. **Graceful failure.** If Calendar API is unreachable or token expired, log warning and skip. Don't crash the scheduler. Other jobs (email, ClickUp, etc.) must continue.

5. **Don't expose calendar credentials.** The `calendar` scope reuses the existing Gmail OAuth. No new secrets needed — just scope addition + token refresh.

6. **Meeting prep alerts are T2.** Not T1 (fires). They appear in Fires tab but don't trigger emergency notifications.

---

## Commit Plan

```
Step 1: feat: Phase 3A step 1 -- calendar trigger + config
Step 2: feat: Phase 3A step 2 -- meeting prep generation + scheduler
Step 3: feat: Phase 3A step 3 -- upcoming meetings endpoint + morning brief
```

3 commits on branch `feat/phase-3a-calendar`. Push to origin when complete. Code 300 will review before merge.

---

## Director Action Required

Before Brisen can test this:
1. Enable Google Calendar API in Google Cloud Console
2. Delete `config/gmail_token.json` locally
3. Run Baker locally → OAuth flow opens browser → approve both Gmail + Calendar scopes
4. Upload new `gmail_token.json` to Render Secret Files

Code 300 will guide through this when ready.
