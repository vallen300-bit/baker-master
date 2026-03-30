# BRIEF: Ideas Capture — Sidebar Section + Multi-Channel Detection

**Priority:** High — Director's ideas sent via Slack/WhatsApp get buried in message streams
**Ticket:** IDEAS-CAPTURE-1

## Problem

The Director sends ideas via Slack ("Idea: nvidia proposal...") or WhatsApp. These are ingested as regular messages and buried. No dedicated place to find, review, or act on them.

## Solution

1. Detect "Idea:" prefix across all channels (Slack, WhatsApp, Dashboard)
2. Store in dedicated `ideas` table
3. Show in IDEAS sidebar section (same pattern as Projects/Operations/Inbox/People)
4. Each idea is a card with triage: Develop / Create ClickUp Task / Dismiss

## Implementation

### Change 1: Ideas table

**File:** `outputs/dashboard.py` (startup migration block, near existing CREATE TABLE statements)

```sql
CREATE TABLE IF NOT EXISTS ideas (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'slack',
    status TEXT DEFAULT 'new',
    matter TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
```

### Change 2: Idea detection in Slack

**File:** `triggers/slack_trigger.py`

In the `_handle_director_slack_message()` function (SLACK-INTERACTIVE-1), BEFORE the intent classification step, add:

```python
# IDEAS-CAPTURE-1: Detect idea prefix before intent classification
if text.lower().startswith('idea:') or text.lower().startswith('idea -'):
    _store_idea(text, source='slack')
    _post_and_store_reply(client, channel_id, thread_ts, "Idea captured. You'll find it in the Ideas section on the dashboard.")
    return
```

Add the `_store_idea` function (can go near the top of the file or near other helper functions):

```python
def _store_idea(text: str, source: str = 'slack'):
    """IDEAS-CAPTURE-1: Store a Director idea. Strip the 'Idea:' prefix."""
    import re as _re
    content = _re.sub(r'^idea[:\-\s]+', '', text, flags=_re.IGNORECASE).strip()
    if not content:
        return
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO ideas (content, source) VALUES (%s, %s)", (content, source))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Idea store failed: {e}")
```

### Change 3: Idea detection in WhatsApp

**File:** `triggers/waha_webhook.py`

In the Director message handling section (around where `_handle_director_message()` processes the text), BEFORE intent classification, add:

```python
# IDEAS-CAPTURE-1: Detect idea prefix
if combined_body.lower().startswith('idea:') or combined_body.lower().startswith('idea -'):
    _store_idea_wa(combined_body)
    _wa_reply(sender, "Idea captured. You'll find it in the Ideas section on the dashboard.")
    return
```

Add the store function (same logic, adapted for WhatsApp context):

```python
def _store_idea_wa(text: str):
    """IDEAS-CAPTURE-1: Store a Director idea from WhatsApp."""
    import re as _re
    content = _re.sub(r'^idea[:\-\s]+', '', text, flags=_re.IGNORECASE).strip()
    if not content:
        return
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO ideas (content, source) VALUES (%s, %s)", (content, 'whatsapp'))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Idea store (WA) failed: {e}")
```

**IMPORTANT:** Find the exact location in `_handle_director_message()` where intent is classified. The idea detection MUST go before `classify_intent()` — otherwise Baker will try to interpret "Idea: nvidia proposal" as an action request.

### Change 4: Idea detection in Dashboard (Ask Baker)

**File:** `outputs/dashboard.py`

In the `scan_chat()` function, BEFORE intent classification, add idea detection:

```python
# IDEAS-CAPTURE-1: Detect idea prefix in Ask Baker
if req.question.lower().startswith('idea:') or req.question.lower().startswith('idea -'):
    import re as _idea_re
    _idea_content = _idea_re.sub(r'^idea[:\-\s]+', '', req.question, flags=_idea_re.IGNORECASE).strip()
    if _idea_content:
        try:
            store = _get_store()
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO ideas (content, source) VALUES (%s, %s)", (_idea_content, 'scan'))
                    conn.commit()
                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception:
            pass

    async def _idea_stream():
        yield f"data: {json.dumps({'token': 'Idea captured. You can find it in the Ideas section.'})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(_idea_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

**Location:** This must go early in `scan_chat()`, before the complexity routing / intent classification. Search for where `req.question` is first used and add this check there.

### Change 5: API endpoints

**File:** `outputs/dashboard.py`

```python
@app.get("/api/ideas", tags=["ideas"], dependencies=[Depends(verify_api_key)])
async def list_ideas(status: str = None):
    """List ideas, newest first."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT id, content, source, status, matter, created_at
                FROM ideas WHERE status = %s
                ORDER BY created_at DESC LIMIT 50
            """, (status,))
        else:
            cur.execute("""
                SELECT id, content, source, status, matter, created_at
                FROM ideas WHERE status != 'dismissed'
                ORDER BY created_at DESC LIMIT 50
            """)
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "content": r[1], "source": r[2], "status": r[3],
                 "matter": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]
    finally:
        store._put_conn(conn)


@app.patch("/api/ideas/{idea_id}", tags=["ideas"], dependencies=[Depends(verify_api_key)])
async def triage_idea(idea_id: int, request: Request):
    """Triage an idea: update status."""
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ('new', 'developing', 'actioned', 'dismissed'):
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("UPDATE ideas SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                   (new_status, idea_id))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return JSONResponse({"error": "Idea not found"}, status_code=404)
        return {"updated": idea_id}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)
```

### Change 6: Sidebar section

**File:** `outputs/static/index.html`

Add IDEAS as a collapsible section after PEOPLE, before the divider:

```html
<!-- IDEAS-CAPTURE-1: Ideas section (expandable) -->
<div class="nav-section-header" id="navIdeasHeader" data-section="ideas">
    <span class="nav-section-arrow">&#9656;</span>
    <span class="nav-section-label">Ideas</span>
    <span class="nav-count" id="ideasCount"></span>
</div>
<div class="nav-sub" id="ideasSubList" style="display:none;"></div>
```

Add the section header color (same teal as all other sections):
```css
#navIdeasHeader .nav-section-label { color: #0d9488; }
```

Add the Ideas view in the content area:
```html
<div class="view" id="viewIdeas">
    <div class="section-label">Ideas</div>
    <div id="ideasContent"></div>
</div>
```

### Change 7: Frontend — sidebar loader + view + triage

**File:** `outputs/static/app.js`

Add `'ideas': 'viewIdeas'` to `TAB_VIEW_MAP` and `'ideas'` to `FUNCTIONAL_TABS`.

Add to `switchTab()`:
```javascript
else if (tabName === 'ideas') loadIdeasTab();
```

Add `loadIdeasSidebar()` call in `loadMorningBrief()` (next to `loadPeopleSidebar()`).

```javascript
async function loadIdeasSidebar() {
    try {
        var resp = await bakerFetch('/api/ideas');
        if (!resp.ok) return;
        var ideas = await resp.json();
        var container = document.getElementById('ideasSubList');
        if (!container) return;
        container.textContent = '';
        for (var i = 0; i < Math.min(ideas.length, 10); i++) {
            var idea = ideas[i];
            var item = document.createElement('div');
            item.className = 'nav-item';
            item.dataset.tab = 'ideas';
            var lbl = document.createElement('span');
            lbl.className = 'nav-label';
            lbl.textContent = idea.content.substring(0, 40) + (idea.content.length > 40 ? '...' : '');
            item.appendChild(lbl);
            container.appendChild(item);
        }
        setText('ideasCount', ideas.length || '');
        _initSectionToggle('navIdeasHeader', 'ideasSubList', 'ideas', false);
        // Auto-expand if there are ideas
        if (ideas.length > 0) {
            var list = document.getElementById('ideasSubList');
            var arrow = document.querySelector('#navIdeasHeader .nav-section-arrow');
            if (list) list.style.display = '';
            if (arrow) arrow.innerHTML = '&#9662;';
            localStorage.setItem('sidebar_ideas', 'true');
        }
    } catch (e) {
        console.error('loadIdeasSidebar failed:', e);
    }
}

async function loadIdeasTab() {
    var container = document.getElementById('ideasContent');
    if (!container) return;
    container.innerHTML = '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Loading...</div>';
    try {
        var resp = await bakerFetch('/api/ideas');
        if (!resp.ok) throw new Error('API ' + resp.status);
        var ideas = await resp.json();
        container.textContent = '';
        if (!ideas.length) {
            container.textContent = 'No ideas yet. Send "Idea: ..." via Slack, WhatsApp, or Ask Baker.';
            return;
        }
        for (var i = 0; i < ideas.length; i++) {
            var idea = ideas[i];
            var card = document.createElement('div');
            card.className = 'issue-card issue-open';
            card.dataset.ideaId = idea.id;

            var sourceTag = '<span class="issue-badge issue-badge-open">' + esc(idea.source) + '</span>';
            var dateTag = idea.created_at ? '<span class="doc-date">' + esc(idea.created_at.substring(0, 10)) + '</span>' : '';

            card.innerHTML =
                '<div class="issue-card-header">' + sourceTag + dateTag + '</div>' +
                '<div class="issue-card-title">' + esc(idea.content) + '</div>' +
                '<div class="issue-card-triage"></div>';

            var triage = card.querySelector('.issue-card-triage');
            _addIdeaTriageButtons(triage, idea, card);
            container.appendChild(card);
        }
    } catch (e) {
        container.textContent = 'Failed to load ideas.';
    }
}

function _addIdeaTriageButtons(triage, idea, card) {
    // Develop
    var devBtn = document.createElement('button');
    devBtn.className = 'triage-btn';
    devBtn.textContent = 'Develop';
    devBtn.addEventListener('click', function() {
        _triggerScanQuestion('Develop this idea further and suggest concrete next steps: "' + idea.content + '"');
    });
    triage.appendChild(devBtn);

    // Create ClickUp Task
    var cuBtn = document.createElement('button');
    cuBtn.className = 'triage-btn';
    cuBtn.textContent = 'ClickUp Task';
    cuBtn.addEventListener('click', function() {
        _triggerScanQuestion('Create a ClickUp task for this idea: "' + idea.content + '"');
    });
    triage.appendChild(cuBtn);

    // Dismiss
    var dismissBtn = document.createElement('button');
    dismissBtn.className = 'triage-btn triage-dismiss';
    dismissBtn.textContent = '\u2715';
    dismissBtn.title = 'Dismiss';
    dismissBtn.addEventListener('click', function() {
        bakerFetch('/api/ideas/' + idea.id, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'dismissed' }),
        }).then(function() {
            card.style.opacity = '0.3';
            setTimeout(function() { card.remove(); }, 500);
            loadIdeasSidebar();
        });
    });
    triage.appendChild(dismissBtn);
}
```

Add delegated click handler for ideas sidebar items (near the existing People delegated handler):

```javascript
// IDEAS-CAPTURE-1: Delegated click handler for Ideas sub-list
var ideasSubList = document.getElementById('ideasSubList');
if (ideasSubList) {
    ideasSubList.addEventListener('click', function(e) {
        var item = e.target.closest('.nav-item');
        if (item) switchTab('ideas');
    });
}
```

### Cache bust
- CSS v++ (if CSS changes needed)
- JS v++

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Ideas table migration, idea detection in scan_chat, 2 API endpoints |
| `triggers/slack_trigger.py` | Idea detection + _store_idea() in Director handler |
| `triggers/waha_webhook.py` | Idea detection + _store_idea_wa() in Director handler |
| `outputs/static/index.html` | Ideas sidebar section + view HTML |
| `outputs/static/style.css` | Ideas header color (one line) |
| `outputs/static/app.js` | TAB_VIEW_MAP, loadIdeasSidebar(), loadIdeasTab(), triage handlers |

## Testing

1. Send `Idea: test nvidia proposal` via Slack → Baker replies "Idea captured" → appears in Ideas sidebar
2. Send `Idea: drone company meeting` via WhatsApp → same result
3. Type `Idea: AI development company` in Ask Baker → same result
4. Click Ideas in sidebar → right panel shows all ideas as cards
5. Click "Develop" → switches to Ask Baker with pre-filled question
6. Click Dismiss → idea fades out and disappears
7. Ideas without "Idea:" prefix → processed normally (NOT captured as ideas)

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/slack_trigger.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"
```

## Rules

- Check all table schemas before writing SQL
- `conn.rollback()` in all except blocks
- Idea detection MUST go BEFORE intent classification in all three channels
- Syntax check all modified files before commit
- Never force push
- git pull before starting
