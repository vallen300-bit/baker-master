"""AI_HOTEL_FIELD_NOTES_CARD_SHELF_1 — saved structured cards folded into the
Field Notes feed.

Public interface: the EXTENDED GET /api/ai-hotel/captures (now carries an
optional `form_record` per capture). Load-bearing test: AC5 (a bad/missing/
discarded form record never breaks the raw capture feed).

Source-level UI checks always run. TestClient runs skip cleanly when
outputs.dashboard cannot import (local Python 3.9 PEP-604 chain — clears on 3.10+).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


# ─── Unit: the fail-soft form_record shaper (always runs) ───────────────────


def test_form_record_view_confirmed_prefers_corrected():
    import outputs.dashboard as dash  # import guarded by the skip below for TestClient
    # If dashboard can't import locally, this unit test still needs it; skip then.
    fr = {"id": 5, "capture_id": 1, "form_type": "site_visit", "schema_version": "site_visit_v1",
          "status": "confirmed", "extracted_json": {"overall_score": "2"},
          "corrected_json": {"overall_score": "4"}, "field_meta_json": {"overall_score": {"critical": False}}}
    v = dash._ai_hotel_form_record_view(fr)
    assert v["form_type"] == "site_visit"
    assert v["status"] == "confirmed"
    assert v["values"]["overall_score"] == "4"   # corrected wins for confirmed


def test_form_record_view_draft_uses_extracted():
    import outputs.dashboard as dash
    fr = {"id": 6, "capture_id": 2, "form_type": "supplier_card", "schema_version": "supplier_card_v1",
          "status": "draft", "extracted_json": {"company_name": "NVIDIA"},
          "corrected_json": None, "field_meta_json": {}}
    v = dash._ai_hotel_form_record_view(fr)
    assert v["values"]["company_name"] == "NVIDIA"


def test_form_record_view_malformed_is_fail_soft():
    import outputs.dashboard as dash
    assert dash._ai_hotel_form_record_view(None) is None
    # extracted_json is a string, not a dict → values coerced to {} (never raises)
    bad = {"id": 7, "capture_id": 3, "form_type": "site_visit", "schema_version": "x",
           "status": "draft", "extracted_json": "not-a-dict", "corrected_json": None,
           "field_meta_json": "also-bad"}
    v = dash._ai_hotel_form_record_view(bad)
    assert v["values"] == {} and v["field_meta"] == {}


# ─── Source-level checks (always run) ───────────────────────────────────────


def test_endpoint_has_form_record_join():
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("async def ai_hotel_captures("):src.index("# ── AI_HOTEL_VOICE_FORM")]
    assert "FROM ai_hotel_form_records" in seg
    assert "DISTINCT ON (capture_id)" in seg
    assert "status <> 'discarded'" in seg
    assert "capture_id = ANY(%s)" in seg
    assert '_ai_hotel_form_record_view(' in seg
    # No image base64 duplicated into the form-record SELECT clause (kill criterion).
    fq = seg[seg.index("DISTINCT ON (capture_id)"):seg.index("FROM ai_hotel_form_records")]
    assert "image_b64" not in fq


def test_ui_has_chips_filters_detail():
    html = Path("outputs/static/ai-hotel.html").read_text()
    # type chips
    assert "function cardKind(" in html
    assert "kind-site" in html and "kind-supplier" in html and "kind-free" in html
    # filters (AC4)
    assert "Site Cards" in html and "Suppliers" in html and "Free Notes" in html
    # detail view (AC3) + actions
    assert "function openNoteDetail(" in html
    assert "Copy card text" in html
    assert "/discard" in html          # dismiss reuses the #380 endpoint
    # XSS-safe: card data must never be assigned via innerHTML
    assert ".innerHTML" not in html


# ─── TestClient harness ─────────────────────────────────────────────────────


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


class _RDCursor:
    """Emulates a RealDictCursor over the stub store for the three feed queries."""

    def __init__(self, store):
        self.s = store
        self._rows = []

    def execute(self, sql, params=None):
        if "FROM ai_hotel_capture_images" in sql:
            ids = params[0] if params else []
            kids = [dict(i) for i in self.s.images if i["capture_id"] in ids]
            self._rows = sorted(kids, key=lambda i: (i["capture_id"], i["ordinal"]))
        elif "FROM ai_hotel_form_records" in sql:
            if self.s.raise_on_forms:
                raise RuntimeError("form_record join boom")
            ids = params[0] if params else []
            frs = [dict(f) for f in self.s.forms
                   if f["capture_id"] in ids and f.get("status") != "discarded"]
            # DISTINCT ON (capture_id) ORDER BY capture_id, id DESC → latest per capture
            latest: dict = {}
            for f in sorted(frs, key=lambda f: (f["capture_id"], f["id"])):
                latest[f["capture_id"]] = f
            self._rows = list(latest.values())
        elif "FROM ai_hotel_captures" in sql:
            rows = [r for r in self.s.captures if r.get("status") != "dismissed"]
            self._rows = [dict(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]
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
        self.forms = []
        self.raise_on_forms = False

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _cap(cid, summary="A note", source="note", note_text="hi", status="new", img=None):
    return {"id": cid, "created_at": _dt.datetime(2026, 6, 19, 9, cid % 60, 0), "source": source,
            "note_text": note_text, "image_b64": img, "image_media": ("image/jpeg" if img else None),
            "section_guess": "general", "related_area": None, "summary": summary, "status": status}


def _form(fid, cid, form_type="site_visit", status="confirmed", values=None):
    vals = values or {"overall_score": "3"}
    return {"id": fid, "capture_id": cid, "form_type": form_type,
            "schema_version": form_type + "_v1", "status": status,
            "extracted_json": vals, "corrected_json": (vals if status == "confirmed" else None),
            "field_meta_json": {}}


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}


# ─── AC1: capture without a form record → appears, Free note ────────────────


@_skip_without_dashboard
def test_ac1_capture_without_form_record_appears(monkeypatch):
    store = _Store()
    store.captures = [_cap(1, summary="Just a quick note")]
    client = _client(monkeypatch, store)
    caps = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"]
    assert len(caps) == 1
    assert caps[0]["id"] == 1
    assert caps[0]["form_record"] is None          # → UI types it "Free note"


# ─── AC2: confirmed site card → appears with Site chip ──────────────────────


@_skip_without_dashboard
def test_ac2_confirmed_site_card_appears(monkeypatch):
    store = _Store()
    store.captures = [_cap(17, summary="Palo Alto site", source="note")]
    store.forms = [_form(5, 17, "site_visit", "confirmed",
                         {"overall_score": "4", "geo_context": "Palo Alto", "hospitality_fit": "high"})]
    client = _client(monkeypatch, store)
    caps = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"]
    fr = caps[0]["form_record"]
    assert fr is not None
    assert fr["form_type"] == "site_visit"          # → UI renders the "Site" chip
    assert fr["status"] == "confirmed"
    assert fr["values"]["overall_score"] == "4"


# ─── AC3: detail carries structured fields AND raw evidence ─────────────────


@_skip_without_dashboard
def test_ac3_item_has_structured_and_raw(monkeypatch):
    store = _Store()
    store.captures = [_cap(20, summary="Booth chat", source="photo", note_text="NVIDIA at booth 14", img="QUJD")]
    store.images = [{"capture_id": 20, "ordinal": 0, "image_b64": "QUJD", "image_media": "image/jpeg"}]
    store.forms = [_form(8, 20, "supplier_card", "confirmed", {"company_name": "NVIDIA"})]
    client = _client(monkeypatch, store)
    c = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]
    # structured
    assert c["form_record"]["values"]["company_name"] == "NVIDIA"
    # raw evidence: transcript/note on the item + a photo present (image_count;
    # full photos lazy-fetched in detail per FIELDNOTES_THUMBNAIL_LAZYIMG_1).
    assert c["note_text"] == "NVIDIA at booth 14"
    assert c["image_count"] == 1


# ─── AC4: latest non-discarded wins; multiple cards collapse to one ─────────


@_skip_without_dashboard
def test_latest_non_discarded_form_record_wins(monkeypatch):
    store = _Store()
    store.captures = [_cap(30)]
    store.forms = [
        _form(1, 30, "site_visit", "draft", {"overall_score": "2"}),
        _form(9, 30, "site_visit", "confirmed", {"overall_score": "5"}),   # latest (higher id)
    ]
    client = _client(monkeypatch, store)
    fr = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]["form_record"]
    assert fr["id"] == 9 and fr["status"] == "confirmed"
    assert fr["values"]["overall_score"] == "5"


# ─── AC5: a bad / discarded form record never breaks the feed ───────────────


@_skip_without_dashboard
def test_ac5_form_record_query_failure_still_serves_captures(monkeypatch):
    store = _Store()
    store.captures = [_cap(40, summary="still here"), _cap(41)]
    store.raise_on_forms = True                      # the join blows up
    client = _client(monkeypatch, store)
    resp = client.get("/api/ai-hotel/captures", headers=_HDR)
    assert resp.status_code == 200
    caps = resp.json()["captures"]
    assert len(caps) == 2                             # raw feed intact
    assert all(c["form_record"] is None for c in caps)


@_skip_without_dashboard
def test_ac5_discarded_form_record_excluded(monkeypatch):
    store = _Store()
    store.captures = [_cap(50)]
    store.forms = [_form(3, 50, "site_visit", "discarded", {"overall_score": "1"})]
    client = _client(monkeypatch, store)
    c = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]
    assert c["form_record"] is None                  # discarded → not surfaced


@_skip_without_dashboard
def test_ac5_malformed_form_record_does_not_break_feed(monkeypatch):
    store = _Store()
    store.captures = [_cap(60, summary="capture stays")]
    bad = _form(4, 60, "site_visit", "confirmed")
    bad["corrected_json"] = "not-a-dict"             # both jsons malformed → values coerces to {}
    bad["extracted_json"] = "also-not-a-dict"
    bad["field_meta_json"] = 12345
    store.forms = [bad]
    client = _client(monkeypatch, store)
    resp = client.get("/api/ai-hotel/captures", headers=_HDR)
    assert resp.status_code == 200
    c = resp.json()["captures"][0]
    assert c["summary"] == "capture stays"           # feed intact
    assert c["form_record"]["values"] == {}          # malformed coerced, never raised


@_skip_without_dashboard
def test_dismissed_capture_still_hidden(monkeypatch):
    store = _Store()
    store.captures = [_cap(70, status="dismissed"), _cap(71, summary="visible")]
    client = _client(monkeypatch, store)
    caps = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"]
    assert [c["id"] for c in caps] == [71]
