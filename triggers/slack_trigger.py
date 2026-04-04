"""
Sentinel Trigger — Slack
Polls configured Slack channels every 5 minutes via slack_sdk WebClient.

Human messages are embedded to Qdrant baker-slack (silent ingest).
@Baker mentions additionally run the full Sentinel pipeline + S3 thread reply.

Called by scheduler every 5 minutes.

Pattern: follows rss_trigger.py structure (lazy imports, module-level entry point).

Requires: SLACK_BOT_TOKEN
Config:   SLACK_CHANNEL_IDS  (comma-separated channel IDs, default: C0AF4FVN3FB)
Optional: SLACK_BAKER_USER_ID (Baker's Slack user ID for @mention detection)

Deprecation check date: N/A — Slack API stable.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.slack_trigger")

# Module-level cache for user name lookups (avoids repeated API calls per process)
_user_name_cache: dict = {}


def _get_webclient():
    """Get a Slack WebClient authenticated with the bot token (lazy import)."""
    from slack_sdk import WebClient
    from config.settings import config
    return WebClient(token=config.slack.bot_token)


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _store_idea(text: str, source: str = 'slack'):
    """IDEAS-CAPTURE-1: Store a Director idea. Strip the 'Idea:' prefix."""
    import re as _re
    content = _re.sub(r'^idea[:\-\s]+', '', text, flags=_re.IGNORECASE).strip()
    if not content:
        return
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO ideas (content, source) VALUES (%s, %s)", (content, source))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Idea store failed: {e}")


def _resolve_user_name(client, user_id: str) -> str:
    """Resolve Slack user ID to display name. In-process cache to limit API calls."""
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        resp = client.users_info(user=user_id)
        if resp.get("ok"):
            profile = resp["user"].get("profile", {})
            name = (
                profile.get("real_name")
                or profile.get("display_name")
                or user_id
            )
            _user_name_cache[user_id] = name
            return name
    except Exception as e:
        logger.debug(f"Slack: could not resolve user {user_id}: {e}")
    _user_name_cache[user_id] = user_id
    return user_id


# -------------------------------------------------------
# Main poll entry point
# -------------------------------------------------------

def run_slack_poll():
    """Main entry point — called by scheduler every 5 minutes."""
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("slack"):
        return

    logger.info("Slack trigger: starting poll...")

    from config.settings import config

    if not config.slack.bot_token:
        logger.warning("SLACK_BOT_TOKEN not set — skipping Slack poll")
        return

    try:
        client = _get_webclient()
        store = _get_store()

        channels_polled = 0
        messages_ingested = 0
        messages_skipped = 0
        mentions_pipelined = 0

        for channel_id in config.slack.channel_ids:
            watermark_key = f"slack:{channel_id}"
            watermark = trigger_state.get_watermark(watermark_key)

            # Slack `oldest` is an exclusive lower bound (Unix timestamp string)
            oldest_ts = f"{watermark.timestamp():.6f}"

            try:
                resp = client.conversations_history(
                    channel=channel_id,
                    oldest=oldest_ts,
                    limit=200,
                )
            except Exception as e:
                logger.warning(f"Slack: error fetching history for channel {channel_id}: {e}")
                continue

            if not resp.get("ok"):
                logger.warning(
                    f"Slack: conversations_history failed for {channel_id}: {resp.get('error')}"
                )
                continue

            channels_polled += 1
            messages = resp.get("messages", [])

            if not messages:
                continue

            latest_ts_dt = watermark

            # Process oldest-first (messages come newest-first from API)
            for msg in reversed(messages):
                ts = msg.get("ts", "")
                if not ts:
                    continue

                # Skip bot messages, app messages, and Slack system events
                if msg.get("subtype") or msg.get("bot_id"):
                    messages_skipped += 1
                    continue

                user_id = msg.get("user", "")
                if not user_id:
                    messages_skipped += 1
                    continue

                text = (msg.get("text") or "").strip()
                if not text:
                    messages_skipped += 1
                    continue

                user_name = _resolve_user_name(client, user_id)
                source_id = f"slack:{channel_id}:{ts}"

                # 1. Silent ingest — embed every human message to Qdrant baker-slack
                _embed_message(store, channel_id, user_name, text, ts, config.slack.collection)

                # SLACK-STRUCTURED-1: Store to PostgreSQL for structured queries + Tier 2 enrichment
                try:
                    msg_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    store.store_slack_message(
                        msg_id=source_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        user_name=user_name,
                        full_text=text,
                        thread_ts=msg.get("thread_ts"),
                        received_at=msg_dt,
                    )
                except Exception as _se:
                    logger.debug(f"Slack PostgreSQL store failed (non-fatal): {_se}")

                # 2. @Baker mention — run full pipeline (S3 posts thread reply)
                baker_uid = config.slack.baker_bot_user_id
                is_mention = bool(baker_uid and f"<@{baker_uid}>" in text)

                if is_mention and not trigger_state.is_processed("slack", source_id):
                    # COST-OPT-WAVE1: Pre-mark as processed to prevent race condition
                    trigger_state.mark_processed("slack", source_id)

                    # LEARNING-LOOP: Check if this is feedback (short message after @Baker)
                    clean_text = text.replace(f"<@{baker_uid}>", "").strip() if baker_uid else text
                    if _is_slack_feedback(clean_text):
                        _handle_slack_feedback(clean_text, channel_id, ts, client)
                        continue

                    # SLACK-INTERACTIVE-1: Route Director messages through interactive scan_chat flow
                    if _is_director_user(user_name):
                        _handle_director_slack_message(
                            text=clean_text,
                            channel_id=channel_id,
                            thread_ts=ts,
                            user_name=user_name,
                            client=client,
                        )
                    else:
                        _feed_to_pipeline(
                            channel_id=channel_id,
                            ts=ts,
                            user_name=user_name,
                            text=text,
                            source_id=source_id,
                        )
                    mentions_pipelined += 1

                messages_ingested += 1

                # Advance local watermark tracker
                try:
                    msg_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    if msg_dt > latest_ts_dt:
                        latest_ts_dt = msg_dt
                except (ValueError, OSError):
                    pass

            # Persist watermark for this channel
            if latest_ts_dt > watermark:
                trigger_state.set_watermark(watermark_key, latest_ts_dt)

        # SLACK-THREAD-1: Also poll thread replies (Director replies in threads)
        thread_replies_found = 0
        for channel_id in config.slack.channel_ids:
            try:
                thread_replies_found += _poll_thread_replies(client, store, channel_id)
            except Exception as _te:
                logger.warning(f"Slack thread poll failed for {channel_id} (non-fatal): {_te}")

        report_success("slack")
        logger.info(
            f"Slack poll complete: {channels_polled} channels polled, "
            f"{messages_ingested} messages ingested, {messages_skipped} skipped, "
            f"{mentions_pipelined} mentions pipelined, "
            f"{thread_replies_found} thread replies found"
        )

    except Exception as e:
        report_failure("slack", str(e))
        logger.error(f"Slack poll failed: {e}")


# -------------------------------------------------------
# SLACK-THREAD-1: Thread reply polling
# -------------------------------------------------------

def _poll_thread_replies(client, store, channel_id: str) -> int:
    """Poll thread replies in recent threads.
    Director often replies in threads to Baker's posts — conversations_history
    only returns top-level messages, missing these replies entirely."""
    from config.settings import config

    thread_wm_key = f"slack_threads:{channel_id}"
    thread_watermark = trigger_state.get_watermark(thread_wm_key)

    # Fetch recent top-level messages to find threads with new replies
    try:
        resp = client.conversations_history(channel=channel_id, limit=50)
    except Exception as e:
        logger.debug(f"Slack thread poll: history fetch failed: {e}")
        return 0

    if not resp.get("ok"):
        return 0

    messages = resp.get("messages", [])
    replies_found = 0
    latest_reply_dt = thread_watermark

    for msg in messages:
        reply_count = msg.get("reply_count", 0)
        latest_reply = msg.get("latest_reply", "")

        if reply_count == 0 or not latest_reply:
            continue

        # Check if this thread has replies newer than our watermark
        try:
            latest_reply_ts = datetime.fromtimestamp(float(latest_reply), tz=timezone.utc)
        except (ValueError, OSError):
            continue

        if latest_reply_ts <= thread_watermark:
            continue

        # Fetch thread replies newer than watermark
        parent_ts = msg.get("ts", "")
        try:
            thread_resp = client.conversations_replies(
                channel=channel_id,
                ts=parent_ts,
                oldest=f"{thread_watermark.timestamp():.6f}",
                limit=50,
            )
        except Exception as e:
            logger.debug(f"Slack thread poll: replies fetch failed for {parent_ts}: {e}")
            continue

        if not thread_resp.get("ok"):
            continue

        for reply in thread_resp.get("messages", []):
            # Skip parent message itself
            if reply.get("ts") == parent_ts:
                continue
            # Skip bot/app messages
            if reply.get("bot_id") or reply.get("subtype"):
                continue

            user_id = reply.get("user", "")
            if not user_id:
                continue
            text = (reply.get("text") or "").strip()
            if not text:
                continue

            reply_ts = reply.get("ts", "")
            source_id = f"slack:{channel_id}:{reply_ts}"

            # Skip already processed
            if trigger_state.is_processed("slack", source_id):
                continue

            user_name = _resolve_user_name(client, user_id)

            # 1. Ingest to Qdrant
            _embed_message(store, channel_id, user_name, text, reply_ts, config.slack.collection)

            # 2. Store to PostgreSQL
            try:
                msg_dt = datetime.fromtimestamp(float(reply_ts), tz=timezone.utc)
                store.store_slack_message(
                    msg_id=source_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    user_name=user_name,
                    full_text=text,
                    thread_ts=parent_ts,
                    received_at=msg_dt,
                )
            except Exception:
                pass

            # 3. Route: @Baker mention or Director thread reply
            baker_uid = config.slack.baker_bot_user_id
            is_mention = bool(baker_uid and f"<@{baker_uid}>" in text)
            clean_text = text.replace(f"<@{baker_uid}>", "").strip() if baker_uid and is_mention else text

            trigger_state.mark_processed("slack", source_id)

            if _is_director_user(user_name):
                # Director thread replies always get handled (even without @Baker)
                _handle_director_slack_message(
                    text=clean_text,
                    channel_id=channel_id,
                    thread_ts=parent_ts,
                    user_name=user_name,
                    client=client,
                )
            elif is_mention:
                _feed_to_pipeline(
                    channel_id=channel_id,
                    ts=reply_ts,
                    user_name=user_name,
                    text=text,
                    source_id=source_id,
                )

            replies_found += 1

            # Track latest
            try:
                reply_dt = datetime.fromtimestamp(float(reply_ts), tz=timezone.utc)
                if reply_dt > latest_reply_dt:
                    latest_reply_dt = reply_dt
            except (ValueError, OSError):
                pass

    # Update thread watermark
    if latest_reply_dt > thread_watermark:
        trigger_state.set_watermark(thread_wm_key, latest_reply_dt)

    if replies_found:
        logger.info(f"SLACK-THREAD-1: found {replies_found} new thread replies in {channel_id}")

    return replies_found


# -------------------------------------------------------
# Qdrant embedding
# -------------------------------------------------------

def _embed_message(store, channel_id: str, user_name: str, text: str, ts: str, collection: str):
    """Embed Slack message into Qdrant baker-slack collection."""
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dt_str = ""
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            dt_str = dt.isoformat()
        except (ValueError, OSError):
            pass

        embed_text = f"[Slack] {user_name}: {text}".strip()

        metadata = {
            "source": "slack",
            "channel_id": channel_id,
            "user_name": user_name,
            "ts": ts,
            "timestamp": dt_str,
            "date": date_str,
            "content_type": "slack_message",
            "label": f"slack:{user_name[:60]}",
            "text": text,
        }

        store.store_document(embed_text, metadata, collection=collection)
    except Exception as e:
        logger.warning(f"Slack: failed to embed message ts={ts}: {e}")


# -------------------------------------------------------
# Pipeline feed (@Baker mentions only)
# -------------------------------------------------------

def _feed_to_pipeline(channel_id: str, ts: str, user_name: str, text: str, source_id: str):
    """Feed @Baker mention into Sentinel pipeline. S3 will post thread reply."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        content = (
            f"Channel: #{channel_id}\n"
            f"From: {user_name}\n"
            f"Message: {text}"
        )

        trigger = TriggerEvent(
            type="slack",
            content=content,
            source_id=source_id,
            contact_name=user_name,
            metadata={
                "channel_id": channel_id,
                "thread_ts": ts,
                "is_mention": True,
            },
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Slack: pipeline feed failed for message ts={ts}: {e}")


# -------------------------------------------------------
# SLACK-INTERACTIVE-1: Director identification
# -------------------------------------------------------

def _is_director_user(user_name: str) -> bool:
    """Check if the Slack user is the Director (Dimitry)."""
    name_lower = (user_name or "").lower()
    return "dimitry" in name_lower or "vallen" in name_lower


# -------------------------------------------------------
# SLACK-INTERACTIVE-1: Director interactive flow
# -------------------------------------------------------

def _handle_director_slack_message(text: str, channel_id: str, thread_ts: str,
                                    user_name: str, client):
    """
    Handle Director @Baker messages using the same interactive flow
    as WhatsApp and Dashboard (classify_intent → action handlers).
    """
    from orchestrator.action_handler import (
        classify_intent, check_pending_draft, check_pending_plan,
        handle_email_action, handle_whatsapp_action,
    )
    from memory.retriever import SentinelRetriever

    retriever = SentinelRetriever()

    # Step 1: Build conversation history from recent Slack messages
    conversation_history = ""
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT user_name, full_text FROM slack_messages
                    WHERE channel_id = %s
                    ORDER BY received_at DESC LIMIT 4
                """, (channel_id,))
                rows = cur.fetchall()
                cur.close()
                lines = []
                for uname, ftxt in reversed(rows):
                    role = "Director" if _is_director_user(uname) else "Baker"
                    lines.append(f"{role}: {ftxt}")
                conversation_history = "\n".join(lines) if lines else ""
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    # Step 2: Check pending draft/plan (same as WhatsApp/Dashboard)
    draft_response = check_pending_draft(text)
    if draft_response:
        _post_and_store_reply(client, channel_id, thread_ts, draft_response)
        return

    plan_response = check_pending_plan(text)
    if plan_response:
        _post_and_store_reply(client, channel_id, thread_ts, plan_response)
        return

    # IDEAS-CAPTURE-1: Detect idea prefix before intent classification
    if text.lower().startswith('idea:') or text.lower().startswith('idea -'):
        _store_idea(text, source='slack')
        _post_and_store_reply(client, channel_id, thread_ts, "Idea captured. You'll find it in the Ideas section on the dashboard.")
        return

    # Step 3: Enrich with alert context if this looks like a reply
    enriched_text = _enrich_with_alert_context(text, channel_id, thread_ts)

    # Step 4: Classify intent (same as scan_chat)
    intent = classify_intent(enriched_text, conversation_history=conversation_history)
    intent["original_question"] = enriched_text

    # Step 5: Route to appropriate handler
    intent_type = intent.get("type", "question")
    result = None

    try:
        if intent_type == "email_action":
            result = handle_email_action(intent, retriever, channel="slack",
                                         conversation_history=conversation_history)
        elif intent_type == "whatsapp_action":
            result = handle_whatsapp_action(intent, retriever, channel="slack",
                                             conversation_history=conversation_history)
        elif intent_type == "question" or intent_type == "capability_task":
            # General question or specialist — use agent loop (blocking)
            result = _run_scan_for_slack(enriched_text, retriever, conversation_history)
        else:
            # Other action types — feed through pipeline as fallback
            _feed_to_pipeline(
                channel_id=channel_id, ts=thread_ts,
                user_name=user_name, text=text,
                source_id=f"slack:{channel_id}:{thread_ts}",
            )
            return
    except Exception as e:
        logger.error(f"Slack interactive handler failed: {e}")
        result = f"Sorry, I encountered an error: {e}"

    if result:
        _post_and_store_reply(client, channel_id, thread_ts, result)

    # Store to conversation_memory
    try:
        store = _get_store()
        store.log_conversation(
            question=enriched_text,
            answer=result or "",
            answer_length=len(result or ""),
            project="general",
            owner="dimitry",
        )
    except Exception:
        pass


def _run_scan_for_slack(question: str, retriever, conversation_history: str) -> str:
    """Run a blocking agent loop for Slack (like WhatsApp's _handle_director_question)."""
    try:
        from orchestrator.agent import run_agent_loop
        from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt

        system_prompt = build_mode_aware_prompt(SCAN_SYSTEM_PROMPT, domain=None, mode="delegate")
        history = []
        if conversation_history:
            history.append({"role": "user", "content": conversation_history})

        result = run_agent_loop(
            question=question,
            system_prompt=system_prompt,
            history=history,
            max_iterations=5,
            timeout_override=30.0,
        )
        return result.answer or "I searched but couldn't find a clear answer."
    except Exception as e:
        logger.error(f"Slack agent loop failed: {e}")
        return f"Sorry, I encountered an error while researching: {e}"


# -------------------------------------------------------
# SLACK-INTERACTIVE-1: Alert context enrichment
# -------------------------------------------------------

def _enrich_with_alert_context(text: str, channel_id: str, thread_ts: str) -> str:
    """
    If the Director's message is short and looks like a reply to a Baker alert
    (e.g. "Please draft", "Run it", "Yes"), find the most recent Baker alert
    and prepend it as context.
    """
    if len(text) > 200:
        return text  # Long enough to be self-contained

    import re
    _reply_patterns = [
        r'(?i)^(please\s+)?(draft|run|do it|yes|go ahead|send|proceed|approve|execute)',
        r'(?i)^(ok|okay|sure|confirmed?|agreed)',
    ]
    is_reply = any(re.match(p, text.strip()) for p in _reply_patterns)
    if not is_reply:
        return text

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return text
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, body, structured_actions
                FROM alerts
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND status != 'dismissed'
                ORDER BY created_at DESC
                LIMIT 5
            """)
            recent_alerts = cur.fetchall()
            cur.close()

            if not recent_alerts:
                return text

            # Prefer alerts with draft/run actions
            best_alert = None
            for alert_id, title, body, actions in recent_alerts:
                if actions and ('draft' in str(actions).lower() or 'run' in str(actions).lower()):
                    best_alert = (alert_id, title, body)
                    break
            if not best_alert:
                best_alert = (recent_alerts[0][0], recent_alerts[0][1], recent_alerts[0][2])

            alert_id, alert_title, alert_body = best_alert
            enriched = (
                f"CONTEXT — This is a reply to Baker alert #{alert_id}: \"{alert_title}\"\n"
                f"Alert details: {(alert_body or '')[:500]}\n\n"
                f"Director's instruction: {text}"
            )
            logger.info(f"Enriched Slack reply with alert #{alert_id}: {(alert_title or '')[:60]}")
            return enriched
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Alert context enrichment failed: {e}")
        return text


# -------------------------------------------------------
# SLACK-INTERACTIVE-1: Post + store Baker's replies
# -------------------------------------------------------

def _post_and_store_reply(client, channel_id: str, thread_ts: str, text: str):
    """Post a thread reply to Slack AND store it in slack_messages for history."""
    import time as _time
    # Post to Slack
    try:
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)
    except Exception as e:
        logger.error(f"Slack reply post failed: {e}")
        return

    # Store Baker's reply in slack_messages for conversation history
    try:
        store = _get_store()
        store.store_slack_message(
            msg_id=f"slack:{channel_id}:baker_{int(_time.time())}",
            channel_id=channel_id,
            channel_name="",
            user_id="baker",
            user_name="Baker",
            full_text=text[:5000],
            thread_ts=thread_ts,
            received_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.warning(f"Failed to store Baker Slack reply: {e}")


# -------------------------------------------------------
# LEARNING-LOOP: Slack feedback detection
# -------------------------------------------------------

import re as _re

_SLACK_FB_POSITIVE = _re.compile(
    r"^(good|great|thanks|perfect|correct|exactly|yes)\s*$", _re.IGNORECASE
)
_SLACK_FB_NEGATIVE = _re.compile(
    r"^(wrong|no|bad|incorrect|not right|nein|falsch)\s*$", _re.IGNORECASE
)
_SLACK_FB_REVISE = _re.compile(
    r"^(revise|update|change|fix|adjust|anders|korrigier)\b", _re.IGNORECASE
)


def _is_slack_feedback(text: str) -> bool:
    """Check if @Baker message is short feedback rather than a question."""
    if len(text) > 100:
        return False
    return bool(
        _SLACK_FB_POSITIVE.match(text) or
        _SLACK_FB_NEGATIVE.match(text) or
        _SLACK_FB_REVISE.match(text)
    )


def _handle_slack_feedback(text: str, channel_id: str, ts: str, client):
    """Store feedback on the most recent baker_task and reply in thread."""
    if _SLACK_FB_POSITIVE.match(text):
        feedback = "accepted"
    elif _SLACK_FB_NEGATIVE.match(text):
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
                WHERE status = 'completed'
                  AND director_feedback IS NULL
                ORDER BY completed_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                task_id = row[0]
                store.update_baker_task(task_id, director_feedback=feedback, feedback_comment=text)
                logger.info(f"Slack feedback stored: task {task_id} = {feedback}")
                reply = f"Feedback noted: {feedback}. I'll adjust next time."
            else:
                reply = "No recent task found to apply feedback to."
            cur.close()
        finally:
            store._put_conn(conn)

        # Reply in thread
        try:
            client.chat_postMessage(channel=channel_id, text=reply, thread_ts=ts)
        except Exception as e:
            logger.warning(f"Slack feedback reply failed: {e}")
    except Exception as e:
        logger.warning(f"Slack feedback storage failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_slack_poll()
