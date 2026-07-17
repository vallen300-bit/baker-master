"""LAB_COCKPIT_NOTIFY_SLICE_1 — controller-side unread-bus notification.

Covers the pure transition detector, the eligible-seat derivation, mute
persistence + gating, the banner command shape, and the mute HTTP endpoints.
All network-free: the pure functions are exercised directly and the endpoint
tests use TestClient WITHOUT a lifespan context, so the background poll task
never starts (it is registered on the startup event only).
"""
import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts import cockpit_controller as controller

REPO_LAYOUT = Path("scripts/cockpit_static/cockpit_layout.json")


# ---- fixtures ---------------------------------------------------------------

def _write_fixture(tmp_path):
    manifest = tmp_path / "launch_manifest.json"
    manifest.write_text(
        json.dumps({"seats": [
            {"slug": "b3", "alias": "b3", "port": 17603, "eligible": True},
        ]}),
        encoding="utf-8",
    )
    credential = tmp_path / "credentials"
    credential.write_text("director:secret", encoding="utf-8")
    credential.chmod(0o600)
    return manifest, credential


def _settings(tmp_path):
    manifest, credential = _write_fixture(tmp_path)
    static = tmp_path / "static"
    static.mkdir()
    return controller.Settings(
        bind_host="127.0.0.1",
        port=7800,
        manifest_path=manifest,
        credential_path=credential,
        static_dir=static,
        fleet_script=tmp_path / "fleet_terminals.sh",
        notify_mute_path=tmp_path / "notify_mute.json",
        notify_enabled=False,  # never spawn the background loop under test
    )


def _auth():
    token = base64.b64encode(b"director:secret").decode("ascii")
    return {"Authorization": f"Basic {token}", "Host": "127.0.0.1:7800"}


def _layout_with(cards):
    return {"plates": [{"label": "P", "cards": cards}]}


# ---- eligible-seat derivation ----------------------------------------------

def test_load_notify_seats_reads_flag_from_layout(tmp_path):
    static = tmp_path / "s"
    static.mkdir()
    (static / "cockpit_layout.json").write_text(json.dumps(_layout_with([
        {"slug": "codex-arch", "notify_eligible": True},
        {"slug": "cowork-hag-desk", "notify_eligible": True},
        {"slug": "b1", "notify_eligible": False},
        {"slug": "cowork-ah1", "notify_eligible": False},
        {"slug": "cortex"},  # missing flag → excluded
    ])), encoding="utf-8")
    assert controller.load_notify_seats(static) == {"codex-arch", "cowork-hag-desk"}


def test_load_notify_seats_missing_or_bad_file_is_empty(tmp_path):
    assert controller.load_notify_seats(tmp_path / "nope") == set()
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "cockpit_layout.json").write_text("{not json", encoding="utf-8")
    assert controller.load_notify_seats(bad) == set()


def test_committed_layout_matches_approved_classifier():
    """The generated, committed layout must carry the lead-approved fired-set
    (bus #12332): codex-arch + wakeable:false cowork desks fire; self-awake
    terminals (b1) and Wake.app-covered app-claude (cowork-ah1, ben) do not."""
    raw = json.loads(REPO_LAYOUT.read_text("utf-8"))
    flag = {}
    for plate in raw["plates"]:
        for card in plate["cards"]:
            flag[card["slug"]] = bool(card.get("notify_eligible"))
    assert flag.get("codex-arch") is True
    assert flag.get("cowork-hag-desk") is True
    assert flag.get("b1") is False
    assert flag.get("cowork-ah1") is False
    assert flag.get("ben") is False


# ---- transition detector ----------------------------------------------------

def test_first_observation_only_seeds_no_fire():
    fire, prev, last = controller.compute_notifications(
        {}, {"codex-arch": {"unacked_count": 3}}, {"codex-arch"}, {},
        now=100.0, cooldown=300.0,
    )
    assert fire == []                 # startup backlog must not banner
    assert prev == {"codex-arch": 3}


def test_zero_to_n_fires():
    fire, prev, last = controller.compute_notifications(
        {"codex-arch": 0}, {"codex-arch": {"unacked_count": 2}}, {"codex-arch"}, {},
        now=100.0, cooldown=300.0,
    )
    assert fire == [("codex-arch", 2)]
    assert last["codex-arch"] == 100.0


def test_n_to_n_plus_one_does_not_fire():
    fire, _p, _l = controller.compute_notifications(
        {"codex-arch": 1}, {"codex-arch": {"unacked_count": 2}}, {"codex-arch"},
        {"codex-arch": 90.0}, now=100.0, cooldown=300.0,
    )
    assert fire == []


def test_ack_to_zero_then_new_message_refires():
    # N → 0 (acked)
    _f, prev, _l = controller.compute_notifications(
        {"codex-arch": 2}, {"codex-arch": {"unacked_count": 0}}, {"codex-arch"}, {},
        now=100.0, cooldown=300.0,
    )
    assert prev["codex-arch"] == 0
    # 0 → 1 later, past cooldown → fires again
    fire, _p, _l = controller.compute_notifications(
        prev, {"codex-arch": {"unacked_count": 1}}, {"codex-arch"}, {},
        now=500.0, cooldown=300.0,
    )
    assert fire == [("codex-arch", 1)]


def test_cooldown_suppresses_refire():
    fire, _p, _l = controller.compute_notifications(
        {"codex-arch": 0}, {"codex-arch": {"unacked_count": 1}}, {"codex-arch"},
        {"codex-arch": 100.0}, now=200.0, cooldown=300.0,  # 100s < 300s cooldown
    )
    assert fire == []


def test_only_eligible_seats_fire():
    fire, _p, _l = controller.compute_notifications(
        {"b1": 0, "codex-arch": 0},
        {"b1": {"unacked_count": 5}, "codex-arch": {"unacked_count": 1}},
        {"codex-arch"},  # b1 not eligible
        {}, now=100.0, cooldown=300.0,
    )
    assert fire == [("codex-arch", 1)]


# ---- mute persistence + gating ---------------------------------------------

def test_mute_roundtrip_and_default(tmp_path):
    p = tmp_path / "m.json"
    assert controller.read_mute(p) is False           # default (no file) = on
    controller.write_mute(p, True)
    assert controller.read_mute(p) is True
    controller.write_mute(p, False)
    assert controller.read_mute(p) is False


def test_mute_corrupt_file_reads_unmuted(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("garbage", encoding="utf-8")
    assert controller.read_mute(p) is False           # corrupt never silences


# ---- banner command shape ---------------------------------------------------

def test_notify_macos_osascript_names_seat_and_count(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.shutil, "which", lambda _n: None)  # force osascript
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0
        return R()
    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    controller.notify_macos(_settings(tmp_path), "codex-arch", 3)
    joined = " ".join(captured["cmd"])
    assert captured["cmd"][0] == "osascript"
    assert "codex-arch" in joined and "3 unread" in joined


def test_notify_macos_prefers_terminal_notifier(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.shutil, "which", lambda _n: "/usr/local/bin/terminal-notifier")
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0
        return R()
    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    controller.notify_macos(_settings(tmp_path), "cowork-hag-desk", 1)
    assert captured["cmd"][0].endswith("terminal-notifier")
    assert "cowork-hag-desk" in " ".join(captured["cmd"])
    assert "1 unread bus message" in " ".join(captured["cmd"])  # singular


def test_notify_macos_never_raises_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(controller.shutil, "which", lambda _n: None)
    def boom(*a, **k):
        raise OSError("no such binary")
    monkeypatch.setattr(controller.subprocess, "run", boom)
    controller.notify_macos(_settings(tmp_path), "codex-arch", 2)  # must not raise


# ---- HTTP endpoints ---------------------------------------------------------

def test_mute_endpoints_persist_and_hydrate(tmp_path):
    settings = _settings(tmp_path)
    # seed a layout so /api/notify/state reports the eligible set
    (settings.static_dir / "cockpit_layout.json").write_text(
        json.dumps(_layout_with([
            {"slug": "codex-arch", "notify_eligible": True},
            {"slug": "b1", "notify_eligible": False},
        ])), encoding="utf-8")
    app = controller.create_app(settings, lab_glance=controller.LabGlance(settings))
    client = TestClient(app)

    # auth required
    assert client.get("/api/notify/state").status_code == 401

    state = client.get("/api/notify/state", headers=_auth()).json()
    assert state["muted"] is False
    assert state["eligible"] == ["codex-arch"]

    r = client.post("/api/notify/mute", json={"muted": True}, headers=_auth())
    assert r.status_code == 200 and r.json()["muted"] is True
    assert controller.read_mute(settings.notify_mute_path) is True
    assert client.get("/api/notify/state", headers=_auth()).json()["muted"] is True

    client.post("/api/notify/mute", json={"muted": False}, headers=_auth())
    assert controller.read_mute(settings.notify_mute_path) is False
