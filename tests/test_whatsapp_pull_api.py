"""Tests for `GET /api/whatsapp/messages` (BAKER_WA_PULL_API_1).

Read-only endpoint over `whatsapp_messages` for desk consumption. X-Baker-Key
auth (verify_api_key reused from `/api/whatsapp/backfill`). JSON default,
format=md returns text/plain markdown thread.

Tests mock the store singleton so no real Postgres is required.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient


class _FakeCursor:
    def __init__(self, queued_rows, cols):
        self._rows = list(queued_rows)
        self._cols = cols
        # psycopg2 Column rows are tuple-like; `d[0]` returns the column name.
        self.description = [(c,) for c in cols]
        self.last_sql = None
        self.last_params = None
        self.fail_with = None

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params
        if self.fail_with:
            raise self.fail_with

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class _FakeStore:
    def __init__(self, conn):
        self._conn = conn
        self.put_called = False

    def _get_conn(self):
        return self._conn

    def _put_conn(self, conn):
        self.put_called = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEFAULT_COLS = ["id", "timestamp", "sender", "sender_name", "chat_id", "full_text", "has_media"]


@pytest.fixture
def client_unauth(monkeypatch):
    """TestClient with verify_api_key wired live (key configured but caller omits header)."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs.dashboard import app
    return TestClient(app)


@pytest.fixture
def client_authed(monkeypatch):
    """TestClient with verify_api_key bypassed via dependency_overrides."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs.dashboard import app, verify_api_key
    app.dependency_overrides[verify_api_key] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


def _install_fake_store(monkeypatch, rows, fail_with=None, no_conn=False):
    cursor = _FakeCursor(rows, _DEFAULT_COLS)
    if fail_with:
        cursor.fail_with = fail_with
    conn = None if no_conn else _FakeConn(cursor)
    store = _FakeStore(conn)
    from outputs import dashboard as dash
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return store, cursor


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_whatsapp_messages_happy_path_json(client_authed, monkeypatch):
    ts = datetime(2026, 5, 14, 8, 32, 14, tzinfo=timezone.utc)
    rows = [
        ("wamid.AAA", ts, "41788888888@c.us", "Constantinos", "chat-123", "Hi there", False),
        ("wamid.BBB", datetime(2026, 5, 14, 8, 35, tzinfo=timezone.utc),
         "41799605092@c.us", "Dimitry", "chat-123", "Reply text", True),
    ]
    store, cursor = _install_fake_store(monkeypatch, rows)

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "Constantinos", "from": "2026-05-11", "to": "2026-05-17"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["contact"] == "Constantinos"
    assert body["from"] == "2026-05-11"
    assert body["to"] == "2026-05-17"
    assert body["count"] == 2
    assert len(body["messages"]) == 2
    first = body["messages"][0]
    assert first["id"] == "wamid.AAA"
    assert first["sender_name"] == "Constantinos"
    assert first["chat_id"] == "chat-123"
    assert first["full_text"] == "Hi there"
    assert first["has_media"] is False
    assert first["timestamp"].startswith("2026-05-14")
    assert body["messages"][1]["has_media"] is True
    assert store.put_called  # connection released


def test_whatsapp_messages_sql_uses_canonical_media_column(client_authed, monkeypatch):
    """Drift guard: brief said `media_path`, real schema (per
    `_ensure_whatsapp_messages_table`) is `media_dropbox_path`."""
    _, cursor = _install_fake_store(monkeypatch, [])

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "X", "from": "2026-05-11", "to": "2026-05-17"},
    )

    assert resp.status_code == 200
    assert "media_dropbox_path IS NOT NULL" in cursor.last_sql
    assert "media_path " not in cursor.last_sql
    # Param order: contact ILIKE x2, from_date, to_date, limit
    assert cursor.last_params[0] == "%X%"
    assert cursor.last_params[1] == "%X%"
    assert cursor.last_params[4] == 200  # default limit


def test_whatsapp_messages_markdown_format(client_authed, monkeypatch):
    rows = [
        ("wamid.AAA",
         datetime(2026, 5, 14, 8, 32, tzinfo=timezone.utc),
         "41700000000@c.us", "Constantinos", "chat-1", "Hello world", False),
        ("wamid.BBB",
         datetime(2026, 5, 14, 8, 35, tzinfo=timezone.utc),
         "41799605092@c.us", "Dimitry", "chat-1", "Reply", False),
    ]
    _install_fake_store(monkeypatch, rows)

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "Constantinos", "from": "2026-05-11", "to": "2026-05-17", "format": "md"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "**[2026-05-14 08:32 UTC] Constantinos**" in text
    assert "Hello world" in text
    assert "**[2026-05-14 08:35 UTC] Dimitry**" in text
    # Oldest-first ordering preserved in rendered output
    assert text.index("Constantinos") < text.index("Dimitry")


def test_whatsapp_messages_empty_result_is_200(client_authed, monkeypatch):
    _install_fake_store(monkeypatch, [])

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "Nonexistent", "from": "2026-05-11", "to": "2026-05-17"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok",
        "contact": "Nonexistent",
        "from": "2026-05-11",
        "to": "2026-05-17",
        "count": 0,
        "messages": [],
    }


def test_whatsapp_messages_limit_clamped(client_authed, monkeypatch):
    _install_fake_store(monkeypatch, [])

    too_high = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17", "limit": 5000},
    )
    too_low = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17", "limit": 0},
    )

    assert too_high.status_code == 422
    assert too_low.status_code == 422


# ---------------------------------------------------------------------------
# Validation: required params + format whitelist
# ---------------------------------------------------------------------------


def test_whatsapp_messages_missing_contact_422(client_authed):
    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"from": "2026-05-11", "to": "2026-05-17"},
    )
    assert resp.status_code == 422


def test_whatsapp_messages_missing_from_422(client_authed):
    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "to": "2026-05-17"},
    )
    assert resp.status_code == 422


def test_whatsapp_messages_bad_format_422(client_authed):
    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17", "format": "xml"},
    )
    assert resp.status_code == 422


def test_whatsapp_messages_bad_date_422(client_authed):
    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "not-a-date", "to": "2026-05-17"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth — verify_api_key live
# ---------------------------------------------------------------------------


def test_whatsapp_messages_no_api_key_returns_401(client_unauth):
    resp = client_unauth.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17"},
    )
    assert resp.status_code == 401


def test_whatsapp_messages_wrong_api_key_returns_401(client_unauth):
    resp = client_unauth.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17"},
        headers={"X-Baker-Key": "wrong-key"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Fault tolerance — DB errors return 200 with status=error, rollback called
# ---------------------------------------------------------------------------


def test_whatsapp_messages_db_failure_returns_200_status_error(client_authed, monkeypatch):
    store, _ = _install_fake_store(monkeypatch, [], fail_with=RuntimeError("boom"))

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "boom" in body["message"]
    assert store._conn.rolled_back is True  # noqa: SLF001
    assert store.put_called  # connection released even on failure


def test_whatsapp_messages_no_db_conn_returns_200_status_error(client_authed, monkeypatch):
    _install_fake_store(monkeypatch, [], no_conn=True)

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "x", "from": "2026-05-11", "to": "2026-05-17"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "database unavailable" in body["message"]
