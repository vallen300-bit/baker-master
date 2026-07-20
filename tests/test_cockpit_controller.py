import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

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


class RefreshingFakeLab:
    def __init__(self, initial, refreshed):
        self.initial = initial
        self.refreshed = refreshed
        self.last_ok = True
        self.read_calls = 0
        self.force_refresh_calls = 0

    async def read(self):
        self.read_calls += 1
        return self.initial

    async def force_refresh(self):
        self.force_refresh_calls += 1
        return self.refreshed


class FailingRefreshFakeLab:
    """Initial authoritative miss followed by a failed forced Lab refresh."""
    def __init__(self):
        self.last_ok = True
        self.force_refresh_calls = 0

    async def read(self):
        return {}

    async def force_refresh(self):
        self.force_refresh_calls += 1
        self.last_ok = False
        return {}


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
                    "wake_obligation_count": 1,
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
                "wake_obligation_count": 1,
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
                "wake_obligation_count": None,
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


def test_api_agents_hydrates_status_only_layout_cards(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings.static_dir.mkdir()
    (settings.static_dir / "cockpit_layout.json").write_text(
        json.dumps(
            {
                "plates": [
                    {
                        "label": "Control Tower",
                        "cards": [
                            {
                                "slug": "codex-arch",
                                "alias": "codex-arch",
                                "status_only": True,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "codex-arch": {
                    "is_working": True,
                    "has_telemetry": True,
                    "unacked_count": 1,
                    "unacked_messages": [{"id": 901, "topic": "review/test"}],
                    "last_message": {"id": 901, "topic": "review/test"},
                    "acked_count": 0,
                }
            }
        ),
        ttyd_prober=_prober(set()),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _s: set())
    monkeypatch.setattr(controller, "tmux_window_activity", lambda _s: {})

    agents = {
        row["slug"]: row
        for row in TestClient(app).get(
            "/api/agents",
            headers={"Host": "127.0.0.1:7800", **_auth()},
        ).json()["agents"]
    }
    assert agents["codex-arch"]["alias"] == "codex-arch"
    assert agents["codex-arch"]["session_up"] is False
    assert agents["codex-arch"]["ttyd_up"] is False
    assert agents["codex-arch"]["unacked_count"] == 1
    assert agents["codex-arch"]["last_message"]["id"] == 901


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
        "wake_obligation_count": 1,
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
    assert glance["wake_obligation_count"] == 1


def test_wake_obligation_count_prefers_server_field_and_falls_back_when_absent():
    # A server-side zero must override the all-message display count.
    assert controller.wake_obligation_count(
        {"unacked_count": 4, "wake_obligation_count": 0}
    ) == 0
    assert controller.wake_skip_reason(
        {
            "unacked_count": 4,
            "wake_obligation_count": 0,
            "unacked_messages": [{"id": 1}],
        }
    ) == "no wake obligation"

    # Older servers have no field: preserve the current unacked-count behavior.
    assert controller.wake_obligation_count({"unacked_count": 4}) == 4
    assert controller.wake_skip_reason(
        {"unacked_count": 4, "unacked_messages": [{"id": 1}]}
    ) is None


def test_wake_row_selection_uses_server_truth_with_legacy_fallback():
    mixed = [
        {
            "id": 10,
            "kind": "broadcast",
            "topic": "fleet/status",
            "created_at": "2026-07-19T08:00:00Z",
            "wake_obligation": False,
        },
        {
            "id": 11,
            "kind": "dispatch",
            "topic": "real/work",
            "created_at": "2026-07-19T09:00:00Z",
            "wake_obligation": True,
        },
    ]
    assert controller._oldest_wake_row(mixed, aggregate_count=1)["id"] == 11

    # A pre-WAKE_FORCE Lab has no per-row marker: preserve legacy selection.
    legacy = [{"id": 20, "created_at": "a"}, {"id": 21, "created_at": "b"}]
    assert controller._oldest_wake_row(legacy)["id"] == 20


def test_aggregate_present_without_row_marker_fails_closed():
    row = {
        "wake_obligation_count": 1,
        "unacked_messages": [{"id": 30, "created_at": "a"}],
    }
    assert controller._oldest_wake_row(
        row["unacked_messages"], aggregate_count=row["wake_obligation_count"]
    ) is None
    assert controller.wake_skip_reason(row) == "no wake obligation message id"


def test_obligation_count_without_authoritative_row_fails_closed():
    """Codex #13735 omitted-row shape: never select a display-only row merely
    because the aggregate says an obligation exists outside the old top-five."""
    row = {
        "unacked_count": 6,
        "wake_obligation_count": 1,
        "unacked_messages": [
            {
                "id": 30,
                "kind": "broadcast",
                "created_at": "a",
                "wake_obligation": False,
            }
        ],
    }
    assert controller._oldest_wake_row(
        row["unacked_messages"], aggregate_count=row["wake_obligation_count"]
    ) is None
    assert controller.wake_skip_reason(row) == "no wake obligation message id"


def test_click_line_lists_only_authoritative_wake_rows():
    row = {
        "unacked_count": 7,
        "wake_obligation_count": 1,
        "unacked_messages": [
            {
                "id": 40,
                "kind": "broadcast",
                "topic": "fleet/status",
                "created_at": "2026-07-19T08:00:00Z",
                "wake_obligation": False,
            },
            {
                "id": 41,
                "kind": "dispatch",
                "topic": "real/work",
                "from_terminal": "lead",
                "created_at": "2026-07-19T09:00:00Z",
                "wake_obligation": True,
            },
        ],
    }
    line = controller.compose_click_wake_line(row)
    assert line == "[wake] check your bus: 1 unacked — #41 real/work (from lead)"
    assert "#40" not in line


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


def _click_wake_app(tmp_path, monkeypatch):
    """A wake app whose send_wake is stubbed to capture the audit_source kwarg."""
    settings = _settings(tmp_path)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {"b3": {"is_working": False, "needs_go": False, "unacked_count": 1,
                    "unacked_messages": [{"id": 1, "topic": "t", "created_at": "z"}]}}
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _s: {"b3"})
    captured = {}

    def fake_send_wake(*args, **kwargs):
        captured["audit_source"] = kwargs.get("audit_source")
        return {"ok": True, "sent": True, "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    return TestClient(app), captured


def test_wake_endpoint_tags_cockpit_click_origin(tmp_path, monkeypatch):
    """COCKPIT_CARD_CLICK_WAKE_INJECT_1 — a card click passes origin=cockpit_click
    through to the wake audit source."""
    client, captured = _click_wake_app(tmp_path, monkeypatch)
    r = client.post("/api/sessions/b3/wake?force=1&origin=cockpit_click",
                    headers={"Host": "127.0.0.1:7800", **_auth()})
    assert r.status_code == 200
    assert captured["audit_source"] == "cockpit_click"


def test_wake_endpoint_rejects_unknown_origin(tmp_path, monkeypatch):
    """A caller-supplied free string is never used as the audit source (allow-list)."""
    client, captured = _click_wake_app(tmp_path, monkeypatch)
    r = client.post("/api/sessions/b3/wake?origin=evil",
                    headers={"Host": "127.0.0.1:7800", **_auth()})
    assert r.status_code == 200
    assert captured["audit_source"] is None


def test_wake_endpoint_rejects_client_spoofed_sweep_origin(tmp_path, monkeypatch):
    """P2c (codex FAIL #13397): a client may claim cockpit_click only. A browser that
    POSTs origin=sweep must NOT forge the internal sweep audit source — it drops to None."""
    client, captured = _click_wake_app(tmp_path, monkeypatch)
    r = client.post("/api/sessions/b3/wake?force=1&origin=sweep",
                    headers={"Host": "127.0.0.1:7800", **_auth()})
    assert r.status_code == 200
    assert captured["audit_source"] is None


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


def test_force_wake_respects_zero_server_wake_obligation(tmp_path, monkeypatch):
    """A click may show ordinary unacked rows but must not wake for them."""
    settings = _settings(tmp_path)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "needs_go": False,
                    "unacked_count": 2,
                    "wake_obligation_count": 0,
                    "unacked_messages": [
                        {
                            "id": 1,
                            "kind": "broadcast",
                            "topic": "heartbeat/fleet",
                            "created_at": "t",
                        }
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})

    response = TestClient(app).post(
        "/api/sessions/b3/wake?force=1&origin=cockpit_click",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "sent": False,
        "disposition": "skipped",
        "reason": "no wake obligation",
        "skipped": "no wake obligation",
        "slug": "b3",
    }


def test_wake_structured_disposition_and_request_receipt(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "unacked_count": 1,
                    "unacked_messages": [
                        {
                            "id": 7,
                            "kind": "dispatch",
                            "topic": "wake/receipt",
                            "created_at": "2026-07-20T00:00:00Z",
                        }
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    monkeypatch.setattr(
        controller,
        "_run_tmux",
        lambda _settings, _args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(
        controller,
        "_verify_wake_submit",
        lambda *_args, **_kwargs: {"verified": "submitted"},
    )

    client = TestClient(app)
    headers = {
        "Host": "127.0.0.1:7800",
        "X-Wake-Request-Id": "rid-structured-7",
        **_auth(),
    }
    response = client.post("/api/sessions/b3/wake", headers=headers)

    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert response.json()["disposition"] == "delivered"
    assert response.json()["reason"] == "delivered"
    receipt = client.get(
        "/api/wake-receipt/rid-structured-7",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert receipt.status_code == 200
    assert receipt.json() == {"landed": True}
    audit = [json.loads(line) for line in settings.wake_audit_path.read_text().splitlines()]
    assert audit[-1]["request_id"] == "rid-structured-7"
    assert audit[-1]["landed"] is True


def test_wake_deadline_returns_undelivered_disposition(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(settings, lab_glance=FakeLab({}))

    def expired(_settings, *, deadline=None):
        raise controller.WakeDeadlineExceeded("test deadline")

    monkeypatch.setattr(controller, "tmux_session_names", expired)
    response = TestClient(app).post(
        "/api/sessions/b3/wake",
        headers={
            "Host": "127.0.0.1:7800",
            "X-Wake-Request-Id": "rid-deadline-7",
            **_auth(),
        },
    )

    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["disposition"] == "undelivered"
    assert response.json()["reason"] == "controller-deadline"
    assert response.json()["skipped"] == "controller-deadline"
    receipt = TestClient(app).get(
        "/api/wake-receipt/rid-deadline-7",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert receipt.json() == {"landed": False}


def test_undelivered_wake_result_keeps_legacy_skipped_reason():
    result = controller._wake_result(
        "undelivered", "controller-deadline", slug="b3"
    )

    assert result["disposition"] == "undelivered"
    assert result["reason"] == "controller-deadline"
    assert result["skipped"] == "controller-deadline"


def test_wake_tmux_probe_timeout_returns_undelivered_disposition(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(settings, lab_glance=FakeLab({}))

    def tmux_probe_timeout(_settings, **kwargs):
        assert kwargs["timeout"] > 0
        raise subprocess.TimeoutExpired(["tmux", "ls"], kwargs["timeout"])

    monkeypatch.setattr(controller.subprocess, "run", tmux_probe_timeout)
    response = TestClient(app).post(
        "/api/sessions/b3/wake",
        headers={
            "Host": "127.0.0.1:7800",
            "X-Wake-Request-Id": "rid-tmux-timeout-7",
            **_auth(),
        },
    )

    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["disposition"] == "undelivered"
    assert response.json()["reason"] == "controller-deadline"


def test_working_skip_rewakes_once_on_idle_transition(tmp_path, monkeypatch):
    settings = _settings(tmp_path)

    class SequencedLab:
        last_ok = True

        def __init__(self):
            self.read_count = 0

        async def read(self):
            self.read_count += 1
            working = self.read_count == 1
            return {
                "b3": {
                    "is_working": working,
                    "unacked_count": 1,
                    "unacked_messages": [{
                        "id": 42,
                        "kind": "dispatch",
                        "topic": "rewake/idle",
                        "created_at": "2026-07-20T00:00:00Z",
                    }],
                }
            }

    lab = SequencedLab()
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return controller._wake_result(
                "skipped", "working", slug="b3", msg_id=42, topic="rewake/idle"
            )
        return controller._wake_result(
            "delivered", "delivered", slug="b3", msg_id=42, topic="rewake/idle"
        )

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    client = TestClient(app)
    first = client.post(
        "/api/sessions/b3/wake",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    assert first.json()["reason"] == "working"

    asyncio.run(app.state.notify_tick())
    asyncio.run(app.state.notify_tick())

    assert len(calls) == 2
    assert calls[1]["audit_source"] == "deferred"


def test_deferred_wake_retains_pending_until_delivered(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    app.state.pending_wakes["b3"] = {"msg_id": 42}
    app.state.wake_prev_working["b3"] = True
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return controller._wake_result(
                "skipped", "seat_floor", slug="b3", msg_id=42, topic="rewake/idle"
            )
        return controller._wake_result(
            "delivered", "delivered", slug="b3", msg_id=42, topic="rewake/idle"
        )

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    row = {
        "is_working": False,
        "wake_obligation_count": 1,
        "unacked_messages": [{"id": 42, "topic": "rewake/idle"}],
    }

    first = asyncio.run(app.state.deferred_wake_tick({"b3": row}))
    assert first[0]["disposition"] == "skipped"
    assert "b3" in app.state.pending_wakes

    app.state.wake_prev_working["b3"] = True
    second = asyncio.run(app.state.deferred_wake_tick({"b3": row}))
    assert second[0]["disposition"] == "delivered"
    assert "b3" not in app.state.pending_wakes


def test_deferred_rewake_runs_when_notifications_disabled(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), notify_enabled=False, notify_poll_seconds=0.01)

    class SequencedLab:
        last_ok = True

        def __init__(self):
            self.read_count = 0

        async def read(self):
            self.read_count += 1
            working = self.read_count <= 2
            return {
                "b3": {
                    "is_working": working,
                    "unacked_count": 1,
                    "unacked_messages": [{"id": 43, "topic": "rewake/disabled"}],
                }
            }

    lab = SequencedLab()
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return controller._wake_result(
                "skipped", "working", slug="b3", msg_id=43, topic="rewake/disabled"
            )
        return controller._wake_result(
            "delivered", "delivered", slug="b3", msg_id=43, topic="rewake/disabled"
        )

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/b3/wake",
            headers={"Host": "127.0.0.1:7800", **_auth()},
        )
        assert response.status_code == 200
        deadline = time.time() + 2.0
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.01)

    assert len(calls) == 2
    assert calls[1]["audit_source"] == "deferred"


def test_wake_endpoint_rechecks_after_stale_no_unacked_glance(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    lab = RefreshingFakeLab(
        {"b3": {"is_working": False, "unacked_count": 0}},
        {
            "b3": {
                "is_working": False,
                "unacked_count": 1,
                "unacked_messages": [
                    {
                        "id": 13129,
                        "kind": "dispatch",
                        "topic": "wake-respawn-backlog-drain-1",
                        "created_at": "2026-07-19T08:00:00Z",
                    }
                ],
            }
        },
    )
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append((args[2], kwargs))
        if len(calls) == 1:
            return {"ok": True, "sent": False, "skipped": "no unacked", "slug": "b3"}
        return {"ok": True, "sent": True, "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    response = TestClient(app).post(
        "/api/sessions/b3/wake",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert lab.force_refresh_calls == 1
    assert len(calls) == 2
    assert calls[1][0]["unacked_count"] == 1


def test_wake_endpoint_rechecks_after_no_telemetry_glance(tmp_path, monkeypatch):
    """A missing row is not an authoritative force/click no-op; refresh once."""
    settings = _settings(tmp_path)
    lab = RefreshingFakeLab(
        {},
        {
            "b3": {
                "is_working": False,
                "unacked_count": 1,
                "unacked_messages": [
                    {
                        "id": 13634,
                        "kind": "dispatch",
                        "topic": "wake-force-authoritative-read-1",
                        "created_at": "2026-07-19T20:07:55Z",
                    }
                ],
            }
        },
    )
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append(args[2])
        if len(calls) == 1:
            return {"ok": True, "sent": False, "skipped": "no telemetry", "slug": "b3"}
        return {"ok": True, "sent": True, "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    response = TestClient(app).post(
        "/api/sessions/b3/wake?force=1&origin=cockpit_click",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert lab.force_refresh_calls == 1
    assert len(calls) == 2
    assert calls[1]["unacked_messages"][0]["id"] == 13634


def test_force_wake_failed_refresh_is_explicit_503(tmp_path, monkeypatch):
    """Lab starvation must never become 200 sent:false/no-telemetry."""
    settings = _settings(tmp_path)
    lab = FailingRefreshFakeLab()
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*_args, **_kwargs):
        calls.append(True)
        return {"ok": True, "sent": False, "skipped": "no telemetry", "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    response = TestClient(app).post(
        "/api/sessions/b3/wake?force=1&origin=cockpit_click",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "wake_state_unknown",
        "slug": "b3",
        "disposition": "undelivered",
        "reason": "lab_glance_unavailable",
        "skipped": "lab_glance_unavailable",
        "sent": False,
    }
    assert lab.force_refresh_calls == 1
    assert len(calls) == 1


def test_lab_glance_failure_stale_serves_all_last_good_rows(tmp_path, monkeypatch):
    """One Lab 503 cannot blank the last-good 28-seat fleet view."""
    settings = replace(_settings(tmp_path), lab_cache_seconds=30.0)
    terminals = [
        {"slug": f"seat-{index}", "unacked_count": index + 1}
        for index in range(28)
    ]
    lab_503 = httpx.HTTPStatusError(
        "simulated Lab 503/read starvation",
        request=httpx.Request("GET", settings.lab_url),
        response=httpx.Response(503),
    )
    outcomes = [
        {"terminals": terminals},
        lab_503,
    ]

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return FakeResponse(outcome)

    monkeypatch.setattr(controller.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    glance = controller.LabGlance(settings)

    first = asyncio.run(glance.read())
    degraded = asyncio.run(glance.force_refresh())

    assert len(first) == 28
    assert degraded == first
    assert len(degraded) == 28
    assert glance.last_ok is False


def test_wake_endpoint_rechecks_after_lean_no_message_id_glance(tmp_path, monkeypatch):
    """P1 (codex FAIL #13397): a card hydrated status-only via /api/agents carries
    unacked_count>0 but unacked_messages=None, so send_wake skips 'no unacked message
    id'. The endpoint must still force a fresh read — which DOES carry the message rows
    — so a Director card click on that lean shape actually wakes the seat."""
    settings = _settings(tmp_path)
    lab = RefreshingFakeLab(
        {"b3": {"is_working": False, "unacked_count": 2, "unacked_messages": None}},
        {
            "b3": {
                "is_working": False,
                "unacked_count": 2,
                "unacked_messages": [
                    {
                        "id": 13416,
                        "kind": "dispatch",
                        "topic": "cockpit-card-click-wake-inject-1",
                        "created_at": "2026-07-19T15:00:00Z",
                    }
                ],
            }
        },
    )
    app = controller.create_app(settings, lab_glance=lab)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append((args[2], kwargs))
        if len(calls) == 1:
            return {"ok": True, "sent": False, "skipped": "no unacked message id", "slug": "b3"}
        return {"ok": True, "sent": True, "slug": "b3"}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)
    response = TestClient(app).post(
        "/api/sessions/b3/wake?force=1&origin=cockpit_click",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert lab.force_refresh_calls == 1
    assert len(calls) == 2
    assert calls[1][0]["unacked_messages"][0]["id"] == 13416


def test_backlog_sweep_tick_wakes_old_idle_session(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), backlog_sweep_seconds=600)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "unacked_count": 1,
                    "oldest_unacked_age_sec": 601,
                    "unacked_messages": [
                        {
                            "id": 13129,
                            "kind": "dispatch",
                            "topic": "wake-respawn-backlog-drain-1",
                            "created_at": "2026-07-19T08:00:00Z",
                        }
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    calls = []

    def fake_send_wake(*args, **kwargs):
        calls.append((args[1].slug, kwargs))
        return {"ok": True, "sent": True, "slug": args[1].slug}

    monkeypatch.setattr(controller, "send_wake", fake_send_wake)

    result = asyncio.run(app.state.backlog_sweep_tick())

    assert result == [{"ok": True, "sent": True, "slug": "b3"}]
    assert len(calls) == 1
    assert calls[0][0] == "b3"
    assert calls[0][1]["audit_source"] == "sweep"


def test_backlog_sweep_ignores_display_only_unacked_without_wake_obligation(
    tmp_path, monkeypatch
):
    """A broadcast/status backlog may stay visible but must not drive re-wake."""
    settings = replace(_settings(tmp_path), backlog_sweep_seconds=600)
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "unacked_count": 3,
                    "wake_obligation_count": 0,
                    "oldest_unacked_age_sec": 601,
                    "unacked_messages": [
                        {
                            "id": 13129,
                            "kind": "broadcast",
                            "topic": "heartbeat/fleet",
                            "created_at": "2026-07-19T08:00:00Z",
                        }
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    monkeypatch.setattr(
        controller,
        "send_wake",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("display-only backlog must not wake")
        ),
    )

    assert asyncio.run(app.state.backlog_sweep_tick()) == []


def test_backlog_sweep_ages_only_authoritative_wake_rows(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), backlog_sweep_seconds=600)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc).timestamp()
    app = controller.create_app(
        settings,
        lab_glance=FakeLab(
            {
                "b3": {
                    "is_working": False,
                    "unacked_count": 2,
                    "wake_obligation_count": 1,
                    # The display-only broadcast is old; the obligation is fresh.
                    "oldest_unacked_age_sec": 3600,
                    "unacked_messages": [
                        {
                            "id": 1,
                            "kind": "broadcast",
                            "topic": "fleet/status",
                            "created_at": "2026-07-20T11:00:00Z",
                            "wake_obligation": False,
                        },
                        {
                            "id": 2,
                            "kind": "dispatch",
                            "topic": "real/work",
                            "created_at": "2026-07-20T11:59:30Z",
                            "wake_obligation": True,
                        },
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(controller.time, "time", lambda: now)
    monkeypatch.setattr(controller, "tmux_session_names", lambda _settings: {"b3"})
    monkeypatch.setattr(
        controller,
        "send_wake",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fresh obligation must not trigger a sweep")
        ),
    )

    assert asyncio.run(app.state.backlog_sweep_tick()) == []


def test_backlog_sweep_tick_is_off_at_zero(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), backlog_sweep_seconds=0)
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    monkeypatch.setattr(
        controller,
        "tmux_session_names",
        lambda _settings: (_ for _ in ()).throw(AssertionError("must stay off")),
    )

    assert asyncio.run(app.state.backlog_sweep_tick()) == []


def test_api_messages_reads_authenticated_preview_and_caches(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), lab_messages_url="https://lab.test/msg")
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    (key_dir / "b3").write_text("seat-key\n", encoding="utf-8")
    settings = replace(settings, lab_key_dir=key_dir)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "messages": [
                    {
                        "id": 17,
                        "from_terminal": "lead",
                        "topic": "cockpit-msg-panel-body-preview-1",
                        "kind": "dispatch",
                        "created_at": "2026-07-19T08:31:28Z",
                        "acknowledged_at": None,
                        "body_preview": "x" * 500,
                    }
                ]
            }

    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params, headers):
            calls.append((url, params, headers))
            return FakeResponse()

    monkeypatch.setattr(
        controller.httpx, "AsyncClient", lambda **_kwargs: FakeClient()
    )
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    client = TestClient(app)

    first = client.get(
        "/api/messages/b3",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    second = client.get(
        "/api/messages/b3",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "https://lab.test/msg/b3"
    assert calls[0][1] == {"limit": 12}
    assert calls[0][2] == {"X-Terminal-Key": "seat-key"}
    payload = first.json()
    assert payload["available"] is True
    assert payload["messages"][0]["acked"] is False
    assert len(payload["messages"][0]["body_preview"]) == 400
    assert "acknowledged_at" not in payload["messages"][0]


def test_api_messages_allows_layout_slug_and_fails_soft_without_key(tmp_path):
    settings = replace(_settings(tmp_path), lab_key_dir=tmp_path / "keys")
    settings.static_dir.mkdir()
    (settings.static_dir / "cockpit_layout.json").write_text(
        json.dumps({"plates": [{"cards": [{"slug": "codex-arch"}]}]}),
        encoding="utf-8",
    )
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    client = TestClient(app)

    response = client.get(
        "/api/messages/codex-arch",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )
    unknown = client.get(
        "/api/messages/not-a-cockpit-seat",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert response.json() == {"available": False, "reason": "no key"}
    assert unknown.status_code == 404


def test_api_messages_upstream_failure_is_panel_safe(tmp_path, monkeypatch):
    settings = replace(_settings(tmp_path), lab_messages_url="https://lab.test/msg")
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    (key_dir / "b3").write_text("seat-key", encoding="utf-8")
    settings = replace(settings, lab_key_dir=key_dir)

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("lab unavailable")

    monkeypatch.setattr(
        controller.httpx, "AsyncClient", lambda **_kwargs: FailingClient()
    )
    app = controller.create_app(settings, lab_glance=FakeLab({}))
    response = TestClient(app).get(
        "/api/messages/b3",
        headers={"Host": "127.0.0.1:7800", **_auth()},
    )

    assert response.status_code == 200
    assert response.json() == {"available": False}


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
