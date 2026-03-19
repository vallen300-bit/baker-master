# BRIEF: D8 — Remove Commitments Tab from Dashboard

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 27)
**Priority:** Low — cleanup, 30-minute task
**Branch:** `fix/remove-commitments-tab-d8`

---

## Context

All 625 commitments were migrated to the `deadlines` table (OBLIGATIONS-UNIFY-1, Session 24-25). The `commitment_checker` scheduler job was killed (Session 26). The `commitments` table still exists in PostgreSQL but all rows have `status='migrated'`.

The Commitments tab is now dead weight:
- The sidebar has no "Commitments" nav item in the HTML (it was removed), but `app.js` still has the tab route, loader function, CSS, and the Obligations tab still fetches from `/api/commitments` (which returns migrated/empty data)
- The Obligations (Deadlines) tab at line ~3239 of `app.js` fetches BOTH `/api/deadlines` AND `/api/commitments` and merges them. This is now redundant.
- There is an entire `loadCommitmentsTab()` function (lines ~4394-4486) that nobody can reach.

---

## Changes

### 1. `outputs/static/app.js` — Remove dead code

**a) Remove `'commitments'` from TAB_VIEW_MAP (line ~415):**
```js
// REMOVE this line:
'commitments': 'viewCommitments',
```

**b) Remove `'commitments'` from FUNCTIONAL_TABS set (line ~421):**
```js
// BEFORE:
const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'people', 'tags', 'search', 'ask-baker', 'ask-specialist', 'travel', 'media', 'commitments', 'documents', 'browser', 'baker-data']);

// AFTER:
const FUNCTIONAL_TABS = new Set(['morning-brief', 'fires', 'matters', 'deadlines', 'people', 'tags', 'search', 'ask-baker', 'ask-specialist', 'travel', 'media', 'documents', 'browser', 'baker-data']);
```

**c) Remove commitments case in `switchTab()` (line ~454):**
```js
// REMOVE this line:
else if (tabName === 'commitments') loadCommitmentsTab();
```

**d) Clean up `loadDeadlinesTab()` (lines ~3239-3267) — stop fetching commitments:**

The function currently does:
```js
var [dlResp, cmResp] = await Promise.all([
    bakerFetch('/api/deadlines?limit=100'),
    bakerFetch('/api/commitments?status=active&limit=200'),
]);
```

Replace the entire fetch+merge block. The new version should only fetch deadlines:

```js
async function loadDeadlinesTab() {
    var container = document.getElementById('deadlinesContent');
    if (!container) return;
    showLoading(container, 'Loading obligations');

    try {
        var dlResp = await bakerFetch('/api/deadlines?limit=100');
        var allItems = [];

        if (dlResp.ok) {
            var dlData = await dlResp.json();
            (dlData.deadlines || []).forEach(function(d) {
                allItems.push({ type: 'deadline', id: d.id, description: d.description, due_date: d.due_date, source: d.source_type || 'deadline', matter: d.matter_slug, priority: d.priority, status: d.status, severity: d.severity, obligation_type: d.obligation_type, assigned_to: d.assigned_to });
            });
        }

        // Dedup by type+id
        var seen = {};
        // ... rest of the function stays the same from line 3269 onward
```

Remove these specific blocks:
- The `bakerFetch('/api/commitments?status=active&limit=200')` call from the Promise.all (line ~3242)
- The `cmResp` handling block (lines ~3252-3256)
- The overdue commitments fetch block (lines ~3259-3266)

Keep everything else in `loadDeadlinesTab()` — the dedup logic, sorting, rendering, dismiss/reschedule handlers all still apply to deadlines.

**Note on dismiss/reschedule URLs (lines ~3378-3387):** The rendering currently branches:
```js
var dismissUrl = item.type === 'deadline'
    ? '/api/deadlines/' + item.id + '/dismiss'
    : '/api/commitments/' + item.id + '/dismiss';
```
Since all items are now type `'deadline'`, simplify to just the deadline URL. Same for reschedule. But this is optional — the ternary still works correctly since `item.type` will always be `'deadline'`.

**e) Remove the entire `loadCommitmentsTab()` function (lines ~4394-4486).**
Delete from `// --- Commitments Tab ---` through the closing `}` of the function.

**f) Remove commitment-related CSS from `_injectDataLayerCSS()` (lines ~4150-4153).**
Remove these lines from the CSS string array:
```js
'.commitment-card{background:white;border:1px solid #e8e8e8;border-radius:8px;padding:12px 16px;margin-bottom:8px}',
'.commitment-card.overdue{border-left:3px solid #f44336}',
'.commitment-desc{font-size:14px;font-weight:500;margin-bottom:4px}',
'.commitment-meta{font-size:12px;color:#888}',
```

### 2. `outputs/static/index.html` — No changes needed

There is no Commitments nav item in the sidebar HTML (it was already removed). There is no `viewCommitments` div. Nothing to do here.

### 3. `outputs/static/style.css` — No changes needed

No commitment-specific CSS in the external stylesheet (it is all inline in `_injectDataLayerCSS()` in `app.js`).

### 4. Backend — No changes

Keep the `/api/commitments` endpoint in `dashboard.py` (lines 3518-3570). It still works and returns the migrated data. Removing it could break things if anything else references it. It is harmless.

Keep the `commitments` table in PostgreSQL. All rows have `status='migrated'` — this is our historical archive.

---

## Bump Cache Version

In `outputs/static/index.html` line 295:
```html
<!-- BEFORE -->
<script src="/static/app.js?v=42"></script>

<!-- AFTER -->
<script src="/static/app.js?v=43"></script>
```

(Coordinate with E3 brief — if both ship together, bump once to `?v=43`.)

---

## DO NOT Touch

- `memory/store_back.py` — AI Head area
- `outputs/dashboard.py` — backend endpoints stay
- `triggers/*.py` — AI Head area
- The `commitments` PostgreSQL table — leave it as historical archive

---

## Testing

1. Open dashboard, verify sidebar has no "Commitments" item (it was already removed)
2. Click "Obligations" tab — verify it loads only deadlines (no commitment cards mixed in)
3. Verify dismiss and reschedule buttons still work on deadline items
4. Open browser console — no 404s or JS errors
5. Verify the landing page Obligations grid cell still works (it fetches deadlines directly, not commitments)

---

## Acceptance Criteria

- [ ] No `loadCommitmentsTab` function in `app.js`
- [ ] `FUNCTIONAL_TABS` and `TAB_VIEW_MAP` have no `commitments` entry
- [ ] `loadDeadlinesTab()` only fetches `/api/deadlines`, not `/api/commitments`
- [ ] No `.commitment-card` CSS injected
- [ ] Dashboard loads cleanly with no console errors
- [ ] Obligations tab shows deadlines correctly
- [ ] Backend `/api/commitments` endpoint still exists (just not called from frontend)
