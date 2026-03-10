"""
Backfill script: Store email attachments as standalone documents.

Parses the === ATTACHMENTS === section from email_messages.full_body,
stores each attachment as a separate row in the documents table, and
queues classification + extraction.

Zero Gmail API calls — uses text already in the database.

Usage:
    python scripts/backfill_email_attachments.py --dry-run
    python scripts/backfill_email_attachments.py --limit 10
    python scripts/backfill_email_attachments.py --all

Cost: ~$0.03/attachment for classify + extract (Haiku).
"""
import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill.email_attachments")

# Pattern: --- Attachment: filename.ext ---
_ATTACHMENT_HEADER = re.compile(r"^---\s*Attachment:\s*(.+?)\s*---\s*$", re.MULTILINE)


def parse_attachments(attachment_section: str) -> list:
    """Parse attachment section into list of {filename, text} dicts."""
    results = []
    headers = list(_ATTACHMENT_HEADER.finditer(attachment_section))

    for i, match in enumerate(headers):
        filename = match.group(1).strip()
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(attachment_section)
        text = attachment_section[start:end].strip()

        if text and len(text) >= 20:  # skip trivially short extractions
            results.append({"filename": filename, "text": text})

    return results


def backfill_email_attachments(limit: int = None, dry_run: bool = False):
    """Parse email attachments from full_body, store as documents, queue extraction."""
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT message_id, subject,
                   SUBSTRING(full_body FROM POSITION('=== ATTACHMENTS ===' IN full_body))
            FROM email_messages
            WHERE full_body LIKE '%%=== ATTACHMENTS ===%%'
            ORDER BY received_date DESC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    logger.info(f"Found {len(rows)} emails with attachments")

    if limit:
        rows = rows[:limit]

    # Check existing hashes
    conn = store._get_conn()
    existing_hashes = set()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT file_hash FROM documents WHERE source_path LIKE 'email:%%'")
            existing_hashes = {r[0] for r in cur.fetchall()}
            cur.close()
        finally:
            store._put_conn(conn)
    logger.info(f"Existing email attachment docs: {len(existing_hashes)}")

    total_attachments = 0
    stored = 0
    skipped = 0
    classified = 0
    errors = 0

    for i, (message_id, subject, att_section) in enumerate(rows):
        if not att_section:
            continue

        attachments = parse_attachments(att_section)
        total_attachments += len(attachments)

        for att in attachments:
            filename = att["filename"]
            text = att["text"]

            if dry_run:
                logger.info(f"  [DRY-RUN] {subject[:50]} → {filename} ({len(text):,} chars)")
                stored += 1
                continue

            try:
                file_hash = hashlib.sha256(text.encode()).hexdigest()

                if file_hash in existing_hashes:
                    skipped += 1
                    continue

                doc_id = store.store_document_full(
                    source_path=f"email:{message_id}/{filename}",
                    filename=filename,
                    file_hash=file_hash,
                    full_text=text,
                    token_count=len(text) // 4,
                )

                if doc_id:
                    stored += 1
                    existing_hashes.add(file_hash)
                    logger.info(f"  Stored: {filename} → doc {doc_id} ({len(text):,} chars) [from: {subject[:40]}]")

                    # Queue extraction
                    from orchestrator.cost_monitor import check_circuit_breaker
                    allowed, daily_cost = check_circuit_breaker()
                    if allowed:
                        from tools.document_pipeline import run_pipeline
                        time.sleep(2)
                        run_pipeline(doc_id)
                        classified += 1
                    else:
                        logger.warning(f"  Circuit breaker at €{daily_cost:.2f}, stopping extraction")
                        break

            except Exception as e:
                logger.warning(f"  Error processing {filename}: {e}")
                errors += 1

        # Progress every 10 emails
        if (i + 1) % 10 == 0:
            logger.info(
                f"Progress: {i + 1}/{len(rows)} emails — "
                f"{stored} stored, {classified} classified, {skipped} skipped, {errors} errors"
            )

    if dry_run:
        logger.info(f"Dry run complete. {total_attachments} attachments in {len(rows)} emails.")
    else:
        logger.info(
            f"Backfill complete: {stored} stored, {classified} classified, "
            f"{skipped} skipped, {errors} errors ({total_attachments} total attachments)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill email attachments to documents table")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=None, help="Max emails to process")
    parser.add_argument("--all", action="store_true", help="Process all")
    args = parser.parse_args()

    limit = None if args.all else (args.limit or 10)
    backfill_email_attachments(limit=limit, dry_run=args.dry_run)
