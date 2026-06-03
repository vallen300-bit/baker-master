"""Baker AI — Attachment two-write promotion.

ATTACHMENT_TWO_WRITE_PARITY_1: a single shared helper that promotes an
already-extracted attachment's text into BOTH durable stores, so it is fully
covered:

  - Postgres `documents`  (Documents UI + GET /api/documents/search)  via store_document_full
  - Qdrant `baker-documents` (chat / Cortex semantic RAG)             via ingest_text

Callers (email live path, WhatsApp media, backfills) hold extracted text but NOT
a durable file on disk — the temp file is deleted right after extraction. So this
helper never touches a filepath and never re-extracts (do NOT route it through
ingest_file). It is idempotent (store_document_full dedups on content_hash +
ON CONFLICT file_hash; ingest_text dedups on filename+hash and uses deterministic
Qdrant point IDs) and NON-FATAL to the caller — every write is wrapped, failures
are logged loudly but never raised, so parent-message ingest is never broken.
"""
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("baker.ingest.attachments")


def promote_attachment_text_to_document_and_qdrant(
    source_path: str,
    filename: str,
    full_text: str,
    owner: str = "shared",
    file_hash: Optional[str] = None,
    collection: str = "baker-documents",
) -> dict:
    """Promote one attachment's already-extracted text to documents + Qdrant.

    Args:
        source_path: Durable origin path — e.g. "email:<mid>/<name>", a Dropbox
            path, or "whatsapp:<msg_id>/<name>". MUST NOT be a temp filepath that
            gets deleted after extraction.
        filename: Logical filename (documents row + Qdrant payload + dedup key).
        full_text: Already-extracted text. Empty/whitespace → no-op.
        owner: documents.owner tag (default "shared").
        file_hash: SHA-256 of the source bytes/text. Computed from full_text if
            None — pass the caller's existing hash to keep dedup keys aligned.
        collection: Target Qdrant collection (default baker-documents).

    Returns:
        {"doc_id": <int|None>, "chunk_count": <int>} — best-effort; either half
        may be None/0 if that store failed (logged). Never raises.
    """
    result = {"doc_id": None, "chunk_count": 0}

    if not full_text or not full_text.strip():
        return result

    if file_hash is None:
        file_hash = hashlib.sha256(full_text.encode()).hexdigest()

    token_count = len(full_text) // 4

    # --- Half 1: Postgres documents row (+ queue structured extraction) ---
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        doc_id = store.store_document_full(
            source_path=source_path,
            filename=filename,
            file_hash=file_hash,
            full_text=full_text,
            token_count=token_count,
            owner=owner,
        )
        result["doc_id"] = doc_id
        if doc_id:
            try:
                from tools.document_pipeline import queue_extraction
                queue_extraction(doc_id)
            except Exception as e:
                logger.warning(
                    "promote: queue_extraction failed (non-fatal) doc=%s file=%s err=%s",
                    doc_id, filename, e,
                )
    except Exception as e:
        logger.warning(
            "promote: store_document_full failed (non-fatal) file=%s path=%s err=%s",
            filename, source_path, e,
        )

    # --- Half 2: Qdrant baker-documents (semantic RAG) ---
    try:
        from tools.ingest.pipeline import ingest_text
        ir = ingest_text(
            full_text=full_text,
            filename=filename,
            source_path=source_path,
            collection=collection,
            file_hash=file_hash,
            document_id=result["doc_id"],  # B1: durable join key (PG row written in Half 1)
        )
        if ir is not None:
            result["chunk_count"] = ir.chunk_count or 0
    except Exception as e:
        logger.warning(
            "promote: ingest_text (Qdrant) failed (non-fatal) file=%s path=%s err=%s",
            filename, source_path, e,
        )

    return result
