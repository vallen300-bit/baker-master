"""
EXCHANGE-IMAP-POLL-1: Poll dvallen@brisengroup.com via IMAP.
Temporary measure until Microsoft 365 migration.
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

logger = logging.getLogger("exchange_poller")

# ── Config ──────────────────────────────────────────────────────────────
EXCHANGE_IMAP_HOST = "exchange.evok.ch"
EXCHANGE_IMAP_PORT = 993
EXCHANGE_USER = os.getenv("EXCHANGE_USER", "dvallen@brisengroup.com")
EXCHANGE_PASS = os.getenv("EXCHANGE_PASS", "")
EXCHANGE_FOLDER = "INBOX"
WATERMARK_KEY = "exchange_poll"
SOURCE_TYPE = "exchange"

# Max emails per poll cycle (safety)
MAX_FETCH = 50

# BAKER_CAPTURE_BLINDSPOTS_1: Sent-folder sibling poller config.
# Director outbound from Outlook is invisible until polled here.
SENT_FOLDER_CANDIDATES = ["Sent Items", "Sent", "INBOX.Sent"]
WATERMARK_KEY_SENT = "exchange_poll_sent"
SOURCE_TYPE_SENT = "exchange_sent"


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
    if "<" in from_header and ">" in from_header:
        name = from_header.split("<")[0].strip().strip('"')
        addr = from_header.split("<")[1].split(">")[0].strip()
    else:
        name = ""
        addr = from_header.strip()
    return name, addr


def poll_exchange() -> list:
    """
    Connect to Exchange IMAP, fetch emails since last watermark.
    Returns list of dicts matching Gmail poller format:
    {
        "text": "Email Thread: ...",
        "metadata": { "source": "exchange", "thread_id": "...", ... }
    }
    """
    if not EXCHANGE_PASS:
        logger.warning("EXCHANGE_PASS not set — skipping Exchange poll")
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
        conn = imaplib.IMAP4_SSL(EXCHANGE_IMAP_HOST, EXCHANGE_IMAP_PORT)
        conn.login(EXCHANGE_USER, EXCHANGE_PASS)
        conn.select(EXCHANGE_FOLDER, readonly=True)

        # Search for emails since watermark
        status, msg_ids = conn.search(None, f'(SINCE {since_date})')
        if status != "OK" or not msg_ids[0]:
            logger.info(f"Exchange poll: no new emails since {since_date}")
            return []

        id_list = msg_ids[0].split()
        # Take most recent N
        if len(id_list) > MAX_FETCH:
            id_list = id_list[-MAX_FETCH:]

        logger.info(f"Exchange poll: {len(id_list)} emails since {since_date}")

        latest_date = None

        for msg_id in id_list:
            try:
                status, data = conn.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Extract fields
                message_id = msg.get("Message-ID", f"exchange-{msg_id.decode()}")
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
                        "source": "exchange",
                        "thread_id": dedup_key,
                        "subject": subject,
                        "primary_sender": sender_name or sender_email,
                        "primary_sender_email": sender_email,
                        "received_date": received_dt.isoformat(),
                        "participants": participants,
                    }
                })

            except Exception as e:
                logger.warning(f"Exchange: failed to parse msg {msg_id}: {e}")
                continue

        # Update watermark
        if latest_date:
            state.set_watermark(WATERMARK_KEY, latest_date)
            logger.info(f"Exchange poll: {len(results)} new emails, watermark -> {latest_date.isoformat()}")

        # EXCHANGE-IMAP-POLL-1: Report health
        try:
            from triggers.sentinel_health import report_success
            report_success("exchange")
        except Exception:
            pass

    except imaplib.IMAP4.error as e:
        logger.error(f"Exchange IMAP auth/connection error: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange", str(e))
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Exchange poll failed: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange", str(e))
        except Exception:
            pass
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return results


def _detect_sent_folder(conn) -> str | None:
    """Probe IMAP LIST for the Sent folder.

    EVOK Exchange may expose Sent under any of SENT_FOLDER_CANDIDATES.
    Returns the first matching folder name, or None if no candidate matches.
    """
    try:
        status, folders = conn.list()
        if status != "OK":
            logger.warning(f"IMAP LIST failed: {status}")
            return None
        folder_names = []
        for raw in folders:
            try:
                decoded = raw.decode("utf-8", errors="replace")
                if '"' in decoded:
                    # Quoted-name form: (\HasNoChildren) "/" "Sent Items"
                    folder_names.append(decoded.rsplit('"', 2)[-2])
                else:
                    # Unquoted-name form (RFC-3501 allows bare atoms for
                    # whitespace-free names): (\HasNoChildren) / Sent
                    # AH2 review bus #1350 MEDIUM — without this fallback
                    # some Exchange configs silently disable the Sent poll.
                    parts = decoded.rsplit(None, 1)
                    if len(parts) == 2 and parts[1].strip():
                        folder_names.append(parts[1].strip())
            except Exception:
                continue
        for candidate in SENT_FOLDER_CANDIDATES:
            if candidate in folder_names:
                return candidate
        logger.warning(f"No Sent folder found in: {folder_names[:20]}")
        return None
    except Exception as e:
        logger.error(f"_detect_sent_folder error: {e}")
        return None


def poll_exchange_sent() -> list:
    """
    BAKER_CAPTURE_BLINDSPOTS_1: Poll EVOK Exchange Sent folder.

    Mirrors poll_exchange() body except: (a) folder name detected at runtime
    via _detect_sent_folder(), (b) separate watermark key.

    Direction is implicit — every row has sender_email = EXCHANGE_USER (the
    Director's address). Downstream retrievers distinguish outbound by sender
    filter; no metadata.direction column exists on email_messages.
    """
    if not EXCHANGE_PASS:
        logger.warning("EXCHANGE_PASS not set — skipping Exchange Sent poll")
        return []

    from triggers.state import TriggerState
    state = TriggerState()

    wm = state.get_watermark(WATERMARK_KEY_SENT)
    if wm:
        since_date = wm.strftime("%d-%b-%Y")
    else:
        since_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%d-%b-%Y")

    results = []
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(EXCHANGE_IMAP_HOST, EXCHANGE_IMAP_PORT)
        conn.login(EXCHANGE_USER, EXCHANGE_PASS)

        sent_folder = _detect_sent_folder(conn)
        if not sent_folder:
            logger.warning("Exchange Sent poll: no Sent folder detected — skipping")
            return []
        status, _ = conn.select(f'"{sent_folder}"', readonly=True)
        if status != "OK":
            logger.warning(f"IMAP select '{sent_folder}' failed: {status}")
            return []

        status, msg_ids = conn.search(None, f'(SINCE {since_date})')
        if status != "OK" or not msg_ids[0]:
            logger.info(f"Exchange Sent poll: no new emails since {since_date}")
            return []

        id_list = msg_ids[0].split()
        if len(id_list) > MAX_FETCH:
            id_list = id_list[-MAX_FETCH:]

        logger.info(f"Exchange Sent poll: {len(id_list)} emails since {since_date}")

        latest_date = None

        for msg_id in id_list:
            try:
                status, data = conn.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                message_id = msg.get("Message-ID", f"exchange-sent-{msg_id.decode()}")
                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender_name, sender_email = _extract_sender(msg)
                to_header = _decode_header_value(msg.get("To", ""))
                body = _extract_body(msg)

                date_str = msg.get("Date", "")
                try:
                    received_dt = parsedate_to_datetime(date_str)
                    if received_dt.tzinfo is None:
                        received_dt = received_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    received_dt = datetime.now(timezone.utc)

                dedup_key = message_id.strip("<>")
                if state.is_processed(SOURCE_TYPE_SENT, dedup_key):
                    continue

                if latest_date is None or received_dt > latest_date:
                    latest_date = received_dt

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
                        "source": SOURCE_TYPE_SENT,
                        "thread_id": dedup_key,
                        "subject": subject,
                        "primary_sender": sender_name or sender_email,
                        "primary_sender_email": sender_email,
                        "received_date": received_dt.isoformat(),
                        "participants": participants,
                    }
                })

            except Exception as e:
                logger.warning(f"Exchange Sent: failed to parse msg {msg_id}: {e}")
                continue

        if latest_date:
            state.set_watermark(WATERMARK_KEY_SENT, latest_date)
            logger.info(
                f"Exchange Sent poll: {len(results)} new emails, "
                f"watermark -> {latest_date.isoformat()}"
            )

        try:
            from triggers.sentinel_health import report_success
            report_success("exchange_sent")
        except Exception:
            pass

    except imaplib.IMAP4.error as e:
        logger.error(f"Exchange Sent IMAP auth/connection error: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange_sent", str(e))
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Exchange Sent poll failed: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange_sent", str(e))
        except Exception:
            pass
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return results
