"""Cortex Phase 4 — proposal card.

Renders a Slack Block Kit card with:
  * proposal text (markdown)
  * structured_actions summary
  * per-file Gold checkboxes (RA-23 Q2)
  * 4 action buttons (✅ Approve / ✏️ Edit / 🔄 Refresh / ❌ Reject)

DRY_RUN-aware: when ``CORTEX_DRY_RUN=true`` the Slack post is skipped and
a ``dry_run_marker`` row is written to ``cortex_phase_outputs``.

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md`` (Fix/Feature 1).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DIRECTOR_DM_CHANNEL = "D0AFY28N030"  # mirror of triggers/ai_head_audit.py:_DIRECTOR_DM_CHANNEL
SECTION_TEXT_LIMIT = 2900  # Slack mrkdwn section cap (3000 raw — 100 char headroom)
MAX_GOLD_CHECKBOXES = 10   # Slack checkbox-element option max
MAX_ACTION_LINES = 5
STAGING_ROOT = Path("outputs/cortex_proposed_curated")


@dataclass
class ProposalCard:
    proposal_id: str
    cycle_id: str
    matter_slug: str
    proposal_text: str
    structured_actions: list[dict]
    proposed_gold_entries: list[dict]   # [{filename, content, default_checked}, ...]
    blocks: list[dict]                   # Slack Block Kit payload
    dry_run: bool = False


def _get_store():
    """Resolve the SentinelStoreBack singleton via the canonical accessor.

    Module-level indirection lets tests monkeypatch the store.
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _is_dry_run() -> bool:
    return os.environ.get("CORTEX_DRY_RUN", "false").strip().lower() == "true"


async def run_phase4_propose(
    *,
    cycle_id: str,
    matter_slug: str,
    phase3c_result: Any,
) -> ProposalCard:
    """Build proposal card, persist, post to Slack (or skip in DRY_RUN).

    Returns the ProposalCard regardless of Slack post outcome — Slack failure
    is non-fatal (matches SlackNotifier invariant) and is logged but does
    NOT raise.
    """
    proposal_id = str(uuid.uuid4())
    proposal_text = getattr(phase3c_result, "proposal_text", "") or ""
    structured_actions = list(getattr(phase3c_result, "structured_actions", []) or [])

    proposed_gold = _build_proposed_gold_entries(
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        structured_actions=structured_actions,
        proposal_text=proposal_text,
    )

    blocks = _build_blocks(
        proposal_id=proposal_id,
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        proposal_text=proposal_text,
        structured_actions=structured_actions,
        proposed_gold=proposed_gold,
    )

    dry_run = _is_dry_run()
    card = ProposalCard(
        proposal_id=proposal_id,
        cycle_id=cycle_id,
        matter_slug=matter_slug,
        proposal_text=proposal_text,
        structured_actions=structured_actions,
        proposed_gold_entries=proposed_gold,
        blocks=blocks,
        dry_run=dry_run,
    )

    _persist_phase4(cycle_id, card)

    if dry_run:
        logger.info(
            "[CORTEX_DRY_RUN] Would post Slack card for cycle %s matter=%s "
            "(%d gold entries, %d structured actions) — skipping",
            cycle_id, matter_slug, len(proposed_gold), len(structured_actions),
        )
        _mark_dry_run(cycle_id)
    else:
        _post_to_slack(card)

    return card


def _build_blocks(
    *,
    proposal_id: str,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    structured_actions: list[dict],
    proposed_gold: list[dict],
) -> list[dict]:
    """Slack Block Kit payload. ≤50 blocks, sections ≤3000 chars (Slack limits)."""
    blocks: list[dict] = []
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"Cortex proposal — {matter_slug}"[:150]},
    })
    body_text = proposal_text[:SECTION_TEXT_LIMIT] if proposal_text else "_(no proposal text)_"
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": body_text},
    })
    if structured_actions:
        lines = []
        for a in structured_actions[:MAX_ACTION_LINES]:
            action_name = str(a.get("action") or a.get("type") or "?")[:60]
            rationale = str(a.get("rationale") or a.get("description") or "")[:120]
            lines.append(f"• *{action_name}* — {rationale}")
        actions_md = "\n".join(lines) or "_(no structured actions)_"
        actions_text = f"*Proposed actions:*\n{actions_md}"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": actions_text[:SECTION_TEXT_LIMIT]},
        })
    if proposed_gold:
        options = []
        for entry in proposed_gold[:MAX_GOLD_CHECKBOXES]:
            label = str(entry.get("filename") or "")[:75]
            options.append({
                "text": {"type": "plain_text", "text": label or "_unnamed_"},
                "value": label,
            })
        block = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Proposed Gold updates* (uncheck to skip):"},
            "accessory": {
                "type": "checkboxes",
                "action_id": f"cortex_gold_select_{proposal_id}",
                "options": options,
            },
        }
        if options:
            block["accessory"]["initial_options"] = options
        blocks.append(block)
    button_value = json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})
    blocks.append({
        "type": "actions",
        "block_id": f"cortex_actions_{proposal_id}",
        "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "✅ Approve"},
             "style": "primary",
             "action_id": "cortex_approve",
             "value": button_value},
            {"type": "button",
             "text": {"type": "plain_text", "text": "✏️ Edit"},
             "action_id": "cortex_edit",
             "value": button_value},
            {"type": "button",
             "text": {"type": "plain_text", "text": "🔄 Refresh"},
             "action_id": "cortex_refresh",
             "value": button_value},
            {"type": "button",
             "text": {"type": "plain_text", "text": "❌ Reject"},
             "style": "danger",
             "action_id": "cortex_reject",
             "value": button_value},
        ],
    })
    return blocks[:50]


def _build_proposed_gold_entries(
    *,
    cycle_id: str,
    matter_slug: str,
    structured_actions: list[dict],
    proposal_text: str,
) -> list[dict]:
    """Read staged curated files at outputs/cortex_proposed_curated/<cycle_id>/*.md.

    Each file becomes a Director-toggleable Gold entry.
    """
    staging = STAGING_ROOT / cycle_id
    if not staging.is_dir():
        return []
    entries: list[dict] = []
    for f in sorted(staging.glob("*.md"))[:MAX_GOLD_CHECKBOXES]:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Failed to read staged curated file %s: %s", f, e)
            continue
        entries.append({
            "filename": f.name,
            "content": content,
            "default_checked": True,
        })
    return entries


def _persist_phase4(cycle_id: str, card: ProposalCard) -> None:
    """INSERT propose row + UPDATE cycle.proposal_id + status='tier_b_pending'."""
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        logger.error("Phase 4 persist: no DB connection")
        return
    try:
        cur = conn.cursor()
        payload = {
            "proposal_id": card.proposal_id,
            "proposal_text": card.proposal_text[:8000],
            "structured_actions": card.structured_actions,
            "proposed_gold_entries": [
                {"filename": e.get("filename")} for e in card.proposed_gold_entries
            ],
            "slack_blocks": card.blocks,
            "dry_run": card.dry_run,
        }
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 7, 'proposal_card', %s::jsonb)
            """,
            (cycle_id, json.dumps(payload, default=str)),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET proposal_id=%s, status='tier_b_pending', current_phase='propose'
            WHERE cycle_id=%s
            """,
            (card.proposal_id, cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_persist_phase4 failed: %s", e)
        raise
    finally:
        store._put_conn(conn)


def _mark_dry_run(cycle_id: str) -> None:
    """Append a dry_run_marker artifact (best-effort — never raises)."""
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 8, 'dry_run_marker', %s::jsonb)
            """,
            (cycle_id, json.dumps({"reason": "CORTEX_DRY_RUN=true; Slack post skipped"})),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("_mark_dry_run failed: %s", e)
    finally:
        store._put_conn(conn)


def _post_to_slack(card: ProposalCard) -> bool:
    """Post Block Kit card to Director DM. Non-fatal on failure."""
    try:
        from outputs.slack_notifier import _get_webclient
        from config.settings import config
        if not config.outputs.slack_bot_token:
            logger.warning("cortex_phase4: SLACK_BOT_TOKEN unset; skipping post")
            return False
        client = _get_webclient()
        resp = client.chat_postMessage(
            channel=DIRECTOR_DM_CHANNEL,
            blocks=card.blocks,
            text=f"Cortex proposal — {card.matter_slug} (cycle {card.cycle_id[:8]})",
        )
        if resp.get("ok"):
            return True
        logger.warning("cortex_phase4 Slack post failed: %s", resp.get("error"))
        return False
    except Exception as e:
        logger.warning("cortex_phase4 Slack post raised: %s", e)
        return False
