"""AI_HOTEL_FIELDNOTES_IMAGE_VIEWER_FIX_1 — tap-to-enlarge lightbox + on-demand
single-image load (no 2 MB upfront blob).

Diagnosis (live): the photos DID render; the gaps were (a) the detail modal pulled
ALL full-res images in one response (capture 17 = 2.07 MB → "Loading photos…" hang
on cellular) and (b) they showed as un-enlargeable 44px crops buried under GPS/audio.

  AC2  detail strip loads small per-image thumbs (GET /thumbs), not the full set.
  ---  GET /captures/{id}/images/{idx} returns ONE full-res image (lightbox load).
  AC5  both new endpoints are auth-gated; out-of-range index is fail-soft (null).
  KILL the list/feed stays thumbnail-only (#383 invariant) — no full base64 upfront.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest


# ─── Source guards (always run) ─────────────────────────────────────────────


def test_modal_strip_uses_thumbs_not_full_set():
    src = Path("outputs/static/ai-hotel.html").read_text()
    rp = src[src.index("function renderPhotos(b, c)"):src.index("function openLightbox(")]
    # strip fetches the small per-image thumbs endpoint, NOT the 2MB all-images one
    assert "/thumbs'" in rp
    assert "/captures/'+c.id+'/images'" not in rp           # no upfront full-res blob
    assert "openLightbox(c,i)" in rp                         # each thumb is tap-to-enlarge


def test_lightbox_loads_single_image_on_demand():
    src = Path("outputs/static/ai-hotel.html").read_text()
    lb = src[src.index("function openLightbox("):src.index("function openNoteDetail(")]
    # loads ONE image by index on demand (not the whole set)
    assert "/captures/'+c.id+'/images/'+idx" in lb
    assert "ArrowLeft" in lb and "ArrowRight" in lb         # keyboard nav
    assert "Escape" in lb                                    # esc closes
    assert "touchstart" in lb and "touchend" in lb          # swipe
    assert "cache[idx]" in lb                                # don't refetch a viewed image


def test_lightbox_has_persistent_rotate_control():
    src = Path("outputs/static/ai-hotel.html").read_text()
    lb = src[src.index("function openLightbox("):src.index("function openNoteDetail(")]
    assert "lbox-rotate" in src
    assert "Rotate photo clockwise" in lb
    assert "/captures/'+c.id+'/images/'+idx+'/rotate" in lb
    assert "aiHotelJsonOptions({deg:90})" in lb
    assert "updatePhotoThumbs(c,idx" in lb


def test_rotate_thumb_update_does_not_replace_feed_for_non_first_photo():
    src = Path("outputs/static/ai-hotel.html").read_text()
    fn = src[src.index("function updatePhotoThumbs("):src.index("function cardAsText(")]
    assert "if(idx===0)" in fn
    assert ".nthumb[data-capture-id" in fn
    assert "data-photo-idx" in fn


def test_photos_block_moved_above_gps_and_audio():
    src = Path("outputs/static/ai-hotel.html").read_text()
    start = src.index("function openNoteDetail(")
    end = src.index("\nfunction ", start + 10)               # next function after openNoteDetail
    det = src[start:end]
    pos_photos = det.index("renderPhotos(b, c)")
    pos_gps = det.index("AI_HOTEL_GPS_CAPTURE_1: location evidence")
    pos_audio = det.index("dlg-h','Audio")
    assert pos_photos < pos_gps < pos_audio                  # photos first, then GPS, then audio


def test_feed_list_invariant_383_held():
    """KILL criterion: the in-feed card still uses the tiny server thumb, never a
    full-res image — the #383 invariant must not regress."""
    src = Path("outputs/static/ai-hotel.html").read_text()
    bnc = src[src.index("function buildNoteCard(c)"):src.index("function cardAsText(")]
    assert "img.src=c.thumb" in bnc                          # feed thumbnail unchanged


def test_backend_endpoints_exist():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/ai-hotel/captures/{capture_id}/thumbs"' in src
    assert '"/api/ai-hotel/captures/{capture_id}/images/{idx}"' in src
    assert '"/api/ai-hotel/captures/{capture_id}/images/{idx}/rotate"' in src
    assert "ImageOps.exif_transpose" in src
    assert "_ai_hotel_image_data_url" in src
    assert "_ai_hotel_rotate_image_b64" in src
    # both read-auth gated (master key or scoped AI-Hotel PIN cookie)
    seg = src[src.index('"/api/ai-hotel/captures/{capture_id}/thumbs"'):
              src.index('"/api/ai-hotel/captures/{capture_id}/media"')]
    assert seg.count("Depends(verify_ai_hotel_read_access)") >= 2
    assert "Depends(verify_ai_hotel_photo_edit_access)" in seg
    assert "UPDATE ai_hotel_capture_images" in seg
    assert "UPDATE ai_hotel_captures" in seg
    assert "AND image_b64 = %s" in seg


def test_photo_css_has_exif_orientation_fallback():
    src = Path("outputs/static/ai-hotel.html").read_text()
    assert "image-orientation:from-image" in src
    assert ".nthumb,.nthumbs img,.lbox-img" in src


# ─── TestClient backend behaviour ───────────────────────────────────────────


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(not _dashboard_importable(), reason="dashboard unimportable (Py3.9 PEP-604)")


class _Cur:
    def __init__(self, store):
        self.s = store
        self._res = []

    def execute(self, sql, params=None):
        if "UPDATE ai_hotel_capture_images" in sql:
            new_b64, new_media, cid, idx, old_b64 = params
            self._res = []
            for r in self.s.images:
                if (
                    r["capture_id"] == cid
                    and r["ordinal"] == idx
                    and r["image_b64"] == old_b64
                ):
                    r["image_b64"] = new_b64
                    r["image_media"] = new_media
                    self._res = [{"ordinal": idx}]
                    break
        elif "UPDATE ai_hotel_captures" in sql:
            if len(params) == 3:
                new_b64, new_media, cid = params
                old_b64 = None
            else:
                new_b64, new_media, cid, old_b64 = params
            self._res = []
            for r in self.s.parents:
                if r["id"] == cid and (old_b64 is None or r.get("image_b64") == old_b64):
                    r["image_b64"] = new_b64
                    r["image_media"] = new_media
                    self._res = [{"id": cid}]
                    break
        elif "FROM ai_hotel_capture_images" in sql and "AND ordinal = %s" in sql:
            cid, idx = params
            self._res = [r for r in self.s.images if r["capture_id"] == cid and r["ordinal"] == idx][:1]
        elif "FROM ai_hotel_capture_images" in sql:                       # ordered list
            cid = params[0]
            self._res = sorted([r for r in self.s.images if r["capture_id"] == cid],
                               key=lambda r: r["ordinal"])
        elif "FROM ai_hotel_captures" in sql:                            # legacy parent
            cid = params[0]
            self._res = [r for r in self.s.parents if r["id"] == cid][:1]
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
        self.images = []   # {capture_id, ordinal, image_b64, image_media}
        self.parents = []  # {id, image_b64, image_media}

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
    # avoid PIL — make the thumb helper a cheap deterministic marker
    monkeypatch.setattr(dash, "_ai_hotel_thumb_data_url",
                        lambda b64, media="image/jpeg", px=160: "THUMB:" + b64[:4])
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}


def _exif_rotated_jpeg_b64() -> str:
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (40, 20), "white")
    exif = PILImage.Exif()
    exif[274] = 6
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _plain_jpeg_b64(size: tuple[int, int] = (80, 40)) -> str:
    from PIL import Image as PILImage

    img = PILImage.new("RGB", size, "white")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _image_size_from_data_url(url: str) -> tuple[int, int]:
    from PIL import Image as PILImage

    raw = base64.b64decode(url.split(",", 1)[1])
    img = PILImage.open(BytesIO(raw))
    img.load()
    return img.size


@_skip
def test_thumbs_returns_small_ordered_per_image(monkeypatch):
    store = _Store()
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": "AAAAfull0", "image_media": "image/jpeg"},
        {"capture_id": 17, "ordinal": 1, "image_b64": "BBBBfull1", "image_media": "image/jpeg"},
        {"capture_id": 17, "ordinal": 2, "image_b64": "CCCCfull2", "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)
    d = client.get("/api/ai-hotel/captures/17/thumbs", headers=_HDR).json()
    assert d["thumbs"] == ["THUMB:AAAA", "THUMB:BBBB", "THUMB:CCCC"]   # ordered, small markers


@_skip
def test_upload_resize_transposes_phone_exif_orientation():
    import outputs.dashboard as dash

    raw = base64.b64decode(_exif_rotated_jpeg_b64())
    resized_b64, media = dash._ai_hotel_resize_for_db(raw, "image/jpeg")
    assert media == "image/jpeg"
    width, height = _image_size_from_data_url(f"data:image/jpeg;base64,{resized_b64}")
    assert height > width


@_skip
def test_thumbnail_transposes_phone_exif_orientation():
    import outputs.dashboard as dash

    thumb = dash._ai_hotel_thumb_data_url(_exif_rotated_jpeg_b64(), "image/jpeg", px=160)
    assert thumb is not None
    width, height = _image_size_from_data_url(thumb)
    assert height > width


@_skip
def test_single_image_by_index_and_fail_soft(monkeypatch):
    store = _Store()
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": "AAAAfull0", "image_media": "image/jpeg"},
        {"capture_id": 17, "ordinal": 1, "image_b64": "BBBBfull1", "image_media": "image/png"},
    ]
    client = _client(monkeypatch, store)
    # in-range returns the single full-res data-URL for that ordinal
    d1 = client.get("/api/ai-hotel/captures/17/images/1", headers=_HDR).json()
    assert d1["image"] == "data:image/png;base64,BBBBfull1"
    # out-of-range → fail-soft null, never 500
    r2 = client.get("/api/ai-hotel/captures/17/images/9", headers=_HDR)
    assert r2.status_code == 200 and r2.json()["image"] is None


@_skip
def test_single_image_endpoint_transposes_phone_exif_orientation(monkeypatch):
    store = _Store()
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": _exif_rotated_jpeg_b64(), "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)

    data_url = client.get("/api/ai-hotel/captures/17/images/0", headers=_HDR).json()["image"]

    width, height = _image_size_from_data_url(data_url)
    assert height > width


@_skip
def test_rotate_endpoint_persists_child_image_and_returns_new_thumb(monkeypatch):
    store = _Store()
    original = _plain_jpeg_b64((80, 40))
    store.parents = [
        {"id": 17, "image_b64": original, "image_media": "image/jpeg"},
    ]
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": original, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/images/0/rotate",
        headers=_HDR,
        json={"deg": 90},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["deg"] == 90
    assert body["thumb"].startswith("THUMB:")
    assert store.images[0]["image_b64"] != original
    assert store.parents[0]["image_b64"] == store.images[0]["image_b64"]
    assert _image_size_from_data_url(body["image"]) == (40, 80)
    detail = client.get("/api/ai-hotel/captures/17/images/0", headers=_HDR).json()["image"]
    assert _image_size_from_data_url(detail) == (40, 80)


@_skip
def test_rotate_endpoint_updates_legacy_parent_fallback(monkeypatch):
    store = _Store()
    original = _plain_jpeg_b64((90, 30))
    store.parents = [
        {"id": 9, "image_b64": original, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/9/images/0/rotate",
        headers=_HDR,
        json={"deg": 90},
    )

    assert resp.status_code == 200, resp.text
    assert store.parents[0]["image_b64"] != original
    assert _image_size_from_data_url(resp.json()["image"]) == (30, 90)


@_skip
def test_rotate_endpoint_accepts_scoped_pin_cookie(monkeypatch):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    store = _Store()
    original = _plain_jpeg_b64((80, 40))
    store.parents = [
        {"id": 17, "image_b64": original, "image_media": "image/jpeg"},
    ]
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": original, "image_media": "image/jpeg"},
    ]
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("AI_HOTEL_PIN", "6470")
    monkeypatch.setenv("AI_HOTEL_SESSION_SECRET", "session-secret")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    dash._ai_hotel_pin_state.clear()
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    dash.app.dependency_overrides.pop(dash.verify_ai_hotel_read_access, None)
    dash.app.dependency_overrides.pop(dash.verify_ai_hotel_photo_edit_access, None)
    client = TestClient(dash.app, base_url="https://testserver")

    pin = client.post("/api/ai-hotel/pin-auth", json={"pin": "6470"})
    resp = client.post("/api/ai-hotel/captures/17/images/0/rotate", json={"deg": 90})

    assert pin.status_code == 200
    assert resp.status_code == 200, resp.text
    assert store.images[0]["image_b64"] != original
    assert store.parents[0]["image_b64"] == store.images[0]["image_b64"]


@_skip
def test_rotate_endpoint_rejects_invalid_degree_without_mutating(monkeypatch):
    store = _Store()
    original = _plain_jpeg_b64((80, 40))
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": original, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/images/0/rotate",
        headers=_HDR,
        json={"deg": 45},
    )

    assert resp.status_code == 400
    assert store.images[0]["image_b64"] == original


@_skip
def test_rotate_endpoint_bad_image_loses_nothing(monkeypatch):
    store = _Store()
    original = "not base64 at all!!"
    store.images = [
        {"capture_id": 17, "ordinal": 0, "image_b64": original, "image_media": "image/jpeg"},
    ]
    client = _client(monkeypatch, store)

    resp = client.post(
        "/api/ai-hotel/captures/17/images/0/rotate",
        headers=_HDR,
        json={"deg": 90},
    )

    assert resp.status_code == 400
    assert store.images[0]["image_b64"] == original


@_skip
def test_new_endpoints_require_auth(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    assert client.get("/api/ai-hotel/captures/17/thumbs").status_code == 401
    assert client.get("/api/ai-hotel/captures/17/images/0").status_code == 401
    assert client.post(
        "/api/ai-hotel/captures/17/images/0/rotate",
        json={"deg": 90},
    ).status_code == 401
