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
    from scripts.extract_gmail import extract_poll
    service = _get_gmail_service()
    return extract_poll(service)


def check_new_emails():
    """
    Main entry point — called by scheduler every 5 minutes.
    1. Polls Gmail for new threads
    2. Classifies each by priority
    3. Runs pipeline immediately for high/medium priority
    4. Queues low-priority for daily briefing
    """
    logger.info("Email trigger: checking for new threads...")

    try:
        new_threads = poll_gmail()
    except Exception as e:
        logger.error(f"Email trigger: Gmail poll failed: {e}")
        return

    if not new_threads:
        logger.info("Email trigger: no new threads")
        # Gap detection: alert if no email activity for 48+ hours
        wm = trigger_state.get_watermark("email_poll")
        if wm:
            gap_hours = (datetime.now(timezone.utc) - wm).total_seconds() / 3600
            if gap_hours > 48:
                gap_title = f"Email gap alert: {gap_hours:.0f}h since last email"
                gap_body = f"Watermark stuck at {wm.isoformat()}. Check Gmail auth and poll health."
                logger.warning(gap_title)
                try:
                    from memory.store_back import store
                    store.create_alert(tier=1, title=gap_title, body=gap_body)
                    from outputs.slack_notifier import SlackNotifier
                    SlackNotifier().post_alert(gap_title, gap_body)
                except Exception as e:
                    logger.error(f"Gap alert dispatch failed: {e}")
        return

    logger.info(f"Email trigger: {len(new_threads)} new threads found")

    from orchestrator.pipeline import SentinelPipeline, TriggerEvent
    pipeline = SentinelPipeline()
    batch_for_briefing = []
    processed = 0
    skipped = 0
    latest_seen_dt = None  # F4: track max received_date across ALL seen threads

    for thread in new_threads:
        metadata = thread.get("metadata", {})
        thread_id = metadata.get("thread_id", "unknown")

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

        # F1: Dedup on ALL message IDs in thread — skip only if every message was seen before
        all_message_ids = metadata.get("all_message_ids") or [metadata.get("message_id", thread_id)]
        new_ids = [mid for mid in all_message_ids if not trigger_state.is_processed("email", mid)]
        if not new_ids:
            skipped += 1
            continue

        # Use latest message ID as pipeline source_id (logged in trigger_log for future dedup)
        message_id = all_message_ids[-1]

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
        else:
            # Queue low-priority for daily briefing
            batch_for_briefing.append({
                "type": "email",
                "source_id": message_id,
                "content": thread["text"][:500],
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
        f"Email trigger complete: {processed} processed, "
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    check_new_emails()
