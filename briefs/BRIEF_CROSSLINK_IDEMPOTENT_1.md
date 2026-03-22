# Brief: CROSSLINK-IDEMPOTENT-1 — Document Cross-Linking + Extraction Idempotency

**Author:** AI Head (Session 21)
**For:** Code 300
**Priority:** HIGH — cross-linking is the highest-value unshipped feature from SPECIALIST-UPGRADE-1

---

## Part A: Document Cross-Linking

### Problem

`_cross_link()` in `tools/document_pipeline.py` (line 410) is a stub. It only verifies the matter exists in the registry. The original SPECIALIST-UPGRADE-1 brief specified:
- Match extracted party names to VIP contacts
- Flag dates that might be new deadlines
- Store cross-references

None of this was built. A contract mentioning "Hagenauer" or "Cupial" has no link to the contact record.

### What to Build

**Modify `tools/document_pipeline.py` — `_cross_link()` function (line 410):**

Replace the current stub with:

```python
def _cross_link(doc_id: int, classification: dict):
    """Cross-link extracted data with VIPs, matters, deadlines. No Claude calls."""
    matter_slug = classification.get("matter_slug")
    parties = classification.get("parties", [])

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()

            # 1. Verify matter exists in registry
            if matter_slug:
                cur.execute("SELECT id FROM matter_registry WHERE matter_name = %s", (matter_slug,))
                if not cur.fetchone():
                    logger.debug(f"Matter '{matter_slug}' not found in registry for doc {doc_id}")

            # 2. Match parties to VIP contacts (fuzzy name match)
            matched_contacts = []
            for party in parties:
                if not party or len(party) < 2:
                    continue
                cur.execute("""
                    SELECT id, name FROM vip_contacts
                    WHERE LOWER(name) = LOWER(%s)
                       OR LOWER(name) LIKE '%%' || LOWER(%s) || '%%'
                    LIMIT 3
                """, (party, party))
                for row in cur.fetchall():
                    matched_contacts.append({"contact_id": row[0], "contact_name": row[1], "party_text": party})

            # 3. Store links in documents table (parties_linked JSONB)
            if matched_contacts:
                cur.execute("""
                    UPDATE documents
                    SET tags = array_append(
                        COALESCE(tags, '{}'),
                        'has_contact_links'
                    )
                    WHERE id = %s AND NOT ('has_contact_links' = ANY(COALESCE(tags, '{}')))
                """, (doc_id,))
                logger.info(f"Doc {doc_id}: linked {len(matched_contacts)} contacts: "
                           f"{[c['contact_name'] for c in matched_contacts]}")

            # 4. Flag potential deadlines from extraction data
            cur.execute("""
                SELECT structured_data FROM document_extractions
                WHERE document_id = %s ORDER BY created_at DESC LIMIT 1
            """, (doc_id,))
            row = cur.fetchone()
            if row and row[0]:
                _flag_deadlines_from_extraction(cur, doc_id, row[0], matter_slug)

            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Cross-link failed for doc {doc_id}: {e}")


def _flag_deadlines_from_extraction(cur, doc_id: int, structured_data: dict, matter_slug: str):
    """Check extraction for date fields that might be deadlines. Insert if new."""
    import re
    from datetime import datetime, timezone

    # Date fields to check by extraction type
    date_fields = ["due_date", "end", "next_meeting", "expiry"]

    for field in date_fields:
        val = structured_data.get(field)
        if not val or not isinstance(val, str):
            continue
        # Try to parse ISO-ish dates
        match = re.match(r'(\d{4}-\d{2}-\d{2})', val)
        if not match:
            continue
        try:
            date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # Only flag future dates
            if date <= datetime.now(timezone.utc):
                continue
            # Check if deadline already exists
            cur.execute("""
                SELECT id FROM deadlines
                WHERE description ILIKE %s AND due_date::date = %s::date
                LIMIT 1
            """, (f"%doc {doc_id}%", match.group(1)))
            if cur.fetchone():
                continue
            # Insert new deadline
            cur.execute("""
                INSERT INTO deadlines (description, due_date, source_type, source_snippet, priority, confidence)
                VALUES (%s, %s, 'document', %s, 'normal', 'medium')
            """, (
                f"[Auto] {field}: {val} (doc {doc_id}, {matter_slug or 'no matter'})",
                match.group(1),
                f"Extracted from document {doc_id}, field: {field}",
            ))
            logger.info(f"Doc {doc_id}: flagged deadline {field}={val}")
        except (ValueError, TypeError):
            continue
```

### Files to Modify

| File | Change |
|------|--------|
| `tools/document_pipeline.py` | Replace `_cross_link()` stub + add `_flag_deadlines_from_extraction()` |

### Verification

1. Run extraction on a document with known parties (e.g., a Hagenauer contract)
2. Check: document gets `has_contact_links` tag
3. Check: if extraction has future dates, a deadline row appears in `deadlines` table
4. Verify no errors on documents with no parties or no extraction

---

## Part B: Extraction Idempotency

### Problem

Re-running the extraction pipeline on a document creates a **duplicate row** in `document_extractions`. The INSERT has no ON CONFLICT clause. If we re-run backfills or the Dropbox trigger reprocesses a file, we get multiple extraction rows per document.

### Fix

**Modify `tools/document_pipeline.py` — `_store_extraction()` function (line 366):**

Add a UNIQUE constraint and use upsert:

**Step 1: Add unique index** in `memory/store_back.py` — `_ensure_document_extractions_table()`:

```python
cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_extractions_unique
    ON document_extractions(document_id, extraction_type)
""")
```

**Step 2: Change INSERT to upsert** in `_store_extraction()`:

Replace:
```python
cur.execute("""
    INSERT INTO document_extractions
        (document_id, extraction_type, structured_data, confidence, extracted_by)
    VALUES (%s, %s, %s, %s, %s)
""", (doc_id, extraction_type, json.dumps(structured), confidence, _HAIKU_MODEL))
```

With:
```python
cur.execute("""
    INSERT INTO document_extractions
        (document_id, extraction_type, structured_data, confidence, extracted_by)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (document_id, extraction_type) DO UPDATE SET
        structured_data = EXCLUDED.structured_data,
        confidence = EXCLUDED.confidence,
        extracted_by = EXCLUDED.extracted_by,
        created_at = NOW()
""", (doc_id, extraction_type, json.dumps(structured), confidence, _HAIKU_MODEL))
```

**Step 3: Clean up existing duplicates** (one-time SQL, run after deploy):

```sql
-- Keep only the latest extraction per (document_id, extraction_type)
DELETE FROM document_extractions a
USING document_extractions b
WHERE a.document_id = b.document_id
  AND a.extraction_type = b.extraction_type
  AND a.id < b.id;
```

Add this as an endpoint or run it before creating the unique index.

### Files to Modify

| File | Change |
|------|--------|
| `tools/document_pipeline.py` | Upsert in `_store_extraction()` |
| `memory/store_back.py` | Add unique index in `_ensure_document_extractions_table()` |

### Verification

1. Run extraction on the same document twice
2. Check `document_extractions`: should have exactly 1 row per (document_id, extraction_type), not 2
3. The second run should UPDATE the existing row (newer `created_at`)

---

## Execution Order

1. **Part B first** (idempotency) — safety fix, prevents data corruption. Must dedup existing rows before adding unique index.
2. **Part A second** (cross-linking) — new functionality, depends on clean extraction data.

Syntax-check all modified files. Commit and push when done.
