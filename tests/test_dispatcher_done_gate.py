"""DISPATCHER_HARNESS_RETROFIT_1 — seeded-violation + done-gate tests.

Machine-checkable evidence for the Dispatcher (ClickUp Super Agent lane) harness
retrofit:

  * AC4 — B4 deterministic done-gate: a dispatched task is re-fetched by ID and
    confirmed at the declared BAKER-space list; a fabricated/absent id FAILS.
  * AC3 — B2 cage (seeded violations): a ClickUp write whose target resolves to a
    NON-BAKER space is REJECTED (no comment written); an 11th write in a cycle is
    REJECTED by the per-cycle cap.
  * AC5 — B7 kill switch flips writes off/on in both directions.

All rejects/fails are exercised against the real guard code (clickup_client cap +
kill switch) or the real gate helper — no prose-only assertions.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestrator import dispatcher_relay as relay

_BAKER_SPACE = "901510186446"
_DECLARED_LIST = "901500000001"  # stand-in for DISPATCHER_CLICKUP_LIST_ID


class _FakeClient:
    """Minimal ClickUp client double: get_task_detail returns a scripted map,
    post_comment records calls so a REJECT can be proven as 'no write'."""

    def __init__(self, details: dict):
        self._details = details  # task_id -> detail dict (or missing -> None)
        self.posted: list = []

    def get_task_detail(self, task_id: str):
        return self._details.get(task_id)

    def post_comment(self, task_id: str, comment: str):
        self.posted.append((task_id, comment))
        return {"id": "cmt-1"}


def _detail(task_id: str, *, list_id: str = _DECLARED_LIST, space_id: str = _BAKER_SPACE) -> dict:
    return {"id": task_id, "list": {"id": list_id}, "space": {"id": space_id}}


# --------------------------------------------------------------------------- #
# AC4 — B4 deterministic done-gate (re-fetch by ID + confirm at declared list)
# --------------------------------------------------------------------------- #
def test_ac4_gate_passes_for_real_task_at_declared_list():
    client = _FakeClient({"task-1": _detail("task-1")})
    out = relay.dispatch_done_gate(client, "task-1", expected_list_id=_DECLARED_LIST)
    assert out == {"ok": True, "reason": "confirmed"}, out


def test_ac4_gate_fails_for_fabricated_absent_task():
    client = _FakeClient({})  # get_task_detail -> None
    out = relay.dispatch_done_gate(client, "ghost-999", expected_list_id=_DECLARED_LIST)
    assert out["ok"] is False and out["reason"] == "task_absent", out


def test_ac4_gate_fails_for_wrong_list():
    client = _FakeClient({"task-2": _detail("task-2", list_id="900999999999")})
    out = relay.dispatch_done_gate(client, "task-2", expected_list_id=_DECLARED_LIST)
    assert out["ok"] is False and out["reason"].startswith("wrong_list"), out


def test_ac4_gate_fails_for_id_mismatch():
    client = _FakeClient({"task-3": _detail("SOMETHING-ELSE")})
    out = relay.dispatch_done_gate(client, "task-3", expected_list_id=_DECLARED_LIST)
    assert out["ok"] is False and out["reason"].startswith("id_mismatch"), out


def test_ac4_gate_fails_when_refetch_errors():
    client = MagicMock()
    client.get_task_detail.side_effect = RuntimeError("clickup down")
    out = relay.dispatch_done_gate(client, "task-4", expected_list_id=_DECLARED_LIST)
    assert out["ok"] is False and out["reason"].startswith("refetch_error"), out


def test_ac4_gate_requires_declared_list():
    client = _FakeClient({"task-5": _detail("task-5")})
    out = relay.dispatch_done_gate(client, "task-5", expected_list_id="")
    assert out["ok"] is False and out["reason"] == "no_declared_list", out


# --------------------------------------------------------------------------- #
# AC3 — B2 cage seeded violations
# --------------------------------------------------------------------------- #
def test_ac3_gate_rejects_non_baker_space():
    # task sits at the declared list id but resolves to a NON-BAKER space.
    client = _FakeClient({"task-x": _detail("task-x", space_id="777777777777")})
    out = relay.dispatch_done_gate(client, "task-x", expected_list_id=_DECLARED_LIST)
    assert out["ok"] is False and out["reason"].startswith("non_baker_space"), out


def test_ac3_process_replies_rejects_out_of_cage_target_no_write(monkeypatch: pytest.MonkeyPatch):
    """A dispatcher reply whose target is out of cage is REJECTED before any write —
    post_comment is never called, the message is not acked."""
    monkeypatch.setenv(relay._LIST_ID_ENV, _DECLARED_LIST)
    client = _FakeClient(
        {"attacker-task": _detail("attacker-task", list_id="900000000000", space_id="777777777777")}
    )
    store = MagicMock()
    store._get_conn.return_value = MagicMock()  # truthy conn -> enter the reply loop

    monkeypatch.setattr(relay, "read_dispatcher_inbox", lambda: [{"id": 11, "from_terminal": "x"}])
    monkeypatch.setattr(relay, "read_bus_event", lambda eid: {"id": eid, "body": "DONE", "from_terminal": "x"})
    monkeypatch.setattr(relay, "resolve_reply_clickup_task_id", lambda *a, **k: "attacker-task")
    ack = MagicMock()
    monkeypatch.setattr(relay, "ack_bus_event", ack)

    out = relay.process_replies(client, store)

    assert out == {"ok": True, "processed": 0}, out
    assert client.posted == [], "out-of-cage target must NOT be written"
    ack.assert_not_called()


def test_ac3_process_replies_allows_in_cage_target(monkeypatch: pytest.MonkeyPatch):
    """Control: an in-cage, real target at the declared list DOES get the comment
    (proves the gate is not a blanket block)."""
    monkeypatch.setenv(relay._LIST_ID_ENV, _DECLARED_LIST)
    client = _FakeClient({"good-task": _detail("good-task")})
    store = MagicMock()
    store._get_conn.return_value = MagicMock()

    monkeypatch.setattr(relay, "read_dispatcher_inbox", lambda: [{"id": 12, "from_terminal": "x"}])
    monkeypatch.setattr(relay, "read_bus_event", lambda eid: {"id": eid, "body": "DONE", "from_terminal": "x"})
    monkeypatch.setattr(relay, "resolve_reply_clickup_task_id", lambda *a, **k: "good-task")
    monkeypatch.setattr(relay, "record_reply", lambda *a, **k: None)
    monkeypatch.setattr(relay, "ack_bus_event", lambda *a, **k: True)

    out = relay.process_replies(client, store)

    assert out == {"ok": True, "processed": 1}, out
    assert [t for t, _ in client.posted] == ["good-task"]


def test_ac3_eleventh_write_in_cycle_rejected(monkeypatch: pytest.MonkeyPatch):
    """The existing per-cycle cap REJECTS the 11th write — real RuntimeError."""
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    from clickup_client import ClickUpClient, _MAX_WRITES_PER_CYCLE

    c = ClickUpClient()
    c.reset_cycle_counter()
    for _ in range(_MAX_WRITES_PER_CYCLE):  # 10 writes allowed
        c._check_write_allowed(_BAKER_SPACE, "post_comment")
        c._cycle_write_count += 1
    with pytest.raises(RuntimeError, match="Max writes per cycle"):
        c._check_write_allowed(_BAKER_SPACE, "post_comment")  # 11th REJECTED


# --------------------------------------------------------------------------- #
# AC5 — B7 kill switch flip (both directions)
# --------------------------------------------------------------------------- #
def test_ac5_kill_switch_flip_both_directions(monkeypatch: pytest.MonkeyPatch):
    from clickup_client import ClickUpClient

    c = ClickUpClient()
    c.reset_cycle_counter()
    # ON -> writes stop
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    with pytest.raises(RuntimeError, match="kill switch"):
        c._check_write_allowed(_BAKER_SPACE, "post_comment")
    # OFF -> writes resume (no raise)
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "false")
    c._check_write_allowed(_BAKER_SPACE, "post_comment")
