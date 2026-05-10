"""Tier B ratify-card emission.

Visual template borrowed from the GOLD card (PR #66 pattern); separate
workflow domain — Tier B is operational/global, GOLD is per-matter. This
module MUST NOT write to ``proposed-gold.md`` or any per-matter GOLD
surface.

When ``enforce_tier_b()`` returns ``PAUSE_REQUIRED``, the call-site hands
the ``pending_id`` to ``emit_ratify_card()``. For V1, B3 prepares the card
payload + DB state transitions; B4 wires the actual Slack push when its
6-phase loop ships.
"""
from __future__ import annotations

import logging
from typing import Optional

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)

VALID_DECISIONS = ("ratified", "rejected")


def _load_pending(pending_id: int) -> Optional[dict]:
    """Read a pending row and return a dict, or None if missing/non-pending."""
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("emit_ratify_card: no DB connection")
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, action_payload, cost_eur, action_class,
                   committer_agent, reason_paused, created_at
              FROM tier_b_pending
             WHERE id = %s AND status = 'pending'
             LIMIT 1
            """,
            (pending_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "action_payload": row[1],
            "cost_eur": float(row[2]),
            "action_class": row[3],
            "committer_agent": row[4],
            "reason_paused": row[5],
            "created_at": row[6],
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"emit_ratify_card DB read failed: {e}")
        return None
    finally:
        store._put_conn(conn)


def build_card_payload(pending: dict) -> dict:
    """Build the Slack Block Kit payload for the Tier-B ratify card.

    Visual structure mirrors the GOLD card (mrkdwn header + facts section +
    4-button proposal). B4 takes this dict and pushes via Slack MCP.
    """
    cost_eur = float(pending["cost_eur"])
    return {
        "channel_intent": "tier_b_ratify",
        "pending_id": pending["id"],
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Tier B ratify required — €{cost_eur:.2f}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Class:* `{pending['action_class']}`"},
                    {"type": "mrkdwn", "text": f"*Agent:* `{pending['committer_agent']}`"},
                    {"type": "mrkdwn", "text": f"*Reason:* `{pending['reason_paused']}`"},
                    {"type": "mrkdwn", "text": f"*Cost:* €{cost_eur:.2f}"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Ratify"},
                        "style": "primary",
                        "action_id": f"tier_b_ratify::{pending['id']}",
                        "value": str(pending["id"]),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": f"tier_b_reject::{pending['id']}",
                        "value": str(pending["id"]),
                    },
                ],
            },
        ],
    }


def emit_ratify_card(pending_id: int) -> bool:
    """Prepare a ratify card for the given ``tier_b_pending`` row.

    For V1 we log the prepared card and return True — B4 wires the Slack
    push. Caller logs failures to ``baker_actions``.
    """
    pending = _load_pending(pending_id)
    if pending is None:
        logger.warning(f"tier_b_pending id={pending_id} not found or not pending")
        return False

    payload = build_card_payload(pending)
    logger.info(
        "Tier-B ratify card prepared: pending_id=%s cost=€%.2f reason=%s "
        "(B4 will wire actual Slack push)",
        payload["pending_id"],
        pending["cost_eur"],
        pending["reason_paused"],
    )
    return True


def consume_ratify_response(
    pending_id: int,
    decision: str,
    ratified_by: str = "director",
) -> bool:
    """Apply Director's ratify decision to a ``tier_b_pending`` row.

    ``decision`` ∈ {ratified, rejected}. On 'ratified' the caller is
    responsible for re-attempting the original action.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {VALID_DECISIONS}, got {decision!r}"
        )

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("consume_ratify_response: no DB connection")
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE tier_b_pending
               SET status = %s,
                   ratified_at = NOW(),
                   ratified_by = %s
             WHERE id = %s AND status = 'pending'
            RETURNING id
            """,
            (decision, ratified_by, pending_id),
        )
        result = cur.fetchone()
        if result is None:
            conn.rollback()
            cur.close()
            logger.warning(f"tier_b_pending id={pending_id} not in pending status")
            return False
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"consume_ratify_response failed: {e}")
        return False
    finally:
        store._put_conn(conn)
