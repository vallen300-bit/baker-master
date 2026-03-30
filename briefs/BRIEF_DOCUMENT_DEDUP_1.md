# BRIEF: Document Dedup — Prevent Duplicate Attachments

**Priority:** Medium — backfill may create duplicates from same attachment emailed multiple times
**Ticket:** DOCUMENT-DEDUP-1

## Problem

When the same PDF/Word file is attached to multiple email threads (e.g., a contract forwarded 3 times), the backfill script extracts and stores it 3 times in the `documents` table. The Documents section then shows duplicates.

## Solution

Add content-hash dedup to the document storage pipeline. Before inserting a new document, check if a document with the same content hash already exists.

## Implementation

### Change 1: Add content_hash column to documents table

**File:** `outputs/dashboard.py` (startup migration block) or `memory/store_back.py`

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
```

### Change 2: Compute hash before storage

**File:** `tools/document_pipeline.py` (or wherever `store_document()` is called for attachments)

Before inserting, compute a SHA-256 hash of the extracted text (first 10,000 chars to handle minor formatting differences):

```python
import hashlib

def _content_hash(text: str) -> str:
    """Hash first 10K chars of extracted text for dedup."""
    normalized = text[:10000].strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()
```

### Change 3: Check for existing hash before insert

In the document storage function, before INSERT:

```python
content_hash = _content_hash(extracted_text)
cur.execute("SELECT id FROM documents WHERE content_hash = %s LIMIT 1", (content_hash,))
if cur.fetchone():
    logger.info(f"Document dedup: skipping duplicate (hash={content_hash[:16]})")
    return  # Skip duplicate
```

Then include `content_hash` in the INSERT.

### Change 4: Backfill hashes for existing documents

One-time script or endpoint to compute hashes for existing documents that don't have one:

```python
cur.execute("SELECT id, extracted_text FROM documents WHERE content_hash IS NULL LIMIT 500")
for row in cur.fetchall():
    h = _content_hash(row[1] or "")
    cur.execute("UPDATE documents SET content_hash = %s WHERE id = %s", (h, row[0]))
conn.commit()
```

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Migration: add content_hash column |
| `tools/document_pipeline.py` | Add _content_hash(), check before insert |
| `memory/store_back.py` | If store_document() is used instead of document_pipeline |

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('tools/document_pipeline.py', doraise=True)"
```

After backfill completes:
```sql
SELECT content_hash, COUNT(*) as copies FROM documents
WHERE content_hash IS NOT NULL
GROUP BY content_hash HAVING COUNT(*) > 1
ORDER BY copies DESC LIMIT 10;
```

Should return 0 rows if dedup is working.

## Change 5: Upgrade extraction to Sonnet for high-value documents

**File:** `tools/document_pipeline.py` (or wherever the Haiku classify → extract pipeline runs)

Currently both classification AND extraction use `claude-haiku-4-5-20251001`. Classification is fine on Haiku — it's a simple "is this an invoice or a contract?" task. But extraction (pulling dates, amounts, parties, obligations) is where Haiku struggles on complex legal/financial documents.

**Change:** After classification, if the document type is one of the high-value types, use Sonnet for extraction instead of Haiku:

```python
# High-value types that benefit from Sonnet extraction
_SONNET_EXTRACTION_TYPES = {
    'contract', 'legal_opinion', 'financial_model', 'invoice',
    'correspondence', 'report', 'proposal'
}

# Low-value types that stay on Haiku (not worth the cost)
# brochure, media_asset, floor_plan, photo, presentation, other

def _get_extraction_model(document_type: str) -> str:
    if document_type in _SONNET_EXTRACTION_TYPES:
        return "claude-opus-4-6"             # Best extraction — CEO-level attachments deserve it
    return "claude-haiku-4-5-20251001"       # cheap, fine for brochures/photos
```

Then in the extraction call, replace the hardcoded model:
```python
# Before:
model="claude-haiku-4-5-20251001"

# After:
model=_get_extraction_model(classified_type)
```

**Cost impact:**
- Haiku extraction: ~$0.01 per document
- Opus extraction: ~$0.15-0.25 per document
- Only ~60% of documents are high-value types → ~$75-125 for 500 backfill documents
- Director's rationale: CEO-level email attachments are contracts, legal opinions, term sheets — worth the investment

**What improves:**
- Legal memos: correct extraction of party names, dates, obligations
- Invoices: accurate amounts, line items, payment terms
- Contracts: clause identification, key dates, counterparties
- Correspondence: correct attribution of who said what

## Rules

- Check documents table schema before writing SQL
- Don't break existing document ingestion flow
- Hash computation must be fast (SHA-256 on 10K chars is ~0.1ms)
- Dedup is best-effort — if hash computation fails, store the document anyway
- Classification stays on Haiku — only extraction upgrades to Opus for high-value types
- Model ID for Opus: `claude-opus-4-6` (verify in config/settings.py — should match config.claude.model)
