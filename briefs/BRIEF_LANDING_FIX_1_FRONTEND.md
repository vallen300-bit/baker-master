# BRIEF: LANDING-FIX-1 — Frontend-Only Landing Page Fixes

## Context
Dashboard audit (Apr 3) found duplicate travel items, raw internal IDs visible to Director, and misleading "All clear" text. These 3 fixes are frontend-only (app.js + index.html), zero backend risk.

## Estimated time: ~30min
## Complexity: Low
## Prerequisites: None

---

## Fix 1: Travel card duplicate items

### Problem
Travel card shows 5 items instead of 2 real flights. Same flights appear from both `travel_deadlines` and `travel_alerts`. The dedup check fails because alert titles have prefixes like `"TODAY: "` or `"In 2d: "` that don't appear in the deadline card HTML.

### Current State
`app.js` lines 855-861:
```javascript
var travelAlerts = data.travel_alerts || [];
for (var tai = 0; tai < travelAlerts.length; tai++) {
    var ta = travelAlerts[tai];
    var taTitle = (ta.title || '').toLowerCase();
    var taDup = allTravel.some(function(html) { return html.toLowerCase().indexOf(taTitle.slice(0, 30)) >= 0; });
    if (taDup) continue;
```

The prefix stripping happens AFTER the dedup check at line 866:
```javascript
taLabel = taLabel.replace(/^(TODAY|In \d+d):\s*/i, '');
```

### Implementation
In `outputs/static/app.js`, replace lines 858-861 (the 4 lines starting with `var ta = travelAlerts[tai]`):

**Find:**
```javascript
                var ta = travelAlerts[tai];
                // Skip if already covered by trips, calendar events, or deadlines
                var taTitle = (ta.title || '').toLowerCase();
                var taDup = allTravel.some(function(html) { return html.toLowerCase().indexOf(taTitle.slice(0, 30)) >= 0; });
```

**Replace with:**
```javascript
                var ta = travelAlerts[tai];
                // Skip if already covered by trips, calendar events, or deadlines
                // Strip "TODAY: " / "In 2d: " prefix BEFORE dedup check (LANDING-FIX-1)
                var taTitle = (ta.title || '').toLowerCase().replace(/^(today|in \d+d):\s*/i, '');
                var taDup = allTravel.some(function(html) { return html.toLowerCase().indexOf(taTitle.slice(0, 30)) >= 0; });
```

### Key Constraints
- Only change the `taTitle` assignment line — nothing else in this loop
- The `taLabel` stripping at line 866 can stay as-is (it operates on a different variable)

### Verification
Reload dashboard. Travel card should show 2 items (Nice→Geneva, Geneva→Vienna) plus possibly the Oskolkov meeting alert (which will be fixed in Brief 2). No more duplicates.

---

## Fix 2: Hide raw "clickup_deadline:XXXX" snippets

### Problem
Expanding a Promised To Do item shows `clickup_deadline:86c94dgxh` — a raw internal reference meaningless to the Director.

### Current State
`app.js` line 2255-2266 in `renderDeadlineCompact()`:
```javascript
var snippetText = (dl.source_snippet || '').trim();
...
if (snippetText) html += '<div style="...">' + esc(snippetText) + '</div>';
```

### Implementation
In `outputs/static/app.js`, find the line in `renderDeadlineCompact`:

**Find:**
```javascript
    var snippetText = (dl.source_snippet || '').trim();
```

**Replace with:**
```javascript
    var snippetText = (dl.source_snippet || '').trim();
    // LANDING-FIX-1: Hide raw internal references (clickup IDs, bare source_type markers)
    if (/^clickup_deadline:/.test(snippetText) || snippetText.length < 20) snippetText = '';
```

### Key Constraints
- Only filter snippets that are clearly internal IDs, not legitimate short snippets
- The `< 20` threshold catches bare IDs while keeping real context

### Verification
Reload dashboard, expand first Promised To Do item. Should show triage buttons without the raw ID text.

---

## Fix 3: Soften "All clear" text in Critical card

### Problem
"No critical items. All clear." feels misleading on a day with active travel and meetings. The Director may think Baker checked everything — but `is_critical` is Director-managed.

### Current State
`app.js` line 902-903:
```javascript
} else {
    gridCritical.innerHTML = '<div class="grid-empty">No critical items. All clear.</div>';
}
```

### Implementation
**Find:**
```javascript
                gridCritical.innerHTML = '<div class="grid-empty">No critical items. All clear.</div>';
```

**Replace with:**
```javascript
                gridCritical.innerHTML = '<div class="grid-empty">No items flagged critical.</div>';
```

### Verification
Reload dashboard with no critical items. Text should say "No items flagged critical." instead of "All clear."

---

## Fix 4: Cache bust

### Implementation
In `outputs/static/index.html`:

**Find:**
```html
<script src="/static/app.js?v=92"></script>
```

**Replace with:**
```html
<script src="/static/app.js?v=93"></script>
```

---

## Files Modified
- `outputs/static/app.js` — 3 changes (dedup fix, snippet filter, critical text)
- `outputs/static/index.html` — cache bust v92→v93

## Do NOT Touch
- `outputs/dashboard.py` — backend changes are in Brief 2
- `outputs/static/style.css` — no CSS changes needed
- Any Python files

## Quality Checkpoints
1. Travel card shows 2-3 items (not 5)
2. No raw `clickup_deadline:` text visible when expanding Promised To Do
3. Critical card says "No items flagged critical." (not "All clear")
4. Cache bust is v=93 in index.html
5. Syntax check: open browser console, no JS errors
