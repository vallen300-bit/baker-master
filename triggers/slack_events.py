"""
Sentinel Trigger — Slack Events API Webhook
Receives real-time events from Slack instead of polling.

Endpoint: POST /webhook/slack
Handles: url_verification, message (human), app_mention (@Baker)

Reuses _embed_message and _feed_to_pipeline from slack_trigger.py.
Coexists with polling — controlled by SLACK_MODE env var (events|polling).
Both can run simultaneously; dedup by event_id prevents double-processing.

Requires: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
"""
import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from config.settings import config

logger = logging.getLogger("sentinel.slack_events")

router = APIRouter()

# In-memory event dedup (TTL 5 min) — Slack retries on non-200
_seen_events: dict[str, float] = {}
_DEDUP_TTL = 300  # 5 minutes


def _prune_seen():
    """Remove expired entries from event dedup cache."""
    now = time.time()
    expired = [eid for eid, ts in _seen_events.items() if now - ts > _DEDUP_TTL]
    for eid in expired:
        del _seen_events[eid]


def _verify_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature using SLACK_SIGNING_SECRET."""
    secret = config.slack.signing_secret
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not set — skipping signature verification")
        return True  # Allow through if no secret configured (polling-only setups)

    # Reject requests older than 5 minutes (replay protection)
    try:
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("Slack event rejected: timestamp too old")
            return False
    except (ValueError, TypeError):
        return False

    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


def _process_event(event: dict):
    """Process a single Slack event in background. Non-fatal."""
    try:
        event_type = event.get("type", "")
        subtype = event.get("subtype")

        # Skip bot messages, system messages
        if subtype or event.get("bot_id"):
            return

        user_id = event.get("user", "")
        text = (event.get("text") or "").strip()
        channel = event.get("channel", "")
        ts = event.get("ts", "")

        if not user_id or not text or not channel:
            return

        # Lazy imports to avoid circular deps at module load
        from triggers.slack_trigger import _embed_message, _feed_to_pipeline, _resolve_user_name, _get_webclient, _get_store
        from triggers.state import trigger_state

        client = _get_webclient()
        store = _get_store()
        user_name = _resolve_user_name(client, user_id)

        # 1. Embed every human message to Qdrant
        _embed_message(store, channel, user_name, text, ts, config.slack.collection)

        # 2. @Baker mention or app_mention → run pipeline
        baker_uid = config.slack.baker_bot_user_id
        is_mention = (
            event_type == "app_mention"
            or (baker_uid and f"<@{baker_uid}>" in text)
        )

        if is_mention:
            source_id = f"slack:{channel}:{ts}"
            if not trigger_state.is_processed("slack", source_id):
                _feed_to_pipeline(
                    channel_id=channel,
                    ts=ts,
                    user_name=user_name,
                    text=text,
                    source_id=source_id,
                )
                logger.info(f"Slack event: @Baker mention from {user_name} in {channel} → pipeline")
            else:
                logger.debug(f"Slack event: duplicate mention {source_id}, skipped")
        else:
            logger.debug(f"Slack event: message from {user_name} in {channel} embedded")

    except Exception as e:
        logger.warning(f"Slack event processing failed: {e}")


@router.post("/slack")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    """
    Slack Events API webhook endpoint.

    Handles:
    - url_verification (Slack challenge handshake)
    - event_callback (message, app_mention)

    Returns 200 within 3 seconds (Slack requirement).
    Actual processing runs in background.
    """
    body = await request.body()

    # Verify signature (if signing secret is configured)
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if config.slack.signing_secret and not _verify_signature(body, timestamp, signature):
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    msg_type = payload.get("type", "")

    # --- url_verification challenge (Slack setup handshake) ---
    if msg_type == "url_verification":
        challenge = payload.get("challenge", "")
        logger.info("Slack Events API: url_verification challenge received")
        return JSONResponse({"challenge": challenge})

    # --- event_callback (actual events) ---
    if msg_type == "event_callback":
        event_id = payload.get("event_id", "")

        # Dedup: Slack may retry events
        _prune_seen()
        if event_id in _seen_events:
            logger.debug(f"Slack event {event_id} already seen, returning 200")
            return JSONResponse({"ok": True})
        _seen_events[event_id] = time.time()

        event = payload.get("event", {})
        event_type = event.get("type", "")

        if event_type in ("message", "app_mention"):
            # Process in background — return 200 within 3 seconds
            background_tasks.add_task(_process_event, event)

        return JSONResponse({"ok": True})

    # Unknown type — accept gracefully
    return JSONResponse({"ok": True})
