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


def test_press_digest_mio_observer_does_not_ticket():
    """TICKETING_BRIDGE_PRESS_DIGEST_EXCLUDE_1 — the MIO OBSERVER daily Pressespiegel
    (mio@observer.at, a media-monitoring vendor digest) carries "Mandarin Oriental" in
    its subject, so it matched the keyword lane and mis-ticketed onto aukera-annaberg
    every morning (bb-desk #8413/#8414 dispose WRONG_TERMINAL). It is not matter mail —
    the sender-skip list must drop it at the automated-sender gate BEFORE the keyword
    match, even when "mandarin oriental" is an ACTIVE keyword (as in prod)."""
    arrival = _arrival()
    digest = bridge.EmailArrival(
        **{
            **arrival.__dict__,
            "sender_name": "MIO OBSERVER",
            "sender_email": "mio@observer.at",
            "subject": "Mandarin Oriental Wien - Ihr OBSERVER Pressespiegel",
            "full_body": "Tagesaktueller Pressespiegel: Mandarin Oriental Wien.",
        }
    )
    assert bridge.build_email_ticket(digest, keywords=("mandarin oriental",)) is None


def test_mio_observer_skip_is_sender_scoped_not_keyword_wide():
    """The cut is surgical (brief: do NOT reroute "mandarin oriental" wholesale). Only the
    digest sender is treated as automated; a legitimate human carrying the same keyword is
    NOT — so the keyword still routes normally for real MO Residences prospects."""
    arrival = _arrival()
    digest = bridge.EmailArrival(**{**arrival.__dict__, "sender_email": "mio@observer.at"})
    human = bridge.EmailArrival(
        **{**arrival.__dict__, "sender_email": "jernej.omahen@example.com",
           "subject": "Re: Your interest in Mandarin Oriental Residences, Vienna"}
    )
    assert bridge._is_automated_email_arrival(digest) is True
    assert bridge._is_automated_email_arrival(human) is False


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


def test_unassigned_review_ticket_uses_neutral_bus_topic(monkeypatch):
    monkeypatch.setattr(bridge, "_sender_matter_set", lambda *a, **k: {"movie", "ao"})
    ticket = bridge.build_email_ticket(
        bridge.EmailArrival(
            message_id="review-message",
            thread_id="review-thread",
            sender_name="Multi-project participant",
            sender_email="participant@example.com",
            subject="Forecast",
            full_body="Numbers for next week",
            received_date=None,
            source="graph",
            participant_fetched=True,
        ),
        conn=object(),
    )
    assert ticket is not None
    assert ticket.suspected_matter_slug == ""
    assert ticket.suspected_flight == ""
    assert "suspected_matter_slug: unknown" in bridge.format_ticket_for_bus(ticket)
    assert "suspected_flight: unknown" in bridge.format_ticket_for_bus(ticket)

    posted = {}
    monkeypatch.setattr(bridge, "_bridge_key", lambda: "test-key")
    monkeypatch.setattr(
        bridge,
        "_request_json",
        lambda method, url, *, key, payload, timeout=15: posted.update(payload) or {},
    )
    result = bridge.post_ticket_to_bus(ticket)

    assert result["ok"] is True
    assert posted["topic"] == "airport-ticketing/review-unassigned"


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
