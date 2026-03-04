"""
Baker AI — Slack Output Layer
Posts formatted messages to #cockpit via Slack Bot Token (slack_sdk WebClient).
Uses Slack Block Kit for rich formatting.

Migration note (SLACK-1 S4): replaced httpx + incoming webhook with
slack_sdk WebClient.chat_postMessage(). Bot token read from SLACK_BOT_TOKEN.
Target channel: config.slack.cockpit_channel_id (default: C0AF4FVN3FB = #cockpit).

ALERT-DEDUP-1: Two-level dedup prevents the same alert from flooding Slack.
Level 1: exact title+tier match → 1h window.
Level 2: topic entity+tier match → 4h window.
"""
import logging
import re
import time
from typing import Optional

from config.settings import config
from outputs.formatters import (
    format_alert_slack,
    format_briefing_slack,
    format_pipeline_result_slack,
    tier_label,
)

logger = logging.getLogger("sentinel.slack")

# Slack limits
_MAX_BLOCKS_PER_MESSAGE = 50
_RATE_LIMIT_DELAY = 1.1  # seconds between multi-message posts

# -------------------------------------------------------
# ALERT-DEDUP-1: In-memory dedup cache
# -------------------------------------------------------
_EXACT_DEDUP_WINDOW = 3600        # 1 hour — blocks identical title+tier repeats
_TOPIC_DEDUP_WINDOW = 4 * 3600    # 4 hours — blocks same-entity+tier variants

# {key: timestamp} — separate caches for exact vs topic dedup
_exact_cache: dict[str, float] = {}
_topic_cache: dict[str, float] = {}
_suppressed_count = 0


def _cleanup_cache(cache: dict, max_age: float):
    """Remove expired entries from a dedup cache."""
    now = time.time()
    expired = [k for k, ts in cache.items() if now - ts > max_age]
    for k in expired:
        del cache[k]


def _exact_key(title: str, tier: int) -> str:
    """Dedup key for exact title match."""
    return f"t{tier}:{title.strip().lower()}"


def _topic_key(title: str, tier: int) -> str:
    """Dedup key based on the primary entity/topic in the alert title.
    Extracts the first proper-noun-like word (>3 chars, capitalized) as the topic."""
    for word in title.split():
        clean = re.sub(r'[^\w]', '', word)
        if len(clean) > 3 and clean[0].isupper():
            return f"t{tier}:{clean.lower()}"
    # Fallback: first significant word
    for word in title.split():
        clean = re.sub(r'[^\w]', '', word).lower()
        if len(clean) > 3:
            return f"t{tier}:{clean}"
    return f"t{tier}:{title[:20].lower()}"


def _is_duplicate_alert(title: str, tier: int) -> bool:
    """Check if a similar alert was posted recently. Returns True to suppress."""
    global _suppressed_count
    now = time.time()

    # Prune expired entries
    _cleanup_cache(_exact_cache, _EXACT_DEDUP_WINDOW)
    _cleanup_cache(_topic_cache, _TOPIC_DEDUP_WINDOW)

    ek = _exact_key(title, tier)
    tk = _topic_key(title, tier)

    # Level 1: exact match within 1h
    if ek in _exact_cache:
        _suppressed_count += 1
        if _suppressed_count % 50 == 0:
            logger.info(f"ALERT-DEDUP-1: {_suppressed_count} total alerts suppressed since startup")
        return True

    # Level 2: topic match within 4h
    if tk in _topic_cache:
        _suppressed_count += 1
        if _suppressed_count % 50 == 0:
            logger.info(f"ALERT-DEDUP-1: {_suppressed_count} total alerts suppressed since startup")
        return True

    # Not a duplicate — record in both caches
    _exact_cache[ek] = now
    _topic_cache[tk] = now
    return False


def _get_webclient():
    """Get a Slack WebClient (lazy import, new instance each call — thread-safe)."""
    from slack_sdk import WebClient
    return WebClient(token=config.outputs.slack_bot_token)


class SlackNotifier:
    """
    Slack delivery engine.
    Posts alerts, briefings, and pipeline results to #cockpit via Bot Token.
    All operations are non-fatal — failures are logged but never raise.
    """

    def __init__(self):
        self._channel = config.slack.cockpit_channel_id
        if not config.outputs.slack_bot_token:
            logger.warning("SlackNotifier: SLACK_BOT_TOKEN not configured")

    # -------------------------------------------------------
    # Public API
    # -------------------------------------------------------

    def post_alert(self, alert: dict) -> bool:
        """
        Format and post a single alert.
        Tier 3 (INFO) alerts are skipped — they appear in the daily briefing only.
        ALERT-DEDUP-1: Duplicate alerts (same title or same topic entity) are suppressed.
        """
        tier = alert.get("tier", 3)
        title = alert.get("title", "")

        if tier >= 3:
            logger.debug(f"Skipping Tier {tier} alert (INFO only): {title}")
            return True

        # ALERT-DEDUP-1: suppress duplicate alerts
        if _is_duplicate_alert(title, tier):
            logger.debug(f"Slack alert suppressed (duplicate): [{tier}] {title}")
            return True

        label = tier_label(tier)
        logger.info(f"Posting {label} alert to Slack: {title}")

        payload = format_alert_slack(alert)
        return self._post(payload)

    def post_briefing(self, briefing_text: str, date_str: str) -> bool:
        """
        Format and post the morning briefing as Block Kit message.
        Splits into multiple POSTs if blocks exceed 50.
        """
        logger.info(f"Posting morning briefing to Slack ({len(briefing_text)} chars)")

        payload = format_briefing_slack(briefing_text, date_str)
        blocks = payload.get("blocks", [])

        if len(blocks) <= _MAX_BLOCKS_PER_MESSAGE:
            return self._post(payload)

        all_ok = True
        for i, chunk_start in enumerate(range(0, len(blocks), _MAX_BLOCKS_PER_MESSAGE)):
            chunk = blocks[chunk_start : chunk_start + _MAX_BLOCKS_PER_MESSAGE]

            if i > 0:
                chunk.insert(0, {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_...continued ({i + 1})_"}],
                })
                if len(chunk) > _MAX_BLOCKS_PER_MESSAGE:
                    chunk = chunk[:_MAX_BLOCKS_PER_MESSAGE]

            ok = self._post({"blocks": chunk})
            if not ok:
                all_ok = False

            if chunk_start + _MAX_BLOCKS_PER_MESSAGE < len(blocks):
                time.sleep(_RATE_LIMIT_DELAY)

        return all_ok

    def post_pipeline_result(self, analysis: str, trigger_type: str,
                             contact_name: str = None) -> bool:
        """
        Post a compact summary when the pipeline processes a trigger.
        Only posts for email/whatsapp/meeting triggers (not scheduled/manual/slack).
        """
        if trigger_type in ("manual", "scheduled", "slack"):
            return True

        logger.info(f"Posting pipeline result to Slack: {trigger_type}")
        payload = format_pipeline_result_slack(analysis, trigger_type, contact_name)
        return self._post(payload)

    def post_thread_reply(self, channel_id: str, thread_ts: str, text: str) -> bool:
        """
        Post a reply in a Slack thread (S3 — @Baker mention response).

        Args:
            channel_id: Slack channel ID (e.g. C0AF4FVN3FB).
            thread_ts:  Timestamp of the parent message (Slack thread identifier).
            text:       Reply text (plain text, max 3000 chars recommended).
        Returns:
            True if posted successfully, False otherwise.
        """
        if not config.outputs.slack_bot_token:
            logger.warning("Slack thread reply skipped: SLACK_BOT_TOKEN not configured")
            return False
        try:
            client = _get_webclient()
            resp = client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text[:3000],
            )
            if resp.get("ok"):
                return True
            logger.warning(f"Slack thread reply failed: {resp.get('error')}")
            return False
        except Exception as e:
            logger.warning(f"Slack thread reply failed: {e}")
            return False

    # -------------------------------------------------------
    # Internal
    # -------------------------------------------------------

    def _post(self, payload: dict) -> bool:
        """
        Post Block Kit payload to #cockpit via WebClient.chat_postMessage().
        Returns True on success. All errors are non-fatal.
        """
        if not config.outputs.slack_bot_token:
            logger.warning("Slack POST skipped: SLACK_BOT_TOKEN not configured")
            return False

        try:
            client = _get_webclient()

            # Ensure `text` fallback exists — required for push notifications / accessibility
            text = payload.get("text") or " "

            resp = client.chat_postMessage(
                channel=self._channel,
                text=text,
                blocks=payload.get("blocks"),
                attachments=payload.get("attachments"),
            )

            if resp.get("ok"):
                return True

            logger.warning(f"Slack chat_postMessage failed: {resp.get('error')}")
            return False

        except Exception as e:
            logger.warning(f"Slack POST failed: {e}")
            return False
