# Brief: SPECIALIST-UPGRADE-1 — Full Document Intelligence + Specialist Power-Up

**Author:** Code Brisen (Session 16, Director-designed)
**For:** Code 300 (architect review)
**Priority:** CRITICAL — Director considers document accuracy the #1 gap
**Reference:** ClaimsMax (Philip's system) as benchmark for document extraction quality

---

## Problem Statement

Baker's dashboard specialists read document fragments (500-token chunks from Qdrant), not full originals. A 20-page contract comes back as 3 paragraphs. This produces inaccurate answers for legal, financial, and claims analysis. Emails and meetings are stored in full (PostgreSQL), but Dropbox documents are not.

ClaimsMax demonstrates the target quality: exact amounts, dates, terms, cross-referenced entities, confidence assessments — all from a clean → classify → tag → extract → store pipeline.

## What to Build

### Foundation: Document Intelligence Pipeline

**The pipeline runs when any document enters Baker (Dropbox sentinel, file upload, or manual ingest):**

```
Document arrives (PDF, DOCX, XLSX, scan, photo)
  │
  ├─ Stage 1: CLEANING
  │   ├─ Scanned PDFs → Claude Vision OCR (not basic OCR)
  │   ├─ Photos of documents → Claude Vision extraction
  │   ├─ XLSX/CSV → extract as structured tables (already works)
  │   ├─ DOCX/PDF with text → extract clean text (already works)
  │   └─ Output: clean_text (full document, no truncation)
  │
  ├─ Stage 2: CLASSIFICATION + TAGGING
  │   ├─ Claude classifies: contract | nachtrag | invoice | schlussrechnung |
  │   │   correspondence | protocol | report | other
  │   ├─ Auto-tag: matter_slug, parties[], project, language
  │   └─ Output: document_type, matter_slug, parties, tags
  │
  ├─ Stage 3: STRUCTURED EXTRACTION
  │   ├─ Claude reads FULL clean text with type-specific prompt:
  │   │   ├─ Contract → parties, value, dates, terms, penalty clauses, retention %
  │   │   ├─ Invoice → amounts (gross/net), period, cumulative, deductions, retention
  │   │   ├─ Nachtrag → scope change, base contract ref, value delta, approval status
  │   │   ├─ Schlussrechnung → final amounts, prior payments, outstanding, disputes
  │   │   └─ Correspondence → sender, recipient, date, key demands/positions
  │   └─ Output: structured JSON (amounts[], dates[], terms[], entities[], references[])
  │
  └─ Stage 4: STORAGE
      ├─ PostgreSQL `documents` table → full_text (no truncation, no chunking)
      ├─ PostgreSQL `document_extractions` table → structured JSON
      ├─ Qdrant `baker-documents` → chunks (keep for vector search / discovery)
      └─ Cross-link: matter_registry, vip_contacts, deadlines
```

### New PostgreSQL Tables

```sql
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    source_path TEXT,              -- Dropbox path or upload identifier
    filename VARCHAR(500),
    file_hash VARCHAR(64),         -- SHA-256 for dedup
    document_type VARCHAR(50),     -- contract, invoice, nachtrag, etc.
    language VARCHAR(10),          -- de, en, fr
    matter_slug VARCHAR(200),      -- auto-assigned
    parties TEXT[],                -- extracted party names
    tags TEXT[],
    full_text TEXT,                -- COMPLETE document text (no truncation)
    page_count INTEGER,
    token_count INTEGER,           -- for context budget planning
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    classified_at TIMESTAMPTZ,
    extracted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS document_extractions (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    extraction_type VARCHAR(50),   -- contract_terms, invoice_amounts, nachtrag_delta, etc.
    structured_data JSONB,         -- the extracted structured data
    confidence VARCHAR(20),        -- high, medium, low
    extracted_by VARCHAR(50),      -- model used (haiku, opus)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_matter ON documents(matter_slug);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_doc_extractions_doc ON document_extractions(document_id);
```

### Item 1: Full Document Storage

**Modify `triggers/dropbox_trigger.py`:**

Currently:
```python
result = ingest_file(local_path, collection="baker-documents")
# → chunks to Qdrant, original discarded
```

After:
```python
# 1. Extract full text (no chunking)
full_text = extract_full_text(local_path)

# 2. Store full text in PostgreSQL documents table
doc_id = store.store_document_full(
    source_path=entry_path,
    filename=entry_name,
    full_text=full_text,
)

# 3. Also chunk to Qdrant (keep for vector search discovery)
result = ingest_file(local_path, collection="baker-documents")

# 4. Run classification + extraction pipeline (async, non-blocking)
background_classify_and_extract(doc_id)
```

### Item 2: Persistent Specialist Memory

**New table:**
```sql
CREATE TABLE IF NOT EXISTS specialist_memory (
    id SERIAL PRIMARY KEY,
    specialist_slug VARCHAR(50) NOT NULL,  -- legal, finance, etc.
    memory_type VARCHAR(30),               -- insight, pattern, preference, error
    content TEXT NOT NULL,
    confidence VARCHAR(20) DEFAULT 'medium',
    source_session TEXT,                   -- scan session ID that generated this
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ                 -- optional TTL
);
CREATE INDEX IF NOT EXISTS idx_specialist_memory_slug ON specialist_memory(specialist_slug);
```

**Modify `orchestrator/capability_runner.py`:**
- Before each specialist call, load relevant memories from `specialist_memory` table
- Inject as `## SPECIALIST MEMORY\n{memories}` section in system prompt
- After specialist produces a significant insight, auto-store to specialist_memory

### Item 3: Longer Conversation History

**Modify `outputs/dashboard.py` `scan_chat()`:**
- Current: 30 messages (15 turns) in conversation history
- Change to: 100 messages (50 turns)
- Add session persistence: store conversation sessions in PostgreSQL so specialist can resume

### Item 4: Richer Context Loading (Use the 1M Window)

**Modify `orchestrator/agent.py` `ToolExecutor`:**
- Current: `content = ctx.content[:2000]` — caps each result at 2000 chars
- Change: for documents, load FULL text from `documents` table (not chunks)
- Budget: allow up to 200K tokens of context per specialist call (20% of 1M)
- Priority: full documents > full emails > full meetings > chunks

**Modify `memory/retriever.py`:**
- When a Qdrant chunk matches a document in `documents` table, swap chunk with full text
- Same pattern as existing email/meeting full-text enrichment

### Item 5: On-Demand Dropbox File Reading + Upload

**New endpoint: `POST /api/documents/upload`**
- Accept file upload in dashboard
- Run through cleaning → classification → extraction pipeline
- Return structured extraction immediately
- Specialist can reference the full document in the same session

**Modify Dropbox sentinel:**
- Add on-demand read function: given a Dropbox path, fetch and return full content
- Specialist tool: `read_dropbox_file(path)` → returns full text + any existing extraction

**Dashboard UI:**
- Add file upload button in Ask Baker / Ask Specialist views
- Drag-and-drop zone
- Shows extraction progress (cleaning → classifying → extracting → ready)

## Files to Modify

| File | Change |
|------|--------|
| `memory/store_back.py` | New tables: documents, document_extractions, specialist_memory |
| `triggers/dropbox_trigger.py` | Store full text + trigger extraction pipeline |
| `orchestrator/capability_runner.py` | Load specialist memory, inject into prompt |
| `orchestrator/agent.py` | Full document retrieval instead of chunks |
| `memory/retriever.py` | Swap document chunks with full text from PostgreSQL |
| `outputs/dashboard.py` | File upload endpoint, conversation history extension |
| `outputs/static/app.js` | Upload UI in Ask Baker/Specialist views |
| NEW: `tools/document_pipeline.py` | Clean → classify → extract pipeline |

## Execution Order

1. **Tables + full text storage** — foundation (Items 1 + tables from 2)
2. **Document pipeline** — clean → classify → extract (Item 1 core)
3. **Full-text retrieval** — specialist reads complete documents (Item 4)
4. **Specialist memory** — persistent per-specialist learning (Item 2)
5. **Upload + on-demand read** — dashboard file access (Item 5)
6. **Conversation history** — extend to 100 messages (Item 3)

## Verification

1. Upload a contract PDF via dashboard → see full extraction (parties, amounts, dates, terms)
2. Ask Legal specialist about a contract → gets full document, not chunks
3. Ask same specialist in next session → remembers prior analysis
4. Check `documents` table → full_text column has complete document
5. Check `document_extractions` table → structured JSON with exact amounts

## What NOT to Build (Phase 2)

- Cross-document chain-of-custody (contract → nachtrag → invoice linking)
- Automatic dispute detection across documents
- Document versioning / diff tracking
- Multi-document synthesis reports (like ClaimsMax full position report)
- Training data export for fine-tuning

## Cost Estimate

- Stage 1 (Vision OCR): ~$0.01 per page (Haiku vision)
- Stage 2 (Classification): ~$0.005 per document (Haiku)
- Stage 3 (Extraction): ~$0.02-0.10 per document depending on length (Haiku for short, Opus for complex)
- Total: ~$0.05-0.15 per document. For 1000 documents in Dropbox: ~$50-150 one-time.
