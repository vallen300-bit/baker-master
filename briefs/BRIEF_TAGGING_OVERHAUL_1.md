# BRIEF: TAGGING-OVERHAUL-1 — Maximum Classification Effectiveness

**Priority:** HIGH
**Effort:** 3-4 hours (Code 300)
**Author:** Code Brisen (Session 21)
**Date:** 2026-03-11

---

## Problem

The document pipeline is classifying poorly. Of 3,150 documents:

| Issue | Count | % |
|-------|-------|---|
| Classified as "other" (catch-all) | 1,336 | 42% |
| Images with no business value | ~1,060 | 34% |
| No matter_slug assigned | 1,612 | 51% |
| Corrupted/unreadable OCR | ~150 | 5% |

**Root causes identified:**

1. **No pre-filtering** — Marketing photos (JPGs of bathrooms, lobbies, portraits) enter the document pipeline and waste Haiku tokens on classification. 998 of them come from the Marketing folder alone.

2. **Too few document_type categories** — Only 8 types. A `Grundbuch` (land register extract) gets "other". A financial model spreadsheet gets "other". A brochure gets "other".

3. **Source path ignored** — A file in `14_HAGENAUER_MASTER/` is obviously Hagenauer, but the classifier doesn't see the path. 87% of "other" docs have no matter_slug.

4. **Free-form tags** — Haiku generates inconsistent tags: "not a document", "non-document", "no text content", "not_a_document", "no_document_content" — 6+ variants of the same concept.

5. **No content quality gate** — Corrupted OCR text ("snores o DN rueplashed person heroes remain changes") gets classified as a real document.

---

## Solution — 5 Changes

### Change 1: Content Triage (pre-filter before Haiku)

Add a `content_class` column to `documents` table. Before Haiku classification, run a fast deterministic triage:

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_class VARCHAR(20) DEFAULT 'document';
-- Values: 'document', 'media_asset', 'corrupted', 'empty'
```

**Triage rules (no Haiku cost):**

```python
def triage_document(filename: str, full_text: str, source_path: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower()

    # Rule 1: Image files with no meaningful text → media_asset
    if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'svg'):
        # Check if text is just a card JSON or whiteboard transcription saying "no document"
        text_lower = full_text.lower() if full_text else ''
        if not full_text or len(full_text) < 100:
            return 'media_asset'
        if any(phrase in text_lower for phrase in [
            'not a business card', 'not a document', 'no text to transcribe',
            'no whiteboard', 'there is no whiteboard', 'does not contain'
        ]):
            return 'media_asset'
        # Images with real text content (whiteboards, signs) → keep as document

    # Rule 2: No text or tiny text → empty
    if not full_text or len(full_text.strip()) < 30:
        return 'empty'

    # Rule 3: Corrupted OCR detection
    # High ratio of single-char words = bad OCR
    words = full_text[:2000].split()
    if len(words) > 10:
        single_char_ratio = sum(1 for w in words if len(w) <= 1) / len(words)
        if single_char_ratio > 0.35:
            return 'corrupted'

    return 'document'
```

**Only `content_class = 'document'` proceeds to Haiku classification.** The rest get tagged automatically (saves ~1,200 Haiku calls = ~€30).

### Change 2: Expanded Document Type Taxonomy

Replace the current 8-type system with 16 types. Update `_CLASSIFY_PROMPT`:

```
Current:  contract | invoice | nachtrag | schlussrechnung | correspondence | protocol | report | other

New:      contract | invoice | nachtrag | schlussrechnung | correspondence | protocol | report |
          proposal | presentation | financial_model | legal_opinion | land_register |
          brochure | floor_plan | meeting_notes | other
```

Add to `_EXTRACTION_SCHEMAS`:

```python
"proposal": "parties, proposed_value, proposed_terms, conditions, deadline, scope",
"presentation": "title, audience, key_messages, data_points, conclusions",
"financial_model": "model_type, scenarios, key_assumptions, outputs (IRR/NPV/cash_flow), sensitivity_ranges",
"legal_opinion": "author, date, jurisdiction, question_posed, opinion, risk_assessment, recommended_action",
"land_register": "grundbuch_nr, municipality, owner, encumbrances, mortgages, area_sqm, restrictions",
"brochure": "product_name, target_audience, key_selling_points, pricing_info, contact_info",
"floor_plan": "project, unit_number, area_sqm, rooms, floor_level, orientation",
"meeting_notes": "date, attendees, topics, decisions, action_items, next_steps",
```

### Change 3: Source Path → Matter Hint

Inject the file's source_path into the classification prompt so Haiku can infer the matter. Add path-to-matter mapping:

```python
PATH_MATTER_HINTS = {
    '14_HAGENAUER': 'Hagenauer',
    '13_CUPIAL': 'Cupial',
    'Baden-Baden': 'Baden-Baden Projects',
    'Baden_Baden': 'Baden-Baden Projects',
    'Lilienmatt': 'Baden-Baden Projects',
    'Mandarin': 'Mandarin Oriental Sales',
    'MOVIE': 'Mandarin Oriental Sales',
    'MO_': 'Mandarin Oriental Sales',
    'Cap Ferrat': 'Cap Ferrat Villa',
    'Cap_Ferrat': 'Cap Ferrat Villa',
    'Villa': 'Cap Ferrat Villa',
    'Kitzb': 'Kitzbühel',
    'Kempinski': 'Kempinski Kitzbühel Acquisition',
    'Oskolkov': 'Oskolkov-RG7',
    'Marketing': 'Mandarin Oriental Sales',
    'Finance': 'Financing Vienna & Baden-Baden',
}

def get_path_hint(source_path: str) -> str:
    for pattern, matter in PATH_MATTER_HINTS.items():
        if pattern.lower() in source_path.lower():
            return f"\nHINT: This file comes from a folder related to '{matter}'. Use this to help determine the matter_slug."
    return ""
```

Update `_CLASSIFY_PROMPT` to include:
```
File path: {source_path}
{path_hint}
```

### Change 4: Controlled Tag Vocabulary

Replace free-form tags with a curated seed list. Haiku picks from the list OR adds max 2 new ones:

```python
CONTROLLED_TAGS = [
    # Content type
    "financial", "legal", "construction", "marketing", "operations", "governance",
    "insurance", "tax", "compliance", "HR", "IT",
    # Geography
    "Vienna", "Baden-Baden", "Geneva", "Cap Ferrat", "Kitzbühel", "Cyprus", "Monaco",
    # Project
    "Mandarin Oriental", "Hagenauer", "Riemergasse 7", "Lilienmattstraße",
    "Stadtvillen", "Annaberg", "MRCI", "Brisen",
    # Document features
    "signed", "draft", "final", "amended", "expired", "bilingual", "handwritten",
    # Urgency
    "deadline_mentioned", "payment_due", "action_required",
]
```

Updated prompt instruction:
```
"tags": Pick 2-5 tags from this list: {tag_list}. You may add up to 2 new tags only if nothing in the list fits.
```

### Change 5: Re-classify All Existing Documents

Write a script `scripts/reclassify_documents.py` that:

1. **Phase A — Triage** (no Haiku cost): Run triage on ALL 3,150 docs. Set `content_class`. Expected: ~1,200 marked as `media_asset`/`corrupted`/`empty`.

2. **Phase B — Re-classify "other"** (Haiku): Re-run classification with the improved prompt on the ~300-400 "other" docs that survive triage. Cost: ~€15-20.

3. **Phase C — Upgrade existing classifications** (Haiku): Re-run on ALL `content_class = 'document'` to get matter_slug from path hints and controlled tags. Cost: ~€60-80. **Optional — run if Phase B results look good.**

```python
# Pseudocode for reclassify script
def reclassify():
    # Phase A: Triage (free)
    docs = query("SELECT id, filename, full_text, source_path FROM documents")
    for doc in docs:
        content_class = triage_document(doc.filename, doc.full_text, doc.source_path)
        update("UPDATE documents SET content_class = %s WHERE id = %s", content_class, doc.id)

    # Phase B: Re-classify "other" that survived triage
    others = query("""
        SELECT id, full_text, source_path
        FROM documents
        WHERE content_class = 'document' AND document_type = 'other'
    """)
    for doc in others:
        classify_document_v2(doc.id, doc.full_text, doc.source_path)

    # Phase C: Full re-tag with path hints (optional)
    all_docs = query("SELECT id, full_text, source_path FROM documents WHERE content_class = 'document'")
    for doc in all_docs:
        classify_document_v2(doc.id, doc.full_text, doc.source_path)
```

---

## Implementation Order

| Step | What | Where | Cost |
|------|------|-------|------|
| 1 | Add `content_class` column | DB migration | Free |
| 2 | Update `_CLASSIFY_PROMPT` with expanded types + path hint + controlled tags | `tools/document_pipeline.py` | Free |
| 3 | Add `triage_document()` function | `tools/document_pipeline.py` | Free |
| 4 | Wire triage into `classify_document()` — skip non-documents | `tools/document_pipeline.py` | Free |
| 5 | Add new extraction schemas | `tools/document_pipeline.py` | Free |
| 6 | Add `PATH_MATTER_HINTS` and inject into prompt | `tools/document_pipeline.py` | Free |
| 7 | Write `scripts/reclassify_documents.py` | New file | Free |
| 8 | Run Phase A (triage) | Script | Free |
| 9 | Run Phase B (re-classify "other") | Script | ~€20 |
| 10 | Run Phase C (full re-tag) — Director approves | Script | ~€70 |

**Total implementation: ~3-4 hours. Total cost: ~€90.**

---

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| "other" bucket | 42% (1,336) | <5% (~100) |
| Matter-matched docs | 49% (1,539) | >85% (~2,700) |
| Image noise in searches | 1,060 results | 0 (filtered by content_class) |
| Document types | 8 | 16 |
| Tag consistency | Free-form chaos | Controlled vocabulary |

---

## Search Impact

After implementation, update `_search_documents` in `agent.py` to filter:
```sql
WHERE content_class = 'document'  -- exclude media/corrupted from search
```

This alone will massively improve specialist search relevance.

---

## Files to Modify

1. `tools/document_pipeline.py` — Main changes (triage, expanded types, path hints, controlled tags)
2. `orchestrator/agent.py` — Add `content_class = 'document'` filter to `_search_documents`
3. `scripts/reclassify_documents.py` — New script for bulk re-classification
4. DB: `ALTER TABLE documents ADD COLUMN content_class VARCHAR(20) DEFAULT 'document'`

## Dependencies

- None — all changes are backward-compatible
- Backfill can continue running; reclassify runs separately on stored docs
