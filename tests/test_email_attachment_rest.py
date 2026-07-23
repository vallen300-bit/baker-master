"""Tests for the REST mirror of baker_email_attachment_read."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest


_DASHBOARD_SRC = Path(__file__).resolve().parents[1] / "outputs" / "dashboard.py"


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


def _stub_mcp_when_unavailable(monkeypatch):
    """Keep this focused REST test runnable in the slim local install."""
    try:
        import mcp.types  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    class _Tool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    mcp_module = types.ModuleType("mcp")
    mcp_types_module = types.ModuleType("mcp.types")
    mcp_types_module.Tool = _Tool
    mcp_module.types = mcp_types_module
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.types", mcp_types_module)


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable",
)


def test_attachment_rest_route_is_authenticated_and_mcp_backed():
    src = _DASHBOARD_SRC.read_text(encoding="utf-8")
    assert '@app.get("/api/emails/attachment"' in src
    route_start = src.index('@app.get("/api/emails/attachment"')
    route_end = src.index("async def emails_attachment_endpoint", route_start)
    route = src[route_start:route_end]
    assert "dependencies=[Depends(verify_api_key)]" in route
    assert 'dispatch_email("baker_email_attachment_read"' in src


@_skip_without_dashboard
def test_attachment_rest_requires_api_key(monkeypatch):
    from fastapi.testclient import TestClient
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key")
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)

    response = TestClient(dashboard.app).get(
        "/api/emails/attachment",
        params={"message_id": "M1"},
    )

    assert response.status_code == 401


@_skip_without_dashboard
def test_attachment_rest_forwards_fetch_to_mcp_dispatch(monkeypatch):
    from fastapi.testclient import TestClient
    from outputs import dashboard

    _stub_mcp_when_unavailable(monkeypatch)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key")
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)
    captured = {}

    def fake_dispatch(name, args):
        captured["name"] = name
        captured["args"] = args
        return json.dumps({
            "message_id": "M1",
            "filename": "Aukera.xlsx",
            "text": "worksheet text",
            "bytes_base64": "eA==",
        })

    monkeypatch.setattr("tools.email.dispatch_email", fake_dispatch)

    response = TestClient(dashboard.app).get(
        "/api/emails/attachment",
        params={
            "message_id": "M1",
            "filename": "Aukera.xlsx",
            "attachment_index": "2",
            "source": "graph",
            "include_bytes": "true",
        },
        headers={"X-Baker-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "worksheet text"
    assert captured == {
        "name": "baker_email_attachment_read",
        "args": {
            "message_id": "M1",
            "filename": "Aukera.xlsx",
            "attachment_index": 2,
            "source": "graph",
            "include_bytes": True,
        },
    }


@_skip_without_dashboard
def test_attachment_rest_list_mode_preserves_omitted_selector(monkeypatch):
    from fastapi.testclient import TestClient
    from outputs import dashboard

    _stub_mcp_when_unavailable(monkeypatch)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key")
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)
    captured = {}

    def fake_dispatch(name, args):
        captured["name"] = name
        captured["args"] = args
        return json.dumps({
            "message_id": "M1",
            "attachment_count": 1,
            "attachments": [{
                "index": 1,
                "filename": "Aukera.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size_bytes": 42,
            }],
        })

    monkeypatch.setattr("tools.email.dispatch_email", fake_dispatch)

    response = TestClient(dashboard.app).get(
        "/api/emails/attachment",
        params={"message_id": "M1"},
        headers={"X-Baker-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["attachment_count"] == 1
    assert captured == {
        "name": "baker_email_attachment_read",
        "args": {
            "message_id": "M1",
            "source": None,
            "include_bytes": False,
        },
    }


@_skip_without_dashboard
def test_attachment_rest_maps_store_outage_to_503(monkeypatch):
    from fastapi.testclient import TestClient
    from outputs import dashboard

    _stub_mcp_when_unavailable(monkeypatch)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key")
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)

    import kbl.attachment_store as store

    def raise_store_outage(message_id, source=None):
        raise store.AttachmentStoreUnavailable("simulated store outage")

    monkeypatch.setattr(store, "list_attachments", raise_store_outage)

    response = TestClient(dashboard.app).get(
        "/api/emails/attachment",
        params={"message_id": "M1"},
        headers={"X-Baker-Key": "test-key"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["backend_unavailable"] is True
    assert "no attachments" not in body.get("error", "")
