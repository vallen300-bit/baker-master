"""Dispatcher schedule-packet parser.

Dispatcher is the airport timetable layer: it schedules and routes, but it does
not reason about the underlying matter. Desks/researchers provide structured
packets; Dispatcher validates owner/date/dependencies before any ClickUp or bus
side effect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional

from orchestrator.agent_identity_data import ROLE_TO_SLUG, VALID_BUS_SLUGS

VALID_FLIGHT_TYPES = frozenset({"scheduled", "chartered"})
VALID_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
RESERVED_RECIPIENTS = frozenset({"director", "daemon", "dispatcher"})


@dataclass(frozen=True)
class DispatcherPacket:
    title: str
    owner_slug: str
    due_at: datetime
    required_action: str
    matter_slug: Optional[str] = None
    flight_type: str = "chartered"
    priority: str = "normal"
    condition_precedent: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    source: Optional[str] = None


@dataclass(frozen=True)
class DispatcherPacketResult:
    ok: bool
    packet: Optional[DispatcherPacket] = None
    errors: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return not self.ok


def resolve_owner_slug(value: str) -> Optional[str]:
    """Resolve an owner token to a valid bus recipient."""
    token = (value or "").strip()
    if not token:
        return None
    if token in VALID_BUS_SLUGS:
        return token
    return ROLE_TO_SLUG.get(token) or ROLE_TO_SLUG.get(token.upper())


def _parse_due_at(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.combine(datetime.strptime(text, "%Y-%m-%d").date(), time.min)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_fields(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    fields: dict[str, str] = {}
    lists: dict[str, list[str]] = {"condition_precedent": [], "blocked_by": []}
    current_list: Optional[str] = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "DISPATCHER PACKET":
            continue
        if line.startswith("-") and current_list:
            value = line[1:].strip()
            if value:
                lists[current_list].append(value)
            continue
        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
        value = value.strip()
        if normalized in lists:
            current_list = normalized
            if value:
                lists[normalized].append(value)
        else:
            fields[normalized] = value
    return fields, lists


def parse_schedule_packet(text: str) -> DispatcherPacketResult:
    """Parse and validate a desk-to-Dispatcher schedule packet."""
    fields, lists = _parse_fields(text)
    errors: list[str] = []

    title = fields.get("title", "").strip()
    if not title:
        errors.append("missing title")

    owner_raw = fields.get("owner_slug", "")
    owner_slug = resolve_owner_slug(owner_raw)
    if not owner_slug:
        errors.append("missing_or_invalid owner_slug")
    elif owner_slug in RESERVED_RECIPIENTS:
        errors.append(f"reserved owner_slug: {owner_slug}")

    due_at = _parse_due_at(fields.get("due_at", ""))
    if due_at is None:
        errors.append("missing_or_invalid due_at")

    flight_type = (fields.get("flight_type") or "chartered").strip().lower()
    if flight_type not in VALID_FLIGHT_TYPES:
        errors.append(f"invalid flight_type: {flight_type}")

    priority = (fields.get("priority") or "normal").strip().lower()
    if priority not in VALID_PRIORITIES:
        errors.append(f"invalid priority: {priority}")

    required_action = fields.get("required_action", "").strip()
    if not required_action:
        errors.append("missing required_action")

    if errors:
        return DispatcherPacketResult(ok=False, errors=errors)

    return DispatcherPacketResult(
        ok=True,
        packet=DispatcherPacket(
            title=title,
            owner_slug=owner_slug or "",
            matter_slug=fields.get("matter_slug") or None,
            flight_type=flight_type,
            due_at=due_at or datetime.now(timezone.utc),
            priority=priority,
            condition_precedent=lists["condition_precedent"],
            blocked_by=lists["blocked_by"],
            required_action=required_action,
            source=fields.get("source") or None,
        ),
    )


def format_packet_for_bus(packet: DispatcherPacket, *, status: str, clickup_task_id: str) -> str:
    conditions = "\n".join(f"- {item}" for item in packet.condition_precedent) or "- none"
    blockers = "\n".join(f"- {item}" for item in packet.blocked_by) or "- none"
    return (
        f"TO: {packet.owner_slug}\n"
        "FROM: dispatcher\n"
        f"RE: {packet.title}\n\n"
        f"ClickUp task: {clickup_task_id}\n"
        f"Due: {packet.due_at.isoformat()}\n"
        f"Status: {status}\n"
        "Condition precedent:\n"
        f"{conditions}\n"
        "Blocked by:\n"
        f"{blockers}\n"
        f"Required action: {packet.required_action}\n\n"
        "Reply to dispatcher with DONE / BLOCKED / NEEDS-CLARIFICATION / RESCHEDULE."
    )
