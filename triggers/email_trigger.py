"""
Sentinel Trigger — Email (Gmail)
Polls Gmail for new threads and fires pipeline for substantive ones.
Called by scheduler every 5 minutes.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.email")

# ALERT-DEDUP-1: Track last gap alert to avoid firing every 5 min
_last_gap_alert_time: float = 0.0
_GAP_ALERT_COOLDOWN = 24 * 3600  # 24 hours between gap alerts

# Gmail 429 backoff: skip polls until this timestamp (epoch seconds)
_gmail_retry_after: float = 0.0
_gmail_backoff_seconds: float = 0.0  # exponential backoff tracker

# Sentinel health monitoring
from triggers.sentinel_health import report_success as _health_success, report_failure as _health_failure

# COST-OPT-WAVE2: Automated sender blocklist — skip pipeline.run() entirely.
# These emails still get stored to PostgreSQL (email_messages) for search,
# but don't trigger an Opus/Sonnet pipeline call. Saves ~EUR 50-80/mo.
_SKIP_PIPELINE_SENDERS = {
    "noreply@", "no-reply@", "no_reply@", "donotreply@",
    "notifications@", "notification@", "mailer-daemon@",
    "calendar-notification@google.com",
    "fred@fireflies.ai",
    "notify@fireflies.ai",
    "@crowdcomms.com",
    "@eventbooking.uk.com",
    "@todoist.com",
    "@clickup.com",
    "@github.com",
    "@render.com",
    "@noreply.github.com",
    "@slack.com",
    "@dropbox.com",
    "news@", "newsletter@", "digest@", "updates@", "info@",
}

# Headers/content that indicate automated email (skip pipeline)
_SKIP_PIPELINE_HEADERS = {
    "unsubscribe", "list-unsubscribe", "precedence: bulk",
    "auto-submitted:", "x-auto-response-suppress:",
}


def _should_skip_pipeline(sender_email: str, body: str) -> bool:
    """COST-OPT-WAVE2: Check if an email is automated junk that shouldn't hit the pipeline.
    VIP financial senders (Amex, UBS, etc.) are never skipped."""
    if not sender_email:
        return False
    sender_lower = sender_email.lower()
    # VIP financial senders bypass all skip logic
    from scripts.extract_gmail import _is_vip_sender
    if _is_vip_sender(sender_lower):
        return False
    for pattern in _SKIP_PIPELINE_SENDERS:
        if pattern in sender_lower:
            return True
    # Check first 500 chars for unsubscribe/bulk headers in body
    body_lower = body[:500].lower() if body else ""
    for header in _SKIP_PIPELINE_HEADERS:
        if header in body_lower:
            return True
    return False


# MEETINGS-DETECT-2: Fast regex pre-filter for meeting emails (zero API cost)
import re as _re
_MEETING_EMAIL_RE = _re.compile(
    r'(?:meeting|call|zoom|teams|lunch|dinner|coffee|breakfast|'
    r'catch-up|sync|sit-down|appointment|conference|'
    r"let'?s meet|see you at|confirmed for|invitation to|"
    r'calendar invite|join us|rsvp|webex|google meet|'
    r'looking forward to meeting|propose a meeting|'
    r'schedule a call|book a time|set up a meeting|'
    r'meeting request|accept this invitation)',
    _re.IGNORECASE
)


def _is_meeting_email(subject: str, body: str) -> bool:
    """MEETINGS-DETECT-2: Fast regex check — no API cost."""
    text = f"{subject} {body[:1000]}"
    return bool(_MEETING_EMAIL_RE.search(text))


def _extract_meeting_from_email(subject: str, body: str, sender_name: str,
                                 sender_email: str, received_date: str):
    """MEETINGS-DETECT-2: One Flash call to extract meeting details from email.
    Returns dict with meeting data or None."""
    import json
    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now().strftime('%Y-%m-%d')
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Extract meeting details from this email. If this is NOT about a specific scheduled meeting, return {{"is_meeting": false}}.

From: {sender_name} <{sender_email}>
Date: {received_date}
Subject: {subject}

Body:
{body[:2000]}

Today's date is {today}.

Return JSON only (no markdown):
{{
  "is_meeting": true,
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD or null if no specific date mentioned",
  "time": "HH:MM or descriptive like 'afternoon' or null",
  "location": "place or 'Zoom/Teams' or null",
  "status": "confirmed or proposed"
}}

Status: "confirmed" if definite language. "proposed" if asking/suggesting."""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_email_detect")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"MEETINGS-DETECT-2: Haiku extraction failed: {e}")
        return None


# OBLIGATIONS-DETECT-1: Regex pre-filter for Director's personal commitments
_COMMITMENT_RE = _re.compile(
    r"(?:I'?ll |I will |let me |I need to |I should |"
    r"I promised |I committed |will do |"
    r"I'?ll send |I'?ll call |I'?ll check |I'?ll follow.?up |"
    r"I'?ll get back |I'?ll revert |I'?ll arrange |I'?ll prepare |"
    r"I'?ll review |I'?ll confirm |I'?ll forward |I'?ll share |"
    r"I'?ll set up |I'?ll organize |I'?ll look into |"
    r"remind me to |don'?t let me forget |"
    r"my action |action on me |I take that)",
    _re.IGNORECASE
)


def _extract_commitment_from_email(subject: str, body: str, recipient: str, received_date: str):
    """OBLIGATIONS-DETECT-1: One Flash call to extract Director's commitment from outbound email."""
    import json
    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now().strftime('%Y-%m-%d')
        resp = call_flash(
            messages=[{"role": "user", "content": f"""Extract the Director's personal commitment from this outbound email. If no personal commitment was made, return {{"is_commitment": false}}.

From: Dimitry Vallen <dvallen@brisengroup.com>
To: {recipient}
Subject: {subject}
Date: {received_date}

Body:
{body[:2000]}

Today's date is {today}.

Return JSON only (no markdown):
{{
  "is_commitment": true,
  "description": "short description of what was promised",
  "to_whom": "recipient name",
  "due_date": "YYYY-MM-DD or null",
  "due_hint": "by Friday / ASAP / null",
  "urgency": "high" | "normal" | "low"
}}

Rules:
- Only extract commitments the Director made personally ("I will", "I'll", "let me")
- NOT tasks assigned to others ("Please send", "Could you check")
- NOT facts ("The deadline is Friday")
- If multiple commitments, return the most important one
- Infer due_date: "by Friday" = next Friday, "tomorrow" = tomorrow"""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="commitment_email_detect")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"OBLIGATIONS-DETECT-1: Haiku extraction failed: {e}")
        return None


def _get_gmail_service():
    """Authenticate and return Gmail API service object."""
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build
    creds = authenticate()
    return build("gmail", "v1", credentials=creds)


# -------------------------------------------------------
# BAKER-LABEL-1: "Baker" Gmail label — Director flags emails for deep analysis
# -------------------------------------------------------

_BAKER_LABEL_NAME = "Baker"
_baker_label_id: str = ""  # cached after first lookup


def _get_baker_label_id(service) -> str:
    """Find or create the 'Baker' label in Gmail. Cached after first call."""
    global _baker_label_id
    if _baker_label_id:
        return _baker_label_id

    try:
        results = service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label["name"] == _BAKER_LABEL_NAME:
                _baker_label_id = label["id"]
                logger.info(f"BAKER-LABEL-1: found label '{_BAKER_LABEL_NAME}' (id={_baker_label_id})")
                return _baker_label_id

        # Label doesn't exist — create it
        body = {
            "name": _BAKER_LABEL_NAME,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = service.users().labels().create(userId="me", body=body).execute()
        _baker_label_id = created["id"]
        logger.info(f"BAKER-LABEL-1: created label '{_BAKER_LABEL_NAME}' (id={_baker_label_id})")
        return _baker_label_id
    except Exception as e:
        logger.warning(f"BAKER-LABEL-1: failed to get/create label: {e}")
        return ""


def _poll_baker_labeled_emails(service) -> list:
    """Poll Gmail for threads with the 'Baker' label. Returns thread IDs."""
    label_id = _get_baker_label_id(service)
    if not label_id:
        return []

    try:
        results = service.users().threads().list(
            userId="me", labelIds=[label_id], maxResults=10
        ).execute()
        threads = results.get("threads", [])
        if threads:
            logger.info(f"BAKER-LABEL-1: found {len(threads)} Baker-labeled threads")
        return threads
    except Exception as e:
        logger.warning(f"BAKER-LABEL-1: label poll failed: {e}")
        return []


def _remove_baker_label(service, thread_id: str):
    """Remove the 'Baker' label from a thread after processing."""
    label_id = _get_baker_label_id(service)
    if not label_id:
        return

    try:
        # Get all message IDs in the thread
        thread = service.users().threads().get(userId="me", id=thread_id, format="minimal").execute()
        for msg in thread.get("messages", []):
            service.users().messages().modify(
                userId="me", id=msg["id"],
                body={"removeLabelIds": [label_id]}
            ).execute()
        logger.info(f"BAKER-LABEL-1: removed label from thread {thread_id}")
    except Exception as e:
        logger.warning(f"BAKER-LABEL-1: failed to remove label from {thread_id}: {e}")


def _process_baker_labeled_threads(service):
    """
    BAKER-LABEL-1: Process emails the Director flagged with 'Baker' label.
    Runs deep analysis via Scan pipeline and pushes result to WhatsApp + dashboard.
    """
    labeled = _poll_baker_labeled_emails(service)
    if not labeled:
        return

    from scripts import extract_gmail
    from memory.store_back import SentinelStoreBack

    extract_gmail._gmail_service = service
    store = SentinelStoreBack._get_global_instance()

    for item in labeled:
        thread_id = item["id"]

        # Skip if already processed this label application
        dedup_key = f"baker-label-{thread_id}"
        existing_wm = trigger_state.get_watermark(dedup_key)
        if existing_wm and existing_wm.year > 2001:
            # Already processed — still try to remove the label
            _remove_baker_label(service, thread_id)
            continue

        try:
            # Fetch full thread
            thread_detail = extract_gmail.fetch_thread_detail(service, thread_id)
            if not thread_detail:
                _remove_baker_label(service, thread_id)
                continue

            messages = thread_detail.get("messages", [])
            if len(messages) > config.gmail.max_messages_per_thread:
                messages = messages[-config.gmail.max_messages_per_thread:]

            formatted = extract_gmail.format_thread(thread_detail, messages)
            if not formatted:
                _remove_baker_label(service, thread_id)
                continue

            metadata = formatted.get("metadata", {})
            subject = metadata.get("subject", "(no subject)")
            sender = metadata.get("primary_sender", "unknown")
            email_text = formatted["text"]

            logger.info(f"BAKER-LABEL-1: deep analyzing '{subject}' from {sender}")

            # Store email if not already stored
            try:
                store.store_email_message(
                    message_id=thread_id,
                    thread_id=thread_id,
                    sender_name=sender,
                    sender_email=metadata.get("primary_sender_email"),
                    subject=subject,
                    full_body=email_text,
                    received_date=metadata.get("received_date"),
                    priority="high",
                )
            except Exception:
                pass

            # Run deep analysis via Gemini Pro
            from orchestrator.gemini_client import call_pro

            analysis_prompt = f"""The Director has flagged this email for your deep analysis. Analyze it thoroughly and provide:

1. **Summary** — What is this about? Key facts.
2. **Who** — People involved, their roles, any VIP connections.
3. **Action required** — What does the Director need to do, if anything?
4. **Deadlines** — Any dates or time-sensitive elements.
5. **Risks & Opportunities** — What should the Director be aware of?
6. **Recommended response** — If a reply is needed, suggest the approach.
7. **Connected matters** — Link to any known Baker matters or ongoing issues.

---

**From:** {sender} ({metadata.get('primary_sender_email', '')})
**Subject:** {subject}
**Date:** {metadata.get('received_date', '')}

**Full email:**
{email_text[:8000]}"""

            resp = call_pro(
                messages=[{"role": "user", "content": analysis_prompt}],
                max_tokens=2000,
            )

            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="baker_label_analysis")
            except Exception:
                pass

            analysis = resp.text

            # Create alert on dashboard
            store.create_alert(
                tier=1,
                title=f"Email Analysis: {subject[:80]}",
                body=f"**From:** {sender}\n**Subject:** {subject}\n\n{analysis}",
                action_required=True,
                tags=["baker-label", "email-analysis"],
                source="baker_label",
                source_id=dedup_key,
            )

            # Push to WhatsApp
            try:
                from outputs.whatsapp_sender import send_whatsapp
                wa_text = (
                    f"📧 *Email Analysis* (you flagged this)\n\n"
                    f"*From:* {sender}\n"
                    f"*Subject:* {subject}\n\n"
                    f"{analysis[:3000]}"
                )
                send_whatsapp(wa_text)
            except Exception as _we:
                logger.warning(f"BAKER-LABEL-1: WhatsApp push failed: {_we}")

            # Mark as processed via watermark (trigger_log has no direct insert)
            trigger_state.set_watermark(dedup_key, datetime.now(timezone.utc))
            logger.info(f"BAKER-LABEL-1: analysis complete for '{subject[:60]}'")

        except Exception as e:
            logger.error(f"BAKER-LABEL-1: failed to process thread {thread_id}: {e}")
        finally:
            # Try to remove the label (requires gmail.modify scope — may fail gracefully)
            _remove_baker_label(service, thread_id)


def poll_gmail() -> list:
    """
    Poll Gmail for new threads since last watermark.
    Returns list of {text, metadata} dicts.
    Reuses extract_gmail.py's poll logic.
    """
    from scripts import extract_gmail
    service = _get_gmail_service()
    # ARCH-6: Set Gmail service so format_thread() can extract attachments
    extract_gmail._gmail_service = service
    return extract_gmail.extract_poll(service)


# -------------------------------------------------------
# Phase 3C: Commitment extraction from emails
# -------------------------------------------------------

_EMAIL_COMMITMENT_PROMPT = """You are Baker. Extract commitments from this email.

Look for:
- Promises made BY the sender: "I'll send...", "We'll provide...", "Attached is..."
- Requests TO the Director: "Please review...", "Could you approve...", "We need your..."
- Deadlines mentioned: "by Friday", "before end of month", "within 5 business days"

Return ONLY valid JSON:
{"commitments": [
    {"description": "...", "assigned_to": "sender_name or director", "due_date": "YYYY-MM-DD or null", "urgency": "high|medium|low"}
]}

If no clear commitments found, return {"commitments": []}
"""


def _extract_commitments_from_email(email_text: str, subject: str,
                                     sender: str, source_id: str):
    """Extract commitments from an email using Flash. Fault-tolerant."""
    import json
    from memory.store_back import SentinelStoreBack

    if not email_text or len(email_text.strip()) < 30:
        return

    try:
        from orchestrator.gemini_client import call_flash
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Today: {today}\nSubject: {subject}\nFrom: {sender}\n\n{email_text[:4000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="email_commitments")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        parsed = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Commitment extraction failed for email {source_id}: {e}")
        return

    commitments = parsed.get("commitments", [])
    if not commitments:
        return

    store = SentinelStoreBack._get_global_instance()
    inserted = 0
    for c in commitments:
        desc = (c.get("description") or "").strip()
        if not desc:
            continue
        due_date = c.get("due_date")
        if due_date == "null" or not due_date:
            due_date = None

        matter_slug = None
        try:
            from orchestrator.pipeline import _match_matter_slug
            matter_slug = _match_matter_slug(desc, subject, store)
        except Exception:
            pass

        cid = store.store_commitment(
            description=desc,
            assigned_to=c.get("assigned_to", sender or ""),
            due_date=due_date,
            source_type="email",
            source_id=source_id,
            source_context=f"Email: {subject}",
            matter_slug=matter_slug,
        )
        if cid:
            inserted += 1

    if inserted:
        logger.info(f"Extracted {inserted} commitments from email '{subject[:60]}'")


# -------------------------------------------------------
# Phase 3C: Email intelligence signal detection
# -------------------------------------------------------

_EMAIL_INTELLIGENCE_PROMPT = """You are Baker. Check if this email contains a signal the Director should know about proactively.

Signals: competitor moves, regulatory changes, market shifts, opportunity alerts, risk indicators, deadline changes, relationship changes (new contact, role change, departure).

Return ONLY valid JSON:
{
    "signal_detected": true/false,
    "signal_type": "competitor|regulatory|market|opportunity|risk|deadline|relationship",
    "summary": "One sentence",
    "urgency": "high|medium|low",
    "related_matter": "matter_slug or null"
}

If no clear signal, set signal_detected: false.
"""


def _check_email_intelligence(email_text: str, subject: str, sender: str, source_id: str = None):
    """Check high-priority email for intelligence signals. Creates alert if found."""
    import json
    from memory.store_back import SentinelStoreBack

    if not email_text or len(email_text.strip()) < 30:
        return

    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Subject: {subject}\nFrom: {sender}\n\n{email_text[:3000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="email_intelligence")
        except Exception:
            pass
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        result = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Email intelligence check parse error: {e}")
        return

    if not result.get("signal_detected"):
        return

    signal_type = result.get("signal_type", "")
    urgency = result.get("urgency", "low")
    summary = result.get("summary", "")
    matter = result.get("related_matter")
    if matter == "null":
        matter = None

    if urgency in ("high", "medium"):
        tier = 2 if urgency == "high" else 3
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=tier,
            title=f"Intelligence: {summary[:80]}",
            body=f"**Signal:** {signal_type}\n**From:** {sender}\n**Subject:** {subject}\n\n{summary}",
            action_required=(urgency == "high"),
            matter_slug=matter,
            tags=["intelligence", signal_type] if signal_type else ["intelligence"],
            source="email_intelligence",
            source_id=f"email-intel-{source_id}" if source_id else None,
        )
        logger.info(f"Email intelligence alert: {signal_type} — {summary[:60]}")


def check_new_emails():
    """
    Main entry point — called by scheduler every 5 minutes.
    1. Polls Gmail for new threads
    2. Classifies each by priority
    3. Runs pipeline immediately for high/medium priority
    4. Queues low-priority for daily briefing
    """
    from triggers.sentinel_health import should_skip_poll

    if should_skip_poll("email"):
        return

    # ── BLUEWIN-IMAP-POLL-1: Poll Bluewin independently of Gmail ──
    try:
        from triggers.bluewin_poller import poll_bluewin
        bluewin_threads = poll_bluewin()
        if bluewin_threads:
            logger.info(f"Bluewin: {len(bluewin_threads)} new emails to process")
            _process_email_threads(bluewin_threads)
    except Exception as e:
        logger.warning(f"Bluewin poll failed (non-fatal): {e}")

    # ── EXCHANGE-IMAP-POLL-1: Poll Exchange independently of Gmail ──
    try:
        from triggers.exchange_poller import poll_exchange
        exchange_threads = poll_exchange()
        if exchange_threads:
            logger.info(f"Exchange: {len(exchange_threads)} new emails to process")
            _process_email_threads(exchange_threads)
    except Exception as e:
        logger.warning(f"Exchange poll failed (non-fatal): {e}")

    import time as _time
    global _gmail_retry_after, _gmail_backoff_seconds

    # Load persisted backoff state (survives deploys)
    now_ts = _time.time()
    if _gmail_retry_after == 0.0:
        persisted = trigger_state.get_watermark("email_429_backoff")
        if persisted:
            _gmail_retry_after = persisted.timestamp()

    # Skip poll if we're in a 429 backoff window
    if now_ts < _gmail_retry_after:
        remaining = int(_gmail_retry_after - now_ts)
        logger.info(f"Email trigger: skipping poll — Gmail 429 backoff ({remaining}s remaining)")
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        return

    logger.info("Email trigger: checking for new threads...")

    # BAKER-LABEL-1: Check for Director-flagged emails first (separate from regular poll)
    try:
        _bl_service = _get_gmail_service()
        _process_baker_labeled_threads(_bl_service)
    except Exception as _ble:
        logger.warning(f"BAKER-LABEL-1: label check failed (non-fatal): {_ble}")

    try:
        new_threads = poll_gmail()
    except Exception as e:
        error_str = str(e)
        _health_failure("email", error_str)
        logger.error(f"Email trigger: Gmail poll failed: {e}")

        # Parse 429 Retry-After and set backoff
        if "429" in error_str or "rateLimitExceeded" in error_str:
            # Try to parse "Retry after YYYY-MM-DDTHH:MM:SS" from error
            import re
            retry_match = re.search(r'Retry after (\d{4}-\d{2}-\d{2}T[\d:.]+Z?)', error_str)
            if retry_match:
                try:
                    retry_dt = datetime.fromisoformat(retry_match.group(1).replace("Z", "+00:00"))
                    _gmail_retry_after = retry_dt.timestamp() + 60  # add 60s buffer
                    _gmail_backoff_seconds = 0  # reset exponential — we have a real timestamp
                    # Persist to DB so backoff survives deploys
                    backoff_until = datetime.fromtimestamp(_gmail_retry_after, tz=timezone.utc)
                    trigger_state.set_watermark("email_429_backoff", backoff_until)
                    logger.info(f"Email trigger: 429 retry-after parsed → backoff until {retry_dt.isoformat()} + 60s")
                except (ValueError, TypeError):
                    pass

            if _gmail_retry_after <= now_ts:
                # No parsed timestamp — use exponential backoff
                if _gmail_backoff_seconds == 0:
                    _gmail_backoff_seconds = 600  # start at 10 min
                else:
                    _gmail_backoff_seconds = min(_gmail_backoff_seconds * 2, 3600)  # max 1 hour
                _gmail_retry_after = now_ts + _gmail_backoff_seconds
                backoff_until = datetime.fromtimestamp(_gmail_retry_after, tz=timezone.utc)
                trigger_state.set_watermark("email_429_backoff", backoff_until)
                logger.info(f"Email trigger: 429 exponential backoff → {int(_gmail_backoff_seconds)}s")

        # Still update checked watermark so we can distinguish "poll crashed"
        # from "poll never ran" in /api/status
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        return

    # Poll succeeded — reset 429 backoff state
    _gmail_retry_after = 0.0
    _gmail_backoff_seconds = 0.0
    # Clear persisted backoff
    try:
        trigger_state.set_watermark("email_429_backoff", datetime(2000, 1, 1, tzinfo=timezone.utc))
    except Exception:
        pass

    if not new_threads:
        logger.info("Email trigger: no new threads")
        # PHASE-4A: Advance watermark even when no emails found — prevents
        # false "gap alert" when inbox is quiet (cosmetic but confusing).
        # Separate "last_checked" (now) from "last_email_seen" (watermark).
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        # Gap detection: alert if no SUBSTANTIVE email for 48+ hours
        # Uses the real watermark (last email seen), not last_checked
        global _last_gap_alert_time
        import time as _time
        now_ts = _time.time()
        wm = trigger_state.get_watermark("email_poll")
        if wm:
            gap_hours = (datetime.now(timezone.utc) - wm).total_seconds() / 3600
            if gap_hours > 48 and (now_ts - _last_gap_alert_time) > _GAP_ALERT_COOLDOWN:
                gap_title = f"Email gap alert: {gap_hours:.0f}h since last email"
                gap_body = (
                    f"Last email seen: {wm.isoformat()} ({gap_hours:.0f}h ago).\n"
                    f"Last successful poll: just now (no new emails).\n"
                    f"This may be normal if inbox is quiet."
                )
                logger.warning(gap_title)
                try:
                    from memory.store_back import SentinelStoreBack
                    store = SentinelStoreBack._get_global_instance()
                    store.create_alert(tier=2, title=gap_title, body=gap_body, source="email_gap")
                    _last_gap_alert_time = now_ts
                except Exception as e:
                    logger.error(f"Gap alert dispatch failed: {e}")
        _health_success("email")
        return

    logger.info(f"Email trigger: {len(new_threads)} new threads found")

    try:
        _process_email_threads(new_threads)
    except Exception as e:
        logger.error(f"Email trigger: thread processing crashed: {e}")
    finally:
        # ALWAYS update checked watermark and report success (poll itself worked)
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        _health_success("email")

    logger.info("Email trigger: poll cycle complete")


def _process_email_threads(new_threads: list):
    """Process email threads — extracted so outer function always updates health."""
    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    batch_for_briefing = []
    processed = 0
    skipped = 0
    latest_seen_dt = None  # F4: track max received_date across ALL seen threads
    _seen_threads_this_cycle: set = set()  # ALERT-DEDUP-1: prevent within-cycle duplicates

    for thread in new_threads:
        metadata = thread.get("metadata", {})
        thread_id = metadata.get("thread_id", "unknown")

        # ALERT-DEDUP-1: Skip if we already processed this thread in this poll cycle
        # (extract_poll can return the same thread twice via Gmail pagination)
        if thread_id in _seen_threads_this_cycle:
            skipped += 1
            continue
        _seen_threads_this_cycle.add(thread_id)

        # REPLY-TRACK-1: Check if this incoming email is a reply to a Baker-sent email
        try:
            _check_reply_match(
                thread_id=thread_id,
                sender=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
                subject=metadata.get("subject", ""),
                body_preview=thread.get("text", "")[:300],
            )
        except Exception as _e:
            logger.debug(f"Reply check failed for thread {thread_id}: {_e}")

        # F4: Track received_date of every seen thread (processed + skipped)
        received_date_str = metadata.get("received_date", "")
        if received_date_str and received_date_str != "unknown":
            try:
                rd = datetime.fromisoformat(received_date_str)
                if rd.tzinfo is None:
                    rd = rd.replace(tzinfo=timezone.utc)
                if latest_seen_dt is None or rd > latest_seen_dt:
                    latest_seen_dt = rd
            except (ValueError, TypeError):
                pass

        # F1: Dedup on thread_id against trigger_log — skip if this thread was already processed
        # ALERT-DEDUP-1 fix: use thread_id for dedup (not individual message_ids which only
        # partially match trigger_log entries, causing repeat processing every cycle)
        if trigger_state.is_processed("email", thread_id):
            skipped += 1
            continue

        # COST-OPT-WAVE1: Pre-mark as processed BEFORE pipeline.run() to prevent
        # race condition where next poll cycle re-processes the same thread.
        # Safe: email is also stored in email_messages (line below) so nothing is lost
        # even if pipeline.run() fails. The store_back inside pipeline.run() will
        # attempt its own INSERT which harmlessly conflicts (ON CONFLICT DO NOTHING).
        trigger_state.mark_processed("email", thread_id)

        # Use thread_id as pipeline source_id (stable across poll cycles)
        message_id = thread_id

        # ARCH-6: Store full email to PostgreSQL
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.store_email_message(
                message_id=message_id,
                thread_id=thread_id,
                sender_name=metadata.get("primary_sender"),
                sender_email=metadata.get("primary_sender_email"),
                subject=metadata.get("subject"),
                full_body=thread["text"],
                received_date=metadata.get("received_date"),
                priority=None,  # set after classification
            )
        except Exception as _e:
            logger.warning(f"Failed to store email {message_id} to PostgreSQL (non-fatal): {_e}")

        # INTERACTION-PIPELINE-1: Record contact interaction from email
        try:
            from memory.store_back import SentinelStoreBack
            _store_ip = SentinelStoreBack._get_global_instance()
            _sender_email = metadata.get("primary_sender_email", "")
            _direction = "outbound" if _sender_email and "@brisengroup.com" in _sender_email.lower() else "inbound"
            _cid = _store_ip.match_contact_by_name(
                name=metadata.get("primary_sender", ""),
                email=_sender_email,
            )
            if _cid:
                _store_ip.record_interaction(
                    contact_id=_cid, channel="email", direction=_direction,
                    timestamp=metadata.get("received_date"),
                    subject=metadata.get("subject", "")[:200],
                    source_ref=f"email:{message_id}",
                )
        except Exception:
            pass  # Non-fatal — pipeline continues

        # PM-SIGNAL: Detect PM-relevant emails (generic, PM_REGISTRY-driven)
        try:
            from orchestrator.pm_signal_detector import detect_relevant_pms_text, flag_pm_signal
            _pm_sender = metadata.get("primary_sender", "") + " " + metadata.get("primary_sender_email", "")
            _pm_text = f"{metadata.get('subject', '')} {thread['text'][:500]}"
            for _pm_slug in detect_relevant_pms_text(_pm_sender, _pm_text):
                flag_pm_signal(_pm_slug, "email", metadata.get("primary_sender", "unknown"), metadata.get("subject", "")[:200])
        except Exception:
            pass  # Non-fatal

        # TRIP-INTELLIGENCE-1: Auto-link to active trip if content mentions destination
        try:
            from memory.store_back import SentinelStoreBack
            _store_tc = SentinelStoreBack._get_global_instance()
            _store_tc.link_to_trip_context(
                content=metadata.get("subject", "") + " " + thread["text"][:500],
                source_type="email", source_ref=f"email:{message_id}",
                timestamp=metadata.get("received_date"),
            )
        except Exception:
            pass

        # OBLIGATIONS-DETECT-1: Check outbound emails for Director's personal commitments
        try:
            _ob_sender_email = metadata.get("primary_sender_email", "")
            _ob_is_outbound = _ob_sender_email and "@brisengroup.com" in _ob_sender_email.lower()
            if _ob_is_outbound and _COMMITMENT_RE.search(thread["text"]):
                _ob_data = _extract_commitment_from_email(
                    metadata.get("subject", ""), thread["text"],
                    metadata.get("to", metadata.get("primary_sender", "")),
                    metadata.get("received_date", ""),
                )
                if _ob_data and _ob_data.get("is_commitment"):
                    from models.deadlines import insert_deadline
                    _ob_to = _ob_data.get("to_whom", "")
                    _ob_desc = _ob_data.get("description", "")
                    _ob_due = _ob_data.get("due_date")
                    if not _ob_due:
                        _ob_due = (datetime.now(timezone.utc) + __import__('datetime').timedelta(days=3)).strftime("%Y-%m-%d")
                    _ob_priority = "high" if _ob_data.get("urgency") == "high" else "normal"
                    insert_deadline(
                        description=f"[Commitment to {_ob_to}] {_ob_desc}",
                        due_date=datetime.strptime(_ob_due, "%Y-%m-%d"),
                        source_type="email",
                        source_id=f"commitment-email:{message_id}",
                        confidence="medium",
                        priority=_ob_priority,
                        source_snippet=f"Email to {_ob_to}\nSubject: {metadata.get('subject', '')}\n{thread['text'][:300]}",
                    )
                    logger.info(f"OBLIGATIONS-DETECT-1: commitment from email: {_ob_desc[:60]}")
        except Exception as _oe:
            logger.warning(f"OBLIGATIONS-DETECT-1: email commitment detection failed (non-fatal): {_oe}")

        trigger = TriggerEvent(
            type="email",
            content=thread["text"],
            source_id=message_id,
            contact_name=metadata.get("primary_sender"),
        )
        trigger = pipeline.classify_trigger(trigger)

        # DEADLINE-SYSTEM-1: Extract deadlines from email content
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=thread["text"],
                source_type="email",
                source_id=message_id,
                sender_name=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
            )
        except Exception as _e:
            logger.debug(f"Deadline extraction failed for email {message_id}: {_e}")

        # MEETINGS-DETECT-2: Check for meeting content in email
        try:
            _email_subject = metadata.get("subject", "")
            _email_body = thread["text"]
            if _is_meeting_email(_email_subject, _email_body):
                _meeting_data = _extract_meeting_from_email(
                    _email_subject, _email_body,
                    metadata.get("primary_sender", ""),
                    metadata.get("primary_sender_email", ""),
                    metadata.get("received_date", ""),
                )
                if _meeting_data and _meeting_data.get("is_meeting") and _meeting_data.get("date"):
                    from memory.store_back import SentinelStoreBack
                    _mstore = SentinelStoreBack._get_global_instance()
                    _parsed_date = None
                    try:
                        _parsed_date = datetime.strptime(_meeting_data["date"], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
                    if _parsed_date:
                        _mstore.insert_detected_meeting(
                            title=_meeting_data.get("title", _email_subject),
                            participant_names=_meeting_data.get("participants", []),
                            meeting_date=_parsed_date,
                            meeting_time=_meeting_data.get("time"),
                            location=_meeting_data.get("location"),
                            status=_meeting_data.get("status", "proposed"),
                            source="email",
                            source_ref=f"email:{thread_id}",
                            raw_text=f"From: {metadata.get('primary_sender', '')}\nSubject: {_email_subject}\n{_email_body[:500]}",
                        )
                        logger.info(f"MEETINGS-DETECT-2: detected meeting from email: {_meeting_data.get('title', '')[:60]}")
        except Exception as _e:
            logger.warning(f"MEETINGS-DETECT-2: email meeting detection failed (non-fatal): {_e}")

        # COST-OPT-WAVE2: Skip pipeline for automated/newsletter senders
        _sender_email = metadata.get("primary_sender_email", "")
        if _should_skip_pipeline(_sender_email, thread.get("text", "")):
            logger.info(f"Email trigger: skipping pipeline for automated sender {_sender_email} (thread {thread_id})")
            skipped += 1
            continue

        if trigger.priority in ("high", "medium"):
            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"Email trigger: pipeline failed for message {message_id} (thread {thread_id}): {e}")

            # Phase 3C: Extract commitments from high-priority emails
            try:
                _extract_commitments_from_email(
                    email_text=thread["text"],
                    subject=metadata.get("subject", ""),
                    sender=metadata.get("primary_sender", ""),
                    source_id=message_id,
                )
            except Exception as _e:
                logger.debug(f"Commitment extraction failed for email {message_id}: {_e}")

            # Phase 3C: Check for intelligence signals in high-priority emails
            if trigger.priority == "high":
                try:
                    _check_email_intelligence(
                        email_text=thread["text"],
                        subject=metadata.get("subject", ""),
                        sender=metadata.get("primary_sender", ""),
                        source_id=message_id,
                    )
                except Exception as _e:
                    logger.debug(f"Email intelligence check failed for {message_id}: {_e}")
        else:
            # Queue low-priority for daily briefing
            batch_for_briefing.append({
                "type": "email",
                "source_id": message_id,
                "content": thread["text"],
                "contact_name": metadata.get("primary_sender"),
                "subject": metadata.get("subject", ""),
                "priority": trigger.priority,
            })

    # Store low-priority batch for briefing
    if batch_for_briefing:
        trigger_state.add_to_briefing_queue(batch_for_briefing)

    # ART-1: Check all processed emails for research-worthy intelligence
    # Content-driven — regex pre-filter + Haiku classification
    # COST-OPT-WAVE1: Only check threads that actually got processed (post-dedup),
    # not the full new_threads list which includes already-seen threads.
    for thread in new_threads:
        try:
            _text = thread.get("text", "")
            _meta = thread.get("metadata", {})
            _sender = _meta.get("primary_sender", "")
            _tid = _meta.get("thread_id", "")
            if _text and len(_text) > 200:
                from orchestrator.research_trigger import check_research_trigger
                check_research_trigger(_text, _sender, f"email-{_tid}")
        except Exception:
            pass  # Non-fatal

    # F4: Advance watermark to the newest received_date seen this cycle
    # (covers both processed and deduped threads — prevents re-fetching old batches)
    if latest_seen_dt:
        now_utc = datetime.now(timezone.utc)
        if latest_seen_dt > now_utc:
            logger.warning(
                f"Email watermark ceiling hit: {latest_seen_dt.isoformat()} > now "
                f"({now_utc.isoformat()}). Capping at now."
            )
            latest_seen_dt = now_utc
        trigger_state.set_watermark("email_poll", latest_seen_dt)
        logger.info(f"Email watermark advanced to {latest_seen_dt.isoformat()}")

    logger.info(
        f"Email trigger: {processed} processed, "
        f"{len(batch_for_briefing)} queued for briefing, {skipped} skipped (dedup)"
    )


def _check_reply_match(
    thread_id: str,
    sender: str = "",
    sender_email: str = "",
    subject: str = "",
    body_preview: str = "",
):
    """
    REPLY-TRACK-1: Check if an incoming email is a reply to a Baker-sent email.
    If so, mark it as replied and push an alert to the digest buffer.
    """
    from models.sent_emails import find_awaiting_reply, mark_reply_received

    sent = find_awaiting_reply(thread_id)
    if not sent:
        return  # Not a reply to anything Baker sent

    # Mark reply received
    mark_reply_received(
        sent_email_id=sent["id"],
        reply_snippet=body_preview[:300],
        reply_from=sender_email or sender,
    )
    logger.info(
        f"Reply detected from {sender} to Baker-sent email "
        f"(thread={thread_id}, original subject: {sent.get('subject', '?')[:60]})"
    )

    # Determine urgency: VIP replies = urgent
    is_vip = False
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        sender_lower = (sender or "").lower()
        email_lower = (sender_email or "").lower()
        for vip in vips:
            vip_name = (vip.get("name") or "").lower()
            vip_email = (vip.get("email") or "").lower()
            if (sender_lower and sender_lower in vip_name) or \
               (email_lower and email_lower == vip_email):
                is_vip = True
                break
    except Exception:
        pass

    tier = 1 if is_vip else 2

    # Push alert to digest buffer
    try:
        from orchestrator.digest_manager import add_alert

        reply_preview = body_preview[:200].replace("\n", " ")
        title = (
            f"\U0001f4e9 Reply received to Baker-sent email\n"
            f"From: {sender or sender_email}\n"
            f"Original subject: {sent.get('subject', '?')}\n"
            f'Preview: "{reply_preview}..."'
        )

        add_alert(
            title=title,
            source_type="Reply Detection",
            timestamp=datetime.now(timezone.utc).strftime("%H:%M UTC"),
            tier=tier,
            source_id=f"reply:{thread_id}",
            content=f"Reply from {sender} to: {sent.get('subject', '?')}",
            is_critical=is_vip,
        )
    except Exception as e:
        logger.warning(f"Failed to push reply alert to digest: {e}")

    # If original was sent via WhatsApp, also notify on WhatsApp
    if sent.get("channel") == "whatsapp":
        try:
            from outputs.whatsapp_sender import send_whatsapp

            wa_text = (
                f"\U0001f4e9 Reply to your email:\n"
                f"From: {sender or sender_email}\n"
                f"Re: {sent.get('subject', '?')}\n"
                f'"{body_preview[:200]}"\n\n'
                f"Reply here to follow up, or ask me to draft a response."
            )
            send_whatsapp(wa_text)
        except Exception as e:
            logger.warning(f"WhatsApp reply notification failed: {e}")


def backfill_emails(days: int = 14):
    """
    ARCH-6: One-time backfill — fetch last N days of emails from Gmail API,
    store full bodies to email_messages table + embed to Qdrant.
    No pipeline re-run. Safe to run repeatedly (upsert on conflict).
    """
    import time as _time

    logger.info(f"Email backfill: fetching last {days} days from Gmail API...")

    try:
        from scripts import extract_gmail
        from scripts.extract_gmail import (
            authenticate, fetch_thread_ids, fetch_thread_detail,
            format_thread, has_skip_label, is_noise_thread,
        )
        from googleapiclient.discovery import build
        from memory.store_back import SentinelStoreBack

        creds = authenticate()
        service = build("gmail", "v1", credentials=creds)
        # ARCH-6: Set Gmail service so format_thread() can extract attachments
        extract_gmail._gmail_service = service
        store = SentinelStoreBack._get_global_instance()

        since_date = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
        query = f"after:{since_date} {config.gmail.default_query}"

        logger.info(f"Email backfill query: {query}")
        thread_ids = fetch_thread_ids(service, query, limit=None)

        if not thread_ids:
            logger.info("Email backfill: no threads found")
            return

        logger.info(f"Email backfill: {len(thread_ids)} threads to process")

        stored = 0
        embedded = 0

        for i, tid in enumerate(thread_ids):
            thread = fetch_thread_detail(service, tid)
            if not thread:
                continue

            messages = thread.get("messages", [])

            # Skip noise
            if has_skip_label(messages):
                continue
            is_noise, _ = is_noise_thread(messages)
            if is_noise:
                continue

            # Limit messages per thread
            if len(messages) > config.gmail.max_messages_per_thread:
                messages = messages[-config.gmail.max_messages_per_thread:]

            formatted = format_thread(thread, messages)
            if not formatted:
                continue

            metadata = formatted.get("metadata", {})
            message_id = metadata.get("message_id", tid)

            # Store to PostgreSQL
            success = store.store_email_message(
                message_id=message_id,
                thread_id=metadata.get("thread_id"),
                sender_name=metadata.get("primary_sender"),
                sender_email=metadata.get("primary_sender_email"),
                subject=metadata.get("subject"),
                full_body=formatted["text"],
                received_date=metadata.get("received_date"),
            )
            if success:
                stored += 1

            # Embed to Qdrant with rate limiting
            try:
                _time.sleep(2)  # Voyage AI rate limit
                embed_metadata = {
                    "source": "email",
                    "subject": metadata.get("subject", ""),
                    "sender": metadata.get("primary_sender", ""),
                    "sender_email": metadata.get("primary_sender_email", ""),
                    "date": metadata.get("received_date", ""),
                    "message_id": message_id,
                    "thread_id": metadata.get("thread_id", ""),
                    "content_type": "email_thread",
                    "label": metadata.get("subject", "email"),
                }
                store.store_document(formatted["text"], embed_metadata, collection="baker-conversations")
                embedded += 1
            except Exception as _e:
                logger.warning(f"Email Qdrant embed failed for {message_id}: {_e}")

            if (i + 1) % 50 == 0:
                logger.info(f"Email backfill: processed {i + 1}/{len(thread_ids)}...")

        logger.info(f"Email backfill complete: {stored} stored to PostgreSQL, {embedded} embedded to Qdrant (of {len(thread_ids)} threads)")

    except Exception as e:
        logger.error(f"Email backfill failed: {e}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=0,
                        help="Backfill last N days of emails to PostgreSQL + Qdrant")
    args = parser.parse_args()

    if args.backfill:
        backfill_emails(days=args.backfill)
    else:
        check_new_emails()
