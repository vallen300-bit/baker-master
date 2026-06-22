"""BAKER_DASHBOARD_V2_TODAY_1 — the trusted Today read service.

Today is the Director's first screen. It must show ONLY items Baker is prepared
to defend: ``verified_items`` in state ``verified`` or ``ratified``, grouped into
four allowlisted lanes (critical / promises / meetings / travel), with evidence
metadata only — never raw source bodies.

This module is read-only. It makes NO model calls, NO writes, NO migrations, and
reads ONLY ``verified_items`` (via ``models.verified_items.list_today_items``).
It never queries ``signal_candidates``, ``alerts``, or ``deadlines`` — raw and
candidate rows cannot bypass into Today.

Defence-in-depth: even though ``list_today_items`` already filters to trusted
states, ``build_today_payload`` re-filters by ``TRUSTED_STATES`` and re-strips
source-ref bodies, so a caller passing untrusted rows (or a future read path)
cannot leak candidate/dismissed rows or raw bodies through this assembler.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("baker.today_v2")

LANES = ("critical", "promises", "meetings", "travel")
TRUSTED_STATES = ("verified", "ratified")

# Explicit item_type -> lane allowlist (AC3). An item_type not in this map is
# excluded from Today and counted under `excluded`; we never invent a 5th lane.
ITEM_TYPE_TO_LANE = {
    "critical": "critical",
    "critical_item": "critical",
    "promise": "promises",
    "commitment": "promises",
    "deadline": "promises",
    "action_item": "promises",
    "meeting": "meetings",
    "meeting_prep": "meetings",
    "meeting_followup": "meetings",
    "travel": "travel",
    "travel_obligation": "travel",
    "trip": "travel",
}

# AC4 — source_refs may carry only metadata. Any key equal to or ending in one of
# these tokens is stripped (recursively) so raw bodies never reach Today.
_RAW_REF_KEY_TOKENS = (
    "body",
    "raw_body",
    "text",
    "content",
    "snippet",
    "source_snippet",
    "transcript",
)

# The stable card field set (AC4) pulled from a verified_items row.
_CARD_FIELDS = (
    "id", "state", "item_type", "claim", "why_matters", "next_action", "owner",
    "due_at", "matter_slug", "people", "confidence", "source_trust",
    "verification_summary", "counterargument", "created_at", "updated_at",
)


def lane_for_item_type(item_type: Optional[str]) -> Optional[str]:
    """Map an item_type to its allowlisted lane, or None if unknown (excluded)."""
    if not item_type:
        return None
    return ITEM_TYPE_TO_LANE.get(str(item_type).strip().lower())


def _is_raw_key(key: str) -> bool:
    k = str(key).strip().lower()
    return any(k == tok or k.endswith(tok) for tok in _RAW_REF_KEY_TOKENS)


def _strip_raw(value):
    """Recursively drop raw-body-like keys from dicts/lists (AC4/AC5)."""
    if isinstance(value, dict):
        return {
            k: _strip_raw(v)
            for k, v in value.items()
            if not _is_raw_key(k)
        }
    if isinstance(value, list):
        return [_strip_raw(v) for v in value]
    return value


def sanitize_source_refs(source_refs) -> tuple[list, int]:
    """Return (sanitized_refs, count). Strips raw-body-like keys at any depth.

    The count reflects the number of source refs BEFORE stripping (so a card can
    show "3 sources" even though each is reduced to metadata). Non-list inputs
    yield ([], 0) — Today never echoes a malformed/raw blob.
    """
    if not isinstance(source_refs, (list, tuple)):
        return [], 0
    sanitized = [_strip_raw(ref) for ref in source_refs]
    return sanitized, len(source_refs)


def _card_from_row(row: dict, lane: str) -> dict:
    card = {f: row.get(f) for f in _CARD_FIELDS}
    card["lane"] = lane
    refs, count = sanitize_source_refs(row.get("source_refs"))
    card["source_refs"] = refs
    card["source_refs_count"] = count
    return card


def _empty_payload() -> dict:
    return {
        "status": "ok",
        "lanes": {lane: [] for lane in LANES},
        "counts": {
            **{lane: 0 for lane in LANES},
            "total": 0,
            "excluded": 0,
        },
    }


def build_today_payload(rows: list, limit_per_lane: int = 5) -> dict:
    """Group trusted rows into the four lanes with per-lane limits (AC3/AC6/AC9).

    Defence-in-depth: rows whose ``state`` is not in ``TRUSTED_STATES`` are
    dropped here regardless of how they were read (AC8). Rows arrive pre-sorted
    in Today order from ``list_today_items``; this assembler preserves that order
    and applies the per-lane cap.
    """
    if not isinstance(limit_per_lane, int) or limit_per_lane <= 0:
        limit_per_lane = 5
    if limit_per_lane > 20:
        limit_per_lane = 20

    payload = _empty_payload()
    excluded = 0
    for row in rows or []:
        if not isinstance(row, dict):
            excluded += 1
            continue
        if row.get("state") not in TRUSTED_STATES:
            # candidate / dismissed / anything untrusted never reaches Today.
            continue
        lane = lane_for_item_type(row.get("item_type"))
        if lane is None:
            excluded += 1
            continue
        if len(payload["lanes"][lane]) >= limit_per_lane:
            # lane already full; do not over-serve.
            continue
        payload["lanes"][lane].append(_card_from_row(row, lane))

    total = 0
    for lane in LANES:
        n = len(payload["lanes"][lane])
        payload["counts"][lane] = n
        total += n
    payload["counts"]["total"] = total
    payload["counts"]["excluded"] = excluded
    return payload


def get_today_payload(limit_per_lane: int = 5) -> dict:
    """Return the trusted Today payload from ``verified_items`` only.

    Reads a generous slice of trusted rows, then assembles lanes. Fault-tolerant:
    a degraded DB yields the stable empty-lane shape (AC9), never an error.
    """
    try:
        from models.verified_items import list_today_items
        # Read enough to fill every lane even with skew + unknown types.
        read_limit = max(200, len(LANES) * max(limit_per_lane, 1) * 5)
        rows = list_today_items(limit=read_limit)
        return build_today_payload(rows, limit_per_lane=limit_per_lane)
    except Exception as e:  # pragma: no cover - defensive; list_today_items is itself guarded
        logger.error(f"today_v2: get_today_payload failed: {e}")
        return _empty_payload()
