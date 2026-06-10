"""
BACKFILL_BLUEWIN_1: Historical IMAP backfill of dvallen@bluewin.ch.

Backfills the full mailbox history (INBOX + sent folder, messages AND
attachments) into email_messages + email_attachments, BEFORE the live
poller's 2026-06-09 start. The live poller (triggers/bluewin_poller.py)
keeps ingesting forward; this script never touches its watermark.

Design (locked by brief BACKFILL_BLUEWIN_1):
- NO LLM classification on historical rows: priority=NULL, direct INSERT
  (dedup ON CONFLICT message_id DO NOTHING), no _process_email_threads.
- Resumable: cursor = "<uidvalidity>:<last-processed-uid>" per folder in
  email_backfill_progress (source='bluewin:<folder>'); crash-safe re-run.
- Batched: 200 msgs/batch, 0.5s sleep between batches (Swisscom
  throttle-safety), oldest -> newest (ascending UID).
- Attachments via kbl.attachment_store.insert_attachment (b3's
  EMAIL_ATTACHMENT_STORE_1 lane — locked interface).
- Parsing helpers REUSED from triggers.bluewin_poller (no fork-copy).

Usage:
    python3 scripts/backfill_bluewin.py                 # full resumable run
    python3 scripts/backfill_bluewin.py --limit 50      # dry-run: first 50
        # msgs after cursor, INSERTs real rows but does NOT advance the
        # cursor — re-running the same dry-run proves dedup (0 new rows).
    python3 scripts/backfill_bluewin.py --skip-attachments
        # explicit degraded mode if kbl.attachment_store is unavailable

Env: DATABASE_URL (or POSTGRES_* split), BLUEWIN_USER, BLUEWIN_PASS.
Progress: one log line per batch; run under nohup with output to
/tmp/backfill_bluewin.log and check with `tail -3`, never `cat`.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.bluewin_poller import (  # noqa: E402  (reused, not forked)
    BLUEWIN_IMAP_HOST,
    BLUEWIN_IMAP_PORT,
    _decode_header_value,
    _extract_body,
    _extract_sender,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("backfill_bluewin")

SOURCE = "bluewin"
BATCH_SIZE = 200
BATCH_SLEEP_S = 0.5
PROGRESS_PREFIX = "bluewin:"  # email_backfill_progress.source = 'bluewin:<folder>'

# Locked DDL from EMAIL_ATTACHMENT_STORE_1 (CODE_3_PENDING.md) — idempotent
# self-heal so the cursor table exists even if this lane runs before b3's
# migration is applied. Byte-for-byte the locked schema; no drift.
_PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS email_backfill_progress (
  source TEXT PRIMARY KEY, cursor TEXT,
  done_count BIGINT DEFAULT 0, total_estimate BIGINT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
"""


# ── pure helpers (unit-tested) ──────────────────────────────────────────


def parse_cursor(raw: str | None) -> tuple[int | None, int]:
    """Parse "<uidvalidity>:<uid>" cursor -> (uidvalidity, last_uid).

    Returns (None, 0) when no cursor exists yet.
    """
    if not raw:
        return None, 0
    try:
        validity_s, uid_s = raw.split(":", 1)
        return int(validity_s), int(uid_s)
    except (ValueError, AttributeError):
        logger.warning("Unparseable cursor %r — restarting folder from UID 0", raw)
        return None, 0


def format_cursor(uidvalidity: int, last_uid: int) -> str:
    return f"{uidvalidity}:{last_uid}"


def detect_sent_folder(list_lines: list[bytes]) -> str | None:
    r"""Pick the sent folder from IMAP LIST response lines.

    Prefers the \Sent special-use flag (RFC 6154); falls back to common
    Bluewin/IMAP names. Returns None when nothing matches.
    """
    name_re = re.compile(rb'\(([^)]*)\)\s+"([^"]*)"\s+"?([^"]+?)"?\s*$')
    candidates: list[str] = []
    for line in list_lines or []:
        if not line:
            continue
        m = name_re.search(line)
        if not m:
            continue
        flags, _delim, name = m.group(1), m.group(2), m.group(3)
        decoded = name.decode("utf-8", errors="replace")
        if rb"\sent" in flags.lower():
            return decoded  # special-use flag wins outright
        candidates.append(decoded)
    fallback_order = ["Sent", "INBOX.Sent", "Sent Messages", "Sent Items", "INBOX/Sent"]
    by_lower = {c.lower(): c for c in candidates}
    for want in fallback_order:
        if want.lower() in by_lower:
            return by_lower[want.lower()]
    return None


def message_id_for(msg, folder: str, uidvalidity: int, uid: int) -> str:
    """Message-ID header (stripped), or a deterministic synthetic id.

    The synthetic id includes UIDVALIDITY so a validity reset cannot make
    two DIFFERENT messages collide on the same id (silent loss); the cost
    is possible re-insert duplicates after a reset, which is rare + loud.
    """
    raw = (msg.get("Message-ID") or "").strip().strip("<>").strip()
    if raw:
        return raw
    return f"bluewin-{folder}-{uidvalidity}-uid-{uid}"


def extract_attachments(msg) -> list[tuple[str, str, bytes]]:
    """Return [(filename, mime_type, payload_bytes)] for real attachments.

    A part counts as an attachment when it carries a filename or an
    `attachment` Content-Disposition; multipart containers and the
    text/plain|html body parts the poller already captures are skipped.
    """
    out: list[tuple[str, str, bytes]] = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        cd = str(part.get("Content-Disposition", ""))
        filename = part.get_filename()
        if not filename and "attachment" not in cd.lower():
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001 — malformed part must not kill the message
            payload = None
        if not payload:
            continue
        name = _decode_header_value(filename) if filename else "(unnamed)"
        out.append((name, part.get_content_type(), payload))
    return out


def parse_received_date(msg, internaldate_raw: bytes | None):
    """Date header -> tz-aware datetime; INTERNALDATE fallback; else None."""
    date_str = msg.get("Date", "")
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:  # noqa: BLE001
            pass
    if internaldate_raw:
        try:
            tt = imaplib.Internaldate2tuple(internaldate_raw)
            if tt:
                return datetime.fromtimestamp(time.mktime(tt), tz=timezone.utc)
        except Exception:  # noqa: BLE001
            pass
    return None


def chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ── DB layer ────────────────────────────────────────────────────────────


def _ensure_progress_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(_PROGRESS_DDL)
    conn.commit()


def read_progress(conn, folder: str) -> str | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cursor FROM email_backfill_progress WHERE source = %s",
                (PROGRESS_PREFIX + folder,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.error("read_progress(%s) failed: %s", folder, e)
        raise


def write_progress(conn, folder: str, cursor_val: str, done_delta: int,
                   total_estimate: int | None = None) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO email_backfill_progress (source, cursor, done_count, total_estimate, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (source) DO UPDATE SET
                    cursor = EXCLUDED.cursor,
                    done_count = email_backfill_progress.done_count + %s,
                    total_estimate = COALESCE(EXCLUDED.total_estimate, email_backfill_progress.total_estimate),
                    updated_at = now()
                """,
                (PROGRESS_PREFIX + folder, cursor_val, done_delta, total_estimate, done_delta),
            )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.error("write_progress(%s) failed: %s", folder, e)
        raise


INSERT_MESSAGE_SQL = """
INSERT INTO email_messages
    (message_id, thread_id, sender_name, sender_email,
     subject, full_body, received_date, priority, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)
ON CONFLICT (message_id) DO NOTHING
"""


def insert_message_row(cur, parsed: dict) -> int:
    """INSERT one historical row; returns 1 if inserted, 0 if deduped."""
    cur.execute(
        INSERT_MESSAGE_SQL,
        (
            parsed["message_id"],
            parsed["thread_id"],
            parsed["sender_name"],
            parsed["sender_email"],
            parsed["subject"],
            parsed["full_body"],
            parsed["received_date"],
            SOURCE,
        ),
    )
    return cur.rowcount


# ── message parsing (composes reused poller helpers) ────────────────────


def parse_message(raw_bytes: bytes, folder: str, uidvalidity: int, uid: int,
                  internaldate_raw: bytes | None = None) -> tuple[dict, list]:
    """Raw RFC822 bytes -> (email_messages row dict, attachments list)."""
    msg = email.message_from_bytes(raw_bytes)
    message_id = message_id_for(msg, folder, uidvalidity, uid)
    sender_name, sender_email = _extract_sender(msg)
    parsed = {
        "message_id": message_id,
        "thread_id": message_id,  # mirrors live poller's dedup_key usage
        "sender_name": sender_name,
        "sender_email": sender_email,
        "subject": _decode_header_value(msg.get("Subject", "(no subject)")),
        "full_body": _extract_body(msg),
        "received_date": parse_received_date(msg, internaldate_raw),
    }
    return parsed, extract_attachments(msg)


# ── IMAP + run loop ─────────────────────────────────────────────────────


def _imap_connect():
    user = os.getenv("BLUEWIN_USER", "dvallen@bluewin.ch")
    password = os.getenv("BLUEWIN_PASS", "")
    if not password:
        logger.error("BLUEWIN_PASS not set — aborting (fail loud, no silent skip)")
        sys.exit(2)
    conn = imaplib.IMAP4_SSL(BLUEWIN_IMAP_HOST, BLUEWIN_IMAP_PORT)
    conn.login(user, password)
    return conn


def _quote_folder(folder: str) -> str:
    """IMAP-quote a mailbox name (imaplib does NOT quote; names with spaces
    like "Sent Messages" make STATUS/SELECT fail with Invalid arguments)."""
    if folder.startswith('"') and folder.endswith('"'):
        return folder
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _folder_status(imap, folder: str) -> tuple[int, int]:
    """Return (uidvalidity, message_count) for folder."""
    typ, data = imap.status(_quote_folder(folder), "(UIDVALIDITY MESSAGES)")
    if typ != "OK" or not data or not data[0]:
        raise RuntimeError(f"STATUS {folder} failed: {typ} {data!r}")
    text = data[0].decode("utf-8", errors="replace")
    validity = int(re.search(r"UIDVALIDITY (\d+)", text).group(1))
    count = int(re.search(r"MESSAGES (\d+)", text).group(1))
    return validity, count


def _load_attachment_writer(skip_attachments: bool):
    """Locked-interface import of b3's store. Fail LOUD unless explicitly skipped."""
    if skip_attachments:
        logger.warning("--skip-attachments: historical attachments will NOT be stored this run")
        return None
    try:
        from kbl.attachment_store import insert_attachment  # noqa: PLC0415
        return insert_attachment
    except ImportError:
        logger.error(
            "kbl.attachment_store not available (b3 EMAIL_ATTACHMENT_STORE_1 not merged?). "
            "Re-run after rebase, or pass --skip-attachments for an explicit degraded run."
        )
        sys.exit(3)


class AttachmentStoreFailure(RuntimeError):
    """An attachment insert failed (None return or exception from the store).

    G3-S1 (codex): insert_attachment -> None is the locked FAILURE semantics.
    Swallowing it and advancing the cursor loses the attachment FOREVER on
    resume, because message-id dedup blocks a re-walk of that message. The
    batch must roll back and retry; after MAX_BATCH_ATTEMPTS, abort loud.
    """

    def __init__(self, folder: str, uid: int, filename: str, cause: Exception | None = None):
        self.folder, self.uid, self.filename, self.cause = folder, uid, filename, cause
        detail = f" ({cause})" if cause else " (store returned None)"
        super().__init__(f"attachment store failed: {folder} uid={uid} file={filename!r}{detail}")


MAX_BATCH_ATTEMPTS = 3


def _process_batch(imap, db_conn, folder: str, uidvalidity: int, batch: list[int],
                   insert_attachment) -> tuple[int, int, int]:
    """One ATTEMPT at a batch; returns (processed, inserted, att_count).

    Raises AttachmentStoreFailure on any attachment-store failure — caller
    rolls back (message inserts of this attempt included) and the cursor is
    NOT advanced, so the whole batch replays cleanly on retry/resume.
    """
    processed = inserted = att_count = 0
    with db_conn.cursor() as cur:
        for uid in batch:
            typ, fdata = imap.uid("fetch", str(uid), "(RFC822 INTERNALDATE)")
            if typ != "OK" or not fdata or fdata[0] is None:
                logger.warning("%s uid=%d: fetch failed — skipping", folder, uid)
                continue
            raw = None
            internaldate_raw = None
            for item in fdata:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw = item[1]
                    internaldate_raw = item[0]
                elif isinstance(item, bytes) and b"INTERNALDATE" in item:
                    internaldate_raw = item
            if not raw:
                logger.warning("%s uid=%d: empty RFC822 — skipping", folder, uid)
                continue
            try:
                parsed, attachments = parse_message(
                    raw, folder, uidvalidity, uid, internaldate_raw
                )
            except Exception as e:  # noqa: BLE001 — one bad msg must not kill the run
                logger.warning("%s uid=%d: parse failed: %s — skipping", folder, uid, e)
                continue
            inserted += insert_message_row(cur, parsed)
            if insert_attachment is not None:
                for fname, mime, payload in attachments:
                    try:
                        att_id = insert_attachment(parsed["message_id"], SOURCE,
                                                   fname, mime, payload)
                    except Exception as e:  # noqa: BLE001 — same failure class as None
                        raise AttachmentStoreFailure(folder, uid, fname, e) from e
                    if att_id is None:
                        raise AttachmentStoreFailure(folder, uid, fname)
                    att_count += 1
            processed += 1
    db_conn.commit()
    return processed, inserted, att_count


def backfill_folder(imap, db_conn, folder: str, insert_attachment, limit: int | None,
                    batch_size: int = BATCH_SIZE) -> tuple[int, int, int]:
    """Backfill one folder oldest->newest. Returns (processed, inserted, attachments)."""
    dry_run = limit is not None
    uidvalidity, msg_count = _folder_status(imap, folder)

    cur_validity, last_uid = parse_cursor(read_progress(db_conn, folder))
    if cur_validity is not None and cur_validity != uidvalidity:
        logger.warning(
            "%s: UIDVALIDITY changed %s -> %s — restarting folder from UID 0 "
            "(dedup on message_id absorbs the re-read)",
            folder, cur_validity, uidvalidity,
        )
        last_uid = 0

    typ, data = imap.select(_quote_folder(folder), readonly=True)
    if typ != "OK":
        raise RuntimeError(f"SELECT {folder} failed: {typ} {data!r}")

    typ, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
    if typ != "OK":
        raise RuntimeError(f"UID SEARCH {folder} failed: {typ}")
    uids = sorted(int(u) for u in (data[0].split() if data and data[0] else []))
    # IMAP quirk: "N:*" returns the last message even when its UID < N — filter.
    uids = [u for u in uids if u > last_uid]
    if limit is not None:
        uids = uids[:limit]

    logger.info(
        "%s: %d msgs in folder, cursor uid=%d, %d to process%s",
        folder, msg_count, last_uid, len(uids), " (DRY-RUN, cursor frozen)" if dry_run else "",
    )
    if not uids:
        return 0, 0, 0

    processed = inserted = att_count = 0
    for batch in chunks(uids, batch_size):
        for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
            try:
                b_processed, b_inserted, b_atts = _process_batch(
                    imap, db_conn, folder, uidvalidity, batch, insert_attachment
                )
                break
            except AttachmentStoreFailure as e:
                db_conn.rollback()
                if attempt == MAX_BATCH_ATTEMPTS:
                    logger.error(
                        "%s: batch uid %d..%d ABORTED after %d attachment-store "
                        "failures (cursor NOT advanced — resume replays this batch): %s",
                        folder, batch[0], batch[-1], MAX_BATCH_ATTEMPTS, e,
                    )
                    raise
                logger.warning(
                    "%s: attempt %d/%d rolled back (%s) — retrying batch",
                    folder, attempt, MAX_BATCH_ATTEMPTS, e,
                )
                time.sleep(2 * attempt)
            except Exception as e:  # noqa: BLE001
                db_conn.rollback()
                logger.error("%s: batch failed, rolled back (cursor NOT advanced): %s", folder, e)
                raise
        processed += b_processed
        inserted += b_inserted
        att_count += b_atts
        if not dry_run:
            write_progress(db_conn, folder, format_cursor(uidvalidity, batch[-1]),
                           b_inserted, total_estimate=msg_count)
        logger.info(
            "%s: batch -> uid %d | processed %d/%d | inserted %d (+%d) | attachments %d",
            folder, batch[-1], processed, len(uids), inserted, b_inserted, att_count,
        )
        time.sleep(BATCH_SLEEP_S)
    return processed, inserted, att_count


def main() -> int:
    ap = argparse.ArgumentParser(description="Historical bluewin IMAP backfill")
    ap.add_argument("--limit", type=int, default=None,
                    help="dry-run: process first N msgs after cursor, no cursor advance")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--folders", default=None,
                    help="comma-separated override; default INBOX + auto-detected sent")
    ap.add_argument("--skip-attachments", action="store_true",
                    help="explicit degraded run without kbl.attachment_store")
    args = ap.parse_args()

    insert_attachment = _load_attachment_writer(args.skip_attachments)

    from kbl.db import get_conn  # noqa: PLC0415 — existing pool helper, kbl pattern

    imap = _imap_connect()
    try:
        if args.folders:
            folders = [f.strip() for f in args.folders.split(",") if f.strip()]
        else:
            folders = ["INBOX"]
            typ, lines = imap.list()
            sent = detect_sent_folder(lines if typ == "OK" else [])
            if sent:
                folders.append(sent)
            else:
                logger.warning("No sent folder detected via LIST — INBOX only this run")

        totals = [0, 0, 0]
        with get_conn() as db_conn:
            _ensure_progress_table(db_conn)
            for folder in folders:
                p, i, a = backfill_folder(
                    imap, db_conn, folder, insert_attachment,
                    args.limit, args.batch_size,
                )
                totals = [t + x for t, x in zip(totals, (p, i, a))]
        logger.info(
            "DONE: processed=%d inserted=%d attachments=%d folders=%s%s",
            *totals, folders, " (DRY-RUN)" if args.limit is not None else "",
        )
        return 0
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
