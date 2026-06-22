"""BAKER_DASHBOARD_V2_SELECTION_ENGINE_1 — deterministic Today selection.

Today V2 (``today_v2.build_today_payload``) already filters to trusted states,
allowlists lanes, strips raw bodies, and caps each lane. That makes Today *safe*
but it is still a dump: every trusted item in a lane shows up (up to the cap) in
read order, duplicates included, with no explanation of why a card is there.

This module is the **selection layer** on top of that safe primitive. Given the
same trusted ``verified_items`` rows it:

  1. collapses duplicates by stable trusted metadata (no model calls),
  2. ranks rows deterministically using existing trusted fields only,
  3. reuses ``build_today_payload`` for the trusted re-filter + lane group + cap,
  4. enriches each surviving card with a ``selected_reason`` / ``rank`` /
     ``duplicate_count``, and
  5. attaches an explainable ``selection_summary`` + ``duplicates_collapsed`` +
     ``excluded_count`` so the cockpit (and tests) can account for every trusted
     row: ``selected + duplicates_collapsed + excluded_unknown_lane +
     excluded_over_cap == total_trusted_considered``.

Hard exclusions honoured (parent + child brief): NO model/embedding calls, NO
raw-source-table reads, NO trust promotion, NO writes, NO migration. Input is
trusted ``verified_items`` rows ONLY; everything here is pure in-memory logic.

Ranking field mapping (brief §"Ranking requirements" -> actual schema; the test
file documents this explicitly):

  1. Director-critical / explicit priority  -> ``state`` (ratified ranks above
     verified; ratified == a ratify-actor stood behind it) + the ``critical`` lane.
  2. Due / overdue action metadata          -> ``due_at`` ascending, NULLS LAST.
  3. Confidence / verification strength      -> ``confidence`` (high>medium>low).
  4. Recency tie-breaker                     -> ``updated_at`` descending.
  5. Stable final tie-breaker                -> ``id`` descending.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from orchestrator.today_v2 import (
    LANES,
    TRUSTED_STATES,
    build_today_payload,
    lane_for_item_type,
)

logger = logging.getLogger("baker.today_selection")

# Lower sort value == higher priority. ratified outranks verified.
_STATE_RANK = {"ratified": 0, "verified": 1}
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
_LANE_RANK = {lane: i for i, lane in enumerate(LANES)}


def normalize_claim(claim) -> str:
    """Lowercase + whitespace-collapse a claim for duplicate keying.

    Deterministic and dependency-free: ``"  Pay   the  SW  spec.\\n"`` and
    ``"Pay the SW spec."`` collapse to the same key. We intentionally do NOT do
    fuzzy/embedding matching (that would need a model call — forbidden); only
    exact normalized-text or shared canonical id collapse.
    """
    return " ".join(str(claim or "").strip().lower().split())


def dedup_key(row: dict) -> tuple:
    """Stable duplicate key from trusted metadata only.

    Prefers a shared canonical id (``signal_candidate_id`` — two verified_items
    born from the same raw signal are the same thing). Falls back to the
    normalized (matter, item_type, claim) tuple. Never uses raw source bodies.
    """
    sc = row.get("signal_candidate_id")
    if sc is not None:
        return ("cand", sc)
    return (
        "claim",
        str(row.get("matter_slug") or ""),
        str(row.get("item_type") or "").strip().lower(),
        normalize_claim(row.get("claim")),
    )


def _to_epoch(ts) -> float:
    """Best-effort ISO/datetime -> epoch seconds for the recency tie-break.

    Returns 0.0 on anything unparseable so ranking degrades to the id tie-break
    rather than raising. Handles trailing ``Z`` (pre-3.11 fromisoformat).
    """
    if ts is None:
        return 0.0
    if isinstance(ts, datetime):
        try:
            return ts.timestamp()
        except Exception:
            return 0.0
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def rank_key(row: dict) -> tuple:
    """Total deterministic ordering key (ascending == higher priority).

    Every component is comparable and the final ``-id`` term makes the order a
    strict total order, so ``sorted`` is stable across repeated calls and the
    duplicate-canonical pick is unambiguous.
    """
    state = str(row.get("state") or "").lower()
    item_type = row.get("item_type")
    lane = lane_for_item_type(item_type)
    due = row.get("due_at")
    conf = str(row.get("confidence") or "").lower()
    try:
        item_id = int(row.get("id"))
    except (TypeError, ValueError):
        item_id = 0

    return (
        _LANE_RANK.get(lane, len(LANES)),          # 1 — lane order (critical first)
        _STATE_RANK.get(state, 9),                 # 1 — ratified > verified
        (1, "") if due is None else (0, str(due)),  # 2 — due asc, NULLS LAST
        _CONFIDENCE_RANK.get(conf, 9),             # 3 — confidence strength
        -_to_epoch(row.get("updated_at")),         # 4 — recency desc
        -item_id,                                  # 5 — stable id desc
    )


def collapse_duplicates(rows: list) -> tuple[list, int, dict]:
    """Collapse duplicate trusted rows by ``dedup_key``.

    Keeps the best-ranked member of each duplicate group as the canonical card.
    Returns ``(canonical_rows, collapsed_count, dup_counts)`` where
    ``dup_counts[canonical_id]`` is how many siblings were folded into it.
    Pure / deterministic — the canonical pick uses ``rank_key`` (a total order).
    """
    groups: dict[tuple, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        groups.setdefault(dedup_key(row), []).append(row)

    canonical_rows: list = []
    collapsed_count = 0
    dup_counts: dict = {}
    for members in groups.values():
        members.sort(key=rank_key)
        winner = members[0]
        extra = len(members) - 1
        if extra > 0:
            collapsed_count += extra
            wid = winner.get("id")
            if wid is not None:
                dup_counts[wid] = extra
        canonical_rows.append(winner)
    return canonical_rows, collapsed_count, dup_counts


def selected_reason(row: dict, duplicate_count: int = 0) -> str:
    """Compact, deterministic, model-free explanation of why a card is shown."""
    parts: list[str] = []
    state = str(row.get("state") or "").lower()
    parts.append("Ratified" if state == "ratified" else "Verified")

    due = row.get("due_at")
    if due is not None:
        due_s = str(due)
        # show just the date portion when an ISO timestamp is present
        date_part = due_s.split("T")[0].split(" ")[0]
        parts.append(f"due {date_part}")

    conf = str(row.get("confidence") or "").strip().lower()
    if conf in _CONFIDENCE_RANK:
        parts.append(f"{conf} confidence")

    if duplicate_count > 0:
        parts.append(f"+{duplicate_count} similar")

    return " · ".join(parts)


def select_today_payload(rows: list, limit_per_lane: int = 5) -> dict:
    """Deterministic selected Today payload (the engine entry point).

    Backward-compatible superset of ``build_today_payload``'s shape: keeps
    ``status`` / ``lanes`` / ``counts`` exactly, enriches each card with
    ``rank`` / ``selected_reason`` / ``duplicate_count``, and adds
    ``selection_summary`` / ``duplicates_collapsed`` / ``excluded_count``.
    """
    # 1 — trusted-only (defence-in-depth; build_today_payload re-filters too).
    trusted = [
        r for r in (rows or [])
        if isinstance(r, dict) and r.get("state") in TRUSTED_STATES
    ]
    total_trusted = len(trusted)

    # 2 — collapse duplicates, then rank deterministically.
    deduped, collapsed_count, dup_counts = collapse_duplicates(trusted)
    ranked = sorted(deduped, key=rank_key)

    # 3 — reuse the safe primitive for trusted re-filter + lane group + cap.
    payload = build_today_payload(ranked, limit_per_lane=limit_per_lane)

    # Effective cap mirrors build_today_payload's own clamp (1..20, default 5).
    if not isinstance(limit_per_lane, int) or limit_per_lane <= 0:
        effective_cap = 5
    elif limit_per_lane > 20:
        effective_cap = 20
    else:
        effective_cap = limit_per_lane

    # 4 — how many lane-mapped (deduped) items would qualify per lane, to
    #     report over-cap exclusions explainably.
    lane_qualifying = {lane: 0 for lane in LANES}
    for row in ranked:
        lane = lane_for_item_type(row.get("item_type"))
        if lane is not None:
            lane_qualifying[lane] += 1
    excluded_over_cap = sum(max(0, n - effective_cap) for n in lane_qualifying.values())

    # 5 — enrich each surviving card with rank + reason + duplicate count.
    row_by_id = {r.get("id"): r for r in ranked}
    for lane in LANES:
        for idx, card in enumerate(payload["lanes"][lane]):
            cid = card.get("id")
            src = row_by_id.get(cid, {})
            dup_n = int(dup_counts.get(cid, 0))
            card["rank"] = idx + 1
            card["duplicate_count"] = dup_n
            card["selected_reason"] = selected_reason(src, dup_n)

    selected_total = payload["counts"]["total"]
    excluded_unknown_lane = payload["counts"]["excluded"]
    excluded_count = total_trusted - selected_total - collapsed_count

    payload["duplicates_collapsed"] = collapsed_count
    payload["excluded_count"] = excluded_count
    payload["selection_summary"] = {
        "total_trusted_considered": total_trusted,
        "selected": selected_total,
        "duplicates_collapsed": collapsed_count,
        "excluded_count": excluded_count,
        "excluded_unknown_lane": excluded_unknown_lane,
        "excluded_over_cap": excluded_over_cap,
        "limit_per_lane": effective_cap,
        "per_lane": {lane: payload["counts"][lane] for lane in LANES},
    }
    return payload
