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
from datetime import datetime, timedelta, timezone
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
    DROPBOX-EXPANSION-5: Polls multiple watch paths (comma-separated).
    Each path gets its own cursor and watermark.
    """
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("dropbox"):
        return

    logger.info("Dropbox trigger: starting poll...")

    from config.settings import config

    try:
        client = _get_client()
        raw_watch_path = config.dropbox.watch_path
        # DROPBOX-EXPANSION-5: Support comma-separated paths
        watch_paths = [p.strip() for p in raw_watch_path.split(",") if p.strip()]
        if not watch_paths:
            watch_paths = ["/Baker-Feed"]

        total_processed = 0
        total_skipped = 0
        total_errored = 0

        for watch_path in watch_paths:
            try:
                p, s, e = _poll_single_path(client, watch_path)
                total_processed += p
                total_skipped += s
                total_errored += e
            except Exception as path_err:
                logger.error(f"Dropbox poll failed for path {watch_path}: {path_err}")

        report_success("dropbox")
        logger.info(f"Dropbox poll complete: {total_processed} processed, {total_skipped} skipped, {total_errored} errors across {len(watch_paths)} path(s)")

    except Exception as e:
        report_failure("dropbox", str(e))
        logger.error(f"dropbox poll failed: {e}")


def _poll_single_path(client, watch_path: str) -> tuple:
    """Poll a single Dropbox path. Returns (processed, skipped, errored).
    DROPBOX-EXPANSION-5: Extracted from run_dropbox_poll() for multi-path support.
    """
    from triggers.sentinel_health import report_success, report_failure

    try:
        supported_extensions = _get_supported_extensions()

        files_processed = 0
        files_skipped = 0
        files_errored = 0
        processed_file_names = []  # ALERT-BATCH-1: collect for summary alert
        request_count_start = client._request_count

        # DROPBOX-EXPANSION-5: Per-path cursor and watermark keys
        _cursor_key = f"dropbox:{watch_path}"
        _watermark_key = f"dropbox:{watch_path}"

        # Migrate legacy "dropbox" key to path-specific key (one-time)
        if watch_path == "/Baker-Feed":
            _legacy_cursor = trigger_state.get_cursor("dropbox")
            _legacy_wm = trigger_state.get_watermark("dropbox")
            _new_cursor = trigger_state.get_cursor(_cursor_key)
            if _legacy_cursor and not _new_cursor:
                trigger_state.set_cursor(_cursor_key, _legacy_cursor)
                logger.info(f"Dropbox: migrated legacy cursor to {_cursor_key}")
            if _legacy_wm and not trigger_state.get_watermark(_watermark_key):
                trigger_state.set_watermark(_watermark_key, _legacy_wm)
                logger.info(f"Dropbox: migrated legacy watermark to {_watermark_key}")

        # -------------------------------------------------------
        # Step 1-3: Get cursor and list changes
        # -------------------------------------------------------
        cursor = trigger_state.get_cursor(_cursor_key)
        had_cursor = cursor is not None

        # PM-OOM-1 H4: Stale watermark safeguard. If last poll was >24h ago,
        # don't batch-process the backlog (OOM risk). Get a fresh cursor only.
        last_poll = trigger_state.get_watermark(_watermark_key)
        stale = (datetime.now(timezone.utc) - last_poll) > timedelta(hours=24) if last_poll else True
        if stale and had_cursor:
            logger.warning(
                f"Dropbox: watermark stale for {watch_path} (last poll: {last_poll}) — "
                "resetting cursor to skip backlog"
            )
            # Get fresh cursor without processing files
            try:
                _entries, new_cursor = client.list_folder(watch_path, cursor=cursor)
                if new_cursor:
                    trigger_state.set_cursor(_cursor_key, new_cursor)
                trigger_state.set_watermark(_watermark_key, datetime.now(timezone.utc))
                logger.info(
                    f"Dropbox: cursor reset complete for {watch_path} ({len(_entries)} backlog entries skipped). "
                    "Next poll will process only new changes."
                )
            except Exception as e:
                logger.error(f"Dropbox cursor reset failed for {watch_path}: {e}")
            return (0, 0, 0)

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
                trigger_state.set_cursor(_cursor_key, new_cursor)
            trigger_state.set_watermark(_watermark_key, datetime.now(timezone.utc))
            logger.info(
                f"Dropbox poll {watch_path}: 0 processed, {files_skipped} skipped"
            )
            return (0, files_skipped, 0)

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

                    # AO-PM-1: Soul.md sync — Dropbox is master, DB is cache
                    if entry_name == "Soul.md" and "source_of_truth" in entry_path.lower():
                        _sync_soul_to_db(local_path, entry_path)
                        files_processed += 1
                        processed_file_names.append(f"{entry_name} (soul sync)")
                        continue

                    # 5a2. Store full text in PostgreSQL (SPECIALIST-UPGRADE-1A)
                    try:
                        from tools.ingest.extractors import extract
                        from tools.ingest.dedup import compute_file_hash
                        full_text = extract(local_path)
                        file_hash = compute_file_hash(local_path)
                        store = _get_store()
                        # Determine owner from path (WEALTH-MANAGER)
                        _path_lower = entry_path.lower()
                        _owner = "edita" if ("/edita-feed" in _path_lower or "/baker-feed/edita/" in _path_lower) else "dimitry"
                        doc_id = store.store_document_full(
                            source_path=entry_path,
                            filename=entry_name,
                            file_hash=file_hash,
                            full_text=full_text,
                            token_count=len(full_text) // 4 if full_text else 0,
                            owner=_owner,
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
                        processed_file_names.append(entry_name)

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
        # Step 5e: ALERT-BATCH-1 — One summary alert for the batch
        # -------------------------------------------------------
        if processed_file_names:
            _create_batch_alert(processed_file_names)

        # -------------------------------------------------------
        # Step 6: Store new cursor
        # -------------------------------------------------------
        if new_cursor:
            trigger_state.set_cursor(_cursor_key, new_cursor)

        trigger_state.set_watermark(_watermark_key, datetime.now(timezone.utc))

        # -------------------------------------------------------
        # Step 7: Log summary
        # -------------------------------------------------------
        logger.info(
            f"Dropbox poll {watch_path}: {files_processed} processed, {files_skipped} skipped, "
            f"{files_errored} errors"
        )
        return (files_processed, files_skipped, files_errored)

    except Exception as e:
        logger.error(f"Dropbox poll failed for {watch_path}: {e}")
        return (0, 0, 1)



def _sync_soul_to_db(local_path, entry_path: str):
    """AO-PM-1: Sync Soul.md from Dropbox (master) to capability_sets.system_prompt (cache).
    Cowork rule: Soul.md ALWAYS wins. DB is cache. Log warning if DB diverges."""
    try:
        import hashlib
        soul_text = Path(local_path).read_text(encoding="utf-8").strip()
        if not soul_text or len(soul_text) < 100:
            logger.warning(f"Soul.md too short ({len(soul_text)} chars) — skipping sync")
            return

        # PM-FACTORY: Determine which PM this Soul.md belongs to
        from orchestrator.capability_runner import PM_REGISTRY
        _path_lower = entry_path.lower()
        cap_slug = None
        for slug, config in PM_REGISTRY.items():
            keywords = config.get("soul_md_keywords", [])
            if any(kw in _path_lower for kw in keywords):
                cap_slug = slug
                break
        if not cap_slug:
            logger.info(f"Soul.md found at {entry_path} but no matching PM capability — skipping")
            return

        import psycopg2
        from config.settings import config
        conn = psycopg2.connect(**config.postgres.dsn_params)
        cur = conn.cursor()

        cur.execute("SELECT system_prompt FROM capability_sets WHERE slug = %s", (cap_slug,))
        row = cur.fetchone()
        if not row:
            logger.warning(f"Capability {cap_slug} not found in DB — cannot sync Soul.md")
            conn.close()
            return

        db_prompt = (row[0] or "").strip()
        file_hash = hashlib.sha256(soul_text.encode()).hexdigest()[:16]
        db_hash = hashlib.sha256(db_prompt.encode()).hexdigest()[:16]

        if file_hash == db_hash:
            logger.info(f"Soul.md sync: {cap_slug} already matches DB (hash={file_hash})")
        else:
            # Soul.md wins — overwrite DB
            if db_prompt and db_prompt != soul_text:
                logger.warning(
                    f"Soul.md sync: {cap_slug} DB version DIVERGES from file "
                    f"(db_hash={db_hash}, file_hash={file_hash}). "
                    f"Overwriting DB with Soul.md (file is master)."
                )
            cur.execute(
                "UPDATE capability_sets SET system_prompt = %s, updated_at = NOW() WHERE slug = %s",
                (soul_text, cap_slug),
            )
            conn.commit()
            logger.info(f"Soul.md sync: {cap_slug} system_prompt updated from Dropbox ({len(soul_text)} chars)")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Soul.md sync failed (non-fatal): {e}")


def _create_batch_alert(file_names: list):
    """ALERT-BATCH-1: Create one summary alert for a batch of ingested documents."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        count = len(file_names)
        # Group by common path prefix or just list them
        if count == 1:
            title = f"Document ingested: {file_names[0]}"
        else:
            title = f"{count} documents ingested from Dropbox"

        # Build body with file list (max 20 lines)
        body_lines = [f"**{count} file(s)** ingested and stored:\n"]
        for name in file_names[:20]:
            body_lines.append(f"- {name}")
        if count > 20:
            body_lines.append(f"- ... and {count - 20} more")

        # Try to detect matter from file names
        matter_slug = None
        try:
            from orchestrator.pipeline import _match_matter_slug
            combined = " ".join(file_names)
            matter_slug = _match_matter_slug(combined, "", store)
        except Exception:
            pass

        from datetime import date
        source_id = f"dropbox-batch-{date.today().isoformat()}-{count}"

        store.create_alert(
            tier=3,  # Info tier — not urgent
            title=title[:120],
            body="\n".join(body_lines),
            action_required=False,
            matter_slug=matter_slug,
            tags=["documents", "dropbox"],
            source="dropbox_batch",
            source_id=source_id,
        )
    except Exception as e:
        logger.warning(f"Batch alert creation failed (non-fatal): {e}")


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


def run_edita_dropbox_poll():
    """WEALTH-MANAGER: Poll /Edita-Feed/ for Edita's documents.

    Reuses the same Dropbox client and ingestion pipeline.
    Uses a separate cursor key ('dropbox_edita') so it tracks independently.
    Documents are stored with owner='edita'.
    """
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("dropbox_edita"):
        return

    edita_path = "/Edita-Feed"
    logger.info(f"Edita Dropbox trigger: polling {edita_path}...")

    try:
        client = _get_client()
        supported_extensions = _get_supported_extensions()

        cursor = trigger_state.get_cursor("dropbox_edita")
        had_cursor = cursor is not None

        try:
            entries, new_cursor = client.list_folder(edita_path, cursor=cursor)
        except Exception as e:
            if "409" in str(e) or "path/not_found" in str(e):
                logger.info(f"Edita folder {edita_path} not found — create it to start polling")
                report_success("dropbox_edita")
                return
            report_failure("dropbox_edita", str(e))
            return

        file_entries = []
        for entry in entries:
            if entry.get(".tag") != "file":
                continue
            name = entry.get("name", "")
            ext = Path(name).suffix.lower()
            size = entry.get("size", 0)
            if ext not in supported_extensions or size > _MAX_FILE_SIZE:
                continue
            file_entries.append(entry)

        if not file_entries:
            if new_cursor:
                trigger_state.set_cursor("dropbox_edita", new_cursor)
            report_success("dropbox_edita")
            logger.info(f"Edita Dropbox poll: 0 files to process")
            return

        temp_dir = tempfile.mkdtemp(prefix="baker_edita_")
        processed = 0
        try:
            for entry in file_entries:
                entry_name = entry.get("name", "?")
                entry_path = entry.get("path_display") or entry.get("path_lower", "")
                try:
                    local_path = client.download_file(entry_path, Path(temp_dir))
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
                        owner="edita",
                    )
                    if doc_id:
                        logger.info(f"Edita doc stored: {entry_name} → id={doc_id}")
                        try:
                            from tools.document_pipeline import queue_extraction
                            queue_extraction(doc_id)
                        except Exception:
                            pass
                    processed += 1
                except Exception as e:
                    logger.warning(f"Edita file failed: {entry_name}: {e}")
                finally:
                    try:
                        (Path(temp_dir) / entry_name).unlink(missing_ok=True)
                    except Exception:
                        pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        if new_cursor:
            trigger_state.set_cursor("dropbox_edita", new_cursor)
        report_success("dropbox_edita")
        logger.info(f"Edita Dropbox poll: {processed} processed out of {len(file_entries)} files")

    except Exception as e:
        report_failure("dropbox_edita", str(e))
        logger.error(f"Edita Dropbox poll failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_dropbox_poll()
