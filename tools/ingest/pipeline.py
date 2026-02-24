"""Baker AI — Core ingestion pipeline.

Orchestrates: extract → classify → dedup → chunk → embed → upsert → log.
Reuses chunking and embedding logic from scripts/bulk_ingest.py.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from config.settings import config
from scripts.bulk_ingest import chunk_text, ensure_collection, estimate_tokens, make_point_id
from tools.ingest.classifier import classify, VALID_COLLECTIONS
from tools.ingest.contact_writer import write_contact
from tools.ingest.dedup import compute_file_hash, is_duplicate, log_ingestion
from tools.ingest.extractors import extract, extract_image, parse_card_json, IMAGE_EXTENSIONS
from tools.ingest.models import IngestResult

logger = logging.getLogger("baker.ingest.pipeline")


def ingest_file(
    filepath: Path,
    collection: Optional[str] = None,
    dry_run: bool = False,
    skip_dedup: bool = False,
    skip_llm: bool = False,
    verbose: bool = False,
    image_type: Optional[str] = None,
    project: Optional[str] = None,
    role: Optional[str] = None,
) -> IngestResult:
    """Ingest a single file through the full pipeline.

    Steps:
        1. Extract text from file (or image via Claude Vision)
        2. Classify into collection (if not specified)
        3. Check for duplicates (SHA-256 + filename)
        4. Chunk text (~500 tokens, 50 overlap)
        5. Embed via Voyage AI (rate-limited batches)
        6. Upsert into Qdrant
        7. For business cards: also write to PostgreSQL contacts table
        8. Log to PostgreSQL ingestion_log

    Args:
        filepath: Path to the file to ingest.
        collection: Target Qdrant collection. Auto-classified if None.
        dry_run: Preview without calling APIs.
        skip_dedup: Skip duplicate detection.
        skip_llm: Skip LLM classification (heuristic only).
        verbose: Extra logging output.
        image_type: For images: 'card', 'whiteboard', or 'auto'. None for non-images.

    Returns:
        IngestResult with details of the ingestion.
    """
    filepath = Path(filepath).resolve()
    filename = filepath.name
    file_size = filepath.stat().st_size
    ext = filepath.suffix.lower()
    is_image = ext in IMAGE_EXTENSIONS

    if verbose:
        logger.info("Processing: %s (%d bytes)%s", filename, file_size,
                     f" [image_type={image_type}]" if is_image else "")

    # --- Step 1: Extract ---
    try:
        if is_image:
            text = extract_image(filepath, image_type=image_type)
        else:
            text = extract(filepath)
    except (ValueError, ImportError) as e:
        return IngestResult(
            filename=filename, file_hash="", file_size_bytes=file_size,
            collection="", chunk_count=0, skipped=True,
            skip_reason=str(e),
        )

    if not text:
        return IngestResult(
            filename=filename, file_hash="", file_size_bytes=file_size,
            collection="", chunk_count=0, skipped=True,
            skip_reason="Empty content after extraction",
        )

    token_est = estimate_tokens(text)
    if verbose:
        logger.info("  Extracted %d chars (~%d tokens)", len(text), token_est)

    # --- Detect card vs whiteboard for image routing ---
    card_data = None
    if is_image:
        card_data = parse_card_json(text)
        if card_data and card_data.get("name"):
            # It's a business card — route to baker-people
            if not collection:
                collection = "baker-people"
            if verbose:
                logger.info("  Business card detected: %s", card_data.get("name"))
        else:
            # Whiteboard or failed card parse — route to baker-documents
            card_data = None
            if not collection:
                collection = "baker-documents"
            if verbose:
                logger.info("  Whiteboard/document image — routing to baker-documents")

    # --- Step 2: Classify ---
    if collection:
        if collection not in VALID_COLLECTIONS:
            logger.warning("Collection '%s' not in known set — using anyway", collection)
        target = collection
    else:
        target = classify(filepath, text_preview=text[:500], use_llm=(not skip_llm))
    if verbose:
        logger.info("  Collection: %s", target)

    # --- Step 3: Dedup ---
    file_hash = compute_file_hash(filepath)
    if not skip_dedup and not dry_run:
        if is_duplicate(filename, file_hash):
            return IngestResult(
                filename=filename, file_hash=file_hash, file_size_bytes=file_size,
                collection=target, chunk_count=0, skipped=True,
                skip_reason="Duplicate (same filename + hash already ingested)",
            )

    # --- Step 4: Chunk ---
    chunks = chunk_text(text)
    if verbose:
        logger.info("  Chunked into %d pieces", len(chunks))

    # --- Dry run stop ---
    if dry_run:
        return IngestResult(
            filename=filename, file_hash=file_hash, file_size_bytes=file_size,
            collection=target, chunk_count=len(chunks),
        )

    # --- Step 5+6: Embed + Upsert ---
    point_ids = _embed_and_upsert(chunks, target, filepath, verbose, project=project, role=role)

    # --- Step 6b: Business card → dual-write to PostgreSQL contacts ---
    contact_result = None
    if card_data:
        try:
            contact_result = write_contact(card_data, source_file=filename)
            if verbose:
                logger.info("  Contact write: %s (%s)",
                             contact_result.get("name"), contact_result.get("action"))
        except Exception as e:
            logger.error("  Contact dual-write failed: %s", e)
            contact_result = {
                "contact_id": None,
                "name": card_data.get("name"),
                "action": "error",
                "collection": "baker-people",
                "error": str(e),
            }

    # --- Step 7: Log ---
    log_ingestion(
        filename=filename,
        file_hash=file_hash,
        file_size_bytes=file_size,
        collection=target,
        chunk_count=len(chunks),
        point_ids=point_ids,
        source_path=str(filepath),
        project=project,
        role=role,
    )

    result = IngestResult(
        filename=filename, file_hash=file_hash, file_size_bytes=file_size,
        collection=target, chunk_count=len(chunks),
        project=project, role=role, point_ids=point_ids,
    )

    # Attach card extraction data for API response
    if card_data:
        result.card_data = card_data
    if contact_result:
        result.contact_result = contact_result

    return result


def _embed_and_upsert(
    chunks: list[str],
    collection: str,
    filepath: Path,
    verbose: bool = False,
    project: Optional[str] = None,
    role: Optional[str] = None,
) -> list[str]:
    """Embed chunks via Voyage AI and upsert into Qdrant.

    Rate-limited with configurable batch size and delay via env vars:
        INGEST_EMBED_BATCH (default: 3)
        INGEST_EMBED_DELAY (default: 25s)

    Returns:
        List of Qdrant point IDs.
    """
    voyage = voyageai.Client(api_key=config.voyage.api_key)
    qdrant = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    ensure_collection(qdrant, collection)

    embed_batch = int(os.environ.get("INGEST_EMBED_BATCH", "3"))
    embed_delay = float(os.environ.get("INGEST_EMBED_DELAY", "25"))
    max_retries = 5
    upsert_batch = 100

    all_point_ids = []
    points_buffer = []
    batches = [chunks[i:i + embed_batch] for i in range(0, len(chunks), embed_batch)]

    metadata = {"source_file": filepath.name, "source_path": str(filepath)}
    if project:
        metadata["project"] = project
    if role:
        metadata["role"] = role

    for batch_num, batch in enumerate(batches, 1):
        if batch_num > 1:
            time.sleep(embed_delay)

        result = None
        for attempt in range(1, max_retries + 1):
            try:
                result = voyage.embed(
                    texts=batch,
                    model=config.voyage.model,
                    input_type="document",
                )
                break
            except Exception as e:
                if "RateLimit" in type(e).__name__ or "rate" in str(e).lower():
                    backoff = embed_delay * attempt
                    if verbose:
                        logger.info("  Rate limited (attempt %d/%d), backing off %ds...",
                                    attempt, max_retries, backoff)
                    time.sleep(backoff)
                else:
                    raise

        if result is None:
            logger.error("  FAILED batch %d after %d retries — skipping", batch_num, max_retries)
            continue

        for text, vector in zip(batch, result.embeddings):
            point_id = make_point_id(text)
            all_point_ids.append(point_id)
            points_buffer.append(PointStruct(
                id=point_id,
                vector=vector,
                payload={"text": text, **metadata},
            ))

        while len(points_buffer) >= upsert_batch:
            upsert_slice = points_buffer[:upsert_batch]
            points_buffer = points_buffer[upsert_batch:]
            qdrant.upsert(collection_name=collection, points=upsert_slice)

        if verbose:
            logger.info("  Batch %d/%d: embedded %d chunks", batch_num, len(batches), len(batch))

    # Flush remaining
    if points_buffer:
        qdrant.upsert(collection_name=collection, points=points_buffer)

    return all_point_ids
