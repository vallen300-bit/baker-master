# BRIEF: EXPANDABLE-CARDS-1 — Click-to-Expand on All Dashboard Cards

**Priority:** HIGH
**Assignee:** Code Brisen (Mac Mini)
**Estimated effort:** 2-3 hours
**Date:** 2026-03-25

---

## What the Director Wants

Every card on the dashboard landing page should be expandable — click to see details, click again to collapse. This applies to:

1. **Travel cards** — Show flight details (time, airline, terminal, seat, booking ref)
2. **Fires cards** — Show the alert body with full context
3. **Obligation cards** — Show description, source, due date details
4. **Meeting cards** — Show attendees, location, prep notes

The pattern already exists in `renderFireCompact()` (app.js:1841) — alerts with body text have a click-to-expand chevron. Extend this pattern to ALL card types.

---

## Fix 1: Travel Deadline Cards — Expandable with Flight Details

The travel deadlines come from the `deadlines` table. Flight details are in the `source_snippet` column.

### Backend (dashboard.py)

In the travel deadlines query (added by TRAVEL-HYGIENE-1 Fix 5), include `source_snippet`:

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

### Frontend (app.js)

Parse flight details from `source_snippet` and render in expandable detail panel:

```javascript
// Render travel deadline card with expandable details
var travelDeadlines = data.travel_deadlines || [];
for (var tdi = 0; tdi < travelDeadlines.length; tdi++) {
    var td = travelDeadlines[tdi];
    var dueLabel = fmtDeadlineDays(td.due_date);
    var snippet = td.source_snippet || '';
    var flightInfo = parseFlightInfo(snippet);
    var hasDetail = flightInfo !== '';
    var detailHtml = hasDetail
        ? '<div class="fire-detail" style="display:none;font-size:12px;color:var(--text2);padding:8px 18px 10px;border-top:1px solid var(--border-light);line-height:1.6;white-space:pre-wrap;">' +
          esc(flightInfo) + '</div>'
        : '';
    var clickAttr = hasDetail
        ? ' onclick="var n=this.querySelector(\'.fire-detail\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"'
        : '';
    var chevron = hasDetail ? ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>' : '';

    allTravel.push(
        '<div class="card card-compact"' + clickAttr + '><div class="card-header">' +
        '<span class="nav-dot amber" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(td.description) + chevron + '</span>' +
        '<span class="card-time" style="font-weight:600;">' + esc(dueLabel) + '</span>' +
        '</div>' + detailHtml + '</div>'
    );
}
```

Add a helper to extract key flight details from the raw source_snippet:

```javascript
function parseFlightInfo(snippet) {
    if (!snippet) return '';
    var lines = [];

    // Flight number + airline
    var flightMatch = snippet.match(/([A-Z]{2}\s?\d{2,4})\s+(.+?Airlines?|Austrian|Swiss|Lufthansa)/i);
    if (flightMatch) lines.push('Flight: ' + flightMatch[1] + ' ' + flightMatch[2]);

    // Departure time + city
    var depMatch = snippet.match(/(\d{2}[A-Z]{3}),?\s*(\d{2}:\d{2})\s+([\w\s,()]+?)(?:\s+Terminal\s*:\s*(\w+))?/);
    if (depMatch) lines.push('Departure: ' + depMatch[2] + ' — ' + depMatch[3].trim() + (depMatch[4] ? ' (T' + depMatch[4] + ')' : ''));

    // Arrival time + city — look for the second time pattern
    var times = snippet.match(/\d{2}[A-Z]{3},?\s*\d{2}:\d{2}/g);
    if (times && times.length >= 2) {
        var arrMatch = snippet.match(/\d{2}[A-Z]{3},?\s*(\d{2}:\d{2})\s+([\w\s,()]+?)(?:\s+Terminal\s*:\s*(\w+))?/g);
        if (arrMatch && arrMatch[1]) {
            var m2 = arrMatch[1].match(/(\d{2}:\d{2})\s+([\w\s,()]+?)(?:\s+Terminal\s*:\s*(\w+))?/);
            if (m2) lines.push('Arrival: ' + m2[1] + ' — ' + m2[2].trim() + (m2[3] ? ' (T' + m2[3] + ')' : ''));
        }
    }

    // Duration
    var durMatch = snippet.match(/(\d{2}h\s*\d{2}m)\s*\(([^)]+)\)/);
    if (durMatch) lines.push('Duration: ' + durMatch[1] + ' (' + durMatch[2] + ')');

    // Class
    var classMatch = snippet.match(/Class\s*:\s*(\w+(?:\s*\(\w\))?)/);
    if (classMatch) lines.push('Class: ' + classMatch[1]);

    // Seat
    var seatMatch = snippet.match(/Seat\s*:\s*(\w+)/);
    if (seatMatch) lines.push('Seat: ' + seatMatch[1]);

    // Booking ref
    var refMatch = snippet.match(/Booking ref\s*:\s*(\w+)/i) || snippet.match(/reference\s*:\s*(\w{5,})/i);
    if (refMatch) lines.push('Booking: ' + refMatch[1]);

    // If parsing failed, show first 200 chars of snippet as fallback
    if (lines.length === 0 && snippet.length > 20) {
        return snippet.substring(0, 200).replace(/\s+/g, ' ').trim();
    }

    return lines.join('\n');
}
```

**NOTE:** The regex parsing is best-effort. If it fails, fall back to showing the raw snippet (truncated). Don't let parsing failures hide the data.

---

## Fix 2: Fires Cards — Already Expandable (verify)

`renderFireCompact()` already supports click-to-expand if `alert.body` exists. Verify this works on the dashboard grid. The grid fires use the same function — should already work.

If any fires in the grid DON'T expand, it's because the alert has an empty body. No code change needed.

---

## Fix 3: Obligation Cards — Add Expandable Details

Obligations are rendered in the Obligations section. Check how they're currently rendered.

**Backend:** The obligations/proposed_actions already include `description`, `source_evidence`, and `reasoning`. Make sure these are in the API response.

**Frontend:** Apply the same expand/collapse pattern:
- Card header: title + due date (always visible)
- Detail panel (hidden by default): description, source evidence, reasoning
- Click header to toggle detail

---

## Fix 4: Meeting Cards — Add Expandable Details

Meetings already have `attendees`, `location`, `prep_notes` in the data.

**Frontend:** Same pattern:
- Card header: meeting title + time (always visible)
- Detail panel: attendees list, location, Baker's prep notes
- Click to toggle

---

## Pattern to Follow

All expandable cards should use the same CSS/HTML pattern from `renderFireCompact()`:

```javascript
// Standard expandable card pattern
var hasDetail = /* check if detail data exists */;
var clickAttr = hasDetail
    ? ' onclick="var n=this.querySelector(\'.fire-detail\');n.style.display=n.style.display===\'none\'?\'block\':\'none\'" style="cursor:pointer;"'
    : '';
var chevron = hasDetail
    ? ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span>'
    : '';
var detailHtml = hasDetail
    ? '<div class="fire-detail" style="display:none;font-size:12px;color:var(--text2);padding:6px 18px 10px;line-height:1.5;border-top:1px solid var(--border-light);white-space:pre-wrap;">'
      + esc(detailContent) + '</div>'
    : '';

return '<div class="card card-compact"' + clickAttr + '>' +
    '<div class="card-header">' +
    '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
    '<span class="card-title">' + esc(title) + chevron + '</span>' +
    '<span class="card-time">' + esc(timeLabel) + '</span>' +
    '</div>' + detailHtml + '</div>';
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/dashboard.py` | Include `source_snippet` in travel deadlines query |
| `outputs/static/app.js` | `parseFlightInfo()` helper + expandable travel cards + expandable obligation cards + expandable meeting cards. Bump cache version. |
| `outputs/static/index.html` | Bump cache version if needed |

## Testing

1. Click "Flight departure from Vienna to Geneva" → should expand to show: OS 155, 17:35 VIE T3, 19:10 GVA T1, Business, Seat 03D, Booking 822GP6
2. Click a fire card → should expand to show alert body
3. Click an obligation → should expand to show description/evidence
4. Click a meeting → should expand to show attendees/location/prep
5. Click again on any expanded card → collapses back

---

*Brief by AI Head — Session 37, 2026-03-25*
