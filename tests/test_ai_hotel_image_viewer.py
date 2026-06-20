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
    # both read-auth gated (master key or scoped AI-Hotel PIN cookie)
    seg = src[src.index('"/api/ai-hotel/captures/{capture_id}/thumbs"'):
              src.index('"/api/ai-hotel/captures/{capture_id}/media"')]
    assert seg.count("Depends(verify_ai_hotel_read_access)") >= 2


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
        if "FROM ai_hotel_capture_images" in sql and "AND ordinal = %s" in sql:
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
def test_new_endpoints_require_auth(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    assert client.get("/api/ai-hotel/captures/17/thumbs").status_code == 401
    assert client.get("/api/ai-hotel/captures/17/images/0").status_code == 401
