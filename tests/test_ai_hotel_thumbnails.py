"""AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1 — Field Notes feed returns thumbnails,
not full-res base64 (the 7.1 MB feed that hung the Director's phone).

AC1 list carries `thumb` (or null) + `image_count`; NO full-res images[]/image base64.
AC2 GET /captures/{id}/images returns the ordered full data-URLs, auth-gated.
AC3 capture with no images → thumb=null, image_count=0, still in feed.
AC4 corrupt stored image → thumb=null, never 500, feed still serves other captures.
"""

from __future__ import annotations

import base64 as _b64
import datetime as _dt
from io import BytesIO
from pathlib import Path

import pytest


# ─── Source-level checks (always run) ───────────────────────────────────────


def test_list_drops_full_base64_in_source():
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("async def ai_hotel_captures("):src.index("async def ai_hotel_capture_audio_detail(")]
    assert 'd["thumb"] = _ai_hotel_thumb_data_url(' in seg
    assert 'd["image_count"]' in seg
    # full images[] / image fields removed from the list payload
    assert 'd["images"] = images' not in seg
    assert 'd["image"] = images[0]' not in seg
    assert "def _ai_hotel_thumb_data_url(" in src
    assert "async def ai_hotel_capture_images_detail(" in src


# ─── Real-JPEG fixture ──────────────────────────────────────────────────────


def _jpeg_b64(px: int = 1400) -> str:
    from PIL import Image as PILImage
    img = PILImage.effect_noise((px, px), 120).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return _b64.b64encode(buf.getvalue()).decode("ascii")


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


# ─── Unit: the thumbnail helper (needs dashboard import) ────────────────────


@_skip
def test_thumb_helper_shrinks_real_jpeg():
    import outputs.dashboard as dash
    big = _jpeg_b64(1400)
    thumb = dash._ai_hotel_thumb_data_url(big, "image/jpeg")
    assert thumb and thumb.startswith("data:image/jpeg;base64,")
    # thumbnail must be dramatically smaller than the source
    assert len(thumb) < len(big) // 3


@_skip
def test_thumb_helper_fail_soft():
    import outputs.dashboard as dash
    assert dash._ai_hotel_thumb_data_url(None) is None
    assert dash._ai_hotel_thumb_data_url("QUJD") is None       # "ABC" — not an image
    assert dash._ai_hotel_thumb_data_url("not base64 at all!!") is None


# ─── TestClient stub ─────────────────────────────────────────────────────────


class _RDCursor:
    def __init__(self, store):
        self.s = store
        self._rows = []

    def execute(self, sql, params=None):
        if "FROM ai_hotel_capture_images" in sql and "ANY(" in sql:           # list children
            ids = params[0] if params else []
            kids = [dict(i) for i in self.s.images if i["capture_id"] in ids]
            self._rows = sorted(kids, key=lambda i: (i["capture_id"], i["ordinal"]))
        elif "FROM ai_hotel_capture_images" in sql:                            # detail (single id)
            cid = params[0] if params else None
            kids = [dict(i) for i in self.s.images if i["capture_id"] == cid]
            self._rows = sorted(kids, key=lambda i: i["ordinal"])
        elif "FROM ai_hotel_form_records" in sql:
            self._rows = []
        elif "FROM ai_hotel_capture_audio" in sql:
            self._rows = []
        elif "FROM ai_hotel_captures" in sql and "WHERE id =" in sql:          # legacy parent fallback
            cid = params[0] if params else None
            r = next((c for c in self.s.captures if c["id"] == cid), None)
            self._rows = [dict(r)] if (r and r.get("image_b64")) else []
        elif "FROM ai_hotel_captures" in sql:                                  # feed list
            rows = [c for c in self.s.captures if c.get("status") != "dismissed"]
            self._rows = [dict(c) for c in sorted(rows, key=lambda c: c["created_at"], reverse=True)]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, store):
        self.s = store

    def cursor(self, cursor_factory=None):
        return _RDCursor(self.s)

    def commit(self):
        pass

    def rollback(self):
        pass


class _Store:
    def __init__(self):
        self.captures = []
        self.images = []

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _cap(cid, img_b64=None, status="new"):
    return {"id": cid, "created_at": _dt.datetime(2026, 6, 19, 9, cid % 60, 0), "source": "photo",
            "note_text": "note", "image_b64": img_b64, "image_media": ("image/jpeg" if img_b64 else None),
            "section_guess": "general", "related_area": None, "summary": "cap %d" % cid, "status": status}


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}


# ─── AC1: list = thumbnails only, no full-res base64 ────────────────────────


@_skip
def test_ac1_list_returns_thumb_not_full_base64(monkeypatch):
    store = _Store()
    big = _jpeg_b64(1400)                       # a chunky source image
    store.captures = [_cap(1)]
    store.images = [{"capture_id": 1, "ordinal": 0, "image_b64": big, "image_media": "image/jpeg"}]
    client = _client(monkeypatch, store)
    resp = client.get("/api/ai-hotel/captures", headers=_HDR)
    assert resp.status_code == 200, resp.text
    body = resp.text
    item = resp.json()["captures"][0]
    # new contract
    assert item["image_count"] == 1
    assert item["thumb"] and item["thumb"].startswith("data:image/jpeg;base64,")
    assert "images" not in item and "image" not in item and "image_b64" not in item
    # the full-res source base64 must NOT appear anywhere in the list payload
    assert big not in body
    # thumb is small — whole feed stays tiny even with a big stored image
    assert len(body) < 60_000


# ─── AC2: full images on tap ────────────────────────────────────────────────


@_skip
def test_ac2_images_detail_returns_full_ordered(monkeypatch):
    store = _Store()
    a, b, c = _jpeg_b64(200), _jpeg_b64(200), _jpeg_b64(200)
    store.captures = [_cap(7)]
    store.images = [
        {"capture_id": 7, "ordinal": 2, "image_b64": c, "image_media": "image/jpeg"},
        {"capture_id": 7, "ordinal": 0, "image_b64": a, "image_media": "image/jpeg"},
        {"capture_id": 7, "ordinal": 1, "image_b64": b, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)
    imgs = client.get("/api/ai-hotel/captures/7/images", headers=_HDR).json()["images"]
    assert len(imgs) == 3
    assert imgs[0] == "data:image/jpeg;base64," + a       # ordered by ordinal
    assert imgs[2] == "data:image/jpeg;base64," + c


@_skip
def test_ac2_images_detail_requires_auth(monkeypatch):
    client = _client(monkeypatch, _Store())
    assert client.get("/api/ai-hotel/captures/1/images").status_code == 401


@_skip
def test_images_detail_legacy_parent_fallback(monkeypatch):
    store = _Store()
    legacy = _jpeg_b64(200)
    store.captures = [_cap(9, img_b64=legacy)]     # parent image_b64, no child rows
    client = _client(monkeypatch, store)
    imgs = client.get("/api/ai-hotel/captures/9/images", headers=_HDR).json()["images"]
    assert imgs == ["data:image/jpeg;base64," + legacy]


# ─── AC3: no images → thumb null, count 0, still listed ─────────────────────


@_skip
def test_ac3_no_images_thumb_null(monkeypatch):
    store = _Store()
    store.captures = [_cap(3, img_b64=None)]       # note-only capture
    client = _client(monkeypatch, store)
    item = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]
    assert item["thumb"] is None
    assert item["image_count"] == 0


# ─── AC4: corrupt stored image → thumb null, feed never 500s ────────────────


@_skip
def test_ac4_corrupt_image_fail_soft(monkeypatch):
    store = _Store()
    good = _jpeg_b64(300)
    store.captures = [_cap(4), _cap(5)]
    store.images = [
        {"capture_id": 4, "ordinal": 0, "image_b64": "QUJD", "image_media": "image/jpeg"},   # corrupt
        {"capture_id": 5, "ordinal": 0, "image_b64": good, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)
    resp = client.get("/api/ai-hotel/captures", headers=_HDR)
    assert resp.status_code == 200                  # never 500
    caps = {c["id"]: c for c in resp.json()["captures"]}
    assert caps[4]["thumb"] is None and caps[4]["image_count"] == 1   # corrupt → null thumb, counted
    assert caps[5]["thumb"] is not None and caps[5]["image_count"] == 1
