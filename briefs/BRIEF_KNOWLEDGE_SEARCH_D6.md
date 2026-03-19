# BRIEF: Knowledge Base Search UI (D6)

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 27)
**Priority:** Medium — backend API exists, no frontend yet
**Branch:** `feat/knowledge-search-d6`

## Context

- Backend endpoint already deployed: `GET /api/search/unified?q=...&limit=20&sources=emails,meetings,whatsapp,documents,conversations`
- Returns: `{"query": "...", "results": [{source, content, score, metadata, token_estimate}], "total": N, "sources_searched": [...]}`
- Each result has `source` (one of: `emails`, `meetings`, `document`, `whatsapp`, `conversation`), `content` (first 500 chars), `score` (0-1 relevance), and `metadata` dict (varies by source: date, sender, label, filename, etc.)
- The existing Search tab (`viewSearch`) is an **alert-only search** (calls `/api/alerts/search`). D6 replaces it with a unified knowledge base search. The old alert search functionality already lives in the Fires tab (filter + search there).
- Sidebar already has `data-tab="search"` and `switchTab` calls `loadSearchTab()`
- Current cache versions: `style.css?v=36`, `app.js?v=43`

## What to Build

Replace the current Search tab with a unified knowledge base search UI that feels like a fast search engine, not a chat.

## Deliverables

### 1. Replace `loadSearchTab()` in app.js

Remove the existing `loadSearchTab()` + `executeSearch()` functions (lines ~2976-3084) and replace with new unified search implementation.

**State variables:**
```js
var _kbSearchQuery = '';
var _kbSourceFilter = '';  // '' = all, or 'emails', 'meetings', etc.
var _kbResults = [];
var _kbSearchInitialized = false;
```

**`loadSearchTab()` must:**
1. Build the search bar + source filter chips (only once, guard with `_kbSearchInitialized`)
2. Focus the search input on tab switch

### 2. Search Bar

- Full-width input at the top of `#searchFilters`
- Placeholder: `"Search across all Baker content..."`
- Style: match the Documents tab search input (`padding:8px 12px; border:1px solid var(--border); border-radius:8px; font-size:13px; font-family:var(--font); background:var(--bg); width:100%;`)
- **Enter key triggers search** (not character-by-character debounce)
- A "Search" button to the right of the input (class `run-btn`, already styled)
- `maxLength="500"`

### 3. Source Filter Chips

Below the search bar, a row of clickable chips:

| Chip label | `sources` param value | Color when active |
|---|---|---|
| All | _(empty = all)_ | `var(--blue)` |
| Emails | `emails` | `#2563eb` (blue) |
| Meetings | `meetings` | `#7c3aed` (purple) |
| Documents | `documents` | `#16a34a` (green) |
| WhatsApp | `whatsapp` | `#0d9488` (teal) |
| Conversations | `conversations` | `rgba(0,0,0,0.45)` (gray) |

**Chip implementation:**
- Build chips using DOM methods (no innerHTML with untrusted data)
- Each chip is a `<button>` with class `kb-chip` (new CSS class, see section 7)
- Active chip gets class `kb-chip active` — background filled with its color, white text
- "All" is active by default
- Clicking a chip sets `_kbSourceFilter` and re-runs the search if there are results (don't re-search on empty query)
- Only one chip active at a time

### 4. Search Execution

```js
async function executeKBSearch() {
    var q = _kbSearchQuery.trim();
    if (q.length < 2) return;

    var results = document.getElementById('searchResults');
    showLoading(results, 'Searching');

    var params = new URLSearchParams();
    params.set('q', q);
    params.set('limit', '30');
    if (_kbSourceFilter) params.set('sources', _kbSourceFilter);

    try {
        var resp = await bakerFetch('/api/search/unified?' + params.toString());
        if (!resp.ok) throw new Error('API ' + resp.status);
        var data = await resp.json();
        _kbResults = data.results || [];
        renderKBResults(data);
    } catch (e) {
        results.textContent = 'Search failed. Try again.';
    }
}
```

### 5. Result Rendering

**Result count header:**
```
23 results across emails, meetings, documents    (or "No results found")
```
Style: `font-size:12px; color:var(--text3); margin:12px 0 8px;`

**Each result card (`renderKBResultCard`):**
```html
<div class="kb-result" data-index="0">
  <div class="kb-result-header">
    <span class="kb-source-badge kb-source-emails">EMAIL</span>
    <span class="kb-result-title">{title or label from metadata}</span>
    <span class="kb-result-score">{score as percentage, e.g. "87%"}</span>
    <span class="kb-result-date">{formatted date}</span>
  </div>
  <div class="kb-result-body">{content preview, truncated to ~200 chars}</div>
  <div class="kb-result-meta">{sender or filename or other metadata}</div>
</div>
```

**Title extraction from metadata** (varies by source):
- `emails`: `metadata.subject` or `metadata.label` or first line of content
- `meetings`: `metadata.title` or `metadata.label`
- `document`: `metadata.filename` or `metadata.label`
- `whatsapp`: `metadata.sender_name` or `metadata.chat` or "WhatsApp message"
- `conversation`: `metadata.label` or "Past conversation"

**Date extraction from metadata:**
- Try `metadata.date`, `metadata.received_at`, `metadata.timestamp`, `metadata.ingested_at`
- Format as relative if <7 days ("2d ago", "5h ago"), otherwise "Mar 14, 2026"
- Use a helper function `formatRelativeDate(dateStr)`

**Source badge colors (CSS classes):**
| Source | Badge text | Background |
|---|---|---|
| `emails` | EMAIL | `#2563eb` |
| `meetings` | MEETING | `#7c3aed` |
| `document` | DOC | `#16a34a` |
| `whatsapp` | WHATSAPP | `#0d9488` |
| `conversation` | MEMORY | `rgba(0,0,0,0.45)` |

**Click to expand:**
- Clicking a result card toggles class `kb-result-expanded`
- When expanded, show the full `content` (all 500 chars) in a `kb-result-full` div
- The expanded view replaces the truncated `kb-result-body`
- Second click collapses back to preview

**Build all card HTML using `esc()` for every dynamic value.** Use `setSafeHTML()` to inject the final assembled HTML string.

### 6. Empty State

Before any search is executed, show:
```html
<div class="kb-empty">
  <div class="kb-empty-icon">&#x1F50D;</div>
  <div class="kb-empty-title">Search Baker's Knowledge Base</div>
  <div class="kb-empty-desc">Find anything across emails, meetings, documents, WhatsApp messages, and past conversations.</div>
</div>
```

Center it vertically in the results area. Style:
- `kb-empty`: `text-align:center; padding:80px 20px; color:var(--text3);`
- `kb-empty-icon`: `font-size:48px; margin-bottom:16px; opacity:0.4;`
- `kb-empty-title`: `font-size:16px; font-weight:600; color:var(--text2); margin-bottom:8px;`
- `kb-empty-desc`: `font-size:13px; line-height:1.6;`

### 7. CSS (add to style.css)

Add these classes at the end of `style.css`:

```css
/* ═══ D6: Knowledge Base Search ═══ */
.kb-chip {
  font-size: 11px; padding: 5px 14px; border-radius: 16px;
  border: 1px solid var(--border); background: var(--bg);
  color: var(--text2); cursor: pointer; font-family: var(--font);
  font-weight: 500; transition: all 0.15s;
}
.kb-chip:hover { border-color: var(--text3); }
.kb-chip.active { color: #fff; border-color: transparent; }

.kb-result {
  padding: 14px 18px; border: 1px solid var(--border-light);
  border-radius: var(--radius-sm); margin-bottom: 8px;
  background: var(--card); cursor: pointer; transition: border-color 0.15s;
}
.kb-result:hover { border-color: var(--blue); }
.kb-result-expanded { border-color: var(--blue); background: var(--bg-subtle); }

.kb-result-header {
  display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
}
.kb-source-badge {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  padding: 2px 8px; border-radius: 4px; color: #fff;
  text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0;
}
.kb-source-emails { background: #2563eb; }
.kb-source-meetings { background: #7c3aed; }
.kb-source-document { background: #16a34a; }
.kb-source-whatsapp { background: #0d9488; }
.kb-source-conversation { background: rgba(0,0,0,0.45); }

.kb-result-title {
  font-weight: 600; font-size: 13px; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kb-result-score {
  font-family: var(--mono); font-size: 10px; color: var(--text3);
  flex-shrink: 0;
}
.kb-result-date {
  font-size: 11px; color: var(--text3); flex-shrink: 0; white-space: nowrap;
}
.kb-result-body {
  font-size: 12px; color: var(--text2); line-height: 1.6;
  overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.kb-result-full {
  font-size: 12px; color: var(--text2); line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}
.kb-result-meta {
  font-size: 11px; color: var(--text3); margin-top: 4px;
}
```

### 8. Update index.html viewSearch block

The existing HTML block:
```html
<!-- VIEW: Search -->
<div class="view" id="viewSearch">
    <div class="section-label">Search</div>
    <div id="searchFilters"></div>
    <div id="searchResults"></div>
</div>
```

Change the section-label text from "Search" to "Knowledge Base". Keep the element IDs the same (`searchFilters`, `searchResults`) so the JS wires up correctly.

### 9. Cache Bust

Bump versions:
- `style.css?v=36` -> `style.css?v=37`
- `app.js?v=43` -> `app.js?v=44`

## Code Patterns (must follow)

| Pattern | How |
|---------|-----|
| Auth | All API calls via `bakerFetch(url)` |
| XSS | Every dynamic string through `esc()`. Final HTML via `setSafeHTML()` |
| Loading | Use `showLoading(el, 'Searching')` (existing helper) |
| DOM building | Filter chips and inputs built with `document.createElement()` |
| Card HTML | String concatenation with `esc()` values is fine (existing pattern in `renderAlertCard`, `renderFireCompact`) |
| State guard | `_kbSearchInitialized` flag to avoid re-building UI on tab re-entry |

## DO NOT Touch

- `outputs/dashboard.py` -- backend is done, no changes needed
- `memory/*.py`, `orchestrator/*.py`, `triggers/*.py` -- AI Head area
- `outputs/static/mobile.html`, `outputs/static/mobile.js` -- separate mobile app

## API Reference

**Endpoint:** `GET /api/search/unified`

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `q` | string (required) | -- | Min 2 chars, max 500 |
| `limit` | int | 20 | 1-50 |
| `sources` | string | all | Comma-separated: `emails,meetings,whatsapp,documents,conversations` |

**Response:**
```json
{
  "query": "hagenauer damage",
  "results": [
    {
      "source": "emails",
      "content": "First 500 chars of the email thread about Hagenauer...",
      "score": 0.847,
      "metadata": {
        "subject": "Re: Hagenauer - Damage Report",
        "date": "2026-03-10T14:22:00",
        "sender": "sandra@example.com",
        "label": "Hagenauer damage report"
      },
      "token_estimate": 312
    },
    {
      "source": "document",
      "content": "Vertrag uber die Durchfuhrung von Sanierungsarbeiten...",
      "score": 0.792,
      "metadata": {
        "filename": "Hagenauer_Vertrag_2024.pdf",
        "date": "2024-11-15",
        "label": "contract"
      },
      "token_estimate": 289
    }
  ],
  "total": 23,
  "sources_searched": ["emails", "meetings", "whatsapp", "documents", "conversations"]
}
```

## Acceptance Criteria

1. **Tab works:** Click "Search" in sidebar -> shows search bar + source chips + empty state
2. **Search executes:** Type query + Enter (or click Search button) -> loading state -> results appear
3. **Source filtering:** Click "Emails" chip -> only email results shown; click "All" -> all sources
4. **Source badges:** Each result shows colored source badge (EMAIL blue, MEETING purple, DOC green, WHATSAPP teal, MEMORY gray)
5. **Result cards:** Show title, content preview (2 lines), date, relevance score
6. **Click to expand:** Click a result -> toggles expanded view with full content
7. **No results:** Shows "No results found for '...'" message
8. **Empty state:** Before searching, shows centered empty state with description
9. **XSS safe:** All dynamic text escaped with `esc()`, no raw innerHTML with user data
10. **Fast feel:** Loading state appears instantly, results render in <1s on typical queries
11. **Cache busted:** CSS v37, JS v44
