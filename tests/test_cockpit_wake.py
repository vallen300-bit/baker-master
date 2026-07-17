"""LAB_COCKPIT_REDESIGN_1 D6 — wake-on-open verb: guards, dedupe, audit.

Exercises the pure guard/selection logic and send_wake with a fake tmux runner
so no real tmux/Lab is needed (CI-safe).
"""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import cockpit_controller as controller


def _settings(tmp_path):
    return controller.Settings(
        bind_host="127.0.0.1",
        manifest_path=tmp_path / "m.json",
        credential_path=tmp_path / "cred",
        static_dir=tmp_path / "static",
        fleet_script=tmp_path / "fleet.sh",
        wake_audit_path=tmp_path / "wake_audit.log",
    )


ENTRY = controller.ManifestEntry(slug="b3", alias="b3", port=17603)


@pytest.fixture
def fake_tmux(monkeypatch):
    calls = []

    def _fake(settings, args):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run_tmux", _fake)
    return calls


UNACKED_ROW = {
    "unacked_count": 2,
    "is_working": False,
    "needs_go": False,
    "unacked_messages": [
        {"id": 12063, "topic": "ao-room-architecture", "created_at": "2026-07-16T20:00:00Z"},
        {"id": 12099, "topic": "later-topic", "created_at": "2026-07-17T09:00:00Z"},
    ],
}


def test_oldest_unacked_picks_earliest_created_at():
    assert controller._oldest_unacked(UNACKED_ROW["unacked_messages"]) == (12063, "ao-room-architecture")
    assert controller._oldest_unacked([]) is None
    assert controller._oldest_unacked(None) is None


@pytest.mark.parametrize("row,reason", [
    (None, "no telemetry"),
    ({"needs_go": True, "unacked_count": 3, "unacked_messages": [{"id": 1, "topic": "t", "created_at": "z"}]}, "needs_go (GO flow owns it)"),
    ({"is_working": True, "unacked_count": 3, "unacked_messages": [{"id": 1, "topic": "t", "created_at": "z"}]}, "working"),
    ({"unacked_count": 0}, "no unacked"),
    ({"unacked_count": 2, "unacked_messages": []}, "no unacked message id"),
])
def test_wake_guards_skip(row, reason):
    assert controller.wake_skip_reason(row) == reason


def test_wake_allowed_when_unacked_and_idle():
    assert controller.wake_skip_reason(UNACKED_ROW) is None


def test_send_wake_happy_path_sends_line_and_audits(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=1000.0, last_wake=last)
    assert res["sent"] is True
    assert res["line"] == "check bus #12063 ao-room-architecture"
    # literal line then Enter
    assert fake_tmux[0] == ["send-keys", "-t", "b3", "-l", "check bus #12063 ao-room-architecture"]
    assert fake_tmux[1] == ["send-keys", "-t", "b3", "Enter"]
    assert last["b3"] == 1000.0
    # audit line written
    audited = [json.loads(l) for l in settings.wake_audit_path.read_text().splitlines()]
    assert audited[-1]["slug"] == "b3" and audited[-1]["msg_id"] == 12063


def test_send_wake_dedupes_within_window(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": 900.0}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=900.0 + controller.WAKE_DEDUPE_SECONDS - 1, last_wake=last)
    assert res["sent"] is False and res["skipped"] == "deduped"
    assert fake_tmux == []  # nothing sent


def test_send_wake_fires_again_after_window(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    last = {"b3": 900.0}
    res = controller.send_wake(settings, ENTRY, UNACKED_ROW, now=900.0 + controller.WAKE_DEDUPE_SECONDS + 1, last_wake=last)
    assert res["sent"] is True


def test_send_wake_guarded_seat_is_noop(tmp_path, fake_tmux):
    settings = _settings(tmp_path)
    res = controller.send_wake(settings, ENTRY, {"is_working": True, "unacked_count": 5}, now=1.0, last_wake={})
    assert res["sent"] is False and res["skipped"] == "working"
    assert fake_tmux == []
