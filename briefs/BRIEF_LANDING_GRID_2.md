# Brief: LANDING-GRID-2 — Grid Polish: Dedup, Expandable Detail, Vivid Titles, Quick-Add

**Author:** AI Head (Session 21, Director feedback on LANDING-GRID-1)
**For:** Code 300
**Priority:** HIGH — 5 Director-reported issues from live testing

---

## Issue 1: Remove `[Baker Prep]` Duplicates + Double Prefix

### Problem
Frankfurt flight shows 5 times. Calendar returns both the actual event AND Baker's internal `[Baker Prep]` scheduler events. Some have double prefix `[Baker Prep] [Baker Prep]`.

### Fix
**`outputs/static/app.js` — in the travel/meetings rendering:**

Filter out any meeting whose title starts with `[Baker Prep]`:

```javascript
var travelItems = (data.meetings_today || []).filter(function(m) {
    return !m.title.startsWith('[Baker Prep]');
});
```

This keeps only the real calendar events (which already have `prepped` status and `prep_notes`).

---

## Issue 2: More Vivid Section Titles

### Problem
Section titles (TRAVEL & MEETINGS, FIRES, DEADLINES, COMMITMENTS) are faint `var(--text3)` — hard to read and don't guide the eye.

### Fix
**`outputs/static/style.css` — `.grid-cell-header` label:**

Make the section label bolder and use primary text color:

```css
.grid-cell-header .section-label {
    font-size: 12px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: 0.5px;
    margin-bottom: 0;
}
```

Keep the count badge in `var(--text3)` for contrast — the title pops, the count is secondary.

---

## Issue 3: "+" Button on Upcoming Tab (Quick-Add Issue)

### Problem
Director wants to add custom issues to the Upcoming list. Currently everything in Upcoming is Baker-generated — no way for the Director to manually add.

### Fix

**Frontend (`app.js` + `index.html`):**

Add a "+" button next to the "Upcoming" sidebar tab label (or at the top of the Upcoming view):

```html
<button class="quick-add-btn" onclick="showQuickAdd()" title="Add issue">+</button>
```

On click, show a minimal inline form at the top of the Upcoming view:

```html
<div id="quickAddForm" style="display:none;">
    <input type="text" id="quickAddTitle" placeholder="What needs attention?"
           style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;margin-bottom:8px;">
    <div style="display:flex;gap:8px;">
        <select id="quickAddPriority" style="...">
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
        </select>
        <input type="date" id="quickAddDue" style="...">
        <button onclick="submitQuickAdd()" style="...">Add</button>
        <button onclick="hideQuickAdd()" style="...">Cancel</button>
    </div>
</div>
```

**Backend (`outputs/dashboard.py`):**

New endpoint:

```python
@app.post("/api/alerts/quick-add", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def quick_add_alert(body: dict = Body(...)):
    """Director manually creates an alert/issue from the dashboard."""
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")

    priority = body.get("priority", "normal")
    due_date = body.get("due_date")  # optional ISO date

    store = _get_store()

    # Create as T1 alert (Director-created = high priority by definition)
    tier = 1 if priority == "critical" else 2
    alert_id = store.create_alert(
        tier=tier,
        title=title,
        body=f"Director-created issue. Priority: {priority}.",
        action_required=True,
        source="director_manual",
        tags=["director-created"],
    )

    # Also create deadline if due_date provided
    if due_date and alert_id:
        store.insert_deadline(
            description=title,
            due_date=due_date,
            source_type="director_manual",
            priority=priority,
            confidence="hard",
        )

    return {"status": "created", "alert_id": alert_id}

    # Baker auto-enriches in next pipeline cycle (every 5 min):
    # - matter_slug from keyword matching
    # - tags from auto_tag()
    # - people links from name detection
    # No enrichment at creation time — instant capture, background intelligence.
```

**Style the "+" button:**
```css
.quick-add-btn {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text3);
    font-size: 14px;
    line-height: 20px;
    text-align: center;
    cursor: pointer;
    margin-left: 8px;
}
.quick-add-btn:hover {
    background: var(--blue);
    color: white;
    border-color: var(--blue);
}
```

---

## Issue 4: Deadlines — Click to Expand

### Problem
Clicking a deadline does nothing. Director expects expandable detail like travel cards.

### Fix

**Backend (`outputs/dashboard.py`):**

Include `source_snippet` (truncated) in deadline data. The current query excludes it because it "can be 80KB per row." Fix: include first 500 chars.

Change the deadlines query:
```sql
SELECT id, description, due_date, source_type, confidence,
       priority, status, created_at,
       LEFT(source_snippet, 500) as source_snippet
FROM deadlines
WHERE status = 'active' AND due_date <= NOW() + INTERVAL '7 days'
ORDER BY due_date ASC LIMIT 10
```

**Frontend (`app.js`):**

In the deadline card rendering, add the same click-to-expand pattern:

```javascript
// For each deadline item in the grid
var hasDetail = dl.source_snippet && dl.source_snippet.trim().length > 0;
var clickAttr = hasDetail ? ' onclick="var d=this.querySelector(\'.item-detail\');if(d){d.style.display=d.style.display===\'none\'?\'block\':\'none\'}"' : '';
var chevron = hasDetail ? '<span class="landing-item-chevron">▾</span>' : '';
var detailHtml = hasDetail
    ? '<div class="item-detail" style="display:none;font-size:12px;color:var(--text2);padding:8px 12px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);">' + esc(dl.source_snippet) + '</div>'
    : '';
```

---

## Issue 5: Fires — Click to Expand Summary

### Problem
Same as deadlines — fire items should be clickable to show a summary.

### Fix

**Backend (`outputs/dashboard.py`):**

The top_fires query already uses `SELECT *`, so `body` is included. No backend change needed.

**Frontend (`app.js`):**

In the fires card rendering, add click-to-expand:

```javascript
var fireBody = (f.body || '').substring(0, 500);
var hasDetail = fireBody.trim().length > 0;
var clickAttr = hasDetail ? ' onclick="var d=this.querySelector(\'.item-detail\');if(d){d.style.display=d.style.display===\'none\'?\'block\':\'none\'}" style="cursor:pointer;"' : '';
var chevron = hasDetail ? '<span class="landing-item-chevron">▾</span>' : '';
var detailHtml = hasDetail
    ? '<div class="item-detail" style="display:none;font-size:12px;color:var(--text2);padding:8px 12px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);">'
      + esc(fireBody)
      + (f.body && f.body.length > 500 ? '<div style="margin-top:8px;"><a href="#" onclick="event.stopPropagation();switchTab(\'fires\');return false;" style="color:var(--blue);font-size:11px;">See full →</a></div>' : '')
      + '</div>'
    : '';
```

**Key detail:** `event.stopPropagation()` on the "See full →" link prevents the toggle from firing when clicking the link.

---

## Execution Order

1. **Issue 1** (dedup `[Baker Prep]`) — quickest, most visible fix
2. **Issue 2** (vivid titles) — CSS only, instant
3. **Issue 4 + 5** together (expandable deadlines + fires) — same pattern, do both at once
4. **Issue 3** (quick-add) — new feature, do last

## Files to Modify

| File | Change |
|------|--------|
| `outputs/static/app.js` | Filter `[Baker Prep]`, expandable fires/deadlines, quick-add form |
| `outputs/static/style.css` | Vivid titles, quick-add button style |
| `outputs/static/index.html` | Quick-add button in Upcoming tab header |
| `outputs/dashboard.py` | Include source_snippet in deadlines, POST /api/alerts/quick-add endpoint |

## Verification

1. No `[Baker Prep]` items in travel grid
2. Section titles are bold and readable
3. Click deadline → source snippet expands with ▾
4. Click fire → alert body expands (truncated to 500 chars) with "See full →"
5. "+" button on Upcoming → form appears, submit creates alert
6. New alert appears in Upcoming list after creation
