# BRIEF: LANDING-FIX-3 — Flight Parser + Meeting Alert Routing

## Context
Dashboard audit (Apr 3) found: (1) arrival time wrong in expanded travel cards because `parseFlightInfo()` picks up times from email headers/URLs in the raw e-ticket snippet, and (2) after Brief 2 removes the Oskolkov meeting from Travel, it vanishes entirely — the Meetings card only shows calendar events and detected_meetings, not meeting-tagged alerts.

## Estimated time: ~45min
## Complexity: Medium
## Prerequisites: Brief 2 deployed (meeting excluded from travel_alerts)

---

## Fix 1: Improve parseFlightInfo() — extract itinerary section first

### Problem
Expanded travel card shows `Arrival: 21:00` (same as departure) and `Terminals: T4U → T1 → T1` for LX 529 Nice→Geneva. Actual arrival is 22:00 and terminals are T1→T1.

### Root Cause
The source_snippet is a full Amadeus e-ticket email (~3000 chars) containing URLs, email headers, send timestamps, and the actual itinerary. The naive regex `snippet.match(/\d{2}:\d{2}/g)` picks up times from email headers (e.g., `18:03` send time) before reaching the itinerary times.

The Amadeus itinerary section always sits between a line containing the flight code (e.g., `LX 529`) and the line `Ticket details` or `Other information`. Key data format inside:
```
LX 529
Swiss International Air Lines
Check-in...
03APR, 21:00
Nice, (Cote D Azur)
Terminal : 1-AEROGARE 1
03APR, 22:00
Geneva, (Geneva International)
Terminal : 1
01h 00m (Non stop)
Class : Economy (W)
Seat : 05C
```

### Current State
`outputs/static/app.js` lines 2103-2148, function `parseFlightInfo(snippet)`.

### Implementation
Replace the entire `parseFlightInfo` function with a version that first extracts the itinerary block, then parses within it.

**Find the entire function** (lines 2103-2149, from `// EXPANDABLE-CARDS-1` comment through the closing `}`):

```javascript
// EXPANDABLE-CARDS-1: Parse flight details from deadline source_snippet
function parseFlightInfo(snippet) {
    if (!snippet) return '';
    var lines = [];

    // Flight number (OS 155, LX 1234, etc.)
    var flightMatch = snippet.match(/\b([A-Z]{2}\s?\d{2,4})\b/);
    if (flightMatch) lines.push('Flight: ' + flightMatch[1]);

    // Departure: time + airport/city
    var depMatch = snippet.match(/(\d{2}:\d{2})\s+([\w\s,()]+?)\s+(?:Terminal|T\d)/i);
    if (depMatch) lines.push('Departure: ' + depMatch[1] + ' ' + depMatch[2].trim());

    // Arrival: second time pattern
    var allTimes = snippet.match(/\d{2}:\d{2}/g);
    if (allTimes && allTimes.length >= 2) {
        lines.push('Arrival: ' + allTimes[allTimes.length > 2 ? 2 : 1]);
    }

    // Terminal info
    var terminals = snippet.match(/(?:Terminal\s*:?\s*|T)(\d\w?)/gi);
    if (terminals && terminals.length >= 2) {
        lines.push('Terminals: ' + terminals.join(' → ').replace(/Terminal\s*:?\s*/gi, 'T'));
    }

    // Class
    var classMatch = snippet.match(/Class\s*:?\s*(\w+(?:\s*\(\w\))?)/i);
    if (classMatch) lines.push('Class: ' + classMatch[1]);

    // Seat
    var seatMatch = snippet.match(/Seat\s*:?\s*(\w+)/i);
    if (seatMatch) lines.push('Seat: ' + seatMatch[1]);

    // Booking ref
    var refMatch = snippet.match(/(?:Booking\s*ref|reference|Booking)\s*:?\s*(\w{5,})/i);
    if (refMatch) lines.push('Booking: ' + refMatch[1]);

    // Duration
    var durMatch = snippet.match(/(\d+h\s*\d+m)/);
    if (durMatch) lines.push('Duration: ' + durMatch[1]);

    // Fallback: show raw snippet if parsing failed
    if (lines.length === 0 && snippet.length > 20) {
        return snippet.substring(0, 200).replace(/\s+/g, ' ').trim();
    }

    return lines.join('\n');
}
```

**Replace with:**

```javascript
// EXPANDABLE-CARDS-1 + LANDING-FIX-3: Parse flight details from e-ticket snippet
// First extracts the itinerary block (between flight code and "Ticket details"),
// then parses structured data within it. Avoids false matches from email headers/URLs.
function parseFlightInfo(snippet) {
    if (!snippet) return '';

    // Step 1: Try to extract Amadeus itinerary block (most common e-ticket format)
    // Look for flight code line (e.g. "LX 529\n") up to "Ticket details" or "Other information"
    var itin = snippet;
    var flightMatch = snippet.match(/\b([A-Z]{2}\s?\d{2,4})\s*\n/);
    if (flightMatch) {
        var startIdx = flightMatch.index;
        var endMatch = snippet.substring(startIdx).match(/(?:Ticket details|Other information|Travel Checklist)/i);
        if (endMatch) {
            itin = snippet.substring(startIdx, startIdx + endMatch.index);
        } else {
            itin = snippet.substring(startIdx);
        }
    }

    var lines = [];

    // Flight number
    var fMatch = itin.match(/\b([A-Z]{2}\s?\d{2,4})\b/);
    if (fMatch) lines.push('Flight: ' + fMatch[1]);

    // Departure + Arrival: find all "DDMMM, HH:MM" patterns in the itinerary block
    // Amadeus format: "03APR, 21:00" followed by city on next non-empty line
    var legPattern = /(\d{2}[A-Z]{3}),?\s*(\d{2}:\d{2})\s*\n+\s*(.+?)(?:\s*\n)/g;
    var legs = [];
    var legMatch;
    while ((legMatch = legPattern.exec(itin)) !== null) {
        legs.push({ date: legMatch[1], time: legMatch[2], city: legMatch[3].trim() });
    }
    if (legs.length >= 1) {
        lines.push('Departure: ' + legs[0].time + ' ' + legs[0].city);
    }
    if (legs.length >= 2) {
        lines.push('Arrival: ' + legs[1].time + ' ' + legs[1].city);
    }

    // Terminals: "Terminal : X" or "Terminal : X-TEXT"
    var termMatches = itin.match(/Terminal\s*:\s*(\S+)/gi);
    if (termMatches && termMatches.length >= 2) {
        var terms = termMatches.map(function(t) { return 'T' + t.replace(/Terminal\s*:\s*/i, '').replace(/-.*/, ''); });
        lines.push('Terminals: ' + terms.join(' → '));
    }

    // Duration
    var durMatch = itin.match(/(\d+h\s*\d+m)/);
    if (durMatch) lines.push('Duration: ' + durMatch[1]);

    // Class
    var classMatch = itin.match(/Class\s*:\s*(\w+(?:\s*\(\w\))?)/i);
    if (classMatch) lines.push('Class: ' + classMatch[1]);

    // Seat
    var seatMatch = itin.match(/Seat\s*:\s*(\w+)/i);
    if (seatMatch) lines.push('Seat: ' + seatMatch[1]);

    // Booking ref — search full snippet (ref appears in header before itinerary)
    var refMatch = snippet.match(/(?:Booking\s*ref|Booking ref)\s*:\s*(\w{5,})/i);
    if (refMatch) lines.push('Booking: ' + refMatch[1]);

    // Fallback: show raw snippet if parsing failed entirely
    if (lines.length === 0 && snippet.length > 20) {
        return snippet.substring(0, 200).replace(/\s+/g, ' ').trim();
    }

    return lines.join('\n');
}
```

### Key Constraints
- Booking ref search still uses full `snippet` (it appears before the itinerary block)
- All other parsing uses `itin` (the extracted itinerary section)
- The `legPattern` regex handles Amadeus date format (`03APR, 21:00`) — this is the standard format from CB Travel Services / Swiss / Austrian
- If the itinerary block extraction fails (non-Amadeus format), `itin` falls back to full snippet — same behavior as before but no worse
- Terminal cleanup strips suffixes like `-AEROGARE 1` to just show `T1`

### Verification
Reload dashboard, expand the Nice→Geneva travel card. Expected:
```
Flight: LX 529
Departure: 21:00 Nice, (Cote D Azur)
Arrival: 22:00 Geneva, (Geneva International)
Terminals: T1 → T1
Duration: 01h 00m
Class: Economy (W)
Seat: 05C
Booking: 96KFRX
```

Also expand Geneva→Vienna card. Expected:
```
Flight: OS 152
Departure: 09:35 Geneva, (Geneva International)
Arrival: 11:10 Vienna, (Schwechat Intl)
Terminals: T1 → T3
Duration: 01h 35m
Class: Economy (Y)
Seat: 06C
Booking: 9P85X4
```

---

## Fix 2: Show meeting alerts in Meetings card

### Problem
After Brief 2 excludes meeting-tagged alerts from the Travel card, the Oskolkov Monaco meeting disappears from the landing page entirely. The Meetings card only shows Google Calendar events + detected_meetings — not alert-based meetings.

### Implementation — Backend
In `outputs/dashboard.py`, inside the `get_morning_brief()` function, add a query for meeting alerts. Place it right after the `_travel_deadlines_rows` query inside the connection block (added by Brief 2), before `cur.close()`.

**Find** (inside the connection block, the line added by Brief 2):

```python
            cur.close()
        finally:
            store._put_conn(conn)
```

**Add BEFORE `cur.close()`:**

```python
            # LANDING-FIX-3: Meeting alerts for Meetings card (alerts tagged 'meeting', not calendar)
            try:
                cur.execute("""
                    SELECT id, title, body, tags, created_at
                    FROM alerts
                    WHERE status = 'pending'
                      AND tags ? 'meeting'
                      AND created_at >= NOW() - INTERVAL '48 hours'
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                _meeting_alerts_rows = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Morning brief: meeting alerts query failed: {e}")
                conn.rollback()
                _meeting_alerts_rows = []

```

Then, after the connection block (where Brief 2 placed the `travel_alerts = _travel_alerts_rows` line), add:

```python
        # LANDING-FIX-3: meeting alerts for Meetings card
        meeting_alerts = _meeting_alerts_rows
```

Finally, add `meeting_alerts` to the return dict. **Find:**

```python
            "travel_deadlines": travel_deadlines,
```

**Add after it:**

```python
            "meeting_alerts": meeting_alerts,
```

### Implementation — Frontend
In `outputs/static/app.js`, after the detected meetings loop (around line 932), add meeting alerts rendering.

**Find:**

```javascript
            // MEETINGS-DETECT-1: Add detected meetings from Director messages
            var detectedMeetings = data.detected_meetings || [];
            for (var dmi = 0; dmi < detectedMeetings.length; dmi++) {
                meetingItems.push(renderDetectedMeetingCard(detectedMeetings[dmi]));
            }
```

**Add after:**

```javascript
            // LANDING-FIX-3: Meeting alerts (Baker-generated meeting prep, not in calendar)
            var meetingAlerts = data.meeting_alerts || [];
            for (var mai = 0; mai < meetingAlerts.length; mai++) {
                var ma = meetingAlerts[mai];
                // Skip if title already appears in calendar meetings or detected meetings
                var maTitle = (ma.title || '').toLowerCase().slice(0, 30);
                var maDup = meetingItems.some(function(html) { return html.toLowerCase().indexOf(maTitle) >= 0; });
                if (maDup) continue;
                // Render as compact meeting-style card
                var maHtml = '<div class="card card-compact" style="cursor:pointer;" onclick="_toggleTriageCard(this)"><div class="card-header">' +
                    '<span class="nav-dot blue" style="margin-top:5px;"></span>' +
                    '<span class="card-title">' + esc(ma.title || '') + ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span></span>' +
                    '<span class="card-time">' + esc(fmtRelativeTime(ma.created_at)) + '</span>' +
                    '</div>';
                maHtml += '<div class="triage-detail" style="display:none;">';
                var maBody = (ma.body || '').substring(0, 300);
                if (maBody) maHtml += '<div style="font-size:12px;color:var(--text2);padding:8px 16px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);">' + esc(maBody) + '</div>';
                maHtml += _landingTriageBar(String(ma.id), ma.title || '', maBody, 'meeting', ma.id);
                maHtml += '</div></div>';
                meetingItems.push(maHtml);
            }
```

### Key Constraints
- Meeting alerts deduplicate against existing calendar/detected items (same `.slice(0, 30)` pattern but lowercase-safe — learned from Brief 1)
- Blue dot for alert-sourced meetings (vs green/amber for calendar)
- 48h lookback — meeting prep alerts older than 2 days are stale
- Body truncated to 300 chars for display
- LIMIT 5 on the query

### Verification
After deploy, the Oskolkov Monaco meeting should appear in the Meetings card (not Travel). The Meetings card should show "1" count instead of "No meetings today."

---

## Fix 3: Cache bust

In `outputs/static/index.html`:

**Find:**
```html
<script src="/static/app.js?v=93"></script>
```

**Replace with:**
```html
<script src="/static/app.js?v=94"></script>
```

(If Brief 1 bumped to v93, this goes to v94. Adjust to current version + 1.)

---

## Files Modified
- `outputs/static/app.js` — parseFlightInfo rewrite + meeting alerts rendering
- `outputs/dashboard.py` — meeting_alerts query + return field
- `outputs/static/index.html` — cache bust

## Do NOT Touch
- `models/deadlines.py` — no changes needed
- `outputs/static/style.css` — no CSS changes
- Trigger files, orchestrator files

## Quality Checkpoints
1. LX 529 expanded: Arrival shows 22:00 (not 21:00), Terminals show T1 → T1 (not T4U)
2. OS 152 expanded: Departure 09:35 Geneva, Arrival 11:10 Vienna, Terminals T1 → T3
3. Meetings card shows Oskolkov Monaco meeting (blue dot)
4. Travel card does NOT show Oskolkov Monaco meeting (Brief 2 prerequisite)
5. Meetings count badge shows correct number
6. Python syntax check passes
7. No JS console errors
