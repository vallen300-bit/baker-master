# BRIEF: TRAVEL-HYGIENE-1 — Fix Travel Section + Deadline Labels

**Priority:** HIGH
**Assignee:** Code Brisen (Mac Mini)
**Estimated effort:** 1-2 hours
**Date:** 2026-03-25

---

## Problem Statement

Three issues reported by Director on the Baker dashboard:

### Issue 1: Past travel alerts never expire
The Travel section on the dashboard grid shows old travel alerts (flights from days ago). They persist indefinitely because they're queried as `status = 'pending'` with no date filter.

**Current query** (`outputs/dashboard.py:1917-1922`):
```sql
SELECT * FROM alerts
WHERE status = 'pending'
  AND (tags ? 'travel' OR title ILIKE '%%flight%%')
ORDER BY created_at DESC
LIMIT 10
```

**Problem:** No date filter. A flight alert from March 20 still shows on March 25.

**Fix:** Auto-dismiss travel alerts once their travel date has passed. Two approaches:

**Approach A (recommended):** Add a date filter to the query — only show travel alerts created in the last 2 days OR whose body mentions a future date:
```sql
SELECT * FROM alerts
WHERE status = 'pending'
  AND (tags ? 'travel' OR title ILIKE '%%flight%%')
  AND created_at > NOW() - INTERVAL '48 hours'
ORDER BY created_at DESC
LIMIT 10
```

**Approach B (cleaner, more work):** Add a scheduled job that auto-dismisses travel alerts after the travel date passes. Parse the date from the alert body/title. Run every 6 hours.

### Issue 2: Tomorrow's flight not in Travel section
The flight to Vienna tomorrow (deadline 1089: "Flight departure from Vienna to Geneva", due 2026-03-26) only appears as a deadline in the left sidebar, not in the Travel grid.

**Root cause:** The Travel grid shows:
1. Active trips from `trips` table (line 781-807)
2. Today's calendar travel events from `travel_today` (line 810-817)
3. Travel alerts from `alerts` table (line 832)

Tomorrow's flight exists as a **deadline** (deadlines table id=1089) but NOT as a travel alert or calendar event for today. The Travel grid doesn't look at the deadlines table.

**Fix:** In the morning brief endpoint (`outputs/dashboard.py` around line 1913), add a query for upcoming travel-related deadlines and include them in the travel section:

```python
# After travel_alerts query, also fetch travel-related deadlines
travel_deadlines = []
try:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, description, due_date, priority, status
        FROM deadlines
        WHERE status = 'active'
          AND due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
          AND (description ILIKE '%%flight%%' OR description ILIKE '%%travel%%'
               OR description ILIKE '%%airport%%' OR description ILIKE '%%check-in%%'
               OR description ILIKE '%%departure%%')
        ORDER BY due_date ASC
        LIMIT 5
    """)
    travel_deadlines = [_serialize(dict(r)) for r in cur.fetchall()]
    cur.close()
except Exception as e:
    logger.warning(f"Morning brief: travel deadlines query failed: {e}")
```

Then add `"travel_deadlines": travel_deadlines` to the response dict (line ~1955).

In `app.js`, render these in the Travel grid (after travel alerts, before the "no travel" empty state):
```javascript
// 3. Upcoming travel deadlines (next 3 days)
var travelDeadlines = data.travel_deadlines || [];
for (var tdi = 0; tdi < travelDeadlines.length; tdi++) {
    var td = travelDeadlines[tdi];
    var dueLabel = fmtDeadlineDays(td.due_date);
    allTravel.push(
        '<div class="card card-compact"><div class="card-header">' +
        '<span class="nav-dot amber" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(td.description) + '</span>' +
        '<span class="card-time">' + esc(dueLabel) + '</span>' +
        '</div></div>'
    );
}
```

### Issue 3: "DUE TODAY" label is wrong — flight is tomorrow
Deadline 1089 has `due_date = 2026-03-26` (tomorrow). But the deadline manager fires a "DUE TODAY" reminder at stage `day_of`.

**Root cause:** `orchestrator/deadline_manager.py:402-403`:
```python
elif stage == "day_of":
    title = f"DUE TODAY: {description}"
```

The `day_of` stage fires when `hours_remaining` is between 0 and 24. If the deadline is `2026-03-26 00:00:00 UTC` and it's checked at `2026-03-25 00:12 UTC`, that's ~24 hours remaining — which crosses into `day_of` territory.

**The real bug:** The deadline `due_date` is stored as `2026-03-26 00:00:00+00:00` (midnight UTC). The check runs at midnight UTC on March 25. At that point, the deadline is ~24 hours away — it's still tomorrow in most timezones, but the `day_of` stage fires because `hours_remaining < 24`.

**Fix options:**

**Option A (quick):** Change the alert title to use the actual date, not "DUE TODAY":
```python
elif stage == "day_of":
    title = f"Due {due_str}: {description}"
```
This avoids the timezone confusion entirely.

**Option B (better):** Use the Director's timezone (CET/CEST) for the check:
```python
from zoneinfo import ZoneInfo
director_tz = ZoneInfo("Europe/Zurich")
now_local = datetime.now(director_tz).date()
due_local = due_date.astimezone(director_tz).date()
if now_local == due_local:
    title = f"DUE TODAY: {description}"
elif (due_local - now_local).days == 1:
    title = f"Due tomorrow: {description}"
else:
    title = f"Due in {(due_local - now_local).days}d: {description}"
```

**Recommend Option B** — it's more accurate and adds a "Due tomorrow" label.

---

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/dashboard.py` | ~1913-1925: Add date filter to travel alerts query. ~1925: Add travel deadlines query. ~1955: Add to response. |
| `outputs/static/app.js` | ~777-825: Render travel deadlines in grid. Bump cache version. |
| `orchestrator/deadline_manager.py` | ~400-405: Fix "DUE TODAY" to use Director's timezone. Add "Due tomorrow" label. |

## Immediate Data Cleanup

These stale alerts should be dismissed now (or the backend fix will filter them out):

```sql
-- Dismiss old travel alerts (before today)
UPDATE alerts SET status = 'dismissed'
WHERE status = 'pending'
  AND (tags ? 'travel' OR title ILIKE '%flight%')
  AND created_at < NOW() - INTERVAL '48 hours';

-- Also dismiss duplicate lost laptop alerts
UPDATE alerts SET status = 'dismissed'
WHERE status = 'pending'
  AND title ILIKE '%lost laptop%'
  AND id NOT IN (SELECT MAX(id) FROM alerts WHERE title ILIKE '%lost laptop%' AND status = 'pending');
```

## Testing

1. After fix: Travel grid should show tomorrow's Vienna flight
2. Past flights (March 20, 21, etc.) should NOT appear
3. Deadline reminder for tomorrow's flight should say "Due tomorrow" not "DUE TODAY"
4. Verify `fmtDeadlineDays()` returns "Tomorrow" for March 26 when viewed on March 25

---

*Brief by AI Head — Session 37, 2026-03-25*
