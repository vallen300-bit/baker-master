# BRIEF: Documents Section Redesign — Search-First

**Priority:** Medium — current layout shows 4,728 cards, unusable
**Ticket:** DOCUMENTS-REDESIGN-1
**Reference:** ClaimsMax Document Intelligence search page (brisen.claimsmax.co.uk)

## Problem

The Documents section dumps all 4,728 documents as cards on page load. Nobody scrolls through that. Dates are wrong (showing ingestion date, not document date). The only useful feature is matter-based search, buried in a filter.

## Solution

Search-first design inspired by ClaimsMax. Empty results area until you search or filter. Left sidebar with faceted filters. Compact result rows, not cards.

## Layout

### Default State (no search yet)

```
┌─────────────────────┬──────────────────────────────────────────┐
│                     │  🔍 [Search documents...]      [Search]  │
│ ▾ MATTER            ├──────────────────────────────────────────┤
│   □ Hagenauer  847  │                                          │
│   □ Kempinski  312  │     Search for documents, invoices,      │
│   □ MORV       290  │     contracts, or emails.                │
│   □ Baden-Baden 156 │                                          │
│   □ Cap Ferrat  98  │     4,728 documents indexed.             │
│   □ ...             │                                          │
│                     │                                          │
│ ▸ TYPE              │                                          │
│   (invoice, contract│                                          │
│    email, meeting,  │                                          │
│    document, other) │                                          │
│                     │                                          │
│ ▸ SOURCE            │                                          │
│   (dropbox, email,  │                                          │
│    whatsapp, clickup│                                          │
│    fireflies)       │                                          │
└─────────────────────┴──────────────────────────────────────────┘
```

### After Search

```
┌─────────────────────┬──────────────────────────────────────────┐
│                     │  🔍 [Baden-Baden invoice]       [Search] │
│ ▾ MATTER            ├──────────────────────────────────────────┤
│   ■ Baden-Baden 156 │  156 results · Relevance ▾              │
│   □ Hagenauer   0   │                                          │
│   ...               │  ● Invoice · Baden-Baden · 3 May 2024   │
│                     │  Asteco Ltd advance payment — plastering │
│ ▾ TYPE              │  works, €33,000, LCG Services            │
│   ■ Invoice    236  │  [Ask Baker] [Save to Dossiers]          │
│   □ Financial   89  │  ─────────────────────────────────────── │
│   □ Contract     9  │  ● Invoice · Baden-Baden · 25 Nov 2024  │
│   ...               │  Consulting fee Balgerstrasse 7, €50,000 │
│                     │  MRCI&IGmbH · Interexperts SA            │
│ ▸ SOURCE            │  [Ask Baker] [Save to Dossiers]          │
│                     │  ─────────────────────────────────────── │
│                     │  ● Contract · Baden-Baden · 12 Jan 2024  │
│                     │  ...                                      │
│                     │                                          │
│                     │  [Load more — 136 remaining]             │
└─────────────────────┴──────────────────────────────────────────┘
```

## Implementation

### Change 1: Replace Documents view HTML

**File:** `outputs/static/index.html`

Replace the existing `viewDocuments` div content:

```html
<div class="view" id="viewDocuments">
    <div class="docs-layout">
        <!-- Left: Filters -->
        <div class="docs-filters">
            <div class="docs-filter-section" id="docFilterMatter">
                <div class="docs-filter-header" onclick="toggleDocFilter('matter')">
                    ▾ MATTER
                </div>
                <div class="docs-filter-body" id="docFilterMatterBody"></div>
            </div>
            <div class="docs-filter-section" id="docFilterType">
                <div class="docs-filter-header" onclick="toggleDocFilter('type')">
                    ▸ TYPE
                </div>
                <div class="docs-filter-body" id="docFilterTypeBody" style="display:none;"></div>
            </div>
            <div class="docs-filter-section" id="docFilterSource">
                <div class="docs-filter-header" onclick="toggleDocFilter('source')">
                    ▸ SOURCE
                </div>
                <div class="docs-filter-body" id="docFilterSourceBody" style="display:none;"></div>
            </div>
        </div>

        <!-- Right: Search + Results -->
        <div class="docs-main">
            <div class="docs-search-bar">
                <input type="text" id="docSearchInput" class="docs-search-input"
                    placeholder="Search documents, invoices, contracts..."
                    onkeydown="if(event.key==='Enter')searchDocuments()" />
                <button class="docs-search-btn" onclick="searchDocuments()">Search</button>
            </div>
            <div class="docs-result-meta" id="docResultMeta" style="display:none;">
                <span id="docResultCount"></span>
                <select id="docSortBy" onchange="searchDocuments()">
                    <option value="relevance">Relevance</option>
                    <option value="date_desc">Newest first</option>
                    <option value="date_asc">Oldest first</option>
                </select>
            </div>
            <div id="docResults" class="docs-results">
                <div class="docs-empty-state">
                    <div style="font-size:15px;color:var(--text2);margin-bottom:8px;">Search for documents, invoices, contracts, or emails.</div>
                    <div style="font-size:13px;color:var(--text3);" id="docTotalCount">Loading...</div>
                </div>
            </div>
            <button class="docs-load-more" id="docLoadMore" style="display:none;" onclick="loadMoreDocuments()">Load more</button>
        </div>
    </div>
</div>
```

### Change 2: CSS

**File:** `outputs/static/style.css`

```css
/* DOCUMENTS-REDESIGN-1 */
.docs-layout { display: flex; gap: 0; height: 100%; }
.docs-filters { width: 220px; flex-shrink: 0; border-right: 1px solid var(--border); padding: 12px 0; overflow-y: auto; }
.docs-main { flex: 1; display: flex; flex-direction: column; overflow-y: auto; }
.docs-filter-header { padding: 8px 14px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text3); cursor: pointer; }
.docs-filter-header:hover { color: var(--text2); }
.docs-filter-body { padding: 0 14px 8px; }
.docs-filter-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; color: var(--text2); cursor: pointer; }
.docs-filter-item:hover { color: var(--text1); }
.docs-filter-item input[type="checkbox"] { accent-color: var(--blue); }
.docs-filter-count { margin-left: auto; font-size: 11px; color: var(--text4); }
.docs-search-bar { display: flex; gap: 8px; padding: 16px; border-bottom: 1px solid var(--border); }
.docs-search-input { flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg1); color: var(--text1); font-size: 14px; }
.docs-search-input:focus { outline: none; border-color: var(--blue); }
.docs-search-btn { padding: 10px 20px; border-radius: 8px; border: none; background: var(--blue); color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; }
.docs-search-btn:hover { opacity: 0.9; }
.docs-result-meta { display: flex; align-items: center; justify-content: space-between; padding: 8px 16px; font-size: 12px; color: var(--text3); border-bottom: 1px solid var(--border); }
.docs-result-meta select { background: var(--bg1); color: var(--text2); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 12px; }
.docs-results { flex: 1; overflow-y: auto; padding: 0 16px; }
.docs-empty-state { text-align: center; padding: 60px 20px; }
.doc-row { padding: 14px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.doc-row-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.doc-type-badge { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; }
.doc-type-badge.invoice { background: rgba(78,205,196,0.15); color: #4ecdc4; }
.doc-type-badge.contract { background: rgba(212,175,55,0.15); color: #d4af37; }
.doc-type-badge.email { background: rgba(100,149,237,0.15); color: #6495ed; }
.doc-type-badge.meeting { background: rgba(186,85,211,0.15); color: #ba55d3; }
.doc-type-badge.document { background: rgba(255,255,255,0.08); color: var(--text3); }
.doc-matter-tag { font-size: 11px; color: var(--text3); }
.doc-date { font-size: 11px; color: var(--text4); margin-left: auto; }
.doc-title { font-size: 14px; font-weight: 500; color: var(--text1); margin-bottom: 4px; }
.doc-summary { font-size: 12px; color: var(--text3); line-height: 1.4; margin-bottom: 6px; }
.doc-actions { display: flex; gap: 6px; }
.doc-actions button { font-size: 11px; padding: 3px 10px; border: 1px solid var(--border); background: var(--bg1); color: var(--text2); border-radius: 4px; cursor: pointer; }
.doc-actions button:hover { color: var(--text1); border-color: var(--text3); }
.docs-load-more { display: block; margin: 12px auto; padding: 8px 24px; border: 1px solid var(--border); background: var(--bg1); color: var(--text2); border-radius: 6px; cursor: pointer; font-size: 13px; }
.docs-load-more:hover { color: var(--text1); }
```

### Change 3: Backend — Documents search endpoint

**File:** `outputs/dashboard.py`

The existing `/api/documents` endpoint probably returns all documents. We need a search-oriented endpoint.

**New endpoint:** `GET /api/documents/search`

```python
@app.get("/api/documents/search", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def search_documents(
    q: str = "",
    matter: str = None,
    doc_type: str = None,
    source: str = None,
    sort: str = "relevance",
    offset: int = 0,
    limit: int = 20,
):
    """Search documents with filters. Returns compact results for list view."""
```

Query logic:
1. If `q` is provided → use Qdrant semantic search on `baker-documents` collection, filtered by metadata
2. If only filters (no `q`) → PostgreSQL query on `documents` table with WHERE clauses
3. Sort: relevance (Qdrant score), date_desc, date_asc
4. Return: `{results: [...], total: N, offset: N}`

Each result item:
```json
{
    "id": "doc_abc123",
    "title": "Asteco invoice INV00047",
    "document_type": "invoice",
    "matter": "baden-baden",
    "source": "dropbox",
    "date": "2024-05-03",
    "summary": "Sales invoice from Asteco Ltd to LCG Services for advance payment...",
    "score": 0.92
}
```

**New endpoint:** `GET /api/documents/facets`

Returns filter counts for the sidebar:
```json
{
    "matters": [{"name": "Hagenauer", "count": 847}, ...],
    "types": [{"name": "invoice", "count": 1200}, ...],
    "sources": [{"name": "dropbox", "count": 3100}, ...],
    "total": 4728
}
```

Query:
```sql
SELECT document_type, COUNT(*) FROM documents GROUP BY document_type ORDER BY COUNT(*) DESC;
SELECT matter, COUNT(*) FROM documents WHERE matter IS NOT NULL GROUP BY matter ORDER BY COUNT(*) DESC LIMIT 20;
SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY COUNT(*) DESC;
```

**Important:** Check the actual `documents` table schema first:
```sql
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'documents';
```

### Change 4: Frontend — Search + Filter Logic

**File:** `outputs/static/app.js`

Replace the existing `loadDocumentsTab()` function with:

```javascript
// State
var _docFilters = { matter: [], type: [], source: [] };
var _docOffset = 0;
var _docResults = [];

async function loadDocumentsTab() {
    // Load facets for sidebar filters
    try {
        var resp = await bakerFetch('/api/documents/facets');
        if (resp.ok) {
            var facets = await resp.json();
            _renderDocFacets('docFilterMatterBody', facets.matters || [], 'matter');
            _renderDocFacets('docFilterTypeBody', facets.types || [], 'type');
            _renderDocFacets('docFilterSourceBody', facets.sources || [], 'source');
            setText('docTotalCount', (facets.total || 0).toLocaleString() + ' documents indexed.');
        }
    } catch (e) {
        console.error('loadDocumentsTab facets failed:', e);
    }
}

function _renderDocFacets(containerId, items, filterKey) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.textContent = '';
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var row = document.createElement('label');
        row.className = 'docs-filter-item';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.dataset.filter = filterKey;
        cb.dataset.value = item.name;
        cb.addEventListener('change', function() { _onDocFilterChange(); });
        row.appendChild(cb);
        var lbl = document.createElement('span');
        lbl.textContent = item.name;
        row.appendChild(lbl);
        var cnt = document.createElement('span');
        cnt.className = 'docs-filter-count';
        cnt.textContent = item.count;
        row.appendChild(cnt);
        container.appendChild(row);
    }
}

function _onDocFilterChange() {
    // Collect all checked filters
    _docFilters = { matter: [], type: [], source: [] };
    document.querySelectorAll('.docs-filter-item input:checked').forEach(function(cb) {
        _docFilters[cb.dataset.filter].push(cb.dataset.value);
    });
    _docOffset = 0;
    searchDocuments();
}

async function searchDocuments() {
    var q = (document.getElementById('docSearchInput') || {}).value || '';
    var sort = (document.getElementById('docSortBy') || {}).value || 'relevance';

    // Build query params
    var params = new URLSearchParams();
    if (q) params.set('q', q);
    if (_docFilters.matter.length) params.set('matter', _docFilters.matter.join(','));
    if (_docFilters.type.length) params.set('doc_type', _docFilters.type.join(','));
    if (_docFilters.source.length) params.set('source', _docFilters.source.join(','));
    params.set('sort', sort);
    params.set('offset', _docOffset);
    params.set('limit', 20);

    // Don't search if nothing specified
    if (!q && !_docFilters.matter.length && !_docFilters.type.length && !_docFilters.source.length) {
        return; // Stay on empty state
    }

    var container = document.getElementById('docResults');
    if (_docOffset === 0 && container) {
        container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3);">Searching...</div>';
    }

    try {
        var resp = await bakerFetch('/api/documents/search?' + params.toString());
        if (!resp.ok) throw new Error('API ' + resp.status);
        var data = await resp.json();

        if (_docOffset === 0 && container) container.textContent = '';

        // Show result meta
        var meta = document.getElementById('docResultMeta');
        if (meta) {
            meta.style.display = 'flex';
            var countEl = document.getElementById('docResultCount');
            if (countEl) countEl.textContent = data.total + ' results';
        }

        // Render result rows
        _renderDocResults(container, data.results || []);
        _docResults = _docResults.concat(data.results || []);

        // Load more button
        var loadMore = document.getElementById('docLoadMore');
        var remaining = data.total - _docOffset - (data.results || []).length;
        if (loadMore) {
            if (remaining > 0) {
                loadMore.style.display = 'block';
                loadMore.textContent = 'Load more — ' + remaining + ' remaining';
            } else {
                loadMore.style.display = 'none';
            }
        }
    } catch (e) {
        if (container) container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3);">Search failed: ' + e.message + '</div>';
    }
}

function loadMoreDocuments() {
    _docOffset += 20;
    searchDocuments();
}

function _renderDocResults(container, results) {
    for (var i = 0; i < results.length; i++) {
        var doc = results[i];
        var row = document.createElement('div');
        row.className = 'doc-row';

        var typeBadge = '<span class="doc-type-badge ' + (doc.document_type || 'document') + '">' + esc(doc.document_type || 'document') + '</span>';
        var matterTag = doc.matter ? '<span class="doc-matter-tag">' + esc(doc.matter) + '</span>' : '';
        var dateTag = doc.date ? '<span class="doc-date">' + esc(doc.date) + '</span>' : '';

        row.innerHTML =
            '<div class="doc-row-header">' + typeBadge + matterTag + dateTag + '</div>' +
            '<div class="doc-title">' + esc(doc.title || 'Untitled') + '</div>' +
            (doc.summary ? '<div class="doc-summary">' + esc(doc.summary) + '</div>' : '') +
            '<div class="doc-actions"></div>';

        // Action buttons
        var actions = row.querySelector('.doc-actions');
        _addDocAction(actions, 'Ask Baker', doc);
        _addDocAction(actions, 'Save', doc);

        container.appendChild(row);
    }
}

function _addDocAction(container, label, doc) {
    var btn = document.createElement('button');
    btn.textContent = label;
    if (label === 'Ask Baker') {
        btn.addEventListener('click', function() {
            _triggerScanQuestion('Analyze this document: "' + doc.title + '". ' + (doc.summary || ''));
        });
    } else if (label === 'Save') {
        btn.addEventListener('click', function() {
            _saveToDossiers(btn, 'Document: ' + doc.title, doc.summary || doc.title);
        });
    }
    container.appendChild(btn);
}

function toggleDocFilter(key) {
    var body = document.getElementById('docFilter' + key.charAt(0).toUpperCase() + key.slice(1) + 'Body');
    var header = body ? body.previousElementSibling : null;
    if (body) {
        var show = body.style.display === 'none';
        body.style.display = show ? '' : 'none';
        if (header) header.textContent = (show ? '▾ ' : '▸ ') + key.toUpperCase();
    }
}
```

### Change 5: Remove existing document card rendering

**File:** `outputs/static/app.js`

Find the existing `loadDocumentsTab()` function and replace it entirely with the new code from Change 4. The old function that renders 4,728 cards should be deleted.

## Files to Modify

| File | Change |
|------|--------|
| `outputs/static/index.html` | Replace viewDocuments content, CSS v++ |
| `outputs/static/style.css` | Documents redesign CSS |
| `outputs/dashboard.py` | `GET /api/documents/search` + `GET /api/documents/facets` |
| `outputs/static/app.js` | Replace loadDocumentsTab, add search/filter/render functions, JS v++ |

## Key Decisions

1. **No results on page load** — just filters + empty state with total count
2. **Filters trigger search** — checking a filter checkbox runs the search
3. **Search uses Qdrant** for semantic relevance when query text is provided
4. **Filters-only uses PostgreSQL** for fast faceted queries
5. **20 results per page** with "Load more" (not pagination — simpler)
6. **Compact rows, not cards** — title + type badge + matter + date + summary on 3-4 lines

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

Test:
1. Open Documents — empty state, filters visible with counts
2. Type "Baden-Baden invoice" → results appear with type badges
3. Check "Invoice" filter → results narrow
4. Click "Ask Baker" on a result → switches to Ask Baker with pre-filled question
5. "Load more" works for paginated results

## Schema Check (MUST do before coding)

```sql
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'documents' ORDER BY ordinal_position;
```

Adapt all SQL queries to match actual column names. Lesson #2 and #3 from tasks/lessons.md: column name mismatches are silent killers.
