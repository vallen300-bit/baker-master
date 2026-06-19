"""AI_HOTEL_GPS_CAPTURE_1 — capture-level GPS evidence.

AC1  capture WITH a GPS payload → coords + accuracy + captured_at stored on ai_hotel_captures.
AC2  permission-denied → capture still created (no GPS, gps_address_status='permission_denied').
AC3  reverse-geocode failure → coords stored, gps_address=NULL, status='geocode_failed'.
AC4  stale GPS (>10 min) → client warns + allows retry/proceed (client-side; source-asserted).
AC5  low-accuracy (>150 m) is flagged, NOT geocoded into a precise-looking address.
AC6  existing captures (null GPS) render cleanly — gps=None, no error.
AC7  CHECK constraints reject out-of-range lat/lng; server drops out-of-range coords too.
AC8  Maps deep link is built from lat/lng (URL-encoded), never from the free-text address.
AC9  GPS fields are NOT written to vector/Qdrant/wiki memory.
AC10 reverse-geocode runs once at insert, never on the captures GET.

The reverse-geocode + LLM + vector-ingest seams are mocked — no network. TestClient
runs skip cleanly when outputs.dashboard cannot import (Py 3.9 PEP-604 chain).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


# ─── Source / migration checks (always run, no import needed) ───────────────


def test_migration_shape():
    mig = Path("migrations/20260619c_ai_hotel_captures_gps.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS gps_lat" in mig
    assert "gps_lng" in mig and "gps_accuracy_m" in mig and "gps_captured_at" in mig
    assert "gps_address" in mig and "gps_address_source" in mig and "gps_address_status" in mig
    # AC7: CHECK constraints present (defense-in-depth).
    assert "gps_lat BETWEEN -90 AND 90" in mig
    assert "gps_lng BETWEEN -180 AND 180" in mig
    assert "gps_accuracy_m IS NULL OR gps_accuracy_m >= 0" in mig
    assert "gps_address_source IN ('google','nominatim')" in mig
    # up section must not DROP (mirrors the sibling migrations' safety note).
    up = mig.split("== migrate:down ==")[0]
    assert "DROP TABLE" not in up and "DROP COLUMN" not in up


def test_ac8_maps_link_built_from_latlng_not_address():
    """AC8: the Open-in-Maps link is generated from lat/lng (URL-encoded), never
    from the free-text address."""
    src = Path("outputs/static/ai-hotel.html").read_text()
    # The link uses encodeURIComponent of the lat,lng pair…
    assert "encodeURIComponent(Number(g.lat)+','+Number(g.lng))" in src
    assert "https://maps.google.com/?q='+q" in src
    assert "'geo:'+q" in src
    # …and the address is never concatenated into a maps URL.
    assert "maps.google.com/?q='+g.address" not in src
    assert "maps.google.com/?q='+encodeURIComponent(g.address" not in src


def test_ac4_client_stale_and_retry_logic_present():
    """AC4: capture page warns on a >10-min-old fix and allows retry/proceed."""
    cap = Path("outputs/static/ai-hotel-capture.html").read_text()
    assert "STALE_MS" in cap and "10*60*1000" in cap
    assert "gpsStaleOkToSend" in cap
    assert "getCurrentPosition" in cap
    assert "enableHighAccuracy:true" in cap and "timeout:10000" in cap and "maximumAge:0" in cap
    # permission-denied / timeout are non-blocking (capture still saves).
    assert "permission_denied" in cap and "timeout" in cap


def test_ac5_display_flags_low_accuracy():
    """AC5: the renderer has explicit accuracy tiers and a low tier that is NOT
    shown as a primary/exact location."""
    src = Path("outputs/static/ai-hotel.html").read_text()
    assert "function gpsAccuracyTier" in src
    assert "accuracy_m<=50" in src and "accuracy_m<=150" in src
    # low tier returns 'low' and compactLocation never returns a GPS address for it
    assert "return 'low'" in src
    assert "tier==='verified'" in src and "tier==='approx'" in src


def test_ac9_gps_not_in_vector_ingest_body_source():
    """AC9 (source guard): the capture endpoint's kbl ingest body is built from
    summary + note only — no gps_ fields are ever passed to the vector layer."""
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("def ai_hotel_capture("):src.index("async def ai_hotel_captures(")]
    ingest_seg = seg[seg.index("from kbl.ingest_endpoint import ingest"):]
    body_call = ingest_seg[:ingest_seg.index("trigger_source")]
    assert "gps_lat" not in body_call and "gps_lng" not in body_call and "gps_address" not in body_call


# ─── TestClient harness ─────────────────────────────────────────────────────


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


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.usage = _FakeUsage()


class _Cur:
    def __init__(self, store):
        self.s = store
        self._res = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.rowcount = 0
        if "INSERT INTO ai_hotel_captures" in sql:
            source, note, b64, media, section, related, summary = params
            nid = self.s.nextcap; self.s.nextcap += 1
            self.s.captures.append({
                "id": nid, "source": source, "note_text": note, "summary": summary,
                "status": "new", "image_b64": b64, "image_media": media,
                "section_guess": section, "related_area": related,
                "created_at": _dt.datetime(2026, 6, 19, 9, nid % 60, 0),
                # gps columns default NULL (set later by the UPDATE).
                "gps_lat": None, "gps_lng": None, "gps_accuracy_m": None,
                "gps_captured_at": None, "gps_address": None,
                "gps_address_source": None, "gps_address_status": None,
            })
            self._res = [(nid,)]; self.rowcount = 1
        elif "UPDATE ai_hotel_captures" in sql and "gps_lat" in sql:
            lat, lng, acc, cap_at, addr, src, status, cid = params
            for r in self.s.captures:
                if r["id"] == cid:
                    r["gps_lat"] = lat; r["gps_lng"] = lng; r["gps_accuracy_m"] = acc
                    r["gps_captured_at"] = cap_at; r["gps_address"] = addr
                    r["gps_address_source"] = src; r["gps_address_status"] = status
            self.rowcount = 1
        elif "INSERT INTO ai_hotel_capture_images" in sql:
            cid, ordi, b64, media = params
            self.s.images.append({"capture_id": cid, "ordinal": ordi,
                                  "image_b64": b64, "image_media": media})
            self.rowcount = 1
        elif "FROM ai_hotel_capture_images" in sql:
            ids = params[0] if params else []
            kids = [dict(i) for i in self.s.images if i["capture_id"] in ids]
            self._res = sorted(kids, key=lambda i: (i["capture_id"], i["ordinal"]))
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
        self.captures = []
        self.images = []
        self.nextcap = 1

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, store, geocode=None):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    import orchestrator.cost_monitor as cm
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    monkeypatch.setattr(cm, "log_api_cost", lambda *a, **k: None)
    # classification LLM → harmless stub (capture stays 'general').
    monkeypatch.setattr(dash, "_llm_call", lambda *a, **k: _FakeResp("{}"))
    # reverse-geocode seam — count calls (AC10) and return a fake address.
    calls = {"n": 0}

    def _default_geo(lat, lng):
        calls["n"] += 1
        return ("742 Evergreen Terrace, Springfield", "nominatim")

    monkeypatch.setattr(dash, "_ai_hotel_reverse_geocode", geocode or _default_geo)
    # vector ingest seam — record bodies (AC9), never touch network/Qdrant.
    import kbl.ingest_endpoint as ie
    ingested = []

    class _IngestResult:
        qdrant_point_id = None

    def _fake_ingest(frontmatter=None, body=None, trigger_source=None, **k):
        ingested.append({"frontmatter": frontmatter, "body": body})
        return _IngestResult()

    monkeypatch.setattr(ie, "ingest", _fake_ingest)
    client = TestClient(dash.app)
    client._geo_calls = calls
    client._ingested = ingested
    return client


_HDR = {"X-Baker-Key": "test-key"}


# ─── AC1: coords + accuracy + captured_at persisted ─────────────────────────


@_skip
def test_ac1_gps_payload_persisted(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Vacant lot by the campus.",
        "gps_lat": "37.4419", "gps_lng": "-122.1430",
        "gps_accuracy_m": "8", "gps_captured_at": "2026-06-19T10:00:00+00:00",
        "gps_capture_method": "manual_tag_location",
    })
    assert resp.status_code == 200, resp.text
    cap = store.captures[0]
    assert abs(cap["gps_lat"] - 37.4419) < 1e-6
    assert abs(cap["gps_lng"] - (-122.1430)) < 1e-6
    assert abs(cap["gps_accuracy_m"] - 8.0) < 1e-6
    assert cap["gps_captured_at"] is not None
    assert cap["gps_address_status"] == "ok"
    assert cap["gps_address"] == "742 Evergreen Terrace, Springfield"
    assert cap["gps_address_source"] == "nominatim"
    assert client._geo_calls["n"] == 1   # geocoded exactly once at insert


# ─── AC2: permission-denied still saves the capture ─────────────────────────


@_skip
def test_ac2_permission_denied_still_saves(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Note without location.",
        "gps_address_status": "permission_denied",
    })
    assert resp.status_code == 200, resp.text
    assert len(store.captures) == 1
    cap = store.captures[0]
    assert cap["gps_lat"] is None and cap["gps_lng"] is None
    assert cap["gps_address_status"] == "permission_denied"
    assert client._geo_calls["n"] == 0   # no coords → no geocode


# ─── AC3: reverse-geocode failure keeps coords, address NULL ────────────────


@_skip
def test_ac3_geocode_failure_keeps_coords(monkeypatch):
    store = _Store()

    def _boom(lat, lng):
        return (None, None)   # the helper swallows errors → (None, None)

    client = _client(monkeypatch, store, geocode=_boom)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Site with bad geocode.",
        "gps_lat": "48.2082", "gps_lng": "16.3738", "gps_accuracy_m": "12",
    })
    assert resp.status_code == 200, resp.text
    cap = store.captures[0]
    assert abs(cap["gps_lat"] - 48.2082) < 1e-6      # coords kept
    assert cap["gps_address"] is None                 # no address
    assert cap["gps_address_status"] == "geocode_failed"


# ─── AC5: low-accuracy flagged, NOT geocoded ────────────────────────────────


@_skip
def test_ac5_low_accuracy_not_geocoded(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Fuzzy fix.",
        "gps_lat": "37.4419", "gps_lng": "-122.1430", "gps_accuracy_m": "300",
    })
    assert resp.status_code == 200, resp.text
    cap = store.captures[0]
    assert cap["gps_address_status"] == "low_accuracy"
    assert cap["gps_address"] is None                 # a >150 m fix is never geocoded
    assert client._geo_calls["n"] == 0                # geocode skipped for low accuracy
    assert abs(cap["gps_accuracy_m"] - 300.0) < 1e-6  # accuracy still recorded


# ─── AC7: out-of-range coords rejected server-side ──────────────────────────


@_skip
def test_ac7_out_of_range_coords_dropped(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Bad coords.",
        "gps_lat": "999", "gps_lng": "500", "gps_accuracy_m": "5",
    })
    assert resp.status_code == 200, resp.text   # capture still saved
    cap = store.captures[0]
    assert cap["gps_lat"] is None and cap["gps_lng"] is None   # junk coords dropped
    assert cap["gps_address_status"] != "ok"
    assert client._geo_calls["n"] == 0


# ─── AC6 + AC10: feed shape, gps=None for legacy, no geocode on GET ─────────


@_skip
def test_ac6_legacy_rows_render_and_ac10_no_geocode_on_get(monkeypatch):
    store = _Store()
    # one legacy capture (no GPS) + one with GPS
    store.captures = [
        {"id": 1, "source": "note", "note_text": "legacy", "summary": "legacy",
         "status": "new", "image_b64": None, "image_media": None,
         "section_guess": "general", "related_area": None,
         "created_at": _dt.datetime(2026, 6, 19, 9, 0, 0)},
        {"id": 2, "source": "note", "note_text": "geo", "summary": "geo",
         "status": "new", "image_b64": None, "image_media": None,
         "section_guess": "general", "related_area": None,
         "created_at": _dt.datetime(2026, 6, 19, 9, 5, 0),
         "gps_lat": 37.44, "gps_lng": -122.14, "gps_accuracy_m": 8.0,
         "gps_captured_at": _dt.datetime(2026, 6, 19, 9, 4, 0),
         "gps_address": "742 Evergreen Terrace", "gps_address_source": "nominatim",
         "gps_address_status": "ok"},
    ]
    client = _client(monkeypatch, store)
    items = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"]
    by_id = {it["id"]: it for it in items}
    # AC6: legacy row renders, gps is None, no stray flat gps_ keys leaked.
    assert by_id[1]["gps"] is None
    assert "gps_lat" not in by_id[1]
    # GPS row carries a compact gps object.
    g = by_id[2]["gps"]
    assert g and abs(g["lat"] - 37.44) < 1e-6 and g["address"] == "742 Evergreen Terrace"
    assert g["accuracy_m"] == 8.0 and g["address_status"] == "ok"
    assert isinstance(g["captured_at"], str)   # serialized to ISO
    # AC10: a GET must never trigger reverse-geocoding.
    assert client._geo_calls["n"] == 0


# ─── AC9: GPS never reaches the vector layer (behavioral) ───────────────────


@_skip
def test_ac9_gps_not_sent_to_vector(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.post("/api/ai-hotel/capture", headers=_HDR, data={
        "note": "Embed this note text only.",
        "gps_lat": "37.4419", "gps_lng": "-122.1430", "gps_accuracy_m": "8",
    })
    assert resp.status_code == 200, resp.text
    assert client._ingested, "expected a vector ingest for a note capture"
    for rec in client._ingested:
        blob = repr(rec)
        # neither the coordinates nor the accuracy reach the vector layer
        assert "37.4419" not in blob and "-122.1430" not in blob and "742 Evergreen" not in blob
        # frontmatter carries no gps_* keys
        assert not any(str(k).startswith("gps") for k in (rec.get("frontmatter") or {}))
