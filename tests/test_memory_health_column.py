"""HEALTH_ENDPOINT_COLUMN_FIX_1 regression test.

Guards /api/memory/health against the schema mismatch that made the whole
tier-1 SELECT fail and return {"error": ...}: the query referenced
`whatsapp_messages.received_at`, but the real column is `timestamp`
(verified via information_schema; 5 other call sites use MAX(timestamp)).

Cheap SQL-assertion regression per Lesson #44 — a _FakeCursor captures the
SQL the endpoint actually executes, so we assert on the canonical column name
without a live DB. Also asserts the endpoint returns the stats object, not an
error envelope (AC1).
"""
from __future__ import annotations

from threading import RLock


def _set_api_key(monkeypatch, key="test-key-memhealth"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash

    dash._BAKER_API_KEY = key
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    return dash


class _FakeCursor:
    def __init__(self, store):
        self.store = store
        self._row = None

    def execute(self, sql, params=()):
        self.store.executed.append(sql)
        compact = " ".join(sql.split()).lower()
        if "whatsapp_messages" in compact:
            # Tier-1 aggregate SELECT
            self._row = {"emails": 1, "whatsapp": 2, "alerts": 3, "conversations": 4}
        elif "memory_summaries" in compact or "memory_institutional" in compact:
            self._row = {"count": 0, "last_run": None}
        elif "memory_archive_log" in compact:
            self._row = {"count": 0}
        else:
            self._row = {}

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def __init__(self):
        self.executed = []
        self.lock = RLock()

    def _get_conn(self):
        return _FakeConn(self)

    def _put_conn(self, conn):
        pass


def _install_fake_store(monkeypatch):
    dash = _set_api_key(monkeypatch)
    store = _FakeStore()
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return dash, store


def test_memory_health_uses_canonical_whatsapp_column(monkeypatch):
    from fastapi.testclient import TestClient

    dash, store = _install_fake_store(monkeypatch)
    client = TestClient(dash.app)

    resp = client.get("/api/memory/health", headers={"X-Baker-Key": "test-key-memhealth"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # AC1: real stats object, never the error envelope.
    assert "error" not in body, body
    assert set(body) >= {"tier1", "tier2", "tier3", "archive"}, body
    assert body["tier1"]["total"] == 1 + 2 + 3 + 4

    # The canonical column guard: the whatsapp count must query `timestamp`,
    # never the non-existent `received_at`.
    tier1_sql = next(s for s in store.executed if "whatsapp_messages" in s.lower())
    assert "received_at" not in tier1_sql.lower(), tier1_sql
    assert "whatsapp_messages where timestamp" in " ".join(tier1_sql.split()).lower(), tier1_sql
