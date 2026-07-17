"""LAB_COCKPIT_NOTIFY_SLICE_1 — controller-side unread-bus notification.

Covers the pure transition detector, the eligible-seat derivation, mute
persistence + gating, the banner command shape, and the mute HTTP endpoints.
All network-free: the pure functions are exercised directly and the endpoint
tests use TestClient WITHOUT a lifespan context, so the background poll task
never starts (it is registered on the startup event only).
"""
import asyncio
import base64
import dataclasses
import json
import time
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


def test_write_mute_propagates_failure(tmp_path, monkeypatch):
    # codex #12354 — write_mute must NOT swallow: a persistence failure has to be
    # surfaceable so the endpoint never reports a false success.
    p = tmp_path / "m.json"
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(controller.Path, "write_text", boom)
    try:
        controller.write_mute(p, True)
        raised = False
    except OSError:
        raised = True
    assert raised is True


# ---- loop path (codex #12354, finding 1) -----------------------------------

class _Flip:
    """Lab stub: first read reports 0 (seeds baseline), later reads report N."""
    def __init__(self, slug, count):
        self.slug, self.count, self.n, self.last_ok = slug, count, 0, True

    async def read(self):
        self.n += 1
        return {self.slug: {"unacked_count": 0 if self.n < 2 else self.count}}


def _seed_layout(settings, slug):
    (settings.static_dir / "cockpit_layout.json").write_text(
        json.dumps(_layout_with([{"slug": slug, "notify_eligible": True}])),
        encoding="utf-8",
    )


def test_notify_tick_fires_once_through_loop(tmp_path, monkeypatch):
    """A 0→N transition must banner exactly once through the real
    read→compute→fire tick path (not just the pure detector)."""
    settings = _settings(tmp_path)
    _seed_layout(settings, "codex-arch")
    app = controller.create_app(settings, lab_glance=_Flip("codex-arch", 4))
    fired = []
    monkeypatch.setattr(
        controller, "notify_macos",
        lambda _cfg, slug, count: fired.append((slug, count)),
    )
    tick = app.state.notify_tick

    async def drive():
        await tick()   # n=1 → count 0 → seed only
        await tick()   # n=2 → count 4 → 0→N fire
        await tick()   # n=3 → still 4 → N→N, no re-fire
    asyncio.run(drive())
    assert fired == [("codex-arch", 4)]


def test_notify_tick_muted_does_not_fire_but_advances_baseline(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_layout(settings, "codex-arch")
    controller.write_mute(settings.notify_mute_path, True)   # muted
    app = controller.create_app(settings, lab_glance=_Flip("codex-arch", 2))
    fired = []
    monkeypatch.setattr(
        controller, "notify_macos",
        lambda _cfg, slug, count: fired.append((slug, count)),
    )
    tick = app.state.notify_tick

    async def drive():
        await tick(); await tick()
    asyncio.run(drive())
    assert fired == []                                        # muted → silent
    assert app.state.notify_prev.get("codex-arch") == 2      # baseline still advanced


def test_lifespan_background_task_fires_on_transition(tmp_path, monkeypatch):
    """The lifespan actually starts the poll loop and it banners a 0→N seat."""
    settings = dataclasses.replace(
        _settings(tmp_path), notify_enabled=True, notify_poll_seconds=0.01
    )
    _seed_layout(settings, "codex-arch")
    fired = []
    monkeypatch.setattr(
        controller, "notify_macos",
        lambda _cfg, slug, count: fired.append((slug, count)),
    )
    app = controller.create_app(settings, lab_glance=_Flip("codex-arch", 5))
    with TestClient(app):                 # __enter__ fires lifespan → starts loop
        deadline = time.time() + 3.0
        while not fired and time.time() < deadline:
            time.sleep(0.02)
    assert ("codex-arch", 5) in fired     # background loop delivered the banner


# ---- mute endpoint write-failure (codex #12354, finding 2) -----------------

def test_mute_endpoint_surfaces_write_failure(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    (settings.static_dir / "cockpit_layout.json").write_text(
        json.dumps(_layout_with([])), encoding="utf-8")
    app = controller.create_app(settings, lab_glance=controller.LabGlance(settings))
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(controller, "write_mute", boom)
    client = TestClient(app)
    r = client.post("/api/notify/mute", json={"muted": True}, headers=_auth())
    assert r.status_code == 500          # false success is a bug; must surface


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
