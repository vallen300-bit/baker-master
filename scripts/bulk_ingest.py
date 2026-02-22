"""
Baker AI — Bulk Ingestion Pipeline
Reads JSON source files and indexes them into Qdrant via Voyage AI embeddings.

Usage:
    python scripts/bulk_ingest.py --source path/to/data.json --collection baker-conversations
    python scripts/bulk_ingest.py --source path/to/data.json --collection baker-conversations --dry-run

Input JSON format:
    {
        "texts": [
            {"text": "content to index", "metadata": {"key": "value", ...}},
            ...
        ]
    }
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

# Ensure project root is on sys.path so `from config.settings import config` works
# when running as `python scripts/bulk_ingest.py` from the 01_build directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config.settings import config

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return len(text) // 4


def chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    """
    Split text into chunks of approximately `max_tokens` tokens with `overlap_tokens` overlap.
    Uses character-level splitting (max_tokens * 4 chars) and breaks on sentence boundaries
    where possible.
    """
    if estimate_tokens(text) <= max_tokens:
        return [text]

    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars

        # If we're not at the end, try to break at a sentence boundary
        if end < len(text):
            # Look backwards from `end` for a sentence-ending character
            search_region = text[start + (max_chars // 2):end]
            for delim in [". ", ".\n", "?\n", "!\n", "\n\n", "? ", "! "]:
                last_break = search_region.rfind(delim)
                if last_break != -1:
                    end = start + (max_chars // 2) + last_break + len(delim)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Advance with overlap
        start = end - overlap_chars
        if start <= (end - max_chars):
            # Safety: always advance at least half a chunk to avoid infinite loops
            start = end - (max_chars // 2)

    return chunks


# ---------------------------------------------------------------------------
# Main ingestion logic
# ---------------------------------------------------------------------------

def load_source(source_path: Path) -> list[dict]:
    """Load and validate a JSON source file. Returns list of {text, metadata} dicts."""
    with open(source_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    texts = data.get("texts", [])
    if not texts:
        print(f"WARNING: No texts found in {source_path}")
        return []

    # Validate structure
    valid = []
    for i, item in enumerate(texts):
        if not isinstance(item, dict) or "text" not in item:
            print(f"  Skipping item {i}: missing 'text' field")
            continue
        if not item["text"].strip():
            continue
        valid.append({
            "text": item["text"],
            "metadata": item.get("metadata", {}),
        })

    return valid


def make_point_id(text: str) -> str:
    """Deterministic UUID from text content — re-running won't create duplicates."""
    return str(uuid5(NAMESPACE_URL, text[:200]))


def ensure_collection(qdrant: QdrantClient, collection: str):
    """Create the Qdrant collection if it doesn't exist."""
    try:
        qdrant.get_collection(collection)
        print(f"Collection '{collection}' exists.")
    except Exception:
        qdrant.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=config.voyage.dimensions,  # 1024
                distance=Distance.COSINE,
            ),
        )
        print(f"Created collection '{collection}' ({config.voyage.dimensions}d, cosine).")


def ingest(source_path: Path, collection: str, dry_run: bool = False):
    """Main ingestion pipeline: load → chunk → embed → upsert."""

    # --- Load source ---
    print(f"\n{'='*60}")
    print(f"Bulk Ingest: {source_path.name} → {collection}")
    print(f"{'='*60}")

    items = load_source(source_path)
    if not items:
        print("Nothing to ingest. Exiting.")
        return

    print(f"Loaded {len(items)} text items from source.")

    # --- Chunk ---
    chunks = []  # list of (text, metadata)
    for item in items:
        text_chunks = chunk_text(item["text"])
        for chunk in text_chunks:
            chunks.append((chunk, item["metadata"]))

    print(f"Chunked into {len(chunks)} pieces (~500 tokens each, 50 token overlap).")

    if dry_run:
        print("\n[DRY RUN] Would process:")
        print(f"  - {len(chunks)} chunks")
        print(f"  - {(len(chunks) + 49) // 50} embedding batches (50/batch)")
        print(f"  - {(len(chunks) + 99) // 100} upsert batches (100/batch)")
        sample = chunks[:3]
        for i, (text, meta) in enumerate(sample):
            print(f"\n  Sample chunk {i+1} (~{estimate_tokens(text)} tokens):")
            print(f"    Text: {text[:120]}...")
            print(f"    Metadata: {meta}")
        return

    # --- Init clients ---
    voyage = voyageai.Client(api_key=config.voyage.api_key)
    qdrant = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    ensure_collection(qdrant, collection)

    # --- Embed + Upsert in batches ---
    # Voyage free tier: 3 RPM, 10K TPM. With ~500 tok/chunk, 3 chunks ≈ 1.5K tokens/call.
    # Env overrides: INGEST_EMBED_BATCH, INGEST_EMBED_DELAY
    # Paid tier: set INGEST_EMBED_BATCH=50 INGEST_EMBED_DELAY=1
    EMBED_BATCH = int(os.environ.get("INGEST_EMBED_BATCH", "3"))
    EMBED_DELAY = float(os.environ.get("INGEST_EMBED_DELAY", "25"))  # 25s → well under 3 RPM
    MAX_RETRIES = 5
    UPSERT_BATCH = 100
    total_upserted = 0
    points_buffer = []

    embed_batches = [chunks[i:i + EMBED_BATCH] for i in range(0, len(chunks), EMBED_BATCH)]
    est_time = len(embed_batches) * EMBED_DELAY
    print(f"Embedding config: {EMBED_BATCH} chunks/batch, {EMBED_DELAY}s delay, "
          f"{len(embed_batches)} batches (~{est_time/60:.0f}min est.)")

    for batch_num, batch in enumerate(embed_batches, 1):
        texts_to_embed = [text for text, _ in batch]

        # Rate-limit between batches
        if batch_num > 1:
            time.sleep(EMBED_DELAY)

        # Embed with retry on rate-limit errors
        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = voyage.embed(
                    texts=texts_to_embed,
                    model=config.voyage.model,
                    input_type="document",
                )
                break
            except Exception as e:
                if "RateLimit" in type(e).__name__ or "rate" in str(e).lower():
                    backoff = EMBED_DELAY * attempt
                    print(f"  Rate limited (attempt {attempt}/{MAX_RETRIES}), "
                          f"backing off {backoff:.0f}s...")
                    time.sleep(backoff)
                else:
                    raise

        if result is None:
            print(f"  FAILED batch {batch_num} after {MAX_RETRIES} retries. Skipping.")
            continue

        # Build points
        for (text, metadata), vector in zip(batch, result.embeddings):
            point_id = make_point_id(text)
            payload = {
                "text": text,
                **metadata,
            }
            points_buffer.append(PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            ))

        # Upsert when buffer is full (or on last batch)
        while len(points_buffer) >= UPSERT_BATCH:
            upsert_batch = points_buffer[:UPSERT_BATCH]
            points_buffer = points_buffer[UPSERT_BATCH:]
            qdrant.upsert(collection_name=collection, points=upsert_batch)
            total_upserted += len(upsert_batch)

        print(
            f"[{collection}] Batch {batch_num}/{len(embed_batches)}: "
            f"embedded {len(batch)} chunks, upserted to Qdrant "
            f"(total so far: {total_upserted})"
        )

    # Flush remaining points
    if points_buffer:
        qdrant.upsert(collection_name=collection, points=points_buffer)
        total_upserted += len(points_buffer)
        print(f"[{collection}] Flushed final {len(points_buffer)} points.")

    print(f"\nDone. Total upserted: {total_upserted} vectors into '{collection}'.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baker AI — Bulk vector ingestion pipeline",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to JSON source file with {texts: [{text, metadata}, ...]}",
    )
    parser.add_argument(
        "--collection",
        type=str,
        required=True,
        help="Qdrant collection name (e.g. baker-conversations, sentinel-meetings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be ingested without calling APIs",
    )

    args = parser.parse_args()

    if not args.source.exists():
        print(f"ERROR: Source file not found: {args.source}")
        sys.exit(1)

    ingest(args.source, args.collection, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
