"""
Sentinel Trigger — Dropbox (Read-Only)
Polls /Baker-Feed/ every 30 minutes for new and modified files.
Downloads files, runs through ingestion pipeline (tools/ingest/pipeline.py),
stores embeddings in baker-documents Qdrant collection + PostgreSQL ingestion_log,
and feeds changes into the Sentinel pipeline.

Called by scheduler every 30 minutes.

Pattern: follows todoist_trigger.py structure (lazy imports, module-level entry point).

API: Dropbox API v2 — no deprecation announced.
Deprecation check date: 2026-03-23
"""
import logging
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.dropbox_trigger")

_MAX_FILE_SIZE = 104_857_600  # 100 MB


def _get_client():
    """Get the global DropboxClient singleton."""
    from triggers.dropbox_client import DropboxClient
    return DropboxClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_supported_extensions():
    """Lazy import SUPPORTED_EXTENSIONS from ingest extractors."""
    from tools.ingest.extractors import SUPPORTED_EXTENSIONS
    return SUPPORTED_EXTENSIONS


def run_dropbox_poll():
    """Main entry point — called by scheduler every 30 minutes.

    Algorithm:
    1. Get DropboxClient singleton
    2. Get stored cursor (opaque string or None for first poll)
    3. Call list_folder with cursor to get changed entries
    4. Filter: only files, supported extensions, ≤100 MB
    5. For each valid file:
       a. Download to temp directory
       b. Run through ingest_file() → baker-documents collection
       c. If not skipped → feed to Sentinel pipeline
       d. Clean up temp file
    6. Store new cursor
    7. Log summary
    """
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("dropbox"):
        return

    logger.info("Dropbox trigger: starting poll...")

    from config.settings import config

    try:
        client = _get_client()
        watch_path = config.dropbox.watch_path
        supported_extensions = _get_supported_extensions()

        files_processed = 0
        files_skipped = 0
        files_errored = 0
        request_count_start = client._request_count

        # -------------------------------------------------------
        # Step 1-3: Get cursor and list changes
        # -------------------------------------------------------
        cursor = trigger_state.get_cursor("dropbox")
        had_cursor = cursor is not None

        # PM-OOM-1 H4: Stale watermark safeguard. If last poll was >24h ago,
        # don't batch-process the backlog (OOM risk). Get a fresh cursor only.
        from datetime import timedelta
        last_poll = trigger_state.get_watermark("dropbox")
        stale = (datetime.now(timezone.utc) - last_poll) > timedelta(hours=24) if last_poll else True
        if stale and had_cursor:
            logger.warning(
                f"Dropbox: watermark stale (last poll: {last_poll}) — "
                "resetting cursor to skip backlog"
            )
            # Get fresh cursor without processing files
            try:
                _entries, new_cursor = client.list_folder(watch_path, cursor=cursor)
                if new_cursor:
                    trigger_state.set_cursor("dropbox", new_cursor)
                trigger_state.set_watermark("dropbox", datetime.now(timezone.utc))
                report_success("dropbox")
                logger.info(
                    f"Dropbox: cursor reset complete ({len(_entries)} backlog entries skipped). "
                    "Next poll will process only new changes."
                )
            except Exception as e:
                report_failure("dropbox", f"Cursor reset failed: {e}")
                logger.error(f"Dropbox cursor reset failed: {e}")
            return

        try:
            entries, new_cursor = client.list_folder(watch_path, cursor=cursor)
            logger.info(f"Dropbox list_folder returned {len(entries)} entries (cursor={'continued' if had_cursor else 'initial'})")
        except Exception as e:
            # 409 path not found → folder may not exist yet
            if "409" in str(e) or "path/not_found" in str(e):
                logger.warning(f"Dropbox folder {watch_path} not found — skipping poll (create the folder to start)")
                report_success("dropbox")  # not an error — folder just doesn't exist yet
                return
            report_failure("dropbox", str(e))
            logger.error(f"Failed to list Dropbox folder {watch_path}: {e}")
            return

        # -------------------------------------------------------
        # Step 4: Filter entries
        # -------------------------------------------------------
        file_entries = []
        for entry in entries:
            # Only process files (skip folders, deletions)
            if entry.get(".tag") != "file":
                continue

            name = entry.get("name", "")
            ext = Path(name).suffix.lower()
            size = entry.get("size", 0)

            # Check extension
            if ext not in supported_extensions:
                logger.debug(f"Skipping unsupported extension: {name} ({ext})")
                files_skipped += 1
                continue

            # Check file size
            if size > _MAX_FILE_SIZE:
                logger.warning(f"Skipping oversized file: {name} ({size:,} bytes > {_MAX_FILE_SIZE:,})")
                files_skipped += 1
                continue

            file_entries.append(entry)

        if not file_entries:
            # Still update cursor even if no files to process
            if new_cursor:
                trigger_state.set_cursor("dropbox", new_cursor)
            requests_used = client._request_count - request_count_start
            report_success("dropbox")
            logger.info(
                f"Dropbox poll complete: 0 processed, {files_skipped} skipped, 0 errors "
                f"({requests_used} API requests)"
            )
            return

        # -------------------------------------------------------
        # Step 5: Download and ingest each file
        # -------------------------------------------------------
        temp_dir = tempfile.mkdtemp(prefix="baker_dropbox_")

        try:
            for entry in file_entries:
                entry_name = entry.get("name", "?")
                entry_path = entry.get("path_display") or entry.get("path_lower", "")
                entry_id = entry.get("id", "")
                entry_size = entry.get("size", 0)

                try:
                    # 5a. Download
                    local_path = client.download_file(entry_path, Path(temp_dir))
                    logger.info(f"Downloaded: {entry_name} ({entry_size:,} bytes)")

                    # 5a2. Store full text in PostgreSQL (SPECIALIST-UPGRADE-1A)
                    try:
                        from tools.ingest.extractors import extract
                        from tools.ingest.dedup import compute_file_hash
                        full_text = extract(local_path)
                        file_hash = compute_file_hash(local_path)
                        store = _get_store()
                        doc_id = store.store_document_full(
                            source_path=entry_path,
                            filename=entry_name,
                            file_hash=file_hash,
                            full_text=full_text,
                            token_count=len(full_text) // 4 if full_text else 0,
                        )
                        if doc_id:
                            logger.info(f"Full text stored: {entry_name} → documents.id={doc_id} ({len(full_text):,} chars)")
                            # Queue classification + extraction (SPECIALIST-UPGRADE-1B)
                            try:
                                from tools.document_pipeline import queue_extraction
                                queue_extraction(doc_id)
                            except Exception as qe:
                                logger.warning(f"Queue extraction failed for doc {doc_id} (non-fatal): {qe}")
                    except Exception as e:
                        logger.warning(f"Full text storage failed for {entry_name} (non-fatal): {e}")

                    # 5b. Ingest (chunks to Qdrant — unchanged)
                    from tools.ingest.pipeline import ingest_file
                    result = ingest_file(local_path, collection="baker-documents")

                    # 5c. Check result
                    if result.skipped:
                        logger.info(f"Skipped (duplicate): {entry_name} — {result.skip_reason}")
                        files_skipped += 1
                    elif result.error:
                        logger.warning(f"Ingestion error for {entry_name}: {result.error}")
                        files_errored += 1
                    else:
                        logger.info(
                            f"Ingested: {entry_name} → {result.collection} "
                            f"({result.chunk_count} chunks, hash={result.file_hash[:12]})"
                        )
                        files_processed += 1

                        # 5d. Feed to Sentinel pipeline
                        classification = "dropbox_file_new" if not had_cursor else "dropbox_file_modified"
                        _feed_to_pipeline(entry, classification)

                except Exception as e:
                    logger.error(f"Failed to process {entry_name}: {e}")
                    files_errored += 1
                    continue
                finally:
                    # Clean up individual file (best-effort)
                    try:
                        local_file = Path(temp_dir) / entry_name
                        if local_file.exists():
                            local_file.unlink()
                    except Exception:
                        pass

        finally:
            # Clean up entire temp directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up temp dir {temp_dir}: {e}")

        # -------------------------------------------------------
        # Step 6: Store new cursor
        # -------------------------------------------------------
        if new_cursor:
            trigger_state.set_cursor("dropbox", new_cursor)

        # -------------------------------------------------------
        # Step 7: Log summary
        # -------------------------------------------------------
        requests_used = client._request_count - request_count_start
        report_success("dropbox")
        logger.info(
            f"Dropbox poll complete: {files_processed} processed, {files_skipped} skipped, "
            f"{files_errored} errors ({requests_used} API requests)"
        )

    except Exception as e:
        report_failure("dropbox", str(e))
        logger.error(f"dropbox poll failed: {e}")



def _feed_to_pipeline(entry: dict, classification: str):
    """Feed a processed file event into the Sentinel pipeline."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        trigger = TriggerEvent(
            type=classification,
            content=(
                f"File: {entry.get('name', '?')}\n"
                f"Path: {entry.get('path_display', '?')}\n"
                f"Size: {entry.get('size', 0)} bytes\n"
                f"Collection: baker-documents"
            ),
            source_id=f"dropbox:{entry.get('id', '?')}",
            contact_name=None,
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for {entry.get('name', '?')}: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_dropbox_poll()
