"""
Webhook receiver for WAHA (WhatsApp HTTP API).
Replaces Wassenger polling with push-based message ingestion.

WHATSAPP-ACTION-1: Director messages (41799605092@c.us) are checked for
action intent before pipeline routing. Email, deadline, and VIP actions
are executed and confirmed on WhatsApp. Non-action messages fall through
to the normal pipeline.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Header, Request

router = APIRouter()
logger = logging.getLogger("sentinel.trigger.whatsapp")

DIRECTOR_WHATSAPP = "41799605092@c.us"


def _wa_reply(text: str):
    """Send a reply to the Director on WhatsApp. Non-fatal on error."""
    try:
        from outputs.whatsapp_sender import send_whatsapp
        send_whatsapp(text)
    except Exception as e:
        logger.warning(f"WhatsApp reply failed: {e}")


def _get_retriever():
    """Lazy-initialize the retriever for RAG-based email body generation."""
    from memory.retriever import SentinelRetriever
    return SentinelRetriever()


def _handle_director_message(message_body: str, msg_id: str, sender_name: str) -> bool:
    """
    WHATSAPP-ACTION-1: Process a Director message for action intent.
    Returns True if the message was handled as an action, False to fall through
    to the normal pipeline.
    """
    import orchestrator.action_handler as ah

    # 1. Check for pending draft interaction (send/edit/dismiss)
    draft_action = ah.check_pending_draft(message_body)
    if draft_action == "confirm":
        result = ah.handle_confirmation()
        _wa_reply(result)
        logger.info(f"WhatsApp action: draft confirmed by Director")
        return True
    elif draft_action and draft_action.startswith("edit:"):
        instruction = draft_action[5:]
        result = ah.handle_edit(instruction, _get_retriever())
        _wa_reply(result)
        logger.info(f"WhatsApp action: draft edit requested")
        return True
    elif draft_action == "dismiss":
        # Draft was dismissed by unrelated input — fall through to intent check
        pass

    # 2. Classify intent
    intent = ah.classify_intent(message_body)
    intent_type = intent.get("type", "question")

    if intent_type == "email_action":
        result = ah.handle_email_action(
            intent, _get_retriever(), channel="whatsapp",
        )
        _wa_reply(result)
        logger.info(f"WhatsApp action: email action processed")
        return True

    elif intent_type == "deadline_action":
        result = ah.handle_deadline_action(intent)
        _wa_reply(result)
        logger.info(f"WhatsApp action: deadline action processed")
        return True

    elif intent_type == "vip_action":
        result = ah.handle_vip_action(intent)
        _wa_reply(result)
        logger.info(f"WhatsApp action: VIP action processed")
        return True

    # 3. Not an action — fall through to normal pipeline
    return False


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

    # WHATSAPP-ACTION-1: Director messages → action detection first
    if sender == DIRECTOR_WHATSAPP and message_body:
        try:
            handled = _handle_director_message(message_body, msg_id, sender_name)
            if handled:
                return {"status": "action_processed", "sender": sender_name}
        except Exception as e:
            logger.error(f"WhatsApp action routing failed (falling through to pipeline): {e}")

    # Format and run pipeline (normal flow for non-Director or non-action messages)
    text = f"WhatsApp message from {sender_name}:\n[{datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()[:19]}] {sender_name}: {message_body}"

    # DEADLINE-SYSTEM-1: Extract deadlines from WhatsApp messages (Director's only)
    if sender == DIRECTOR_WHATSAPP:
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
