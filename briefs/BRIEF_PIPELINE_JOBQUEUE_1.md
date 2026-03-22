# Brief: PIPELINE-JOBQUEUE-1 — Replace Thread-Based Document Pipeline with DB-Backed Job Queue

**Author:** AI Head (Session 21, from SPECIALIST-UPGRADE-1 architectural review)
**For:** Code 300
**Priority:** MEDIUM — prevents data loss on restart, adds observability for free

---

## Problem

`queue_extraction()` in `tools/document_pipeline.py` (line 266) spawns a `threading.Thread` per document. A module-level `_processing_lock` serializes all processing — only one document at a time.

Risks:
1. **Process restart = lost work.** If Render restarts mid-pipeline, all queued threads vanish. No record of what was pending.
2. **No observability.** Can't answer "how many documents are waiting for extraction?" or "which document failed?"
3. **No retry.** If extraction fails (network timeout, rate limit), the document is silently skipped forever.
4. **No backpressure.** 100 new Dropbox files = 100 threads created instantly (only 1 runs, 99 wait on the lock, consuming memory).

## What to Build

### Step 1: Add `pipeline_status` column to `documents` table

**Modify `memory/store_back.py` — `_ensure_documents_table()`:**

```python
cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_status VARCHAR(20) DEFAULT 'pending'")
cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_error TEXT")
cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_attempts INTEGER DEFAULT 0")
cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_pipeline ON documents(pipeline_status)")
```

Values: `pending` → `classifying` → `extracting` → `done` | `failed`

### Step 2: Update `store_document_full()` to set initial status

**Modify `memory/store_back.py` — `store_document_full()`:**

Add `pipeline_status = 'pending'` to the INSERT. On upsert (conflict), only reset to pending if the document's full_text actually changed:

```python
ON CONFLICT (file_hash) DO UPDATE SET
    source_path = EXCLUDED.source_path,
    full_text = EXCLUDED.full_text,
    token_count = EXCLUDED.token_count,
    search_vector = EXCLUDED.search_vector,
    pipeline_status = CASE
        WHEN documents.full_text IS DISTINCT FROM EXCLUDED.full_text THEN 'pending'
        ELSE documents.pipeline_status
    END,
    ingested_at = NOW()
```

### Step 3: Replace `queue_extraction()` with DB-driven processing

**Modify `tools/document_pipeline.py`:**

Replace `queue_extraction()`, `_safe_run_pipeline()`, and the thread/lock with:

```python
def process_pending_documents(batch_size: int = 5):
    """Process pending documents from DB queue. Called by scheduler."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor()
        # Grab a batch of pending docs (oldest first), skip recently failed
        cur.execute("""
            SELECT id, full_text, document_type
            FROM documents
            WHERE pipeline_status IN ('pending', 'failed')
              AND full_text IS NOT NULL
              AND (pipeline_status = 'pending' OR pipeline_attempts < 3)
            ORDER BY
                CASE WHEN pipeline_status = 'pending' THEN 0 ELSE 1 END,
                ingested_at ASC
            LIMIT %s
        """, (batch_size,))
        rows = cur.fetchall()
        cur.close()
        store._put_conn(conn)

        if not rows:
            return

        logger.info(f"Document pipeline: processing {len(rows)} pending documents")
        for doc_id, full_text, doc_type in rows:
            _process_one(doc_id)

    except Exception as e:
        logger.error(f"process_pending_documents failed: {e}")
        try:
            store._put_conn(conn)
        except Exception:
            pass


def _process_one(doc_id: int):
    """Process a single document — update status at each stage."""
    store = _get_store()

    def _set_status(status: str, error: str = None):
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE documents
                SET pipeline_status = %s,
                    pipeline_error = %s,
                    pipeline_attempts = pipeline_attempts + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END
                WHERE id = %s
            """, (status, error, status, doc_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)

    try:
        _set_status('classifying')
        run_pipeline(doc_id)
        _set_status('done')
    except Exception as e:
        logger.error(f"Document pipeline failed for doc {doc_id}: {e}")
        _set_status('failed', str(e)[:500])
```

### Step 4: Register scheduler job

**Modify `triggers/embedded_scheduler.py`:**

Add a new job that runs every 2 minutes:

```python
from tools.document_pipeline import process_pending_documents

scheduler.add_job(
    process_pending_documents,
    'interval',
    minutes=2,
    id='document_pipeline',
    name='Document extraction pipeline',
    max_instances=1,
    replace_existing=True,
)
```

### Step 5: Update callers

**Modify `triggers/dropbox_trigger.py`:**

Replace `queue_extraction(doc_id)` call with nothing — the scheduler picks it up automatically. The document is already stored with `pipeline_status = 'pending'`.

```python
# Remove: from tools.document_pipeline import queue_extraction
# Remove: queue_extraction(doc_id)
# The scheduler-based pipeline picks up pending docs every 2 minutes
logger.info(f"Document {doc_id} queued for pipeline (status=pending)")
```

### Step 6: Observability endpoint

**Modify `outputs/dashboard.py`:**

```python
@app.get("/api/documents/pipeline-status", tags=["system"], dependencies=[Depends(verify_api_key)])
async def document_pipeline_status():
    """Show document pipeline queue status."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pipeline_status, COUNT(*) as count
            FROM documents
            WHERE full_text IS NOT NULL
            GROUP BY pipeline_status
            ORDER BY pipeline_status
        """)
        rows = cur.fetchall()
        cur.close()
        return {"pipeline": {r[0] or "null": r[1] for r in rows}}
    finally:
        store._put_conn(conn)
```

### Step 7: Backfill existing documents

Existing documents with `classified_at IS NOT NULL` should be set to `done`. The rest to `pending`:

```sql
-- Run after deploy (add as endpoint or run manually)
UPDATE documents SET pipeline_status = 'done' WHERE classified_at IS NOT NULL;
UPDATE documents SET pipeline_status = 'pending' WHERE classified_at IS NULL AND full_text IS NOT NULL;
```

## Files to Modify

| File | Change |
|------|--------|
| `memory/store_back.py` | Add pipeline_status/error/attempts columns, update store_document_full |
| `tools/document_pipeline.py` | Replace thread/lock with process_pending_documents + _process_one |
| `triggers/embedded_scheduler.py` | Add document_pipeline job (every 2 min) |
| `triggers/dropbox_trigger.py` | Remove queue_extraction call |
| `outputs/dashboard.py` | Add /api/documents/pipeline-status endpoint |

## Verification

1. `GET /api/documents/pipeline-status` → shows distribution across statuses
2. Upload a new doc via Dropbox → appears as `pending`, then `classifying`, then `done` within 2 minutes
3. Restart the Render service → pending docs resume processing (no data loss)
4. Force a failure (e.g., circuit breaker) → doc shows `failed` with error message, `pipeline_attempts = 1`
5. After circuit breaker clears → failed doc retried (up to 3 attempts)

## What NOT to Build

- Parallel processing (asyncio.gather) — keep it sequential for now, one doc at a time
- Priority queue — FIFO is fine at current volume
- Dead letter notifications — just log, don't alert
