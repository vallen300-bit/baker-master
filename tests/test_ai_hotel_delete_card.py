"""AI_HOTEL_DELETE_CARD_BUTTON_1 — recoverable delete for Field Notes cards.

Soft delete only: the live feed hides deleted captures, but capture rows and
linked media remain recoverable. The endpoint accepts the same private AI-Hotel
edit context as the rotate repair action.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


def test_source_guards_soft_delete_only():
    src = Path("outputs/dashboard.py").read_text()
    endpoint = src[
        src.index('@app.post("/api/ai-hotel/captures/{capture_id}/delete"'):
        src.index('@app.get("/api/ai-hotel/captures/{capture_id}/media"')
    ]
    feed = src[src.index("async def ai_hotel_captures("):src.index("async def ai_hotel_capture_audio_detail(")]
    migration = Path("migrations/20260620_ai_hotel_captures_deleted_at.sql").read_text()

    assert "Depends(verify_ai_hotel_photo_edit_access)" in endpoint
    assert "UPDATE ai_hotel_captures" in endpoint
    assert "SET deleted_at = COALESCE(deleted_at, NOW())" in endpoint
    assert "RETURNING id, deleted_at" in endpoint
    assert "DELETE FROM ai_hotel_captures" not in endpoint
    assert "deleted_at IS NULL" in feed
    assert "ADD COLUMN IF NOT EXISTS deleted_at" in migration
    assert "WHERE deleted_at IS NULL" in migration
    assert "DELETE FROM" not in migration


def test_ui_confirm_posts_delete_and_hides_card():
    html = Path("outputs/static/ai-hotel.html").read_text()
    delete_fn = html[html.index("function removeDeletedNoteCard("):html.index("function cardAsText(")]
    detail = html[html.index("function openNoteDetail("):html.index("/* ---- HITEC 2026")]

    assert "Delete field note" in detail
    assert "confirm('Delete this field note? It will be hidden.')" in delete_fn
    assert "fetch('/api/ai-hotel/captures/'+c.id+'/delete',aiHotelJsonOptions({}))" in delete_fn
    assert "_aihDeletedCaptureIds[String(c.id)]=true" in delete_fn
    assert ".ncard[data-capture-id" in delete_fn
    assert "document.getElementById('detail').close()" in delete_fn


def test_pin_gate_mentions_delete_endpoint_auth():
    src = Path("outputs/dashboard.py").read_text()
    delete_seg = src[
        src.index('@app.post("/api/ai-hotel/captures/{capture_id}/delete"'):
        src.index("async def ai_hotel_capture_soft_delete(")
    ]
    assert "verify_ai_hotel_photo_edit_access" in delete_seg


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable in this interpreter",
)


class _Cur:
    def __init__(self, store):
        self.s = store
        self._res = []

    def execute(self, sql, params=None):
        self.s.sqls.append(sql)
        if "UPDATE ai_hotel_captures" in sql and "deleted_at" in sql:
            cid = params[0]
            self._res = []
            for row in self.s.captures:
                if row["id"] == cid:
                    if row.get("deleted_at") is None:
                        row["deleted_at"] = _dt.datetime(2026, 6, 20, 12, 0, tzinfo=_dt.timezone.utc)
                    self._res = [{"id": cid, "deleted_at": row["deleted_at"]}]
                    break
        else:
            self._res = []

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res

    def close(self):
        pass


class _Conn:
    def __init__(self, store):
        self.s = store

    def cursor(self, cursor_factory=None):
        return _Cur(self.s)

    def commit(self):
        self.s.commits += 1

    def rollback(self):
        self.s.rollbacks += 1


class _Store:
    def __init__(self):
        self.captures = []
        self.sqls = []
        self.commits = 0
        self.rollbacks = 0

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    dash.app.dependency_overrides.pop(dash.verify_ai_hotel_read_access, None)
    dash.app.dependency_overrides.pop(dash.verify_ai_hotel_photo_edit_access, None)
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}


@_skip
def test_delete_endpoint_sets_deleted_at_and_is_idempotent(monkeypatch):
    store = _Store()
    store.captures = [{"id": 17, "deleted_at": None}]
    client = _client(monkeypatch, store)

    first = client.post("/api/ai-hotel/captures/17/delete", headers=_HDR)
    second = client.post("/api/ai-hotel/captures/17/delete", headers=_HDR)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["ok"] is True and first.json()["id"] == 17
    assert first.json()["deleted_at"] == second.json()["deleted_at"]
    assert store.captures[0]["deleted_at"].isoformat() == first.json()["deleted_at"]
    assert store.commits == 2
    assert store.rollbacks == 0
    assert all("DELETE FROM ai_hotel_captures" not in sql for sql in store.sqls)


@_skip
def test_delete_endpoint_missing_capture_404s(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)

    resp = client.post("/api/ai-hotel/captures/404/delete", headers=_HDR)

    assert resp.status_code == 404
    assert store.commits == 0
    assert store.rollbacks == 1


@_skip
def test_delete_endpoint_requires_auth(monkeypatch):
    store = _Store()
    store.captures = [{"id": 17, "deleted_at": None}]
    client = _client(monkeypatch, store)

    resp = client.post("/api/ai-hotel/captures/17/delete")

    assert resp.status_code == 401
    assert store.captures[0]["deleted_at"] is None
    assert store.sqls == []
