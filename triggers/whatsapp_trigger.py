"""
DEPRECATED — Session 26 (2026-02-28)
Replaced by WAHA webhook receiver (triggers/waha_webhook.py).
Inbound messages now arrive via POST /api/webhook/whatsapp.
Outbound via outputs/whatsapp_sender.py.
Do NOT delete — kept as archive reference.

Original: Sentinel Trigger — WhatsApp (via Wassenger REST API)
Checks for new WhatsApp messages every 10 minutes.
Uses Wassenger REST API directly (not MCP) for headless operation.
Requires WASSENGER_API_KEY and WASSENGER_DEVICE_ID in .env.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.whatsapp")

# Wassenger API base
WASSENGER_API = "https://api.wassenger.com/v1"


def _get_api_key() -> str:
    """Get Wassenger API key from environment."""
    import os
    key = os.getenv("WASSENGER_API_KEY", "")
    if not key:
        logger.warning("WhatsApp trigger: WASSENGER_API_KEY not set, skipping")
    return key


def _get_device_id() -> str:
    """Get Wassenger device ID from environment."""
    import os
    return os.getenv("WASSENGER_DEVICE_ID", "")


def fetch_new_messages(api_key: str, device_id: str, since: datetime) -> list:
    """
    Fetch new WhatsApp messages from Wassenger API since watermark.
    Returns list of message dicts grouped by chat.
    """
    headers = {
        "Token": api_key,
        "Content-Type": "application/json",
    }

    # Fetch recent chats with unread messages
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{WASSENGER_API}/devices/{device_id}/chats",
                headers=headers,
                params={
                    "size": 50,
                    "sort": "-lastMessageAt",
                },
            )
            resp.raise_for_status()
            chats = resp.json()
    except Exception as e:
        logger.error(f"WhatsApp trigger: failed to fetch chats: {e}")
        return []

    if not chats:
        return []

    # For each chat with recent activity, fetch messages
    new_messages = []
    since_iso = since.isoformat()

    for chat in chats:
        last_msg_at = chat.get("lastMessageAt", "")
        if not last_msg_at or last_msg_at <= since_iso:
            continue

        chat_id = chat.get("wid", chat.get("id", ""))
        chat_name = chat.get("name") or chat.get("pushname") or chat_id

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{WASSENGER_API}/devices/{device_id}/chats/{chat_id}/messages",
                    headers=headers,
                    params={"size": 20, "sort": "-createdAt"},
                )
                resp.raise_for_status()
                messages = resp.json()
        except Exception as e:
            logger.warning(f"WhatsApp trigger: failed to fetch messages for {chat_name}: {e}")
            continue

        # Filter to messages newer than watermark
        recent = []
        for msg in messages:
            created = msg.get("createdAt", "")
            if created > since_iso:
                recent.append(msg)

        if recent:
            new_messages.append({
                "chat_id": chat_id,
                "chat_name": chat_name,
                "contact_type": chat.get("kind", "chat"),
                "messages": recent,
            })

    return new_messages


def format_chat_messages(chat_group: dict) -> dict:
    """Format a group of messages from one chat into pipeline-ready format."""
    chat_name = chat_group["chat_name"]
    messages = chat_group["messages"]

    lines = [f"WhatsApp conversation with {chat_name}:"]
    for msg in reversed(messages):  # chronological order
        sender = msg.get("senderName") or msg.get("fromNumber") or "Unknown"
        body = msg.get("body") or msg.get("text") or ""
        msg_type = msg.get("type", "text")
        timestamp = msg.get("createdAt", "")[:19]

        if msg_type == "text" and body:
            lines.append(f"[{timestamp}] {sender}: {body}")
        elif msg_type in ("image", "video", "document", "audio"):
            caption = body or f"[{msg_type} file]"
            lines.append(f"[{timestamp}] {sender}: {caption}")
        else:
            lines.append(f"[{timestamp}] {sender}: [{msg_type}]")

    return {
        "text": "\n".join(lines),
        "metadata": {
            "chat_id": chat_group["chat_id"],
            "chat_name": chat_name,
            "contact_type": chat_group["contact_type"],
            "message_count": len(messages),
            "source": "whatsapp",
        },
    }


def check_new_whatsapp():
    """
    Main entry point — called by scheduler every 10 minutes.
    1. Fetches new WhatsApp messages since watermark
    2. Groups by chat and formats
    3. Runs pipeline for known contacts or high-priority signals
    4. Updates watermark
    """
    logger.info("WhatsApp trigger: checking for new messages...")

    api_key = _get_api_key()
    device_id = _get_device_id()

    if not api_key or not device_id:
        logger.info("WhatsApp trigger: API key or device ID not configured, skipping")
        return

    watermark = trigger_state.get_watermark("whatsapp")
    logger.info(f"WhatsApp watermark: {watermark.isoformat()}")

    try:
        chat_groups = fetch_new_messages(api_key, device_id, watermark)
    except Exception as e:
        logger.error(f"WhatsApp trigger: fetch failed: {e}")
        return

    if not chat_groups:
        logger.info("WhatsApp trigger: no new messages")
        return

    total_msgs = sum(len(g["messages"]) for g in chat_groups)
    logger.info(f"WhatsApp trigger: {total_msgs} new messages in {len(chat_groups)} chats")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    processed = 0
    batch_for_briefing = []

    for chat_group in chat_groups:
        formatted = format_chat_messages(chat_group)
        chat_id = chat_group["chat_id"]

        trigger = TriggerEvent(
            type="whatsapp",
            content=formatted["text"],
            source_id=f"wa-{chat_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            contact_name=chat_group["chat_name"],
        )
        trigger = pipeline.classify_trigger(trigger)

        if trigger.priority in ("high", "medium"):
            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"WhatsApp trigger: pipeline failed for {chat_group['chat_name']}: {e}")
        else:
            batch_for_briefing.append({
                "type": "whatsapp",
                "source_id": chat_id,
                "content": formatted["text"][:500],
                "contact_name": chat_group["chat_name"],
                "message_count": len(chat_group["messages"]),
                "priority": trigger.priority,
            })

    if batch_for_briefing:
        trigger_state.add_to_briefing_queue(batch_for_briefing)

    # Update watermark
    trigger_state.set_watermark("whatsapp")

    logger.info(
        f"WhatsApp trigger complete: {processed} processed, "
        f"{len(batch_for_briefing)} queued for briefing"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    check_new_whatsapp()
