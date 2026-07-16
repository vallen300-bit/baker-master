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
    def __init__(self, rows):
        self.rows = rows

    async def read(self):
        return self.rows


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
    )
    monkeypatch.setattr(
        controller,
        "tmux_session_names",
        lambda _settings: {"b3"},
    )
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
                "is_working": True,
                "has_telemetry": True,
                "needs_go": False,
                "unacked_count": 2,
                "oldest_unacked_age_sec": 700,
                "unacked_topics": ["review/one"],
            },
            {
                "slug": "b4",
                "alias": "b4",
                "port": 17604,
                "session_up": False,
                "is_working": None,
                "has_telemetry": None,
                "needs_go": None,
                "unacked_count": None,
                "oldest_unacked_age_sec": None,
                "unacked_topics": None,
            },
        ]
    }


def test_lab_failure_is_fail_soft_and_origin_is_strict(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    class UnavailableLab:
        async def read(self):
            return {}

    app = controller.create_app(settings, lab_glance=UnavailableLab())
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: set())
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
    assert all(
        all(agent[field] is None for field in controller.GLANCE_FIELDS)
        for agent in response.json()["agents"]
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
        headers = httpx.Headers({"content-type": "text/plain"})

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
