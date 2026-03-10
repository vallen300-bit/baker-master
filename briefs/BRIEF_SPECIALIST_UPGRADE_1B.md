# Brief: SPECIALIST-UPGRADE-1B — Document Intelligence Pipeline + Shared Memory

**Author:** Code 300 (architecture review) + Director input
**Parent:** SPECIALIST-UPGRADE-1 (split into 1A + 1B per architect recommendation)
**Depends on:** SPECIALIST-UPGRADE-1A (full document storage must be live first)
**Priority:** HIGH — builds on 1A foundation
**Scope:** Classification, structured extraction, email attachments, shared specialist memory, file upload
**Estimate:** 1-2 sessions
**Director decisions applied:**
- Document types: Contracts, invoices, Nachträge (priority order)
- Memory: Shared across all specialists (Baker is one team)
- Auto-extraction: Run on everything (cost is negligible per Director)
- Email attachments: Treat same as Dropbox documents (full storage + extraction pipeline)

---

## What to Build

Five things, in order:

### 1. Document Classification + Extraction Pipeline

**New file: `tools/document_pipeline.py`**

Three-stage pipeline that runs after a document is stored in the `documents` table (1A):

```
document.id (from 1A) → classify → extract → store_extraction
```

**Stage 1: Classification (Haiku — fast, cheap)**

```python
async def classify_document(doc_id: int, full_text: str) -> dict:
    """Classify document type, language, matter, parties.

    Returns: {
        document_type: "contract" | "invoice" | "nachtrag" | "schlussrechnung" |
                       "correspondence" | "protocol" | "report" | "other",
        language: "de" | "en" | "fr",
        matter_slug: str or None,  # matched against matter_registry
        parties: list[str],
        tags: list[str],
    }
    """
```

- Uses Haiku (cost: ~$0.005/doc)
- Prompt includes list of active matters from `matter_registry` for slug matching
- Classification stored back to `documents` table (`classified_at` set)

**Stage 2: Structured Extraction (Haiku — Director says cost negligible)**

Type-specific extraction prompts:

| Document Type | Extraction Schema |
|---|---|
| `contract` | parties, value (gross/net), dates (signed, start, end), penalty_clauses, retention_pct, governing_law, jurisdiction |
| `invoice` | amounts (gross/net/vat), period, cumulative_total, deductions, retention, payment_terms, due_date |
| `nachtrag` | base_contract_ref, scope_change_description, value_delta, approval_status, approval_date |
| `schlussrechnung` | final_amount, prior_payments, outstanding_balance, disputed_items, retention_release |
| `correspondence` | sender, recipient, date, subject, key_demands, positions_stated, deadlines_mentioned |
| `protocol` | meeting_date, attendees, decisions[], action_items[], next_meeting |
| `report` | report_type, period, key_metrics, conclusions, recommendations |

- Uses Haiku for all extraction (Director: cost negligible; architect: Haiku is sufficient for structured extraction)
- Prompt: "Extract the following fields from this {document_type}. Return JSON. If a field cannot be determined, use null."
- Output stored to `document_extractions` table with `confidence` assessment

**Stage 3: Cross-linking (no Claude call)**

After extraction:
- If `deadlines_mentioned` or contract end dates found → check against `deadlines` table, flag if new
- If `parties` extracted → match against `vip_contacts`, add `document_id` reference
- If `matter_slug` identified → verify against `matter_registry`

### `document_extractions` Table

```sql
CREATE TABLE IF NOT EXISTS document_extractions (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    extraction_type VARCHAR(50),      -- contract_terms, invoice_amounts, nachtrag_delta, etc.
    structured_data JSONB,            -- the extracted structured data
    confidence VARCHAR(20),           -- high, medium, low
    extracted_by VARCHAR(50),         -- model slug (haiku-4.5, etc.)
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_extractions_doc ON document_extractions(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_extractions_type ON document_extractions(extraction_type);
```

### Cost Monitoring Integration

Every Claude call in the pipeline MUST use the Phase 4A cost infrastructure:

```python
from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

# Before each API call:
allowed, daily_cost = check_circuit_breaker()
if not allowed:
    logger.error(f"Document pipeline blocked by circuit breaker (€{daily_cost:.2f})")
    return

# After each API call:
log_api_cost(model, response.usage.input_tokens, response.usage.output_tokens,
             source="document_pipeline", capability_id="doc_classify")  # or "doc_extract"
```

### Pipeline Trigger

**Modify `triggers/dropbox_trigger.py`** — after 1A's `store_document_full()`:

```python
# After storing full text (1A):
doc_id = store.store_document_full(...)

# Queue classification + extraction (non-blocking)
if doc_id:
    from tools.document_pipeline import queue_extraction
    queue_extraction(doc_id)
```

**`queue_extraction()`** uses FastAPI `BackgroundTasks` pattern (same as existing WhatsApp backfill). Rate-limited: max 10 docs per poll cycle, 2-second delay between API calls.

### Backfill for Existing Documents

```python
# scripts/backfill_document_extractions.py
# Processes documents in `documents` table that have full_text but classified_at IS NULL
# Rate: 5 docs/minute (respects circuit breaker)
# Run: python scripts/backfill_document_extractions.py --limit 100 --dry-run
```

**Estimated cost for full backfill (3,188 docs):**
- Classification: 3,188 × $0.005 = ~$16
- Extraction: 3,188 × $0.02 = ~$64
- **Total: ~$80** (all Haiku)

---

### 2. Email Attachments as First-Class Documents

**Problem:** Email attachments (contracts, invoices sent as PDF) suffer the same loss as Dropbox files. Currently:
- `extract_gmail.py` extracts attachment text inline into `email_messages.full_body` after an `=== ATTACHMENTS ===` marker
- The `read_document` tool's `_read_email_attachment()` truncates at 8000 chars
- Attachments never enter the `documents` table, never get classified or extracted
- A 20-page contract attached to an email is treated no differently than a 3-line email body

**Solution:** Store each email attachment as a standalone row in the `documents` table (1A), then run through the same classification + extraction pipeline.

**Modify `scripts/extract_gmail.py` `extract_attachments_text()`:**

Currently returns `[{"filename": ..., "text": ...}]` which gets concatenated into the email body. Add a parallel path:

```python
def extract_attachments_text(service, message, store_as_documents=True):
    """Extract text from attachments. Optionally store each as a standalone document."""
    results = []
    # ... existing extraction logic (unchanged) ...

    if store_as_documents and results:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        message_id = message.get("id", "")
        for att in results:
            # Store each attachment as a standalone document
            file_hash = hashlib.sha256(att["text"].encode()).hexdigest()
            doc_id = store.store_document_full(
                source_path=f"email:{message_id}/{att['filename']}",
                filename=att["filename"],
                file_hash=file_hash,
                full_text=att["text"],
                token_count=len(att["text"]) // 4,
            )
            if doc_id:
                from tools.document_pipeline import queue_extraction
                queue_extraction(doc_id)

    return results  # still returned for inline embedding (backward compatible)
```

**Key design decisions:**
- `source_path` format: `email:{message_id}/{filename}` — enables cross-referencing back to the email
- Hash is computed from text content (not file bytes, since we only have text at this point)
- Existing inline embedding into `full_body` is preserved — backward compatible
- Each attachment becomes independently searchable, classifiable, and extractable
- The `read_document` tool's `_read_email_attachment()` can be upgraded to check `documents` table first (full text) before falling back to the truncated `full_body` extraction

**Modify `orchestrator/agent.py` `_read_email_attachment()`:**

```python
def _read_email_attachment(self, query: str) -> str:
    """Find attachment — check documents table first (full text), fall back to email body."""
    # NEW: Try documents table first (full text, no truncation)
    try:
        conn = store._get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT d.full_text, d.filename, d.source_path
            FROM documents d
            WHERE d.source_path LIKE 'email:%%'
              AND d.filename ILIKE %s
            ORDER BY d.ingested_at DESC LIMIT 1
        """, (f"%{query}%",))
        row = cur.fetchone()
        if row and row[0]:
            return f"--- DOCUMENT: {row[1]} (from email) ---\n{row[0][:12000]}"
    except Exception:
        pass
    # FALLBACK: existing email body extraction (unchanged)
    ...
```

**Backfill for existing email attachments:**

```python
# scripts/backfill_email_attachments.py
# 1. Query email_messages for rows with '=== ATTACHMENTS ===' in full_body
# 2. For each: re-download attachments via Gmail API (need service auth)
# 3. Extract text, store to documents table, queue extraction
# 4. Rate: 5/minute (Gmail API limits)
# Note: Requires Gmail OAuth credentials (same as email_trigger.py)
```

**Estimated volume:** Based on typical email patterns, ~15-25% of emails have attachments. With ~10K emails in `email_messages`, that's ~1,500-2,500 attachments to backfill.

**Estimated cost:** Same as Dropbox backfill per doc (~$0.03 each Haiku). For 2,000 attachments: ~$60.

---

### 3. Shared Specialist Memory

**Director decision: shared across all specialists (Baker is one team).**

This replaces the original per-specialist memory proposal. Instead of a parallel feedback mechanism, we extend the existing `baker_tasks` feedback loop with a shared insights system.

**New table:**

```sql
CREATE TABLE IF NOT EXISTS baker_insights (
    id SERIAL PRIMARY KEY,
    insight_type VARCHAR(30) NOT NULL,     -- finding, pattern, preference, correction
    content TEXT NOT NULL,                  -- the insight itself
    matter_slug VARCHAR(200),              -- optional: which matter this applies to
    source_capability VARCHAR(50),         -- which specialist generated it
    source_task_id INTEGER,                -- link to baker_tasks.id
    confidence VARCHAR(20) DEFAULT 'medium',
    validated_by VARCHAR(50),              -- 'director' if explicitly confirmed, 'auto' if auto-stored
    active BOOLEAN DEFAULT TRUE,           -- Director can deactivate bad insights
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ                 -- optional TTL for time-sensitive insights
);

CREATE INDEX IF NOT EXISTS idx_baker_insights_matter ON baker_insights(matter_slug);
CREATE INDEX IF NOT EXISTS idx_baker_insights_active ON baker_insights(active) WHERE active = TRUE;
```

**Why `baker_insights` instead of `specialist_memory`:**
- Shared = any specialist can read any insight
- Table name reflects Baker-as-team, not siloed specialists
- `validated_by` distinguishes Director-confirmed vs auto-stored (architect's concern addressed)
- `active` flag lets Director deactivate bad insights without deleting them
- Links to `baker_tasks` for provenance tracking

**Injection into specialist prompts — modify `capability_runner.py` `_build_system_prompt()`:**

```python
# After feedback injection, before mode-aware prompt:
insights = self._get_shared_insights(capability.slug, domain)
if insights:
    enriched += f"\n\n## BAKER TEAM INSIGHTS\n{insights}\n"
```

```python
def _get_shared_insights(self, slug: str, domain: str = None, limit: int = 5) -> str:
    """Fetch active insights relevant to this capability's work."""
    try:
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        cur = conn.cursor()
        # Get insights: matter-relevant first, then general, most recent
        cur.execute("""
            SELECT content, source_capability, matter_slug, validated_by
            FROM baker_insights
            WHERE active = TRUE
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY
                CASE WHEN validated_by = 'director' THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        if not rows:
            return ""
        parts = ["Baker's accumulated insights (shared across all specialists):"]
        for content, source_cap, matter, validated in rows:
            prefix = "[Director-confirmed]" if validated == "director" else ""
            matter_tag = f" [{matter}]" if matter else ""
            parts.append(f"- {prefix}{matter_tag} {content}")
        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Shared insights fetch failed (non-fatal): {e}")
        return ""
```

**Auto-storage of insights — modify `capability_runner.py`:**

After a specialist run completes, if the answer contains structured findings (amounts, dates, legal positions), auto-extract and store:

```python
def _maybe_store_insight(self, capability: CapabilityDef, question: str,
                         answer: str, baker_task_id: int = None):
    """Auto-extract and store significant findings. Haiku call."""
    if len(answer) < 200:  # too short to contain insights
        return
    # Use Haiku to extract key findings
    # Only store if confidence is high
    # Tag with validated_by='auto' (Director can confirm later)
```

This is a Haiku call (~$0.002) per specialist response. Only runs for answers > 200 chars.

**Director validation endpoint — modify `outputs/dashboard.py`:**

```
POST /api/insights/{id}/validate   — Director confirms insight
POST /api/insights/{id}/deactivate — Director deactivates bad insight
```

---

### 4. File Upload Endpoint + UI

**New endpoint in `outputs/dashboard.py`:**

```
POST /api/documents/upload
  - Accept: multipart/form-data (single file)
  - Max size: 100 MB (match Dropbox trigger limit)
  - Process: extract → store_document_full (1A) → classify + extract (1B) → return result
  - Response: { document_id, filename, document_type, extraction_summary }
```

**Dashboard UI in `outputs/static/app.js`:**

- Add upload button in Ask Baker / Ask Specialist header
- Drag-and-drop zone (small, non-intrusive)
- Progress indicator: uploading → extracting → classifying → ready
- After upload, the document is immediately available for the current specialist session

### 5. `search_documents` Agent Tool

**New tool #12 in `orchestrator/agent.py`:**

```python
{
    "name": "search_documents",
    "description": (
        "Search Baker's document store for full documents by type, matter, "
        "parties, or keywords. Returns full text and any structured extractions. "
        "Use when you need complete contracts, invoices, Nachträge, or correspondence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms"},
            "document_type": {"type": "string", "description": "contract, invoice, nachtrag, etc."},
            "matter_slug": {"type": "string", "description": "Filter by matter"},
        },
        "required": ["query"],
    },
}
```

Executor method queries `documents` table (full-text search on `full_text` + filter on `document_type`, `matter_slug`) and joins with `document_extractions` for structured data.

Returns full text up to the budget cap from 1A (12K chars), plus structured extraction JSON if available.

**Capabilities that get this tool:** legal, finance, asset_management, sales, research (5 of 11).

---

## Files to Modify

| File | Change |
|------|--------|
| NEW: `tools/document_pipeline.py` | Classification + extraction pipeline |
| NEW: `scripts/backfill_document_extractions.py` | Process existing Dropbox documents |
| NEW: `scripts/backfill_email_attachments.py` | Re-download + store email attachments |
| `memory/store_back.py` | DDL for `document_extractions` + `baker_insights` tables |
| `scripts/extract_gmail.py` | Store each attachment as standalone document + queue extraction |
| `triggers/dropbox_trigger.py` | Queue extraction after 1A storage |
| `orchestrator/agent.py` | `search_documents` tool (#12) + upgrade `_read_email_attachment()` |
| `orchestrator/capability_runner.py` | Shared insights injection + auto-insight extraction |
| `outputs/dashboard.py` | Upload endpoint + insight validation endpoints |
| `outputs/static/app.js` | Upload UI (drag-and-drop + progress) |

## Execution Order

1. **Tables:** `document_extractions` + `baker_insights` DDL
2. **Pipeline:** `tools/document_pipeline.py` (classify + extract)
3. **Trigger wiring:** Queue extraction in dropbox_trigger + email attachment storage in extract_gmail
4. **Email attachment retrieval upgrade:** `_read_email_attachment()` checks `documents` table first
5. **Shared memory:** `baker_insights` injection in capability_runner
6. **Agent tool:** `search_documents` in agent.py
7. **Upload UI:** endpoint + frontend
8. **Backfill (Dropbox):** Run extraction on existing documents
9. **Backfill (Email):** Re-download and store email attachments

## Verification

1. Upload a contract PDF → see classification (type, matter, parties) + structured extraction (amounts, dates, terms)
2. Upload an invoice → see invoice-specific extraction (gross, net, VAT, deductions)
3. Ask Legal specialist "What are the penalty clauses in the Hagenauer contract?" → specialist uses `search_documents` tool → returns full contract with extraction
4. **Email attachment test:** Send an email with a PDF attachment → email trigger runs → attachment appears in `documents` table as standalone entry → classification + extraction runs automatically
5. Ask specialist about an email attachment → gets full text (not 8K-truncated), plus structured extraction
6. After specialist produces a finding, check `baker_insights` table → insight auto-stored
7. Ask a different specialist about the same matter → shared insight appears in prompt
8. Director deactivates a bad insight → no longer injected
9. Check `api_cost_log` → all pipeline calls tracked, circuit breaker respected

## What This Does NOT Include (Phase 2+)

- Cross-document chain-of-custody (contract → nachtrag → invoice linking)
- Automatic dispute detection across documents
- Document versioning / diff tracking
- Multi-document synthesis (ClaimsMax-style position reports)
- ContextBudgetManager class (12K-char cap from 1A is sufficient for now)
- Conversation history extension (separate brief if needed)

## Cost Estimate

| Component | Per-document | Dropbox backfill (3,188 docs) | Email attachment backfill (~2,000) |
|---|---|---|---|
| Classification (Haiku) | $0.005 | $16 | $10 |
| Extraction (Haiku) | $0.02 | $64 | $40 |
| Auto-insight (Haiku) | $0.002/specialist run | Negligible | Negligible |
| **Total** | **~$0.03** | **~$80** | **~$50** |
| | | **Combined total: ~$130** | |

Director confirmed: cost is negligible. Run on everything.
