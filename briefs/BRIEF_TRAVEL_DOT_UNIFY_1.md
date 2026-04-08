# BRIEF: TRAVEL-DOT-UNIFY-1 — Unified Travel Card Color System + Status Triage

## Context
Travel card on the landing page has 3 data sources (trips, deadlines, alerts) with 3 independent color systems. Director changed flight status but dots didn't update. Deadline-sourced flights (e.g., OS 155 from email extraction) use hardcoded amber/green and ignore the trip status system entirely. Director wants one consistent color system with manual triage control.

## Estimated time: ~1.5h
## Complexity: Medium
## Prerequisites: None

---

## Rules (Director-specified, Apr 8 2026)

1. **All flights start as `planned` (blue dot)** — regardless of data source
2. **Director manually changes status** via triage pills: Confirm (green), Complete (yellow), Discard (red)
3. **Flights disappear** the calendar day after the flight date
4. **No automatic status changes** — Baker never auto-promotes or auto-completes

## Color Legend
| Status | Dot Color | Meaning |
|--------|-----------|---------|
| `planned` | Blue | Sourced, not yet confirmed by Director |
| `confirmed` | Green | Director confirmed |
| `completed` | Amber/Yellow | Director marked as done (still visible until next calendar day) |
| `discarded` | Red | Director discarded |

---

## Feature 1: Unify Deadline-Sourced Flight Dots

### Problem
Line 1081 of `app.js` hardcodes deadline-sourced flights to `_tdDone ? 'green' : 'amber'`. These flights ignore trip status entirely.

### Current State
```javascript
// app.js line 1081
'<span class="nav-dot ' + (_tdDone ? 'green' : 'amber') + '" ...'
```
Travel deadlines always show amber (upcoming) or green (past). No way to change via triage.

### Implementation

**File:** `outputs/static/app.js`

**Replace lines 1073-1089** (the travel deadline rendering block). Find this code:

```javascript
                var _tdDone = false;
                try {
                    if (td.due_date) {
                        var _tdDep = new Date(td.due_date);
                        _tdDone = new Date() > new Date(_tdDep.getTime() + 2 * 3600000);
                    }
                } catch(e) {}
                var _travelHtml = '<div class="card card-compact' + (_tdDone ? ' travel-done' : '') + '" style="cursor:pointer;" onclick="_toggleTriageCard(this)"><div class="card-header">' +
                    '<span class="nav-dot ' + (_tdDone ? 'green' : 'amber') + '" style="margin-top:5px;"></span>' +
                    '<span class="card-title">' + esc(td.description) + ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span></span>' +
                    '<span class="card-time" style="font-weight:600;">' + esc(dueLabel) + '</span>' +
                    '</div>';
                _travelHtml += '<div class="triage-detail" style="display:none;">';
                if (flightInfo) _travelHtml += '<div style="font-size:12px;color:var(--text2);padding:8px 18px 10px;border-top:1px solid var(--border-light);line-height:1.6;white-space:pre-wrap;">' + esc(flightInfo) + '</div>';
                _travelHtml += _landingTriageBar(String(td.id), td.description, flightInfo, 'travel', td.id);
                _travelHtml += '</div></div>';
```

**Replace with:**

```javascript
                // TRAVEL-DOT-UNIFY-1: All flights start blue (planned). Director controls status via triage.
                // Check if this deadline has an associated trip (linked_trip_id in notes or matching destination+date)
                var _tdTripId = td.linked_trip_id || null;
                var _tdStatus = td.trip_status || 'planned';
                var _tdDotColor = _tripStatusColors[_tdStatus] || 'var(--blue, #0a6fdb)';
                // Disappear rule: next calendar day after flight date
                var _tdGone = false;
                try {
                    if (td.due_date) {
                        var _tdDueDate = new Date(td.due_date.slice(0, 10) + 'T23:59:59');
                        _tdGone = new Date() > _tdDueDate;
                    }
                } catch(e) {}
                if (_tdGone && _tdStatus !== 'confirmed' && _tdStatus !== 'planned') continue; // skip completed/discarded past flights
                var _travelHtml = '<div class="card card-compact" style="cursor:pointer;" data-deadline-id="' + td.id + '" data-trip-id="' + (_tdTripId || '') + '" onclick="_toggleTriageCard(this)"><div class="card-header">' +
                    '<span class="nav-dot travel-status-dot" style="margin-top:5px;background:' + _tdDotColor + ';"></span>' +
                    '<span class="card-title">' + esc(td.description) + ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span></span>' +
                    '<span class="card-time" style="font-weight:600;">' + esc(dueLabel) + '</span>' +
                    '</div>';
                _travelHtml += '<div class="triage-detail" style="display:none;">';
                if (flightInfo) _travelHtml += '<div style="font-size:12px;color:var(--text2);padding:8px 18px 10px;border-top:1px solid var(--border-light);line-height:1.6;white-space:pre-wrap;">' + esc(flightInfo) + '</div>';
                _travelHtml += _travelTriageBar(td.id, _tdTripId, td.description, flightInfo, _tdStatus);
                _travelHtml += '</div></div>';
```

### Key Constraints
- Use inline `style="background:..."` for dot color (same pattern as trip cards at line 1025) — NOT CSS class names like `'blue'`, `'amber'`. This ensures both trip cards and deadline cards use the same color values from `_tripStatusColors`.
- `_tdGone` logic: disappear the next calendar day (midnight), not 2h after departure.
- Keep `data-deadline-id` and `data-trip-id` attributes for triage JS to use.

---

## Feature 2: Unify Trip Card Dots (Landing Page)

### Problem
Trip cards at line 1024 already use `_tripStatusColors` — mostly correct. But newly auto-created trips default to `status = 'planned'` in the DB schema, which is correct per Director's rules. No changes needed to the dot logic.

### Implementation
**No code change needed** for trip card dots — they already use `_tripStatusColors[trip.status]` at line 1009/1025. Just verify the default status in the DB schema is `'planned'`.

**One fix needed:** Trip cards on the landing page (line 1024) have no triage. Add a triage bar so Director can change status without opening the full Trip View.

**Replace line 1023-1031:**

```javascript
                allTravel.push(
                    '<div class="card card-compact" onclick="showTripView(' + trip.id + ')" style="cursor:pointer;"><div class="card-header">' +
                    '<span class="nav-dot" style="margin-top:5px;background:' + statusColor + ';"></span>' +
                    '<span class="card-title">' + esc(trip.event_name || trip.destination || 'Trip') +
                    (catLabel ? ' <span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;margin-left:6px;">' + esc(catLabel) + '</span>' : '') +
                    ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9656;</span></span>' +
                    '<span class="card-time">' + esc(dateDisplay) + '</span>' +
                    '</div></div>'
                );
```

**Replace with:**

```javascript
                // TRAVEL-DOT-UNIFY-1: Trip cards with triage bar for status change
                var _tripGone = false;
                try {
                    var _tripEndDate = new Date((trip.end_date || trip.start_date) + 'T23:59:59');
                    _tripGone = new Date() > _tripEndDate;
                } catch(e) {}
                if (_tripGone && (trip.status === 'completed' || trip.status === 'discarded')) continue;
                allTravel.push(
                    '<div class="card card-compact" style="cursor:pointer;" data-trip-id="' + trip.id + '" onclick="_toggleTriageCard(this)"><div class="card-header">' +
                    '<span class="nav-dot travel-status-dot" style="margin-top:5px;background:' + statusColor + ';"></span>' +
                    '<span class="card-title">' + esc(trip.event_name || trip.destination || 'Trip') +
                    (catLabel ? ' <span style="font-size:9px;font-weight:600;color:var(--text3);background:var(--bg2);padding:1px 4px;border-radius:3px;margin-left:6px;">' + esc(catLabel) + '</span>' : '') +
                    ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span></span>' +
                    '<span class="card-time">' + esc(dateDisplay) + '</span>' +
                    '</div>' +
                    '<div class="triage-detail" style="display:none;">' +
                    _travelTriageBar(null, trip.id, trip.event_name || trip.destination || 'Trip', '', trip.status) +
                    '</div></div>'
                );
```

### Key Constraints
- Changed chevron from `&#9656;` (right arrow = "click to open trip view") to `&#9662;` (down arrow = "expandable triage"). Director now triages from landing page directly.
- Trip detail view is still accessible via a "View Details" button in the triage bar.
- `_tripGone` uses end_date midnight — disappears next calendar day.

---

## Feature 3: Travel Triage Bar with Status Buttons

### Problem
Current `_landingTriageBar()` for `cardType === 'travel'` has no status-change buttons — only Dismiss, Draft Email, etc.

### Implementation

**File:** `outputs/static/app.js`

**Add new function** after `_landingTriageBar()` (after line ~2920):

```javascript
// TRAVEL-DOT-UNIFY-1: Travel-specific triage bar with status buttons
function _travelTriageBar(deadlineId, tripId, title, flightInfo, currentStatus) {
    var _t = escAttr(title);
    var _c = escAttr((flightInfo || '').substring(0, 200));
    var html = '<div class="triage-actions" style="display:flex;flex-wrap:wrap;gap:6px;padding:8px 16px 12px;">';

    // Status buttons — always show all 4, highlight current
    var statuses = [
        { key: 'planned', label: 'Planned', color: 'var(--blue, #0a6fdb)' },
        { key: 'confirmed', label: 'Confirmed', color: 'var(--green, #22c55e)' },
        { key: 'completed', label: 'Completed', color: 'var(--amber, #f59e0b)' },
        { key: 'discarded', label: 'Discard', color: 'var(--red, #ef4444)' }
    ];
    for (var si = 0; si < statuses.length; si++) {
        var s = statuses[si];
        var active = s.key === currentStatus;
        html += '<button class="triage-pill" onclick="event.stopPropagation();_travelSetStatus(this,' +
            (tripId || 'null') + ',' + (deadlineId || 'null') + ',\'' + s.key + '\')" style="' +
            (active ? 'background:' + s.color + ';color:#fff;border-color:' + s.color + ';' : '') +
            '">' + s.label + '</button>';
    }

    // Utility buttons
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Draft an email regarding: \\x22' + _t + '\\x22. Context: ' + _c + '\')">✉ Draft Email</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Draft a WhatsApp message regarding: \\x22' + _t + '\\x22. Context: ' + _c + '\')">💬 Draft WA</button>';
    if (tripId) {
        html += '<button class="triage-pill" onclick="event.stopPropagation();showTripView(' + tripId + ')">📋 View Details</button>';
    }
    html += '<button class="triage-pill" onclick="event.stopPropagation();_landingDismiss(\'travel\',' + (deadlineId || tripId) + ',this)">✕ Dismiss</button>';

    html += '</div>';
    return html;
}

// TRAVEL-DOT-UNIFY-1: Set travel status — update trip (create if needed), live-update dot
async function _travelSetStatus(btn, tripId, deadlineId, newStatus) {
    var card = btn.closest('.card');
    var dot = card ? card.querySelector('.travel-status-dot') : null;

    // If no trip exists yet, create one from the deadline
    if (!tripId && deadlineId) {
        try {
            var resp = await bakerFetch('/api/travel/promote-deadline/' + deadlineId, { method: 'POST' });
            var result = await resp.json();
            tripId = result.trip_id || result.id;
            if (card) card.dataset.tripId = tripId;
        } catch(e) {
            _showToast('Failed to create trip');
            return;
        }
    }

    if (!tripId) { _showToast('No trip to update'); return; }

    // Update trip status
    try {
        await bakerFetch('/api/trips/' + tripId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });

        // Live-update dot color
        var newColor = _tripStatusColors[newStatus] || 'var(--text3)';
        if (dot) dot.style.background = newColor;

        // Update button highlights
        var pills = btn.parentElement.querySelectorAll('.triage-pill');
        var statusKeys = ['planned', 'confirmed', 'completed', 'discarded'];
        for (var pi = 0; pi < Math.min(pills.length, 4); pi++) {
            var sk = statusKeys[pi];
            var sc = _tripStatusColors[sk];
            if (sk === newStatus) {
                pills[pi].style.background = sc;
                pills[pi].style.color = '#fff';
                pills[pi].style.borderColor = sc;
            } else {
                pills[pi].style.background = '';
                pills[pi].style.color = '';
                pills[pi].style.borderColor = '';
            }
        }

        _showToast('Status → ' + newStatus.charAt(0).toUpperCase() + newStatus.slice(1));
    } catch(e) {
        _showToast('Failed to update status');
    }
}
```

### Key Constraints
- `_travelSetStatus` is async — uses `bakerFetch` which already handles auth headers.
- Live-updates the dot AND the button highlights without page reload.
- If a deadline-sourced flight has no trip yet, calls `POST /api/travel/promote-deadline/{deadline_id}` to create one (Feature 4).
- First 4 buttons are always status buttons. Utility buttons follow.

---

## Feature 4: Promote Deadline to Trip API

### Problem
Deadline-sourced flights (like OS 155) exist only in the `deadlines` table, not `trips`. When Director triages them, we need a trip record to store the status.

### Implementation

**File:** `outputs/dashboard.py`

**Add new endpoint** (after the existing `/api/trips` endpoints, around line 2663):

```python
@app.post("/api/travel/promote-deadline/{deadline_id}", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def promote_deadline_to_trip(deadline_id: int):
    """Create a trip from a travel deadline. Returns the new trip with id."""
    store = _get_store()
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, description, due_date, source_snippet
            FROM deadlines WHERE id = %s LIMIT 1
        """, (deadline_id,))
        dl = cur.fetchone()
        cur.close()
        if not dl:
            raise HTTPException(status_code=404, detail="Deadline not found")

        # Parse destination from description (e.g., "Return from Vienna to Geneva (Flight OS 155)")
        desc = dl["description"] or ""
        destination = ""
        origin = ""
        import re
        to_match = re.search(r"(?:to|nach|→)\s+([A-Za-z\s]+?)(?:\s*\(|$)", desc)
        from_match = re.search(r"(?:from|von|Return from)\s+([A-Za-z\s]+?)(?:\s+to|\s*\(|$)", desc, re.IGNORECASE)
        if to_match:
            destination = to_match.group(1).strip()
        if from_match:
            origin = from_match.group(1).strip()

        flight_date = None
        if dl.get("due_date"):
            flight_date = dl["due_date"]
            if hasattr(flight_date, "date"):
                flight_date = flight_date.date()
            flight_date = str(flight_date)

        trip = store.upsert_trip(
            destination=destination or "Unknown",
            origin=origin or "",
            start_date=flight_date,
            end_date=flight_date,
            event_name=desc,
            category="meeting",
            status="planned",
        )
        return _serialize(trip)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Promote deadline to trip failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        put_conn(conn)
```

**Also verify:** `grep -n "promote-deadline" dashboard.py` — must return 0 matches before adding (no duplicate endpoints).

### Key Constraints
- Uses `upsert_trip()` which checks for existing trip by destination+date — won't create duplicates.
- Default status is `planned` (blue dot) per Director's rules.
- `conn.rollback()` in except block (Lesson #7).
- LIMIT 1 on the SELECT (Lesson: unbounded queries).

---

## Feature 5: Enrich Morning Brief with Deadline-Trip Linking

### Problem
The morning brief returns `travel_deadlines` without any trip status info. The frontend needs `trip_status` and `linked_trip_id` to render the correct dot color.

### Implementation

**File:** `outputs/dashboard.py`

Find the travel deadlines query (around line 2290). After fetching `_travel_deadlines_rows`, add a post-processing step to look up associated trips:

```python
        # TRAVEL-DOT-UNIFY-1: Enrich travel deadlines with linked trip status
        try:
            if _travel_deadlines_rows and active_trips:
                for tdl in _travel_deadlines_rows:
                    tdl_desc = (tdl.get("description") or "").lower()
                    tdl_date = str(tdl.get("due_date", ""))[:10] if tdl.get("due_date") else ""
                    for atrip in active_trips:
                        trip_dest = (atrip.get("destination") or "").lower()
                        trip_date = str(atrip.get("start_date", ""))
                        if trip_dest and trip_dest in tdl_desc and trip_date == tdl_date:
                            tdl["linked_trip_id"] = atrip.get("id")
                            tdl["trip_status"] = atrip.get("status", "planned")
                            break
                    else:
                        tdl["trip_status"] = "planned"  # Default: blue dot
        except Exception:
            pass
```

**Insert this** after line ~2477 (`travel_deadlines = _travel_deadlines_rows`) and BEFORE the `return` statement. It must run after both `_travel_deadlines_rows` and `active_trips` are populated.

### Key Constraints
- Matching is by destination name + date (fuzzy). If no match, defaults to `planned` (blue).
- Non-fatal try/except — if matching fails, all deadlines show blue (safe default).
- Does NOT modify the deadlines table — enrichment is in-memory for the API response only.

---

## Feature 6: Travel Alerts — Default Blue Dot

### Problem
Travel alerts at line 1102 hardcode `taDot = 'blue'` — this happens to be correct per Director's rules (blue = planned). No change needed, but document it.

### Implementation
**No code change.** Alert-sourced travel items already show blue. If they need triage in the future, the same pattern from Feature 3 can be applied.

---

## Feature 7: Disappear Logic — Next Calendar Day

### Problem
Current disappear logic uses 2h after departure (line 1077). Director wants: disappear the next calendar day.

### Implementation
Already handled in Feature 1 (`_tdGone`) and Feature 2 (`_tripGone`). Both use:
```javascript
var endDate = new Date(dateStr + 'T23:59:59');
var gone = new Date() > endDate;
```
This means flights disappear at midnight after their date. The old 2h logic at line 1077 is replaced.

---

## Files Modified
- `outputs/static/app.js` — Travel card rendering (Features 1-3), new `_travelTriageBar()` + `_travelSetStatus()` functions, disappear logic. **Bump cache: `?v=N+1`**
- `outputs/dashboard.py` — New `POST /api/travel/promote-deadline/{deadline_id}` endpoint (Feature 4), deadline-trip enrichment (Feature 5)

## Do NOT Touch
- `memory/store_back.py` — Schema is fine, `upsert_trip()` already exists
- `triggers/` — No trigger changes
- `outputs/static/style.css` — No new styles needed (reuses `.triage-pill`, `.nav-dot`)
- `outputs/static/index.html` — No HTML changes (travel card container already exists)

## Quality Checkpoints
1. All flights show **blue dot** by default on first load
2. Clicking a flight expands triage with 4 status buttons (Planned highlighted)
3. Clicking "Confirmed" → dot turns green immediately (no reload)
4. Clicking "Completed" → dot turns amber immediately
5. Clicking "Discard" → dot turns red immediately
6. Clicking "Planned" → dot returns to blue
7. Deadline-sourced flights (OS 155) work the same as trip-sourced flights (Emirates)
8. Flights from yesterday or earlier do NOT appear (unless still planned/confirmed)
9. Trip detail view still accessible via "View Details" button in triage
10. Cache busted: CSS/JS `?v=N+1` in index.html
11. No console errors on landing page load
12. Verify `POST /api/travel/promote-deadline/{id}` creates a trip and returns trip_id

## Verification SQL
```sql
-- Check all active trips have valid status
SELECT id, event_name, status, start_date FROM trips
WHERE status IN ('planned', 'confirmed') ORDER BY start_date LIMIT 10;

-- Verify no orphaned travel deadlines without trip linkage (informational)
SELECT d.id, d.description, d.due_date, t.id as trip_id, t.status as trip_status
FROM deadlines d
LEFT JOIN trips t ON t.destination ILIKE '%' || SPLIT_PART(d.description, ' ', -1) || '%'
  AND t.start_date = d.due_date::date
WHERE d.status = 'active'
  AND (d.description ILIKE '%flight%' OR d.description ILIKE '%depart%')
LIMIT 10;
```
