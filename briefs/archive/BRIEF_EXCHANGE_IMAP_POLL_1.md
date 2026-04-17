# BRIEF: EXCHANGE-IMAP-POLL-1 — Poll dvallen@brisengroup.com via IMAP (Temporary)

## Context
Baker has no visibility into the Brisengroup Exchange mailbox (`dvallen@brisengroup.com` on `exchange.evok.ch`). The Exchange→Gmail forwarding is broken — Gmail rejects forwarded emails from external senders (Minor Hotels, The Times, etc.) due to DMARC policy failures. Director missed a Minor Hotels meeting invite today because of this.

This is a **temporary measure** until the Microsoft 365 migration completes (offer expected this week from Florian Bourqui / evok). Once on M365, we'll switch to Graph API.

**IMAP access tested and confirmed working:**
- Server: `exchange.evok.ch:993` (SSL/TLS)
- Username: `dvallen@brisengroup.com`
- Password: stored in Render env var `EXCHANGE_PASS`
- 43 messages found since Apr 7 in test

## Estimated time: ~1h
## Complexity: Low (95% clone of Bluewin poller)
## Prerequisites: Render env vars `EXCHANGE_USER` and `EXCHANGE_PASS` set

---

## Feature 1: Exchange IMAP Poller Module

### Problem
Brisengroup emails from external contacts (Minor Hotels, clients, legal counsel) never reach Baker. The Exchange→Gmail forwarding fails DMARC for any non-brisengroup.com sender. Calendar invites (.ics) don't forward at all.

### Current State
- `triggers/bluewin_poller.py` — Working IMAP poller for Bluewin (our template)
- `triggers/email_trigger.py` line 741-749 — Bluewin integration pattern (our template)
- `triggers/state.py` — Generic TriggerState with `get_watermark()`, `set_watermark()`, `is_processed()`
- No Exchange/evok code exists anywhere in the codebase

### Implementation

**Create:** `triggers/exchange_poller.py`

Clone `triggers/bluewin_poller.py` with these changes only:

```python
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

    except imaplib.IMAP4.error as e:
        logger.error(f"Exchange IMAP auth/connection error: {e}")
    except Exception as e:
        logger.error(f"Exchange poll failed: {e}")
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return results
```

### Key Constraints
- **Read-only** IMAP connection (`readonly=True`) — never modify Exchange mailbox
- **Max 50 emails per poll** — safety limit (inbox has 39K+ unread)
- **Same output format as Gmail/Bluewin pollers** — `{text, metadata}` dicts
- **Dedup via `trigger_log`** — uses Message-ID as source_id with type "exchange"
- **Watermark via `trigger_watermarks`** — key "exchange_poll"
- **Body capped at 10K chars** — prevents memory issues on large HTML emails
- **Non-fatal** — if `EXCHANGE_PASS` not set, silently skips
- **Temporary** — will be replaced by M365 Graph API after migration

---

## Feature 2: Integrate into Email Trigger

### Problem
Exchange emails need to flow through the same processing pipeline as Gmail and Bluewin emails.

### Current State
- `triggers/email_trigger.py` line 741-749 — Bluewin integration (our exact template)

### Implementation

**File:** `triggers/email_trigger.py`

Add after the Bluewin block (after line 749), before the final return:

```python
    # ── EXCHANGE-IMAP-POLL-1: Poll Exchange alongside Gmail + Bluewin ──
    try:
        from triggers.exchange_poller import poll_exchange
        exchange_threads = poll_exchange()
        if exchange_threads:
            logger.info(f"Exchange: {len(exchange_threads)} new emails to process")
            _process_email_threads(exchange_threads)
    except Exception as e:
        logger.warning(f"Exchange poll failed (non-fatal): {e}")
```

### Key Constraints
- **Same 5-min cycle** as Gmail and Bluewin — no separate scheduler job
- **Non-fatal wrapper** — Exchange failure must never break Gmail or Bluewin polling
- **Process after Bluewin** — Gmail is primary, Bluewin second, Exchange third
- **No changes to `embedded_scheduler.py`** — runs inside existing `check_new_emails` job

---

## Feature 3: Environment Variables on Render

### Problem
Exchange credentials must not be in code.

### Implementation

Set on Render baker-master service via MCP merge mode:
- `EXCHANGE_USER` = `dvallen@brisengroup.com`
- `EXCHANGE_PASS` = (the Exchange/OWA password — set by Director or AI Head via Render MCP)

### Key Constraints
- Use Render MCP merge mode — NEVER raw PUT
- Username is `dvallen@brisengroup.com` (full email), NOT `dvallen@evokmail.ch`
- **NEVER put the password in this brief or in code** — Render env vars only

---

## Feature 4: Sentinel Health Reporting

### Problem
Exchange poller must report to sentinel_health like all other pollers.

### Implementation

Already handled in the integration block (Feature 2). The `_process_email_threads()` function runs the full pipeline. But we should also add explicit health reporting for the Exchange connection itself.

**In `triggers/exchange_poller.py`**, add at the end of `poll_exchange()`, before the final `return results`:

After the watermark update (after `logger.info(f"Exchange poll: {len(results)} new emails..."`):
```python
        # EXCHANGE-IMAP-POLL-1: Report health
        try:
            from triggers.sentinel_health import report_success
            report_success("exchange")
        except Exception:
            pass
```

In the `except imaplib.IMAP4.error` block:
```python
    except imaplib.IMAP4.error as e:
        logger.error(f"Exchange IMAP auth/connection error: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange", str(e))
        except Exception:
            pass
```

In the general `except Exception` block:
```python
    except Exception as e:
        logger.error(f"Exchange poll failed: {e}")
        try:
            from triggers.sentinel_health import report_failure
            report_failure("exchange", str(e))
        except Exception:
            pass
```

**In `triggers/sentinel_health.py`**, add to `_WATERMARK_MAX_AGE` dict:
```python
    "exchange_poll": 2,      # EXCHANGE-IMAP-POLL-1: polls every 5 min, 2h max tolerable
```

---

## Files Modified
- `triggers/exchange_poller.py` — **NEW** — IMAP poller for Exchange/evok.ch
- `triggers/email_trigger.py` — Add ~8 lines to `check_new_emails()` to call Exchange poller
- `triggers/sentinel_health.py` — Add `"exchange_poll": 2` to `_WATERMARK_MAX_AGE`

## Do NOT Touch
- `triggers/bluewin_poller.py` — Bluewin poller, template only
- `scripts/extract_gmail.py` — Gmail API poller, unrelated
- `triggers/scheduler.py` / `triggers/embedded_scheduler.py` — No separate job needed
- `triggers/state.py` — Already generic, works with any source type
- `config/settings.py` — No new config dataclass needed

## Quality Checkpoints
1. Syntax check: `python3 -c "import py_compile; py_compile.compile('triggers/exchange_poller.py', doraise=True)"`
2. Syntax check: `python3 -c "import py_compile; py_compile.compile('triggers/email_trigger.py', doraise=True)"`
3. Render env vars set: `EXCHANGE_USER`, `EXCHANGE_PASS`
4. After deploy, check Render logs for: `Exchange poll: N new emails`
5. Verify dedup: second poll should show 0 new emails (all already processed)
6. Verify watermark: `SELECT * FROM trigger_watermarks WHERE source = 'exchange_poll' LIMIT 1`
7. Verify sentinel health: `SELECT * FROM sentinel_health WHERE source = 'exchange' LIMIT 1`
8. Verify no Gmail/Bluewin disruption: both continue polling normally
9. Verify noise filtering: newsletters and spam from Exchange get filtered by existing `_process_email_threads()` noise patterns

## Verification SQL
```sql
-- Check Exchange watermark exists
SELECT source, last_seen, updated_at FROM trigger_watermarks WHERE source = 'exchange_poll' LIMIT 1;

-- Check Exchange emails stored
SELECT subject, sender_email, received_date FROM email_messages
WHERE thread_id LIKE '%exchange%' ORDER BY received_date DESC LIMIT 5;

-- Check dedup entries
SELECT type, source_id, created_at FROM trigger_log
WHERE type = 'exchange' ORDER BY created_at DESC LIMIT 5;

-- Check sentinel health
SELECT source, status, consecutive_failures, last_success_at FROM sentinel_health
WHERE source = 'exchange' LIMIT 1;
```

## Deprecation Note
This poller is **temporary**. When Brisengroup migrates to Microsoft 365:
1. Replace IMAP polling with Microsoft Graph API
2. Remove `EXCHANGE_USER` / `EXCHANGE_PASS` env vars from Render
3. Delete `triggers/exchange_poller.py`
4. Remove Exchange block from `triggers/email_trigger.py`
5. Remove `"exchange_poll"` from `_WATERMARK_MAX_AGE` in `triggers/sentinel_health.py`
