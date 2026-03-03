"""
Webhook receiver for WAHA (WhatsApp HTTP API).
Replaces Wassenger polling with push-based message ingestion.

WHATSAPP-ACTION-1: Director messages (41799605092@c.us) are checked for
action intent before pipeline routing. Email, deadline, and VIP actions
are executed and confirmed on WhatsApp. Non-action messages fall through
to the normal pipeline.

WA-QUESTION-1: Director questions (intent == "question") get a
conversational reply using the same Scan-style RAG flow (retrieval →
SCAN_SYSTEM_PROMPT → Claude → WhatsApp reply + store-back).
"""
import logging
import time
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


def _format_wa_context(contexts) -> str:
    """Format retrieved contexts into a compact block for the WhatsApp prompt.
    Mirrors _format_scan_context() from dashboard.py."""
    if not contexts:
        return "[No relevant context found in memory]"

    sections = {}
    for ctx in contexts:
        source = ctx.source.upper()
        if source not in sections:
            sections[source] = []
        sections[source].append(ctx)

    blocks = []
    for source, items in sections.items():
        blocks.append(f"\n--- {source} ({len(items)} items) ---")
        for item in items:
            label = item.metadata.get("label", "unknown")
            date_str = item.metadata.get("date", "")
            meta = f" [{date_str}]" if date_str else ""
            blocks.append(f"[{source}] {label}{meta}: {item.content[:600]}")

    return "\n".join(blocks)


def _handle_director_question(question: str, msg_id: str):
    """
    WA-QUESTION-1: Answer a Director question using the Scan-style RAG flow.
    Retrieves context from Qdrant + PostgreSQL, calls Claude, replies on
    WhatsApp, and stores the interaction back to memory.
    """
    start = time.time()

    # --- 1. Retrieve context (Qdrant vectors) ---
    try:
        retriever = _get_retriever()
        contexts = retriever.search_all_collections(
            query=question,
            limit_per_collection=8,
            score_threshold=0.3,
        )
        logger.info(f"WA question: retrieved {len(contexts)} Qdrant contexts")
    except Exception as e:
        logger.error(f"WA question retrieval failed: {e}")
        contexts = []

    # --- 1b. Meeting transcripts from PostgreSQL ---
    try:
        retriever = _get_retriever()
        transcripts = retriever.get_meeting_transcripts(question, limit=3)
        if transcripts:
            contexts.extend(transcripts)
        recent = retriever.get_recent_meeting_transcripts(limit=3)
        existing_ids = {c.metadata.get("meeting_id") for c in transcripts}
        for r in recent:
            if r.metadata.get("meeting_id") not in existing_ids:
                contexts.append(r)
    except Exception as e:
        logger.warning(f"WA question: transcript retrieval failed (non-fatal): {e}")

    # --- 1c. Emails + WhatsApp from PostgreSQL ---
    try:
        retriever = _get_retriever()
        emails = retriever.get_email_messages(question, limit=3)
        if emails:
            contexts.extend(emails)
        recent_emails = retriever.get_recent_emails(limit=3)
        existing_eids = {c.metadata.get("message_id") for c in emails}
        for r in recent_emails:
            if r.metadata.get("message_id") not in existing_eids:
                contexts.append(r)

        wa_msgs = retriever.get_whatsapp_messages(question, limit=3)
        if wa_msgs:
            contexts.extend(wa_msgs)
        recent_wa = retriever.get_recent_whatsapp(limit=3)
        existing_wids = {c.metadata.get("msg_id") for c in wa_msgs}
        for r in recent_wa:
            if r.metadata.get("msg_id") not in existing_wids:
                contexts.append(r)
    except Exception as e:
        logger.warning(f"WA question: email/WA retrieval failed (non-fatal): {e}")

    # --- 2. Build system prompt ---
    from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT
    from config.settings import config

    context_block = _format_wa_context(contexts)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Deadlines
    deadline_block = ""
    try:
        from models.deadlines import get_active_deadlines
        deadlines = get_active_deadlines(limit=15)
        if deadlines:
            dl_lines = []
            for dl in deadlines:
                due = dl.get("due_date")
                due_str = due.strftime("%Y-%m-%d") if due else "TBD"
                priority = dl.get("priority", "normal")
                status = dl.get("status", "active")
                desc = dl.get("description", "")
                dl_lines.append(f"- [{priority.upper()}] {due_str}: {desc} ({status})")
            deadline_block = "\n\n## ACTIVE DEADLINES\n" + "\n".join(dl_lines)
    except Exception:
        pass

    system_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n"
        f"## CURRENT TIME\n{now}\n\n"
        f"## RETRIEVED CONTEXT\n{context_block}"
        f"{deadline_block}\n\n"
        f"## CHANNEL\n"
        f"You are replying on WhatsApp. Keep your answer concise — 2-3 short paragraphs max.\n"
        f"No markdown headers or bullet formatting. Use *bold* sparingly (WhatsApp supports it).\n"
        f"No document blocks. No numbered lists longer than 5 items.\n"
    )

    # --- 3. Call Claude (non-streaming, WhatsApp doesn't support SSE) ---
    try:
        import anthropic
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        response = claude.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )
        answer = response.content[0].text
    except Exception as e:
        logger.error(f"WA question: Claude call failed: {e}")
        _wa_reply("Sorry, I couldn't process that right now. Try again in a moment.")
        return

    # --- 4. Send reply ---
    _wa_reply(answer)
    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(f"WA question answered: {elapsed_ms}ms, {len(answer)} chars")

    # --- 5. Store-back (fire-and-forget) ---
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        # 5a. Log decision
        store.log_decision(
            decision=f"WA question: {question[:100]}",
            reasoning=answer[:500],
            confidence="medium",
            trigger_type="whatsapp_question",
        )

        # 5b. Store Q+A to Qdrant for conversation memory (CONV-MEM-1)
        conversation_content = (
            f"[CONVERSATION]\n"
            f"Question (WhatsApp): {question}\n\n"
            f"Answer: {answer}"
        )
        conv_metadata = {
            "type": "conversation",
            "source": "whatsapp_question",
            "question": question[:500],
            "project": "general",
            "role": "ceo",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "answer_length": len(answer),
        }
        store.store_document(
            content=conversation_content,
            metadata=conv_metadata,
            collection="baker-conversations",
        )

        # 5c. Log to conversation_memory table
        store.log_conversation(
            question=question,
            answer=answer,
            answer_length=len(answer),
            project="general",
            chunk_count=1,
        )
    except Exception as e:
        logger.warning(f"WA question store-back failed (non-fatal): {e}")


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

    # 2. Classify intent (with short-term memory for reference resolution)
    _conv_history = ""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        recent_turns = store.get_recent_conversations(limit=15)
        if recent_turns:
            lines = []
            for turn in reversed(recent_turns):
                q = (turn.get("question") or "")[:200]
                a = (turn.get("answer") or "")[:300]
                lines.append(f"Director: {q}")
                if a:
                    lines.append(f"Baker: {a}")
            _conv_history = "\n".join(lines)
    except Exception:
        pass

    intent = ah.classify_intent(message_body, conversation_history=_conv_history)
    intent_type = intent.get("type", "question")

    if intent_type == "email_action":
        result = ah.handle_email_action(
            intent, _get_retriever(), channel="whatsapp",
        )
        _wa_reply(result)
        logger.info(f"WhatsApp action: email action processed")
        return True

    elif intent_type == "whatsapp_action":
        result = ah.handle_whatsapp_action(
            intent, _get_retriever(), channel="whatsapp",
            conversation_history=_conv_history,
        )
        _wa_reply(result)
        logger.info(f"WhatsApp action: whatsapp send processed")
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
            logger.error(f"WhatsApp action routing failed (falling through to question handler): {e}")

        # DEADLINE-SYSTEM-1: Extract deadlines from Director messages
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

        # WA-QUESTION-1: Director question — conversational reply via Scan-style RAG
        try:
            _handle_director_question(combined_body, msg_id)
            return {"status": "question_answered", "sender": sender_name}
        except Exception as e:
            logger.error(f"WA question handler failed: {e}")
            return {"status": "error", "sender": sender_name}

    # Non-Director messages: background intelligence via pipeline (no reply)
    text = f"WhatsApp message from {sender_name}:\n[{datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()[:19]}] {sender_name}: {combined_body}"

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
