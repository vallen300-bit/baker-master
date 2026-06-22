"""BAKER_DASHBOARD_V2_CARD_DETAIL_1 — bounded detail view for one trusted item.

Backend half of Workstream B. Given a ``verified_items`` id, return a single
trusted card with bounded evidence + the verification audit timeline, so the
Director can inspect *why* a Today card exists without ever seeing a raw
confidential source body.

This module is read-only and reads ONLY ``verified_items`` +
``verification_events`` (via ``models.verified_items``). It makes NO model calls,
NO writes, NO migrations, and exposes NO raw email/WhatsApp/ClaimsMax body text.

Defence-in-depth against body leakage (G2 security):
  * source_refs run through ``today_v2.sanitize_source_refs`` (drops body/text/
    content/snippet/transcript keys recursively), AND
  * every remaining string in source_refs + each event's ``evidence_delta`` is
    length-bounded to ``EXCERPT_MAX`` chars, so even an unexpected large/raw
    field cannot dump a full body through the detail route.

Trust gate: an item whose ``state`` is not in ``today_v2.TRUSTED_STATES`` returns
``{"status": "not_trusted"}`` and the route HIDES it as a 404 (no enumeration of
candidate/dismissed rows). A missing id returns ``{"status": "not_found"}``.

NOTE: deliberately does NOT import the WS-A ``today_selection`` module (unmerged,
PR #414) so the route is independent of selection-engine merge order. The compact
``selected_reason`` here is a small standalone helper.
"""
from __future__ import annotations

import logging
from typing import Optional

from orchestrator.today_v2 import (
    TRUSTED_STATES,
    lane_for_item_type,
    sanitize_source_refs,
)

logger = logging.getLogger("baker.verified_item_detail")

# Max length for ANY string echoed in the detail payload (claim, why_matters,
# verification_summary, source-ref metadata, audit rationale/delta — everything).
# This is a HARD ceiling: a truncated string's FINAL length (marker included) is
# exactly EXCERPT_MAX, never over (deputy-codex G0 F1 — the bound is required by
# the brief's "bounded excerpts only" contract, and must not overshoot).
EXCERPT_MAX = 280
_TRUNC_MARKER = "…(truncated)"

# Safe-to-surface scalar fields copied verbatim from the trusted row. These are
# Baker's OWN structured fields (claim/why/analysis/metadata), never raw bodies.
_DETAIL_FIELDS = (
    "id", "state", "item_type", "claim", "why_matters", "next_action", "owner",
    "due_at", "confidence", "matter_slug", "related_matters", "people",
    "source_type", "source_trust", "verification_summary", "counterargument",
    "created_at", "updated_at",
)

# Audit-event fields safe to surface. ``evidence_delta`` is bounded+stripped;
# raw source bodies were never stored on events, but we strip defensively anyway.
_EVENT_FIELDS = (
    "id", "from_state", "to_state", "actor_type", "actor_id", "model",
    "rationale", "created_at",
)


def _bound(value, max_len: int = EXCERPT_MAX):
    """Recursively truncate any string so its FINAL length is <= ``max_len``.

    The truncation marker is counted INTO the budget (truncate to
    ``max_len - len(marker)`` then append), so a bounded string never exceeds
    ``max_len`` — including the marker (deputy-codex G0 F1 secondary).
    """
    if isinstance(value, str):
        if len(value) > max_len:
            keep = max(0, max_len - len(_TRUNC_MARKER))
            return value[:keep] + _TRUNC_MARKER
        return value
    if isinstance(value, dict):
        return {k: _bound(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_bound(v, max_len) for v in value]
    return value


def _selected_reason(row: dict) -> str:
    """Compact, deterministic, model-free reason string (standalone)."""
    parts = ["Ratified" if str(row.get("state") or "").lower() == "ratified" else "Verified"]
    due = row.get("due_at")
    if due is not None:
        parts.append("due " + str(due).split("T")[0].split(" ")[0])
    conf = str(row.get("confidence") or "").strip().lower()
    if conf in ("high", "medium", "low"):
        parts.append(f"{conf} confidence")
    return " · ".join(parts)


def _sanitize_event(event: dict) -> dict:
    """Select safe event fields + strip raw-body keys from evidence_delta.

    Length-bounding is NOT done here — the whole assembled item (this included)
    runs through ``_bound`` once at the end of ``build_detail`` so no string in
    the payload can escape the ceiling.
    """
    out = {f: event.get(f) for f in _EVENT_FIELDS}
    delta = event.get("evidence_delta")
    if isinstance(delta, (dict, list)):
        from orchestrator.today_v2 import _strip_raw  # reuse the canonical stripper
        out["evidence_delta"] = _strip_raw(delta)
    else:
        out["evidence_delta"] = delta
    return out


def build_detail(row: dict, events: Optional[list] = None) -> dict:
    """Assemble the bounded detail payload from a trusted row + its audit events.

    Pure (no DB) so it is unit-testable. Caller guarantees ``row`` is trusted.
    """
    detail = {f: row.get(f) for f in _DETAIL_FIELDS}
    detail["lane"] = lane_for_item_type(row.get("item_type"))
    detail["selected_reason"] = _selected_reason(row)

    refs, count = sanitize_source_refs(row.get("source_refs"))
    detail["source_refs"] = refs
    detail["source_refs_count"] = count

    # Evidence-packet metadata (model ids are safe + wanted by the brief).
    detail["evidence"] = {
        "source_type": row.get("source_type"),
        "source_trust": row.get("source_trust"),
        "extraction_model": row.get("extraction_model"),
        "source_model": row.get("source_model"),
        "source_refs_count": count,
    }

    safe_events = [_sanitize_event(e) for e in (events or []) if isinstance(e, dict)]
    detail["verification_events"] = safe_events
    detail["verification_event_count"] = len(safe_events)

    # Single wholesale length-bound pass (G0 F1): EVERY free-text scalar in the
    # item — claim, why_matters, next_action, verification_summary,
    # counterargument, source-ref metadata, event rationale/delta — is bounded to
    # <= EXCERPT_MAX. No field can escape the ceiling. (counts/ids are ints; the
    # `_*_count` keys and id stay numeric.)
    return {"status": "ok", "item": _bound(detail)}


def get_verified_item_detail(item_id: int) -> dict:
    """Fetch + assemble the bounded detail for ``item_id``.

    Returns one of::

        {"status": "ok", "item": {...}}
        {"status": "not_found"}
        {"status": "not_trusted"}

    Fault-tolerant: a degraded DB surfaces as ``not_found`` (never an exception).
    """
    try:
        from models.verified_items import get_item, get_events
        row = get_item(item_id)
        if not row:
            return {"status": "not_found"}
        if row.get("state") not in TRUSTED_STATES:
            # Hide candidate/dismissed rows — route maps this to 404.
            return {"status": "not_trusted"}
        events = get_events(row["id"])
        return build_detail(row, events)
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"verified_item_detail: get_verified_item_detail failed: {e}")
        return {"status": "not_found"}
