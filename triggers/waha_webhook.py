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
import re
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Header, Request

router = APIRouter()
logger = logging.getLogger("sentinel.trigger.whatsapp")

# LEARNING-LOOP: WhatsApp feedback keywords
_WA_FEEDBACK_POSITIVE = re.compile(
    r"^(good|great|thanks|perfect|correct|exactly|yes)\s*$", re.IGNORECASE
)
_WA_FEEDBACK_NEGATIVE = re.compile(
    r"^(wrong|no|bad|incorrect|not right|nein|falsch)\s*$", re.IGNORECASE
)
_WA_FEEDBACK_REVISE = re.compile(
    r"^(revise|update|change|fix|adjust|anders|korrigier)\b", re.IGNORECASE
)

DIRECTOR_WHATSAPP = "41799605092@c.us"

# MEETINGS-DETECT-3: Fast regex pre-filter for meeting WhatsApp messages
_MEETING_WA_RE = re.compile(
    r'(?:meeting|call|zoom|teams|lunch|dinner|coffee|breakfast|'
    r'catch-up|sync|sit-down|appointment|conference|'
    r"let'?s meet|see you at|confirmed for|'ll meet|"
    r'looking forward to|propose a meeting|schedule a call|'
    r'book a time|set up a meeting|'
    r'tomorrow at \d|today at \d|\d{1,2}:\d{2}\s*(?:am|pm)?)',
    re.IGNORECASE
)


def _is_meeting_whatsapp(body: str) -> bool:
    """MEETINGS-DETECT-3: Fast regex check — no API cost."""
    return bool(_MEETING_WA_RE.search((body or "")[:1000]))


def _extract_meeting_from_whatsapp(body: str, sender_name: str, chat_name: str):
    """MEETINGS-DETECT-3: One Haiku call to extract meeting details from WhatsApp."""
    import json
    import anthropic
    from config.settings import config
    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        today = datetime.now().strftime('%Y-%m-%d')
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": f"""Extract meeting details from this WhatsApp message. If NOT about a specific meeting, return {{"is_meeting": false}}.

From: {sender_name} (chat: {chat_name})
Message: {body[:1500]}

Today's date is {today}.

Return JSON only (no markdown):
{{
  "is_meeting": true,
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD or null",
  "time": "HH:MM or descriptive or null",
  "location": "place or null",
  "status": "confirmed or proposed"
}}

Status: "confirmed" if definite ("see you", "confirmed", "booked"). "proposed" if suggesting."""}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="meeting_wa_detect")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"MEETINGS-DETECT-3: Haiku extraction failed: {e}")
        return None


def _wa_reply(text: str):
    """Send a reply to the Director on WhatsApp. Non-fatal on error."""
    try:
        from outputs.whatsapp_sender import send_whatsapp
        send_whatsapp(text)
    except Exception as e:
        logger.warning(f"WhatsApp reply failed: {e}")


def _is_wa_feedback(text: str) -> bool:
    """Check if message looks like feedback (short, keyword match)."""
    if len(text) > 100:
        return False
    return bool(
        _WA_FEEDBACK_POSITIVE.match(text) or
        _WA_FEEDBACK_NEGATIVE.match(text) or
        _WA_FEEDBACK_REVISE.match(text)
    )


def _handle_wa_feedback(text: str):
    """Store feedback on the most recent baker_task from WhatsApp."""
    if _WA_FEEDBACK_POSITIVE.match(text):
        feedback = "accepted"
    elif _WA_FEEDBACK_NEGATIVE.match(text):
        feedback = "rejected"
    else:
        feedback = "revised"

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM baker_tasks
                WHERE channel = 'whatsapp'
                  AND status = 'completed'
                  AND director_feedback IS NULL
                ORDER BY completed_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                task_id = row[0]
                store.update_baker_task(task_id, director_feedback=feedback, feedback_comment=text)
                logger.info(f"WA feedback stored: task {task_id} = {feedback}")
                _wa_reply(f"Feedback noted: {feedback}. I'll adjust next time.")
            else:
                _wa_reply("No recent task found to apply feedback to.")
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"WA feedback storage failed: {e}")


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


def _handle_director_question(question: str, msg_id: str, scored: dict = None,
                               intent: dict = None):
    """
    WA-QUESTION-1 + STEP1C: Answer a Director question using Scan-style RAG.

    Mode+tier routing: delegate forces agentic path with more iterations.
    All paths create a baker_task for tracking.
    """
    start = time.time()

    from orchestrator.agent import is_agentic_rag_enabled

    _tier = scored.get("tier", 3) if scored else 3
    _mode = scored.get("mode", "escalate") if scored else "escalate"
    _domain = scored.get("domain", "projects") if scored else "projects"

    # Create baker_task (non-fatal)
    _task_id = None
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        _task_id = store.create_baker_task(
            domain=_domain,
            urgency_score=scored.get("urgency_score") if scored else None,
            tier=_tier, mode=_mode, task_type="question",
            title=question[:200], description=question,
            sender="director", source="whatsapp", channel="whatsapp",
            status="in_progress",
        )
        # COMPLEXITY-ROUTER-1: Store complexity classification (shadow mode)
        if _task_id and intent:
            store.update_baker_task(
                _task_id,
                complexity=intent.get("complexity", "deep"),
                complexity_confidence=intent.get("complexity_confidence"),
                complexity_reasoning=intent.get("complexity_reasoning"),
            )
    except Exception:
        pass

    # AGENT-FRAMEWORK-1: Try capability routing first
    answer = None
    try:
        from orchestrator.capability_router import CapabilityRouter
        from orchestrator.capability_runner import CapabilityRunner
        _cap_plan = CapabilityRouter().route(question, _domain, _mode, scored)
        if _cap_plan and _cap_plan.capabilities:
            cap_slugs = [c.slug for c in _cap_plan.capabilities]
            logger.info(f"WA capability routing: mode={_cap_plan.mode}, caps={cap_slugs}")
            runner = CapabilityRunner()
            _complexity = intent.get("complexity") if intent else None
            if _cap_plan.mode == "fast":
                result = runner.run_single(_cap_plan.capabilities[0], question,
                                           domain=_domain, mode=_mode,
                                           complexity=_complexity)
            else:
                result = runner.run_multi(_cap_plan, question,
                                          domain=_domain, mode=_mode)
            if result and result.answer:
                answer = result.answer
                # Log capability run
                try:
                    import json as _json
                    from memory.store_back import SentinelStoreBack
                    store = SentinelStoreBack._get_global_instance()
                    store.insert_capability_run(
                        baker_task_id=_task_id, capability_slug=cap_slugs[0],
                        sub_task=question[:500], status="completed",
                    )
                    if _task_id:
                        store.update_baker_task(
                            _task_id, capability_slugs=_json.dumps(cap_slugs),
                            agent_iterations=result.iterations,
                            agent_elapsed_ms=result.elapsed_ms,
                        )
                except Exception:
                    pass
    except Exception as _cap_e:
        logger.warning(f"WA capability routing failed (non-fatal): {_cap_e}")

    # Fallback: agentic by default for quality (INTELLIGENCE-GAP-1)
    # T1 keeps legacy for speed (~3s WhatsApp reply)
    if not answer:
        if _tier == 1 and _mode != "delegate":
            logger.info("WA question: Tier 1 — forcing legacy path for speed")
            answer = _handle_director_question_legacy(question, start, mode=_mode, domain=_domain)
        else:
            answer = _handle_director_question_agentic(question, start, mode=_mode, domain=_domain)

    if not answer:
        return  # error already handled inside the helper

    # --- Send reply ---
    _wa_reply(answer)
    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(f"WA question answered: {elapsed_ms}ms, {len(answer)} chars")

    # Close baker_task (non-fatal)
    if _task_id:
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.update_baker_task(_task_id, status="completed",
                                   deliverable=answer[:5000])
        except Exception:
            pass

    # --- Store-back (fire-and-forget) ---
    _wa_store_back(question, answer)


def _handle_director_question_agentic(question: str, start: float,
                                      mode: str = None, domain: str = None) -> str:
    """Agent loop path for WhatsApp questions. STEP1C: mode-aware prompt."""
    from orchestrator.agent import run_agent_loop
    from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt
    from config.settings import config

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Deadlines (lightweight — always included)
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

    base_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n"
        f"## CURRENT TIME\n{now}\n"
        f"{deadline_block}\n\n"
        f"## CHANNEL\n"
        f"You are replying on WhatsApp. Keep your answer concise — 2-3 short paragraphs max.\n"
        f"No markdown headers or bullet formatting. Use *bold* sparingly (WhatsApp supports it).\n"
        f"No document blocks. No numbered lists longer than 5 items.\n"
    )
    # RICHER-CONTEXT-1: inject entity context (people + matters mentioned)
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode, question=question)

    # Fetch recent conversation history for context
    _history = []
    try:
        from memory.store_back import SentinelStoreBack
        _store = SentinelStoreBack._get_global_instance()
        _recent = _store.get_recent_conversations(limit=10)
        for turn in reversed(_recent or []):
            q = (turn.get("question") or "")[:300]
            a = (turn.get("answer") or "")[:500]
            if q:
                _history.append({"role": "user", "content": q})
            if a:
                _history.append({"role": "assistant", "content": a})
    except Exception:
        pass

    # WhatsApp agent: 5 iterations / 45s default, delegate gets more
    _max_iter = 7 if mode == "delegate" else 5
    _timeout = 60.0 if mode == "delegate" else 45.0

    try:
        result = run_agent_loop(
            question=question,
            system_prompt=system_prompt,
            history=_history,
            max_iterations=_max_iter,
            timeout_override=_timeout,
        )
        logger.info(
            f"AGENTIC-RAG WA: {result.iterations} iterations, "
            f"{len(result.tool_calls)} tools, "
            f"{result.total_input_tokens}+{result.total_output_tokens} tokens, "
            f"{result.elapsed_ms}ms"
        )

        if result.timed_out or not result.answer:
            logger.warning("Agent timed out on WhatsApp — falling back to legacy")
            return _handle_director_question_legacy(question, start, mode=mode, domain=domain)

        return result.answer
    except Exception as e:
        logger.error(f"Agentic WA question failed, falling back to legacy: {e}")
        return _handle_director_question_legacy(question, start, mode=mode, domain=domain)


def _handle_director_question_legacy(question: str, start: float,
                                     mode: str = None, domain: str = None) -> str:
    """Legacy single-pass RAG path for WhatsApp questions."""
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

    # --- 2. Build system prompt (STEP1C: mode-aware) ---
    from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt
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

    base_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n"
        f"## CURRENT TIME\n{now}\n\n"
        f"## RETRIEVED CONTEXT\n{context_block}"
        f"{deadline_block}\n\n"
        f"## CHANNEL\n"
        f"You are replying on WhatsApp. Keep your answer concise — 2-3 short paragraphs max.\n"
        f"No markdown headers or bullet formatting. Use *bold* sparingly (WhatsApp supports it).\n"
        f"No document blocks. No numbered lists longer than 5 items.\n"
    )
    # RICHER-CONTEXT-1: inject entity context (people + matters mentioned)
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode, question=question)

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
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(config.claude.model, response.usage.input_tokens, response.usage.output_tokens, source="wa_question")
        except Exception:
            pass
        return response.content[0].text
    except Exception as e:
        logger.error(f"WA question: Claude call failed: {e}")
        _wa_reply("Sorry, I couldn't process that right now. Try again in a moment.")
        return ""


def _wa_store_back(question: str, answer: str):
    """Store-back logic for WhatsApp questions (shared by both paths)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        store.log_decision(
            decision=f"WA question: {question[:100]}",
            reasoning=answer[:500],
            confidence="medium",
            trigger_type="whatsapp_question",
        )

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

    # LEARNING-LOOP: Check if this is feedback on the last baker_task
    if _is_wa_feedback(message_body):
        _handle_wa_feedback(message_body)
        return True

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
        intent["original_question"] = combined_body  # pass full text for phone extraction
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

    elif intent_type in ("vip_action", "contact_action"):
        result = ah.handle_vip_action(intent)
        _wa_reply(result)
        logger.info(f"WhatsApp action: contact action processed")
        return True

    elif intent_type == "meeting_declaration":
        result = ah.handle_meeting_declaration(message_body, channel="whatsapp")
        _wa_reply(result)
        logger.info(f"WhatsApp action: meeting declaration processed")
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

    # 3. Not an action — fall through to normal pipeline.
    # COMPLEXITY-ROUTER-1: Return intent dict so complexity can be stored on baker_task.
    return intent


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
                    # Clean up temp file to prevent /tmp accumulation
                    try:
                        import os
                        os.unlink(filepath)
                    except OSError:
                        pass
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

    # INTERACTION-PIPELINE-1: Record contact interaction from WhatsApp
    try:
        from memory.store_back import SentinelStoreBack
        _store_ip = SentinelStoreBack._get_global_instance()
        _is_dir = (sender == DIRECTOR_WHATSAPP)
        _cid = _store_ip.match_contact_by_name(
            name=sender_name or "",
            whatsapp_id=sender,
        )
        if _cid and not _is_dir:  # Don't record Director's own messages as contact interactions
            _wa_ts = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None
            _store_ip.record_interaction(
                contact_id=_cid, channel="whatsapp", direction="inbound",
                timestamp=_wa_ts,
                subject=(combined_body[:200] if combined_body else None),
                source_ref=f"wa:{msg_id}",
            )
    except Exception:
        pass  # Non-fatal

    # TRIP-INTELLIGENCE-1: Auto-link to active trip if content mentions destination
    try:
        from memory.store_back import SentinelStoreBack
        _store_tc = SentinelStoreBack._get_global_instance()
        _wa_ts2 = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else None
        _store_tc.link_to_trip_context(
            content=combined_body[:500] if combined_body else "",
            source_type="whatsapp", source_ref=f"wa:{msg_id}",
            timestamp=_wa_ts2,
        )
    except Exception:
        pass

    # Auto-create contact for every WhatsApp sender (WhatsApp = real people, no spam)
    if sender and sender != DIRECTOR_WHATSAPP and sender_name:
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _conn = _store._get_conn()
            if _conn:
                try:
                    _cur = _conn.cursor()
                    # Only insert if this whatsapp_id doesn't exist yet
                    _cur.execute(
                        "SELECT id FROM vip_contacts WHERE whatsapp_id = %s LIMIT 1",
                        (sender,),
                    )
                    if not _cur.fetchone():
                        _cur.execute(
                            """INSERT INTO vip_contacts (name, whatsapp_id, communication_pref, created_at)
                               VALUES (%s, %s, 'whatsapp', NOW())""",
                            (sender_name, sender),
                        )
                        _conn.commit()
                        logger.info(f"Auto-created contact from WhatsApp: {sender_name} ({sender})")
                    _cur.close()
                finally:
                    _store._put_conn(_conn)
        except Exception as _ce:
            logger.debug(f"Auto-contact creation failed (non-fatal): {_ce}")

    # MEETINGS-DETECT-3: Check ALL WhatsApp messages for meeting content
    # Runs for Director AND non-Director. Dedup in insert_detected_meeting() prevents doubles.
    try:
        if combined_body and _is_meeting_whatsapp(combined_body):
            _wa_meeting = _extract_meeting_from_whatsapp(combined_body, sender_name, sender_name)
            if _wa_meeting and _wa_meeting.get("is_meeting") and _wa_meeting.get("date"):
                from memory.store_back import SentinelStoreBack
                _mstore = SentinelStoreBack._get_global_instance()
                _parsed_mdate = None
                try:
                    _parsed_mdate = datetime.strptime(_wa_meeting["date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass
                if _parsed_mdate:
                    _mstore.insert_detected_meeting(
                        title=_wa_meeting.get("title", "Meeting"),
                        participant_names=_wa_meeting.get("participants", []),
                        meeting_date=_parsed_mdate,
                        meeting_time=_wa_meeting.get("time"),
                        location=_wa_meeting.get("location"),
                        status=_wa_meeting.get("status", "proposed"),
                        source="whatsapp",
                        source_ref=f"wa:{msg_id}",
                        raw_text=f"From: {sender_name}\n{combined_body[:500]}",
                    )
                    logger.info(f"MEETINGS-DETECT-3: meeting from WhatsApp: {_wa_meeting.get('title', '')[:60]}")
    except Exception as _me:
        logger.warning(f"MEETINGS-DETECT-3: WhatsApp meeting detection failed (non-fatal): {_me}")

    # DECISION-ENGINE-1A: Score trigger (no LLM fallback for webhook latency)
    _scored = None
    try:
        from orchestrator.decision_engine import score_trigger
        _scored = score_trigger(combined_body, sender_name, "whatsapp", {}, allow_llm=False)
        logger.info(
            f"Decision Engine (WA): domain={_scored['domain']} score={_scored['urgency_score']} "
            f"tier={_scored['tier']} mode={_scored['mode']}"
        )
    except Exception as _e:
        logger.warning(f"Decision Engine scoring failed (non-fatal): {_e}")

    # WHATSAPP-ACTION-1: Director messages → action detection first
    _wa_intent = None
    if sender == DIRECTOR_WHATSAPP and combined_body:
        try:
            handled = _handle_director_message(combined_body, msg_id, sender_name)
            if handled is True:
                return {"status": "action_processed", "sender": sender_name}
            # COMPLEXITY-ROUTER-1: handled is the intent dict (question type)
            if isinstance(handled, dict):
                _wa_intent = handled
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
            _handle_director_question(combined_body, msg_id, scored=_scored,
                                       intent=_wa_intent)
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

    # DECISION-ENGINE-1A: Use scored tier for routing
    # Tier convention: 1=most urgent, 3=least urgent. Tier <= 2 → run pipeline.
    run_pipeline = False
    if _scored and _scored.get("tier", 3) <= 2:
        run_pipeline = True
    elif trigger.priority in ("high", "medium"):
        run_pipeline = True  # fallback to old heuristic if scoring failed

    if run_pipeline:
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

    # ART-1: Check if this message contains research-worthy intelligence
    # Content-driven (not tier-driven) — regex pre-filter + Haiku classification
    try:
        from orchestrator.research_trigger import check_research_trigger
        check_research_trigger(combined_body, sender_name, msg_id)
    except Exception as _rt_e:
        logger.debug(f"Research trigger check failed (non-fatal): {_rt_e}")

    return {"status": "processed", "sender": sender_name}
