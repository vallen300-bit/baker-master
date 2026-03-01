"""
Webhook receiver for WAHA (WhatsApp HTTP API).
Replaces Wassenger polling with push-based message ingestion.
"""
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()
logger = logging.getLogger("sentinel.trigger.whatsapp")

@router.post("/api/webhook/whatsapp")
async def waha_webhook(
    request: Request,
    x_webhook_hmac: str = Header(None, alias="X-Webhook-Hmac"),
):
    body = await request.json()
    event_type = body.get("event")

    # Only process incoming messages (not our own outbound)
    if event_type != "message":
        return {"status": "ignored", "event": event_type}

    payload = body.get("payload", {})
    if payload.get("fromMe", False):
        return {"status": "ignored", "reason": "outbound"}

    # Extract message data
    sender = payload.get("from", "")
    sender_name = payload.get("_data", {}).get("notifyName", sender)
    message_body = payload.get("body", "")
    timestamp = payload.get("timestamp", 0)
    has_media = payload.get("hasMedia", False)
    msg_id = payload.get("id", "")

    if not message_body and not has_media:
        return {"status": "ignored", "reason": "empty"}

    logger.info(f"WhatsApp webhook: message from {sender_name} ({sender})")

    # Format and run pipeline (same pattern as old trigger)
    text = f"WhatsApp message from {sender_name}:\n[{datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()[:19]}] {sender_name}: {message_body}"

    # DEADLINE-SYSTEM-1: Extract deadlines from WhatsApp messages (Director's only)
    if sender == "41799605092@c.us":
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=message_body,
                source_type="whatsapp",
                source_id=f"wa-{msg_id}",
                sender_name=sender_name,
                sender_whatsapp=sender,
            )
        except Exception as _e:
            logger.debug(f"Deadline extraction failed for WA {msg_id}: {_e}")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()

    trigger = TriggerEvent(
        type="whatsapp",
        content=text,
        source_id=f"wa-{msg_id}",
        contact_name=sender_name,
    )
    trigger = pipeline.classify_trigger(trigger)

    if trigger.priority in ("high", "medium"):
        try:
            pipeline.run(trigger)
        except Exception as e:
            logger.error(f"WhatsApp webhook: pipeline failed for {sender_name}: {e}")
    else:
        from triggers.state import trigger_state
        trigger_state.add_to_briefing_queue([{
            "type": "whatsapp",
            "source_id": sender,
            "content": text[:500],
            "contact_name": sender_name,
            "message_count": 1,
            "priority": trigger.priority,
        }])

    return {"status": "processed", "sender": sender_name}
