# BRIEF: Document Browser (D2)

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 26)
**Priority:** High — 3,665 documents stored, zero UI to browse them
**Branch:** `feat/document-browser-1`

## Context

- 3,665 documents in `documents` PostgreSQL table (contracts, invoices, proposals, etc.)
- Full-text stored, Haiku-classified (14 types), matter-tagged, extraction pipeline complete
- Only accessible by asking Baker in chat — no browse/search UI
- Desktop has many tabs but no "Documents" tab

## Deliverables

### 1. New endpoint: GET /api/documents
- Query params: `?search=`, `?doc_type=`, `?matter_slug=`, `?limit=`, `?offset=`
- Returns JSON: `{documents: [{id, filename, doc_type, matter_slug, source_path, ingested_at, text_preview}], total: N}`
- `text_preview`: first 200 chars of full_text
- Default: limit=20, ordered by ingested_at DESC
- Auth: X-Baker-Key
- **File:** `outputs/dashboard.py`

### 2. Documents Tab on Desktop
- Add "Documents" to `FUNCTIONAL_TABS`
- Replace the stale "Commitments" tab in the sidebar navigation
- **Files:** `outputs/static/app.js`, `outputs/static/index.html`

### 3. Document List View
- Search bar at top (full-text search, debounced 300ms)
- Filter chips: doc_type (contract, invoice, correspondence, etc.) + matter_slug
- Document cards: filename, type badge, matter tag, date, preview snippet
- Click to expand: full text in a scrollable panel (max 2000 chars, "Show more" button)
- **Files:** `outputs/static/app.js`, `outputs/static/index.html`

### 4. Document Stats Header
- "3,665 documents | 14 types | Top matter: hagenauer (423)"
- Fetched from a simple count endpoint or inline in the list response
- **Files:** `outputs/static/app.js`

## Database Schema (existing)
```sql
documents (
  id SERIAL, filename TEXT, source_path TEXT, full_text TEXT,
  doc_type VARCHAR(50), matter_slug VARCHAR(100),
  classification JSONB, extraction JSONB,
  ingested_at TIMESTAMP, tokens INT
)
```

## DO NOT Touch
- `memory/store_back.py`, `orchestrator/*.py`, `triggers/*.py` — AI Head area

## Test
1. Desktop: Documents tab appears in sidebar (replacing Commitments)
2. Search "Hagenauer" returns relevant documents
3. Filter by doc_type "contract" works
4. Click document expands text preview
5. Pagination works (load more button or scroll)
