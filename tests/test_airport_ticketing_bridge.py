from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from orchestrator import airport_ticketing_bridge as bridge


def _arrival() -> bridge.EmailArrival:
    return bridge.EmailArrival(
        message_id="AAQk-test-message",
        thread_id="AAQk-test-thread",
        sender_name="Balazs Csepregi",
        sender_email="balazs.csepregi@brisengroup.com",
        subject="Annaberg Status - Closing actions",
        full_body="Absolute priority is completing the Aukera data room today.",
        received_date=datetime(2026, 6, 29, 8, 47, tzinfo=timezone.utc),
        source="graph",
        attachments=(
            {
                "filename": "Annaberg Checklist and VDR Index 20260629.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size_bytes": 26367,
            },
        ),
    )


def test_build_email_ticket_contract_is_candidate_not_judgment(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_DESK", raising=False)
    ticket = bridge.build_email_ticket(
        _arrival(),
        now=datetime(2026, 6, 29, 9, tzinfo=timezone.utc),
    )

    assert ticket is not None
    assert ticket.source_channel == "email"
    assert ticket.source_id == "AAQk-test-message"
    assert ticket.suspected_matter_slug == "lilienmatt"
    assert ticket.suspected_flight == "aukera-annaberg-financing"
    assert ticket.proposed_desk_slug == "baden-baden-desk"
    assert ticket.urgency_hint == "urgent"
    assert any("attachment:" in item for item in ticket.luggage)
    assert any("did not read or interpret attachments" in item for item in ticket.known_limits)
    assert "VALID" in ticket.known_limits[-1]


def test_non_matching_email_does_not_ticket():
    arrival = _arrival()
    other = bridge.EmailArrival(
        **{**arrival.__dict__, "subject": "Weekly newsletter", "full_body": "No active flight here."}
    )
    assert bridge.build_email_ticket(other) is None


def test_automated_clickup_notification_email_does_not_ticket():
    arrival = _arrival()
    automated = bridge.EmailArrival(
        **{
            **arrival.__dict__,
            "sender_name": "Dimitry Vallen's Workspace",
            "sender_email": "notifications@tasks.clickup.com",
            "subject": "[Overdue] 2. Write financing working brief (room deliverable)",
            "full_body": "Aukera Annaberg financing task is overdue.",
        }
    )
    assert bridge.build_email_ticket(automated) is None


def test_format_ticket_for_bus_includes_check_in_contract():
    ticket = bridge.build_email_ticket(
        _arrival(),
        now=datetime(2026, 6, 29, 9, tzinfo=timezone.utc),
    )
    assert ticket is not None

    body = bridge.format_ticket_for_bus(ticket)

    assert body.startswith("TO: baden-baden-desk\nFROM: ticketing-desk")
    assert "AIRPORT_TICKET v1" in body
    assert "source_id: AAQk-test-message" in body
    assert "Check-in required: reply with VALID, FAKE, DUPLICATE" in body


def test_issue_ticket_duplicate_does_not_post(monkeypatch):
    ticket = bridge.build_email_ticket(_arrival())
    assert ticket is not None
    post = MagicMock()
    monkeypatch.setattr(bridge, "reserve_ticket", lambda conn, ticket: {"reserved": False, "id": 7})
    monkeypatch.setattr(bridge, "post_ticket_to_bus", post)

    out = bridge.issue_ticket(ticket, MagicMock())

    assert out == {"skipped": True, "reason": "duplicate", "id": 7}
    post.assert_not_called()


def test_issue_ticket_marks_sent_after_bus_post(monkeypatch):
    ticket = bridge.build_email_ticket(_arrival())
    assert ticket is not None
    calls = []
    monkeypatch.setattr(bridge, "reserve_ticket", lambda conn, ticket: {"reserved": True, "id": 9})
    monkeypatch.setattr(
        bridge,
        "post_ticket_to_bus",
        lambda ticket: {"ok": True, "message_id": 4588, "thread_id": "thread-4588"},
    )
    monkeypatch.setattr(bridge, "mark_ticket_sent", lambda *a, **kw: calls.append(kw))

    out = bridge.issue_ticket(ticket, MagicMock())

    assert out == {"ok": True, "id": 9, "bus_message_id": 4588}
    assert calls[0]["bus_thread_id"] == "thread-4588"


def test_issue_ticket_marks_failed_when_bus_key_missing(monkeypatch):
    ticket = bridge.build_email_ticket(_arrival())
    assert ticket is not None
    calls = []
    monkeypatch.setattr(bridge, "reserve_ticket", lambda conn, ticket: {"reserved": True, "id": 9})
    monkeypatch.setattr(bridge, "post_ticket_to_bus", lambda ticket: {"ok": False, "error": "ticketing_key_missing"})
    monkeypatch.setattr(bridge, "mark_ticket_failed", lambda *a, **kw: calls.append(kw))

    out = bridge.issue_ticket(ticket, MagicMock())

    assert out == {"ok": False, "reason": "bus_failed", "error": "ticketing_key_missing"}
    assert calls[0]["error"] == "ticketing_key_missing"


def test_run_tick_default_off(monkeypatch):
    monkeypatch.delenv("AIRPORT_TICKETING_BRIDGE_ENABLED", raising=False)
    assert bridge.run_tick() == {"skipped": True, "reason": "AIRPORT_TICKETING_BRIDGE_ENABLED off"}


def test_migration_shape_has_airport_ticket_contract():
    sql = Path("migrations/20260629_airport_tickets.sql").read_text()
    assert "-- == migrate:up ==" in sql
    assert "CREATE TABLE IF NOT EXISTS airport_tickets" in sql
    assert "dedup_key TEXT NOT NULL UNIQUE" in sql
    assert "NEEDS_LUGGAGE_READ" in sql
    assert "idx_airport_tickets_desk_status" in sql
