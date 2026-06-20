"""AI_HOTEL_SITE_VIDEO_EVIDENCE_1 — R2-backed short site videos.

The raw capture remains the source of truth. Video is attached afterward via a
browser-to-R2 presigned PUT; Postgres stores metadata only.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


def test_video_routes_and_health_probe_shape_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert "/api/ai-hotel/captures/{capture_id}/media/presign" in src
    assert "/api/ai-hotel/captures/{capture_id}/media/confirm" in src
    assert "/api/ai-hotel/captures/{capture_id}/media" in src
    assert "storage_health(probe=False)" in src


def test_capture_page_has_client_video_guards_and_presigned_upload():
    src = Path("outputs/static/ai-hotel-capture.html").read_text()
    assert "id=\"videoInput\"" in src
    assert "VIDEO_MAX_BYTES=50*1024*1024" in src
    assert "VIDEO_MAX_SECONDS=30" in src
    assert "uploadSelectedVideo" in src
    assert "/media/presign" in src and "/media/confirm" in src
    assert "Content-Length" in src and "forbidden" in src


def test_field_notes_load_video_on_demand_only():
    src = Path("outputs/static/ai-hotel.html").read_text()
    assert "Array.isArray(c.video)" in src
    assert "Load & play video" in src
    assert "/media" in src
    assert "nvideo-player" in src


def test_list_endpoint_video_metadata_only_in_source():
    src = Path("outputs/dashboard.py").read_text()
    listseg = src[src.index("async def ai_hotel_captures("):src.index("async def ai_hotel_capture_audio_detail(")]
    vq = listseg[listseg.index("FROM ai_hotel_capture_media"):]
    before_order = vq.split("ORDER BY")[0]
    assert "storage_key" not in before_order
    assert "thumbnail_key IS NOT NULL" in listseg
    assert "video_by_cap" in listseg
    detailseg = src[src.index("async def ai_hotel_capture_media_detail("):src.index("# ── AI_HOTEL_VOICE_FORM_SUPPLIER_1")]
    assert "storage_key" in detailseg
    assert '"storage_key":' not in detailseg and '"thumbnail_key":' not in detailseg


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
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.rowcount = 0
        if "SELECT 1 FROM ai_hotel_captures WHERE id = %s" in sql:
            cid = params[0]
            self._res = [(1,)] if any(c["id"] == cid for c in self.s.captures) else []
        elif "INSERT INTO ai_hotel_capture_media" in sql:
            cid, key, tkey, ctype, size, dur = params
            mid = self.s.nextmedia
            self.s.nextmedia += 1
            row = {
                "id": mid,
                "capture_id": cid,
                "media_type": "video",
                "storage_key": key,
                "thumbnail_key": tkey,
                "content_type": ctype,
                "size_bytes": size,
                "duration_seconds": dur,
                "created_at": _dt.datetime(2026, 6, 19, 12, mid, 0),
            }
            self.s.media.append(row)
            self._res = [(mid, row["created_at"])]
            self.rowcount = 1
        elif "FROM ai_hotel_capture_media" in sql and "storage_key" in sql:
            cid = params[0]
            self._res = [dict(m) for m in self.s.media if m["capture_id"] == cid]
        elif "FROM ai_hotel_capture_media" in sql:
            ids = params[0] if params else []
            self._res = [{
                "capture_id": m["capture_id"],
                "id": m["id"],
                "content_type": m["content_type"],
                "size_bytes": m["size_bytes"],
                "duration_seconds": m["duration_seconds"],
                "created_at": m["created_at"],
                "has_thumbnail": bool(m.get("thumbnail_key")),
            } for m in self.s.media if m["capture_id"] in ids]
        elif "FROM ai_hotel_capture_images" in sql:
            self._res = []
        elif "FROM ai_hotel_form_records" in sql:
            self._res = []
        elif "FROM ai_hotel_capture_audio" in sql:
            self._res = []
        elif "FROM ai_hotel_captures" in sql:
            rows = [r for r in self.s.captures if r.get("status") != "dismissed"]
            self._res = [dict(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]
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
        pass

    def rollback(self):
        pass


class _Store:
    def __init__(self):
        self.captures = [{
            "id": 17,
            "source": "note",
            "note_text": "Site video evidence.",
            "summary": "Site video evidence",
            "status": "new",
            "image_b64": None,
            "image_media": None,
            "section_guess": "general",
            "related_area": None,
            "created_at": _dt.datetime(2026, 6, 19, 12, 0, 0),
            "gps_lat": None,
            "gps_lng": None,
            "gps_accuracy_m": None,
            "gps_captured_at": None,
            "gps_address": None,
            "gps_address_source": None,
            "gps_address_status": None,
        }]
        self.media = []
        self.nextmedia = 1

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}


@_skip
def test_media_routes_require_auth(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)

    assert client.post(
        "/api/ai-hotel/captures/17/media/presign",
        json={"asset": "video", "content_type": "video/webm", "size_bytes": 1000, "duration_seconds": 10},
    ).status_code == 401
    assert client.post(
        "/api/ai-hotel/captures/17/media/confirm",
        json={
            "media_type": "video",
            "storage_key": "ai-hotel/captures/17/video/abc.webm",
            "content_type": "video/webm",
            "size_bytes": 1000,
            "duration_seconds": 10,
        },
    ).status_code == 401
    assert client.get("/api/ai-hotel/captures/17/media").status_code == 401


@_skip
def test_presign_rejects_oversize_before_calling_object_storage(monkeypatch):
    import kbl.object_storage as storage
    import outputs.dashboard as dash

    store = _Store()
    called = []
    monkeypatch.setattr(storage, "generate_presigned_put", lambda *a, **k: called.append((a, k)))
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/media/presign",
        headers=_HDR,
        json={
            "asset": "video",
            "content_type": "video/webm",
            "size_bytes": dash._AI_HOTEL_VIDEO_CAP + 1,
            "duration_seconds": 10,
        },
    )

    assert resp.status_code == 400
    assert called == []


@_skip
def test_presign_uses_browser_file_size_for_signed_put(monkeypatch):
    import kbl.object_storage as storage

    store = _Store()
    calls = []

    def fake_presign(key, content_type, max_bytes, expires=300):
        calls.append((key, content_type, max_bytes, expires))
        return {
            "ok": True,
            "method": "PUT",
            "url": "https://r2.invalid/signed",
            "headers": {"Content-Type": content_type, "Content-Length": str(max_bytes)},
            "key": key,
        }

    monkeypatch.setattr(storage, "generate_presigned_put", fake_presign)
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/media/presign",
        headers=_HDR,
        json={
            "asset": "video",
            "content_type": "video/webm",
            "size_bytes": 123456,
            "duration_seconds": 12.5,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upload"]["headers"]["Content-Length"] == "123456"
    assert calls and calls[0][1:] == ("video/webm", 123456, 300)
    assert calls[0][0].startswith("ai-hotel/captures/17/video/")


@_skip
def test_confirm_inserts_metadata_only(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/media/confirm",
        headers=_HDR,
        json={
            "media_type": "video",
            "storage_key": "ai-hotel/captures/17/video/abc.webm",
            "thumbnail_key": "ai-hotel/captures/17/thumbnail/abc.jpg",
            "content_type": "video/webm",
            "size_bytes": 1000,
            "duration_seconds": 12,
        },
    )

    assert resp.status_code == 200, resp.text
    assert len(store.media) == 1
    row = store.media[0]
    assert row["storage_key"].endswith("abc.webm")
    assert row["thumbnail_key"].endswith("abc.jpg")
    assert row["size_bytes"] == 1000
    assert "base64" not in str(row).lower() and "b64" not in row
    assert "storage_key" not in resp.json()["media"]


@_skip
def test_confirm_rejects_wrong_capture_prefix(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/media/confirm",
        headers=_HDR,
        json={
            "media_type": "video",
            "storage_key": "ai-hotel/captures/99/video/abc.webm",
            "content_type": "video/webm",
            "size_bytes": 1000,
            "duration_seconds": 12,
        },
    )

    assert resp.status_code == 400
    assert store.media == []


@_skip
def test_list_metadata_only_and_detail_returns_signed_urls(monkeypatch):
    import kbl.object_storage as storage

    store = _Store()
    store.media.append({
        "id": 3,
        "capture_id": 17,
        "media_type": "video",
        "storage_key": "ai-hotel/captures/17/video/clip.webm",
        "thumbnail_key": "ai-hotel/captures/17/thumbnail/clip.jpg",
        "content_type": "video/webm",
        "size_bytes": 2048,
        "duration_seconds": 9.5,
        "created_at": _dt.datetime(2026, 6, 19, 12, 3, 0),
    })
    monkeypatch.setattr(storage, "generate_presigned_get", lambda key, expires=300: {
        "ok": True,
        "url": "https://r2.invalid/" + key.rsplit("/", 1)[-1],
    })
    client = _client(monkeypatch, store)

    item = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]
    assert len(item["video"]) == 1
    meta = item["video"][0]
    assert meta["duration_seconds"] == 9.5
    assert meta["has_thumbnail"] is True
    assert "storage_key" not in meta and "url" not in meta

    detail = client.get("/api/ai-hotel/captures/17/media", headers=_HDR).json()["media"][0]
    assert detail["url"].endswith("/clip.webm")
    assert detail["thumbnail_url"].endswith("/clip.jpg")
    assert "storage_key" not in detail and "thumbnail_key" not in detail
