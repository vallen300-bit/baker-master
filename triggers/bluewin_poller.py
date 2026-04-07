"""
BLUEWIN-IMAP-POLL-1: Poll dvallen@bluewin.ch via IMAP.
Fetches new emails since last watermark, formats them identically to
Gmail poller output, then feeds into the same processing pipeline.
"""

import imaplib
import email
import os
import logging
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime

logger = logging.getLogger("bluewin_poller")

# ── Config ──────────────────────────────────────────────────────────────
BLUEWIN_IMAP_HOST = "imaps.bluewin.ch"
BLUEWIN_IMAP_PORT = 993
BLUEWIN_USER = os.getenv("BLUEWIN_USER", "dvallen@bluewin.ch")
BLUEWIN_PASS = os.getenv("BLUEWIN_PASS", "")
BLUEWIN_FOLDER = "INBOX"
WATERMARK_KEY = "bluewin_poll"
SOURCE_TYPE = "bluewin"

# Max emails per poll cycle (safety)
MAX_FETCH = 50


def _decode_header_value(raw: str) -> str:
    """Decode RFC 2047 encoded header values."""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_body(msg) -> str:
    """Extract plain text body from email message."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
            elif ct == "text/html" and not body_parts and "attachment" not in cd:
                # Fallback to HTML if no plain text
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body_parts.append(payload.decode(charset, errors="replace"))
    return "\n".join(body_parts)[:10000]  # Cap at 10K chars


def _extract_sender(msg) -> tuple:
    """Return (sender_name, sender_email) from From header."""
    from_header = _decode_header_value(msg.get("From", ""))
    # Parse "Name <email@domain>" format
    if "<" in from_header and ">" in from_header:
        name = from_header.split("<")[0].strip().strip('"')
        addr = from_header.split("<")[1].split(">")[0].strip()
    else:
        name = ""
        addr = from_header.strip()
    return name, addr


def poll_bluewin() -> list:
    """
    Connect to Bluewin IMAP, fetch emails since last watermark.
    Returns list of dicts matching Gmail poller format:
    {
        "text": "Email Thread: ...",
        "metadata": { "source": "bluewin", "thread_id": "...", ... }
    }
    """
    if not BLUEWIN_PASS:
        logger.warning("BLUEWIN_PASS not set — skipping Bluewin poll")
        return []

    from triggers.state import TriggerState
    state = TriggerState()

    # Get watermark
    wm = state.get_watermark(WATERMARK_KEY)
    if wm:
        since_date = wm.strftime("%d-%b-%Y")  # IMAP date format: 07-Apr-2026
    else:
        # First run: look back 3 days
        since_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%d-%b-%Y")

    results = []
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(BLUEWIN_IMAP_HOST, BLUEWIN_IMAP_PORT)
        conn.login(BLUEWIN_USER, BLUEWIN_PASS)
        conn.select(BLUEWIN_FOLDER, readonly=True)

        # Search for emails since watermark
        status, msg_ids = conn.search(None, f'(SINCE {since_date})')
        if status != "OK" or not msg_ids[0]:
            logger.info(f"Bluewin poll: no new emails since {since_date}")
            return []

        id_list = msg_ids[0].split()
        # Take most recent N
        if len(id_list) > MAX_FETCH:
            id_list = id_list[-MAX_FETCH:]

        logger.info(f"Bluewin poll: {len(id_list)} emails since {since_date}")

        latest_date = None

        for msg_id in id_list:
            try:
                status, data = conn.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Extract fields
                message_id = msg.get("Message-ID", f"bluewin-{msg_id.decode()}")
                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender_name, sender_email = _extract_sender(msg)
                to_header = _decode_header_value(msg.get("To", ""))
                body = _extract_body(msg)

                # Parse date
                date_str = msg.get("Date", "")
                try:
                    received_dt = parsedate_to_datetime(date_str)
                    if received_dt.tzinfo is None:
                        received_dt = received_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    received_dt = datetime.now(timezone.utc)

                # Dedup check
                dedup_key = message_id.strip("<>")
                if state.is_processed(SOURCE_TYPE, dedup_key):
                    continue

                # Track latest date for watermark
                if latest_date is None or received_dt > latest_date:
                    latest_date = received_dt

                # Format to match Gmail poller output
                participants = f"{sender_email}, {to_header}"
                text_block = (
                    f"Email Thread: {subject}\n"
                    f"Date: {received_dt.strftime('%Y-%m-%d')}\n"
                    f"Participants: {participants}\n"
                    f"Messages: 1\n\n"
                    f"--- {sender_name or sender_email} ({received_dt.strftime('%Y-%m-%d %H:%M')}) ---\n"
                    f"{subject}\n\n"
                    f"{body}"
                )

                results.append({
                    "text": text_block,
                    "metadata": {
                        "source": "bluewin",
                        "thread_id": dedup_key,
                        "subject": subject,
                        "primary_sender": sender_name or sender_email,
                        "primary_sender_email": sender_email,
                        "received_date": received_dt.isoformat(),
                        "participants": participants,
                    }
                })

            except Exception as e:
                logger.warning(f"Bluewin: failed to parse msg {msg_id}: {e}")
                continue

        # Update watermark
        if latest_date:
            state.set_watermark(WATERMARK_KEY, latest_date)
            logger.info(f"Bluewin poll: {len(results)} new emails, watermark -> {latest_date.isoformat()}")

    except imaplib.IMAP4.error as e:
        logger.error(f"Bluewin IMAP auth/connection error: {e}")
    except Exception as e:
        logger.error(f"Bluewin poll failed: {e}")
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return results
