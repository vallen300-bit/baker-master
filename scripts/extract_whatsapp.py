"""
Baker AI -- WhatsApp Historical Backfill
Fetches message history from WhatsApp chats via WAHA API,
extracts text from media attachments, and stores in Qdrant + PostgreSQL.

Usage:
    # Full historical backfill (all chats, last 3 months)
    python scripts/extract_whatsapp.py --since 2025-12-01
    python scripts/extract_whatsapp.py --since 2025-12-01 --dry-run

    # Single chat
    python scripts/extract_whatsapp.py --chat-id 41799605092@c.us --since 2025-12-01

    # Limit number of chats (testing)
    python scripts/extract_whatsapp.py --limit 5 --since 2025-12-01 --dry-run
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config

logger = logging.getLogger("baker.extract_whatsapp")

# Concurrency guard — prevent backfill + scheduler poll from running simultaneously
_backfill_running = False


DIRECTOR_WHATSAPP_JID = "41799605092@s.whatsapp.net"
DIRECTOR_WHATSAPP_CUS = "41799605092@c.us"


def _store_messages_to_postgres(msgs: list, chat_id: str):
    """Store individual WhatsApp messages to whatsapp_messages table.
    This enables Phase 3 features (VIP SLA check, context assembly) which
    query whatsapp_messages directly."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        stored = 0
        for m in msgs:
            msg_id = m.get("id", {})
            if isinstance(msg_id, dict):
                msg_id = msg_id.get("id", msg_id.get("_serialized", ""))
            if not msg_id:
                continue

            sender_jid = m.get("from", "")
            from_me = m.get("fromMe", False)
            name = _sender_name(m)
            body = m.get("body", "") or ""
            ts = m.get("timestamp", 0)

            is_director = from_me or sender_jid in (DIRECTOR_WHATSAPP_JID, DIRECTOR_WHATSAPP_CUS)

            ts_iso = None
            if ts:
                try:
                    ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                except (ValueError, OSError):
                    pass

            if body.strip():
                store.store_whatsapp_message(
                    msg_id=str(msg_id),
                    sender=sender_jid,
                    sender_name=name,
                    chat_id=chat_id,
                    full_text=body,
                    timestamp=ts_iso,
                    is_director=is_director,
                )
                stored += 1

        if stored:
            logger.info(f"Stored {stored} messages to whatsapp_messages for chat {chat_id[:20]}")
    except Exception as e:
        logger.warning(f"Failed to store messages to PostgreSQL for chat {chat_id[:20]}: {e}")


# ------------------------------------------------------------------
# Message formatting
# ------------------------------------------------------------------

def _sender_name(msg: dict) -> str:
    """Extract display name from a WAHA message."""
    data = msg.get("_data", {})
    name = data.get("notifyName", "")
    if name:
        return name
    # Fallback: phone number from 'from' field
    sender = msg.get("from", "")
    if "@" in sender:
        return sender.split("@")[0]
    return sender or "Unknown"


def _msg_timestamp(msg: dict) -> Optional[datetime]:
    """Parse message timestamp to timezone-aware UTC datetime."""
    ts = msg.get("timestamp", 0)
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def format_chat(
    chat_id: str,
    chat_name: str,
    is_group: bool,
    messages: list[dict],
    media_texts: dict,
) -> Optional[dict]:
    """
    Format a WhatsApp chat into {text, metadata} for Qdrant ingestion.
    Returns None if chat has no substantive content.

    media_texts: dict mapping msg_id -> extracted text from attachments.
    """
    if not messages:
        return None

    msg_blocks = []
    participants = set()
    dates = []

    for msg in messages:
        sender = _sender_name(msg)
        participants.add(sender)

        dt = _msg_timestamp(msg)
        if dt:
            dates.append(dt)
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown"

        body = msg.get("body", "") or ""
        msg_id = msg.get("id", "")

        # Append media text if available
        media_text = media_texts.get(msg_id, "")
        media_info = ""
        if msg.get("hasMedia"):
            media = msg.get("media") or {}
            mimetype = media.get("mimetype", "attachment")
            if media_text:
                media_info = f"\n[Attachment ({mimetype}): {media_text}]"
            else:
                media_info = f"\n[Attachment ({mimetype})]"

        combined = (body + media_info).strip()
        if not combined:
            continue

        msg_blocks.append(f"--- {sender} ({date_str}) ---\n{combined}")

    if not msg_blocks:
        return None

    total_chars = sum(len(b) for b in msg_blocks)
    if total_chars < 50:
        return None

    # Date range
    if dates:
        dates.sort()
        date_range = (
            f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}"
            if len(dates) > 1
            else dates[0].strftime("%Y-%m-%d")
        )
        first_date = dates[0].strftime("%Y-%m-%d")
        latest_ts = int(dates[-1].timestamp())
    else:
        date_range = "unknown"
        first_date = "unknown"
        latest_ts = 0

    chat_type = "group" if is_group else "direct"
    participants_str = ", ".join(sorted(participants))

    parts = [
        f"WhatsApp Chat: {chat_name}",
        f"Chat ID: {chat_id}",
        f"Type: {chat_type}",
        f"Date: {date_range}",
        f"Participants: {participants_str}",
        f"Messages: {len(msg_blocks)}",
        "",
    ]
    parts.extend(msg_blocks)
    text_block = "\n".join(parts)

    media_count = sum(1 for m in messages if m.get("hasMedia"))

    metadata = {
        "source": "whatsapp",
        "chat_id": chat_id,
        "chat_name": chat_name,
        "chat_type": chat_type,
        "participants": participants_str,
        "date": first_date,
        "date_range": date_range,
        "message_count": len(msg_blocks),
        "media_count": media_count,
        "content_type": "whatsapp_chat",
        "label": f"whatsapp:{chat_name}",
    }

    source_id = f"wa-chat-{chat_id}-{latest_ts}"

    return {"text": text_block, "metadata": metadata, "source_id": source_id}


# ------------------------------------------------------------------
# Media processing
# ------------------------------------------------------------------

def _process_media(messages: list[dict]) -> dict:
    """
    Download and extract text from media attachments.
    Returns dict of msg_id -> extracted text.
    """
    from triggers.waha_client import (
        download_media_file,
        extract_media_text,
        is_extractable,
        _rewrite_media_url,
    )

    media_texts = {}
    for msg in messages:
        if not msg.get("hasMedia"):
            continue

        msg_id = msg.get("id", "")
        media = msg.get("media") or {}
        mimetype = media.get("mimetype", "")
        media_url = media.get("url", "")

        if not media_url or not is_extractable(mimetype):
            continue

        media_url = _rewrite_media_url(media_url)
        filepath = download_media_file(media_url)
        if not filepath:
            continue

        text = extract_media_text(filepath, mimetype)
        if text:
            media_texts[msg_id] = text
            logger.info(f"Extracted {len(text)} chars from {mimetype} in msg {msg_id[:30]}")

        time.sleep(0.5)  # Rate limit media downloads

    return media_texts


# ------------------------------------------------------------------
# Extraction
# ------------------------------------------------------------------

def _chat_name(chat: dict) -> str:
    """Get display name for a chat."""
    return (
        chat.get("name", "")
        or chat.get("pushname", "")
        or chat.get("id", "unknown")
    )


def _is_group(chat_id: str) -> bool:
    return "@g.us" in chat_id


def extract_historical(
    since: str,
    limit: Optional[int] = None,
    chat_id: Optional[str] = None,
    dry_run: bool = False,
    download_media: bool = True,
) -> list[dict]:
    """
    Fetch historical WhatsApp messages from WAHA API.
    Returns list of {text, metadata, source_id} dicts.
    """
    from triggers.waha_client import list_chats, fetch_messages

    since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ts = int(since_dt.timestamp())

    # Get chat list
    if chat_id:
        chats = [{"id": chat_id}]
        print(f"Single chat mode: {chat_id}")
    else:
        print("Fetching chat list from WAHA...")
        chats = list_chats(limit=500)
        print(f"Found {len(chats)} chats")

    if limit:
        chats = chats[:limit]
        print(f"Limited to {limit} chats")

    if dry_run:
        # Preview mode: fetch 3 sample chats
        sample_count = min(3, len(chats))
        print(f"\n[DRY RUN] Fetching {sample_count} sample chats for preview...\n")
        for chat in chats[:sample_count]:
            cid = chat.get("id", "?")
            name = _chat_name(chat)
            try:
                msgs = fetch_messages(cid, limit=100, download_media=False)
                msgs = [m for m in msgs if m.get("timestamp", 0) >= since_ts]
                media_count = sum(1 for m in msgs if m.get("hasMedia"))
                print(f"  {name} ({cid})")
                print(f"    Messages since {since}: {len(msgs)}")
                print(f"    With media: {media_count}")
                if msgs:
                    first_body = (msgs[0].get("body") or "")[:100]
                    print(f"    First msg: {first_body}...")
                print()
            except Exception as e:
                print(f"  {cid}: fetch failed ({e})")
            time.sleep(0.5)

        print(f"[DRY RUN] Would process {len(chats)} chats total")
        return []

    # Full extraction
    items = []
    errors = 0

    for i, chat in enumerate(chats):
        cid = chat.get("id", "?")
        name = _chat_name(chat)

        if (i + 1) % 20 == 0 or i == 0:
            print(f"Processing chat {i + 1}/{len(chats)}: {name}...")

        try:
            msgs = fetch_messages(cid, limit=100, download_media=download_media)
        except Exception as e:
            logger.warning(f"Failed to fetch messages for {cid}: {e}")
            errors += 1
            time.sleep(0.5)
            continue

        # Filter to messages since cutoff
        msgs = [m for m in msgs if m.get("timestamp", 0) >= since_ts]

        if not msgs:
            time.sleep(0.3)
            continue

        # Store individual messages to whatsapp_messages table (Phase 3 needs this)
        _store_messages_to_postgres(msgs, cid)

        # Process media attachments
        media_texts = {}
        if download_media:
            media_texts = _process_media(msgs)

        # Format chat
        formatted = format_chat(
            chat_id=cid,
            chat_name=name,
            is_group=_is_group(cid),
            messages=msgs,
            media_texts=media_texts,
        )

        if formatted:
            items.append(formatted)

        time.sleep(0.5)  # WAHA API rate limit

    print(f"\nExtraction complete:")
    print(f"  Chats processed: {len(chats)}")
    print(f"  Substantive chats: {len(items)}")
    print(f"  Errors: {errors}")

    return items


# ------------------------------------------------------------------
# Qdrant + PostgreSQL ingestion
# ------------------------------------------------------------------

def ingest_to_qdrant(items: list[dict]):
    """
    Store formatted chat items in Qdrant baker-whatsapp + trigger_log.
    Deduplicates via trigger_state.is_processed().
    """
    from memory.store_back import SentinelStoreBack
    from triggers.state import trigger_state

    store = SentinelStoreBack._get_global_instance()
    collection = "baker-whatsapp"

    ingested = 0
    skipped = 0

    for item in items:
        source_id = item["source_id"]

        # Dedup check
        if trigger_state.is_processed("whatsapp", source_id):
            skipped += 1
            continue

        # Store in Qdrant (auto-chunks long chats)
        try:
            store.store_document(
                item["text"],
                item["metadata"],
                collection=collection,
            )
        except Exception as e:
            logger.warning(f"Qdrant store failed for {source_id}: {e}")

        # Log to trigger_log (PostgreSQL) — also serves as dedup marker
        try:
            store.log_trigger(
                trigger_type="whatsapp",
                source_id=source_id,
                content=item["text"],
                priority="low",
            )
        except Exception as e:
            logger.warning(f"trigger_log write failed for {source_id}: {e}")

        ingested += 1
        time.sleep(2)  # Voyage AI rate limit between embeds

    print(f"Ingestion complete: {ingested} ingested, {skipped} skipped (dedup)")


# ------------------------------------------------------------------
# Startup backfill (called by dashboard.py)
# ------------------------------------------------------------------

def backfill_whatsapp():
    """
    Startup catch-up: sync last 7 days of WhatsApp messages.
    Safe to run repeatedly — dedup via trigger_log.
    Called by dashboard.py in a background thread on every deploy.
    """
    global _backfill_running

    if not config.waha.api_key:
        logger.info("WhatsApp backfill: WHATSAPP_API_KEY not set, skipping")
        return

    if _backfill_running:
        logger.info("WhatsApp backfill: already running, skipping")
        return

    _backfill_running = True
    logger.info("WhatsApp backfill: starting 7-day catch-up...")

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        items = extract_historical(
            since=since,
            limit=None,
            chat_id=None,
            dry_run=False,
            download_media=True,
        )
        if items:
            ingest_to_qdrant(items)
        logger.info(f"WhatsApp backfill complete: {len(items)} chats processed")
    except Exception as e:
        logger.error(f"WhatsApp backfill failed: {e}")
    finally:
        _backfill_running = False


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baker AI -- WhatsApp historical backfill via WAHA API",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Fetch messages on or after this date (YYYY-MM-DD). Default: 3 months ago.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of chats to process",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Process a single chat by ID (e.g. 41799605092@c.us)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be extracted without storing",
    )
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Skip media download and text extraction",
    )
    args = parser.parse_args()

    if not args.since:
        three_months_ago = datetime.now(timezone.utc) - timedelta(days=90)
        args.since = three_months_ago.strftime("%Y-%m-%d")
        print(f"No --since provided, defaulting to 3 months ago: {args.since}")

    print(f"\n{'=' * 60}")
    print(f"Baker AI -- WhatsApp Backfill")
    print(f"{'=' * 60}")
    print(f"Since: {args.since}")
    if args.chat_id:
        print(f"Chat: {args.chat_id}")
    if args.limit:
        print(f"Limit: {args.limit} chats")
    if args.dry_run:
        print("Mode: DRY RUN")
    print()

    items = extract_historical(
        since=args.since,
        limit=args.limit,
        chat_id=args.chat_id,
        dry_run=args.dry_run,
        download_media=not args.no_media,
    )

    if args.dry_run or not items:
        return

    # Ingest to Qdrant + PostgreSQL
    print(f"\nIngesting {len(items)} chats to Qdrant + PostgreSQL...")
    ingest_to_qdrant(items)

    total_chars = sum(len(item["text"]) for item in items)
    print(f"\nTotal text: {total_chars:,} chars (~{total_chars // 4:,} tokens)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    main()
