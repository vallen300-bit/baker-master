# BRIEF: Baker 3.0 — Item 0a: Universal Real-Time Extraction Engine

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** CRITICAL — foundation for Items 2, 3, 0b
**Effort:** 2 sessions
**Assigned to:** AI Head + Code Brisen
**Reviewed by:** Cowork (7 pushbacks accepted)

---

## What We're Building

Every signal entering Baker (email, WhatsApp, meeting transcript, calendar event, photo, specialist output) gets structured extraction **immediately on arrival** — not in a daily batch.

Tiered processing:
- **T1/T2 signals:** Agentic RAG extraction (agent loop with 18 tools, context-aware)
- **T3 signals:** Single Haiku call (literal extraction, cheap and fast)

---

## New Files

### `orchestrator/extraction_engine.py` (NEW — main file)

```python
# Core functions:

def extract_signal(source_channel, source_id, content, tier, media_type=None):
    """Main entry point. Routes to agentic or haiku extraction based on tier."""

def _extract_agentic(content, source_channel, source_id, media_type):
    """T1/T2: Full agentic RAG extraction with tool calls."""
    # Uses agent.py's ToolExecutor with focused tool set:
    # search_calendar, get_matter_context, get_contact, get_deadlines
    # Claude reads content + tool results → extracts structured items

def _extract_haiku(content, source_channel, source_id, media_type):
    """T3: Single Haiku call, literal extraction."""

def _extract_visual(image_data, source_channel, source_id):
    """Photos/whiteboards: Claude Vision → classify → extract."""
    # If T1/T2: enriches with agentic context (calendar, matter, contacts)
    # Auto-links to meeting if photo taken within 1 hour

def _store_extractions(source_channel, source_id, extracted_items, media_type, linked_meeting):
    """Write to signal_extractions table."""

def extract_specialist_output(task_id, specialist_slug, output_text):
    """Extract from dossier/deep analysis output. Called once on completion.
    Only for research dossiers and deep analyses. No re-extraction."""
```

### Database: `signal_extractions` table (NEW)

```sql
CREATE TABLE IF NOT EXISTS signal_extractions (
    id SERIAL PRIMARY KEY,
    source_channel VARCHAR(20) NOT NULL,  -- email, whatsapp, meeting, calendar, mobile_upload, specialist
    source_id TEXT,                        -- reference to original content
    media_type VARCHAR(20),               -- null, whiteboard, diagram, screenshot, business_card
    extraction_tier VARCHAR(5),           -- T1, T2, T3
    extracted_items JSONB NOT NULL,       -- array of structured items (universal schema)
    linked_meeting TEXT,                  -- fireflies_id if auto-linked
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    processing_ms INTEGER,               -- how long extraction took
    token_cost NUMERIC(10,6)             -- estimated cost of this extraction
);

CREATE INDEX idx_se_channel ON signal_extractions(source_channel);
CREATE INDEX idx_se_processed ON signal_extractions(processed_at);
CREATE INDEX idx_se_items ON signal_extractions USING GIN(extracted_items);
```

### Universal Schema (JSONB for extracted_items)

```json
[
  {
    "type": "commitment | deadline | decision | question | action_item | financial | intelligence | follow_up",
    "text": "Ofenheimer will send Section 14 demand by Friday",
    "who": "Ofenheimer",
    "directed_to": "Dimitry",
    "when": "2026-03-28",
    "confidence": "high | medium | low",
    "completion_signals": ["email from Ofenheimer", "Section 14 in subject line"],
    "related_matter": "hagenauer",
    "related_contacts": ["Ofenheimer", "Blaschka"],
    "sentiment": "neutral"
  }
]
```

---

## Trigger Hooks (Modify Existing Files)

### `triggers/email_trigger.py`
After storing email to PostgreSQL (existing flow), add:
```python
from orchestrator.extraction_engine import extract_signal
# After pipeline.run() or store_email_message():
extract_signal("email", source_id=thread_id, content=full_body, tier=tier)
```

### `triggers/waha_webhook.py`
After storing WhatsApp message, add extraction call.
For media messages (photos), call `extract_signal` with `media_type`.

### `triggers/fireflies_trigger.py`
After `store_meeting_transcript()`, add extraction call.
This is also the hook for Item 3 (post-meeting pipeline).

### `orchestrator/research_executor.py`
After dossier completion (status="completed"), call:
```python
extract_specialist_output(task_id=proposal_id, specialist_slug="research", output_text=dossier_md)
```

### Calendar events
After calendar meeting prep job detects events, extract prep-needed items.

---

## Rate Limiter (Cowork pushback #7)

```python
# In extraction_engine.py:
_EXTRACTION_SEMAPHORE = asyncio.Semaphore(3)  # max 3 concurrent extractions

async def extract_signal_queued(...):
    async with _EXTRACTION_SEMAPHORE:
        return extract_signal(...)
```

When 20 emails arrive from a morning Gmail poll, max 3 extract simultaneously, rest queue.

---

## Agentic Extraction Prompt

```
You are Baker's extraction engine. Analyze this {source_channel} content
and extract ALL structured items.

For each item, classify as: commitment, deadline, decision, question,
action_item, financial, intelligence, or follow_up.

Context from Baker's memory:
{tool_results — calendar, matter, contacts, deadlines}

Content to analyze:
{content}

Extract items as JSON array. Be specific: names, dates, amounts.
Set confidence to "low" if inferring rather than quoting directly.
If no items to extract, return empty array [].
```

---

## Haiku Extraction Prompt (T3)

```
Extract structured items from this content. For each item provide:
type, text, who, directed_to, when, confidence.
Return JSON array. Empty array if nothing to extract.

Content:
{content}
```

---

## Visual Extraction Flow

```
1. Receive image (from WhatsApp media, email attachment, or mobile upload)
2. Claude Vision (Haiku): classify image type
   → whiteboard | diagram | handwritten | screenshot | business_card | document_photo
3. Claude Vision (Haiku): extract text content from image
4. If T1/T2: run agentic enrichment
   → search_calendar: find meeting within 1 hour
   → get_matter_context: link to relevant matter
   → get_contact: identify people
5. Extract structured items using enriched context
6. If linked_meeting found: store the association
```

---

## Testing

1. **Unit test:** Feed a sample email through `_extract_haiku()` → verify JSON schema
2. **Unit test:** Feed a sample meeting transcript through `_extract_agentic()` → verify tool calls + extraction
3. **Integration test:** Send a test WhatsApp message → verify it appears in signal_extractions within 30 seconds
4. **Rate limiter test:** Simulate 20 simultaneous emails → verify max 3 concurrent
5. **Visual test:** Send a whiteboard photo via WhatsApp → verify classification + extraction + meeting link

---

## What This Brief Does NOT Cover

- Consumer migration (Item 0b — separate brief)
- Context selector integration (Item 2 — separate brief)
- Post-meeting auto-pipeline (Item 3 — separate brief)
- Push notifications (Item 1 — separate brief)

Build the engine first. Consumers switch later.

---

## Safety Rules

- Extraction errors must NOT break the existing pipeline. All extraction calls wrapped in try/except.
- If extraction fails, the signal still flows through the normal pipeline (alerts, storage, etc.)
- Circuit breaker applies to extraction Haiku/Opus calls
- Rate limiter: max 3 concurrent extractions
- Specialist output extraction: dossiers and deep analyses ONLY, triggered once on completion, no re-extraction loop
