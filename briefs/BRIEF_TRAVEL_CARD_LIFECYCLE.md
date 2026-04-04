# BRIEF: TRAVEL_CARD_LIFECYCLE — Yellow "done" state 2h after departure, dismiss next calendar day

## Context
Travel cards on the landing page currently show all day with time-based dot colors (gray=upcoming, amber=in progress, green=past), but they disappear abruptly at UTC midnight. The Director's Geneva-Nice flight disappeared before embarkation, likely due to UTC-vs-local timezone mismatch in `poll_todays_meetings()`.

Director request: "When the time for departure passed two hours after the departure, this item turns yellow, like it's done. And is dismissed next calendar day."

## Estimated time: ~30min
## Complexity: Low
## Prerequisites: None
## Parallel-safe: Yes — touches frontend JS/CSS + one backend function

---

## Part 1: Fix UTC timezone bug in poll_todays_meetings()

### Problem
`poll_todays_meetings()` uses UTC midnight as day boundaries. The Director is in CET/CEST (UTC+1/+2). A flight at 08:00 Geneva time on April 3 = 06:00 UTC April 3 — this works fine. But edge cases around midnight (late flights, early morning departures) could fall outside the UTC day window. More importantly, "today" as perceived by the Director is CET, not UTC.

### Current State (triggers/calendar_trigger.py, lines 97-101)
```python
    now = datetime.now(timezone.utc)
    # Start of today (UTC midnight)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(hours=24)
```

### Implementation

**File: `triggers/calendar_trigger.py`** — lines 97-101

Replace:
```python
    now = datetime.now(timezone.utc)
    # Start of today (UTC midnight)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(hours=24)
```

With:
```python
    from zoneinfo import ZoneInfo
    tz_local = ZoneInfo('Europe/Zurich')
    now_local = datetime.now(tz_local)
    # Start/end of today in Director's timezone
    start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(hours=24)
```

### What changed:
Day boundaries are now CET/CEST midnight, not UTC midnight. A flight at 23:30 Geneva time stays visible until midnight Geneva time (not 22:00 UTC).

### Key Constraints
- `ZoneInfo` is stdlib Python 3.9+. Baker runs Python 3.11 — no new dependency.
- Google Calendar API accepts timezone-aware datetimes in `timeMin`/`timeMax` — it converts internally.
- Hardcoding `Europe/Zurich` is fine — the Director lives there. If multi-timezone support is ever needed, make it a config setting later.

---

## Part 2: Yellow "done" card state 2h after departure

### Problem
Travel cards currently use dot colors (amber/green) but the card background stays the same regardless of whether the flight is past. The Director wants a clear visual signal: the entire card turns yellow/amber when the departure was 2+ hours ago, signaling "this is done but kept for reference."

### Current State (app.js, lines 1994-2003)
The dot color logic already exists:
```javascript
    } else {
        // Time-based dot: green=past, amber=in progress, gray=upcoming
        var now = new Date();
        try {
            var evStart = new Date(t.start);
            var evEnd = t.end ? new Date(t.end) : null;
            if (evEnd && now > evEnd) dotClass = 'green';
            else if (now >= evStart) dotClass = 'amber';
        } catch(e) {}
    }
```

### Implementation

**File: `outputs/static/app.js`** — in `renderTravelCard()` function

**Step A:** After the existing dot color block (after line 2003), add a card-level "done" flag:

Find:
```javascript
    }

    // Route display
```

This is at line 2003-2005. Replace with:
```javascript
    }

    // TRAVEL-LIFECYCLE-1: Card-level "done" state — 2h after departure
    var _travelDone = false;
    try {
        var _depTime = new Date(t.start);
        if (new Date() > new Date(_depTime.getTime() + 2 * 3600000)) _travelDone = true;
    } catch(e) {}

    // Route display
```

**Step B:** Apply the "done" class to the card element. Find the card HTML construction (line 2045):

Find:
```javascript
    return '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
```

Replace with:
```javascript
    return '<div class="card card-compact' + (_travelDone ? ' travel-done' : '') + '"' + clickAttr + '><div class="card-header">' +
```

**File: `outputs/static/style.css`** — add after the `.card-compact` rules (after line 746):

Add:
```css
.card.travel-done { background: rgba(212, 165, 53, 0.10); border-color: rgba(212, 165, 53, 0.25); opacity: 0.75; }
.card.travel-done .card-title { color: var(--text2); }
.card.travel-done .card-time { color: var(--text3); }
```

### What changed:
1. New `_travelDone` boolean: true when `now > departure + 2 hours`
2. Card gets `travel-done` CSS class: light amber/yellow background, slightly reduced opacity
3. Title and time text get muted colors — the card is visually "dimmed but present"

### Key Constraints
- The check uses `t.start` (departure time), not `t.end` (arrival). "2 hours after departure" is the trigger, per Director's request.
- The `travel-done` style must NOT hide the card — it stays visible until next calendar day.
- The dot color logic (lines 1994-2003) is unchanged. The dot will show green (past) while the card background is yellow — this is intentional double signaling.

---

## Part 3: Also apply "done" state to travel deadline cards

### Problem
Travel deadlines (from the `deadlines` table, rendered in the landing grid loop at lines 807-845) also appear as travel cards. They should get the same yellow treatment.

### Current State (app.js, lines 835-843)
Travel deadline cards are built inline with hardcoded HTML, not via `renderTravelCard()`. They use a fixed amber dot.

### Implementation

**File: `outputs/static/app.js`** — lines 835-843

Find:
```javascript
                var _travelHtml = '<div class="card card-compact" style="cursor:pointer;" onclick="_toggleTriageCard(this)"><div class="card-header">' +
                    '<span class="nav-dot amber" style="margin-top:5px;"></span>' +
```

Replace with:
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
```

### What changed:
Travel deadline cards also turn yellow 2h after their due date, and the dot changes from amber to green.

---

## Part 4: Cache bust

**File: `outputs/static/index.html`**

Check current values and bump both by 1:
- `style.css?v=N` → `style.css?v=N+1`
- `app.js?v=N` → `app.js?v=N+1`

(No CSS change for `app.js` logic, but both are modified in this brief.)

---

## Files Modified
- `triggers/calendar_trigger.py` — timezone fix (UTC → Europe/Zurich)
- `outputs/static/app.js` — travel-done flag in `renderTravelCard()` + travel deadline cards
- `outputs/static/style.css` — `.travel-done` card styling
- `outputs/static/index.html` — cache bust

## Do NOT Touch
- `outputs/dashboard.py` — no backend API changes
- Trip cards (from `trips` table) — they have their own status system (`trip_status`), not time-based
- Meeting cards — only travel cards get the yellow treatment

## Quality Checkpoints
1. **Upcoming flight**: Card shows normal (no yellow), gray or amber dot
2. **Flight departed <2h ago**: Card shows normal, amber dot (in progress)
3. **Flight departed >2h ago**: Card turns yellow background, slightly dimmed, green dot
4. **Travel deadline >2h past due**: Same yellow treatment
5. **Next calendar day**: Card disappears entirely (existing behavior, now based on CET midnight)
6. **Late evening flight (23:00 CET)**: Card stays visible until CET midnight, not UTC midnight
7. **Trip-linked travel**: Trip cards are NOT affected (they use `trip_status`, not time-based)
8. **Syntax check**: `python3 -c "import py_compile; py_compile.compile('triggers/calendar_trigger.py', doraise=True)"`

## Cost Impact
- Zero — one stdlib import (`zoneinfo`), no API calls, no model changes

## Rollback
Revert calendar_trigger.py timezone change, remove `_travelDone` logic in app.js, remove `.travel-done` CSS. Cards revert to current behavior.
