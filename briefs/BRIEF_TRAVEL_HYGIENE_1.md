# BRIEF: TRAVEL-HYGIENE-1 — Travel Alert Dedup + Lifecycle

**Priority:** HIGH
**Assignee:** Code Brisen (Mac Mini)
**Estimated effort:** 2-3 hours
**Date:** 2026-03-25

---

## Core Problem

One flight (Vienna → Geneva, March 26) generated **6 separate alerts** from 3 different subsystems:

| ID | Source | Title | Created |
|----|--------|-------|---------|
| 14178 | `pipeline` | Travel Document: Vienna → Geneva | Mar 23 17:19 |
| 14179 | `pipeline` | Travel Booking Confirmed: Vienna → Geneva | Mar 23 17:19 |
| 14195 | `deadline_cadence` | Due in 48h: Flight departure... | Mar 24 00:13 |
| 14207 | `pipeline` | Flight Vienna to Geneva — March 26 | Mar 24 06:02 |
| 14316 | `deadline_cadence` | DUE TODAY: Flight departure... | Mar 25 00:12 |
| 14340 | `obligation` | Execute flight to Geneva... | Mar 25 06:50 |

**The Director's expectation:** ONE card for the flight that UPDATES as the date approaches (e.g., "3 days away" → "Tomorrow" → "Today" → auto-dismissed after departure).

---

## Design: Single Travel Card with Lifecycle

A travel event should have **one alert** that evolves through stages:

```
Created (booking detected) → Upcoming (48h) → Tomorrow → Today → Auto-dismissed (after departure)
```

The alert **title and body update in place** — no new alerts at each stage.

---

## Fix 1: Pipeline dedup for travel alerts

**File:** `orchestrator/pipeline.py` (or wherever `source='pipeline'` travel alerts are created)

**Problem:** Pipeline creates travel alerts with no `source_id`, so dedup doesn't work.

**Fix:** When creating a travel alert, generate a deterministic `source_id` from the flight details:
```python
# Extract key identifiers: route + date
source_id = f"travel:{destination}:{travel_date}"
# e.g., "travel:geneva:2026-03-26"
```

Before creating, check if an alert with that `source_id` already exists. If yes, **update** it instead of creating a new one.

Also search: `Grep for create_alert` calls where `tags` includes `'travel'` or title mentions `'flight'`/`'Travel'` across all `.py` files. Every one of these needs a `source_id`.

**Key grep:**
```bash
grep -n "create_alert" orchestrator/pipeline.py orchestrator/obligation_generator.py triggers/email_trigger.py
```

## Fix 2: Deadline reminders UPDATE existing alert

**File:** `orchestrator/deadline_manager.py:385-448`

**Problem:** Each deadline stage (`48h`, `day_of`, `overdue`) creates a NEW alert with a different `source_id` (`deadline:1089:48h`, `deadline:1089:day_of`).

**Fix:** For travel-related deadlines, find and UPDATE the existing travel alert instead of creating a new one:

```python
def _fire_reminder(deadline, stage, hours_remaining):
    description = deadline.get("description", "")

    # For travel deadlines: update existing alert instead of creating new
    if _is_travel_deadline(description):
        _update_travel_alert(deadline, stage, hours_remaining)
        return

    # ... existing logic for non-travel deadlines ...

def _is_travel_deadline(description: str) -> bool:
    """Check if deadline is travel-related."""
    travel_keywords = ['flight', 'departure', 'airport', 'check-in', 'travel', 'train']
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in travel_keywords)

def _update_travel_alert(deadline, stage, hours_remaining):
    """Find existing travel alert and update its title/body for new stage."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return
    try:
        description = deadline["description"]
        due_date = deadline.get("due_date")

        # Build stage-appropriate title
        from zoneinfo import ZoneInfo
        director_tz = ZoneInfo("Europe/Zurich")
        now_local = datetime.now(director_tz).date()
        due_local = due_date.astimezone(director_tz).date() if due_date else now_local
        days_until = (due_local - now_local).days

        if days_until <= 0:
            title = f"TODAY: {description}"
        elif days_until == 1:
            title = f"Tomorrow: {description}"
        else:
            title = f"In {days_until}d: {description}"

        body = f"{description} (due {due_local.strftime('%B %-d')}, {deadline.get('priority', 'normal').upper()})"

        # Find existing travel alert for this route
        cur = conn.cursor()
        cur.execute("""
            UPDATE alerts
            SET title = %s, body = %s, updated_at = NOW()
            WHERE status = 'pending'
              AND (tags ? 'travel' OR title ILIKE '%%flight%%')
              AND (title ILIKE %s OR body ILIKE %s)
            RETURNING id
        """, (title, body, f"%{description[:30]}%", f"%{description[:30]}%"))

        updated = cur.fetchone()
        if updated:
            conn.commit()
            logger.info(f"Updated travel alert #{updated[0]} to stage '{stage}'")
        else:
            # No existing alert found — create one (fallback)
            conn.rollback()
            store.create_alert(
                tier=2, title=title, body=body,
                action_required=False, tags=["travel"],
                source="deadline_cadence",
                source_id=f"travel-deadline:{deadline.get('id')}",
            )
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.warning(f"_update_travel_alert failed: {e}")
    finally:
        store._put_conn(conn)
```

## Fix 3: Obligation generator — skip if travel alert exists

**File:** `orchestrator/obligation_generator.py`

**Problem:** The obligation generator proposes "Execute flight to Geneva" even though travel alerts already exist.

**Fix:** In the obligation generator's dedup logic, before creating a travel-related obligation, check if a travel alert already exists:

```python
# Before proposing a travel obligation, check for existing travel alert
if _is_travel_related(proposed_title):
    existing = _check_existing_travel_alert(proposed_title)
    if existing:
        logger.info(f"Obligation skipped — travel alert already exists: {existing}")
        continue
```

## Fix 4: Auto-dismiss after departure

**File:** `triggers/embedded_scheduler.py` (add new job) + `outputs/dashboard.py`

Add a lightweight scheduled job (every 6 hours) or a query filter:

**Option A (query filter — simpler):** In the travel alerts query, exclude alerts whose travel date has passed. Since travel alerts don't have a `due_date` column, use the associated deadline's `due_date` or parse from body.

**Option B (scheduled job — cleaner):**
```python
def auto_dismiss_past_travel():
    """Dismiss travel alerts where the travel date has passed."""
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        # Dismiss travel alerts older than 24h that aren't linked to active trips
        cur.execute("""
            UPDATE alerts SET status = 'dismissed'
            WHERE status = 'pending'
              AND (tags ? 'travel' OR title ILIKE '%%flight%%')
              AND created_at < NOW() - INTERVAL '36 hours'
        """)
        count = cur.rowcount
        conn.commit()
        cur.close()
        if count:
            logger.info(f"Auto-dismissed {count} past travel alerts")
    except Exception as e:
        conn.rollback()
        logger.warning(f"auto_dismiss_past_travel failed: {e}")
    finally:
        store._put_conn(conn)
```

Register in `embedded_scheduler.py`:
```python
scheduler.add_job(auto_dismiss_past_travel, 'interval', hours=6, id='dismiss_past_travel')
```

## Fix 5: Travel deadlines in Travel grid

**File:** `outputs/dashboard.py` ~1913, `outputs/static/app.js` ~777

The Travel grid currently only shows: trips + today's calendar events + travel alerts.

Add travel-related deadlines (next 3 days) so tomorrow's flight appears in the Travel grid:

```python
# In morning_brief endpoint, after travel_alerts:
travel_deadlines = []
try:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, description, due_date, priority
        FROM deadlines
        WHERE status = 'active'
          AND due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
          AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
               OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%')
        ORDER BY due_date ASC LIMIT 5
    """)
    travel_deadlines = [_serialize(dict(r)) for r in cur.fetchall()]
    cur.close()
except Exception:
    pass
```

Add to response: `"travel_deadlines": travel_deadlines`

In `app.js`, render in the Travel grid:
```javascript
var travelDeadlines = data.travel_deadlines || [];
for (var tdi = 0; tdi < travelDeadlines.length; tdi++) {
    var td = travelDeadlines[tdi];
    var dueLabel = fmtDeadlineDays(td.due_date);
    allTravel.push(
        '<div class="card card-compact"><div class="card-header">' +
        '<span class="nav-dot amber" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(td.description) + '</span>' +
        '<span class="card-time" style="font-weight:600;">' + esc(dueLabel) + '</span>' +
        '</div></div>'
    );
}
```

## Fix 6: "DUE TODAY" timezone bug

**File:** `orchestrator/deadline_manager.py:398-405`

Use Director's timezone for day-of-check:

```python
from zoneinfo import ZoneInfo

if stage in ("48h", "day_of", "overdue"):
    director_tz = ZoneInfo("Europe/Zurich")
    now_local = datetime.now(director_tz).date()

    if stage == "overdue":
        title = f"OVERDUE: {description}"
    elif stage == "day_of":
        due_local = due_date.astimezone(director_tz).date() if due_date else now_local
        if now_local == due_local:
            title = f"TODAY: {description}"
        elif (due_local - now_local).days == 1:
            title = f"Tomorrow: {description}"
        else:
            title = f"Due {due_str}: {description}"
    else:
        title = f"In 48h: {description}"
```

---

## Files to Modify

| File | Fix |
|------|-----|
| `orchestrator/pipeline.py` | Fix 1: Add `source_id` to travel alerts |
| `orchestrator/deadline_manager.py` | Fix 2: Update existing alert, not create new. Fix 6: Timezone-aware labels |
| `orchestrator/obligation_generator.py` | Fix 3: Skip if travel alert exists |
| `triggers/embedded_scheduler.py` | Fix 4: Register auto-dismiss job |
| `outputs/dashboard.py` | Fix 4: Auto-dismiss function. Fix 5: Travel deadlines query |
| `outputs/static/app.js` | Fix 5: Render travel deadlines in grid. Bump cache version |

## Immediate Data Cleanup (already done by AI Head)

```sql
-- Dismissed duplicate lost laptop alerts (14205, 14206)
-- Fixed alert 14316 title: "DUE TODAY" → "Due tomorrow"
```

## Testing

1. Create a test deadline for a flight 2 days from now → should produce ONE travel alert
2. Wait for deadline_cadence cycle → alert title should UPDATE, not create a second alert
3. After the flight date passes → alert auto-dismissed within 36 hours
4. Travel grid shows upcoming travel deadlines (next 3 days)
5. "DUE TODAY" only appears when it's actually today in Europe/Zurich timezone

---

*Brief by AI Head — Session 37, 2026-03-25*
