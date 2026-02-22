"""
Baker AI — Slack Output Layer
Posts formatted messages to #cockpit via incoming webhook.
Uses Slack Block Kit for rich formatting.
"""
import logging
import time
from typing import Optional

import httpx

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


class SlackNotifier:
    """
    Slack delivery engine.
    Posts alerts, briefings, and pipeline results to #cockpit via webhook.
    All operations are non-fatal — failures are logged but never raise.
    """

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or config.outputs.slack_webhook_url
        if not self.webhook_url or not self.webhook_url.startswith("http"):
            logger.warning("SlackNotifier: no valid webhook URL configured")

    # -------------------------------------------------------
    # Public API
    # -------------------------------------------------------

    def post_alert(self, alert: dict) -> bool:
        """
        Format and post a single alert.
        Tier 3 (INFO) alerts are skipped — they appear in the daily briefing only.

        Args:
            alert: dict with keys: tier (int), title (str), body (str),
                   action_required (bool), contact_name (str), deal_name (str)
        Returns:
            True if posted successfully, False otherwise.
        """
        tier = alert.get("tier", 3)

        # Tier 3 = INFO — don't post, stays in PostgreSQL for morning briefing
        if tier >= 3:
            logger.debug(f"Skipping Tier {tier} alert (INFO only): {alert.get('title')}")
            return True

        label = tier_label(tier)
        logger.info(f"Posting {label} alert to Slack: {alert.get('title', '?')}")

        payload = format_alert_slack(alert)
        return self._post(payload)

    def post_briefing(self, briefing_text: str, date_str: str) -> bool:
        """
        Format and post the morning briefing as Block Kit message.
        Splits into multiple POSTs if blocks exceed 50.

        Args:
            briefing_text: The briefing markdown content.
            date_str: Date string (e.g., "2026-02-19").
        Returns:
            True if all parts posted successfully.
        """
        logger.info(f"Posting morning briefing to Slack ({len(briefing_text)} chars)")

        payload = format_briefing_slack(briefing_text, date_str)
        blocks = payload.get("blocks", [])

        if len(blocks) <= _MAX_BLOCKS_PER_MESSAGE:
            return self._post(payload)

        # Split into chunks of max blocks
        all_ok = True
        for i, chunk_start in enumerate(range(0, len(blocks), _MAX_BLOCKS_PER_MESSAGE)):
            chunk = blocks[chunk_start : chunk_start + _MAX_BLOCKS_PER_MESSAGE]

            # Add continuation header for subsequent chunks
            if i > 0:
                chunk.insert(0, {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_...continued ({i + 1})_"}],
                })
                # May need to drop last block to stay under limit
                if len(chunk) > _MAX_BLOCKS_PER_MESSAGE:
                    chunk = chunk[:_MAX_BLOCKS_PER_MESSAGE]

            ok = self._post({"blocks": chunk})
            if not ok:
                all_ok = False

            # Rate limiting between multi-message posts
            if chunk_start + _MAX_BLOCKS_PER_MESSAGE < len(blocks):
                time.sleep(_RATE_LIMIT_DELAY)

        return all_ok

    def post_pipeline_result(self, analysis: str, trigger_type: str,
                             contact_name: str = None) -> bool:
        """
        Post a compact summary when the pipeline processes a trigger.
        Only posts for email/whatsapp/meeting triggers (not scheduled/manual).

        Args:
            analysis: The pipeline analysis text.
            trigger_type: Type of trigger (email, whatsapp, etc.).
            contact_name: Optional contact name.
        Returns:
            True if posted successfully.
        """
        # Don't spam Slack with manual queries or scheduled runs
        if trigger_type in ("manual", "scheduled"):
            return True

        logger.info(f"Posting pipeline result to Slack: {trigger_type}")
        payload = format_pipeline_result_slack(analysis, trigger_type, contact_name)
        return self._post(payload)

    # -------------------------------------------------------
    # Internal
    # -------------------------------------------------------

    def _post(self, payload: dict) -> bool:
        """
        POST payload to Slack webhook.
        Returns True on success. All errors are non-fatal.
        """
        if not self.webhook_url or not self.webhook_url.startswith("http"):
            logger.warning("Slack POST skipped: no webhook URL configured")
            return False

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(self.webhook_url, json=payload)

                if resp.status_code == 200:
                    return True

                # Slack returns "ok" for success, error text otherwise
                logger.warning(
                    f"Slack POST returned {resp.status_code}: {resp.text[:200]}"
                )
                return False

        except httpx.TimeoutException:
            logger.warning("Slack POST timed out (10s)")
            return False
        except Exception as e:
            logger.warning(f"Slack POST failed: {e}")
            return False
