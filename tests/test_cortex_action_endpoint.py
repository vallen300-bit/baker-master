"""Tests for /cortex/cycle/{cycle_id}/action endpoint — CORTEX_3T_FORMALIZE_1C.

Source-level assertions run in any Python; TestClient tests skip cleanly when
``outputs.dashboard`` cannot import (Python 3.9 / PEP-604 chain — same skip
guard as test_proactive_pm_sentinel.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


# ─── Source-level: the route is registered ───

def test_endpoint_route_is_registered_in_dashboard_source():
    """Verifies the new endpoint exists with proper auth + tag + path."""
    src = Path("outputs/dashboard.py").read_text()
    assert '@app.post(' in src
    assert '/cortex/cycle/{cycle_id}/action' in src
    assert 'tags=["cortex"]' in src
    assert 'dependencies=[Depends(verify_api_key)]' in src
    assert 'async def cortex_cycle_action(cycle_id: str, request: Request):' in src


def test_endpoint_dispatches_to_phase5_handlers_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert "from orchestrator.cortex_phase5_act import" in src
    for name in ("cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"):
        assert name in src


def test_endpoint_rejects_invalid_actions_in_source():
    """Invalid action names must 400, not 500."""
    src = Path("outputs/dashboard.py").read_text()
    assert 'if action not in ("approve", "edit", "refresh", "reject"):' in src
    assert "invalid_action:" in src


# ─── TestClient — happy path + 400/500 verification ───


def _endpoint_client(monkeypatch, handler_overrides=None):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs.dashboard import app, verify_api_key
    app.dependency_overrides[verify_api_key] = lambda: None

    if handler_overrides:
        from orchestrator import cortex_phase5_act as p5
        for name, fn in handler_overrides.items():
            monkeypatch.setattr(p5, name, fn)

    return TestClient(app)


@_skip_without_dashboard
def test_endpoint_400_on_invalid_action(monkeypatch):
    client = _endpoint_client(monkeypatch)
    resp = client.post(
        "/cortex/cycle/cyc-1/action",
        json={"action": "explode"},
    )
    assert resp.status_code == 400
    assert "invalid_action" in resp.json().get("detail", "")


@_skip_without_dashboard
def test_endpoint_400_on_invalid_json(monkeypatch):
    client = _endpoint_client(monkeypatch)
    resp = client.post(
        "/cortex/cycle/cyc-1/action",
        data="this is not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400


@_skip_without_dashboard
def test_endpoint_dispatches_approve(monkeypatch):
    captured = {}

    async def fake_approve(*, cycle_id, body):
        captured["cycle_id"] = cycle_id
        captured["body"] = body
        return {"status": "approved", "actions_logged": 0,
                "gold_files_written": 0, "matter_slug": "ao"}

    client = _endpoint_client(monkeypatch, {"cortex_approve": fake_approve})
    resp = client.post(
        "/cortex/cycle/cyc-77/action",
        json={"action": "approve", "selected_gold_files": ["a.md"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["action"] == "approve"
    assert body["result"]["status"] == "approved"
    assert captured["cycle_id"] == "cyc-77"
    assert captured["body"]["selected_gold_files"] == ["a.md"]


@_skip_without_dashboard
def test_endpoint_500_on_handler_exception(monkeypatch):
    async def boom(*, cycle_id, body):
        raise RuntimeError("kaboom")

    client = _endpoint_client(monkeypatch, {"cortex_reject": boom})
    resp = client.post(
        "/cortex/cycle/cyc-x/action",
        json={"action": "reject", "reason": "stale"},
    )
    assert resp.status_code == 500


@_skip_without_dashboard
def test_endpoint_handles_all_4_actions(monkeypatch):
    """Every canonical action_id is wired."""
    captured = []
    for name in ("cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"):
        async def stub(*, cycle_id, body, _name=name):
            captured.append(_name)
            return {"ok": True}
        monkeypatch_attr_on_p5(monkeypatch, name, stub)

    client = _endpoint_client(monkeypatch)
    for action in ("approve", "edit", "refresh", "reject"):
        body = {"action": action, "edits": "x", "reason": "y", "selected_gold_files": []}
        resp = client.post(f"/cortex/cycle/cyc-{action}/action", json=body)
        assert resp.status_code == 200, resp.text
    expected = {"cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"}
    assert set(captured) == expected


def monkeypatch_attr_on_p5(monkeypatch, name, fn):
    from orchestrator import cortex_phase5_act as p5
    monkeypatch.setattr(p5, name, fn)
