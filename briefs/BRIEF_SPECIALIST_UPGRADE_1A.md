# Brief: SPECIALIST-UPGRADE-1A — Full Document Storage & Retrieval

**Author:** Code 300 (architecture review) + Director input
**Parent:** SPECIALIST-UPGRADE-1 (split into 1A + 1B per architect recommendation)
**Priority:** CRITICAL — #1 retrieval quality gap
**Scope:** Store full documents in PostgreSQL, retrieve full text for specialists
**Estimate:** 1 session (4-6 hours)

---

## Problem

Dropbox documents are chunked into ~500-token fragments. The originals are discarded. A 20-page contract comes back as 3 paragraphs. Emails and meetings already have full-text storage in PostgreSQL — documents do not.

## What to Build

Three things, in order:

### 1. PostgreSQL `documents` Table

```sql
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    source_path TEXT,                -- Dropbox path or upload identifier
    filename VARCHAR(500),
    file_hash VARCHAR(64),           -- SHA-256 (reuse compute_file_hash from dedup.py)
    document_type VARCHAR(50),       -- populated by 1B pipeline, NULL until then
    language VARCHAR(10),            -- populated by 1B pipeline, NULL until then
    matter_slug VARCHAR(200),        -- populated by 1B pipeline, NULL until then
    parties TEXT[],                  -- populated by 1B pipeline, NULL until then
    tags TEXT[],                     -- populated by 1B pipeline, NULL until then
    full_text TEXT,                  -- COMPLETE document text (no truncation)
    page_count INTEGER,
    token_count INTEGER,             -- len(full_text) // 4 — for context budget
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    classified_at TIMESTAMPTZ,       -- set by 1B pipeline
    extracted_at TIMESTAMPTZ         -- set by 1B pipeline
);

CREATE INDEX IF NOT EXISTS idx_documents_matter ON documents(matter_slug);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_path);
```

**Note:** Columns for classification/extraction are nullable — populated by Package 1B. This table works standalone as a full-text store.

### 2. Full-Text Storage in Dropbox Trigger

**Modify `triggers/dropbox_trigger.py`** — after download, before `ingest_file()`:

```python
# Inside the per-file processing loop, after download:

# 1. Extract full text (reuse existing extractors)
from tools.ingest.extractors import extract
full_text = extract(local_path)

# 2. Compute hash (reuse existing dedup utility)
from tools.ingest.dedup import compute_file_hash
file_hash = compute_file_hash(local_path)

# 3. Store full text in PostgreSQL documents table (upsert by file_hash)
store = _get_store()
store.store_document_full(
    source_path=entry_path,
    filename=entry_name,
    file_hash=file_hash,
    full_text=full_text,
    token_count=len(full_text) // 4 if full_text else 0,
)

# 4. Continue with existing chunked ingestion (Qdrant — unchanged)
result = ingest_file(local_path, collection="baker-documents")
```

**Key design decisions:**
- Reuse `compute_file_hash()` from `tools/ingest/dedup.py` — single source of truth for hashing
- Reuse `extract()` from `tools/ingest/extractors.py` — already handles PDF, DOCX, XLSX, images
- Upsert by `file_hash` — if document is re-processed (modified in Dropbox), full_text gets updated
- `ingest_file()` still runs unchanged — Qdrant chunks preserved for vector discovery

**New method in `memory/store_back.py`:**

```python
def store_document_full(self, source_path: str, filename: str,
                        file_hash: str, full_text: str,
                        token_count: int = 0) -> Optional[int]:
    """Store full document text in PostgreSQL. Returns document ID."""
    conn = self._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO documents (source_path, filename, file_hash, full_text, token_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (file_hash) DO UPDATE SET
                source_path = EXCLUDED.source_path,
                full_text = EXCLUDED.full_text,
                token_count = EXCLUDED.token_count,
                ingested_at = NOW()
            RETURNING id
        """, (source_path, filename, file_hash, full_text, token_count))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"store_document_full failed (non-fatal): {e}")
        conn.rollback()
        return None
```

### 3. Full-Text Retrieval for Specialists

**Modify `memory/retriever.py` `_enrich_with_full_text()`** — add document enrichment after existing meeting/email enrichment:

```python
# Inside _enrich_with_full_text(), after the email enrichment block:

# Documents — match by source_path or filename in metadata
collection = ctx.metadata.get("collection", "")
is_document = "document" in collection
source_path = ctx.metadata.get("source_path", "")
filename_meta = ctx.metadata.get("filename", ctx.metadata.get("label", ""))

if is_document and (source_path or filename_meta):
    doc_key = source_path or filename_meta
    if doc_key not in enriched_ids:
        full = self._get_full_document_text(source_path, filename_meta)
        if full:
            contexts[i] = RetrievedContext(
                content=full,
                source=ctx.source,
                score=ctx.score,
                metadata={**ctx.metadata, "enriched": True},
                token_estimate=self._estimate_tokens(full),
            )
            enriched_ids.add(doc_key)
            logger.info(f"Enriched document {doc_key} with full text")
            continue
```

**New method in `memory/retriever.py`:**

```python
def _get_full_document_text(self, source_path: str = None,
                            filename: str = None) -> Optional[str]:
    """Fetch full document text from documents table."""
    try:
        conn = self._get_pg_conn()
        cur = conn.cursor()
        if source_path:
            cur.execute(
                "SELECT full_text FROM documents WHERE source_path = %s LIMIT 1",
                (source_path,),
            )
        elif filename:
            cur.execute(
                "SELECT full_text FROM documents WHERE filename = %s ORDER BY ingested_at DESC LIMIT 1",
                (filename,),
            )
        else:
            cur.close()
            return None
        row = cur.fetchone()
        cur.close()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.debug(f"Full document lookup failed: {e}")
        self._pg_pool = None
        return None
```

**Modify `orchestrator/agent.py` `_format_contexts()`** — replace fixed 2000-char cap with token-aware budget:

```python
# Current (line 670):
content = ctx.content[:2000]

# New: budget-aware truncation
MAX_CHARS_PER_RESULT = 12000  # ~3K tokens — generous but bounded
if ctx.metadata.get("enriched"):
    # Full-text enriched results get more space
    content = ctx.content[:MAX_CHARS_PER_RESULT]
    if len(ctx.content) > MAX_CHARS_PER_RESULT:
        content += "\n[TRUNCATED — full document available via search_documents tool]"
else:
    content = ctx.content[:2000]
```

**Why 12,000 chars (not unlimited):** At ~4 chars/token, this is ~3K tokens per enriched result. With max 3 enriched results, that's ~9K tokens of document content in tool results — well within budget but a 6x improvement over the current 2K-char cap. The 1B package can introduce a proper `ContextBudgetManager` if needed.

### Enrichment Limit Increase

Change `_enrich_with_full_text` limits to account for documents:

```python
# Current:
if len(enriched_ids) >= 3:  # max 3 full-text enrichments

# New:
if len(enriched_ids) >= 5:  # max 5 full-text enrichments (meetings + emails + documents)
```

And scan top 15 candidates instead of 10.

## Files to Modify

| File | Change |
|------|--------|
| `memory/store_back.py` | DDL for `documents` table + `store_document_full()` method |
| `triggers/dropbox_trigger.py` | Extract full text + store to `documents` table before chunking |
| `memory/retriever.py` | `_get_full_document_text()` + document enrichment in `_enrich_with_full_text()` |
| `orchestrator/agent.py` | Budget-aware truncation in `_format_contexts()` (12K chars for enriched) |

## What This Does NOT Include (deferred to 1B)

- Document classification / tagging (Stages 2-3)
- Structured extraction (amounts, dates, parties)
- `document_extractions` table
- **Email attachments as standalone documents** (currently inline in `email_messages.full_body`, truncated at 8K on read)
- Specialist memory
- File upload endpoint / UI
- Conversation history changes
- Backfill script for existing 3,188 documents

## Backfill Script (existing documents)

A simple backfill to re-download and store full text for the ~3,188 documents already in `ingestion_log`:

```python
# scripts/backfill_documents.py
# 1. Query ingestion_log for all baker-documents entries with source_path
# 2. For each: re-download from Dropbox → extract full text → store to documents table
# 3. Rate limit: 5 files/minute (Dropbox API limits)
# 4. Log progress, skip failures (non-fatal)
# 5. Run as: python scripts/backfill_documents.py --dry-run / --limit 100
```

**Cost:** $0 — no Claude API calls. Just Dropbox download + text extraction (local).

## Verification

1. New Dropbox file arrives → check `documents` table has `full_text` (complete, not truncated)
2. Ask Legal specialist about a contract → tool results show full document content (up to 12K chars)
3. Compare answer quality: specialist cites specific clauses, amounts, dates (not vague summaries)
4. Check `ingestion_log` still works — Qdrant chunks unaffected
5. Monitor: no increase in API cost (this package has zero new Claude calls)

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Large documents bloat PostgreSQL | `token_count` column enables monitoring; TEXT type handles any size |
| Full-text retrieval slows specialist calls | 12K-char cap per result bounds worst case; max 5 enrichments |
| Dropbox trigger latency increase | `extract()` already runs during ingestion; `store_document_full()` adds ~10ms |
| Hash collision between `documents` and `ingestion_log` | Same `compute_file_hash()` function — guaranteed consistent |
