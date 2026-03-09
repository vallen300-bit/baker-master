"""
Sentinel Trigger — Email (Gmail)
Polls Gmail for new threads and fires pipeline for substantive ones.
Called by scheduler every 5 minutes.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config
from triggers.state import trigger_state

logger = logging.getLogger("sentinel.trigger.email")

# ALERT-DEDUP-1: Track last gap alert to avoid firing every 5 min
_last_gap_alert_time: float = 0.0
_GAP_ALERT_COOLDOWN = 24 * 3600  # 24 hours between gap alerts

# Gmail 429 backoff: skip polls until this timestamp (epoch seconds)
_gmail_retry_after: float = 0.0
_gmail_backoff_seconds: float = 0.0  # exponential backoff tracker

# Sentinel health monitoring
from triggers.sentinel_health import report_success as _health_success, report_failure as _health_failure


def _get_gmail_service():
    """Authenticate and return Gmail API service object."""
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build
    creds = authenticate()
    return build("gmail", "v1", credentials=creds)


def poll_gmail() -> list:
    """
    Poll Gmail for new threads since last watermark.
    Returns list of {text, metadata} dicts.
    Reuses extract_gmail.py's poll logic.
    """
    from scripts import extract_gmail
    service = _get_gmail_service()
    # ARCH-6: Set Gmail service so format_thread() can extract attachments
    extract_gmail._gmail_service = service
    return extract_gmail.extract_poll(service)


# -------------------------------------------------------
# Phase 3C: Commitment extraction from emails
# -------------------------------------------------------

_EMAIL_COMMITMENT_PROMPT = """You are Baker. Extract commitments from this email.

Look for:
- Promises made BY the sender: "I'll send...", "We'll provide...", "Attached is..."
- Requests TO the Director: "Please review...", "Could you approve...", "We need your..."
- Deadlines mentioned: "by Friday", "before end of month", "within 5 business days"

Return ONLY valid JSON:
{"commitments": [
    {"description": "...", "assigned_to": "sender_name or director", "due_date": "YYYY-MM-DD or null", "urgency": "high|medium|low"}
]}

If no clear commitments found, return {"commitments": []}
"""


def _extract_commitments_from_email(email_text: str, subject: str,
                                     sender: str, source_id: str):
    """Extract commitments from an email using Haiku. Fault-tolerant."""
    import json
    import anthropic
    from memory.store_back import SentinelStoreBack

    if not email_text or len(email_text.strip()) < 30:
        return

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=_EMAIL_COMMITMENT_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Today: {today}\nSubject: {subject}\nFrom: {sender}\n\n{email_text[:4000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="email_commitments")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        parsed = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Commitment extraction failed for email {source_id}: {e}")
        return

    commitments = parsed.get("commitments", [])
    if not commitments:
        return

    store = SentinelStoreBack._get_global_instance()
    inserted = 0
    for c in commitments:
        desc = (c.get("description") or "").strip()
        if not desc:
            continue
        due_date = c.get("due_date")
        if due_date == "null" or not due_date:
            due_date = None

        matter_slug = None
        try:
            from orchestrator.pipeline import _match_matter_slug
            matter_slug = _match_matter_slug(desc, subject, store)
        except Exception:
            pass

        cid = store.store_commitment(
            description=desc,
            assigned_to=c.get("assigned_to", sender or ""),
            due_date=due_date,
            source_type="email",
            source_id=source_id,
            source_context=f"Email: {subject}",
            matter_slug=matter_slug,
        )
        if cid:
            inserted += 1

    if inserted:
        logger.info(f"Extracted {inserted} commitments from email '{subject[:60]}'")


# -------------------------------------------------------
# Phase 3C: Email intelligence signal detection
# -------------------------------------------------------

_EMAIL_INTELLIGENCE_PROMPT = """You are Baker. Check if this email contains a signal the Director should know about proactively.

Signals: competitor moves, regulatory changes, market shifts, opportunity alerts, risk indicators, deadline changes, relationship changes (new contact, role change, departure).

Return ONLY valid JSON:
{
    "signal_detected": true/false,
    "signal_type": "competitor|regulatory|market|opportunity|risk|deadline|relationship",
    "summary": "One sentence",
    "urgency": "high|medium|low",
    "related_matter": "matter_slug or null"
}

If no clear signal, set signal_detected: false.
"""


def _check_email_intelligence(email_text: str, subject: str, sender: str):
    """Check high-priority email for intelligence signals. Creates alert if found."""
    import json
    import anthropic
    from memory.store_back import SentinelStoreBack

    if not email_text or len(email_text.strip()) < 30:
        return

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_EMAIL_INTELLIGENCE_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Subject: {subject}\nFrom: {sender}\n\n{email_text[:3000]}",
            }],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="email_intelligence")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        result = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Email intelligence check parse error: {e}")
        return

    if not result.get("signal_detected"):
        return

    signal_type = result.get("signal_type", "")
    urgency = result.get("urgency", "low")
    summary = result.get("summary", "")
    matter = result.get("related_matter")
    if matter == "null":
        matter = None

    if urgency in ("high", "medium"):
        tier = 2 if urgency == "high" else 3
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=tier,
            title=f"Intelligence: {summary[:80]}",
            body=f"**Signal:** {signal_type}\n**From:** {sender}\n**Subject:** {subject}\n\n{summary}",
            action_required=(urgency == "high"),
            matter_slug=matter,
            tags=["intelligence", signal_type] if signal_type else ["intelligence"],
            source="email_intelligence",
        )
        logger.info(f"Email intelligence alert: {signal_type} — {summary[:60]}")


def check_new_emails():
    """
    Main entry point — called by scheduler every 5 minutes.
    1. Polls Gmail for new threads
    2. Classifies each by priority
    3. Runs pipeline immediately for high/medium priority
    4. Queues low-priority for daily briefing
    """
    import time as _time
    global _gmail_retry_after, _gmail_backoff_seconds

    # Load persisted backoff state (survives deploys)
    now_ts = _time.time()
    if _gmail_retry_after == 0.0:
        persisted = trigger_state.get_watermark("email_429_backoff")
        if persisted:
            _gmail_retry_after = persisted.timestamp()

    # Skip poll if we're in a 429 backoff window
    if now_ts < _gmail_retry_after:
        remaining = int(_gmail_retry_after - now_ts)
        logger.info(f"Email trigger: skipping poll — Gmail 429 backoff ({remaining}s remaining)")
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        return

    logger.info("Email trigger: checking for new threads...")

    try:
        new_threads = poll_gmail()
    except Exception as e:
        error_str = str(e)
        _health_failure("email", error_str)
        logger.error(f"Email trigger: Gmail poll failed: {e}")

        # Parse 429 Retry-After and set backoff
        if "429" in error_str or "rateLimitExceeded" in error_str:
            # Try to parse "Retry after YYYY-MM-DDTHH:MM:SS" from error
            import re
            retry_match = re.search(r'Retry after (\d{4}-\d{2}-\d{2}T[\d:.]+Z?)', error_str)
            if retry_match:
                try:
                    retry_dt = datetime.fromisoformat(retry_match.group(1).replace("Z", "+00:00"))
                    _gmail_retry_after = retry_dt.timestamp() + 60  # add 60s buffer
                    _gmail_backoff_seconds = 0  # reset exponential — we have a real timestamp
                    # Persist to DB so backoff survives deploys
                    backoff_until = datetime.fromtimestamp(_gmail_retry_after, tz=timezone.utc)
                    trigger_state.set_watermark("email_429_backoff", backoff_until)
                    logger.info(f"Email trigger: 429 retry-after parsed → backoff until {retry_dt.isoformat()} + 60s")
                except (ValueError, TypeError):
                    pass

            if _gmail_retry_after <= now_ts:
                # No parsed timestamp — use exponential backoff
                if _gmail_backoff_seconds == 0:
                    _gmail_backoff_seconds = 600  # start at 10 min
                else:
                    _gmail_backoff_seconds = min(_gmail_backoff_seconds * 2, 3600)  # max 1 hour
                _gmail_retry_after = now_ts + _gmail_backoff_seconds
                backoff_until = datetime.fromtimestamp(_gmail_retry_after, tz=timezone.utc)
                trigger_state.set_watermark("email_429_backoff", backoff_until)
                logger.info(f"Email trigger: 429 exponential backoff → {int(_gmail_backoff_seconds)}s")

        # Still update checked watermark so we can distinguish "poll crashed"
        # from "poll never ran" in /api/status
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        return

    # Poll succeeded — reset 429 backoff state
    _gmail_retry_after = 0.0
    _gmail_backoff_seconds = 0.0
    # Clear persisted backoff
    try:
        trigger_state.set_watermark("email_429_backoff", datetime(2000, 1, 1, tzinfo=timezone.utc))
    except Exception:
        pass

    if not new_threads:
        logger.info("Email trigger: no new threads")
        # PHASE-4A: Advance watermark even when no emails found — prevents
        # false "gap alert" when inbox is quiet (cosmetic but confusing).
        # Separate "last_checked" (now) from "last_email_seen" (watermark).
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        # Gap detection: alert if no SUBSTANTIVE email for 48+ hours
        # Uses the real watermark (last email seen), not last_checked
        global _last_gap_alert_time
        import time as _time
        now_ts = _time.time()
        wm = trigger_state.get_watermark("email_poll")
        if wm:
            gap_hours = (datetime.now(timezone.utc) - wm).total_seconds() / 3600
            if gap_hours > 48 and (now_ts - _last_gap_alert_time) > _GAP_ALERT_COOLDOWN:
                gap_title = f"Email gap alert: {gap_hours:.0f}h since last email"
                gap_body = (
                    f"Last email seen: {wm.isoformat()} ({gap_hours:.0f}h ago).\n"
                    f"Last successful poll: just now (no new emails).\n"
                    f"This may be normal if inbox is quiet."
                )
                logger.warning(gap_title)
                try:
                    from memory.store_back import SentinelStoreBack
                    store = SentinelStoreBack._get_global_instance()
                    store.create_alert(tier=2, title=gap_title, body=gap_body, source="email_gap")
                    _last_gap_alert_time = now_ts
                except Exception as e:
                    logger.error(f"Gap alert dispatch failed: {e}")
        _health_success("email")
        return

    logger.info(f"Email trigger: {len(new_threads)} new threads found")

    try:
        _process_email_threads(new_threads)
    except Exception as e:
        logger.error(f"Email trigger: thread processing crashed: {e}")
    finally:
        # ALWAYS update checked watermark and report success (poll itself worked)
        trigger_state.set_watermark("email_poll_checked", datetime.now(timezone.utc))
        _health_success("email")

    logger.info("Email trigger: poll cycle complete")


def _process_email_threads(new_threads: list):
    """Process email threads — extracted so outer function always updates health."""
    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    batch_for_briefing = []
    processed = 0
    skipped = 0
    latest_seen_dt = None  # F4: track max received_date across ALL seen threads
    _seen_threads_this_cycle: set = set()  # ALERT-DEDUP-1: prevent within-cycle duplicates

    for thread in new_threads:
        metadata = thread.get("metadata", {})
        thread_id = metadata.get("thread_id", "unknown")

        # ALERT-DEDUP-1: Skip if we already processed this thread in this poll cycle
        # (extract_poll can return the same thread twice via Gmail pagination)
        if thread_id in _seen_threads_this_cycle:
            skipped += 1
            continue
        _seen_threads_this_cycle.add(thread_id)

        # REPLY-TRACK-1: Check if this incoming email is a reply to a Baker-sent email
        try:
            _check_reply_match(
                thread_id=thread_id,
                sender=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
                subject=metadata.get("subject", ""),
                body_preview=thread.get("text", "")[:300],
            )
        except Exception as _e:
            logger.debug(f"Reply check failed for thread {thread_id}: {_e}")

        # F4: Track received_date of every seen thread (processed + skipped)
        received_date_str = metadata.get("received_date", "")
        if received_date_str and received_date_str != "unknown":
            try:
                rd = datetime.fromisoformat(received_date_str)
                if rd.tzinfo is None:
                    rd = rd.replace(tzinfo=timezone.utc)
                if latest_seen_dt is None or rd > latest_seen_dt:
                    latest_seen_dt = rd
            except (ValueError, TypeError):
                pass

        # F1: Dedup on thread_id against trigger_log — skip if this thread was already processed
        # ALERT-DEDUP-1 fix: use thread_id for dedup (not individual message_ids which only
        # partially match trigger_log entries, causing repeat processing every cycle)
        if trigger_state.is_processed("email", thread_id):
            skipped += 1
            continue

        # Use thread_id as pipeline source_id (stable across poll cycles)
        message_id = thread_id

        # ARCH-6: Store full email to PostgreSQL
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.store_email_message(
                message_id=message_id,
                thread_id=thread_id,
                sender_name=metadata.get("primary_sender"),
                sender_email=metadata.get("primary_sender_email"),
                subject=metadata.get("subject"),
                full_body=thread["text"],
                received_date=metadata.get("received_date"),
                priority=None,  # set after classification
            )
        except Exception as _e:
            logger.warning(f"Failed to store email {message_id} to PostgreSQL (non-fatal): {_e}")

        trigger = TriggerEvent(
            type="email",
            content=thread["text"],
            source_id=message_id,
            contact_name=metadata.get("primary_sender"),
        )
        trigger = pipeline.classify_trigger(trigger)

        # DEADLINE-SYSTEM-1: Extract deadlines from email content
        try:
            from orchestrator.deadline_manager import extract_deadlines
            extract_deadlines(
                content=thread["text"],
                source_type="email",
                source_id=message_id,
                sender_name=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
            )
        except Exception as _e:
            logger.debug(f"Deadline extraction failed for email {message_id}: {_e}")

        if trigger.priority in ("high", "medium"):
            try:
                pipeline.run(trigger)
                processed += 1
            except Exception as e:
                logger.error(f"Email trigger: pipeline failed for message {message_id} (thread {thread_id}): {e}")

            # Phase 3C: Extract commitments from high-priority emails
            try:
                _extract_commitments_from_email(
                    email_text=thread["text"],
                    subject=metadata.get("subject", ""),
                    sender=metadata.get("primary_sender", ""),
                    source_id=message_id,
                )
            except Exception as _e:
                logger.debug(f"Commitment extraction failed for email {message_id}: {_e}")

            # Phase 3C: Check for intelligence signals in high-priority emails
            if trigger.priority == "high":
                try:
                    _check_email_intelligence(
                        email_text=thread["text"],
                        subject=metadata.get("subject", ""),
                        sender=metadata.get("primary_sender", ""),
                    )
                except Exception as _e:
                    logger.debug(f"Email intelligence check failed for {message_id}: {_e}")
        else:
            # Queue low-priority for daily briefing
            batch_for_briefing.append({
                "type": "email",
                "source_id": message_id,
                "content": thread["text"],
                "contact_name": metadata.get("primary_sender"),
                "subject": metadata.get("subject", ""),
                "priority": trigger.priority,
            })

    # Store low-priority batch for briefing
    if batch_for_briefing:
        trigger_state.add_to_briefing_queue(batch_for_briefing)

    # F4: Advance watermark to the newest received_date seen this cycle
    # (covers both processed and deduped threads — prevents re-fetching old batches)
    if latest_seen_dt:
        now_utc = datetime.now(timezone.utc)
        if latest_seen_dt > now_utc:
            logger.warning(
                f"Email watermark ceiling hit: {latest_seen_dt.isoformat()} > now "
                f"({now_utc.isoformat()}). Capping at now."
            )
            latest_seen_dt = now_utc
        trigger_state.set_watermark("email_poll", latest_seen_dt)
        logger.info(f"Email watermark advanced to {latest_seen_dt.isoformat()}")

    logger.info(
        f"Email trigger: {processed} processed, "
        f"{len(batch_for_briefing)} queued for briefing, {skipped} skipped (dedup)"
    )


def _check_reply_match(
    thread_id: str,
    sender: str = "",
    sender_email: str = "",
    subject: str = "",
    body_preview: str = "",
):
    """
    REPLY-TRACK-1: Check if an incoming email is a reply to a Baker-sent email.
    If so, mark it as replied and push an alert to the digest buffer.
    """
    from models.sent_emails import find_awaiting_reply, mark_reply_received

    sent = find_awaiting_reply(thread_id)
    if not sent:
        return  # Not a reply to anything Baker sent

    # Mark reply received
    mark_reply_received(
        sent_email_id=sent["id"],
        reply_snippet=body_preview[:300],
        reply_from=sender_email or sender,
    )
    logger.info(
        f"Reply detected from {sender} to Baker-sent email "
        f"(thread={thread_id}, original subject: {sent.get('subject', '?')[:60]})"
    )

    # Determine urgency: VIP replies = urgent
    is_vip = False
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        sender_lower = (sender or "").lower()
        email_lower = (sender_email or "").lower()
        for vip in vips:
            vip_name = (vip.get("name") or "").lower()
            vip_email = (vip.get("email") or "").lower()
            if (sender_lower and sender_lower in vip_name) or \
               (email_lower and email_lower == vip_email):
                is_vip = True
                break
    except Exception:
        pass

    tier = 1 if is_vip else 2

    # Push alert to digest buffer
    try:
        from orchestrator.digest_manager import add_alert

        reply_preview = body_preview[:200].replace("\n", " ")
        title = (
            f"\U0001f4e9 Reply received to Baker-sent email\n"
            f"From: {sender or sender_email}\n"
            f"Original subject: {sent.get('subject', '?')}\n"
            f'Preview: "{reply_preview}..."'
        )

        add_alert(
            title=title,
            source_type="Reply Detection",
            timestamp=datetime.now(timezone.utc).strftime("%H:%M UTC"),
            tier=tier,
            source_id=f"reply:{thread_id}",
            content=f"Reply from {sender} to: {sent.get('subject', '?')}",
            is_critical=is_vip,
        )
    except Exception as e:
        logger.warning(f"Failed to push reply alert to digest: {e}")

    # If original was sent via WhatsApp, also notify on WhatsApp
    if sent.get("channel") == "whatsapp":
        try:
            from outputs.whatsapp_sender import send_whatsapp

            wa_text = (
                f"\U0001f4e9 Reply to your email:\n"
                f"From: {sender or sender_email}\n"
                f"Re: {sent.get('subject', '?')}\n"
                f'"{body_preview[:200]}"\n\n'
                f"Reply here to follow up, or ask me to draft a response."
            )
            send_whatsapp(wa_text)
        except Exception as e:
            logger.warning(f"WhatsApp reply notification failed: {e}")


def backfill_emails(days: int = 14):
    """
    ARCH-6: One-time backfill — fetch last N days of emails from Gmail API,
    store full bodies to email_messages table + embed to Qdrant.
    No pipeline re-run. Safe to run repeatedly (upsert on conflict).
    """
    import time as _time

    logger.info(f"Email backfill: fetching last {days} days from Gmail API...")

    try:
        from scripts import extract_gmail
        from scripts.extract_gmail import (
            authenticate, fetch_thread_ids, fetch_thread_detail,
            format_thread, has_skip_label, is_noise_thread,
        )
        from googleapiclient.discovery import build
        from memory.store_back import SentinelStoreBack

        creds = authenticate()
        service = build("gmail", "v1", credentials=creds)
        # ARCH-6: Set Gmail service so format_thread() can extract attachments
        extract_gmail._gmail_service = service
        store = SentinelStoreBack._get_global_instance()

        since_date = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
        query = f"after:{since_date} {config.gmail.default_query}"

        logger.info(f"Email backfill query: {query}")
        thread_ids = fetch_thread_ids(service, query, limit=None)

        if not thread_ids:
            logger.info("Email backfill: no threads found")
            return

        logger.info(f"Email backfill: {len(thread_ids)} threads to process")

        stored = 0
        embedded = 0

        for i, tid in enumerate(thread_ids):
            thread = fetch_thread_detail(service, tid)
            if not thread:
                continue

            messages = thread.get("messages", [])

            # Skip noise
            if has_skip_label(messages):
                continue
            is_noise, _ = is_noise_thread(messages)
            if is_noise:
                continue

            # Limit messages per thread
            if len(messages) > config.gmail.max_messages_per_thread:
                messages = messages[-config.gmail.max_messages_per_thread:]

            formatted = format_thread(thread, messages)
            if not formatted:
                continue

            metadata = formatted.get("metadata", {})
            message_id = metadata.get("message_id", tid)

            # Store to PostgreSQL
            success = store.store_email_message(
                message_id=message_id,
                thread_id=metadata.get("thread_id"),
                sender_name=metadata.get("primary_sender"),
                sender_email=metadata.get("primary_sender_email"),
                subject=metadata.get("subject"),
                full_body=formatted["text"],
                received_date=metadata.get("received_date"),
            )
            if success:
                stored += 1

            # Embed to Qdrant with rate limiting
            try:
                _time.sleep(2)  # Voyage AI rate limit
                embed_metadata = {
                    "source": "email",
                    "subject": metadata.get("subject", ""),
                    "sender": metadata.get("primary_sender", ""),
                    "sender_email": metadata.get("primary_sender_email", ""),
                    "date": metadata.get("received_date", ""),
                    "message_id": message_id,
                    "thread_id": metadata.get("thread_id", ""),
                    "content_type": "email_thread",
                    "label": metadata.get("subject", "email"),
                }
                store.store_document(formatted["text"], embed_metadata, collection="baker-conversations")
                embedded += 1
            except Exception as _e:
                logger.warning(f"Email Qdrant embed failed for {message_id}: {_e}")

            if (i + 1) % 50 == 0:
                logger.info(f"Email backfill: processed {i + 1}/{len(thread_ids)}...")

        logger.info(f"Email backfill complete: {stored} stored to PostgreSQL, {embedded} embedded to Qdrant (of {len(thread_ids)} threads)")

    except Exception as e:
        logger.error(f"Email backfill failed: {e}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", type=int, default=0,
                        help="Backfill last N days of emails to PostgreSQL + Qdrant")
    args = parser.parse_args()

    if args.backfill:
        backfill_emails(days=args.backfill)
    else:
        check_new_emails()
