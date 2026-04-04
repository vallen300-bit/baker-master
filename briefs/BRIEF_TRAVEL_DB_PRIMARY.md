# BRIEF: TRAVEL_DB_PRIMARY — Travel cards from Baker's own DB, not Google Calendar

## Context
Travel cards on the landing page depend on Google Calendar as primary source (`poll_todays_meetings()`). When the OAuth token expires (which happened April 1-3), travel cards vanish silently. The Director's Nice-Geneva flight (LX 529, today April 3) didn't show despite Baker having the data in both the `deadlines` table (id 1328) and `alerts` table (id 14871).

The Director doesn't use Google Calendar directly — Baker creates flight data from booking emails. The calendar dependency is unnecessary and fragile.

Director request: "I thought Baker was handling it and putting the dates in a calendar himself. Calendar is mostly for him."

## Estimated time: ~45min
## Complexity: Low-Medium
## Prerequisites: None
## Parallel-safe: Yes (backend + frontend, no concurrent brief conflicts)

---

## Part 1: Fix travel_deadlines SQL — same-day flights excluded after midnight UTC

### Problem
The `travel_deadlines` query uses `due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'`. Today's flight (deadline 1328) has `due_date = 2026-04-03 00:00:00+00:00`. Once `NOW()` passes midnight UTC (~02:00 CET), the lower bound exceeds the deadline's timestamp. The flight disappears.

### Current State (dashboard.py, lines 2432-2439)
```python
            cur.execute("""
                SELECT id, description, due_date, priority, source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
                  AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                       OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%')
                ORDER BY due_date ASC LIMIT 5
            """)
```

### Implementation

**File: `outputs/dashboard.py`** — lines 2432-2439

Replace:
```python
            cur.execute("""
                SELECT id, description, due_date, priority, source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
                  AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                       OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%')
                ORDER BY due_date ASC LIMIT 5
            """)
```

With:
```python
            cur.execute("""
                SELECT id, description, due_date, priority, source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND due_date >= CURRENT_DATE
                  AND due_date < CURRENT_DATE + INTERVAL '4 days'
                  AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                       OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
                       OR description ILIKE '%%train%%' OR description ILIKE '%%depart%%')
                ORDER BY due_date ASC LIMIT 10
            """)
```

### What changed:
1. `BETWEEN NOW() AND NOW() + 3 days` → `>= CURRENT_DATE AND < CURRENT_DATE + 4 days` — uses date boundary not timestamp, so today's flights always show regardless of time-of-day
2. Added `'%%train%%'` and `'%%depart%%'` to match more travel patterns
3. LIMIT 5 → LIMIT 10 — room for multi-leg journeys (e.g., GVA→VIE + VIE→GVA)

---

## Part 2: Render travel_alerts in the frontend (currently dead data)

### Problem
The backend sends `travel_alerts` (alerts with `travel` tag or `flight` in title) — the Director's LX 529 flight exists as alert #14871. But the frontend **never reads `data.travel_alerts`**. The field is completely ignored. This is the most reliable fallback since Baker generates these alerts from email processing.

### Current State (app.js, lines 761-858)
The travel grid builder uses three sources:
1. `data.trips` — trip objects (line 768)
2. `data.travel_today` — calendar events (line 797) — **broken when token expires**
3. `data.travel_deadlines` — deadline-based (line 808) — **broken by NOW() bug**

`data.travel_alerts` is never referenced.

### Implementation

**File: `outputs/static/app.js`** — after the travel deadlines loop (after line 852, before line 854 `if (allTravel.length > 0)`)

Find:
```javascript
            if (allTravel.length > 0) {
```

Insert before it:
```javascript
            // 4. Travel alerts (Baker-generated from email/deadline cadence — most reliable source)
            var travelAlerts = data.travel_alerts || [];
            for (var tai = 0; tai < travelAlerts.length; tai++) {
                var ta = travelAlerts[tai];
                // Skip if already covered by trips, calendar events, or deadlines
                var taTitle = (ta.title || '').toLowerCase();
                var taDup = allTravel.some(function(html) { return html.toLowerCase().indexOf(taTitle.slice(0, 30)) >= 0; });
                if (taDup) continue;
                // Render as compact card
                var taDot = 'blue';
                var taLabel = ta.title || 'Travel alert';
                // Strip "TODAY: " or "In 2d: " prefix for cleaner display
                taLabel = taLabel.replace(/^(TODAY|In \d+d):\s*/i, '');
                var taTime = '';
                if (ta.travel_date) {
                    var _taToday = new Date().toISOString().slice(0, 10);
                    var _taDate = ta.travel_date.slice(0, 10);
                    if (_taDate === _taToday) taTime = 'Today';
                    else {
                        var _taDiff = Math.round((new Date(_taDate) - new Date(_taToday)) / 86400000);
                        if (_taDiff === 1) taTime = 'Tomorrow';
                        else if (_taDiff > 0) taTime = 'In ' + _taDiff + ' days';
                    }
                }
                allTravel.push(
                    '<div class="card card-compact"><div class="card-header">' +
                    '<span class="nav-dot ' + taDot + '" style="margin-top:5px;"></span>' +
                    '<span class="card-title">' + esc(taLabel) + '</span>' +
                    '<span class="card-time">' + esc(taTime) + '</span>' +
                    '</div></div>'
                );
            }

```

### What changed:
Travel alerts now render as a 4th source in the travel grid. Blue dot to distinguish from deadline-based (amber) and calendar-based cards. Deduplication check prevents double-showing if the same flight appears as both a deadline and an alert.

### Key Constraints
- The `travel_date` column on alerts is used for the date label. If null, no date label shows (acceptable — the title contains the info).
- The dedup check compares the first 30 chars of the alert title against existing travel HTML. This is fuzzy but sufficient — exact match would require normalizing across different card formats.

---

## Part 3: Demote Google Calendar to optional fallback

### Problem
`travel_today` depends on `poll_todays_meetings()` which requires a valid Google Calendar OAuth token. When the token expires, all calendar data silently disappears. The Director doesn't maintain Google Calendar — Baker should work without it.

### Current State (dashboard.py, lines 2293-2347)
```python
        # Phase 3A: Fetch today's calendar events, classify as meeting vs travel
        meetings_today = []
        travel_today = []
        try:
            from triggers.calendar_trigger import poll_todays_meetings
            raw_meetings = poll_todays_meetings()  # all of today (past + future)
            ...
        except Exception as e:
            logger.warning(f"Morning brief: calendar unavailable: {e}")
```

### Implementation
**No code change needed.** The try/except already handles calendar failure gracefully — `travel_today` stays empty. With Parts 1 and 2 above, the travel card is now built from 3 reliable DB sources (trips, deadlines, alerts). Calendar data is already an additive bonus when available.

**However**, add a log message so we know when calendar is down:

**File: `outputs/dashboard.py`** — line 2347

Find:
```python
            logger.warning(f"Morning brief: calendar unavailable: {e}")
```

Replace with:
```python
            logger.warning(f"Morning brief: calendar unavailable (travel cards use DB fallback): {e}")
```

This makes it explicit in logs that the system is operating without calendar but travel cards still work.

---

## Part 4: Add NCE/GVA to IATA travel pattern detection

### Problem
`_TRAVEL_PATTERNS` regex (line 3125) lists 14 IATA codes for travel event classification but misses NCE (Nice) and GVA (Geneva) — two airports the Director uses regularly. These are in the `_IATA_TO_CITY` mapping (line 3138) but not in the classification pattern.

### Current State (dashboard.py, line 3125)
```python
    r'|\b(?:VIE|FRA|SFO|JFK|LHR|CDG|ZRH|MUC|LAX|SIN|DXB|FCO|BCN|AMS)\b',  # IATA codes
```

### Implementation

**File: `outputs/dashboard.py`** — line 3125

Replace:
```python
    r'|\b(?:VIE|FRA|SFO|JFK|LHR|CDG|ZRH|MUC|LAX|SIN|DXB|FCO|BCN|AMS)\b',  # IATA codes
```

With:
```python
    r'|\b(?:VIE|FRA|SFO|JFK|LHR|CDG|ZRH|MUC|LAX|SIN|DXB|FCO|BCN|AMS|NCE|GVA|PMI|BER|TXL)\b',  # IATA codes
```

### What changed:
Added NCE (Nice), GVA (Geneva), PMI (Palma), BER (Berlin Brandenburg), TXL (Berlin Tegel) — all present in `_IATA_TO_CITY` but previously missing from the classification pattern.

---

## Part 5: Report calendar failures to health system

### Problem
When `poll_todays_meetings()` fails in the calendar trigger's `check_calendar_and_prep()`, the inner except catches the error and returns early, bypassing `report_failure("calendar")`. The sentinel health dashboard shows "healthy" even when calendar has been broken for 2 days.

### Current State (triggers/calendar_trigger.py, lines 577-582)
```python
def check_calendar_and_prep():
    try:
        try:
            meetings = poll_upcoming_meetings(hours_ahead=24)
        except Exception as e:
            logger.warning(f"Calendar poll failed (API unreachable or token expired): {e}")
            return
```

### Implementation

**File: `triggers/calendar_trigger.py`**

Find the inner except block. Read the actual code first to confirm exact line numbers, then replace:

```python
        except Exception as e:
            logger.warning(f"Calendar poll failed (API unreachable or token expired): {e}")
            return
```

With:
```python
        except Exception as e:
            logger.warning(f"Calendar poll failed (API unreachable or token expired): {e}")
            try:
                from triggers.state import trigger_state
                trigger_state.report_failure("calendar", str(e))
            except Exception:
                pass
            return
```

### What changed:
Calendar failures now register in the health system. After 20 consecutive failures, the generic circuit breaker marks it as unhealthy — visible in the sentinel health dashboard.

---

## Part 6: Cache bust

**File: `outputs/static/index.html`**

Check current values and bump:
- `app.js?v=N` → `app.js?v=N+1`

(CSS not modified in this brief.)

---

## Files Modified
- `outputs/dashboard.py` — travel_deadlines SQL fix (CURRENT_DATE), log message update, IATA pattern expansion
- `outputs/static/app.js` — render travel_alerts in frontend travel grid
- `outputs/static/index.html` — cache bust (JS only)
- `triggers/calendar_trigger.py` — report_failure on calendar poll error

## Do NOT Touch
- `triggers/calendar_trigger.py` `poll_todays_meetings()` — leave the function as-is, it's fine when calendar works
- `outputs/static/style.css` — no CSS changes in this brief
- Google Calendar OAuth flow — separate concern, not blocking anymore

## Quality Checkpoints
1. **Today's flight shows**: Reload dashboard → Nice-Geneva LX 529 appears in travel card
2. **Future flights show**: GVA-VIE (Apr 5) and VIE-GVA (Apr 9) appear in travel card
3. **Calendar down = travel still works**: Even with expired calendar token, travel cards populated from DB
4. **No duplicates**: If the same flight appears as both a deadline and an alert, only one card renders
5. **IATA detection**: A calendar event titled "NCE-GVA transfer" correctly classifies as travel (not meeting)
6. **Health reporting**: Check sentinel health after deploy — calendar should show failure count if token is still expired
7. **Syntax check**: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` and same for `triggers/calendar_trigger.py`

## Verification SQL
```sql
-- Confirm today's flight deadline is queryable
SELECT id, description, due_date FROM deadlines
WHERE status = 'active' AND due_date >= CURRENT_DATE AND due_date < CURRENT_DATE + INTERVAL '4 days'
AND (description ILIKE '%flight%' OR description ILIKE '%departure%' OR description ILIKE '%travel%')
ORDER BY due_date ASC LIMIT 10;

-- Confirm travel alerts exist
SELECT id, title, tags, travel_date FROM alerts
WHERE status = 'pending' AND (tags ? 'travel' OR title ILIKE '%flight%')
ORDER BY created_at DESC LIMIT 10;
```

## Cost Impact
- Zero — no API calls, no model changes. Pure SQL fix + frontend rendering.

## Rollback
Revert the SQL `CURRENT_DATE` back to `NOW()`, remove the `travel_alerts` rendering block from app.js. Calendar dependency is restored (but still broken without token refresh).
