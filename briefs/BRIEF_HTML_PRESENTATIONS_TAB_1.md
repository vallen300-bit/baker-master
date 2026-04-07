# BRIEF: HTML-PRESENTATIONS-TAB-1 — Presentations Sidebar Tab in CEO Cockpit

## Context
Baker can create HTML presentations and publish them to `brisen-docs.onrender.com` (Render static site, auto-deploys from `docs-site/` in the repo). Currently the Director has no way to browse or find these presentations from the CEO Cockpit — must remember URLs or dig through Dropbox. This adds a "Presentations" sidebar tab with folder-grouped cards and inline viewing.

## Estimated time: ~1.5h
## Complexity: Low-Medium
## Prerequisites: None (brisen-docs already deployed, dashboard already has the Dossiers pattern to replicate)

---

## Feature 1: Create Presentation Manifest (`index.json`)

### Problem
No machine-readable list of presentations exists. The dashboard needs a structured source to discover what presentations are available.

### Current State
`docs-site/index.html` is a hand-coded HTML page listing 2 NVIDIA presentations. No JSON manifest.

### Implementation

**Create:** `docs-site/index.json`

```json
{
  "version": 1,
  "updated_at": "2026-04-07",
  "folders": [
    {
      "name": "NVIDIA",
      "slug": "nvidia",
      "presentations": [
        {
          "title": "Brisen AI x NVIDIA x Corinthia — Partnership Strategy",
          "file": "partnership.html",
          "created": "2026-04-05",
          "matter": "nvidia"
        },
        {
          "title": "VERTEX — The First NVIDIA Hotel Concept",
          "file": "vertex-hotel.html",
          "created": "2026-04-05",
          "matter": "nvidia"
        }
      ]
    }
  ]
}
```

**Also create:** `docs-site/_headers` (Render static site custom headers for CORS)

```
/index.json
  Access-Control-Allow-Origin: *
  Cache-Control: no-cache
```

### Key Constraints
- `index.json` is the single source of truth for the dashboard
- When Baker publishes a new presentation, it MUST also update `index.json` (add the entry) and push
- Keep the file human-readable — Director may inspect it
- The `_headers` file is a Render static site feature — it applies headers to matching paths

### Verification
```bash
# After deploy, verify CORS
curl -s -I https://brisen-docs.onrender.com/index.json | grep -i 'access-control\|content-type'
# Should show: Access-Control-Allow-Origin: * and Content-Type: application/json
```

---

## Feature 2: Add Sidebar Nav Item + View Container

### Problem
No "Presentations" entry in the sidebar, no view container for the content.

### Current State
`outputs/static/index.html`:
- Sidebar reference tabs are at lines 95-102: Documents, Dossiers
- View containers are at lines 459-463 (Dossiers pattern)

### Implementation

**File:** `outputs/static/index.html`

**2a. Add sidebar nav item** — insert AFTER the Dossiers nav item (after line 102):

```html
        <div class="nav-item" data-tab="presentations">
            <span class="nav-label">Presentations</span>
            <span class="nav-count" id="presentationsCount"></span>
        </div>
```

**2b. Add view container** — insert AFTER the Dossiers view (after line 463):

```html
        <!-- VIEW: Presentations (HTML-PRESENTATIONS-TAB-1) -->
        <div class="view" id="viewPresentations">
            <div class="section-label">HTML Presentations</div>
            <div id="presentationsContent"></div>
            <div id="presentationViewer" class="presentation-viewer" hidden>
                <div class="presentation-viewer-toolbar">
                    <button class="dossier-btn" id="presentationBackBtn">Back to list</button>
                    <a class="dossier-btn" id="presentationNewTabBtn" target="_blank" rel="noopener">Open in new tab</a>
                </div>
                <iframe id="presentationFrame" class="presentation-frame"></iframe>
            </div>
        </div>
```

**2c. Bump cache versions** — line 16 and line 498:

```html
<link rel="stylesheet" href="/static/style.css?v=67">
```
```html
<script src="/static/app.js?v=99"></script>
```

### Key Constraints
- Nav item placement: between Dossiers and the next divider (natural grouping with Documents and Dossiers)
- View has TWO states: list mode (presentationsContent visible, viewer hidden) and view mode (content hidden, viewer visible with iframe)
- The iframe approach avoids leaving the cockpit

### Verification
Load the dashboard. "Presentations" should appear in sidebar below Dossiers. Clicking it should show a loading state then the content.

---

## Feature 3: Add CSS for Presentation Viewer

### Problem
Need styles for the iframe viewer and toolbar.

### Current State
`outputs/static/style.css` at v=66. Dossier card styles at lines 1272-1299 — we reuse those.

### Implementation

**File:** `outputs/static/style.css`

Add at the end (after the last rule), before the closing:

```css
/* HTML-PRESENTATIONS-TAB-1: Presentation viewer */
.presentation-viewer { display: flex; flex-direction: column; height: calc(100vh - 80px); }
.presentation-viewer-toolbar { display: flex; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); align-items: center; }
.presentation-viewer-toolbar a { text-decoration: none; }
.presentation-frame { flex: 1; border: none; border-radius: 0 0 8px 8px; background: #0a0a0f; }
```

### Key Constraints
- Reuse `.dossier-card` and `.dossier-btn` for cards and buttons — no new card classes needed
- The iframe gets `flex: 1` to fill remaining viewport height
- Background matches the dark theme of brisen-docs presentations

### Verification
Check that the iframe fills the view area and toolbar buttons are properly positioned.

---

## Feature 4: Add `loadPresentationsTab()` in app.js

### Problem
No JavaScript logic to fetch the manifest, render folder groups, or handle inline viewing.

### Current State
`outputs/static/app.js` at v=98.
- `TAB_VIEW_MAP` at line 667-681 — needs `'presentations': 'viewPresentations'`
- `FUNCTIONAL_TABS` at line 684 — needs `'presentations'` added
- `switchTab()` at line 686-728 — needs `else if` for presentations
- Dossier tab pattern at lines 7780-7877 — our template

### Implementation

**File:** `outputs/static/app.js`

**4a. Add to TAB_VIEW_MAP** (after line 678 `'dossiers': 'viewDossiers',`):

```javascript
    'presentations': 'viewPresentations',
```

**4b. Add to FUNCTIONAL_TABS** (line 684 — add `'presentations'` to the Set):

After `'dossiers'` in the Set constructor, add `, 'presentations'`.

**4c. Add to switchTab()** (after line 724 `else if (tabName === 'dossiers') loadDossiersTab();`):

```javascript
    else if (tabName === 'presentations') loadPresentationsTab();
```

**4d. Add the loadPresentationsTab function** — insert after the `loadDossiersTab` function block (after line ~7877):

```javascript
// ═══ HTML PRESENTATIONS TAB (HTML-PRESENTATIONS-TAB-1) ═══

var BRISEN_DOCS_BASE = 'https://brisen-docs.onrender.com';

async function loadPresentationsTab() {
    var container = document.getElementById('presentationsContent');
    var viewer = document.getElementById('presentationViewer');
    if (!container) return;

    // Reset to list mode
    container.style.display = '';
    if (viewer) viewer.hidden = true;

    showLoading(container, 'Loading presentations');

    try {
        var resp = await fetch(BRISEN_DOCS_BASE + '/index.json?_t=' + Date.now());
        if (!resp.ok) throw new Error('Failed to fetch presentations manifest');
        var data = await resp.json();
        var folders = data.folders || [];

        // Count total presentations
        var total = 0;
        folders.forEach(function(f) { total += (f.presentations || []).length; });

        // Update badge
        var badge = document.getElementById('presentationsCount');
        if (badge) badge.textContent = total || '';

        container.textContent = '';
        var wrapper = document.createElement('div');

        if (folders.length === 0) {
            var emptyDiv = document.createElement('div');
            emptyDiv.style.cssText = 'padding:40px;text-align:center;color:var(--text3);';
            emptyDiv.textContent = 'No presentations yet. Ask Baker to prepare one.';
            wrapper.appendChild(emptyDiv);
        }

        for (var i = 0; i < folders.length; i++) {
            var folder = folders[i];
            var section = document.createElement('div');
            section.style.marginTop = i > 0 ? '8px' : '0';

            // Folder header (expanded by default)
            var fHeader = document.createElement('div');
            fHeader.style.cssText = 'padding:10px 16px;font-size:12px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;align-items:center;gap:6px;';
            var _arrowSpan = document.createElement('span');
            _arrowSpan.className = 'dossier-section-arrow';
            _arrowSpan.style.fontSize = '10px';
            _arrowSpan.innerHTML = '&#9662;';
            fHeader.appendChild(_arrowSpan);
            fHeader.appendChild(document.createTextNode(' ' + folder.name + ' (' + (folder.presentations || []).length + ')'));
            var fList = document.createElement('div');

            (function(hdr, lst) {
                hdr.addEventListener('click', function() {
                    var isOpen = lst.style.display !== 'none';
                    lst.style.display = isOpen ? 'none' : '';
                    hdr.querySelector('.dossier-section-arrow').innerHTML = isOpen ? '&#9656;' : '&#9662;';
                });
            })(fHeader, fList);

            section.appendChild(fHeader);

            var presos = folder.presentations || [];
            for (var j = 0; j < presos.length; j++) {
                fList.appendChild(_renderPresentationCard(folder.slug, presos[j]));
            }
            section.appendChild(fList);
            wrapper.appendChild(section);
        }

        container.appendChild(wrapper);

    } catch (err) {
        container.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'padding:20px;color:var(--red);';
        errDiv.textContent = 'Failed to load presentations: ' + err.message;
        container.appendChild(errDiv);
    }
}

function _renderPresentationCard(folderSlug, p) {
    var card = document.createElement('div');
    card.className = 'dossier-card';

    // Title
    var title = document.createElement('div');
    title.style.cssText = 'font-weight:600;font-size:14px;color:var(--text);';
    title.textContent = p.title || p.file;
    card.appendChild(title);

    // Meta row: date + matter
    var meta = document.createElement('div');
    meta.style.cssText = 'font-size:12px;color:var(--text2);margin-top:4px;display:flex;gap:16px;';
    if (p.created) {
        var dateSpan = document.createElement('span');
        dateSpan.textContent = p.created;
        meta.appendChild(dateSpan);
    }
    if (p.matter) {
        var matterSpan = document.createElement('span');
        matterSpan.style.color = 'var(--text3)';
        matterSpan.textContent = p.matter;
        meta.appendChild(matterSpan);
    }
    card.appendChild(meta);

    // Action buttons
    var actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:8px;margin-top:8px;';

    var viewUrl = BRISEN_DOCS_BASE + '/' + folderSlug + '/' + p.file;

    var viewBtn = document.createElement('button');
    viewBtn.className = 'dossier-btn dossier-btn-primary';
    viewBtn.textContent = 'View';
    viewBtn.onclick = function() {
        _openPresentationViewer(viewUrl, p.title || p.file);
    };
    actions.appendChild(viewBtn);

    var newTabBtn = document.createElement('button');
    newTabBtn.className = 'dossier-btn';
    newTabBtn.textContent = 'Open in new tab';
    newTabBtn.onclick = function() {
        window.open(viewUrl, '_blank');
    };
    actions.appendChild(newTabBtn);

    card.appendChild(actions);
    return card;
}

function _openPresentationViewer(url, title) {
    var container = document.getElementById('presentationsContent');
    var viewer = document.getElementById('presentationViewer');
    var frame = document.getElementById('presentationFrame');
    var backBtn = document.getElementById('presentationBackBtn');
    var newTabBtn = document.getElementById('presentationNewTabBtn');

    if (!viewer || !frame) { window.open(url, '_blank'); return; }

    // Switch to viewer mode
    container.style.display = 'none';
    viewer.hidden = false;
    frame.src = url;
    if (newTabBtn) newTabBtn.href = url;

    if (backBtn) {
        backBtn.onclick = function() {
            frame.src = '';
            viewer.hidden = true;
            container.style.display = '';
        };
    }
}
```

### Key Constraints
- Fetch uses `Date.now()` cache buster — brisen-docs is Render static with aggressive caching
- Uses `document.createTextNode()` for folder names — XSS safety (no innerHTML with user data)
- IIFE closure `(function(hdr, lst) { ... })` for click handlers in loop — standard JS pattern used in dossiers
- Inline iframe viewing with back button — Director stays in cockpit
- "Open in new tab" as fallback for full-screen viewing
- No Baker API calls — purely fetches from brisen-docs (zero backend cost)

### Verification
1. Click "Presentations" in sidebar
2. Should show NVIDIA folder with 2 presentations
3. Click "View" on any card — iframe loads the presentation inline
4. Click "Back to list" — returns to card view
5. Click "Open in new tab" — opens in new browser tab
6. Badge shows "2" next to Presentations in sidebar

---

## Feature 5: Update Memory — Baker Publish Flow

### Problem
When Baker creates a presentation, the publish flow (in `memory/gemma-and-docs-hosting.md`) must also update `index.json`.

### Current State
Memory file says: create HTML, copy to `docs-site/[folder]/`, update `docs-site/index.html`, commit, push.

### Implementation

**File:** Memory file `memory/gemma-and-docs-hosting.md`

Update the "How to Add a New Presentation" section to include updating `index.json`:

Add step between current steps 2 and 3:

```
2b. Update `docs-site/index.json`:
   - If the folder exists in the `folders` array, append the new presentation to its `presentations` array
   - If the folder doesn't exist, add a new folder entry
   - Update `updated_at` to today's date
   - Example entry: `{"title": "My Presentation", "file": "my-pres.html", "created": "2026-04-07", "matter": "hagenauer"}`
```

### Key Constraints
- This is a documentation change only — tells future Claude sessions how to publish
- `index.json` is the source of truth, `index.html` is a nice-to-have landing page

### Verification
Read the memory file and confirm the publish flow mentions `index.json`.

---

## Files Modified
- `docs-site/index.json` — **NEW** — presentation manifest (JSON)
- `docs-site/_headers` — **NEW** — CORS headers for Render static site
- `outputs/static/index.html` — sidebar nav item + view container + cache bump
- `outputs/static/app.js` — TAB_VIEW_MAP, FUNCTIONAL_TABS, switchTab, loadPresentationsTab + helpers
- `outputs/static/style.css` — presentation viewer styles (5 lines)
- Memory file — publish flow updated (documentation only)

## Do NOT Touch
- `outputs/dashboard.py` — no backend API needed (frontend fetches from brisen-docs directly)
- `orchestrator/` — no agent/capability changes
- `triggers/` — no trigger changes
- `memory/store_back.py` — no DB schema changes

## Quality Checkpoints
1. Sidebar shows "Presentations" with badge count
2. Clicking tab loads folder-grouped cards from brisen-docs
3. "View" button opens presentation inline in iframe
4. "Back to list" returns to card view
5. "Open in new tab" works
6. No CORS errors in console (check `_headers` deployed)
7. Cache busted: CSS v=67, JS v=99
8. Empty state message if no presentations
9. Lesson #4: CSS/JS cache versions bumped in index.html
10. Lesson #11: No duplicate API endpoints (none added — pure frontend)

## Verification After Deploy
```bash
# 1. Check manifest is accessible with CORS
curl -s -I https://brisen-docs.onrender.com/index.json | grep -i 'access-control'

# 2. Check manifest content
curl -s https://brisen-docs.onrender.com/index.json | python3 -m json.tool

# 3. Load dashboard, click Presentations, verify cards appear
# 4. Click View — iframe loads presentation
# 5. Click Back — returns to list
```
