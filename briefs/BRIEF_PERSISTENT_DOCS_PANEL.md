# BRIEF: Persistent Document Storage + Right Panel UI

## Context
Baker generates documents (PPTX, DOCX, XLSX, PDF) via the `baker-document` code fence in Scan responses. Currently, files are stored in `/tmp/` on Render with references in an in-memory Python dict (`GENERATED_FILES` in `document_generator.py`). When the Render server restarts (deploy, health check, auto-restart), both the dict and the files are lost. The download links return 404. The Director lost a 12-slide press deck this way on March 31.

Additionally, the "Ask Baker" and "Ask Specialist" views have a right-side artifact panel that is hidden (width=0) until a query runs, and empty between queries. This brief turns that panel into a persistent, always-visible workspace with two zones: Generated Files (top) and Drop/Upload (bottom).

## Estimated time: ~3 hours
## Complexity: Medium (DB schema + backend API + frontend UI)
## Cost impact: Zero — no API calls added. Pure DB storage + frontend.
## Prerequisites: None

---

## Part A: Persistent Document Storage (Backend)

### Problem
`document_generator.py` stores files in `/tmp/` and tracks them in `GENERATED_FILES = {}` (in-memory dict). Server restart = all lost. Director lost a 12-slide press deck (task #236) on March 31.

### Current State
- `document_generator.py` lines 30-98: `GENERATED_FILES = {}` dict, `generate_document()` writes to `/tmp/`, `get_file()` does dict lookup only
- `outputs/dashboard.py` line 7598: `/api/scan/download/{file_id}` serves via `FileResponse` from `/tmp/` path
- `outputs/static/app.js` line 3488: frontend calls `/api/scan/generate-document`, gets `download_url`, creates download card
- Existing upload endpoint at `app.js` line 7475 uses raw `fetch` (not `bakerFetch`) for FormData — the drop zone must follow this pattern

### Solution: New `generated_documents` PostgreSQL table + binary storage

**Why binary in DB (not Dropbox/S3)?**
- Documents are small (50KB–5MB typically)
- No external dependency needed
- Instant retrieval
- Survives all restarts
- Simple — one table, one query

### A1: Database Migration

**File:** `outputs/dashboard.py` — add to the `ensure_tables()` or startup migration block.

```sql
CREATE TABLE IF NOT EXISTS generated_documents (
    id              TEXT PRIMARY KEY,           -- UUID (same as current file_id)
    filename        TEXT NOT NULL,              -- e.g. "Press_Deck_2026-03-31.pptx"
    format          VARCHAR(10) NOT NULL,       -- docx, xlsx, pdf, pptx
    size_bytes      INTEGER NOT NULL,
    file_data       BYTEA NOT NULL,             -- the actual file binary
    title           TEXT,                       -- human-readable title
    source          VARCHAR(20) DEFAULT 'scan', -- scan, specialist, pipeline
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    downloaded_at   TIMESTAMPTZ,                -- track last download (nullable)
    expired         BOOLEAN DEFAULT FALSE       -- soft delete after 30 days
);

CREATE INDEX IF NOT EXISTS idx_gendocs_created ON generated_documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gendocs_expired ON generated_documents(expired) WHERE expired = FALSE;
```

**Sizing note:** At ~500KB average per document, 100 documents = 50MB. Well within Neon's storage tier.

### A2: Modify `document_generator.py`

**Current flow:**
1. Generate file in `/tmp/baker_{uuid}.{fmt}`
2. Store reference in `GENERATED_FILES` dict
3. Return `(file_id, filename, size_bytes)`

**New flow:**
1. Generate file in `/tmp/baker_{uuid}.{fmt}` (same as now)
2. Read binary content from the temp file
3. Store binary + metadata in `generated_documents` table
4. Delete temp file immediately
5. Return `(file_id, filename, size_bytes)`

**Replace the entire bottom section of `generate_document()`** (after the `generators[fmt]()` call):

```python
def generate_document(content, fmt, title, metadata=None):
    """Generate a document and store persistently in PostgreSQL."""
    generators = {
        "docx": _generate_docx,
        "xlsx": _generate_xlsx,
        "pdf": _generate_pdf,
        "pptx": _generate_pptx,
    }

    if fmt not in generators:
        raise ValueError(f"Unsupported format: {fmt}")

    file_id = str(uuid.uuid4())
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
    date_str = datetime.utcnow().strftime('%Y-%m-%d')
    filename = f"{safe_title}_{date_str}.{fmt}"

    # Generate into temp file
    tmp_dir = tempfile.gettempdir()
    filepath = os.path.join(tmp_dir, f"baker_{file_id}.{fmt}")
    generators[fmt](content, title, filepath, metadata)

    size_bytes = os.path.getsize(filepath)

    # Read binary and store in PostgreSQL
    with open(filepath, "rb") as f:
        file_data = f.read()

    _store_in_db(file_id, filename, fmt, size_bytes, file_data, title,
                 source=metadata.get("source", "scan") if metadata else "scan")

    # NOTE: Do NOT delete the temp file here. Keep it for immediate downloads
    # via the in-memory fast path. The cleanup_old_files() function handles
    # removing stale temp files after 24h.

    # Keep in-memory cache with filepath (fast path for immediate downloads)
    GENERATED_FILES[file_id] = {
        "file_id": file_id,
        "filepath": filepath,       # CRITICAL: must include filepath for download endpoint
        "filename": filename,
        "format": fmt,
        "size_bytes": size_bytes,
        "created_at": datetime.utcnow().isoformat(),
    }

    return file_id, filename, size_bytes


def _store_in_db(file_id, filename, fmt, size_bytes, file_data, title, source="scan"):
    """Persist generated document binary to PostgreSQL."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            logger.error("No DB connection — document will only be in memory")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO generated_documents (id, filename, format, size_bytes, file_data, title, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (file_id, filename, fmt, size_bytes, file_data, title, source))
            conn.commit()
            cur.close()
            logger.info(f"Document stored in DB: {filename} ({size_bytes} bytes)")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store document in DB: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"DB storage failed (non-fatal): {e}")


def get_file(file_id):
    """Retrieve file info. Check memory first, then DB."""
    # Fast path: in-memory (same server session)
    info = GENERATED_FILES.get(file_id)
    if info:
        return info

    # Slow path: load from PostgreSQL
    return _load_from_db(file_id)


def _load_from_db(file_id):
    """Load a generated document from PostgreSQL."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT filename, format, size_bytes, file_data
                FROM generated_documents
                WHERE id = %s AND expired = FALSE
            """, (file_id,))
            row = cur.fetchone()
            cur.close()
            if not row:
                return None

            # Write binary back to temp file for FileResponse
            tmp_dir = tempfile.gettempdir()
            filepath = os.path.join(tmp_dir, f"baker_{file_id}.{row[1]}")
            with open(filepath, "wb") as f:
                f.write(row[3])  # file_data (bytes)

            info = {
                "file_id": file_id,
                "filepath": filepath,
                "filename": row[0],
                "format": row[1],
                "size_bytes": row[2],
            }

            # Cache in memory for future requests
            GENERATED_FILES[file_id] = info

            # Update downloaded_at
            try:
                cur2 = conn.cursor()
                cur2.execute("""
                    UPDATE generated_documents SET downloaded_at = NOW() WHERE id = %s
                """, (file_id,))
                conn.commit()
                cur2.close()
            except Exception:
                conn.rollback()

            return info
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to load document from DB: {e}")
            return None
        finally:
            store._put_conn(conn)
    except Exception:
        return None


def list_generated_documents(limit=20):
    """List recent generated documents (for the right panel)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, filename, format, size_bytes, title, source, created_at
                FROM generated_documents
                WHERE expired = FALSE
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "file_id": r[0],
                    "filename": r[1],
                    "format": r[2],
                    "size_bytes": r[3],
                    "title": r[4],
                    "source": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                    "download_url": f"/api/scan/download/{r[0]}",
                }
                for r in rows
            ]
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to list generated documents: {e}")
            return []
        finally:
            store._put_conn(conn)
    except Exception:
        return []
```

### A3: Modify download endpoint in `dashboard.py`

**File:** `outputs/dashboard.py`, lines ~7598-7617

The current `download_document()` endpoint already calls `get_file(file_id)` — which now falls through to DB. But it also checks `os.path.exists(info["filepath"])` which would fail if the file isn't in `/tmp/` yet.

**Replace the existing endpoint** (lines 7598-7617):

```python
@app.get("/api/scan/download/{file_id}", tags=["scan"])
async def download_document(file_id: str):
    """Download a generated document. No auth — UUID acts as token."""
    info = get_file(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found or expired")

    filepath = info.get("filepath")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=410, detail="File no longer available")

    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return FileResponse(
        path=filepath,
        filename=info["filename"],
        media_type=media_types.get(info["format"], "application/octet-stream"),
    )
```

This works because `get_file()` → `_load_from_db()` writes the binary back to `/tmp/` before returning. The FileResponse serves from `/tmp/`, then the file can be cleaned up later.

### A4: New API endpoint — list generated documents

**File:** `outputs/dashboard.py` — add near the existing document endpoints:

```python
@app.get("/api/scan/generated-documents", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def list_generated_docs(limit: int = 20):
    """List recently generated documents for the right panel."""
    from document_generator import list_generated_documents
    docs = list_generated_documents(limit=limit)
    return {"documents": docs}
```

### A5: Cleanup cron — expire old documents

**File:** `document_generator.py` — update `cleanup_old_files()`:

```python
def cleanup_old_files(max_age_days=30):
    """Expire documents older than max_age_days in PostgreSQL. Call from scheduler."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE generated_documents
                SET expired = TRUE
                WHERE created_at < NOW() - make_interval(days => %s)
                  AND expired = FALSE
            """, (max_age_days,))
            count = cur.rowcount
            conn.commit()
            cur.close()
            if count:
                logger.info(f"Expired {count} old generated documents")
        except Exception as e:
            conn.rollback()
            logger.error(f"Document cleanup failed: {e}")
        finally:
            store._put_conn(conn)
    except Exception:
        pass

    # Also clean in-memory cache (still useful for temp files)
    now = datetime.utcnow()
    expired = []
    for fid, info in GENERATED_FILES.items():
        created_str = info.get("created_at")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                if (now - created).total_seconds() > 86400:  # 24h for in-memory
                    expired.append(fid)
            except Exception:
                pass
    for fid in expired:
        info = GENERATED_FILES.pop(fid, None)
        if info and info.get("filepath"):
            try:
                os.remove(info["filepath"])
            except OSError:
                pass
```

---

## Part B: Always-Visible Right Panel with Generated Files + Upload Zone

### Problem
The artifact panel (`#scanArtifactPanel`) is hidden (width=0) until a query runs. Between queries it's empty — wasted space. The Director wants it always visible with two persistent sections.

### B1: HTML Changes

**File:** `outputs/static/index.html`

**Replace the artifact panel divs** in both Ask Baker (line 297-299) and Ask Specialist (line 322-324) views:

For **Ask Baker** (replace lines 297-299):
```html
<div class="artifact-panel open" id="scanArtifactPanel">
    <div class="artifact-items" id="scanArtifactItems">
        <!-- Persistent content: generated files + upload zone -->
        <div id="scanPersistentContent">
            <div class="artifact-section-label">Generated Files</div>
            <div id="scanGeneratedFiles" class="generated-files-list">
                <div class="panel-empty-state">No documents yet. Ask Baker to generate one.</div>
            </div>
            <div class="panel-divider"></div>
            <div class="artifact-section-label">Upload Document</div>
            <div class="drop-zone" id="scanDropZone">
                <input type="file" id="scanDropInput" accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg" hidden multiple />
                <div class="drop-zone-icon">&#128206;</div>
                <div class="drop-zone-text">Drop file or click to upload</div>
                <div class="drop-zone-hint">PDF, DOCX, XLSX, CSV, TXT, PNG, JPG</div>
            </div>
            <div id="scanDropStatus" class="drop-status" hidden></div>
        </div>
    </div>
</div>
```

For **Ask Specialist** (replace lines 322-324):
```html
<div class="artifact-panel open" id="specialistArtifactPanel">
    <div class="artifact-items" id="specialistArtifactItems">
        <div id="specialistPersistentContent">
            <div class="artifact-section-label">Generated Files</div>
            <div id="specialistGeneratedFiles" class="generated-files-list">
                <div class="panel-empty-state">No documents yet.</div>
            </div>
            <div class="panel-divider"></div>
            <div class="artifact-section-label">Upload Document</div>
            <div class="drop-zone" id="specialistDropZone">
                <input type="file" id="specialistDropInput" accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg" hidden multiple />
                <div class="drop-zone-icon">&#128206;</div>
                <div class="drop-zone-text">Drop file or click to upload</div>
                <div class="drop-zone-hint">PDF, DOCX, XLSX, CSV, TXT, PNG, JPG</div>
            </div>
            <div id="specialistDropStatus" class="drop-status" hidden></div>
        </div>
    </div>
</div>
```

### B2: CSS Changes

**File:** `outputs/static/style.css`

Add after the existing `.artifact-download-meta` block (~line 970):

```css
/* === RIGHT PANEL: Always-visible persistent content === */

/* Panel starts open by default (class="artifact-panel open" in HTML) */

/* Generated files list */
.generated-files-list {
    display: flex; flex-direction: column; gap: 6px;
    max-height: calc(50vh - 120px); overflow-y: auto;
}

.gen-file-card {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px; background: var(--bg-subtle);
    border: 1px solid var(--border-light); border-radius: var(--radius-sm);
    text-decoration: none; color: var(--text);
    transition: border-color 0.15s, background 0.15s;
    cursor: pointer;
}
.gen-file-card:hover {
    border-color: var(--blue); background: var(--blue-bg);
}
.gen-file-icon { font-size: 16px; flex-shrink: 0; }
.gen-file-info { flex: 1; min-width: 0; }
.gen-file-title {
    font-size: 11px; font-weight: 600; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.gen-file-meta {
    font-size: 9px; color: var(--text3); margin-top: 1px;
}
.gen-file-dl {
    font-size: 10px; color: var(--blue); font-weight: 600; flex-shrink: 0;
}

/* Panel divider between sections */
.panel-divider {
    height: 1px; background: var(--border-light); margin: 12px 0;
}

/* Empty state */
.panel-empty-state {
    font-size: 11px; color: var(--text3); padding: 8px 0;
    font-style: italic;
}

/* Drop zone */
.drop-zone {
    border: 2px dashed var(--border);
    border-radius: var(--radius-sm);
    padding: 16px 12px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
}
.drop-zone:hover, .drop-zone.drag-over {
    border-color: var(--blue);
    background: var(--blue-bg);
}
.drop-zone-icon { font-size: 24px; margin-bottom: 4px; }
.drop-zone-text {
    font-size: 12px; font-weight: 500; color: var(--text2);
}
.drop-zone-hint {
    font-size: 9px; color: var(--text3); margin-top: 4px;
}

/* Upload progress */
.drop-status {
    font-size: 11px; padding: 6px 0; color: var(--text2);
}
.drop-status.success { color: var(--green); }
.drop-status.error { color: var(--red); }
```

### B3: JavaScript Changes

**File:** `outputs/static/app.js`

#### B3a: Load generated files on page load

Add near the top-level initialization (after `DOMContentLoaded` or near `loadMorningBrief()`):

```javascript
// ═══ GENERATED FILES PANEL ═══

function loadGeneratedFiles() {
    bakerFetch('/api/scan/generated-documents').then(function(resp) {
        if (!resp.ok) return;
        return resp.json();
    }).then(function(data) {
        if (!data || !data.documents) return;
        renderGeneratedFiles('scanGeneratedFiles', data.documents);
        renderGeneratedFiles('specialistGeneratedFiles', data.documents);
    }).catch(function(e) {
        console.warn('Failed to load generated files:', e);
    });
}

function renderGeneratedFiles(containerId, docs) {
    var container = document.getElementById(containerId);
    if (!container) return;

    if (!docs.length) {
        container.innerHTML = '<div class="panel-empty-state">No documents yet. Ask Baker to generate one.</div>';
        return;
    }

    container.innerHTML = '';
    var fmtIcons = { docx: '\uD83D\uDCC3', xlsx: '\uD83D\uDCCA', pdf: '\uD83D\uDCC4', pptx: '\uD83D\uDCCA' };
    var fmtLabels = { docx: 'Word', xlsx: 'Excel', pdf: 'PDF', pptx: 'PowerPoint' };

    for (var i = 0; i < docs.length; i++) {
        var doc = docs[i];
        var card = document.createElement('a');
        card.className = 'gen-file-card';
        card.href = doc.download_url;
        card.download = doc.filename;

        var icon = document.createElement('span');
        icon.className = 'gen-file-icon';
        icon.textContent = fmtIcons[doc.format] || '\uD83D\uDCC4';
        card.appendChild(icon);

        var info = document.createElement('div');
        info.className = 'gen-file-info';

        var title = document.createElement('div');
        title.className = 'gen-file-title';
        title.textContent = doc.title || doc.filename;
        info.appendChild(title);

        var meta = document.createElement('div');
        meta.className = 'gen-file-meta';
        var sizeKB = (doc.size_bytes / 1024).toFixed(0);
        var dateStr = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '';
        meta.textContent = (fmtLabels[doc.format] || doc.format) + ' \u00B7 ' + sizeKB + ' KB \u00B7 ' + dateStr;
        info.appendChild(meta);

        card.appendChild(info);

        var dl = document.createElement('span');
        dl.className = 'gen-file-dl';
        dl.textContent = '\u2B07';
        card.appendChild(dl);

        container.appendChild(card);
    }
}
```

Call `loadGeneratedFiles()` from the main init block (wherever `loadMorningBrief()` is called):
```javascript
loadGeneratedFiles();
```

#### B3b: Refresh the panel after document generation

In the existing `sendScanMessage()` function (~line 3497), after a successful document generation, add a call to refresh the panel:

**Find** (around line 3497-3500):
```javascript
            if (genRes.ok) {
                const genData = await genRes.json();
                replyEl.appendChild(_createDownloadCard(genData));
                addArtifactDownload(_itemsId, _panelId, genData);
            }
```

**Replace with:**
```javascript
            if (genRes.ok) {
                const genData = await genRes.json();
                replyEl.appendChild(_createDownloadCard(genData));
                addArtifactDownload(_itemsId, _panelId, genData);
                // Refresh persistent files list
                loadGeneratedFiles();
            }
```

#### B3c: Modify `clearArtifactPanel` to preserve persistent content

The current `clearArtifactPanel()` wipes everything. It should preserve the persistent sections.

**Find** (lines 74-79):
```javascript
function clearArtifactPanel(panelId, itemsId) {
    var panel = _artifactPanel(panelId);
    var items = _artifactItems(itemsId);
    if (items) items.textContent = '';
    if (panel) panel.classList.remove('open');
}
```

**Replace with:**
```javascript
function clearArtifactPanel(panelId, itemsId) {
    var items = _artifactItems(itemsId);
    if (!items) return;

    // Remove everything EXCEPT the persistent content div
    var children = Array.from(items.children);
    for (var i = 0; i < children.length; i++) {
        if (children[i].id && children[i].id.endsWith('PersistentContent')) continue;
        items.removeChild(children[i]);
    }
    // Panel stays open (persistent content always visible)
}
```

#### B3d: Drop zone — drag-and-drop + click upload

Add after the `loadGeneratedFiles` function:

```javascript
// ═══ DROP ZONE (Upload) ═══

function initDropZones() {
    _initDropZone('scanDropZone', 'scanDropInput', 'scanDropStatus');
    _initDropZone('specialistDropZone', 'specialistDropInput', 'specialistDropStatus');
}

function _initDropZone(zoneId, inputId, statusId) {
    var zone = document.getElementById(zoneId);
    var input = document.getElementById(inputId);
    if (!zone || !input) return;

    // Click to open file picker
    zone.addEventListener('click', function() { input.click(); });

    // File selected via picker
    input.addEventListener('change', function() {
        if (input.files.length) _uploadDroppedFiles(input.files, statusId);
        input.value = ''; // reset for re-upload
    });

    // Drag events
    zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', function() {
        zone.classList.remove('drag-over');
    });
    zone.addEventListener('drop', function(e) {
        e.preventDefault();
        zone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) {
            _uploadDroppedFiles(e.dataTransfer.files, statusId);
        }
    });
}

async function _uploadDroppedFiles(files, statusId) {
    var statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.hidden = false;
        statusEl.className = 'drop-status';
        statusEl.textContent = 'Uploading ' + files.length + ' file(s)...';
    }

    var successCount = 0;
    var errors = [];

    for (var i = 0; i < files.length; i++) {
        var formData = new FormData();
        formData.append('file', files[i]);
        try {
            // Use raw fetch (not bakerFetch) — matches existing upload pattern at app.js:7475
            var resp = await fetch('/api/documents/upload', {
                method: 'POST',
                headers: { 'X-Baker-Key': BAKER_CONFIG.apiKey },
                body: formData,
                // Note: don't set Content-Type — browser sets multipart boundary
            });
            if (resp.ok) {
                successCount++;
            } else {
                var err = await resp.json().catch(function() { return { detail: 'Upload failed' }; });
                errors.push(files[i].name + ': ' + (err.detail || 'error'));
            }
        } catch (e) {
            errors.push(files[i].name + ': ' + e.message);
        }
    }

    if (statusEl) {
        if (errors.length) {
            statusEl.className = 'drop-status error';
            statusEl.textContent = errors.join('; ');
        } else {
            statusEl.className = 'drop-status success';
            statusEl.textContent = successCount + ' file(s) uploaded successfully.';
        }
        setTimeout(function() { statusEl.hidden = true; }, 5000);
    }
}
```

Call `initDropZones()` from the main init block:
```javascript
initDropZones();
```

#### B3e: Note on upload pattern

The drop zone uses raw `fetch` (not `bakerFetch`) with manual `X-Baker-Key` header — matching the existing document upload pattern at `app.js` line 7475. This avoids any Content-Type conflicts with FormData. `bakerFetch` does NOT set Content-Type, so it would also work, but raw `fetch` is consistent with the existing code.

---

## Part C: Migration Path

### C1: Table creation — add to startup

**File:** `outputs/dashboard.py` — find the `@app.on_event("startup")` handler or equivalent. Add the `CREATE TABLE IF NOT EXISTS generated_documents` SQL there, alongside other table creation statements.

### C2: Import updates

**File:** `outputs/dashboard.py` — update the import line:

```python
# Old:
from document_generator import generate_document, get_file, cleanup_old_files

# New:
from document_generator import generate_document, get_file, cleanup_old_files, list_generated_documents
```

### C3: CSS cache bust

**File:** `outputs/static/index.html` — bump the CSS version:
```html
<link rel="stylesheet" href="/static/style.css?v=56">
```

---

## Files Modified
- `document_generator.py` — persistent storage in PostgreSQL (Part A2, A5)
- `outputs/dashboard.py` — table migration + new list endpoint + download fix (Part A1, A3, A4, C1, C2)
- `outputs/static/index.html` — always-open panel HTML with generated files + drop zone (Part B1, C3)
- `outputs/static/style.css` — new styles for file cards, drop zone, panel divider (Part B2)
- `outputs/static/app.js` — load/render generated files, drop zone init, clearArtifactPanel fix (Part B3)

## Do NOT Touch
- `orchestrator/pipeline.py` — pipeline document generation flow unchanged
- `orchestrator/agent.py` — agent tools unchanged
- `memory/retriever.py` — retrieval unchanged
- `triggers/` — all triggers unchanged

## Quality Checkpoints
1. Generate a document via Ask Baker → appears in right panel immediately
2. Restart the server → right panel still shows the document, download works
3. Drop a PDF onto the upload zone → ingested, appears in Documents tab
4. Ask Specialist generates a document → same panel, same persistent storage
5. Panel shows capabilities + sources DURING a query, then reverts to persistent content after

## Verification SQL
```sql
-- Check documents are being stored
SELECT id, filename, format, size_bytes, source, created_at
FROM generated_documents
WHERE expired = FALSE
ORDER BY created_at DESC
LIMIT 10;

-- Check no orphaned temp files building up (run on Render shell if needed)
-- ls -la /tmp/baker_*.{docx,xlsx,pdf,pptx} 2>/dev/null | wc -l
```

---

## Review Notes (Step 4 audit — /write-brief process)

**Bugs caught and fixed during review:**

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | CRITICAL | In-memory cache had no `filepath` — immediate downloads would 410 | Keep temp file, include `filepath` in GENERATED_FILES dict |
| 2 | MEDIUM | Drop zone used `bakerFetch` with nonexistent `rawBody` flag | Changed to raw `fetch` matching existing upload pattern (app.js:7475) |
| 3 | LOW | `INTERVAL '%s days'` — works via psycopg2 string sub but non-standard | Changed to `make_interval(days => %s)` |
| 4 | FORMAT | Missing "Current State" and "Cost impact" sections | Added both per brief template |

**Lessons.md items applied:**
- Lesson #2/#3: Verified no column name mismatches (new table, no conflicts with `documents` or `document_extractions`)
- Lesson #4: CSS cache bust included (`?v=56`)
- Lesson #8: Verification SQL and quality checkpoints included
- Lesson #11: Confirmed no duplicate endpoint at `/api/scan/generated-documents`
