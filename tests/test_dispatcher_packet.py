from __future__ import annotations

from datetime import timezone

from orchestrator.dispatcher import (
    format_packet_for_bus,
    parse_schedule_packet,
    resolve_owner_slug,
)


def _packet(owner_slug: str = "baden-baden-desk") -> str:
    return f"""DISPATCHER PACKET
title: Skliar/Derkachova extension
owner_slug: {owner_slug}
matter_slug: lilienmatt
flight_type: chartered
due_at: 2026-06-30
priority: urgent
condition_precedent:
- AO confirms friendly extension posture
- Draft written addendum exists
blocked_by:
- Missing signed Derkachova PDF
required_action: update maturity plan and escalate if not extended
source: baden-baden-desk
"""


def test_valid_packet_parses_with_conditions_in_order() -> None:
    result = parse_schedule_packet(_packet())
    assert result.ok
    assert result.packet is not None
    assert result.packet.owner_slug == "baden-baden-desk"
    assert result.packet.matter_slug == "lilienmatt"
    assert result.packet.due_at.tzinfo is not None
    assert result.packet.due_at.astimezone(timezone.utc).date().isoformat() == "2026-06-30"
    assert result.packet.condition_precedent == [
        "AO confirms friendly extension posture",
        "Draft written addendum exists",
    ]
    assert result.packet.blocked_by == ["Missing signed Derkachova PDF"]


def test_owner_alias_resolves_to_canonical_slug() -> None:
    assert resolve_owner_slug("research-agent") == "researcher"
    result = parse_schedule_packet(_packet("research-agent"))
    assert result.ok
    assert result.packet is not None
    assert result.packet.owner_slug == "researcher"


def test_missing_owner_needs_clarification() -> None:
    result = parse_schedule_packet(_packet("").replace("owner_slug: ", "owner_slug:"))
    assert result.needs_clarification
    assert any("owner_slug" in err for err in result.errors)


def test_director_owner_is_rejected() -> None:
    result = parse_schedule_packet(_packet("director"))
    assert result.needs_clarification
    assert "reserved owner_slug: director" in result.errors


def test_bus_format_has_required_dispatcher_fields() -> None:
    result = parse_schedule_packet(_packet())
    assert result.packet is not None
    body = format_packet_for_bus(result.packet, status="due", clickup_task_id="abc123")
    assert "FROM: dispatcher" in body
    assert "TO: baden-baden-desk" in body
    assert "ClickUp task: abc123" in body
    assert "Condition precedent:" in body
    assert "Required action: update maturity plan" in body
