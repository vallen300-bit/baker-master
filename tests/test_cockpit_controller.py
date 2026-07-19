import base64
import json
from pathlib import Path
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts import cockpit_controller as controller


def _write_fixture(tmp_path: Path, *, rows=None, mode=0o600):
    manifest = tmp_path / "launch_manifest.json"
    manifest.write_text(
        json.dumps({"seats": rows or [
            {"slug": "b3", "alias": "b3", "port": 17603, "eligible": True},
            {"slug": "b4", "alias": "b4", "port": 17604, "eligible": True},
            {"slug": "app", "alias": "app", "port": 17605, "eligible": False},
        ]}),
        encoding="utf-8",
    )
    credential = tmp_path / "credentials"
    credential.write_text("director:secret", encoding="utf-8")
    credential.chmod(mode)
    return manifest, credential


def _settings(tmp_path, *, rows=None, port=7800):
    manifest, credential = _write_fixture(tmp_path, rows=rows)
    return controller.Settings(
        bind_host="127.0.0.1",
        port=port,
        manifest_path=manifest,
        credential_path=credential,
        static_dir=tmp_path / "static",
        fleet_script=tmp_path / "fleet_terminals.sh",
    )


def _auth():
    token = base64.b64encode(b"director:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class FakeLab:
    def __init__(self, rows, *, last_ok=True):
        self.rows = rows
        self.last_ok = last_ok

    async def read(self):
        return self.rows


def _prober(up_slugs):
    """Fake ttyd prober: reports the given slugs as reachable, all others down."""
    up = set(up_slugs)

    async def prober(entry):
        return entry.slug in up

    return prober


def test_api_agents_requires_auth_and_maps_only_pinned_glance_fields(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": True,
                    "has_telemetry": True,
                    "needs_go": False,
                    "unacked_count": 2,
                    "oldest_unacked_age_sec": 700,
                    "unacked_topics": ["review/one"],
                    "body": "must not leak",
                }
            }
        ),
        ttyd_prober=_prober({"b3"}),
    )
    monkeypatch.setattr(
        controller,
        "tmux_session_names",
        lambda _settings: {"b3"},
    )
    # D8: no local activity in this fixture, so is_working comes purely from Lab.
    monkeypatch.setattr(controller, "tmux_window_activity", lambda _settings: {})
    client = TestClient(app)

    assert client.get("/api/agents", headers={"Host": "127.0.0.1:7800"}).status_code == 401
    response = client.get(
        "/api/agents",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert response.status_code == 200
    assert response.json() == {
        "agents": [
            {
                "slug": "b3",
                "alias": "b3",
                "port": 17603,
                "session_up": True,
                "ttyd_up": True,
                "is_working": True,
                "has_telemetry": True,
                "needs_go": False,
                "unacked_count": 2,
                "oldest_unacked_age_sec": 700,
                "unacked_topics": ["review/one"],
                "context_pct": None,
                "unacked_messages": None,
                "last_message": None,
                "acked_count": None,
                "local_working": False,
            },
            {
                "slug": "b4",
                "alias": "b4",
                "port": 17604,
                "session_up": False,
                "ttyd_up": False,
                "is_working": None,
                "has_telemetry": None,
                "needs_go": None,
                "unacked_count": None,
                "oldest_unacked_age_sec": None,
                "unacked_topics": None,
                "context_pct": None,
                "unacked_messages": None,
                "last_message": None,
                "acked_count": None,
                "local_working": False,
            },
        ],
        "lab_glance_ok": True,
    }


def test_tmux_window_activity_parses_batched_output(monkeypatch):
    """D8: one `tmux list-windows -a` call → {slug: last-activity-epoch}, keeping
    the most recent window per session."""
    def fake_run(argv, **_kw):
        assert "list-windows" in argv and "-a" in argv
        out = "b3:1000\nb4:2000\nb3:1500\nbad-line\napp:notanint\n"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    act = controller.tmux_window_activity(_settings_stub())
    assert act == {"b3": 1500, "b4": 2000}  # newest per session; junk dropped


def test_tmux_window_activity_fault_tolerant(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no tmux")
    monkeypatch.setattr(controller.subprocess, "run", boom)
    assert controller.tmux_window_activity(_settings_stub()) == {}


def _settings_stub():
    class S:
        tmux_binary = "tmux"
        command_timeout_seconds = 5
    return S()


def test_d8_local_activity_ors_into_is_working(tmp_path, monkeypatch):
    """D8/AC8: a seat the Lab feed reports NOT working still reads working when
    tmux shows recent output; a stale/absent activity does not."""
    settings = _settings(tmp_path, rows=[
        {"slug": "b3", "alias": "b3", "port": 17603, "eligible": True},
        {"slug": "b4", "alias": "b4", "port": 17604, "eligible": True},
    ])
    app = controller.create_app(
        settings,
        # Lab under-reports: both is_working:false (the Director's D8 defect).
        lab_glance=FakeLab({
            "b3": {"is_working": False, "has_telemetry": False},
            "b4": {"is_working": False, "has_telemetry": False},
        }),
        ttyd_prober=_prober({"b3", "b4"}),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _s: {"b3", "b4"})
    import time as _t
    now = _t.time()
    # b3 produced output 5s ago (working); b4's last output was 5 min ago (quiet).
    monkeypatch.setattr(controller, "tmux_window_activity",
                        lambda _s: {"b3": int(now - 5), "b4": int(now - 300)})
    client = TestClient(app)
    agents = {a["slug"]: a for a in client.get(
        "/api/agents", headers={"Host": "127.0.0.1:7800", **_auth()}).json()["agents"]}
    assert agents["b3"]["local_working"] is True
    assert agents["b3"]["is_working"] is True     # OR'd on despite Lab false
    assert agents["b4"]["local_working"] is False
    assert agents["b4"]["is_working"] is False     # stale activity → not working


def test_derive_context_pct_maps_lab_used_percent():
    # LAB_CONTEXT_BAND_EXPOSURE_1 (#12055): the Lab payload carries usage as
    # ``context_used_percent``; the D4 band renders it as ``context_pct``.
    assert controller.derive_context_pct({"context_used_percent": 73.4}) == 73.4
    # Integer usage flows through as a float.
    assert controller.derive_context_pct({"context_used_percent": 12}) == 12.0


def test_derive_context_pct_null_when_absent_or_stale():
    # No context field at all (seat never heartbeated) → hidden band.
    assert controller.derive_context_pct({"slug": "b3"}) is None
    # Lab nulls its own context fields on a stale/absent row (>900s); that null
    # flows straight through — the consumer invents nothing.
    assert controller.derive_context_pct({"context_used_percent": None}) is None


def test_derive_context_pct_honors_explicit_and_clamps():
    # An explicit ``context_pct`` (should the Lab ever emit one) wins.
    assert controller.derive_context_pct(
        {"context_pct": 40, "context_used_percent": 90}
    ) == 40.0
    # Out-of-range values are clamped to [0, 100] rather than overflowing the bar.
    assert controller.derive_context_pct({"context_used_percent": 140}) == 100.0
    assert controller.derive_context_pct({"context_used_percent": -5}) == 0.0


def test_derive_context_pct_rejects_bool_and_nonnumeric():
    # bool is an int subclass — True must not render as ctx 1%.
    assert controller.derive_context_pct({"context_used_percent": True}) is None
    assert controller.derive_context_pct({"context_used_percent": "80"}) is None


def test_derive_context_pct_rejects_non_finite():
    # NaN/±inf would clamp to a confident ctx 100% (a false full band); non-finite
    # telemetry must hide the band instead (codex #12055 verify — no invention).
    assert controller.derive_context_pct({"context_used_percent": float("nan")}) is None
    assert controller.derive_context_pct({"context_used_percent": float("inf")}) is None
    assert controller.derive_context_pct({"context_used_percent": float("-inf")}) is None


def test_derive_context_pct_never_reads_session_age():
    # HARD RULE (#12055 codex-arch OBJECT): session age is NOT a proxy for
    # context/token consumption and must never populate the context band.
    row = {"session_age_seconds": 9000, "telemetry_age_seconds": 30}
    assert controller.derive_context_pct(row) is None


def test_glance_row_from_lab_projects_pinned_fields_and_context():
    # Full Lab-shaped row: only GLANCE_FIELDS survive (no body leak) and
    # context_pct is derived from context_used_percent.
    lab_row = {
        "slug": "b3",
        "is_working": True,
        "has_telemetry": True,
        "needs_go": False,
        "unacked_count": 1,
        "oldest_unacked_age_sec": 40,
        "unacked_topics": ["ops/x"],
        "unacked_messages": [{"id": 1, "topic": "ops/x", "created_at": "t"}],
        "context_used_percent": 55.0,
        "context_band": "soft",
        "body": "must not leak",
        "session_age_seconds": 9000,
    }
    glance = controller.glance_row_from_lab(lab_row)
    assert set(glance) == set(controller.GLANCE_FIELDS)
    assert "body" not in glance
    assert "context_band" not in glance
    assert glance["context_pct"] == 55.0
    assert glance["unacked_count"] == 1


def test_probe_ttyd_true_for_listening_false_for_closed():
    import asyncio

    async def scenario():
        async def handle(reader, writer):
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            live = await controller.probe_ttyd("127.0.0.1", port, 0.5)
        finally:
            server.close()
            await server.wait_closed()
        # Port is now closed (server torn down).
        dead = await controller.probe_ttyd("127.0.0.1", port, 0.5)
        return live, dead

    live, dead = asyncio.run(scenario())
    assert live is True
    assert dead is False


def test_manifest_consumes_b1_entries_envelope(tmp_path):
    manifest = tmp_path / "launch_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "meta": {"eligible_count": 1},
                "entries": [
                    {
                        "slug": "b3",
                        "alias": "b3",
                        "port": 7608,
                        "eligible": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert controller.load_manifest(manifest) == (
        controller.ManifestEntry(slug="b3", alias="b3", port=7608),
    )


def test_lab_failure_is_fail_soft_and_origin_is_strict(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    class UnavailableLab:
        last_ok = False

        async def read(self):
            return {}

    app = controller.create_app(
        settings, lab_glance=UnavailableLab(), ttyd_prober=_prober(set())
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: set())
    monkeypatch.setattr(controller, "tmux_window_activity", lambda _settings: {})
    client = TestClient(app)
    forged = client.get(
        "/api/agents",
        headers={
            "Host": "127.0.0.1:7800",
            "Origin": "http://evil.local",
            **_auth(),
        },
    )
    assert forged.status_code == 403

    response = client.get(
        "/api/agents",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert response.status_code == 200
    body = response.json()
    # A full Lab outage must surface explicitly, not collapse to silent idle.
    assert body["lab_glance_ok"] is False
    assert all(
        all(agent[field] is None for field in controller.GLANCE_FIELDS)
        for agent in body["agents"]
    )


def test_start_go_are_allowlisted_and_use_exact_tmux_argv(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    client = TestClient(app)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["ls", "-F"]:
            return subprocess.CompletedProcess(argv, 0, "b4\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(controller.subprocess, "run", fake_run)
    start = client.post(
        "/api/sessions/b3/start",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    go = client.post(
        "/api/sessions/b3/go",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    unknown = client.post(
        "/api/sessions/unknown/start",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert start.status_code == 200
    assert go.status_code == 200
    assert go.json() == {"ok": True, "sent": "Enter", "slug": "b3"}
    assert unknown.status_code == 404
    assert calls[1] == [
        "tmux",
        "new-session",
        "-d",
        "-A",
        "-s",
        "b3",
        "/bin/zsh",
        "-lic",
        "b3",
    ]
    assert calls[2] == ["tmux", "send-keys", "-t", "b3", "Enter"]


def test_wake_endpoint_passes_force_query_flag(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "needs_go": False,
                    "unacked_count": 1,
                    "unacked_messages": [
                        {"id": 1, "kind": "dispatch", "topic": "wake/x", "created_at": "t"}
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    captured = {}

    def fake_send_wake(*args, **kwargs):
        captured["force"] = kwargs["force"]
        return {"ok": True, "sent": True, "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    client = TestClient(app)
    response = client.post(
        "/api/sessions/b3/wake?force=1",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert response.status_code == 200
    assert captured["force"] is True


def test_credential_file_must_be_private(tmp_path):
    manifest, credential = _write_fixture(tmp_path, mode=0o644)
    settings = controller.Settings(
        manifest_path=manifest,
        credential_path=credential,
        static_dir=tmp_path / "static",
    )
    app = controller.create_app(settings)
    client = TestClient(app)
    response = client.get(
        "/api/agents",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert response.status_code == 503


def test_http_proxy_rewrites_host_and_origin(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"ttyd"
        headers = httpx.Headers(
            {
                "content-type": "text/plain",
                "content-length": "999",
                "content-encoding": "gzip",
            }
        )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers, content):
            captured.update(method=method, url=url, headers=headers, content=content)
            return FakeResponse()

    monkeypatch.setattr(controller.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    client = TestClient(app)
    response = client.get(
        "/term/b3/",
        headers={
            "Host": "127.0.0.1:7800",
            "Origin": "http://127.0.0.1:7800",
            **_auth(),
        },
    )
    assert response.status_code == 200
    assert captured["url"] == "http://127.0.0.1:17603/term/b3/"
    assert captured["headers"]["Host"] == "127.0.0.1:17603"
    assert captured["headers"]["Origin"] == "http://127.0.0.1:17603"
    assert response.headers["content-length"] == "4"
    assert "content-encoding" not in response.headers


def test_static_root_is_inside_the_single_basic_auth_origin(tmp_path):
    settings = _settings(tmp_path)
    settings.static_dir.mkdir()
    (settings.static_dir / "index.html").write_text("cockpit", encoding="utf-8")
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    client = TestClient(app)

    assert client.get(
        "/",
        headers={"Host": "127.0.0.1:7800"},
    ).status_code == 401
    response = client.get(
        "/",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert response.status_code == 200
    assert response.text == "cockpit"
