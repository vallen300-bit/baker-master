# BRIEF: Dashboard Data Layer — Commitments + Browser Monitor Tabs

**Author:** Code 300 (Session 14)
**Date:** 2026-03-08
**Status:** Ready for Code Brisen
**Branch:** `feat/dashboard-data-layer`

---

## Context

Baker has 2 rich data sources with full API endpoints but zero UI visibility:
- **Commitments:** 50+ tracked items from meetings/emails — the Director can't see them
- **Browser Sentinel:** 4 monitoring tasks (MO rates, Park Hyatt, Grundbuch, occupancy) — results invisible

This brief adds 2 new sidebar tabs to the CEO Cockpit.

---

## Existing Patterns (FOLLOW EXACTLY)

### Tab Registration Pattern

**`outputs/static/index.html`** — sidebar nav items:
```html
<div class="nav-item" data-tab="TAB_NAME">
    <div class="nav-icon">ICON</div>
    <div class="nav-label">Label</div>
</div>
```

**`outputs/static/app.js`** — tab wiring:
```javascript
// 1. Add to TAB_VIEW_MAP (line 116):
const TAB_VIEW_MAP = {
    ...existing tabs...
    'commitments': 'viewCommitments',
    'browser': 'viewBrowser',
};

// 2. Add to FUNCTIONAL_TABS (line 130):
const FUNCTIONAL_TABS = new Set([...existing..., 'commitments', 'browser']);

// 3. Add loader call in switchTab() (line 132+):
// In the switch/if chain that calls tab-specific loaders:
if (tabName === 'commitments') loadCommitmentsTab();
if (tabName === 'browser') loadBrowserTab();
```

### View Container Pattern

**`outputs/static/index.html`** — add view divs alongside existing views:
```html
<!-- VIEW: Commitments -->
<div id="viewCommitments" class="view">
    <h2>Commitments</h2>
    <div id="commitmentsContent"></div>
</div>

<!-- VIEW: Browser Monitor -->
<div id="viewBrowser" class="view">
    <h2>Browser Monitor</h2>
    <div id="browserContent"></div>
</div>
```

---

## Part 1: Commitments Tab

### API Endpoint

```
GET /api/commitments?status=active
GET /api/commitments?status=overdue
```

Response:
```json
{
    "commitments": [
        {
            "id": 1,
            "description": "Send updated cash flow to Balazs",
            "assigned_to": "Director",
            "due_date": "2026-03-10",
            "status": "active",
            "source": "meeting",
            "source_id": "fireflies:abc123",
            "created_at": "2026-03-05T10:00:00Z"
        }
    ],
    "total": 52,
    "overdue_count": 8
}
```

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  Commitments                          8 overdue / 52    │
│                                                         │
│  [Active ▼] [All] [Overdue] [Completed]    filter tabs  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ ⚠️ OVERDUE  Send updated cash flow to Balazs      │  │
│  │  Due: Mar 10 · Source: Meeting · Assigned: Dir.   │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Prepare LP quarterly report for Wertheimer       │  │
│  │  Due: Mar 15 · Source: Email · Assigned: Dir.     │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Follow up with Buchwalder on RG7 escrow          │  │
│  │  Due: Mar 20 · Source: Meeting · Assigned: Dir.   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Implementation

```javascript
var _commitmentsFilter = 'active';

async function loadCommitmentsTab() {
    var container = document.getElementById('commitmentsContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var data = await bakerFetch('/api/commitments?status=' + _commitmentsFilter).then(r => r.json());
        var items = data.commitments || [];
        var overdue = data.overdue_count || 0;
        var total = data.total || items.length;

        var html = '';
        // Header with counts
        html += '<div class="tab-header">';
        html += '<span class="tab-count">' + overdue + ' overdue / ' + total + ' total</span>';
        html += '</div>';

        // Filter tabs
        html += '<div class="filter-tabs">';
        ['active', 'overdue', 'completed', ''].forEach(function(f) {
            var label = f || 'all';
            var cls = _commitmentsFilter === f ? 'filter-tab active' : 'filter-tab';
            html += '<button class="' + cls + '" onclick="filterCommitments(\'' + f + '\')">' + esc(label.charAt(0).toUpperCase() + label.slice(1)) + '</button>';
        });
        html += '</div>';

        // Commitment cards
        if (items.length === 0) {
            html += '<div class="empty-state">No commitments with status "' + esc(_commitmentsFilter || 'all') + '"</div>';
        } else {
            items.forEach(function(c) {
                var isOverdue = c.status === 'overdue' || (c.due_date && new Date(c.due_date) < new Date() && c.status === 'active');
                var cls = isOverdue ? 'commitment-card overdue' : 'commitment-card';
                var dueStr = c.due_date ? new Date(c.due_date).toLocaleDateString('en-GB', {month: 'short', day: 'numeric'}) : 'No date';
                var badge = isOverdue ? '<span class="overdue-badge">OVERDUE</span> ' : '';

                html += '<div class="' + cls + '">';
                html += '<div class="commitment-desc">' + badge + esc(c.description) + '</div>';
                html += '<div class="commitment-meta">';
                html += 'Due: ' + esc(dueStr);
                html += ' · Source: ' + esc(c.source || '?');
                if (c.assigned_to) html += ' · Assigned: ' + esc(c.assigned_to);
                html += '</div>';
                html += '</div>';
            });
        }

        container.innerHTML = html;
    } catch (e) {
        container.textContent = 'Failed to load commitments.';
        console.warn('Commitments load failed:', e);
    }
}

function filterCommitments(status) {
    _commitmentsFilter = status;
    loadCommitmentsTab();
}
```

### CSS

```css
.commitment-card {
    background: white; border: 1px solid #e8e8e8; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 8px;
}
.commitment-card.overdue { border-left: 3px solid #f44336; }
.commitment-desc { font-size: 14px; font-weight: 500; margin-bottom: 4px; }
.commitment-meta { font-size: 12px; color: #888; }
.overdue-badge { background: #f44336; color: white; font-size: 11px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.filter-tabs { display: flex; gap: 4px; margin: 12px 0; }
.filter-tab { border: 1px solid #ddd; background: white; border-radius: 4px; padding: 4px 12px; font-size: 13px; cursor: pointer; }
.filter-tab.active { background: #333; color: white; border-color: #333; }
.tab-header { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.tab-count { font-size: 13px; color: #888; }
.empty-state { text-align: center; color: #aaa; padding: 32px; font-size: 14px; }
```

---

## Part 2: Browser Monitor Tab

### API Endpoints

```
GET /api/browser/tasks                    → list tasks
GET /api/browser/tasks/{id}               → task + 10 recent results
POST /api/browser/tasks/{id}/run          → manual trigger
GET /api/browser/status                   → health summary
```

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  Browser Monitor                    4 tasks active      │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  MO Vienna - Booking.com rates        [Run Now]   │  │
│  │  Mode: browser · Category: hotel_rates            │  │
│  │  Last polled: 14 min ago · 0 failures             │  │
│  │                                                   │  │
│  │  Latest result (2 min ago):                       │  │
│  │  Standard Room €389 · Deluxe €520 · Suite €890    │  │
│  │  [View history →]                                 │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Park Hyatt Vienna - Booking.com rates  [Run Now] │  │
│  │  Mode: browser · Category: hotel_rates            │  │
│  │  Last polled: 14 min ago · 0 failures             │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Austrian Grundbuch - RG7 Baden         [Run Now] │  │
│  │  Mode: simple · Category: public_records          │  │
│  │  Last polled: 14 min ago · 0 failures             │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Implementation

```javascript
async function loadBrowserTab() {
    var container = document.getElementById('browserContent');
    if (!container) return;
    container.textContent = 'Loading...';

    try {
        var data = await bakerFetch('/api/browser/tasks').then(r => r.json());
        var tasks = data.tasks || [];

        var html = '';
        html += '<div class="tab-header"><span class="tab-count">' + tasks.length + ' tasks</span></div>';

        if (tasks.length === 0) {
            html += '<div class="empty-state">No browser monitoring tasks configured</div>';
        } else {
            for (var i = 0; i < tasks.length; i++) {
                var t = tasks[i];
                var lastPolled = t.last_polled ? timeAgo(new Date(t.last_polled)) : 'never';
                var failures = t.consecutive_failures || 0;
                var failClass = failures > 0 ? ' browser-warn' : '';

                html += '<div class="browser-card">';
                html += '<div class="browser-header">';
                html += '<span class="browser-name">' + esc(t.name) + '</span>';
                html += '<button class="run-btn" onclick="runBrowserTask(' + t.id + ', this)">Run Now</button>';
                html += '</div>';
                html += '<div class="browser-meta">';
                html += 'Mode: ' + esc(t.mode) + ' · Category: ' + esc(t.category || '—');
                html += '</div>';
                html += '<div class="browser-meta' + failClass + '">';
                html += 'Last polled: ' + esc(lastPolled) + ' · ' + failures + ' failures';
                html += '</div>';

                // Show latest result snippet if available
                if (t.latest_result) {
                    var snippet = (t.latest_result.content || '').substring(0, 200).replace(/\n/g, ' ');
                    html += '<div class="browser-result">';
                    html += '<div class="result-label">Latest result:</div>';
                    html += '<div class="result-snippet">' + esc(snippet) + '</div>';
                    html += '</div>';
                }

                html += '</div>';
            }
        }

        container.innerHTML = html;
    } catch (e) {
        container.textContent = 'Failed to load browser tasks.';
        console.warn('Browser tab load failed:', e);
    }
}

async function runBrowserTask(taskId, btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
    try {
        await bakerFetch('/api/browser/tasks/' + taskId + '/run', { method: 'POST' });
        btn.textContent = 'Started';
        setTimeout(function() { btn.textContent = 'Run Now'; btn.disabled = false; }, 5000);
    } catch (e) {
        btn.textContent = 'Failed';
        setTimeout(function() { btn.textContent = 'Run Now'; btn.disabled = false; }, 3000);
    }
}

function timeAgo(date) {
    var seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return seconds + 's ago';
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + ' min ago';
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
}
```

### CSS

```css
.browser-card {
    background: white; border: 1px solid #e8e8e8; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 8px;
}
.browser-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.browser-name { font-size: 14px; font-weight: 600; }
.browser-meta { font-size: 12px; color: #888; margin-top: 2px; }
.browser-warn { color: #f44336; }
.browser-result { margin-top: 8px; padding-top: 8px; border-top: 1px solid #f0f0f0; }
.result-label { font-size: 11px; color: #888; text-transform: uppercase; margin-bottom: 4px; }
.result-snippet { font-size: 13px; color: #555; line-height: 1.4; }
.run-btn { border: 1px solid #2196f3; color: #2196f3; background: white; border-radius: 4px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.run-btn:hover { background: #2196f3; color: white; }
.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
```

---

## Part 3: Browser Task API Enhancement (small backend change)

The current `GET /api/browser/tasks` returns tasks but **not their latest result**. Brisen needs to add a `latest_result` field to each task in the response.

### Where

**`outputs/dashboard.py`** — find the `GET /api/browser/tasks` endpoint. After fetching tasks, for each task fetch the most recent result:

```python
# After fetching tasks list:
for task in tasks:
    cur.execute("""
        SELECT content, structured_data, created_at, mode_used
        FROM browser_results
        WHERE task_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (task["id"],))
    result = cur.fetchone()
    if result:
        task["latest_result"] = {
            "content": (result[0] or "")[:300],
            "structured_data": result[1],
            "created_at": result[2].isoformat() if result[2] else None,
            "mode_used": result[3],
        }
    else:
        task["latest_result"] = None
```

---

## Files Summary

| Action | File | What |
|--------|------|------|
| **MODIFY** | `outputs/static/index.html` | +2 nav items (sidebar) + 2 view containers |
| **MODIFY** | `outputs/static/app.js` | TAB_VIEW_MAP + FUNCTIONAL_TABS + 2 tab loaders + CSS |
| **MODIFY** | `outputs/dashboard.py` | Browser tasks endpoint: add latest_result per task |

**Estimated: ~250 lines (JS + CSS + HTML + backend tweak)**

---

## Verification Checklist

- [ ] Sidebar shows "Commitments" and "Browser" tabs
- [ ] Commitments tab loads 50+ items grouped by status
- [ ] Filter buttons work (Active/Overdue/Completed/All)
- [ ] Overdue commitments highlighted with red left border + badge
- [ ] Browser tab shows 4 seed tasks with last_polled time
- [ ] "Run Now" button triggers manual run, shows loading state
- [ ] Latest result snippet shown for tasks with results
- [ ] Both tabs handle empty data gracefully
- [ ] `timeAgo()` function shows human-readable time differences
- [ ] `bakerFetch()` used for all API calls
- [ ] `esc()` used for all user-generated content (XSS prevention)

---

## What NOT to Build

- No result history modal (just show latest snippet for now)
- No commitment editing/creation from UI (commitments are auto-extracted)
- No browser task creation from UI (use API or Scan to add tasks)
- No charts or graphs (text-based cards are sufficient for v1)
- No drag-and-drop or kanban view

---

## Context for Brisen

- `esc()` is the HTML sanitizer function — always use for any dynamic content
- `bakerFetch()` adds the X-Baker-Key header automatically
- `md()` converts markdown to HTML (calls `esc()` first) — use for rich text fields
- Existing tab pattern: each tab has a `loadXxxTab()` function called from `switchTab()`
- Sidebar icon pattern: use emoji or Unicode character in `.nav-icon` div
- The `GET /api/browser/tasks` endpoint currently returns `{tasks: [...], count: N}` — check exact response shape before building
- `timeAgo()` may already exist in app.js — search before creating a duplicate
