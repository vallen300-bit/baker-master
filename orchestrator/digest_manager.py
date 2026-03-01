"""
Baker Digest Manager — EMAIL-REFORM-1
Collects sentinel alerts over a 30-minute window and sends a single digest email.

Rules:
- Timer starts when the first alert arrives in a window.
- At flush time: if buffer has items → compose digest → send → clear.
- Empty buffer at flush time → no email.
- CRITICAL alerts (system down / sentinel failure) bypass the digest and send immediately.
- Urgency: 🔴 for urgent (tier 1), ⚡ for informational (tier 2/3).
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("baker.digest_manager")

DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DASHBOARD_URL = "baker-master.onrender.com"
DIGEST_WINDOW_SECONDS = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# In-memory digest buffer (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_buffer: list = []


def add_alert(
    title: str,
    source_type: str,
    timestamp: str = "",
    tier: int = 3,
    source_id: str = "",
    contact_name: str = "",
    content: str = "",
    is_critical: bool = False,
) -> bool:
    """
    Add an alert to the digest buffer.

    If is_critical=True (system down, sentinel failure), bypasses the digest
    and sends an immediate standalone email.

    Returns True if alert was added/sent, False on error.
    """
    now_str = timestamp or datetime.now(timezone.utc).strftime("%H:%M UTC")

    alert_entry = {
        "title": title,
        "source_type": source_type,
        "timestamp": now_str,
        "tier": tier,
        "source_id": source_id,
        "contact_name": contact_name,
        "content": content,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }

    # Critical bypass — send immediately, skip buffer
    if is_critical:
        logger.warning(f"CRITICAL alert — bypassing digest: {title}")
        return _send_critical_alert(alert_entry)

    with _lock:
        _buffer.append(alert_entry)
        logger.info(f"Alert buffered for digest ({len(_buffer)} in buffer): {title}")

    return True


def flush_digest() -> bool:
    """
    Compose and send the digest email for all buffered alerts.
    Called by the scheduler every 30 minutes.
    Returns True if a digest was sent, False if buffer was empty or on error.
    """
    with _lock:
        if not _buffer:
            return False
        items = list(_buffer)
        _buffer.clear()

    logger.info(f"Flushing digest: {len(items)} alerts")

    try:
        subject = f"\U0001f534 Baker Alert Digest \u2014 {len(items)} items (last 30 min)"
        body = _compose_digest_body(items)

        from outputs.email_alerts import _send_raw
        message_id = _send_raw(DIRECTOR_EMAIL, subject, body)
        if message_id:
            logger.info(f"Digest sent: {len(items)} items (id={message_id})")
            return True
        else:
            # Re-buffer on send failure so alerts aren't lost
            with _lock:
                _buffer.extend(items)
            logger.error("Digest send returned None — alerts re-buffered")
            return False
    except Exception as e:
        # Re-buffer on error
        with _lock:
            _buffer.extend(items)
        logger.error(f"Digest flush failed — alerts re-buffered: {e}")
        return False


def get_buffer_count() -> int:
    """Return the current number of buffered alerts."""
    with _lock:
        return len(_buffer)


def get_buffer_snapshot() -> list:
    """Return a copy of the current buffer (for diagnostics)."""
    with _lock:
        return list(_buffer)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _urgency_icon(tier: int) -> str:
    """Return urgency icon per brief spec."""
    return "\U0001f534" if tier == 1 else "\u26a1"


def _urgency_label(tier: int) -> str:
    """Return urgency label per brief spec."""
    return "URGENT" if tier == 1 else "INFO"


def _compose_digest_body(items: list) -> str:
    """Build the digest email body per the EMAIL-REFORM-1 format spec."""
    lines = [
        f"\U0001f534 Baker Alert Digest \u2014 {len(items)} items",
        "",
        "\u2501" * 30,
        "",
    ]

    for item in items:
        tier = item.get("tier", 3)
        icon = _urgency_icon(tier)
        label = _urgency_label(tier)
        title = item.get("title", "Untitled")
        source = item.get("source_type", "Unknown")
        ts = item.get("timestamp", "")

        lines.append(f"{icon} [{label}] {title}")
        lines.append(f"   Source: {source} | {ts}")
        lines.append("")

    lines.append("\u2501" * 30)
    lines.append(f"View full details on Baker Dashboard")
    lines.append(DASHBOARD_URL)

    return "\n".join(lines)


def _send_critical_alert(alert: dict) -> bool:
    """Send a single critical alert immediately, bypassing the digest."""
    try:
        title = alert.get("title", "CRITICAL ALERT")
        source = alert.get("source_type", "System")
        ts = alert.get("timestamp", "")
        content = alert.get("content", "")

        subject = f"\U0001f534 CRITICAL \u2014 {title}"
        body = (
            f"CRITICAL ALERT \u2014 Immediate attention required\n\n"
            f"Source: {source}\n"
            f"Time: {ts}\n\n"
            f"{content[:500]}\n\n"
            f"\u2501" * 30 + "\n"
            f"Baker CEO Cockpit \u2014 {DASHBOARD_URL}"
        )

        from outputs.email_alerts import _send_raw
        message_id = _send_raw(DIRECTOR_EMAIL, subject, body)
        if message_id:
            logger.info(f"Critical alert sent immediately: {title} (id={message_id})")
            return True
        return False
    except Exception as e:
        logger.error(f"Critical alert send failed: {e}")
        return False
