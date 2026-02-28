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
    logger.info("Slack trigger: starting poll...")

    from config.settings import config

    if not config.slack.bot_token:
        logger.warning("SLACK_BOT_TOKEN not set — skipping Slack poll")
        return

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

            # 2. @Baker mention — run full pipeline (S3 posts thread reply)
            baker_uid = config.slack.baker_bot_user_id
            is_mention = bool(baker_uid and f"<@{baker_uid}>" in text)

            if is_mention and not trigger_state.is_processed("slack", source_id):
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

    logger.info(
        f"Slack poll complete: {channels_polled} channels polled, "
        f"{messages_ingested} messages ingested, {messages_skipped} skipped, "
        f"{mentions_pipelined} mentions pipelined"
    )


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
            "text": text[:500],
        }

        store.store_document(embed_text[:4000], metadata, collection=collection)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_slack_poll()
