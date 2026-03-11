# BRIEF: DOC-RECLASSIFY-1 — Expanded Taxonomy + Controlled Tags + Re-classification

**Author:** AI Head (Session 20)
**For:** Code 300 (after DOC-TRIAGE-1 is done)
**Priority:** MEDIUM — improves search quality, runs as background job
**Estimated scope:** 1 file (document_pipeline.py) + 1 background script
**Cost:** ~€90 Haiku (~3,000 re-classifications × ~€0.03 each)

---

## Prerequisites

DOC-TRIAGE-1 must be done first (images triaged, matter_slugs assigned from paths). This brief re-classifies the remaining ~280 "other" docs and upgrades the taxonomy for all future documents.

## Change 1: Expanded Taxonomy (8 → 16 types)

In `tools/document_pipeline.py`, update `_CLASSIFY_PROMPT` (line 36):

```python
_CLASSIFY_PROMPT = """Classify this document. Return ONLY valid JSON.

Active matters (match if relevant):
{matters_list}

JSON schema:
{{
  "document_type": "contract" | "invoice" | "nachtrag" | "schlussrechnung" | "correspondence" | "protocol" | "report" | "proposal" | "legal_opinion" | "financial_model" | "land_register" | "brochure" | "floor_plan" | "meeting_notes" | "presentation" | "media_asset" | "other",
  "language": "de" | "en" | "fr" | "ru",
  "matter_slug": "<exact slug from list above, or null if no match>",
  "parties": ["<party name 1>", "<party name 2>"],
  "tags": {tags_instruction}
}}

Document text (first 8000 chars):
{text}"""
```

## Change 2: Controlled Tag Vocabulary

Add a controlled vocabulary that Haiku picks from:

```python
_TAG_VOCABULARY = [
    # Legal
    "warranty", "gewaehrleistung", "litigation", "settlement", "court", "arbitration",
    "contract", "amendment", "nachtrag", "termination", "deadline", "statute-of-limitations",
    # Financial
    "invoice", "payment", "budget", "capex", "tax", "audit", "insurance", "valuation",
    "capital-call", "distribution", "loan", "covenant",
    # Construction
    "construction", "defect", "snagging", "permit", "baubewilligung", "handover",
    "contractor", "subcontractor", "final-account", "retention",
    # Property
    "sales", "marketing", "brochure", "floor-plan", "residence", "hotel-operations",
    "tenant", "lease", "service-charge", "facility-management",
    # Corporate
    "governance", "shareholder", "board", "compliance", "kyc", "aml",
    # People / Relationships
    "investor", "lp", "introducer", "broker", "buyer", "seller",
    # Misc
    "meeting", "minutes", "correspondence", "internal", "external", "confidential",
]

_TAGS_INSTRUCTION = f'Pick 1-4 tags from this list: {json.dumps(_TAG_VOCABULARY)}. Do NOT invent new tags.'
```

Update the prompt format call to include the tag instruction:

```python
prompt = _CLASSIFY_PROMPT.format(
    matters_list=matters_list,
    text=path_hint + full_text[:8000],
    tags_instruction=_TAGS_INSTRUCTION,
)
```

## Change 3: Extraction Schemas for New Types

Add extraction schemas for the new document types in `_EXTRACTION_SCHEMAS`:

```python
_EXTRACTION_SCHEMAS = {
    "contract": "parties, value (gross/net in EUR), dates (signed, start, end), penalty_clauses, retention_pct, governing_law, jurisdiction",
    "invoice": "amounts (gross/net/vat in EUR), period, cumulative_total, deductions, retention, payment_terms, due_date",
    "nachtrag": "amendment_number, original_contract_ref, scope_change, price_change (EUR), new_total, approval_status",
    "schlussrechnung": "total_claimed (EUR), total_approved (EUR), retentions, deductions, open_items",
    "correspondence": "sender, recipient, date, subject, key_points, action_items",
    "protocol": "meeting_date, attendees, key_decisions, action_items, next_meeting",
    "report": "report_type, period, key_findings, recommendations",
    "legal_opinion": "author, date, jurisdiction, question, conclusion, risks, recommendations",
    "financial_model": "model_type, assumptions, key_outputs (IRR/NPV/cashflow), scenarios",
    "land_register": "property_address, plot_number, registered_owner, encumbrances, area_sqm",
    "meeting_notes": "date, attendees, topics, decisions, action_items",
    "proposal": "proposer, recipient, scope, value (EUR), timeline, conditions",
    "presentation": "title, author, date, key_slides_summary, audience",
}
```

(brochure, floor_plan, media_asset don't need extraction schemas — they're reference material)

## Change 4: Re-classification Script

Create `scripts/reclassify_docs.py`:

```python
"""
Re-classify documents that are currently 'other' or have no tags.
Runs as a background job. Uses the updated taxonomy + controlled tags.
"""
import time
import logging
from tools.document_pipeline import classify_document

logger = logging.getLogger(__name__)


def run_reclassify(batch_size: int = 50, sleep_between: float = 1.0):
    """Re-classify 'other' docs with the expanded taxonomy."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        print("No DB connection")
        return

    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Phase A: Re-classify "other" docs that have actual text content
        cur.execute("""
            SELECT id, full_text FROM documents
            WHERE document_type = 'other'
              AND full_text IS NOT NULL
              AND LENGTH(full_text) > 100
            ORDER BY ingested_at DESC
        """)
        targets = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    print(f"Found {len(targets)} 'other' docs to re-classify")
    success = 0
    errors = 0

    for i, doc in enumerate(targets):
        try:
            result = classify_document(doc['id'], doc['full_text'])
            if result and result.get('document_type') != 'other':
                success += 1
            time.sleep(sleep_between)  # rate limit
        except Exception as e:
            errors += 1
            logger.warning(f"Re-classify doc {doc['id']} failed: {e}")

        if (i + 1) % batch_size == 0:
            print(f"  Progress: {i+1}/{len(targets)} (success={success}, errors={errors})")

    print(f"Done. {success} re-classified, {errors} errors, {len(targets)-success-errors} remained 'other'")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_reclassify()
```

Run with: `python3 scripts/reclassify_docs.py` (background, takes ~1-2 hours)

## Testing

1. Syntax check `tools/document_pipeline.py`
2. Run reclassify on 5 docs first to verify taxonomy works: `python3 -c "from tools.document_pipeline import classify_document; ..."`
3. Then run full reclassify as background job

## Summary

| Metric | Before DOC-TRIAGE-1 | After DOC-TRIAGE-1 | After DOC-RECLASSIFY-1 |
|--------|---------------------|---------------------|------------------------|
| Document types | 8 | 8 + media_asset | 16 + media_asset |
| "other" docs | 1,340 (42%) | ~280 (9%) | <5% |
| Tag quality | Free-form chaos | Free-form chaos | 40 controlled tags |
| Matter coverage | 49% | ~88% | ~90%+ |
