# BRIEF: ClickUp Full Integration + Google Calendar + Ideas Capture + Dropbox Expansion

**Priority:** High — four connected improvements to Baker's operational capabilities
**Ticket:** CLICKUP-CALENDAR-IDEAS-1

---

## Part 1: ClickUp Task Creation Dropdown

### Problem
When triaging an alert and clicking "ClickUp", Baker creates the task in the BAKER catch-all space (901510186446). The task is orphaned — disconnected from the actual project.

### Fix

#### Change 1A: Fetch real ClickUp structure for dropdown
**File:** `outputs/dashboard.py`

New endpoint that returns the full ClickUp structure for a picker:

```python
@app.get("/api/clickup/structure", dependencies=[Depends(verify_api_key)])
async def get_clickup_structure():
    """Return workspaces → spaces → lists for task creation dropdown."""
    from clickup_client import ClickUpClient
    client = ClickUpClient()
    structure = []
    for ws_id in client.workspace_ids:
        spaces = client.get_spaces(ws_id)
        for space in spaces:
            lists = client.get_lists(space["id"])
            for lst in lists:
                structure.append({
                    "workspace_id": ws_id,
                    "space_name": space["name"],
                    "list_id": lst["id"],
                    "list_name": lst["name"],
                    "full_path": f"{space['name']} / {lst['name']}"
                })
    return {"lists": structure}
```

#### Change 1B: Frontend dropdown in triage
**File:** `outputs/static/app.js`

Replace the current `_triageCreateClickUp()` function. Instead of immediately creating in BAKER space:

1. Fetch `/api/clickup/structure` (cache it — structure doesn't change often)
2. Show a dropdown modal with the list of `full_path` options
3. User picks the list → create task in that list

```javascript
async function _triageCreateClickUp(alertId, title, context) {
    // Show dropdown with real ClickUp lists
    var lists = await _getClickUpLists(); // cached fetch
    var modal = _createListPickerModal(lists, function(selectedList) {
        // Create task in the selected list
        bakerFetch('/api/clickup/create-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                list_id: selectedList.list_id,
                name: title,
                description: context,
                alert_id: alertId
            })
        }).then(function(r) {
            if (r.ok) _showToast('Task created in ' + selectedList.full_path);
        });
    });
}
```

#### Change 1C: Relax write guard
**File:** `clickup_client.py`

Change `_check_write_allowed()` to allow **create-only** operations across all 6 workspaces. Keep the guard for delete/move operations.

```python
def _check_write_allowed(self, operation: str, list_id: str = None):
    """Allow task creation in any workspace. Block destructive operations outside BAKER space."""
    SAFE_OPERATIONS = {'create_task', 'post_comment'}
    if operation in SAFE_OPERATIONS:
        return True  # Create anywhere
    # Destructive operations: BAKER space only
    if not self._is_baker_space(list_id):
        raise PermissionError(f"Write operation '{operation}' only allowed in BAKER space")
    return True
```

#### Change 1D: New create-task endpoint
**File:** `outputs/dashboard.py`

```python
@app.post("/api/clickup/create-task", dependencies=[Depends(verify_api_key)])
async def create_clickup_task(request: Request):
    body = await request.json()
    list_id = body.get("list_id")
    name = body.get("name")
    description = body.get("description", "")
    # ... create task via ClickUp API in the specified list
```

---

## Part 2: ClickUp Document Ingestion

### Problem
Baker polls ClickUp tasks but ignores file attachments on those tasks. Contracts, spec sheets, and site photos attached to ClickUp tasks are invisible to Baker.

### Fix

#### Change 2A: Pull attachments during ClickUp poll
**File:** `triggers/clickup_trigger.py`

After processing each task, check for attachments:

```python
# Inside the task processing loop, after storing task data:
try:
    attachments = client.get_task_attachments(task_id)
    for att in attachments:
        if att.get("url") and att.get("title"):
            # Queue for document pipeline
            _queue_clickup_attachment(
                task_id=task_id,
                task_name=task_name,
                attachment_url=att["url"],
                filename=att["title"],
                matter=matter_slug,
            )
except Exception as e:
    logger.debug(f"ClickUp attachment fetch failed for {task_id}: {e}")
```

#### Change 2B: ClickUp attachment API method
**File:** `clickup_client.py`

```python
def get_task_attachments(self, task_id: str) -> list:
    """Fetch attachments for a task. Returns list of {url, title, extension}."""
    resp = self._get(f"/task/{task_id}/attachment")  # ClickUp API v2
    return resp.get("attachments", [])
```

#### Change 2C: Download + pipeline
**File:** `triggers/clickup_trigger.py` or `tools/document_pipeline.py`

Download each attachment, run through the existing classify → extract pipeline:

```python
def _queue_clickup_attachment(task_id, task_name, attachment_url, filename, matter):
    """Download ClickUp attachment and feed through document pipeline."""
    from tools.document_pipeline import process_document
    import httpx

    resp = httpx.get(attachment_url, timeout=30)
    if resp.status_code != 200:
        return

    process_document(
        content=resp.content,
        filename=filename,
        source="clickup",
        source_id=f"clickup:{task_id}:{filename}",
        matter=matter,
        metadata={"clickup_task_id": task_id, "clickup_task_name": task_name}
    )
```

Documents appear in the Documents section with `source = 'clickup'` filter.

---

## Part 3: Google Calendar API Integration

### Problem
Baker has no calendar access. Meetings like "Sandra confirmed 10:30 Monday" are invisible unless manually stored. Calendar integrations (Zoom invites, meeting confirmations) create events automatically — Baker should read them.

### Fix

#### Change 3A: Add calendar scope to Gmail OAuth
**File:** `config/gmail_credentials.json` / OAuth consent

The existing Gmail OAuth token needs the additional scope:
```
https://www.googleapis.com/auth/calendar.readonly
```

This requires a one-time re-authorization (browser consent screen on Render or locally, then upload the new token).

#### Change 3B: Calendar trigger
**File:** `triggers/calendar_trigger.py` (new file)

```python
"""Poll Google Calendar every 5 minutes for upcoming events."""

def poll_calendar():
    """Fetch events from now to +7 days. Store new/changed events."""
    from googleapiclient.discovery import build
    service = build('calendar', 'v3', credentials=get_credentials())

    now = datetime.utcnow().isoformat() + 'Z'
    week_later = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'

    events = service.events().list(
        calendarId='primary',
        timeMin=now,
        timeMax=week_later,
        singleEvents=True,
        orderBy='startTime',
        maxResults=50,
    ).execute()

    for event in events.get('items', []):
        _store_calendar_event(event)
```

#### Change 3C: Calendar events table
```sql
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,              -- Google Calendar event ID
    title TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location TEXT,
    description TEXT,
    attendees JSONB,                  -- [{email, name, status}]
    conference_url TEXT,              -- Zoom/Meet link
    organizer TEXT,
    status TEXT DEFAULT 'confirmed',  -- confirmed, tentative, cancelled
    source TEXT DEFAULT 'google',     -- google, outlook (future)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cal_start ON calendar_events(start_time);
```

#### Change 3D: Dashboard integration
- Meetings card on landing page pulls from BOTH `meeting_transcripts` (past) AND `calendar_events` (future)
- Baker uses calendar for meeting prep alerts (existing `calendar_prep` job gets real data instead of guessing)

#### Change 3E: Register in scheduler
**File:** `triggers/embedded_scheduler.py`

```python
scheduler.add_job(
    poll_calendar, IntervalTrigger(minutes=5),
    id="calendar_poll", name="Google Calendar poll",
    coalesce=True, max_instances=1, replace_existing=True,
)
```

#### Pre-requisite
Re-authorize Google OAuth with calendar scope. This requires browser access — either:
- Run locally with `python scripts/extract_gmail.py --reauth` (adds calendar scope)
- Or generate new token and upload to Render as env var / secret file

---

## Part 4: Ideas Capture + Sidebar Section

### Problem
The Director captures ideas via Slack/WhatsApp ("Idea: nvidia proposal..."). These get buried in the message stream with no dedicated place to find and act on them.

### Fix

#### Change 4A: Ideas table
**File:** `outputs/dashboard.py` (startup migration)

```sql
CREATE TABLE IF NOT EXISTS ideas (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'slack',       -- slack, whatsapp, scan
    status TEXT DEFAULT 'new',         -- new, developing, actioned, dismissed
    matter TEXT,                       -- auto-detected project link
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
```

#### Change 4B: Detect "Idea:" prefix across all channels

**File:** `triggers/slack_trigger.py` — in Director message handling:
```python
# Before intent classification, check for idea capture
if clean_text.lower().startswith('idea:') or clean_text.lower().startswith('idea -'):
    _store_idea(clean_text, source='slack')
    _post_and_store_reply(client, channel_id, thread_ts, "Idea captured. You'll find it in the Ideas section.")
    return
```

**File:** `triggers/waha_webhook.py` — same pattern in Director message handling:
```python
if combined_body.lower().startswith('idea:'):
    _store_idea(combined_body, source='whatsapp')
    _wa_reply("Idea captured. You'll find it in the Ideas section.")
    return
```

**File:** `outputs/dashboard.py` — in `scan_chat()`, detect before intent classification:
```python
if question.lower().startswith('idea:'):
    _store_idea(question, source='scan')
    yield f"data: {json.dumps({'token': 'Idea captured. You can find it in the Ideas section.'})}\n\n"
    yield "data: [DONE]\n\n"
    return
```

#### Change 4C: Store function
```python
def _store_idea(text: str, source: str = 'scan'):
    """Store an idea. Strip the 'Idea:' prefix."""
    import re
    content = re.sub(r'^idea[:\-\s]+', '', text, flags=re.IGNORECASE).strip()
    if not content:
        return
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ideas (content, source) VALUES (%s, %s)
            """, (content, source))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Idea store failed: {e}")
```

#### Change 4D: API endpoints
**File:** `outputs/dashboard.py`

```python
@app.get("/api/ideas", dependencies=[Depends(verify_api_key)])
async def list_ideas():
    """List ideas, newest first. Filter by status."""
    # Query ideas table WHERE status != 'dismissed'
    # Return [{id, content, source, status, matter, created_at}]

@app.patch("/api/ideas/{idea_id}", dependencies=[Depends(verify_api_key)])
async def triage_idea(idea_id: int, request: Request):
    """Triage: update status (developing, actioned, dismissed)."""
    # Update status + updated_at
```

#### Change 4E: Sidebar section
**File:** `outputs/static/index.html`

Add IDEAS as a 5th collapsible section, after PEOPLE:

```html
<!-- IDEAS section (expandable) -->
<div class="nav-section-header" id="navIdeasHeader" data-section="ideas">
    <span class="nav-section-arrow">&#9656;</span>
    <span class="nav-section-label">Ideas</span>
    <span class="nav-count" id="ideasCount"></span>
</div>
<div class="nav-sub" id="ideasSubList" style="display:none;"></div>
```

Same teal color as other sections. When expanded, shows recent ideas. Click one → right panel shows the idea with triage actions:
- **Develop** → pre-fills Ask Baker: "Develop this idea further: [content]"
- **Create ClickUp Task** → uses the new dropdown picker (Part 1)
- **Dismiss** → hides it

#### Change 4F: Ideas view
**File:** `outputs/static/index.html`

```html
<div class="view" id="viewIdeas">
    <div class="section-label">Ideas</div>
    <div id="ideasContent"></div>
</div>
```

**File:** `outputs/static/app.js`

Add `loadIdeasTab()`, `loadIdeasSidebar()`, triage handlers. Same card pattern as People issues — each idea is a card with triage buttons.

---

## Part 5: Dropbox Watch Path Expansion

### Problem
Baker only watches `/Baker-Feed/` in Dropbox. Documents filed properly in `Baker-Project/01_Projects/Hagenauer/` are invisible unless manually copied to Baker-Feed. This leads to missed documents and duplicates.

### Fix

#### Change 5A: Expand watch path
**File:** Render environment variable

Change:
```
DROPBOX_WATCH_PATH=/Baker-Feed
```
To:
```
DROPBOX_WATCH_PATH=/Baker-Feed,/Baker-Project
```

#### Change 5B: Update trigger to handle multiple paths
**File:** `triggers/dropbox_trigger.py`

```python
watch_paths = config.dropbox.watch_path.split(",")
for path in watch_paths:
    path = path.strip()
    _poll_folder(path)
```

#### Change 5C: Auto-detect matter from folder path
**File:** `triggers/dropbox_trigger.py`

When ingesting from `Baker-Project`, extract the matter from the folder path:

```python
def _detect_matter_from_path(path: str) -> str:
    """Extract matter slug from Baker-Project folder structure."""
    # /Baker-Project/01_Projects/Hagenauer/Media/article.pdf → "hagenauer"
    parts = path.lower().split('/')
    project_folders = ['hagenauer', 'kempinski', 'morv', 'baden-baden', 'cap-ferrat', 'alpengo']
    for part in parts:
        for proj in project_folders:
            if proj in part:
                return proj
    return None
```

#### Change 5D: Content-hash dedup (from BRIEF_DOCUMENT_DEDUP_1)
The dedup brief (already written) handles the case where the same file exists in both Baker-Feed and Baker-Project. SHA-256 hash check prevents double ingestion.

**IMPORTANT:** The dedup brief (BRIEF_DOCUMENT_DEDUP_1.md) MUST be implemented before or alongside this change. Without dedup, expanding the watch path will create duplicates from files that exist in both locations.

---

## Part 6: ClickUp as Calendar Enforcer

### Problem
Baker reads ClickUp due dates but treats them separately from its own deadline system. There's no proactive enforcement — overdue ClickUp tasks don't generate alerts unless they happen to match a Baker deadline.

### Fix

#### Change 6A: Sync ClickUp due dates to Baker deadlines
**File:** `triggers/clickup_trigger.py`

During the existing ClickUp poll, for any task with a due date:

```python
if task.get('due_date'):
    due_dt = datetime.fromtimestamp(int(task['due_date']) / 1000, tz=timezone.utc)
    _sync_clickup_deadline(
        task_id=task['id'],
        task_name=task['name'],
        due_date=due_dt,
        list_name=list_name,
        space_name=space_name,
    )
```

```python
def _sync_clickup_deadline(task_id, task_name, due_date, list_name, space_name):
    """Upsert a Baker deadline from a ClickUp task due date."""
    store = _get_store()
    source_id = f"clickup_deadline:{task_id}"
    # Check if deadline already exists for this ClickUp task
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, due_date FROM deadlines WHERE source_snippet = %s LIMIT 1", (source_id,))
        existing = cur.fetchone()
        if existing:
            # Update due date if changed
            if existing[1] != due_date:
                cur.execute("UPDATE deadlines SET due_date = %s, updated_at = NOW() WHERE id = %s",
                           (due_date, existing[0]))
                conn.commit()
        else:
            # Create new deadline
            cur.execute("""
                INSERT INTO deadlines (description, due_date, priority, source_snippet, status)
                VALUES (%s, %s, %s, %s, 'active')
            """, (f"[{space_name}/{list_name}] {task_name}", due_date, 'normal', source_id))
            conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
```

#### Change 6B: Mark completed ClickUp tasks as done in Baker deadlines
When a ClickUp task status changes to "complete"/"closed", find the matching Baker deadline and mark it done. Prevents stale overdue alerts.

---

## Implementation Sequence

**Batch 1 — Foundation (implement first):**
1. Part 4A: Ideas table migration
2. Part 4B-C: Idea detection + storage across all channels
3. Part 4D: Ideas API endpoints
4. Part 4E-F: Ideas sidebar + view

**Batch 2 — ClickUp dropdown + write guard:**
5. Part 1A: ClickUp structure endpoint
6. Part 1B: Frontend dropdown picker
7. Part 1C: Relaxed write guard (create-only)
8. Part 1D: Create-task endpoint

**Batch 3 — ClickUp documents + calendar enforcer:**
9. Part 2A-C: ClickUp attachment ingestion
10. Part 6A-B: ClickUp due date → Baker deadline sync

**Batch 4 — Google Calendar:**
11. Part 3A: Re-authorize OAuth with calendar scope (requires browser)
12. Part 3B-E: Calendar trigger, table, dashboard integration

**Batch 5 — Dropbox expansion:**
13. Part 5A: Update DROPBOX_WATCH_PATH env var on Render
14. Part 5B-C: Multi-path support + matter detection
15. Requires BRIEF_DOCUMENT_DEDUP_1 to be deployed first

## Files to Modify

| File | Changes |
|------|---------|
| `outputs/dashboard.py` | Ideas table migration, ideas endpoints, ClickUp structure endpoint, create-task endpoint, calendar_events table migration |
| `outputs/static/app.js` | Ideas sidebar + view, ClickUp dropdown picker, calendar integration in meetings card |
| `outputs/static/index.html` | Ideas sidebar section + view HTML |
| `outputs/static/style.css` | Ideas section styling (same teal as other sections) |
| `clickup_client.py` | Relaxed write guard, get_task_attachments() |
| `triggers/clickup_trigger.py` | Attachment ingestion, deadline sync |
| `triggers/dropbox_trigger.py` | Multi-path support, matter detection from path |
| `triggers/calendar_trigger.py` | New file — Google Calendar polling |
| `triggers/slack_trigger.py` | Idea detection in Director messages |
| `triggers/waha_webhook.py` | Idea detection in Director messages |
| `triggers/embedded_scheduler.py` | Register calendar_poll + ideas_count jobs |
| `config/settings.py` | Calendar config, expanded Dropbox paths |

## Pre-requisites

1. **BRIEF_DOCUMENT_DEDUP_1** must be deployed before Batch 5 (Dropbox expansion)
2. **Google OAuth re-authorization** required before Batch 4 (Calendar) — needs browser access
3. **Director reviews ClickUp structure** before Batch 2 — Baker adapts to Director's organization, not the other way around

## Schema Check (MUST do before coding)

```sql
SELECT column_name FROM information_schema.columns WHERE table_name = 'clickup_tasks';
SELECT column_name FROM information_schema.columns WHERE table_name = 'deadlines';
SELECT column_name FROM information_schema.columns WHERE table_name = 'documents';
```

## Verification

Per batch:
- Batch 1: Send "Idea: test idea" via Slack → appears in Ideas sidebar
- Batch 2: Triage alert → ClickUp dropdown shows real lists → task created in correct list
- Batch 3: ClickUp task with PDF attachment → appears in Documents section with source=clickup
- Batch 4: Google Calendar event → appears in Meetings card. Zoom link visible.
- Batch 5: File added to Baker-Project/Hagenauer/ → appears in Documents without manual copy

## Rules

- Check all table schemas before writing SQL (lessons #2, #3)
- `conn.rollback()` in all except blocks
- Syntax check all modified files before commit
- Never force push
- git pull before starting
- ClickUp write guard: create-only across all workspaces, delete/move BAKER space only
- Google Calendar: read-only scope initially (calendar.readonly)
- Dropbox: dedup must be in place before expanding watch paths
