"""
BAKER_CAPTURE_BLINDSPOTS_1: /api/whatsapp/import_iphone_export endpoint tests.
Skips cleanly when outputs.dashboard cannot import (Python 3.9 PEP-604 chain).
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


# ─── Source-level checks (always run) ──────────────────────────────────────


def test_endpoint_route_is_registered_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/whatsapp/import_iphone_export"' in src
    assert 'tags=["whatsapp"]' in src
    assert 'dependencies=[Depends(verify_api_key)]' in src
    assert 'async def whatsapp_import_iphone_export(' in src


def test_endpoint_does_not_collide_with_existing_whatsapp_routes():
    src = Path("outputs/dashboard.py").read_text()
    # /api/whatsapp/import_iphone_export must appear exactly once as a route literal.
    assert src.count('"/api/whatsapp/import_iphone_export"') == 1


# ─── Stub store for TestClient runs ────────────────────────────────────────


class _StubCursor:
    def __init__(self, rows: dict):
        self._rows = rows
        self._result: list = []

    def execute(self, sql: str, params=None):
        if "SELECT id FROM whatsapp_messages WHERE id = ANY" in sql:
            target_ids = list(params[0])
            self._result = [(i,) for i in target_ids if i in self._rows]
        else:
            self._result = []

    def fetchall(self):
        return self._result

    def close(self):
        pass


class _StubConn:
    def __init__(self, rows: dict):
        self._rows = rows

    def cursor(self):
        return _StubCursor(self._rows)

    def rollback(self):
        pass


class _StubStore:
    def __init__(self):
        self.rows: dict = {}

    def _get_conn(self):
        return _StubConn(self.rows)

    def _put_conn(self, conn):
        pass

    def store_whatsapp_message(self, msg_id, sender=None, sender_name=None,
                               chat_id=None, full_text=None, timestamp=None,
                               is_director=False, **kwargs):
        self.rows[msg_id] = {
            "sender": sender,
            "sender_name": sender_name,
            "chat_id": chat_id,
            "full_text": full_text,
            "timestamp": timestamp,
            "is_director": is_director,
        }
        return True


def _client_with_stub(monkeypatch):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    stub = _StubStore()
    monkeypatch.setattr(dash, "_get_store", lambda: stub)
    return TestClient(dash.app), stub


_SAMPLE_TXT = (
    "[2026-05-12, 14:23:01] Dimitry Vallen: First message\n"
    "and a continuation\n"
    "[2026-05-12, 14:24:10] Peter Storer: Reply from Peter\n"
)


# ─── TestClient runs ───────────────────────────────────────────────────────


@_skip_without_dashboard
def test_endpoint_401_without_auth_header(monkeypatch):
    client, _ = _client_with_stub(monkeypatch)
    resp = client.post(
        "/api/whatsapp/import_iphone_export",
        files={"file": ("export.txt", _SAMPLE_TXT, "text/plain")},
        data={"counterparty_phone": "+393358345678", "counterparty_name": "Peter Storer"},
    )
    assert resp.status_code == 401


@_skip_without_dashboard
def test_endpoint_200_with_valid_auth_and_payload(monkeypatch):
    client, stub = _client_with_stub(monkeypatch)
    resp = client.post(
        "/api/whatsapp/import_iphone_export",
        headers={"X-Baker-Key": "test-key"},
        files={"file": ("export.txt", _SAMPLE_TXT, "text/plain")},
        data={"counterparty_phone": "+393358345678", "counterparty_name": "Peter Storer"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ingested"] == 2
    assert body["skipped_duplicates"] == 0
    assert body["counterparty_phone"] == "+393358345678"
    assert body["counterparty_name"] == "Peter Storer"
    # 2 rows landed in stub.
    assert len(stub.rows) == 2
    assert all(k.startswith("iphone:393358345678@c.us:") for k in stub.rows)


@_skip_without_dashboard
def test_endpoint_idempotent_on_repeated_upload(monkeypatch):
    client, stub = _client_with_stub(monkeypatch)
    common = dict(
        headers={"X-Baker-Key": "test-key"},
        files={"file": ("export.txt", _SAMPLE_TXT, "text/plain")},
        data={"counterparty_phone": "+393358345678", "counterparty_name": "Peter Storer"},
    )
    first = client.post("/api/whatsapp/import_iphone_export", **common).json()
    rows_after_first = len(stub.rows)

    # Re-build files (stream is consumed); same payload.
    common["files"] = {"file": ("export.txt", _SAMPLE_TXT, "text/plain")}
    second = client.post("/api/whatsapp/import_iphone_export", **common).json()

    assert first["ingested"] == 2
    assert second["ingested"] == 0
    assert second["skipped_duplicates"] == 2
    # No net-new rows in storage on second call.
    assert len(stub.rows) == rows_after_first == 2


@_skip_without_dashboard
def test_endpoint_422_on_empty_or_garbage_upload(monkeypatch):
    client, _ = _client_with_stub(monkeypatch)
    resp = client.post(
        "/api/whatsapp/import_iphone_export",
        headers={"X-Baker-Key": "test-key"},
        files={"file": ("garbage.txt", "no timestamps here\n", "text/plain")},
        data={"counterparty_phone": "+393358345678", "counterparty_name": "Peter Storer"},
    )
    assert resp.status_code == 422


@_skip_without_dashboard
def test_endpoint_501_on_zip_upload(monkeypatch):
    client, _ = _client_with_stub(monkeypatch)
    resp = client.post(
        "/api/whatsapp/import_iphone_export",
        headers={"X-Baker-Key": "test-key"},
        files={"file": ("export.zip", b"PK\x03\x04", "application/zip")},
        data={"counterparty_phone": "+393358345678", "counterparty_name": "Peter Storer"},
    )
    assert resp.status_code == 501
