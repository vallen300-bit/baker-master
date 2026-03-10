"""
Backfill script: Populate documents table from Dropbox /Baker-Feed/.

Re-downloads files from Dropbox, extracts full text, stores to documents
table, and queues classification + extraction via document_pipeline.

Usage:
    python scripts/backfill_documents.py --dry-run          # Preview only
    python scripts/backfill_documents.py --limit 10         # Process 10 files
    python scripts/backfill_documents.py --all              # Process everything
    python scripts/backfill_documents.py --extract-only     # Only run extraction on existing docs

Cost: ~$0.03/doc for classify + extract (Haiku). Full backfill ~$130.
"""
import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill.documents")


def backfill_from_dropbox(limit: int = None, dry_run: bool = False):
    """Download all files from Dropbox /Baker-Feed/, store full text, queue extraction."""
    from config.settings import config
    from triggers.dropbox_client import DropboxClient
    from tools.ingest.extractors import extract, SUPPORTED_EXTENSIONS
    from tools.ingest.dedup import compute_file_hash
    from memory.store_back import SentinelStoreBack

    client = DropboxClient._get_global_instance()
    store = SentinelStoreBack._get_global_instance()
    watch_path = config.dropbox.watch_path

    # List all files (initial cursor = None gets everything)
    logger.info(f"Listing all files in {watch_path}...")
    try:
        entries, _ = client.list_folder(watch_path, cursor=None)
    except Exception as e:
        logger.error(f"Failed to list Dropbox folder: {e}")
        return

    # Filter to supported files
    file_entries = []
    for entry in entries:
        if entry.get(".tag") != "file":
            continue
        name = entry.get("name", "")
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        size = entry.get("size", 0)
        if size > 104_857_600:  # 100MB
            continue
        file_entries.append(entry)

    total = len(file_entries)
    if limit:
        file_entries = file_entries[:limit]

    logger.info(f"Found {total} supported files, processing {len(file_entries)}")

    if dry_run:
        for entry in file_entries:
            logger.info(f"  [DRY-RUN] Would process: {entry.get('name')} ({entry.get('size', 0):,} bytes)")
        logger.info(f"Dry run complete. {len(file_entries)} files would be processed.")
        return

    # Check existing hashes to skip already-stored docs
    conn = store._get_conn()
    existing_hashes = set()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT file_hash FROM documents WHERE file_hash IS NOT NULL")
            existing_hashes = {r[0] for r in cur.fetchall()}
            cur.close()
        finally:
            store._put_conn(conn)
    logger.info(f"Existing documents in table: {len(existing_hashes)}")

    processed = 0
    skipped_hash = 0
    skipped_empty = 0
    errors = 0
    classified = 0
    circuit_breaker_stopped = False
    temp_dir = tempfile.mkdtemp(prefix="baker_backfill_")

    try:
        for i, entry in enumerate(file_entries):
            name = entry.get("name", "?")
            path = entry.get("path_display") or entry.get("path_lower", "")

            try:
                # Download
                local_path = client.download_file(path, Path(temp_dir))

                # Hash check
                file_hash = compute_file_hash(local_path)
                if file_hash in existing_hashes:
                    logger.info(f"  Skipped (hash match): {name}")
                    skipped_hash += 1
                    continue

                # Extract full text
                full_text = extract(local_path)
                if not full_text or len(full_text.strip()) < 10:
                    logger.info(f"  Skipped (empty/short text): {name}")
                    skipped_empty += 1
                    continue

                # Store
                doc_id = store.store_document_full(
                    source_path=path,
                    filename=name,
                    file_hash=file_hash,
                    full_text=full_text,
                    token_count=len(full_text) // 4,
                )

                if doc_id:
                    processed += 1
                    existing_hashes.add(file_hash)
                    logger.info(f"  Stored: {name} → doc {doc_id} ({len(full_text):,} chars)")

                    # Queue extraction (rate limited — 2s delay between API calls)
                    from orchestrator.cost_monitor import check_circuit_breaker
                    allowed, daily_cost = check_circuit_breaker()
                    if allowed:
                        from tools.document_pipeline import run_pipeline
                        time.sleep(2)
                        run_pipeline(doc_id)
                        classified += 1
                    else:
                        logger.warning(f"  Circuit breaker hit at €{daily_cost:.2f}, stopping extraction")
                        circuit_breaker_stopped = True
                        break

                # Rate limit: 5 files/minute = 12s between downloads
                time.sleep(12)

            except Exception as e:
                logger.warning(f"  Error processing {name}: {e}")
                errors += 1
                continue
            finally:
                # Clean up downloaded file
                try:
                    local_file = Path(temp_dir) / name
                    if local_file.exists():
                        local_file.unlink()
                except Exception:
                    pass

                # Progress log every 100 files (inside finally so continues don't skip it)
                if (i + 1) % 100 == 0:
                    logger.info(
                        f"Progress: {i + 1}/{len(file_entries)} — "
                        f"{processed} stored, {classified} classified, "
                        f"{skipped_hash} hash-skipped, {skipped_empty} empty-skipped, {errors} errors"
                    )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(
        f"\n{'='*60}\n"
        f"BACKFILL COMPLETE\n"
        f"  Total files listed:       {len(file_entries)}\n"
        f"  Skipped (hash match):     {skipped_hash}\n"
        f"  Skipped (empty/short):    {skipped_empty}\n"
        f"  Stored (new documents):   {processed}\n"
        f"  Classified:               {classified}\n"
        f"  Errors:                   {errors}\n"
        f"  Circuit breaker stopped:  {circuit_breaker_stopped}\n"
        f"{'='*60}"
    )


def extract_only(limit: int = None):
    """Run extraction pipeline on documents that have full_text but no classification."""
    from memory.store_back import SentinelStoreBack
    from tools.document_pipeline import run_pipeline
    from orchestrator.cost_monitor import check_circuit_breaker

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, filename FROM documents
            WHERE full_text IS NOT NULL AND classified_at IS NULL
            ORDER BY id
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    total = len(rows)
    if limit:
        rows = rows[:limit]
    logger.info(f"Found {total} unclassified documents, processing {len(rows)}")

    classified = 0
    for i, (doc_id, filename) in enumerate(rows):
        allowed, daily_cost = check_circuit_breaker()
        if not allowed:
            logger.warning(f"Circuit breaker at €{daily_cost:.2f}, stopping")
            break

        try:
            run_pipeline(doc_id)
            classified += 1
            logger.info(f"  Classified doc {doc_id}: {filename}")
        except Exception as e:
            logger.warning(f"  Failed doc {doc_id} ({filename}): {e}")

        time.sleep(2)

        if (i + 1) % 20 == 0:
            logger.info(f"Progress: {i + 1}/{len(rows)} classified")

    logger.info(f"Extract-only complete: {classified} classified of {len(rows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill documents table from Dropbox")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't process")
    parser.add_argument("--limit", type=int, default=None, help="Max files to process")
    parser.add_argument("--all", action="store_true", help="Process all files (no limit)")
    parser.add_argument("--extract-only", action="store_true",
                        help="Only run extraction on existing unclassified docs")
    args = parser.parse_args()

    if args.extract_only:
        extract_only(limit=args.limit)
    else:
        limit = None if args.all else (args.limit or 10)
        backfill_from_dropbox(limit=limit, dry_run=args.dry_run)
