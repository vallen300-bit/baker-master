# BRIEF: CLIENT_PM_SIDEBAR — Add "Client PM" section to dashboard sidebar

## Context
AO-PM (AO Project Manager) is deployed and working as a capability. Currently the only way to reach it is via Ask Baker (hoping the classifier routes correctly) or Ask Specialist (selecting "AO Project Manager" from a long dropdown of ~20 domain specialists). The Director wants a dedicated, prominent entry point.

**Design decision:** Build it as a scalable "Client PM" pattern — a dropdown listing only capabilities with `capability_type = 'client_pm'`. AO is the only one today, but when Wertheimer PM or MORV PM are added, they appear automatically. Approved by Director.

## Estimated time: ~1.5h
## Complexity: Medium
## Prerequisites: AO-PM capability deployed (commit 3737ae1+)
## Parallel-safe: Yes — touches index.html, app.js, dashboard.py, style.css

---

## Part 1: Mark AO-PM as `capability_type = 'client_pm'`

### Problem
AO-PM is currently `capability_type = 'domain'`, which makes it appear in the Ask Specialist dropdown alongside Finance, Legal, etc. It should be its own category.

### Implementation
SQL migration (run once):

```sql
UPDATE capability_sets
SET capability_type = 'client_pm'
WHERE slug = 'ao_pm';
```

**Add this to the brief's verification section — Code Brisen runs it via the Baker MCP `baker_raw_write` tool.**

### Key Constraints
- This removes AO-PM from the Ask Specialist picker (which filters `capability_type === 'domain'`). That's intentional — it gets its own dedicated section.
- The capability runner doesn't filter by `capability_type` when executing — it works with any type. No backend code change needed.
- The `/api/capabilities` endpoint already returns all capabilities. The frontend JS filters by type.

---

## Part 2: Backend — New endpoint `/api/scan/client-pm`

### Problem
Need a dedicated endpoint that routes directly to a client PM capability with pre-fetched context, identical to `/api/scan/specialist`.

### Current State
`/api/scan/specialist` (dashboard.py, lines 4735-4821) takes `SpecialistScanRequest` with `capability_slug` and does:
1. Fetch capability from registry
2. Pre-fetch entity context, emails, WhatsApp, meetings, prior conversations
3. Build `RoutingPlan(mode="fast", capabilities=[cap])`
4. Call `_scan_chat_capability()` with the entity_context

### Implementation

**File: `outputs/dashboard.py`**

After line 4821 (end of `scan_specialist`), add:

```python
@app.post("/api/scan/client-pm", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def scan_client_pm(req: SpecialistScanRequest):
    """
    CLIENT-PM-1: Force-route to a Client PM capability with deep context.
    Reuses the specialist pre-fetch pattern — same deep context injection.
    """
    return await scan_specialist(req)
```

Yes, it's a one-liner that delegates to `scan_specialist`. The specialist endpoint already does everything we need — capability lookup, context pre-fetch, routing. The only difference is the frontend entry point. If we need Client PM–specific behavior later (e.g., auto-loading persistent state), we can add it here without changing the specialist endpoint.

### Key Constraints
- Reuses `SpecialistScanRequest` — same shape: `{question, capability_slug, history}`
- No new request model needed
- If the capability doesn't exist or is inactive, the specialist endpoint already returns 404

---

## Part 3: Backend — New endpoint `/api/client-pms`

### Problem
The frontend needs a list of active Client PM capabilities to populate the dropdown.

### Implementation

**File: `outputs/dashboard.py`**

After the new `scan_client_pm` endpoint, add:

```python
@app.get("/api/client-pms", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_client_pms():
    """CLIENT-PM-1: List active client PM capabilities for the sidebar picker."""
    try:
        store = _get_store()
        caps = store.get_capability_sets(active_only=True)
        pms = [_serialize(c) for c in caps if c.get("capability_type") == "client_pm"]
        return {"client_pms": pms, "count": len(pms)}
    except Exception as e:
        logger.error(f"GET /api/client-pms failed: {e}")
        return {"client_pms": [], "count": 0, "error": str(e)}
```

### Key Constraints
- Filters `capability_type == 'client_pm'` from the full capability list
- No new DB query — reuses `get_capability_sets()`
- Returns empty list gracefully if no client PMs exist

---

## Part 4: Sidebar HTML

### Problem
Need a "Client PM" nav item between "Ask Specialist" and "Search".

### Current State (index.html, lines 80-88):
```html
<div class="nav-item" data-tab="ask-baker">
    <span class="nav-label">Ask Baker</span>
</div>
<div class="nav-item" data-tab="ask-specialist">
    <span class="nav-label">Ask Specialist</span>
</div>
<div class="nav-item" data-tab="search">
    <span class="nav-label">Search</span>
</div>
```

### Replace with:
```html
<div class="nav-item" data-tab="ask-baker">
    <span class="nav-label">Ask Baker</span>
</div>
<div class="nav-item" data-tab="ask-specialist">
    <span class="nav-label">Ask Specialist</span>
</div>
<div class="nav-item" data-tab="ask-client-pm">
    <span class="nav-label">Client PM</span>
</div>
<div class="nav-item" data-tab="search">
    <span class="nav-label">Search</span>
</div>
```

---

## Part 5: View Container HTML

### Problem
Need the "Ask Client PM" view with a dropdown picker and chat interface — identical structure to Ask Specialist.

### Implementation

**File: `outputs/static/index.html`**

After the closing `</div>` of `viewAskSpecialist` (line 359), add:

```html
        <!-- VIEW: Client PM -->
        <div class="view" id="viewAskClientPM">
            <div class="scan-view-header" style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
                <span class="scan-view-title">Client PM</span>
                <select id="clientPMPicker" class="specialist-picker">
                    <option value="">Select a client...</option>
                </select>
            </div>
            <div class="scan-layout">
                <div class="scan-view-body scan-top-input">
                    <form id="clientPMForm" class="scan-form" autocomplete="off">
                        <input id="clientPMFile" type="file" accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg" hidden />
                        <button type="button" class="scan-upload-btn" onclick="document.getElementById('clientPMFile').click()" title="Upload document">&#x1F4CE;</button>
                        <input id="clientPMInput" type="text" class="scan-input" placeholder="Ask the Client PM..." maxlength="4000" required disabled />
                        <button type="submit" class="scan-send" id="clientPMSendBtn" disabled>Send</button>
                    </form>
                    <div id="clientPMUploadStatus" class="upload-status" hidden></div>
                    <div id="clientPMMessages" class="scan-messages"></div>
                </div>
                <div class="artifact-panel open" id="clientPMArtifactPanel">
                    <div class="artifact-items" id="clientPMArtifactItems">
                        <div id="clientPMPersistentContent">
                            <div class="artifact-section-label">Generated Files</div>
                            <div id="clientPMGeneratedFiles" class="generated-files-list">
                                <div class="panel-empty-state">No documents yet.</div>
                            </div>
                            <div class="panel-divider"></div>
                            <div class="artifact-section-label">Upload Document</div>
                            <div class="drop-zone" id="clientPMDropZone">
                                <input type="file" id="clientPMDropInput" accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg" hidden multiple />
                                <div class="drop-zone-icon">&#128206;</div>
                                <div class="drop-zone-text">Drop file or click to upload</div>
                                <div class="drop-zone-hint">PDF, DOCX, XLSX, CSV, TXT, PNG, JPG</div>
                            </div>
                            <div id="clientPMDropStatus" class="drop-status" hidden></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
```

### Key Constraints
- All IDs prefixed with `clientPM` to avoid collision with specialist IDs
- Reuses `specialist-picker` CSS class for the dropdown (same styling)
- File upload wired to `clientPMFile` (same pattern as specialist)

---

## Part 6: Frontend JavaScript

### Problem
Need JS for: tab registration, loading client PMs into the dropdown, sending messages via the new endpoint, and managing per-client conversation history.

### Implementation

**File: `outputs/static/app.js`**

#### Change 1: Add to TAB_VIEW_MAP (line ~441)

After `'ask-specialist': 'viewAskSpecialist',` add:
```javascript
    'ask-client-pm': 'viewAskClientPM',
```

#### Change 2: Add to FUNCTIONAL_TABS (line ~451)

Add `'ask-client-pm'` to the Set.

#### Change 3: Add tab loader in switchTab() (line ~482)

After `else if (tabName === 'ask-specialist') loadSpecialistTab();` add:
```javascript
    else if (tabName === 'ask-client-pm') loadClientPMTab();
```

#### Change 4: Client PM state variables and functions

After the specialist state block (around line 5660, after `_getSpecialistHistory`), add:

```javascript
// ───────────────────────────────────────────────────────────
// CLIENT-PM-1: Client PM state
// ───────────────────────────────────────────────────────────
var _clientPMSlug = null;
var _clientPMHistories = {};
var _clientPMStreaming = false;
var _clientPMContext = 'global';

function _clientPMContextKey() {
    return (_clientPMContext || 'global') + ':' + (_clientPMSlug || '');
}

function _getClientPMHistory() {
    var key = _clientPMContextKey();
    if (!_clientPMHistories[key]) _clientPMHistories[key] = [];
    return _clientPMHistories[key];
}

async function loadClientPMTab() {
    if (_currentMatterSlug) {
        _clientPMContext = 'matter:' + _currentMatterSlug;
    }

    var picker = document.getElementById('clientPMPicker');
    if (!picker) return;
    if (picker.dataset.loaded) return;

    try {
        var resp = await bakerFetch('/api/client-pms');
        if (!resp.ok) return;
        var data = await resp.json();
        if (!data.client_pms) return;

        while (picker.options.length > 1) picker.remove(1);

        for (var i = 0; i < data.client_pms.length; i++) {
            var pm = data.client_pms[i];
            var opt = document.createElement('option');
            opt.value = pm.slug;
            opt.textContent = pm.name;
            picker.appendChild(opt);
        }
        picker.dataset.loaded = 'true';

        // Auto-select if only one client PM exists
        if (data.client_pms.length === 1) {
            picker.value = data.client_pms[0].slug;
            picker.dispatchEvent(new Event('change'));
        }
    } catch (e) {
        console.error('loadClientPMTab failed:', e);
    }
}

function appendClientPMBubble(role, content, id) {
    var container = document.getElementById('clientPMMessages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'scan-msg ' + (role === 'user' ? 'user' : 'baker');
    if (id) div.id = id;
    if (role === 'assistant' && !content) {
        var dots = document.createElement('div');
        dots.className = 'thinking';
        var span = document.createElement('span');
        span.className = 'thinking-dots';
        for (var i = 0; i < 3; i++) span.appendChild(document.createElement('span'));
        dots.appendChild(span);
        dots.appendChild(document.createTextNode(' Client PM is thinking...'));
        div.appendChild(dots);
    } else if (role === 'assistant') {
        var mdDiv = document.createElement('div');
        mdDiv.className = 'md-content';
        setSafeHTML(mdDiv, md(content));
        div.appendChild(mdDiv);
    } else {
        div.textContent = content;
    }
    container.prepend(div);
    container.scrollTop = 0;
}

async function sendClientPMMessage(question) {
    if (_clientPMStreaming || !question.trim() || !_clientPMSlug) return;
    _clientPMStreaming = true;

    var _panelId = 'clientPMArtifactPanel';
    var _itemsId = 'clientPMArtifactItems';
    clearArtifactPanel(_panelId, _itemsId);

    addArtifactCapability(_itemsId, _panelId, [_clientPMSlug]);

    var sendBtn = document.getElementById('clientPMSendBtn');
    var input = document.getElementById('clientPMInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) { input.disabled = true; input.value = ''; }

    _getClientPMHistory().push({ role: 'user', content: question });
    appendClientPMBubble('user', question);

    var replyId = 'clientpm-reply-' + Date.now();
    appendClientPMBubble('assistant', '', replyId);
    var replyEl = document.getElementById(replyId);
    if (replyEl) setSafeHTML(replyEl, '<div class="thinking"><span class="thinking-dots"><span></span><span></span><span></span></span> Client PM is thinking...</div>');

    var fullResponse = '';
    try {
        var resp = await bakerFetch('/api/scan/client-pm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            timeout: 180000,
            body: JSON.stringify({
                question: question,
                capability_slug: _clientPMSlug,
                history: _getClientPMHistory().slice(-30),
            }),
        });
        if (!resp.ok) throw new Error('Client PM API returned ' + resp.status);

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();
            for (var li = 0; li < lines.length; li++) {
                if (!lines[li].startsWith('data: ')) continue;
                var payload = lines[li].slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    var data = JSON.parse(payload);
                    if (data.status && !fullResponse && replyEl) {
                        var _sLabels = {
                            'retrieving': 'Searching client data...',
                            'thinking': 'Analyzing context...',
                            'generating': 'Writing response...'
                        };
                        var _sLabel = _sLabels[data.status];
                        if (_sLabel) {
                            var _sThink = replyEl.querySelector('.thinking');
                            if (_sThink) {
                                var _sNodes = _sThink.childNodes;
                                for (var _si = _sNodes.length - 1; _si >= 0; _si--) {
                                    if (_sNodes[_si].nodeType === 3) _sThink.removeChild(_sNodes[_si]);
                                }
                                _sThink.appendChild(document.createTextNode(' ' + _sLabel));
                            }
                        }
                    }
                    if (data.token) {
                        if (!fullResponse && replyEl) replyEl.textContent = '';
                        fullResponse += data.token;
                        if (replyEl) setSafeHTML(replyEl, '<div class="md-content">' + md(fullResponse) + '</div>');
                    }
                    if (data.capabilities) {
                        addArtifactCapability(_itemsId, _panelId, data.capabilities);
                    }
                    if (data.tool_call) {
                        addArtifactToolCall(_itemsId, _panelId, data.tool_call);
                    }
                    if (data.task_id) {
                        addArtifactTaskId(_itemsId, _panelId, data.task_id);
                    }
                } catch (pe) { /* skip parse errors */ }
            }
        }
    } catch (err) {
        if (replyEl) setSafeHTML(replyEl, '<span class="error">[Error: ' + escAttr(err.message) + ']</span>');
    }

    if (fullResponse) {
        _getClientPMHistory().push({ role: 'assistant', content: fullResponse });
    }

    _clientPMStreaming = false;
    if (sendBtn) sendBtn.disabled = !_clientPMSlug;
    if (input) { input.disabled = !_clientPMSlug; input.focus(); }
}
```

#### Change 5: Event listeners in DOMContentLoaded (after specialist listeners, ~line 6060)

After the specialist picker `change` listener block, add:

```javascript
    // Client PM form
    var clientPMForm = document.getElementById('clientPMForm');
    if (clientPMForm) {
        clientPMForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var input = document.getElementById('clientPMInput');
            if (input && input.value.trim()) sendClientPMMessage(input.value.trim());
        });
    }
    var clientPMPicker = document.getElementById('clientPMPicker');
    if (clientPMPicker) {
        clientPMPicker.addEventListener('change', function() {
            _clientPMSlug = clientPMPicker.value || null;
            var input = document.getElementById('clientPMInput');
            var sendBtn = document.getElementById('clientPMSendBtn');
            if (input) input.disabled = !_clientPMSlug;
            if (sendBtn) sendBtn.disabled = !_clientPMSlug;
            var container = document.getElementById('clientPMMessages');
            if (container) {
                container.textContent = '';
                var existing = _getClientPMHistory();
                for (var i = 0; i < existing.length; i++) {
                    appendClientPMBubble(existing[i].role, existing[i].content);
                }
            }
            if (_clientPMSlug && input) input.focus();
        });
    }

    // Client PM file upload
    setupDocumentUpload('clientPMFile', 'clientPMUploadStatus', 'viewAskClientPM');
```

#### Change 6: Cache bust

Update `index.html`:
- `app.js?v=85` → `app.js?v=86`
- `style.css?v=57` → `style.css?v=58` (only if CSS changes, but bump it anyway for safety)

---

## Part 7: Auto-select UX Enhancement

### Problem
Since AO-PM is currently the only client PM, the user shouldn't have to select from a dropdown with one option.

### Implementation
Already handled in `loadClientPMTab()` above:
```javascript
// Auto-select if only one client PM exists
if (data.client_pms.length === 1) {
    picker.value = data.client_pms[0].slug;
    picker.dispatchEvent(new Event('change'));
}
```

This means today: click "Client PM" → AO PM is auto-selected → input is immediately enabled. When a second PM is added, the dropdown appears with a choice.

---

## Files Modified
- `outputs/static/index.html` — Sidebar nav item + view container HTML + cache bust
- `outputs/static/app.js` — TAB_VIEW_MAP, FUNCTIONAL_TABS, switchTab, state vars, loadClientPMTab, appendClientPMBubble, sendClientPMMessage, event listeners + cache bust
- `outputs/dashboard.py` — 2 new endpoints: `POST /api/scan/client-pm`, `GET /api/client-pms`
- DB: `UPDATE capability_sets SET capability_type = 'client_pm' WHERE slug = 'ao_pm'`

## Do NOT Touch
- `orchestrator/capability_runner.py` — AO-PM execution logic, state injection, auto-update already working
- `orchestrator/agent.py` — Tool handlers for get_ao_state, update_ao_state already working
- `orchestrator/capability_registry.py` — Already loads all capability types
- `scripts/insert_ao_pm_capability.py` — Seed script, not runtime code
- `memory/store_back.py` — AO state persistence already working

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
2. Run SQL: `UPDATE capability_sets SET capability_type = 'client_pm' WHERE slug = 'ao_pm'`
3. Verify: `SELECT slug, capability_type FROM capability_sets WHERE slug = 'ao_pm'` → should show `client_pm`
4. Verify AO-PM no longer appears in Ask Specialist dropdown
5. Dashboard → Click "Client PM" in sidebar → AO PM auto-selected → input enabled
6. Ask: "What is the current state of the AO relationship?" → should stream response with tools
7. Ask: "How much capital has AO contributed?" → should use get_ao_state + query_baker_data tools
8. Verify conversation history persists when switching tabs and coming back
9. Verify `app.js?v=86` and `style.css?v=58` are loaded (not cached v85/v57)
10. Check Render logs for no import errors after deploy

## Verification SQL
```sql
-- Confirm AO-PM type changed
SELECT slug, name, capability_type, active FROM capability_sets WHERE slug = 'ao_pm';

-- After 24h: check Client PM usage
SELECT capability_slug, COUNT(*) as calls
FROM baker_tasks
WHERE capability_slug = 'ao_pm'
  AND created_at >= NOW() - INTERVAL '1 day'
GROUP BY capability_slug;
```

## Cost Impact
- Zero new API calls — this is a frontend routing change
- AO-PM already works; this just makes it easier to reach
- No model cost change

## Rollback
If anything breaks:
1. Revert `capability_type` back to `domain`: `UPDATE capability_sets SET capability_type = 'domain' WHERE slug = 'ao_pm'`
2. AO-PM reappears in Ask Specialist dropdown — user can still reach it
3. The sidebar item can be hidden by removing the `data-tab="ask-client-pm"` nav-item from HTML
