"""
Baker Email Alerts — EMAIL-REFORM-1
Central module for all outbound Baker proactive emails.

Phase 1 (automatic):
  send_alert_email()         — Type 1: routes through digest buffer (30-min batching)
  send_scan_result_email()   — Type 2: only when Director explicitly requests email
  send_daily_summary_email() — Type 3: 06:00 UTC cron → structured executive briefing

Phase 2 (Director-triggered only):
  send_manual_summary_email() — Type 4: dashboard button → on-demand summary
  send_composed_email()        — Type 5: compose form → any recipient

Guard rails:
  - Type 1: alerts batched into 30-min digest via digest_manager (no per-event emails).
  - Type 1: CRITICAL alerts (system down) bypass digest and send immediately.
  - Type 2: disabled by default. Only fires on explicit email request in Scan query.
  - Type 3: curated executive summary with Claude synthesis.
  - Fail silently: Gmail errors are logged, never crash the caller.
  - Phase 1 only ever sends to dvallen@brisengroup.com.
"""
import base64
import logging
import os
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("baker.email_alerts")

DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DASHBOARD_URL = "baker-master.onrender.com"
_BAKER_EMAIL = os.getenv("BAKER_EMAIL_ADDRESS", "bakerai200@gmail.com")


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
# Type 2 — Email delivery intent detection (EMAIL-REFORM-1)
# ---------------------------------------------------------------------------

# Patterns that indicate the Director wants the Scan result emailed
_EMAIL_INTENT_PATTERNS = [
    r"\bemail\s+me\b",
    r"\bemail\s+this\b",
    r"\bemail\s+it\b",
    r"\bsend\s+(?:it\s+)?to\s+my\s+email\b",
    r"\bsend\s+me\s+(?:a\s+)?(?:report|summary|result|analysis)\b",
    r"\bsend\s+(?:this|it)\s+to\s+me\b",
    r"\bmail\s+(?:me|this|it)\b",
]
_EMAIL_INTENT_RE = re.compile("|".join(_EMAIL_INTENT_PATTERNS), re.IGNORECASE)


def has_email_intent(question: str) -> bool:
    """
    Check if the Director's Scan query explicitly requests email delivery.
    Returns True if an email trigger phrase is detected.
    """
    return bool(_EMAIL_INTENT_RE.search(question))


# ---------------------------------------------------------------------------
# Type 3 — Structured daily briefing builder (EMAIL-REFORM-1)
# ---------------------------------------------------------------------------

def _build_daily_briefing_body(briefing_text: str = "") -> str:
    """
    Build the Type 3 daily briefing email body in the new structured format:
    - DECISIONS NEEDED (Claude-synthesized)
    - KEY DEVELOPMENTS (Claude-synthesized)
    - NUMBERS (counts from data)
    - SYSTEM STATUS (sentinel health)

    briefing_text: Claude-generated briefing from briefing_trigger.py
    """
    now = datetime.now(timezone.utc)
    day_name = now.strftime("%A")
    date_display = now.strftime("%-d %B %Y")

    parts = [
        f"Baker Daily Briefing \u2014 {day_name}, {date_display}",
        "",
        "\u2501" * 30,
        "",
    ]

    # Insert Claude-synthesized briefing content (Decisions + Developments)
    if briefing_text and briefing_text.strip():
        parts.append(briefing_text.strip())
        parts.append("")
    else:
        parts.append("\U0001f4cc DECISIONS NEEDED")
        parts.append("\u2022 No pending decisions today.")
        parts.append("")
        parts.append("\U0001f4ca KEY DEVELOPMENTS (last 24h)")
        parts.append("\u2022 No developments to report.")
        parts.append("")

    # NUMBERS section — simple counts from the database
    parts.append("\U0001f4c8 NUMBERS")
    try:
        from triggers.state import trigger_state
        queue = trigger_state.get_briefing_queue()
        email_count = sum(1 for q in queue if q.get("type") == "email")
        meeting_count = sum(1 for q in queue if q.get("type") == "meeting")
        rss_items = [q for q in queue if q.get("type") == "rss"]
        rss_count = len(rss_items)
        rss_flagged = sum(1 for q in rss_items if q.get("flagged"))
        wa_count = sum(1 for q in queue if q.get("type") == "whatsapp")

        parts.append(f"\u2022 Emails received: {email_count}")
        parts.append(f"\u2022 Meetings recorded: {meeting_count}")
        parts.append(f"\u2022 RSS items processed: {rss_count} | Flagged: {rss_flagged}")
        parts.append(f"\u2022 WhatsApp messages: {wa_count}")
    except Exception as e:
        logger.warning(f"Could not read briefing queue for numbers: {e}")
        parts.append("\u2022 Activity stats unavailable")

    # Scan query count
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        decisions = store.get_recent_decisions(limit=50)
        scan_count = sum(1 for d in decisions if d.get("trigger_type") == "scan")
        parts.append(f"\u2022 Scan queries answered: {scan_count}")
    except Exception as e:
        logger.warning(f"Could not count scan queries: {e}")

    parts.append("")

    # SYSTEM STATUS section
    parts.append("\U0001f7e2 SYSTEM STATUS")
    sentinels = [
        ("email_poll",    "Email"),
        ("rss",           "RSS"),
        ("fireflies",     "Fireflies"),
        ("clickup",       "ClickUp"),
        ("whoop",         "Whoop"),
        ("slack",         "Slack"),
        ("dropbox",       "Dropbox"),
        ("todoist",       "Todoist"),
    ]
    all_ok = True
    issues = []
    try:
        from triggers.state import trigger_state
        for source_key, label in sentinels:
            try:
                wm = trigger_state.get_watermark(source_key)
                delta = now - wm
                total_secs = int(delta.total_seconds())
                if total_secs < 0 or total_secs < 7200:  # < 2 hours = healthy
                    pass  # healthy
                else:
                    all_ok = False
                    hours = total_secs // 3600
                    issues.append(f"{label} (last poll {hours}h ago)")
            except Exception:
                all_ok = False
                issues.append(f"{label} (status unknown)")

        if all_ok:
            parts.append("\u2022 All sentinels operational")
        else:
            parts.append(f"\u2022 Issues: {', '.join(issues)}")
            healthy = len(sentinels) - len(issues)
            parts.append(f"\u2022 {healthy}/{len(sentinels)} sentinels healthy")
    except Exception as e:
        logger.warning(f"Could not load trigger state for health: {e}")
        parts.append("\u2022 Sentinel health unavailable")

    parts.append(f"\u2022 Last restart: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    parts.append("")

    # Footer
    parts.append("\u2501" * 30)
    parts.append(f"Baker CEO Cockpit \u2014 {DASHBOARD_URL}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Summary content builder (used by Type 4 manual summary only)
# ---------------------------------------------------------------------------

def _build_summary_body(custom_note: str = "") -> str:
    """
    Assemble the manual summary email body (Type 4):
      [Director's Note] (if custom_note)
      [Briefing — Last 24h] (live stats)
      [System Health] (watermarks)
    """
    now = datetime.now(timezone.utc)
    parts = []

    # Optional director note
    if custom_note and custom_note.strip():
        parts.append(f"[Director's Note]\n{custom_note.strip()}")

    # Live stats from briefing queue + alerts
    stat_lines = ["[Briefing \u2014 Last 24h]"]
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
                f"  \u2022 [{tier_labels.get(a.get('tier'), '?')}] {a.get('title', '')}"
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
                    health_lines.append(f"- {label}: \u2713 active")
                elif total_secs < 3600:
                    health_lines.append(f"- {label}: \u2713 last poll {total_secs // 60}m ago")
                else:
                    health_lines.append(f"- {label}: \u2713 last poll {total_secs // 3600}h ago")
            except Exception:
                health_lines.append(f"- {label}: \u2717 status unknown")
    except Exception as e:
        logger.warning(f"Could not load trigger state for health: {e}")
        health_lines.append("- Sentinel health unavailable")

    parts.append("\n".join(health_lines))
    parts.append(f"---\nSent automatically by Baker CEO Cockpit \u2014 {now.strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 1 — Type 1: Alert → Digest Buffer (EMAIL-REFORM-1)
# ---------------------------------------------------------------------------

def send_alert_email(trigger) -> bool:
    """
    Route a high-priority trigger alert into the 30-min digest buffer.
    Replaces the old per-event immediate email.
    Critical alerts (sentinel failures) bypass the digest and send immediately.

    Called by pipeline.py after classify_trigger() returns priority='high'.
    """
    try:
        source_id = getattr(trigger, "source_id", "") or ""
        source_type = (getattr(trigger, "type", "unknown") or "unknown").title()
        contact_name = getattr(trigger, "contact_name", None) or "Unknown"
        content = getattr(trigger, "content", "") or ""
        timestamp = getattr(trigger, "timestamp", "") or datetime.now(timezone.utc).strftime("%H:%M UTC")
        priority = getattr(trigger, "priority", "medium") or "medium"

        # Determine tier: high priority → tier 1 (urgent), else tier 3 (info)
        tier = 1 if priority == "high" else 3

        # Detect critical alerts: sentinel failures, system down
        is_critical = _is_critical_alert(source_type, content)

        from orchestrator.digest_manager import add_alert
        title = f"{source_type}: {contact_name}"
        if content:
            title = f"{source_type}: {contact_name} \u2014 {content[:80]}"

        return add_alert(
            title=title,
            source_type=source_type,
            timestamp=timestamp,
            tier=tier,
            source_id=source_id,
            contact_name=contact_name,
            content=content,
            is_critical=is_critical,
        )

    except Exception as e:
        logger.error(f"send_alert_email failed (non-fatal): {e}")
        return False


def _is_critical_alert(source_type: str, content: str) -> bool:
    """
    Detect critical alerts that should bypass the digest.
    Critical = system down, sentinel failure, database error.
    """
    critical_keywords = [
        "system down", "sentinel failure", "sentinel failed",
        "database error", "connection failed", "service unavailable",
        "critical error", "fatal error", "out of memory",
    ]
    combined = f"{source_type} {content}".lower()
    return any(kw in combined for kw in critical_keywords)


# ---------------------------------------------------------------------------
# Phase 1 — Type 2: Scan Result (opt-in only — EMAIL-REFORM-1)
# ---------------------------------------------------------------------------

def send_scan_result_email(question: str, answer: str) -> bool:
    """
    Email the Director the full Q&A from Baker Scan.
    Only called when has_email_intent(question) returns True.
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
# Phase 1 — Type 3: Daily Briefing (structured format — EMAIL-REFORM-1)
# ---------------------------------------------------------------------------

def send_daily_summary_email(briefing_text: str = "") -> bool:
    """
    Send the structured daily briefing email to the Director.
    Called by briefing_trigger.py after generate_morning_briefing() completes.

    briefing_text should contain Claude-synthesized DECISIONS NEEDED and
    KEY DEVELOPMENTS sections from the briefing pipeline.
    """
    try:
        now = datetime.now(timezone.utc)
        day_name = now.strftime("%A")
        date_display = now.strftime("%-d %B %Y")
        subject = f"Baker Daily Briefing \u2014 {day_name}, {date_display}"
        body = _build_daily_briefing_body(briefing_text=briefing_text)
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
