"""
Document Intelligence Pipeline — SPECIALIST-UPGRADE-1B + PIPELINE-JOBQUEUE-1

Classify + extract structured data from documents stored in the
`documents` table (Package 1A). Runs after full text storage.

Stages:
  1. classify_document() — Haiku determines type, language, matter, parties
  2. extract_document()  — Haiku extracts type-specific structured fields
  3. cross_link()        — Match parties to VIPs, flag new deadlines

Job queue: DB-backed `doc_pipeline_jobs` table replaces daemon threads.
  - queue_extraction() inserts a pending job
  - drain_doc_pipeline() runs on scheduler (every 2 min), processes batch
  - Max 3 retries, exponential backoff, observable via /api/doc-pipeline/status

All Claude calls go through Phase 4A cost tracking + circuit breaker.
"""
import hashlib
import json
import logging
import time
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.document_pipeline")

_HAIKU_MODEL = "gemini-2.5-flash"
_OPUS_MODEL = "claude-opus-4-6"

# High-value types that use Opus for extraction (better accuracy on legal/financial)
_OPUS_EXTRACTION_TYPES = frozenset({
    'contract', 'legal_opinion', 'financial_model', 'invoice',
    'correspondence', 'report', 'proposal', 'nachtrag', 'schlussrechnung',
})


def _content_hash(text: str) -> str:
    """SHA-256 hash of first 10K chars of extracted text for dedup."""
    normalized = (text or "")[:10000].strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _get_extraction_model(document_type: str) -> str:
    """Return Opus for high-value document types, Haiku for the rest."""
    if document_type in _OPUS_EXTRACTION_TYPES:
        return _OPUS_MODEL
    return _HAIKU_MODEL

# Job queue settings
_MAX_PER_BATCH = 10
_MAX_ATTEMPTS = 3
_RATE_LIMIT_DELAY = 2  # seconds between API calls


# ─────────────────────────────────────────────
# Content Triage (TAGGING-OVERHAUL-1)
# ─────────────────────────────────────────────

# Deterministic pre-filter: skip non-documents before Haiku classification
_MEDIA_EXTENSIONS = frozenset({
    'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'svg',
})

_NON_DOCUMENT_PHRASES = [
    'not a business card', 'not a document', 'no text to transcribe',
    'no whiteboard', 'there is no whiteboard', 'does not contain',
    'no text content', 'image does not', 'cannot transcribe',
]


def triage_document(filename: str, full_text: str, source_path: str = "") -> str:
    """Classify content quality before Haiku. Returns content_class:
    'document', 'media_asset', 'corrupted', or 'empty'."""
    ext = (filename.rsplit('.', 1)[-1].lower()) if '.' in filename else ''

    # Rule 1: Image files with no meaningful text → media_asset
    if ext in _MEDIA_EXTENSIONS:
        text_lower = (full_text or '').lower()
        if not full_text or len(full_text) < 100:
            return 'media_asset'
        if any(phrase in text_lower for phrase in _NON_DOCUMENT_PHRASES):
            return 'media_asset'

    # Rule 2: No text or tiny text → empty
    if not full_text or len(full_text.strip()) < 30:
        return 'empty'

    # Rule 3: Corrupted OCR detection (high ratio of single-char words)
    words = full_text[:2000].split()
    if len(words) > 10:
        single_char_ratio = sum(1 for w in words if len(w) <= 1) / len(words)
        if single_char_ratio > 0.35:
            return 'corrupted'

    return 'document'


# Path-to-matter mapping for classification hints
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
    'Kitzb': 'Kitzbühel',
    'Kempinski': 'Kempinski Kitzbühel Acquisition',
    'Oskolkov': 'Oskolkov-RG7',
    'Marketing': 'Mandarin Oriental Sales',
    'Finance': 'Financing Vienna & Baden-Baden',
    'Annaberg': 'Annaberg',
    'Stadtvillen': 'Baden-Baden Projects',
    'Riemergasse': 'Riemergasse 7',
    'RG7': 'Riemergasse 7',
    'MRCI': 'MRCI',
    'Brisen': 'Brisen Group Operations',
    'Insurance': 'Insurance',
    'Davos': 'Davos-AlpenGold',
    'AlpenGold': 'Davos-AlpenGold',
}


def get_path_matter_hint(source_path: str) -> str:
    """Return a matter hint based on file path, or empty string."""
    if not source_path:
        return ""
    sp_lower = source_path.lower()
    for pattern, matter in PATH_MATTER_HINTS.items():
        if pattern.lower() in sp_lower:
            return f"\nHINT: This file comes from a folder related to '{matter}'. Use this to help determine the matter_slug."
    return ""


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
  "document_type": "contract" | "invoice" | "nachtrag" | "schlussrechnung" | "correspondence" | "protocol" | "report" | "proposal" | "legal_opinion" | "financial_model" | "land_register" | "brochure" | "floor_plan" | "meeting_notes" | "presentation" | "media_asset" | "travel_booking" | "other",
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
                    source_hint += get_path_matter_hint(row[0])
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
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        log_api_cost(
            "gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens,
            source="document_pipeline", capability_id="doc_classify",
        )

        raw = resp.text.strip()
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
    "travel_booking": "booking_type (flight/hotel/train/car), origin, destination, departure_date, return_date, confirmation_number, provider, price (EUR), notes",
}

_EXTRACT_PROMPT = """Extract structured data from this {doc_type}.
Return ONLY valid JSON with **EXACTLY** these fields: {schema}

Rules:
- Use null for fields you cannot determine.
- Use EUR for all amounts (numeric values, not strings).
- Dates as ISO strings (YYYY-MM-DD).
- Do NOT add any fields not listed above (no _notes, no _confidence_notes, no commentary).
- Do NOT wrap values in explanation text — just the value.

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

    extraction_model = _get_extraction_model(document_type)

    try:
        from orchestrator.gemini_client import is_gemini_model
        if is_gemini_model(extraction_model):
            from orchestrator.gemini_client import call_flash
            resp = call_flash(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
        else:
            client = anthropic.Anthropic(api_key=config.claude.api_key)
            _resp = client.messages.create(
                model=extraction_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            # Wrap Anthropic response to match Gemini shape
            from orchestrator.gemini_client import GeminiResponse
            resp = GeminiResponse(_resp.content[0].text, _resp.usage.input_tokens, _resp.usage.output_tokens)
        log_api_cost(
            extraction_model, resp.usage.input_tokens, resp.usage.output_tokens,
            source="document_pipeline", capability_id="doc_extract",
        )

        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        structured = json.loads(raw)

        # Pull confidence from response, default to "medium"
        confidence = structured.pop("_confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        # Validate and normalize via Pydantic schema
        from tools.extraction_schemas import validate_extraction
        validated_data, is_validated = validate_extraction(document_type, structured)

        # Store extraction
        _store_extraction(doc_id, document_type, validated_data, confidence=confidence, validated=is_validated, model=extraction_model)
        extra_count = len(validated_data.get("_extra", {})) if isinstance(validated_data.get("_extra"), dict) else 0
        logger.info(f"Extracted doc {doc_id}: type={document_type}, model={extraction_model}, confidence={confidence}, validated={is_validated}, fields={len(validated_data)}, extras={extra_count}")
        return validated_data

    except Exception as e:
        logger.warning(f"Document extraction failed for doc {doc_id}: {e}")
        return None


# ─────────────────────────────────────────────
# Full pipeline
# ─────────────────────────────────────────────

def run_pipeline(doc_id: int):
    """Run triage → classify → extract → cross-link for a single document."""
    full_text = _get_document_text(doc_id)
    if not full_text:
        logger.warning(f"No text for doc {doc_id}, skipping pipeline")
        return

    # Stage 0: Content triage (TAGGING-OVERHAUL-1, no Haiku cost)
    filename, source_path = _get_document_meta(doc_id)
    content_class = triage_document(filename or "", full_text, source_path or "")
    _set_content_class(doc_id, content_class)
    if content_class != 'document':
        logger.info(f"Doc {doc_id} triaged as '{content_class}', skipping Haiku classification")
        return

    # Stage 1: Classify
    classification = classify_document(doc_id, full_text)
    if not classification:
        return

    doc_type = classification.get("document_type", "other")

    # Stage 2: Extract (skip types without extraction schemas)
    extraction = None
    if doc_type in _EXTRACTION_SCHEMAS:
        import time
        time.sleep(2)  # Rate limit between API calls
        extraction = extract_document(doc_id, full_text, doc_type)

    # Stage 3: Cross-link (no Claude call)
    _cross_link(doc_id, classification, extraction)


def queue_extraction(doc_id: int):
    """Queue document for background classification + extraction.
    PIPELINE-JOBQUEUE-1: Inserts into doc_pipeline_jobs table instead of spawning thread.
    """
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            logger.warning(f"No DB — falling back to sync pipeline for doc {doc_id}")
            run_pipeline(doc_id)
            return
        try:
            cur = conn.cursor()
            # Skip if document is already classified + extracted
            cur.execute(
                "SELECT extracted_at FROM documents WHERE id = %s",
                (doc_id,),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                cur.close()
                logger.debug(f"Doc {doc_id} already extracted, skipping queue")
                return

            cur.execute("""
                INSERT INTO doc_pipeline_jobs (document_id, status)
                VALUES (%s, 'pending')
                ON CONFLICT (document_id) WHERE status IN ('pending', 'running') DO NOTHING
            """, (doc_id,))
            conn.commit()
            cur.close()
            logger.info(f"Queued doc {doc_id} for pipeline processing")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Queue insert failed for doc {doc_id}, running sync: {e}")
        run_pipeline(doc_id)


def drain_doc_pipeline():
    """Process pending jobs from doc_pipeline_jobs. Called by scheduler every 2 min.

    Picks up to _MAX_PER_BATCH pending jobs, runs each through the pipeline,
    marks complete or failed. Max _MAX_ATTEMPTS retries per job.
    """
    from triggers.sentinel_health import report_success, report_failure

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Claim pending jobs (oldest first, skip recently failed)
            cur.execute("""
                UPDATE doc_pipeline_jobs
                SET status = 'running', started_at = NOW(), attempts = attempts + 1
                WHERE id IN (
                    SELECT id FROM doc_pipeline_jobs
                    WHERE status = 'pending' AND attempts < %s
                    ORDER BY created_at
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, document_id, attempts
            """, (_MAX_ATTEMPTS, _MAX_PER_BATCH))
            jobs = cur.fetchall()
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)

        if not jobs:
            return

        processed = 0
        failed = 0
        for job_id, doc_id, attempt in jobs:
            try:
                run_pipeline(doc_id)
                _update_job_status(job_id, "complete")
                processed += 1
                time.sleep(_RATE_LIMIT_DELAY)
            except Exception as e:
                failed += 1
                if attempt >= _MAX_ATTEMPTS:
                    _update_job_status(job_id, "failed", str(e))
                    logger.error(f"Job {job_id} (doc {doc_id}) permanently failed after {attempt} attempts: {e}")
                else:
                    _update_job_status(job_id, "pending", str(e))
                    logger.warning(f"Job {job_id} (doc {doc_id}) attempt {attempt} failed, will retry: {e}")

        report_success("doc_pipeline")
        logger.info(f"Doc pipeline drain: {processed} processed, {failed} failed out of {len(jobs)} jobs")

    except Exception as e:
        report_failure("doc_pipeline", str(e))
        logger.error(f"Doc pipeline drain failed: {e}")


def _update_job_status(job_id: int, status: str, error: str = None):
    """Update a job's status in the queue."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            if status == "complete":
                cur.execute("""
                    UPDATE doc_pipeline_jobs
                    SET status = 'complete', completed_at = NOW(), error = NULL
                    WHERE id = %s
                """, (job_id,))
            else:
                cur.execute("""
                    UPDATE doc_pipeline_jobs
                    SET status = %s, error = %s
                    WHERE id = %s
                """, (status, error, job_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Failed to update job {job_id} status: {e}")


def get_pipeline_status() -> dict:
    """Return job queue stats for /api/doc-pipeline/status."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return {"error": "no db"}
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT status, COUNT(*) FROM doc_pipeline_jobs GROUP BY status
            """)
            counts = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute("""
                SELECT id, document_id, status, attempts, error, created_at
                FROM doc_pipeline_jobs
                WHERE status IN ('pending', 'running', 'failed')
                ORDER BY created_at DESC LIMIT 20
            """)
            active = []
            for row in cur.fetchall():
                active.append({
                    "id": row[0], "document_id": row[1], "status": row[2],
                    "attempts": row[3], "error": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                })
            cur.close()
            return {"counts": counts, "active_jobs": active}
        finally:
            store._put_conn(conn)
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def _get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_document_meta(doc_id: int) -> tuple:
    """Fetch filename and source_path for a document."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return ("", "")
        try:
            cur = conn.cursor()
            cur.execute("SELECT filename, source_path FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            cur.close()
            return (row[0] or "", row[1] or "") if row else ("", "")
        finally:
            store._put_conn(conn)
    except Exception:
        return ("", "")


def _set_content_class(doc_id: int, content_class: str):
    """Set content_class on a document (TAGGING-OVERHAUL-1)."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("UPDATE documents SET content_class = %s WHERE id = %s", (content_class, doc_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Failed to set content_class for doc {doc_id}: {e}")


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


def _store_extraction(doc_id: int, doc_type: str, structured: dict, confidence: str = "medium", validated: bool = False, model: str = None):
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
        "travel_booking": "travel_booking",
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
                    (document_id, extraction_type, structured_data, confidence, extracted_by, validated)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, extraction_type) DO UPDATE SET
                    structured_data = EXCLUDED.structured_data,
                    confidence = EXCLUDED.confidence,
                    extracted_by = EXCLUDED.extracted_by,
                    validated = EXCLUDED.validated,
                    created_at = NOW()
            """, (doc_id, extraction_type, json.dumps(structured), confidence, model or _HAIKU_MODEL, validated))
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


def _cross_link(doc_id: int, classification: dict, extraction: dict = None):
    """Cross-link extracted data with VIPs, matters, deadlines. No Claude calls.

    1. Match classification.parties to vip_contacts by surname
    2. Scan extraction for future dates → create soft deadlines
    """
    parties = classification.get("parties") or []
    matter_slug = classification.get("matter_slug")

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()

            # --- Party → VIP matching ---
            if parties:
                # Fetch all VIP names for matching
                cur.execute("SELECT id, name FROM contacts")
                vips = cur.fetchall()  # [(id, name), ...]

                matched_vips = []
                for party in parties:
                    party_lower = party.lower().strip()
                    if not party_lower or len(party_lower) < 3:
                        continue
                    # Split to get surname (last word)
                    party_parts = party_lower.split()
                    surname = party_parts[-1] if party_parts else party_lower

                    for vip_id, vip_name in vips:
                        vip_lower = vip_name.lower()
                        # Match: full name, or surname appears in VIP name
                        if party_lower == vip_lower or (len(surname) >= 3 and surname in vip_lower):
                            matched_vips.append((vip_id, vip_name, party))
                            break

                # Update last_contact_date for matched VIPs (document = contact evidence)
                for vip_id, vip_name, party in matched_vips:
                    try:
                        cur.execute("""
                            UPDATE contacts SET last_contact_date = GREATEST(
                                last_contact_date,
                                (SELECT COALESCE(classified_at, created_at) FROM documents WHERE id = %s)
                            ) WHERE id = %s
                        """, (doc_id, vip_id))
                    except Exception:
                        pass
                    logger.info(f"Cross-link doc {doc_id}: party '{party}' → VIP '{vip_name}' (id={vip_id})")

            # --- Future dates → deadlines ---
            if extraction:
                _extract_deadlines_from_fields(doc_id, extraction, matter_slug, cur)

            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Cross-link failed for doc {doc_id}: {e}")


def _extract_deadlines_from_fields(doc_id: int, extraction: dict, matter_slug: str, cur):
    """Scan extraction fields for future dates and create soft deadlines."""
    import re
    from datetime import datetime, timezone, timedelta

    # Fields likely to contain actionable dates
    _DATE_FIELD_NAMES = {
        "due_date", "end", "payment_terms", "next_meeting",
        "deadline", "expiry", "expiry_date", "end_date",
    }

    # Common date formats (no external dependency)
    _DATE_FORMATS = [
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
        "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y",
        "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
    ]

    def _try_parse_date(s: str):
        """Try common date formats. Returns datetime or None."""
        s = s.strip()[:30]  # limit length
        # Strip trailing timezone abbreviations like "UTC", "CET"
        s = re.sub(r'\s+[A-Z]{2,4}$', '', s)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    now = datetime.now(timezone.utc)
    max_future = now + timedelta(days=365)

    for key, value in extraction.items():
        if not isinstance(value, str) or not value:
            continue

        # Only check fields whose names suggest dates
        key_lower = key.lower()
        is_date_field = any(df in key_lower for df in _DATE_FIELD_NAMES)
        if not is_date_field:
            continue

        try:
            dt = _try_parse_date(value)
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Only future dates, within 1 year
            if dt <= now or dt > max_future:
                continue

            # Dedup: check if deadline already exists for this doc + date
            cur.execute("""
                SELECT id FROM deadlines
                WHERE source_type = 'document' AND source_id = %s
                  AND due_date::date = %s::date
                LIMIT 1
            """, (str(doc_id), dt.isoformat()))
            if cur.fetchone():
                continue

            # Create soft deadline
            from models.deadlines import insert_deadline
            dl_id = insert_deadline(
                description=f"[Auto-extracted] {key}: {value}" + (f" ({matter_slug})" if matter_slug else ""),
                due_date=dt.isoformat(),
                source_type="document",
                source_id=str(doc_id),
                confidence="soft",
                priority="normal",
            )
            if dl_id:
                logger.info(f"Cross-link doc {doc_id}: deadline #{dl_id} from field '{key}' = {value}")
        except (ValueError, TypeError, OverflowError):
            continue
