# BRIEF: LANDING_TRIAGE_FIXES_1 — Fix card classification & standardize triage across all landing page sections

## Context
Director reported multiple issues on the landing page 2x2 grid:
1. "Flight from Geneva to Nice" appears in BOTH Travel and Promised To Do cards (duplicate)
2. Promised To Do section should only show commitments/promises, not all deadlines — and should NOT sort by due date
3. Critical section triage is missing "Mark Done" button
4. Calendar meetings have NO triage at all; travel cards have a reduced triage set. All cards should have the same full triage bar.

## Estimated time: ~1.5h
## Complexity: Low-Medium
## Prerequisites: None

---

## Fix 1: Exclude travel items from "Promised To Do" query

### Problem
The "Promised To Do" backend query (`dashboard.py:2183-2193`) fetches ALL active non-critical deadlines within 7 days. It does not exclude travel-related items. The Travel section (`dashboard.py:2429-2437`) separately fetches deadlines matching flight/departure/travel/airport keywords. Result: items like "Flight from Geneva to Nice" (deadline #1327) appear in both cards.

### Current State
File: `outputs/dashboard.py`, lines 2182-2193:
```python
# Deadlines this week — exclude critical items (shown in Critical section)
cur.execute("""
    SELECT id, description, due_date, source_type, confidence,
           priority, status, created_at,
           LEFT(source_snippet, 500) AS source_snippet
    FROM deadlines
    WHERE status = 'active'
      AND (is_critical IS NOT TRUE)
      AND due_date >= CURRENT_DATE
      AND due_date <= CURRENT_DATE + INTERVAL '7 days'
    ORDER BY due_date ASC LIMIT 10
""")
```

### Implementation
In `outputs/dashboard.py`, replace the deadlines query (lines ~2183-2193) with:

```python
# Deadlines this week — exclude critical (shown in Critical) and travel (shown in Travel)
cur.execute("""
    SELECT id, description, due_date, source_type, confidence,
           priority, status, created_at,
           LEFT(source_snippet, 500) AS source_snippet
    FROM deadlines
    WHERE status = 'active'
      AND (is_critical IS NOT TRUE)
      AND due_date >= CURRENT_DATE
      AND due_date <= CURRENT_DATE + INTERVAL '7 days'
      AND NOT (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
               OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
               OR description ILIKE '%%boarding%%' OR description ILIKE '%%check-in%%')
    ORDER BY priority DESC, created_at DESC LIMIT 10
""")
```

Note TWO changes:
1. Added `AND NOT (...)` clause with travel keywords (matching the travel deadlines query at line 2434-2435, plus `boarding` and `check-in`)
2. Changed `ORDER BY due_date ASC` → `ORDER BY priority DESC, created_at DESC` — Director wants promises sorted by importance/recency, NOT by deadline date

### Key Constraints
- The `%%` is required because this is inside a Python `cur.execute()` with `%` escaping for psycopg2
- Must match or be a superset of the travel keywords used at line 2434-2435
- LIMIT 10 stays

### Verification
```sql
-- Should NOT return any flight/travel items:
SELECT id, description FROM deadlines
WHERE status = 'active' AND (is_critical IS NOT TRUE)
  AND due_date >= CURRENT_DATE AND due_date <= CURRENT_DATE + INTERVAL '7 days'
  AND NOT (description ILIKE '%flight%' OR description ILIKE '%departure%'
           OR description ILIKE '%travel%' OR description ILIKE '%airport%'
           OR description ILIKE '%boarding%' OR description ILIKE '%check-in%')
ORDER BY priority DESC, created_at DESC LIMIT 10;
```

---

## Fix 2: Add "Mark Done" to Critical section triage

### Problem
When expanding a Critical item, the triage bar only shows "Not Critical" as the final button. There is no "Mark Done" button, so the Director can't complete critical items from the triage bar.

### Current State
File: `outputs/static/app.js`, lines 2541-2548 in `_landingTriageBar()`:
```javascript
// Last button varies by card type
if (cardType === 'critical') {
    html += '<button class="triage-pill" onclick="event.stopPropagation();_landingMarkNotCritical(' + itemId + ',this)">⚡ Not Critical</button>';
} else if (cardType === 'deadline') {
    html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
} else if (cardType === 'meeting') {
    // ...
}
```

### Implementation
In `outputs/static/app.js`, replace the `if (cardType === 'critical')` block (line ~2542-2543) with TWO buttons — Mark Done AND Not Critical:

```javascript
if (cardType === 'critical') {
    html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_landingMarkNotCritical(' + itemId + ',this)">⚡ Not Critical</button>';
}
```

The `_landingMarkDone` function already exists (line 2576) and calls `/api/deadlines/{id}/complete`. It works for any deadline — critical items are just deadlines with `is_critical=TRUE`.

### Key Constraints
- Keep "Not Critical" button — Director still needs it to demote items
- "Mark Done" should appear FIRST (green, more prominent) before "Not Critical"
- `_landingMarkDone` already handles the API call and card removal animation

### Verification
1. Load dashboard, expand a Critical item
2. Should see both "✓ Mark Done" (green) and "⚡ Not Critical" buttons at the end of the triage bar
3. Clicking "Mark Done" should fade and remove the card

---

## Fix 3: Add full triage bar to calendar meeting cards

### Problem
Calendar meeting cards (`renderMeetingCard`, line 2102) expand to show prep notes only — NO triage buttons at all. Detected meeting cards (`renderDetectedMeetingCard`, line 2140) DO have the full triage bar. The Director wants all cards to have the same triage.

### Current State
File: `outputs/static/app.js`, lines 2102-2137 — `renderMeetingCard()`:
- Uses a simple onclick toggle for `.prep-notes` div
- Shows attendees, location, prep notes
- NO `_landingTriageBar()` call
- NOT a drag-card (no `drag-card` class, no `data-item-id`)

### Implementation
Replace `renderMeetingCard()` entirely (lines 2102-2137) with a version that:
1. Uses `_toggleTriageCard(this)` for expand/collapse (like all other card types)
2. Includes `_landingTriageBar()` with cardType `'meeting'`
3. Uses a stable ID (calendar event ID or fallback to title hash)

```javascript
function renderMeetingCard(m) {
    var startTime = '';
    try {
        var d = new Date(m.start);
        startTime = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch(e) { startTime = m.start || ''; }
    var attendeeStr = (m.attendees || []).slice(0, 3).map(esc).join(', ');
    if ((m.attendees || []).length > 3) attendeeStr += ' +' + ((m.attendees || []).length - 3);
    var dotClass = m.prepped ? 'green' : 'amber';
    var statusText = m.prepped ? 'Prepped' : 'Pending';

    // Build detail content
    var detailLines = [];
    if (m.location && m.location.trim()) detailLines.push('Location: ' + m.location.trim());
    if ((m.attendees || []).length > 0) detailLines.push('Attendees: ' + (m.attendees || []).join(', '));
    if (m.prep_notes && m.prep_notes.trim()) detailLines.push('\n' + m.prep_notes.trim());
    var detailContent = detailLines.join('\n');

    // Use event ID or generate one from title
    var meetingId = m.id || m.event_id || ('cal-' + (m.title || '').replace(/\s+/g, '-').substring(0, 30));
    var aid = String(meetingId);

    var html = '<div class="card card-compact" data-item-id="' + esc(aid) + '" data-item-type="meeting" style="cursor:pointer;" onclick="_toggleTriageCard(this)"><div class="card-header">' +
        '<span class="nav-dot ' + dotClass + '" style="margin-top:5px;"></span>' +
        '<span class="card-title">' + esc(m.title || '') + ' <span style="font-size:10px;color:var(--text3);margin-left:4px;">&#9662;</span></span>' +
        '<span class="card-time">' + esc(startTime) + '</span>' +
        '</div>' +
        '<div class="card-body" style="font-size:11px;color:var(--text3);padding:2px 0 4px 18px;">' +
        (attendeeStr ? esc(attendeeStr) + ' &middot; ' : '') +
        '<span style="color:var(--' + (m.prepped ? 'green' : 'amber') + ');">' + esc(statusText) + '</span>' +
        '</div>';

    // Expandable detail + triage
    html += '<div class="triage-detail" style="display:none;">';
    if (detailContent) {
        html += '<div style="font-size:12px;color:var(--text2);padding:8px 18px 12px;line-height:1.5;white-space:pre-wrap;border-top:1px solid var(--border-light);">' + esc(detailContent).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>') + '</div>';
    }
    html += _landingTriageBar(aid, m.title || '', attendeeStr, 'meeting', meetingId);
    html += '</div></div>';
    return html;
}
```

### Key Constraints
- Calendar events don't have numeric IDs like deadlines. Use `m.id || m.event_id` or generate a slug from title.
- The `'meeting'` cardType in `_landingTriageBar` already adds "Cancel Meeting" as the final button (line 2546-2547). Keep that.
- Prep notes still appear in the detail section above the triage bar.
- The `_landingCancelMeeting` function (line 2584) calls `/api/detected-meetings/{id}/cancel`. Calendar events may not have this endpoint. The Cancel button may not work for calendar events — acceptable for now (most meetings in the grid are detected meetings anyway). Worst case: button shows a toast error.

### Verification
1. Load dashboard, check Meetings section
2. Calendar meetings should now show the ▼ chevron
3. Clicking should expand to show prep notes + full triage bar (Draft Email, Draft WA, Analyze, etc.)
4. Detected meetings should continue working as before

---

## Fix 4: Standardize travel card triage to match all other cards

### Problem
Travel cards use a REDUCED triage set (Ask Baker, Confirm Booking, Book Accommodation, Dismiss). The Director wants ALL cards to have the SAME triage bar everywhere.

### Current State
File: `outputs/static/app.js`, lines 2520-2526 in `_landingTriageBar()`:
```javascript
if (cardType === 'travel') {
    // Reduced set for travel
    var _tt = escAttr(title);
    html += '<button ...>💬 Ask Baker</button>';
    html += '<button ...>✅ Confirm Booking</button>';
    html += '<button ...>🏨 Book Accommodation</button>';
    html += '<button ...>✕ Dismiss</button>';
}
```

### Implementation
Remove the special `if (cardType === 'travel')` branch entirely. Let travel cards fall through to the `else` block (lines 2527+) which has the full 10-button triage set.

Replace lines 2520-2549 (the entire if/else chain for cardType) with:

```javascript
    // Full triage actions for ALL card types (unified)
    var _t = escAttr(title);
    var _c = escAttr(ctx);
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Draft an email regarding: \\x22' + _t + '\\x22. Context: ' + _c + '\')">✉ Draft Email</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Draft a WhatsApp message regarding: \\x22' + _t + '\\x22. Context: ' + _c + '\')">💬 Draft WA</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Analyze this situation in depth: \\x22' + _t + '\\x22. Context: ' + _c + '\')">🔍 Analyze</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Give me a 3-line summary of: \\x22' + _t + '\\x22. Context: ' + _c + '\')">📋 Summarize</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Run a comprehensive dossier on the key people in: \\x22' + _t + '\\x22\')">🗂 Dossier</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageCreateClickUp(' + aid + ',\'' + _t + '\',\'' + _c + '\')">↗ ClickUp</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Draft an email delegating this task: \\x22' + _t + '\\x22\')">👤 Delegate</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_landingDismiss(\'' + cardType + '\',' + itemId + ',this)">✕ Dismiss</button>';
    html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Regarding: \\x22' + _t + '\\x22. ' + _c + '. What should I know?\')">💬 Ask Baker</button>';

    // Context-specific final buttons
    if (cardType === 'critical') {
        html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
        html += '<button class="triage-pill" onclick="event.stopPropagation();_landingMarkNotCritical(' + itemId + ',this)">⚡ Not Critical</button>';
    } else if (cardType === 'deadline') {
        html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_landingMarkDone(' + itemId + ',this)">✓ Mark Done</button>';
    } else if (cardType === 'meeting') {
        html += '<button class="triage-pill" style="background:var(--red);color:#fff;border-color:var(--red);" onclick="event.stopPropagation();_landingCancelMeeting(' + itemId + ',this)">✕ Cancel Meeting</button>';
    }
```

This gives ALL card types (travel, critical, deadline, meeting) the same base triage set of 9 buttons, plus context-appropriate final button(s).

### Key Constraints
- The `escAttr()` function must be used for onclick attributes (XSS prevention)
- The `\\x22` is the escaped quote character used in Baker prompts — keep it
- For travel cards, `_landingDismiss('travel', itemId, this)` will call the generic dismiss. The travel endpoint may not exist. Check: `_landingDismiss` at line 2554 maps `cardType` to endpoint. Currently no 'travel' case — it falls to the `else` which uses `/api/alerts/{id}/dismiss`. This may fail for travel deadlines. Add a `'travel'` case to `_landingDismiss` that uses `/api/deadlines/{id}/dismiss`.

### Additional: Fix _landingDismiss for travel cards
In `_landingDismiss()` (line 2554), add a travel case:

```javascript
function _landingDismiss(cardType, itemId, btn) {
    var card = btn.closest('.card');
    var endpoint = '';
    if (cardType === 'critical') endpoint = '/api/critical/' + itemId + '/done';
    else if (cardType === 'deadline') endpoint = '/api/deadlines/' + itemId + '/dismiss';
    else if (cardType === 'travel') endpoint = '/api/deadlines/' + itemId + '/dismiss';
    else if (cardType === 'meeting') endpoint = '/api/alerts/' + itemId + '/dismiss';
    else endpoint = '/api/alerts/' + itemId + '/dismiss';
    if (!endpoint) return;
    bakerFetch(endpoint, { method: 'POST' }).then(function() {
        if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
        _showToast('Dismissed');
    });
}
```

### Verification
1. Expand a travel card → should see full 9-button triage (not just Ask Baker / Confirm / Accommodate)
2. Expand a critical card → should see full 9 buttons + Mark Done + Not Critical
3. Expand a deadline card → should see full 9 buttons + Mark Done
4. Expand a meeting card → should see full 9 buttons + Cancel Meeting
5. Dismiss on a travel card should not error

---

## Fix 5: Cache bust

### Implementation
In `outputs/static/index.html`:
- Line 16: change `style.css?v=56` → `style.css?v=57`
- Line 445: change `app.js?v=81` → `app.js?v=82`

---

## Files Modified
- `outputs/dashboard.py` — Promised To Do query: add travel exclusion + change sort order
- `outputs/static/app.js` — 4 changes: (a) `_landingTriageBar` unified, (b) Mark Done for critical, (c) `renderMeetingCard` with triage, (d) `_landingDismiss` travel case
- `outputs/static/index.html` — cache bump v57/v82

## Do NOT Touch
- `outputs/dashboard.py` travel deadlines query (lines 2425-2441) — working correctly
- `orchestrator/deadline_manager.py` — extraction logic is out of scope
- `models/deadlines.py` — no schema changes needed
- `outputs/static/style.css` — no CSS changes

## Quality Checkpoints
1. Syntax check: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
2. Load dashboard landing page — "Flight from Geneva to Nice" should NOT appear in Promised To Do
3. Expand Critical item → both "Mark Done" and "Not Critical" buttons visible
4. Expand Calendar meeting → full triage bar visible (same buttons as deadline cards)
5. Expand Travel card → full triage bar (not the old 3-button reduced set)
6. Click "Mark Done" on a Critical item → card fades, toast shows "Marked as done ✓"
7. Verify cache bust: hard-reload, check Network tab for `app.js?v=82` and `style.css?v=57`

## Verification SQL
```sql
-- Confirm "Flight from Geneva to Nice" excluded from Promised but included in Travel:
SELECT id, description, 'TRAVEL' AS section FROM deadlines
WHERE status='active' AND due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
  AND (description ILIKE '%flight%' OR description ILIKE '%departure%')
LIMIT 5;

-- Confirm Promised To Do no longer has travel items:
SELECT id, description FROM deadlines
WHERE status='active' AND (is_critical IS NOT TRUE)
  AND due_date >= CURRENT_DATE AND due_date <= CURRENT_DATE + INTERVAL '7 days'
  AND NOT (description ILIKE '%flight%' OR description ILIKE '%departure%'
           OR description ILIKE '%travel%' OR description ILIKE '%airport%'
           OR description ILIKE '%boarding%' OR description ILIKE '%check-in%')
ORDER BY priority DESC, created_at DESC LIMIT 10;
```
