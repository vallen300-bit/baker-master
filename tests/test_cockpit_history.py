"""Tests for COCKPIT_REVAMP_HISTORY_TAB_VERDICT_CARDS_1 (revamp items 8+9).

TDD seams (brief §Engineering Craft Gates):
  * classify_verdict(body) -> "pass" | "fail" | None   (pure)
  * build_history_jobs(messages) -> list                (pure)
  * GET /api/history                                    (route, Lab fetch faked)
"""

import base64
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts import cockpit_controller as controller


# ---------------------------------------------------------------------------
# Shared harness (mirrors tests/test_cockpit_controller.py)
# ---------------------------------------------------------------------------
def _write_fixture(tmp_path: Path):
    manifest = tmp_path / "launch_manifest.json"
    manifest.write_text(
        json.dumps({"seats": [
            {"slug": "b3", "alias": "b3", "port": 17603, "eligible": True},
            {"slug": "b4", "alias": "b4", "port": 17604, "eligible": True},
        ]}),
        encoding="utf-8",
    )
    credential = tmp_path / "credentials"
    credential.write_text("director:secret", encoding="utf-8")
    credential.chmod(0o600)
    return manifest, credential


def _settings(tmp_path, *, lab_key_dir=None):
    manifest, credential = _write_fixture(tmp_path)
    base = controller.Settings(
        bind_host="127.0.0.1",
        port=7800,
        manifest_path=manifest,
        credential_path=credential,
        static_dir=tmp_path / "static",
        fleet_script=tmp_path / "fleet_terminals.sh",
    )
    if lab_key_dir is not None:
        base = replace(base, lab_key_dir=lab_key_dir)
    return base


def _auth():
    token = base64.b64encode(b"director:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class FakeLab:
    def __init__(self, rows=None, *, last_ok=True):
        self.rows = rows or {}
        self.last_ok = last_ok

    async def read(self):
        return self.rows


def _prober(up=()):
    up = set(up)

    async def prober(entry):
        return entry.slug in up

    return prober


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class _FakeClient:
    """Async-context httpx.AsyncClient stand-in returning a canned payload,
    or raising a supplied exception, on .get()."""
    def __init__(self, *, payload=None, exc=None):
        self._payload = payload
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._payload)


def _patch_lab(monkeypatch, *, payload=None, exc=None):
    def _factory(*args, **kwargs):
        return _FakeClient(payload=payload, exc=exc)
    monkeypatch.setattr(controller.httpx, "AsyncClient", _factory)


def _key_dir(tmp_path, slug="lead", value="seat-key"):
    d = tmp_path / "keys"
    d.mkdir(parents=True, exist_ok=True)
    (d / slug).write_text(value, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Feature 2 (item 9): classify_verdict
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body, expected",
    [
        ("codex verdict: PASS on exact HEAD abc123", "pass"),
        ("PASS-WITH-NOTE — minor nit on naming", "pass"),
        ("PASS-WITH-NOTES: two follow-ups filed", "pass"),
        ("LGTM, ship it", "pass"),
        ("Approved for merge", "pass"),
        ("REQUEST CHANGES: XSS on the preview render", "fail"),
        ("REQUEST_CHANGES — same class as above", "fail"),
        ("FAIL: route 500s on Lab-down", "fail"),
        ("FAILED the no-blur AC", "fail"),
        ("REJECTED — wrong base commit", "fail"),
        ("BLOCKED on the sequencing gate", "fail"),
        ("first FAIL then a later PASS after the fix", "fail"),
        ("PASS overall, no FAIL markers of concern", "pass"),
        ("routine heartbeat, no verdict here", None),
        ("", None),
        (None, None),
        ("the COMPASS points north; BYPASSED the check", None),
    ],
)
def test_classify_verdict(body, expected):
    assert controller.classify_verdict(body) == expected


def test_classify_verdict_only_reads_head_400_chars():
    body = ("x" * 500) + " PASS"
    assert controller.classify_verdict(body) is None


# ---------------------------------------------------------------------------
# Feature 1 (item 8): build_history_jobs
# ---------------------------------------------------------------------------
def _msg(id, *, thread_id=None, topic=None, from_terminal="lead",
         body=None, body_preview=None, created_at=None):
    return {
        "id": id,
        "thread_id": thread_id,
        "topic": topic,
        "kind": "dispatch",
        "from_terminal": from_terminal,
        "to_terminals": ["lead"],
        "body": body,
        "body_preview": body_preview,
        "created_at": created_at,
        "acknowledged_at": None,
    }


def test_build_history_jobs_groups_by_thread_and_derives_verdict():
    msgs = [
        _msg(1, thread_id="T1", topic="review/ctx-bars", from_terminal="lead",
             body="DISPATCH ctx-bars", created_at="2026-07-20T10:00:00+00:00"),
        _msg(2, thread_id="T1", topic="review/ctx-bars", from_terminal="b2",
             body="STARTED", created_at="2026-07-20T10:05:00+00:00"),
        _msg(3, thread_id="T1", topic="review/ctx-bars", from_terminal="codex",
             body="codex verdict: PASS on HEAD 030dc07b",
             created_at="2026-07-20T10:30:00+00:00"),
    ]
    jobs = controller.build_history_jobs(msgs)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["key"] == "T1"
    assert job["topic"] == "review/ctx-bars"
    assert job["seat"] == "codex"     # latest non-lead from_terminal
    assert job["started_at"] == "2026-07-20T10:00:00+00:00"
    assert job["ended_at"] == "2026-07-20T10:30:00+00:00"
    assert job["duration_sec"] == 1800
    assert job["status"] == "done"
    assert job["outcome"] == "pass"
    assert job["msg_ids"] == [1, 2, 3]
    assert len(job["last_preview"]) <= 160


def test_build_history_jobs_classifies_from_body_preview_field():
    # The Lab LIST endpoint returns body_preview (body is null there); the
    # verdict must still classify off body_preview.
    msgs = [
        _msg(5, thread_id="TP", topic="gate/y", from_terminal="codex",
             body=None, body_preview="codex: PASS clean",
             created_at="2026-07-20T11:00:00+00:00"),
    ]
    job = controller.build_history_jobs(msgs)[0]
    assert job["outcome"] == "pass"
    assert job["status"] == "done"


def test_build_history_jobs_in_flight_when_no_verdict():
    msgs = [
        _msg(10, thread_id="T2", topic="build/foo", from_terminal="lead",
             body="DISPATCH foo", created_at="2026-07-20T09:00:00+00:00"),
        _msg(11, thread_id="T2", topic="build/foo", from_terminal="b3",
             body="STARTED foo", created_at="2026-07-20T09:02:00+00:00"),
    ]
    job = controller.build_history_jobs(msgs)[0]
    assert job["status"] == "in-flight"
    assert job["outcome"] is None
    assert job["ended_at"] is None
    assert job["duration_sec"] is None
    assert job["seat"] == "b3"


def test_build_history_jobs_fail_wins_and_uses_latest_verdict():
    msgs = [
        _msg(20, thread_id="T3", topic="gate/x", from_terminal="codex",
             body="FAIL: request changes", created_at="2026-07-20T08:00:00+00:00"),
        _msg(21, thread_id="T3", topic="gate/x", from_terminal="codex",
             body="PASS after fix", created_at="2026-07-20T08:40:00+00:00"),
    ]
    job = controller.build_history_jobs(msgs)[0]
    assert job["outcome"] == "pass"
    assert job["ended_at"] == "2026-07-20T08:40:00+00:00"


def test_build_history_jobs_groups_untopiced_by_id_when_no_thread():
    msgs = [
        _msg(30, thread_id=None, topic=None, from_terminal="b1",
             body="loose msg", created_at="2026-07-20T07:00:00+00:00"),
        _msg(31, thread_id=None, topic="build/bar", from_terminal="b1",
             body="topiced loose", created_at="2026-07-20T07:01:00+00:00"),
    ]
    keys = {j["key"] for j in controller.build_history_jobs(msgs)}
    assert "untopiced-30" in keys
    assert "build/bar" in keys


def test_build_history_jobs_sorted_newest_first():
    msgs = [
        _msg(40, thread_id="OLD", topic="a", created_at="2026-07-19T00:00:00+00:00"),
        _msg(41, thread_id="NEW", topic="b", created_at="2026-07-20T00:00:00+00:00"),
    ]
    jobs = controller.build_history_jobs(msgs)
    assert [j["key"] for j in jobs] == ["NEW", "OLD"]


def test_build_history_jobs_skips_malformed_never_raises():
    msgs = [
        {"id": 50, "thread_id": "T", "topic": "ok", "from_terminal": "lead",
         "body": "fine", "created_at": "2026-07-20T06:00:00+00:00"},
        {"id": 51, "thread_id": "T", "topic": "ok"},          # no created_at
        {"id": 52},                                            # near-empty
        "not-a-dict",                                          # junk
    ]
    jobs = controller.build_history_jobs(msgs)
    assert len(jobs) == 1
    assert jobs[0]["msg_ids"] == [50]


def test_build_history_jobs_limit_caps_rows():
    msgs = [
        _msg(60 + i, thread_id=f"T{i}", topic="t",
             created_at=f"2026-07-20T0{i}:00:00+00:00")
        for i in range(5)
    ]
    assert len(controller.build_history_jobs(msgs, limit=2)) == 2
    assert len(controller.build_history_jobs(msgs)) == 5


def test_build_history_jobs_empty_and_non_list():
    assert controller.build_history_jobs([]) == []
    assert controller.build_history_jobs(None) == []


# ---------------------------------------------------------------------------
# Route: GET /api/history
# ---------------------------------------------------------------------------
def test_api_history_requires_auth(tmp_path, monkeypatch):
    settings = _settings(tmp_path, lab_key_dir=_key_dir(tmp_path))
    app = controller.create_app(settings, lab_glance=FakeLab(), ttyd_prober=_prober())
    _patch_lab(monkeypatch, payload={"messages": []})
    client = TestClient(app)
    assert client.get(
        "/api/history", headers={"Host": "127.0.0.1:7800"}
    ).status_code == 401


def test_api_history_returns_jobs_from_lead_stream(tmp_path, monkeypatch):
    settings = _settings(tmp_path, lab_key_dir=_key_dir(tmp_path))
    app = controller.create_app(settings, lab_glance=FakeLab(), ttyd_prober=_prober())
    payload = {"messages": [
        {"id": 1, "thread_id": "A", "topic": "ship/history",
         "from_terminal": "b2", "body_preview": "codex: PASS",
         "created_at": "2026-07-20T10:00:00+00:00", "acknowledged_at": None},
    ]}
    _patch_lab(monkeypatch, payload=payload)
    client = TestClient(app)
    resp = client.get(
        "/api/history?limit=20", headers={"Host": "127.0.0.1:7800", **_auth()}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stale"] is False
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["topic"] == "ship/history"
    assert data["jobs"][0]["outcome"] == "pass"


def test_api_history_fail_soft_when_lab_down(tmp_path, monkeypatch):
    settings = _settings(tmp_path, lab_key_dir=_key_dir(tmp_path))
    app = controller.create_app(settings, lab_glance=FakeLab(), ttyd_prober=_prober())
    _patch_lab(monkeypatch, exc=httpx.ConnectError("no route"))
    client = TestClient(app)
    resp = client.get(
        "/api/history", headers={"Host": "127.0.0.1:7800", **_auth()}
    )
    assert resp.status_code == 200          # NEVER 500
    assert resp.json() == {"jobs": [], "stale": True}


def test_api_history_bus_busy_payload_is_stale_not_500(tmp_path, monkeypatch):
    settings = _settings(tmp_path, lab_key_dir=_key_dir(tmp_path))
    app = controller.create_app(settings, lab_glance=FakeLab(), ttyd_prober=_prober())
    # transient {"detail": "bus_busy_retry"} with no "messages" key.
    _patch_lab(monkeypatch, payload={"detail": "bus_busy_retry"})
    client = TestClient(app)
    resp = client.get(
        "/api/history", headers={"Host": "127.0.0.1:7800", **_auth()}
    )
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [], "stale": True}
