"""
Baker Email Alerts — EMAIL-SMART-1
Central module for all outbound Baker proactive emails.

Phase 1 (automatic):
  send_alert_email()         — Type 1: high-priority trigger → immediate alert
  send_scan_result_email()   — Type 2: scan complete → Q&A to Director
  send_daily_summary_email() — Type 3: 06:00 UTC cron → daily briefing + health

Phase 2 (Director-triggered only):
  send_manual_summary_email() — Type 4: dashboard button → on-demand summary
  send_composed_email()        — Type 5: compose form → any recipient

Guard rails:
  - Max 20 alert emails per hour. Overflow batched into a digest at hour end.
  - Dedup: same source_id does not trigger duplicate alerts within an hour.
  - Fail silently: Gmail errors are logged, never crash the caller.
  - Phase 1 only ever sends to dvallen@brisengroup.com.
"""
import base64
import logging
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("baker.email_alerts")

DIRECTOR_EMAIL = "dvallen@brisengroup.com"
_BAKER_EMAIL = os.getenv("BAKER_EMAIL_ADDRESS", "bakerai200@gmail.com")
_MAX_ALERTS_PER_HOUR = 20

# ---------------------------------------------------------------------------
# In-memory rate limiter and dedup tracker (reset each hour)
# ---------------------------------------------------------------------------
_rate_hour: str = ""
_rate_count: int = 0
_sent_source_ids: set = set()
_overflow_buffer: list = []  # alerts held when rate limit exceeded


def _reset_if_new_hour():
    global _rate_hour, _rate_count, _sent_source_ids, _overflow_buffer
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    if current_hour != _rate_hour:
        if _overflow_buffer:
            _flush_overflow_digest()
        _rate_hour = current_hour
        _rate_count = 0
        _sent_source_ids = set()
        _overflow_buffer = []


def _under_rate_limit() -> bool:
    _reset_if_new_hour()
    return _rate_count < _MAX_ALERTS_PER_HOUR


def _increment_rate():
    global _rate_count
    _rate_count += 1


def _flush_overflow_digest():
    """Send a single digest for alerts that exceeded the hourly rate limit."""
    if not _overflow_buffer:
        return
    try:
        now = datetime.now(timezone.utc)
        subject = f"Baker Alert Digest — {len(_overflow_buffer)} alerts (rate limit exceeded)"
        lines = [
            f"Rate limit of {_MAX_ALERTS_PER_HOUR} alert emails/hour was exceeded.",
            f"The following {len(_overflow_buffer)} alerts were held:\n",
        ]
        for item in _overflow_buffer:
            lines.append(f"  • [{item.get('source_type')}] {item.get('contact_name')} — {item.get('snippet')}")
        lines.append(f"\n---\nSent automatically by Baker CEO Cockpit — {now.strftime('%Y-%m-%d %H:%M UTC')}")
        _send_raw(DIRECTOR_EMAIL, subject, "\n".join(lines))
        logger.info(f"Alert digest sent: {len(_overflow_buffer)} buffered alerts")
    except Exception as e:
        logger.error(f"Overflow digest send failed: {e}")


# ---------------------------------------------------------------------------
# Gmail send primitive (no FastAPI dependency — safe to import from pipeline)
# ---------------------------------------------------------------------------

def _get_gmail_service():
    """Build Gmail API service using Baker's OAuth2 refresh token."""
    client_id = os.getenv("BAKER_GMAIL_CLIENT_ID", "")
    client_secret = os.getenv("BAKER_GMAIL_CLIENT_SECRET", "")
    refresh_token = os.getenv("BAKER_GMAIL_REFRESH_TOKEN", "")
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "Missing Gmail credentials: BAKER_GMAIL_CLIENT_ID, "
            "BAKER_GMAIL_CLIENT_SECRET, BAKER_GMAIL_REFRESH_TOKEN"
        )
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    return build("gmail", "v1", credentials=creds)


def _send_raw(to: str, subject: str, body: str) -> Optional[str]:
    """
    Low-level Gmail send. Returns message_id on success, None on failure.
    Caller is responsible for all error handling.
    """
    service = _get_gmail_service()
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = _BAKER_EMAIL
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    message_id = result.get("id")
    logger.info(f"Email sent to {to}: {subject!r} (id={message_id})")
    return message_id


# ---------------------------------------------------------------------------
# Summary content builder (shared by Type 3 and Type 4)
# ---------------------------------------------------------------------------

def _build_summary_body(custom_note: str = "", briefing_text: str = "") -> str:
    """
    Assemble the full summary email body:
      [Director's Note] (if custom_note)
      [Morning Briefing] (if briefing_text)
      [Briefing — Last 24h] (live stats)
      [System Health] (watermarks)
    """
    now = datetime.now(timezone.utc)
    parts = []

    # Optional director note
    if custom_note and custom_note.strip():
        parts.append(f"[Director's Note]\n{custom_note.strip()}")

    # Optional pipeline briefing (Type 3 daily only)
    if briefing_text and briefing_text.strip():
        preview = briefing_text.strip()[:2000]
        parts.append(f"[Morning Briefing]\n{preview}")

    # Live stats from briefing queue + alerts
    stat_lines = ["[Briefing — Last 24h]"]
    try:
        from triggers.state import trigger_state
        queue = trigger_state.get_briefing_queue()
        email_items = [q for q in queue if q.get("type") == "email"]
        wa_items = [q for q in queue if q.get("type") == "whatsapp"]
        meeting_items = [q for q in queue if q.get("type") == "meeting"]
        rss_items = [q for q in queue if q.get("type") == "rss"]

        top_senders = list({q.get("contact_name", "?") for q in email_items if q.get("contact_name")})[:3]
        sender_str = f" (top senders: {', '.join(top_senders)})" if top_senders else ""
        stat_lines.append(f"- {len(email_items)} emails processed{sender_str}")

        meeting_titles = [q.get("content", "")[:40] for q in meeting_items[:3]]
        title_str = f" ({', '.join(meeting_titles)})" if meeting_titles else ""
        stat_lines.append(f"- {len(meeting_items)} meeting transcripts{title_str}")

        top_rss = list({q.get("contact_name", q.get("source", "?")) for q in rss_items})[:3]
        rss_str = f" (top sources: {', '.join(top_rss)})" if top_rss else ""
        stat_lines.append(f"- {len(rss_items)} RSS articles ingested{rss_str}")
        stat_lines.append(f"- {len(wa_items)} WhatsApp messages received")
    except Exception as e:
        logger.warning(f"Could not read briefing queue for summary: {e}")
        stat_lines.append("- Activity stats unavailable")

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        alerts = store.get_pending_alerts()
        tier1 = [a for a in alerts if a.get("tier") == 1]
        stat_lines.append(f"- {len(tier1)} high-priority alerts fired")
        if alerts:
            tier_labels = {1: "URGENT", 2: "IMPORTANT", 3: "INFO"}
            pending = [
                f"  • [{tier_labels.get(a.get('tier'), '?')}] {a.get('title', '')}"
                for a in alerts[:8]
            ]
            stat_lines.append("- Action items pending:")
            stat_lines.extend(pending)
    except Exception as e:
        logger.warning(f"Could not fetch alerts for summary: {e}")

    parts.append("\n".join(stat_lines))

    # System health via watermarks
    health_lines = ["[System Health]"]
    sentinels = [
        ("email_poll",    "Email sentinel"),
        ("rss",           "RSS sentinel"),
        ("fireflies",     "Fireflies sentinel"),
        ("clickup",       "ClickUp sentinel"),
        ("whoop",         "Whoop sentinel"),
        ("slack",         "Slack sentinel"),
        ("dropbox",       "Dropbox sentinel"),
        ("todoist",       "Todoist sentinel"),
    ]
    try:
        from triggers.state import trigger_state
        for source_key, label in sentinels:
            try:
                wm = trigger_state.get_watermark(source_key)
                delta = now - wm
                total_secs = int(delta.total_seconds())
                if total_secs < 0:
                    health_lines.append(f"- {label}: ✓ active")
                elif total_secs < 3600:
                    health_lines.append(f"- {label}: ✓ last poll {total_secs // 60}m ago")
                else:
                    health_lines.append(f"- {label}: ✓ last poll {total_secs // 3600}h ago")
            except Exception:
                health_lines.append(f"- {label}: ✗ status unknown")
    except Exception as e:
        logger.warning(f"Could not load trigger state for health: {e}")
        health_lines.append("- Sentinel health unavailable")

    parts.append("\n".join(health_lines))
    parts.append(f"---\nSent automatically by Baker CEO Cockpit — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 1 — Type 1: Urgent Alert (automatic, immediate)
# ---------------------------------------------------------------------------

def send_alert_email(trigger) -> bool:
    """
    Send immediate alert email for high-priority pipeline triggers.
    Called by pipeline.py after classify_trigger() returns priority='high'.
    Rate limited to 20/hour with overflow digest. Deduped by source_id.
    """
    try:
        _reset_if_new_hour()
        source_id = getattr(trigger, "source_id", "") or ""
        source_type = (getattr(trigger, "type", "unknown") or "unknown").title()
        contact_name = getattr(trigger, "contact_name", None) or "Unknown"
        content = getattr(trigger, "content", "") or ""
        timestamp = getattr(trigger, "timestamp", "") or datetime.now(timezone.utc).isoformat()

        # Dedup check
        if source_id and source_id in _sent_source_ids:
            logger.info(f"Alert email dedup: {source_id} already sent this hour")
            return False

        # Rate limit check
        if not _under_rate_limit():
            logger.warning(f"Alert rate limit reached — buffering alert for {source_id}")
            _overflow_buffer.append({
                "source_type": source_type,
                "contact_name": contact_name,
                "snippet": content[:80],
            })
            return False

        subject = f"\U0001f534 Baker Alert \u2014 {source_type}: {contact_name}"
        body = (
            f"URGENT \u2014 requires your attention\n\n"
            f"Source: {source_type}\n"
            f"From: {contact_name}\n"
            f"Time: {timestamp}\n\n"
            f"{content[:500]}\n\n"
            f"---\n"
            f"Sent automatically by Baker CEO Cockpit"
        )

        message_id = _send_raw(DIRECTOR_EMAIL, subject, body)
        if message_id:
            if source_id:
                _sent_source_ids.add(source_id)
            _increment_rate()
            return True
        return False

    except Exception as e:
        logger.error(f"send_alert_email failed (non-fatal): {e}")
        return False


# ---------------------------------------------------------------------------
# Phase 1 — Type 2: Scan Result (automatic, on scan completion)
# ---------------------------------------------------------------------------

def send_scan_result_email(question: str, answer: str) -> bool:
    """
    Email the Director the full Q&A after each Baker Scan completes.
    Called by dashboard.py event_stream() after streaming finishes.
    """
    try:
        subject = f"Baker Scan \u2014 {question[:60]}"
        body = (
            f"Your question:\n{question}\n\n"
            f"Baker\u2019s answer:\n{answer}\n\n"
            f"---\n"
            f"Sent automatically by Baker CEO Cockpit"
        )
        return bool(_send_raw(DIRECTOR_EMAIL, subject, body))
    except Exception as e:
        logger.error(f"send_scan_result_email failed (non-fatal): {e}")
        return False


# ---------------------------------------------------------------------------
# Phase 1 — Type 3: Daily Summary (automatic, 06:00 UTC cron)
# ---------------------------------------------------------------------------

def send_daily_summary_email(briefing_text: str = "") -> bool:
    """
    Send the morning summary email to the Director.
    Called by briefing_trigger.py after generate_morning_briefing() completes.
    """
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subject = f"Baker Daily Summary \u2014 {date_str}"
        body = _build_summary_body(briefing_text=briefing_text)
        return bool(_send_raw(DIRECTOR_EMAIL, subject, body))
    except Exception as e:
        logger.error(f"send_daily_summary_email failed (non-fatal): {e}")
        return False


# ---------------------------------------------------------------------------
# Phase 2 — Type 4: Manual Summary (Director-triggered via dashboard button)
# ---------------------------------------------------------------------------

def send_manual_summary_email(custom_note: str = "", to: str = None) -> Optional[str]:
    """
    Generate and send an on-demand summary to the Director.
    Returns message_id on success, None on failure.
    Called by /api/email/send when no body is provided.
    """
    try:
        recipient = to or DIRECTOR_EMAIL
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subject = f"Baker Summary \u2014 {date_str}"
        body = _build_summary_body(custom_note=custom_note)
        return _send_raw(recipient, subject, body)
    except Exception as e:
        logger.error(f"send_manual_summary_email failed (non-fatal): {e}")
        return None


# ---------------------------------------------------------------------------
# Phase 2 — Type 5: Composed Email (Director-triggered, any recipient)
# ---------------------------------------------------------------------------

def send_composed_email(to: str, subject: str, body: str) -> Optional[str]:
    """
    Send a Director-composed email via Baker's Gmail to any recipient.
    Appends standard footer. Returns message_id on success, None on failure.
    Called by /api/email/send when body is provided.
    """
    try:
        full_body = (
            f"{body}\n\n"
            f"---\n"
            f"Sent via Baker CEO Cockpit on behalf of Dimitry Vallen"
        )
        return _send_raw(to, subject, full_body)
    except Exception as e:
        logger.error(f"send_composed_email failed (non-fatal): {e}")
        return None
