from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from orchestrator import dispatcher_relay as relay


def _packet_text(owner: str = "baden-baden-desk") -> str:
    return f"""DISPATCHER PACKET
title: Aukera extension papering
owner_slug: {owner}
matter_slug: lilienmatt
flight_type: chartered
due_at: 2026-06-30T09:00:00+00:00
priority: high
condition_precedent:
- Patrick confirms longstop extension in writing
blocked_by:
- Fee letter not read
required_action: confirm extension status and update schedule
source: baden-baden-desk
"""


def _task(**overrides):
    now = datetime(2026, 6, 30, 10, tzinfo=timezone.utc)
    base = {
        "id": "task123",
        "description": _packet_text(),
        "tags": [{"name": "dispatcher"}],
        "status": {"status": "open"},
        "due_date": int((now - timedelta(hours=1)).timestamp() * 1000),
        "date_updated": int((now - timedelta(hours=2)).timestamp() * 1000),
    }
    base.update(overrides)
    return base


def test_dispatch_reason_due_blocked_unblocked_and_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 6, 30, 10, tzinfo=timezone.utc)
    assert relay.dispatch_reason_for_task(_task(), now=now) == "due"
    assert relay.dispatch_reason_for_task(_task(status={"status": "blocked"}), now=now) == "blocked"
    assert relay.dispatch_reason_for_task(_task(status={"status": "ready"}), now=now) == "unblocked"
    future_due = int((now + timedelta(days=3)).timestamp() * 1000)
    old_update = int((now - timedelta(hours=30)).timestamp() * 1000)
    monkeypatch.setenv("DISPATCHER_STALE_HOURS", "24")
    assert relay.dispatch_reason_for_task(_task(due_date=future_due, date_updated=old_update), now=now) == "stale"


def test_post_bus_message_rejects_director_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _request(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setenv("BRISEN_LAB_TERMINAL_KEY_DISPATCHER", "key")
    monkeypatch.setattr(relay, "_request_json", _request)
    out = relay.post_bus_message("director", "body", topic="dispatcher/test")
    assert out == {"ok": False, "error": "invalid_recipient"}
    assert called is False


def test_dispatch_task_sends_once_and_updates_waiting_room(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    conn = MagicMock()

    monkeypatch.setattr(relay, "reserve_dispatch", lambda *a, **kw: {"reserved": True, "id": 9})
    monkeypatch.setattr(relay, "complete_dispatch", lambda *a, **kw: calls.append(("complete", kw)))
    monkeypatch.setattr(relay, "_post_waiting_room", lambda *a, **kw: calls.append(("waiting", kw)))
    monkeypatch.setattr(
        relay,
        "post_bus_message",
        lambda recipient, body, *, topic: calls.append(("bus", recipient, body, topic))
        or {"ok": True, "message_id": 4555, "thread_id": "thread-1"},
    )

    out = relay.dispatch_task(_task(), conn, now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert out["ok"] is True
    assert out["bus_message_id"] == 4555
    assert calls[0][0] == "bus"
    assert calls[0][1] == "baden-baden-desk"
    assert "Condition precedent:" in calls[0][2]
    assert any(c[0] == "complete" for c in calls)
    assert any(c[0] == "waiting" for c in calls)
    complete = [c for c in calls if c[0] == "complete"][0][1]
    assert complete["bus_thread_id"] == "thread-1"


def test_dispatch_task_duplicate_does_not_send_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = MagicMock()
    monkeypatch.setattr(relay, "reserve_dispatch", lambda *a, **kw: {"reserved": False, "id": 9})
    monkeypatch.setattr(relay, "post_bus_message", bus)

    out = relay.dispatch_task(_task(), MagicMock(), now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert out["skipped"] is True
    assert out["reason"] == "duplicate"
    bus.assert_not_called()


def test_bus_failure_is_retryable_for_same_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []
    failed_rows = []
    waiting = []
    conn = MagicMock()
    state = {"failed": False}

    def _reserve(*args, **kwargs):
        if state["failed"]:
            return {"reserved": True, "id": 9, "retry": True}
        return {"reserved": True, "id": 9}

    def _post(*args, **kwargs):
        sent.append(args)
        if not state["failed"]:
            state["failed"] = True
            return {"ok": False, "error": "network"}
        return {"ok": True, "message_id": 4559}

    monkeypatch.setattr(relay, "reserve_dispatch", _reserve)
    monkeypatch.setattr(relay, "mark_dispatch_failed", lambda *a, **kw: failed_rows.append(kw))
    monkeypatch.setattr(relay, "complete_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(relay, "_post_waiting_room", lambda *a, **kw: waiting.append(kw) or None)
    monkeypatch.setattr(relay, "post_bus_message", _post)

    first = relay.dispatch_task(_task(), conn, now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))
    second = relay.dispatch_task(_task(), conn, now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert first == {"ok": False, "reason": "bus_failed", "error": "network"}
    assert second["ok"] is True
    assert len(sent) == 2
    assert failed_rows
    assert waiting


def test_waiting_room_failure_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    marked = []
    monkeypatch.setattr(relay, "reserve_dispatch", lambda *a, **kw: {"reserved": True, "id": 11})
    monkeypatch.setattr(relay, "complete_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(relay, "post_bus_message", lambda *a, **kw: {"ok": True, "message_id": 4560})
    monkeypatch.setattr(relay, "_post_waiting_room", lambda *a, **kw: "waiting db down")
    monkeypatch.setattr(relay, "mark_waiting_room_error", lambda *a, **kw: marked.append(kw))

    out = relay.dispatch_task(_task(), MagicMock(), now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert out["ok"] is True
    assert marked == [{"dispatch_id": 11, "error": "waiting db down"}]


def test_scheduled_packet_does_not_mirror_to_chartered_waiting_room(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.dispatcher import parse_schedule_packet

    text = _packet_text().replace("flight_type: chartered", "flight_type: scheduled")
    packet = parse_schedule_packet(text).packet
    assert packet is not None

    # Scheduled flights are tracked in dispatcher_bus_threads until a scheduled
    # waiting-room rail exists; current waiting-room nudge tick is chartered-only.
    out = relay._post_waiting_room(
        MagicMock(),
        packet=packet,
        clickup_task_id="task123",
        reason_code="due",
        payload={},
    )

    assert out is None


def test_dispatch_due_tasks_respects_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    out = relay.dispatch_due_tasks(MagicMock(), MagicMock())
    assert out == {"skipped": True, "reason": "clickup_readonly"}


def test_process_replies_does_not_ack_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    store = MagicMock()
    store._get_conn.return_value = None
    ack = MagicMock()
    monkeypatch.setattr(relay, "read_dispatcher_inbox", lambda: [{"id": 1}])
    monkeypatch.setattr(relay, "ack_bus_event", ack)

    out = relay.process_replies(client, store)

    assert out == {"skipped": True, "reason": "database_unavailable"}
    client.post_comment.assert_not_called()
    ack.assert_not_called()


def test_reply_without_mapping_does_not_write_or_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    store = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx
    store._get_conn.return_value = conn
    ack = MagicMock()

    monkeypatch.setattr(relay, "read_dispatcher_inbox", lambda: [{"id": 7}])
    monkeypatch.setattr(
        relay,
        "read_bus_event",
        lambda event_id: {
            "id": event_id,
            "body": "ClickUp task: attacker_task\nDONE",
            "from_terminal": "unknown",
        },
    )
    monkeypatch.setattr(relay, "ack_bus_event", ack)

    out = relay.process_replies(client, store)

    assert out == {"ok": True, "processed": 0}
    client.post_comment.assert_not_called()
    ack.assert_not_called()


def test_reply_resolves_task_from_parent_id_before_body() -> None:
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = ("task-parent",)
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx

    task_id = relay.resolve_reply_clickup_task_id(
        conn,
        event={"id": 99, "parent_id": 4555, "thread_id": "thread-1"},
        body="DONE - extension confirmed",
    )

    assert task_id == "task-parent"
    assert "WHERE bus_message_id = %s" in cur.execute.call_args_list[0].args[0]


def test_reply_resolves_task_from_thread_id_when_parent_missing() -> None:
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = [None, ("task-thread",)]
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx

    task_id = relay.resolve_reply_clickup_task_id(
        conn,
        event={"id": 99, "parent_id": 4555, "thread_id": "thread-1"},
        body="DONE",
    )

    assert task_id == "task-thread"


def test_malformed_packet_clarification_is_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []
    conn = MagicMock()
    monkeypatch.setattr(relay, "reserve_dispatch", lambda *a, **kw: {"reserved": True, "id": 15})
    monkeypatch.setattr(relay, "complete_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(relay, "_send_clarification", lambda *a, **kw: sent.append(kw) or {"ok": True, "message_id": 4561})

    bad = _task(description="DISPATCHER PACKET\ntitle: Broken\nsource: baden-baden-desk\n")
    out = relay.dispatch_task(bad, conn, now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert out == {"ok": True, "reason": "needs_clarification"}
    assert sent


def test_duplicate_malformed_packet_does_not_send_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    send = MagicMock()
    monkeypatch.setattr(relay, "reserve_dispatch", lambda *a, **kw: {"reserved": False, "id": 15})
    monkeypatch.setattr(relay, "_send_clarification", send)

    bad = _task(description="DISPATCHER PACKET\ntitle: Broken\nsource: baden-baden-desk\n")
    out = relay.dispatch_task(bad, MagicMock(), now=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))

    assert out["skipped"] is True
    assert out["reason"] == "duplicate_clarification"
    send.assert_not_called()


def test_migration_shape_has_up_marker_and_mapping_table() -> None:
    from pathlib import Path

    sql = Path("migrations/20260628c_dispatcher_clickup_bus_relay.sql").read_text()
    assert "-- == migrate:up ==" in sql
    assert "CREATE TABLE IF NOT EXISTS dispatcher_bus_threads" in sql
    assert "dedup_key TEXT UNIQUE NOT NULL" in sql
    assert "idx_dispatcher_bus_threads_task" in sql
