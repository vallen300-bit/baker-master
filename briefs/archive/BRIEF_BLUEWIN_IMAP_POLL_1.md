# BRIEF: BLUEWIN-IMAP-POLL-1 — Poll dvallen@bluewin.ch via IMAP for Baker

## Context
Director receives important emails (travel, banking, personal) at dvallen@bluewin.ch. Currently Baker only polls bakerai200@gmail.com (via Gmail API). Bluewin emails are invisible to Baker. Swisscom blocks POP3/IMAP from Google's servers, so Gmail fetch/Gmailify won't work. Solution: Baker polls Bluewin directly from Render via IMAP.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: Bluewin email password set (done — dimitry.vallen / urb1rva_myq@TQB2hvq)

---

## Feature 1: Bluewin IMAP Poller Module

### Problem
Baker has no visibility into dvallen@bluewin.ch emails. Travel confirmations, banking alerts, and personal correspondence are missed.

### Current State
- `scripts/extract_gmail.py` — Gmail API poller (REST, not IMAP)
- `triggers/email_trigger.py` — orchestrates polling + processing pipeline
- `triggers/scheduler.py` — APScheduler runs `check_new_emails()` every 300s
- `triggers/state.py` — PostgreSQL watermarks + dedup via `trigger_log`
- No IMAP code exists anywhere in the codebase

### Implementation

**Create:** `triggers/bluewin_poller.py`

```python
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
from typing import List, Dict, Optional

logger = logging.getLogger("bluewin_poller")

# ── Config ──────────────────────────────────────────────────────────────
BLUEWIN_IMAP_HOST = "imaps.bluewin.ch"
BLUEWIN_IMAP_PORT = 993
BLUEWIN_USER = os.getenv("BLUEWIN_USER", "dimitry.vallen")
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


def poll_bluewin() -> List[Dict]:
    """
    Connect to Bluewin IMAP, fetch emails since last watermark.
    Returns list of dicts matching Gmail poller format:
    {
        "text": "Email Thread: ...\nDate: ...\nParticipants: ...\n\n--- sender (date) ---\nsubject\n\nbody",
        "metadata": {
            "source": "bluewin",
            "thread_id": "<message-id>",
            "subject": "...",
            "primary_sender": "Name",
            "primary_sender_email": "email@domain",
            "received_date": "2026-04-07T12:00:00+00:00",
            "participants": "sender@domain, recipient@domain"
        }
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
            logger.info(f"Bluewin poll: {len(results)} new emails, watermark → {latest_date.isoformat()}")

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
```

### Key Constraints
- **Read-only** IMAP connection (`readonly=True`) — never modify Bluewin mailbox
- **Max 50 emails per poll** — safety limit
- **Same output format as Gmail poller** — `{text, metadata}` dicts feed into identical pipeline
- **Dedup via `trigger_log`** — uses Message-ID as source_id with type "bluewin"
- **Watermark via `trigger_watermarks`** — key "bluewin_poll"
- **Body capped at 10K chars** — prevents memory issues on large HTML emails
- **Non-fatal** — if BLUEWIN_PASS not set, silently skips

---

## Feature 2: Integrate into Email Trigger + Scheduler

### Problem
Bluewin emails need to flow through the same processing pipeline as Gmail emails (noise filter, classification, PM signal detection, storage).

### Current State
- `triggers/email_trigger.py` → `check_new_emails()` only calls Gmail poller
- `triggers/scheduler.py` registers only `check_new_emails` on 5-min interval

### Implementation

**File:** `triggers/email_trigger.py`

Add Bluewin polling at the END of `check_new_emails()`, after Gmail processing completes. Find the function (around line 610+) and add before the final return:

```python
    # ── BLUEWIN-IMAP-POLL-1: Poll Bluewin alongside Gmail ──
    try:
        from triggers.bluewin_poller import poll_bluewin
        bluewin_threads = poll_bluewin()
        if bluewin_threads:
            logger.info(f"Bluewin: {len(bluewin_threads)} new emails to process")
            _process_email_threads(bluewin_threads)
    except Exception as e:
        logger.warning(f"Bluewin poll failed (non-fatal): {e}")
```

**NOTE:** `_process_email_threads()` is the same function that processes Gmail threads. It handles:
- Noise filtering (sender patterns)
- Dedup marking (`trigger_state.mark_processed`)
- Storage to `email_messages` table
- Pipeline classification + extraction
- PM signal detection
- Meeting/deadline/obligation extraction

No changes needed to `scheduler.py` — Bluewin runs inside the existing `check_new_emails` job.

### Key Constraints
- **Same 5-min cycle** as Gmail — no separate scheduler job
- **Non-fatal wrapper** — Bluewin failure must never break Gmail polling
- **Process after Gmail** — Gmail is the primary channel, Bluewin is additive

---

## Feature 3: Environment Variable on Render

### Problem
Bluewin password must not be in code.

### Implementation

Add to Render environment variables (via MCP merge mode):
- `BLUEWIN_USER` = `dimitry.vallen`
- `BLUEWIN_PASS` = `urb1rva_myq@TQB2hvq`

**Verify:** After deploy, check Render logs for `Bluewin poll:` log lines.

### Key Constraints
- Use Render MCP merge mode — NEVER raw PUT
- Username is `dimitry.vallen` (Swisscom login), NOT `dvallen@bluewin.ch`

---

## Feature 4: Noise Filtering for Bluewin

### Problem
Bluewin inbox has 29,000+ unread emails — mostly newsletters, promotions, alerts. Without filtering, Baker would be overwhelmed on first poll.

### Current State
Gmail noise filtering is in `email_trigger.py` → `_process_email_threads()` which already checks `config.gmail.noise_senders` patterns.

### Implementation

The existing noise filter in `_process_email_threads()` already applies to ALL emails regardless of source. Bluewin emails will be filtered by the same 25+ patterns (noreply@, newsletters@, etc.).

**Additional safeguard:** The 3-day lookback on first run (in `poll_bluewin()`) limits initial flood to ~50 emails max.

No code changes needed — existing noise filter handles this.

---

## Files Modified
- `triggers/bluewin_poller.py` — **NEW** — IMAP poller for Bluewin
- `triggers/email_trigger.py` — Add ~8 lines to `check_new_emails()` to call Bluewin poller

## Do NOT Touch
- `scripts/extract_gmail.py` — Gmail API poller, unrelated
- `triggers/scheduler.py` — No separate job needed
- `triggers/state.py` — Already generic, works with any source type
- `config/settings.py` — No new config dataclass needed

## Quality Checkpoints
1. Syntax check both files: `python3 -c "import py_compile; py_compile.compile('triggers/bluewin_poller.py', doraise=True)"`
2. Render env vars set: `BLUEWIN_USER`, `BLUEWIN_PASS`
3. After deploy, check Render logs for: `Bluewin poll: N new emails`
4. Verify dedup: second poll should show 0 new emails
5. Verify watermark: `SELECT * FROM trigger_watermarks WHERE source = 'bluewin_poll'`
6. Verify storage: `SELECT COUNT(*) FROM email_messages WHERE thread_id LIKE 'bluewin%' LIMIT 1`
7. Verify no Gmail disruption: Gmail polling continues normally after Bluewin addition

## Verification SQL
```sql
-- Check Bluewin watermark exists
SELECT source, last_seen, updated_at FROM trigger_watermarks WHERE source = 'bluewin_poll';

-- Check Bluewin emails stored
SELECT subject, sender_email, received_date FROM email_messages
WHERE thread_id LIKE '%bluewin%' ORDER BY received_date DESC LIMIT 5;

-- Check dedup entries
SELECT type, source_id, created_at FROM trigger_log
WHERE type = 'bluewin' ORDER BY created_at DESC LIMIT 5;
```
