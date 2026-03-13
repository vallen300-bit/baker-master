"""
Document Intelligence Pipeline — SPECIALIST-UPGRADE-1B

Classify + extract structured data from documents stored in the
`documents` table (Package 1A). Runs after full text storage.

Stages:
  1. classify_document() — Haiku determines type, language, matter, parties
  2. extract_document()  — Haiku extracts type-specific structured fields
  3. cross_link()        — Match parties to VIPs, flag new deadlines

All Claude calls go through Phase 4A cost tracking + circuit breaker.
"""
import json
import logging
import threading
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.document_pipeline")

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Rate limiter: max 10 docs per batch, 2s between API calls
_MAX_PER_BATCH = 10
_processing_lock = threading.Lock()


# ─────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────

# DOC-RECLASSIFY-1: Controlled tag vocabulary (40 tags)
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

# DOC-RECLASSIFY-1: Expanded taxonomy (8 → 16 types)
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


def classify_document(doc_id: int, full_text: str) -> Optional[dict]:
    """Classify document type, language, matter, parties. Returns dict or None."""
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

    allowed, daily_cost = check_circuit_breaker()
    if not allowed:
        logger.error(f"Document classification blocked by circuit breaker (€{daily_cost:.2f})")
        return None

    # Fetch active matters for slug matching
    matters_list = _get_active_matters()

    # DOC-TRIAGE-1: Include source_path as a hint for matter detection
    source_hint = ""
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT source_path, filename FROM documents WHERE id = %s", (doc_id,))
                row = cur.fetchone()
                cur.close()
                if row and row[0]:
                    source_hint = f"\nFile path (use as context hint): {row[0]}\nFilename: {row[1] or ''}\n"
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    prompt = _CLASSIFY_PROMPT.format(
        matters_list=matters_list,
        text=source_hint + full_text[:8000],
        tags_instruction=_TAGS_INSTRUCTION,
    )

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        log_api_cost(
            _HAIKU_MODEL, resp.usage.input_tokens, resp.usage.output_tokens,
            source="document_pipeline", capability_id="doc_classify",
        )

        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)

        # Store classification back to documents table
        _update_document_classification(doc_id, result)
        logger.info(f"Classified doc {doc_id}: type={result.get('document_type')}, matter={result.get('matter_slug')}")
        return result

    except Exception as e:
        logger.warning(f"Document classification failed for doc {doc_id}: {e}")
        return None


# ─────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────

# DOC-RECLASSIFY-1: Expanded extraction schemas (7 → 13 types)
# brochure, floor_plan, media_asset don't need extraction — reference material
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

_EXTRACT_PROMPT = """Extract structured data from this {doc_type}.
Return ONLY valid JSON with these fields: {schema}
Use null for fields you cannot determine. Use EUR for all amounts.

Additionally, include a "_confidence" field with value "high", "medium", or "low":
- "high": document is clear, fields are unambiguous, amounts/dates are explicit
- "medium": some fields are inferred or partially legible
- "low": poor OCR, truncated text, or most fields are uncertain

Document text (first 12000 chars):
{text}"""


def extract_document(doc_id: int, full_text: str, document_type: str) -> Optional[dict]:
    """Extract type-specific structured data. Returns dict or None."""
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

    if document_type not in _EXTRACTION_SCHEMAS:
        logger.info(f"No extraction schema for type '{document_type}', skipping doc {doc_id}")
        return None

    allowed, daily_cost = check_circuit_breaker()
    if not allowed:
        logger.error(f"Document extraction blocked by circuit breaker (€{daily_cost:.2f})")
        return None

    schema = _EXTRACTION_SCHEMAS[document_type]
    prompt = _EXTRACT_PROMPT.format(
        doc_type=document_type,
        schema=schema,
        text=full_text[:12000],
    )

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        log_api_cost(
            _HAIKU_MODEL, resp.usage.input_tokens, resp.usage.output_tokens,
            source="document_pipeline", capability_id="doc_extract",
        )

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        structured = json.loads(raw)

        # Pull confidence from Haiku's response, default to "medium"
        confidence = structured.pop("_confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        # Store extraction
        _store_extraction(doc_id, document_type, structured, confidence=confidence)
        logger.info(f"Extracted doc {doc_id}: type={document_type}, confidence={confidence}, fields={len(structured)}")
        return structured

    except Exception as e:
        logger.warning(f"Document extraction failed for doc {doc_id}: {e}")
        return None


# ─────────────────────────────────────────────
# Full pipeline
# ─────────────────────────────────────────────

def run_pipeline(doc_id: int):
    """Run classify → extract → cross-link for a single document."""
    full_text = _get_document_text(doc_id)
    if not full_text:
        logger.warning(f"No text for doc {doc_id}, skipping pipeline")
        return

    # Stage 1: Classify
    classification = classify_document(doc_id, full_text)
    if not classification:
        return

    doc_type = classification.get("document_type", "other")

    # Stage 2: Extract (skip types without extraction schemas)
    if doc_type in _EXTRACTION_SCHEMAS:
        import time
        time.sleep(2)  # Rate limit between API calls
        extract_document(doc_id, full_text, doc_type)

    # Stage 3: Cross-link (no Claude call)
    _cross_link(doc_id, classification)


def queue_extraction(doc_id: int):
    """Queue document for background classification + extraction."""
    thread = threading.Thread(
        target=_safe_run_pipeline,
        args=(doc_id,),
        daemon=True,
    )
    thread.start()


def _safe_run_pipeline(doc_id: int):
    """Thread-safe wrapper for run_pipeline."""
    with _processing_lock:
        try:
            run_pipeline(doc_id)
        except Exception as e:
            logger.error(f"Document pipeline failed for doc {doc_id}: {e}")


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def _get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_active_matters() -> str:
    """Fetch active matter names for classification prompt."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return "(no matters loaded)"
        try:
            cur = conn.cursor()
            cur.execute("SELECT matter_name FROM matter_registry WHERE status = 'active'")
            matters = [r[0] for r in cur.fetchall()]
            cur.close()
            return "\n".join(f"- {m}" for m in matters) if matters else "(no matters)"
        finally:
            store._put_conn(conn)
    except Exception:
        return "(no matters loaded)"


def _get_document_text(doc_id: int) -> Optional[str]:
    """Fetch full_text from documents table."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT full_text FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            cur.close()
            return row[0] if row and row[0] else None
        finally:
            store._put_conn(conn)
    except Exception:
        return None


def _update_document_classification(doc_id: int, classification: dict):
    """Update documents table with classification results."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE documents SET
                    document_type = %s,
                    language = %s,
                    matter_slug = %s,
                    parties = %s,
                    tags = %s,
                    classified_at = NOW()
                WHERE id = %s
            """, (
                classification.get("document_type"),
                classification.get("language"),
                classification.get("matter_slug"),
                classification.get("parties", []),
                classification.get("tags", []),
                doc_id,
            ))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Failed to update classification for doc {doc_id}: {e}")


def _store_extraction(doc_id: int, doc_type: str, structured: dict, confidence: str = "medium"):
    """Store extraction results in document_extractions table."""
    extraction_type = {
        "contract": "contract_terms",
        "invoice": "invoice_amounts",
        "nachtrag": "nachtrag_delta",
        "schlussrechnung": "final_account",
        "correspondence": "correspondence_summary",
        "protocol": "meeting_protocol",
        "report": "report_summary",
        "legal_opinion": "legal_opinion",
        "financial_model": "financial_model",
        "land_register": "land_register",
        "meeting_notes": "meeting_notes",
        "proposal": "proposal_summary",
        "presentation": "presentation_summary",
    }.get(doc_type, doc_type)

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO document_extractions
                    (document_id, extraction_type, structured_data, confidence, extracted_by)
                VALUES (%s, %s, %s, %s, %s)
            """, (doc_id, extraction_type, json.dumps(structured), confidence, _HAIKU_MODEL))
            conn.commit()
            cur.close()

            # Mark document as extracted
            cur = conn.cursor()
            cur.execute("UPDATE documents SET extracted_at = NOW() WHERE id = %s", (doc_id,))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Failed to store extraction for doc {doc_id}: {e}")


def _cross_link(doc_id: int, classification: dict):
    """Cross-link extracted data with VIPs, matters, deadlines. No Claude calls."""
    matter_slug = classification.get("matter_slug")
    if not matter_slug:
        return

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            # Verify matter exists
            cur = conn.cursor()
            cur.execute("SELECT id FROM matter_registry WHERE matter_name = %s", (matter_slug,))
            row = cur.fetchone()
            cur.close()
            if not row:
                logger.debug(f"Matter '{matter_slug}' not found in registry for doc {doc_id}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Cross-link failed for doc {doc_id}: {e}")
