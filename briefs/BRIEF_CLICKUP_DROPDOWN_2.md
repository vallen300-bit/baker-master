# BRIEF: ClickUp Task Creation Dropdown + Write Guard Relaxation

**Priority:** High — triage ClickUp button creates orphan tasks in wrong space
**Ticket:** CLICKUP-DROPDOWN-2
**Depends on:** Nothing — standalone

## Problem

When triaging an alert and clicking "ClickUp", Baker creates the task in the BAKER catch-all space (901510186446). The task is orphaned — disconnected from the actual project. The Director wants tasks created in the correct project list.

## Solution

1. New endpoint returns the full ClickUp workspace → space → list structure
2. Frontend shows a dropdown picker when "ClickUp" is clicked
3. Task is created in the selected list
4. Write guard relaxed: create-only allowed across all 6 workspaces

## Implementation

### Change 1: ClickUp structure endpoint

**File:** `outputs/dashboard.py`

```python
@app.get("/api/clickup/structure", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def get_clickup_structure():
    """Return workspaces → spaces → lists for task creation dropdown."""
    from clickup_client import ClickUpClient
    client = ClickUpClient()
    structure = []
    for ws_id in client.workspace_ids:
        try:
            spaces = client.get_spaces(ws_id)
            for space in spaces:
                try:
                    lists = client.get_lists(space["id"])
                    for lst in lists:
                        structure.append({
                            "workspace_id": ws_id,
                            "space_id": space["id"],
                            "space_name": space["name"],
                            "list_id": lst["id"],
                            "list_name": lst["name"],
                            "full_path": f"{space['name']} / {lst['name']}"
                        })
                except Exception:
                    continue
        except Exception:
            continue
    return {"lists": structure}
```

**IMPORTANT:** Check what methods exist on `ClickUpClient` — look at `clickup_client.py` for `get_spaces()`, `get_lists()`, `get_folders()`. The ClickUp API structure is: Workspace → Space → Folder (optional) → List. Adapt the endpoint to match what's available. The client may already have these methods — check before writing new ones.

Also check `client.workspace_ids` — it may be stored differently. Look at how the existing ClickUp trigger iterates workspaces.

### Change 2: Create-task endpoint

**File:** `outputs/dashboard.py`

```python
@app.post("/api/clickup/create-task", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def create_clickup_task_in_list(request: Request):
    """Create a ClickUp task in a specific list."""
    body = await request.json()
    list_id = body.get("list_id")
    name = body.get("name", "Untitled task")
    description = body.get("description", "")
    priority = body.get("priority")  # 1=urgent, 2=high, 3=normal, 4=low
    due_date = body.get("due_date")  # ISO date string

    if not list_id:
        return JSONResponse({"error": "list_id required"}, status_code=400)

    try:
        from clickup_client import ClickUpClient
        client = ClickUpClient()
        result = client.create_task(
            list_id=list_id,
            name=name,
            description=description,
            priority=priority,
            due_date=due_date,
        )
        # Log the action
        try:
            store = _get_store()
            store.log_action(action_type="clickup_create", details=f"Created task '{name}' in list {list_id}")
        except Exception:
            pass
        return {"status": "created", "task_id": result.get("id"), "url": result.get("url")}
    except Exception as e:
        logger.error(f"ClickUp create task failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
```

**IMPORTANT:** Check the existing `create_task()` method in `clickup_client.py`. It may already exist but be restricted to BAKER space. Adapt accordingly.

### Change 3: Relax write guard

**File:** `clickup_client.py`

Find `_check_write_allowed()` (or similar guard function). Change it to allow create operations across all workspaces:

```python
# Before: only BAKER space allowed
# After: create-only allowed everywhere, destructive ops BAKER only

SAFE_WRITE_OPERATIONS = {'create_task', 'post_comment', 'add_attachment'}

def _check_write_allowed(self, operation: str = None):
    if operation in SAFE_WRITE_OPERATIONS:
        return True  # Create anywhere
    # For delete, move, update_status — keep BAKER-only restriction
    # ... existing guard logic ...
```

**IMPORTANT:** Read the existing `_check_write_allowed()` implementation first. Understand what it checks and how it's called. Minimal change — just widen the gate for safe operations.

### Change 4: Frontend dropdown picker

**File:** `outputs/static/app.js`

Replace the existing `_triageCreateClickUp()` function:

```javascript
// Cache ClickUp structure (fetch once per session)
var _clickUpListsCache = null;

async function _getClickUpLists() {
    if (_clickUpListsCache) return _clickUpListsCache;
    try {
        var resp = await bakerFetch('/api/clickup/structure');
        if (resp.ok) {
            var data = await resp.json();
            _clickUpListsCache = data.lists || [];
            return _clickUpListsCache;
        }
    } catch (e) {}
    return [];
}

async function _triageCreateClickUp(alertId, title, context) {
    var lists = await _getClickUpLists();
    if (!lists.length) {
        _showToast('Could not load ClickUp lists');
        return;
    }

    // Create a simple dropdown modal
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:var(--bg1);border:1px solid var(--border);border-radius:12px;padding:20px;min-width:400px;max-width:600px;max-height:70vh;overflow-y:auto;';
    modal.innerHTML = '<div style="font-size:16px;font-weight:600;margin-bottom:12px;color:var(--text);">Create ClickUp Task</div>' +
        '<div style="font-size:13px;color:var(--text3);margin-bottom:16px;">' + esc(title) + '</div>' +
        '<div style="font-size:12px;font-weight:600;color:var(--text3);margin-bottom:8px;">SELECT LIST:</div>';

    // Group by space
    var spaces = {};
    for (var i = 0; i < lists.length; i++) {
        var l = lists[i];
        if (!spaces[l.space_name]) spaces[l.space_name] = [];
        spaces[l.space_name].push(l);
    }

    for (var spaceName in spaces) {
        var spaceDiv = document.createElement('div');
        spaceDiv.style.cssText = 'margin-bottom:8px;';
        spaceDiv.innerHTML = '<div style="font-size:11px;font-weight:700;color:var(--text4);text-transform:uppercase;padding:4px 0;">' + esc(spaceName) + '</div>';
        var spaceLists = spaces[spaceName];
        for (var j = 0; j < spaceLists.length; j++) {
            (function(lst) {
                var btn = document.createElement('button');
                btn.style.cssText = 'display:block;width:100%;text-align:left;padding:8px 12px;margin:2px 0;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text2);cursor:pointer;font-size:13px;';
                btn.textContent = lst.list_name;
                btn.addEventListener('mouseenter', function() { btn.style.borderColor = 'var(--blue)'; btn.style.color = 'var(--text)'; });
                btn.addEventListener('mouseleave', function() { btn.style.borderColor = 'var(--border)'; btn.style.color = 'var(--text2)'; });
                btn.addEventListener('click', function() {
                    btn.textContent = 'Creating...';
                    btn.disabled = true;
                    bakerFetch('/api/clickup/create-task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ list_id: lst.list_id, name: title, description: context }),
                    }).then(function(r) {
                        if (r.ok) {
                            _showToast('Task created in ' + lst.full_path);
                            overlay.remove();
                        } else {
                            btn.textContent = 'Failed — try again';
                            btn.disabled = false;
                        }
                    }).catch(function() {
                        btn.textContent = 'Failed — try again';
                        btn.disabled = false;
                    });
                });
                spaceDiv.appendChild(btn);
            })(spaceLists[j]);
        }
        modal.appendChild(spaceDiv);
    }

    // Cancel button
    var cancelBtn = document.createElement('button');
    cancelBtn.style.cssText = 'margin-top:12px;padding:8px 16px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text3);cursor:pointer;font-size:13px;';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function() { overlay.remove(); });
    modal.appendChild(cancelBtn);

    overlay.appendChild(modal);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}
```

### Cache bust
- JS v++

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | 2 new endpoints: structure + create-task |
| `clickup_client.py` | Relaxed write guard for create operations |
| `outputs/static/app.js` | Dropdown picker modal, cached structure fetch |
| `outputs/static/index.html` | JS cache bust |

## Pre-check

Before coding:
```bash
grep -n "_check_write_allowed\|create_task\|get_spaces\|get_lists\|workspace_ids" clickup_client.py
```
Understand existing methods and adapt — don't duplicate.

## Verification

1. Click "ClickUp" on a triage card → dropdown shows workspaces/spaces/lists
2. Select a list → task created there (not in BAKER catch-all)
3. Task appears in ClickUp in the correct list
4. Cancel button works
5. Existing ClickUp read operations unaffected

## Rules

- Check clickup_client.py schema before writing new methods
- `conn.rollback()` in all except blocks
- Syntax check all modified files before commit
- Never force push
- git pull before starting
- ONLY relax write guard for create_task and post_comment — NOT delete/move
