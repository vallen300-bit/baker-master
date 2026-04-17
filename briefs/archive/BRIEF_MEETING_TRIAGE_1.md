# BRIEF: MEETING-TRIAGE-1 — Meeting Card Triage Buttons + Manual Input

## Context
The Meetings card on the landing page needs proper triage buttons (Confirmed/Declined/Prep me) and a "+" button for Director to manually add meetings. Currently the only meeting-specific triage button is "Cancel Meeting" which is too limited.

## Estimated time: ~2h
## Complexity: Low-Medium
## Prerequisites: None (all backend APIs exist)

---

## Feature 1: Replace Meeting Triage Buttons

### Problem
Meeting triage only has "Cancel Meeting" (red). Director needs Confirmed/Declined/Prep me buttons — same quality as the travel card triage.

### Current State
`outputs/static/app.js` line 2930-2932:
```javascript
    } else if (cardType === 'meeting') {
        html += '<button class="triage-pill" style="background:var(--red);color:#fff;border-color:var(--red);" onclick="event.stopPropagation();_landingCancelMeeting(' + itemId + ',this)">✕ Cancel Meeting</button>';
    }
```

`_landingCancelMeeting()` at line 3057 — dismisses calendar events by removing DOM, cancels detected meetings via `POST /api/detected-meetings/{id}/cancel`.

### Implementation

**File:** `outputs/static/app.js`

**Replace** the meeting section in `_landingTriageBar()` (lines 2930-2932) with:

```javascript
    } else if (cardType === 'meeting') {
        // MEETING-TRIAGE-1: Confirmed / Declined / Prep me
        html += '<button class="triage-pill" style="background:var(--green);color:#fff;border-color:var(--green);" onclick="event.stopPropagation();_meetingSetStatus(' + itemId + ',\'confirmed\',this)">✓ Confirmed</button>';
        html += '<button class="triage-pill" style="background:var(--red);color:#fff;border-color:var(--red);" onclick="event.stopPropagation();_meetingSetStatus(' + itemId + ',\'declined\',this)">✕ Declined</button>';
        html += '<button class="triage-pill" onclick="event.stopPropagation();_triageOpenBaker(\'Prepare me for this meeting: \\x22' + _t + '\\x22. Run dossiers on attendees, pull relevant emails and WhatsApp messages, summarize context. Context: ' + _c + '\')">📋 Prep me</button>';
    }
```

**Add** new function `_meetingSetStatus()` after `_landingCancelMeeting()` (after line 3069):

```javascript
function _meetingSetStatus(meetingId, status, btn) {
    var card = btn.closest('.card');
    var dot = card ? card.querySelector('.nav-dot') : null;

    if (status === 'declined') {
        // Calendar events (non-numeric IDs) — just dismiss from DOM
        if (String(meetingId).indexOf('cal-') === 0 || String(meetingId).indexOf('exchange-') === 0 || isNaN(Number(meetingId))) {
            if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
            _showToast('Meeting declined');
            return;
        }
        // Detected meetings — cancel via API
        bakerFetch('/api/detected-meetings/' + meetingId + '/cancel', { method: 'POST' }).then(function() {
            if (card) { card.style.opacity = '0.3'; setTimeout(function() { card.remove(); }, 500); }
            _showToast('Meeting declined');
        });
        return;
    }

    if (status === 'confirmed') {
        // Update dot to green immediately (live DOM update)
        if (dot) {
            dot.className = 'nav-dot green';
            dot.style.marginTop = '5px';
        }
        // Update status text
        var statusSpan = card ? card.querySelector('.card-body span[style*="color:var(--"]') : null;
        if (statusSpan) {
            statusSpan.textContent = 'Confirmed';
            statusSpan.style.color = 'var(--green)';
        }
        _showToast('Meeting confirmed');

        // For detected meetings, persist to DB
        if (!isNaN(Number(meetingId)) && String(meetingId).indexOf('cal-') !== 0 && String(meetingId).indexOf('exchange-') !== 0) {
            bakerFetch('/api/detected-meetings/' + meetingId + '/confirm', { method: 'POST' });
        }
        return;
    }
}
```

**Add** new API endpoint in `outputs/dashboard.py` — confirm a detected meeting:

First check no existing endpoint: `grep -n "detected-meetings.*confirm" dashboard.py` — should return nothing.

```python
@app.post("/api/detected-meetings/{meeting_id}/confirm", tags=["meetings"], dependencies=[Depends(verify_api_key)])
async def confirm_detected_meeting(meeting_id: int):
    """MEETING-TRIAGE-1: Confirm a detected meeting."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE detected_meetings SET status = 'confirmed', updated_at = NOW() WHERE id = %s", (meeting_id,))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
        return {"status": "confirmed", "id": meeting_id}
    except Exception as e:
        logger.error(f"POST /api/detected-meetings/{meeting_id}/confirm failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

Place this right after the existing `/api/detected-meetings/{meeting_id}/cancel` endpoint (around line 5798).

### Key Constraints
- **Confirmed** updates dot to green immediately (live DOM) + persists for detected meetings
- **Declined** removes card from DOM + cancels detected meetings via existing API
- **Calendar events** (Google/Exchange) have non-numeric IDs (`cal-...`, `exchange-...`) — Confirmed is DOM-only (no backend persistence needed, they refresh each load). Declined is DOM-only dismiss.
- **Prep me** opens Baker chat with full meeting prep prompt — no new backend needed
- **Keep existing common triage buttons** (Draft Email, Draft WA, Analyze, Summarize, Dossier, ClickUp, Delegate, Dismiss, Ask Baker) — only the meeting-specific section changes

---

## Feature 2: "+" Button for Manual Meeting Input

### Problem
Director wants to add meetings manually from the dashboard, same as the Critical card's "+" button.

### Current State
- Critical card has `<button onclick="_criticalQuickAdd()">+</button>` in HTML
- `_criticalQuickAdd()` at line 3101 — creates inline input, calls `POST /api/critical/add`
- `insert_detected_meeting()` at store_back.py line 4476 — stores meeting to `detected_meetings` table
- `detected_meetings` table has: `id, title, participant_names, meeting_date, meeting_time, location, status, source, source_ref, raw_text, created_at, updated_at, dismissed`

### Implementation

**File:** `outputs/static/app.js`

Find the Meetings card header rendering. Search for `gridMeetingsCount` — the header is built near line 1176. Add a "+" button next to the Meetings title, same pattern as Critical card.

In the HTML rendering where the Meetings header is built (the grid header section), add a "+" button:

```javascript
// Find where Meetings header is rendered and add the + button
// Pattern matches Critical card: <button onclick="_criticalQuickAdd()">+</button>
```

The Meetings header is in the static HTML (index.html line area around `gridMeetings`). Search `outputs/static/index.html` for `gridMeetings` and add a "+" button:

```html
<button onclick="_meetingQuickAdd()" title="Add meeting" style="...same style as critical + button...">+</button>
```

**Add** new function `_meetingQuickAdd()` after `_meetingSetStatus()`:

```javascript
function _meetingQuickAdd() {
    var grid = document.getElementById('gridMeetings');
    if (!grid) return;
    if (document.getElementById('meetingQuickInput')) return;
    var row = document.createElement('div');
    row.id = 'meetingQuickInput';
    row.style.cssText = 'display:flex;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border-light);';
    var input = document.createElement('input');
    input.style.cssText = 'flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;font-family:var(--font);';
    input.placeholder = 'e.g. Meeting with Pisani tomorrow 14:00';
    var addBtn = document.createElement('button');
    addBtn.className = 'triage-pill';
    addBtn.style.cssText = 'background:var(--blue);color:#fff;border-color:var(--blue);';
    addBtn.textContent = 'Add';
    addBtn.addEventListener('click', function() {
        var desc = input.value.trim();
        if (!desc) return;
        addBtn.disabled = true;
        addBtn.textContent = '...';
        bakerFetch('/api/meetings/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: desc }),
        }).then(function(r) { return r.json(); }).then(function(d) {
            if (d.error) { _showToast(d.error); }
            else { _showToast('Meeting added: ' + (d.title || desc).substring(0, 40)); loadMorningBrief(); }
            row.remove();
        }).catch(function() { addBtn.disabled = false; addBtn.textContent = 'Add'; });
    });
    input.addEventListener('keydown', function(e) { if (e.key === 'Enter') addBtn.click(); if (e.key === 'Escape') row.remove(); });
    row.appendChild(input);
    row.appendChild(addBtn);
    grid.insertBefore(row, grid.firstChild);
    input.focus();
}
```

**Add** new API endpoint in `outputs/dashboard.py`:

First verify no existing endpoint: `grep -n "/api/meetings/add" dashboard.py`

```python
@app.post("/api/meetings/add", tags=["meetings"], dependencies=[Depends(verify_api_key)])
async def add_meeting_quick(request: Request):
    """MEETING-TRIAGE-1: Quick-add meeting from dashboard. Uses Flash to parse natural language."""
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return {"error": "Meeting description required"}

        # Use Flash to parse meeting details from natural language
        from orchestrator.gemini_client import call_flash
        import json
        today = datetime.now().strftime('%Y-%m-%d')
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Parse this meeting description into structured data. Today is {today}.

Input: "{text}"

Return JSON only (no markdown):
{{
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD",
  "time": "HH:MM or null",
  "location": "place or null",
  "status": "confirmed"
}}

If no date is specified, assume today. If "tomorrow", use the next day."""}],
        )

        parsed = json.loads(resp.text.strip().strip('`').replace('json\n', ''))

        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        meeting_id = store.insert_detected_meeting(
            title=parsed.get("title", text[:100]),
            participant_names=parsed.get("participants", []),
            meeting_date=parsed.get("date"),
            meeting_time=parsed.get("time"),
            location=parsed.get("location"),
            status=parsed.get("status", "confirmed"),
            source="dashboard",
            raw_text=text,
        )

        return {
            "status": "added",
            "id": meeting_id,
            "title": parsed.get("title", text[:100]),
            "date": parsed.get("date"),
            "time": parsed.get("time"),
        }
    except json.JSONDecodeError:
        # Flash returned non-JSON — store as-is with minimal parsing
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        meeting_id = store.insert_detected_meeting(
            title=text[:100],
            status="confirmed",
            source="dashboard",
            raw_text=text,
        )
        return {"status": "added", "id": meeting_id, "title": text[:100]}
    except Exception as e:
        logger.error(f"POST /api/meetings/add failed: {e}")
        return {"error": str(e)}
```

### Key Constraints
- **Flash call for parsing** — one cheap LLM call to extract date/time/participants from natural language. Uses existing `call_flash()` pattern. Returns `.text`, parse as JSON.
- **Fallback** — if Flash returns garbage JSON, store with title only (no crash)
- **Source = "dashboard"** — distinguishes manual entries from auto-detected
- **Status = "confirmed"** — Director-added meetings are confirmed by default
- **`insert_detected_meeting()` handles dedup** via `source_ref` — but manual entries have no source_ref, so no dedup concern
- **LLM three-way match verified**: `call_flash(messages=[...])` returns `GeminiResponse`, extract `.text`

---

## Feature 3: "+" Button in Meetings Card Header

### Problem
The "+" button needs to appear in the Meetings card header, same as Critical card.

### Implementation

**File:** `outputs/static/index.html`

Find the Meetings grid header. Search for `gridMeetings` or `Meetings` heading. Add a "+" button matching the Critical card pattern.

The Critical card header pattern (search for `gridCritical` in index.html to find it):
```html
<button onclick="_criticalQuickAdd()" title="Add critical item" ...>+</button>
```

Add identical button next to Meetings header:
```html
<button onclick="_meetingQuickAdd()" title="Add meeting" style="background:none;border:1px solid var(--border);border-radius:50%;width:22px;height:22px;font-size:14px;cursor:pointer;color:var(--text2);display:inline-flex;align-items:center;justify-content:center;margin-left:8px;vertical-align:middle;">+</button>
```

### Key Constraints
- Match exact style of Critical card's "+" button
- Place next to the "Meetings" label, before the count badge

---

## Files Modified
- `outputs/static/app.js` — Replace meeting triage buttons + add `_meetingSetStatus()` + add `_meetingQuickAdd()`
- `outputs/static/index.html` — Add "+" button to Meetings card header
- `outputs/dashboard.py` — Add `POST /api/detected-meetings/{id}/confirm` + `POST /api/meetings/add`

## Do NOT Touch
- `memory/store_back.py` — `insert_detected_meeting()` already works perfectly
- `triggers/calendar_trigger.py` — Google Calendar poller unchanged
- `triggers/exchange_calendar_poller.py` — Exchange calendar poller unchanged

## Quality Checkpoints
1. Syntax check: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
2. Bump cache bust: `app.js?v=102` in `outputs/static/index.html` (currently v=101)
3. Verify "+" button appears next to Meetings header
4. Click "+" → type "Meeting with Pisani tomorrow 14:00" → should appear in card
5. Expand Minor Hotels meeting → verify Confirmed/Declined/Prep me buttons visible
6. Click Confirmed → dot turns green immediately
7. Click Declined on a detected meeting → card disappears
8. Click Prep me → Baker chat opens with meeting prep prompt
9. Verify existing buttons still work (Draft Email, Draft WA, Analyze, Dismiss etc.)
10. Check no duplicate `/api/meetings/add` or `/api/detected-meetings/confirm` endpoints: `grep -n "meetings/add\|meetings.*confirm" dashboard.py`
11. Mobile: check triage pills wrap properly on narrow screen

## Verification SQL
```sql
-- Check manually added meetings
SELECT id, title, meeting_date, meeting_time, status, source
FROM detected_meetings
WHERE source = 'dashboard'
ORDER BY created_at DESC LIMIT 5;

-- Check confirmed meetings
SELECT id, title, status, updated_at
FROM detected_meetings
WHERE status = 'confirmed'
ORDER BY updated_at DESC LIMIT 5;
```
