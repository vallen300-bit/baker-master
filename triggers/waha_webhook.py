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

    # 0. Check for pending ClickUp plan interaction
    try:
        plan_action = ah.check_pending_plan(message_body, channel="whatsapp")
        if plan_action == "confirm":
            result = ah.execute_pending_plan(channel="whatsapp")
            _wa_reply(result)
            logger.info("WhatsApp action: ClickUp plan confirmed")
            return True
        elif plan_action and plan_action.startswith("revise:"):
            result = ah.revise_pending_plan(plan_action[7:], _get_retriever(), channel="whatsapp")
            _wa_reply(result)
            logger.info("WhatsApp action: ClickUp plan revised")
            return True
    except Exception as e:
        logger.warning(f"Pending plan check failed: {e}")

    # 1. Check for pending draft interaction (send/edit/dismiss)
    draft_action = ah.check_pending_draft(message_body)
    if draft_action == "confirm":
        result = ah.handle_confirmation()
        _wa_reply(result)
        logger.info(f"WhatsApp action: draft confirmed by Director")
        return True
    elif draft_action and draft_action.startswith("confirm_to:"):
        new_recipients = draft_action[11:]
        result = ah.handle_confirmation(recipient_override=new_recipients)
        _wa_reply(result)
        logger.info(f"WhatsApp action: draft confirmed with new recipients: {new_recipients}")
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

    elif intent_type == "fireflies_fetch":
        result = ah.handle_fireflies_fetch(
            message_body, _get_retriever(), channel="whatsapp",
        )
        _wa_reply(result)
        logger.info(f"WhatsApp action: Fireflies fetch processed")
        return True

    elif intent_type == "clickup_action":
        result = ah.handle_clickup_action(intent, _get_retriever(), channel="whatsapp")
        _wa_reply(result)
        logger.info(f"WhatsApp action: ClickUp action processed")
        return True

    elif intent_type == "clickup_fetch":
        result = ah.handle_clickup_fetch(message_body, _get_retriever(), channel="whatsapp")
        _wa_reply(result)
        logger.info(f"WhatsApp action: ClickUp fetch processed")
        return True

    elif intent_type == "clickup_plan":
        result = ah.handle_clickup_plan(message_body, _get_retriever(), channel="whatsapp")
        _wa_reply(result)
        logger.info(f"WhatsApp action: ClickUp plan processed")
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

    # --- Media handling: download and extract text from attachments ---
    media_text = ""
    if has_media:
        try:
            from triggers.waha_client import download_media_file, extract_media_text, is_extractable

            media = payload.get("media") or {}
            media_url = media.get("url", "")
            mimetype = media.get("mimetype", "")

            if media_url and is_extractable(mimetype):
                filepath = download_media_file(media_url)
                if filepath:
                    media_text = extract_media_text(filepath, mimetype)
                    if media_text:
                        logger.info(f"Extracted {len(media_text)} chars from WA media ({mimetype})")
        except Exception as e:
            logger.warning(f"WhatsApp media processing failed (continuing with text only): {e}")

    # Build combined body (text + media)
    body_parts = []
    if message_body:
        body_parts.append(message_body)
    if media_text:
        mimetype = (payload.get("media") or {}).get("mimetype", "attachment")
        body_parts.append(f"[Attachment ({mimetype}): {media_text}]")
    combined_body = "\n".join(body_parts)

    # ARCH-7: Store full WhatsApp message to PostgreSQL
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.store_whatsapp_message(
            msg_id=msg_id,
            sender=sender,
            sender_name=sender_name,
            chat_id=sender,
            full_text=combined_body,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None,
            is_director=(sender == DIRECTOR_WHATSAPP),
        )
    except Exception as _e:
        logger.warning(f"Failed to store WhatsApp msg {msg_id} to PostgreSQL (non-fatal): {_e}")

    # WHATSAPP-ACTION-1: Director messages → action detection first
    if sender == DIRECTOR_WHATSAPP and combined_body:
        try:
            handled = _handle_director_message(combined_body, msg_id, sender_name)
            if handled:
                return {"status": "action_processed", "sender": sender_name}
        except Exception as e:
            logger.error(f"WhatsApp action routing failed (falling through to pipeline): {e}")

    # Format and run pipeline (normal flow for non-Director or non-action messages)
    text = f"WhatsApp message from {sender_name}:\n[{datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()[:19]}] {sender_name}: {combined_body}"

    # DEADLINE-SYSTEM-1: Extract deadlines from WhatsApp messages (Director's only)
    if sender == DIRECTOR_WHATSAPP:
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=combined_body,
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
            "content": text,
            "contact_name": sender_name,
            "message_count": 1,
            "priority": trigger.priority,
        }])

    return {"status": "processed", "sender": sender_name}
