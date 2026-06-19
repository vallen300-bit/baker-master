"""AI_HOTEL_VOICE_FORM_1 — voice dictation → structured form drafts.

Two forms on one substrate: site_visit (priority) + supplier_card (fast-follow).
Public interface: POST /api/ai-hotel/form-drafts (+ /confirm, /discard). Load-
bearing tests: AC2 (no hallucination) + AC3 (no data loss on extraction failure).
The LLM is mocked at the `_llm_call` seam only.

Source-level + schema-unit checks always run. TestClient runs skip cleanly when
outputs.dashboard cannot import (local Python 3.9 PEP-604 chain — clears on 3.10+).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─── Schema-unit checks (always run — no dashboard import) ──────────────────


def test_both_forms_registered():
    from orchestrator.ai_hotel_form_schemas import known_form_types, get_form_schema
    assert set(known_form_types()) == {"site_visit", "supplier_card"}
    assert get_form_schema("site_visit").title == "Site visit card"
    assert get_form_schema("supplier_card").title == "Supplier card"


def test_supplier_critical_is_company_name_only():
    from orchestrator.ai_hotel_form_schemas import get_form_schema
    crit = [f.key for f in get_form_schema("supplier_card").fields if f.critical]
    assert crit == ["company_name"]


def test_site_visit_has_16_fields_and_score():
    from orchestrator.ai_hotel_form_schemas import get_form_schema
    s = get_form_schema("site_visit")
    keys = [f.key for f in s.fields]
    assert len(keys) == 16
    assert "overall_score" in keys
    assert "unknowns_to_research" in keys
    score = next(f for f in s.fields if f.key == "overall_score")
    assert score.type == "score"


def test_unknown_form_type_returns_none():
    from orchestrator.ai_hotel_form_schemas import get_form_schema
    assert get_form_schema("invoice") is None
    assert get_form_schema("") is None
    assert get_form_schema(None) is None


def test_detect_form_type():
    from orchestrator.ai_hotel_form_schemas import detect_form_type
    ft, auto = detect_form_type("Standing outside a vacant building near the NVIDIA campus, good parking, zoning unclear.")
    assert ft == "site_visit" and auto is True
    ft2, _ = detect_form_type("Met a supplier at booth 14, got their business card and email, great product demo.")
    assert ft2 == "supplier_card"
    # default to the priority form when ambiguous
    ft3, _ = detect_form_type("just some words")
    assert ft3 == "site_visit"


def test_prompt_generated_from_schema():
    from orchestrator.ai_hotel_form_schemas import get_form_schema, build_extraction_prompt
    s = get_form_schema("site_visit")
    p = build_extraction_prompt(s, transcript="vacant lot near NVIDIA", note="")
    for f in s.fields:
        assert f.key in p
    assert "NEVER invent" in p
    assert "1-5" in p                       # overall_score spec
    assert "vacant lot near NVIDIA" in p


def test_site_visit_unknowns_backstop_always_lists_research_items():
    """AC2 control-plane: even if the model returns nothing for unknowns, the
    deterministic backstop surfaces owner/zoning/price/etc. so nothing
    unknowable is ever implied as known."""
    from orchestrator.ai_hotel_form_schemas import get_form_schema, parse_and_validate
    s = get_form_schema("site_visit")
    r = parse_and_validate(s, {"site_label": {"value": "Corner lot", "confidence": 0.9}})
    u = (r.values["unknowns_to_research"] or "").lower()
    assert "address" in u and "owner" in u and "zoning" in u and "price" in u
    assert r.values["address_or_location_clue"] is None   # never invented


def test_score_validation():
    from orchestrator.ai_hotel_form_schemas import get_form_schema, parse_and_validate
    s = get_form_schema("site_visit")
    assert parse_and_validate(s, {"overall_score": {"value": 4}}).values["overall_score"] == "4"
    bad = parse_and_validate(s, {"overall_score": {"value": 9}})
    assert any("overall_score" in e for e in bad.validation_errors)


def test_supplier_parse_normalizes_and_validates():
    from orchestrator.ai_hotel_form_schemas import get_form_schema, parse_and_validate
    s = get_form_schema("supplier_card")
    good = parse_and_validate(s, {
        "company_name": {"value": "NVIDIA", "confidence": 0.95},
        "email": {"value": "Jane@NVIDIA.com", "confidence": 0.9},
        "ai_hotel_category": {"value": "Infrastructure", "confidence": 0.7},
    })
    assert good.values["email"] == "jane@nvidia.com"
    assert good.values["ai_hotel_category"] == "infrastructure"
    assert good.missing_critical == []
    bad = parse_and_validate(s, {
        "company_name": {"value": None},
        "email": {"value": "nope", "confidence": 0.8},
        "phone": {"value": "12", "confidence": 0.8},
    })
    assert "company_name" in bad.missing_critical
    j = " ".join(bad.validation_errors)
    assert "email" in j and "phone" in j
    assert bad.field_meta["email"]["needs_review"] is True


def test_evidence_source_reflects_capture_source():
    from orchestrator.ai_hotel_form_schemas import get_form_schema, parse_and_validate
    s = get_form_schema("supplier_card")
    r = parse_and_validate(s, {"company_name": {"value": "NVIDIA", "confidence": 0.9}},
                           capture_source="audio")
    assert r.field_meta["company_name"]["evidence_source"] == "audio"
    low = parse_and_validate(s, {"company_name": {"value": "Maybe NVIDIA", "confidence": 0.2}},
                             capture_source="audio")
    assert low.field_meta["company_name"]["evidence_source"] == "inferred_low_confidence"


# ─── Source-level checks (always run) ───────────────────────────────────────


def test_routes_registered_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/ai-hotel/form-drafts"' in src
    assert '"/api/ai-hotel/form-drafts/{draft_id}/confirm"' in src
    assert '"/api/ai-hotel/form-drafts/{draft_id}/discard"' in src
    assert "async def ai_hotel_form_draft(" in src


def test_extraction_disables_thinking_and_uses_json():
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("async def ai_hotel_form_draft("):src.index("async def ai_hotel_form_draft_confirm(")]
    assert "thinking_budget=0" in seg
    assert 'response_format="json"' in seg


def test_migration_shape():
    mig = Path("migrations/20260619_ai_hotel_form_records.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ai_hotel_form_records" in mig
    assert "REFERENCES ai_hotel_captures(id) ON DELETE CASCADE" in mig
    assert "CHECK (status IN ('draft', 'confirmed', 'discarded'))" in mig
    assert "idx_ai_hotel_form_records_type_status_created" in mig
    up = mig.split("== migrate:down ==")[0]
    assert "DROP TABLE" not in up
    assert "-- DROP TABLE IF EXISTS ai_hotel_form_records" in mig


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


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.usage = _FakeUsage()


def _has_audio_part(messages):
    for m in (messages or []):
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "audio":
                    return True
    return False


def _extract_json(**fields):
    """key -> (value, confidence) → model extraction object."""
    return json.dumps({k: {"value": v, "confidence": c, "evidence": None} for k, (v, c) in fields.items()})


class _Cursor:
    def __init__(self, store):
        self.s = store
        self._result = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.rowcount = 0
        if "INSERT INTO ai_hotel_captures" in sql:
            source, note, b64, media, section, related, summary = params
            nid = self.s._next_cap
            self.s._next_cap += 1
            self.s.captures.append({"id": nid, "source": source, "note_text": note, "image_b64": b64,
                                    "image_media": media, "section_guess": section, "related_area": related,
                                    "summary": summary, "status": "new"})
            self._result = [(nid,)]
            self.rowcount = 1
        elif "INSERT INTO ai_hotel_capture_images" in sql:
            cap_id, ordinal, b64, media = params
            self.s.images.append({"capture_id": cap_id, "ordinal": ordinal, "image_b64": b64, "image_media": media})
            self.rowcount = 1
        elif "INSERT INTO ai_hotel_form_records" in sql:
            cap_id, ftype, ver, ej, fmj, vej, model, pv = params
            nid = self.s._next_form
            self.s._next_form += 1
            self.s.forms.append({"id": nid, "capture_id": cap_id, "form_type": ftype, "schema_version": ver,
                                 "status": "draft", "extracted_json": ej, "corrected_json": None,
                                 "field_meta_json": fmj, "validation_errors_json": vej, "model": model,
                                 "prompt_version": pv})
            self._result = [(nid,)]
            self.rowcount = 1
        elif "SELECT form_type, status FROM ai_hotel_form_records" in sql:
            fid = params[0]
            r = next((f for f in self.s.forms if f["id"] == fid), None)
            self._result = [(r["form_type"], r["status"])] if r else []
        elif "UPDATE ai_hotel_form_records" in sql and "status = 'confirmed'" in sql:
            corrected_json, fid = params
            r = next((f for f in self.s.forms if f["id"] == fid and f["status"] == "draft"), None)
            if r:
                r["status"] = "confirmed"
                r["corrected_json"] = corrected_json
                self.rowcount = 1
        elif "UPDATE ai_hotel_form_records" in sql and "status = 'discarded'" in sql:
            fid = params[0]
            r = next((f for f in self.s.forms if f["id"] == fid and f["status"] == "draft"), None)
            if r:
                r["status"] = "discarded"
                self.rowcount = 1
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def close(self):
        pass


class _Conn:
    def __init__(self, store):
        self.s = store

    def cursor(self, cursor_factory=None):
        return _Cursor(self.s)

    def commit(self):
        pass

    def rollback(self):
        pass


class _Store:
    def __init__(self):
        self.captures = []
        self.images = []
        self.forms = []
        self._next_cap = 1
        self._next_form = 1

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, llm=None):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    import orchestrator.cost_monitor as cm

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    store = _Store()
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    monkeypatch.setattr(cm, "log_api_cost", lambda *a, **k: None)
    if llm is not None:
        monkeypatch.setattr(dash, "_llm_call", llm)
    return TestClient(dash.app), store


def _llm_returning(extract_text, transcript_text="A dictated transcript."):
    def _f(model, messages=None, **k):
        if _has_audio_part(messages):
            return _FakeResp(transcript_text)
        return _FakeResp(extract_text)
    return _f


_HDR = {"X-Baker-Key": "test-key"}


# ─── AC1: messy dictation → valid site_visit draft ──────────────────────────


@_skip_without_dashboard
def test_ac1_messy_dictation_to_site_visit_draft(monkeypatch):
    # fields arrive out of natural order; the schema still maps them.
    extract = _extract_json(
        overall_score=(4, 0.7),
        geo_context=("Two blocks from the NVIDIA campus in Santa Clara", 0.9),
        current_property_type=("office", 0.8),
        hospitality_fit=("high", 0.6),
        ai_hotel_angle=("Tech-corridor demand, could suit an AI-themed hotel", 0.7),
    )
    client, store = _client(monkeypatch, llm=_llm_returning(extract))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR, data={
        "form_type": "site_visit",
        "note": "Okay so I'm looking at this office building, near NVIDIA, score it a 4 I'd say.",
    })
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["form_type"] == "site_visit"
    assert b["status"] == "draft"
    assert b["values"]["overall_score"] == "4"
    assert b["values"]["current_property_type"] == "office"
    assert "NVIDIA" in b["values"]["geo_context"]
    assert b["draft_id"] is not None
    assert len(store.captures) == 1 and len(store.forms) == 1


# ─── AC2: unknowns stay null AND surface in unknowns_to_research ─────────────


@_skip_without_dashboard
def test_ac2_no_hallucinated_address_owner_zoning(monkeypatch):
    # The model returns nothing for address/owner/zoning — they MUST stay null
    # and the research list MUST name them.
    extract = _extract_json(geo_context=("Near the airport", 0.8), overall_score=(3, 0.6))
    client, store = _client(monkeypatch, llm=_llm_returning(extract))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR, data={
        "form_type": "site_visit",
        "note": "Some lot near the airport, not sure who owns it or the zoning.",
    })
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["values"]["address_or_location_clue"] is None
    u = (b["values"]["unknowns_to_research"] or "").lower()
    assert "address" in u and "owner" in u and "zoning" in u and "price" in u


# ─── AC3: extraction failure still saves the raw capture ────────────────────


@_skip_without_dashboard
def test_ac3_raw_capture_survives_extraction_exception(monkeypatch):
    import outputs.dashboard as dash

    def _boom(model, messages=None, **k):
        raise RuntimeError("gemini exploded")

    client, store = _client(monkeypatch)
    monkeypatch.setattr(dash, "_llm_call", _boom)
    from io import BytesIO
    from PIL import Image as PILImage
    buf = BytesIO()
    PILImage.effect_noise((64, 64), 100).convert("RGB").save(buf, format="JPEG", quality=90)
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit", "note": "Vacant building, corner lot."},
                       files={"images": ("site.jpg", buf.getvalue(), "image/jpeg")})
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert len(store.captures) == 1
    assert store.captures[0]["note_text"] and "Vacant building" in store.captures[0]["note_text"]
    assert len(store.images) == 1                       # photo retrievable
    assert b["draft_id"] is not None
    assert any("Extraction failed" in w for w in b["warnings"])


# ─── AC4: no confirmed record before review ─────────────────────────────────


@_skip_without_dashboard
def test_ac4_draft_post_never_writes_confirmed(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(overall_score=(3, 0.6))))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit", "note": "A site."})
    assert resp.status_code == 200, resp.text
    assert all(f["status"] == "draft" for f in store.forms)
    assert not any(f["status"] == "confirmed" for f in store.forms)


# ─── AC5: auto-detect picks site_visit ──────────────────────────────────────


@_skip_without_dashboard
def test_ac5_autodetect_site_visit(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(overall_score=(4, 0.7))))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR, data={
        # NO form_type — must auto-detect from the site/NVIDIA/parking language.
        "note": "Standing by a building near NVIDIA in Santa Clara, decent parking, checking the location.",
    })
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["form_type"] == "site_visit"
    assert b["auto_detected"] is True


# ─── AC6: explicit form_type overrides auto-detect ──────────────────────────


@_skip_without_dashboard
def test_ac6_explicit_form_type_overrides_autodetect(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(company_name=("Acme", 0.9))))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR, data={
        # Site-ish words, but the user explicitly chose supplier_card.
        "form_type": "supplier_card",
        "note": "Near the NVIDIA building, talked to Acme about parking sensors.",
    })
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["form_type"] == "supplier_card"
    assert b["auto_detected"] is False


# ─── AC7: unknown form_type → 400, no rows ──────────────────────────────────


@_skip_without_dashboard
def test_ac7_unknown_form_type_400_no_rows(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json()))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "teleporter", "note": "whatever"})
    assert resp.status_code == 400, resp.text
    assert store.captures == [] and store.forms == []


# ─── AC8: supplier happy path + validators reject bad email/phone ───────────


@_skip_without_dashboard
def test_ac8_supplier_happy_path_and_bad_contact_rejected(monkeypatch):
    extract = _extract_json(
        company_name=("NVIDIA", 0.97),
        contact_name=("Jane Doe", 0.9),
        email=("not-an-email", 0.8),
        phone=("12", 0.8),
    )
    client, store = _client(monkeypatch, llm=_llm_returning(extract))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR, data={
        "form_type": "supplier_card",
        "note": "Spoke to Jane Doe at NVIDIA.",
    })
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["values"]["company_name"] == "NVIDIA"
    errs = " ".join(b["validation_errors"])
    assert "email" in errs and "phone" in errs
    assert b["values"]["email"] == "not-an-email"      # surfaced, not dropped
    assert b["field_meta"]["email"]["needs_review"] is True


@_skip_without_dashboard
def test_audio_transcribed_then_extracted_site_visit(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(
        _extract_json(overall_score=(4, 0.8)), transcript_text="Big vacant lot near the NVIDIA campus."))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit"},
                       files={"audio": ("d.webm", b"\x1aE\xdf\xa3fakebytes", "audio/webm")})
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert "NVIDIA" in b["transcript_preview"]
    assert store.captures[0]["source"] == "audio"
    assert b["field_meta"]["overall_score"]["evidence_source"] == "audio"


# ─── AC6 variant: empty/non-JSON model output → no data loss ────────────────


@_skip_without_dashboard
def test_empty_model_json_no_data_loss(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(""))
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit", "note": "Some site."})
    assert resp.status_code == 200, resp.text
    assert len(store.captures) == 1
    assert any("Extraction failed" in w for w in resp.json()["warnings"])


# ─── Confirm / discard lifecycle ────────────────────────────────────────────


@_skip_without_dashboard
def test_confirm_promotes_supplier_draft(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(company_name=("NVIDIA", 0.95))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "supplier_card", "note": "NVIDIA booth."}).json()["draft_id"]
    resp = client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR,
                       json={"values": {"company_name": "NVIDIA", "email": "jane@nvidia.com"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"
    assert store.forms[0]["status"] == "confirmed"


@_skip_without_dashboard
def test_confirm_rejects_missing_critical(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(company_name=(None, 0.0))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "supplier_card", "note": "unclear"}).json()["draft_id"]
    resp = client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR,
                       json={"values": {"company_name": ""}})
    assert resp.status_code == 422, resp.text
    assert store.forms[0]["status"] == "draft"


@_skip_without_dashboard
def test_confirm_site_visit_no_critical_succeeds_minimal(monkeypatch):
    """site_visit has no critical field — a confirm with a score saves."""
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(overall_score=(3, 0.6))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "site_visit", "note": "A site."}).json()["draft_id"]
    resp = client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR,
                       json={"values": {"overall_score": "3", "site_label": "Corner lot"}})
    assert resp.status_code == 200, resp.text
    assert store.forms[0]["status"] == "confirmed"


@_skip_without_dashboard
def test_confirm_rejects_bad_score(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(overall_score=(3, 0.6))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "site_visit", "note": "A site."}).json()["draft_id"]
    resp = client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR,
                       json={"values": {"overall_score": "99"}})
    assert resp.status_code == 422, resp.text


@_skip_without_dashboard
def test_discard_keeps_raw(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(overall_score=(3, 0.6))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "site_visit", "note": "A site."}).json()["draft_id"]
    resp = client.post(f"/api/ai-hotel/form-drafts/{draft_id}/discard", headers=_HDR)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "discarded"
    assert store.forms[0]["status"] == "discarded"
    assert len(store.captures) == 1


@_skip_without_dashboard
def test_double_confirm_conflicts(monkeypatch):
    client, store = _client(monkeypatch, llm=_llm_returning(_extract_json(company_name=("NVIDIA", 0.95))))
    draft_id = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                           data={"form_type": "supplier_card", "note": "NVIDIA."}).json()["draft_id"]
    body = {"values": {"company_name": "NVIDIA"}}
    assert client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR, json=body).status_code == 200
    assert client.post(f"/api/ai-hotel/form-drafts/{draft_id}/confirm", headers=_HDR, json=body).status_code == 409


@_skip_without_dashboard
def test_401_without_auth(monkeypatch):
    client, _ = _client(monkeypatch, llm=_llm_returning(_extract_json()))
    resp = client.post("/api/ai-hotel/form-drafts", data={"form_type": "site_visit", "note": "x"})
    assert resp.status_code == 401
