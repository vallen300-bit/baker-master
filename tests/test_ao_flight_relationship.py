"""AO_FLIGHT_RELATIONSHIP_1 — comms-gap machine element (Fix 1), optional
relationship card (Fix 2), and cockpit AO-tab discard / 410 signpost (Fix 3).

Doctrine (CRD_1/CRD_2): honesty + subtraction. The comms-gap element must NEVER
default green on a query miss (the exact lie this brief kills); the optional
sections must be invisible to flights that don't opt in (BB-AUK-001 regression).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import orchestrator.flight_dashboard as fd


_TICKETS_OK = {"available": True, "checked_in": 0, "urgent": 0,
               "awaiting": 0, "rejected": 0, "total": 0}


# ───────────────────────── Fix 1: comms-gap element ─────────────────────────

def test_gap_tone_thresholds():
    # green <=10, amber 11-14, red >14; None -> neutral 'none' (never green).
    assert fd._gap_tone(None) == "none"
    assert fd._gap_tone(0) == "green"
    assert fd._gap_tone(10) == "green"
    assert fd._gap_tone(11) == "amber"
    assert fd._gap_tone(14) == "amber"
    assert fd._gap_tone(15) == "red"
    assert fd._gap_tone(40) == "red"


def test_contact_line_absent_when_not_configured():
    # No last_contact in data (flight without comms_contact) -> no line at all.
    assert fd._contact_line_html({}) == ""


def test_contact_line_none_is_no_data_never_green():
    html = fd._contact_line_html({"last_contact": {"days": None, "tone": "none", "label": "AO"}})
    assert "no data (wiring check needed)" in html
    assert "var(--green)" not in html  # the whole point: never fake-green


def test_contact_line_present_shows_days_channel_date():
    html = fd._contact_line_html({"last_contact": {
        "days": 3, "tone": "green", "channel": "WhatsApp", "date": "2026-07-06", "label": "AO"}})
    assert "LAST DIRECT AO CONTACT — 3 days" in html
    assert "WhatsApp" in html and "2026-07-06" in html
    assert "var(--green)" in html


def test_contact_line_red_tone_over_14():
    html = fd._contact_line_html({"last_contact": {
        "days": 20, "tone": "red", "channel": "email", "date": "2026-06-19", "label": "AO"}})
    assert "var(--red)" in html and "20 days" in html


def test_contact_line_escapes_desk_values():
    html = fd._contact_line_html({"last_contact": {
        "days": 3, "tone": "green", "channel": "<img>", "date": "d", "label": "<b>"}})
    assert "<img>" not in html and "<b>" not in html


def test_last_direct_contact_failure_returns_none(monkeypatch):
    # Fail-loud: any DB failure -> None -> caller renders 'no data', never green.
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(fd, "get_conn", _boom)
    assert fd.last_direct_contact({"wa_chat_id": "491736903746@c.us"}) is None


def test_build_ao_no_data_renders_honest_never_green(monkeypatch):
    monkeypatch.setattr(fd, "last_direct_contact", lambda c: None)
    monkeypatch.setattr(fd, "count_flight_tickets", lambda *a, **k: dict(_TICKETS_OK))
    data = fd.build_flight_dashboard("AO-OSK-001")
    assert data is not None
    assert data["last_contact"]["days"] is None
    html = fd.render_dashboard_html(data)
    assert "no data (wiring check needed)" in html


def test_build_ao_present_contact_computes_gap(monkeypatch):
    fixed = datetime(2026, 7, 6, tzinfo=timezone.utc)
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(fd, "last_direct_contact", lambda c: {"at": fixed, "channel": "WhatsApp"})
    monkeypatch.setattr(fd, "count_flight_tickets", lambda *a, **k: dict(_TICKETS_OK))
    data = fd.build_flight_dashboard("AO-OSK-001", now=now)
    assert data["last_contact"]["days"] == 3
    assert data["last_contact"]["channel"] == "WhatsApp"
    assert data["last_contact"]["tone"] == "green"
    assert data["last_contact"]["date"] == "2026-07-06"


def test_ao_snapshot_has_comms_contact_config():
    snap = fd.load_snapshot("AO-OSK-001")
    assert snap is not None
    cc = snap.get("comms_contact")
    assert cc and cc.get("wa_chat_id") == "491736903746@c.us"
    assert "%oskolkov%" in cc.get("email_patterns", [])


# ───────────────────────── Fix 2: relationship card ─────────────────────────

def test_relationship_absent_omits_card():
    assert fd._relationship_html({"relationship": {}}) == ""
    assert fd._relationship_html({}) == ""


def test_relationship_empty_lists_omits_card():
    assert fd._relationship_html({"relationship": {"read": [], "red_flags": [], "orbit": []}}) == ""


def test_relationship_present_renders_and_escapes():
    data = {
        "relationship": {
            "updated_at": "2026-07-09",
            "read": [{"point": "<script>x", "receipt": "src · 2026-07-08"}],
            "red_flags": [{"flag": "capital-call slip risk", "receipt": "pm_state"}],
            "orbit": [{"name": "Constantinos", "role": "gatekeeper", "note": "written-intent channel"}],
        },
        "stale": {},
    }
    html = fd._relationship_html(data)
    assert "RELATIONSHIP — COUNTERPARTY READ" in html
    assert "<script>" not in html  # escaped
    assert "Constantinos" in html and "gatekeeper" in html
    assert "capital-call slip risk" in html


# ─────────────── Fix 1+2 regression: BB-AUK-001 opts into neither ───────────

def test_bb_auk_001_optional_sections_invisible(monkeypatch):
    monkeypatch.setattr(fd, "count_flight_tickets", lambda *a, **k: dict(_TICKETS_OK))
    data = fd.build_flight_dashboard("BB-AUK-001")
    assert data is not None
    assert "last_contact" not in data          # no comms_contact -> no gap line
    assert data.get("relationship") == {}      # no relationship key
    html = fd.render_dashboard_html(data)
    assert "LAST DIRECT" not in html
    assert "RELATIONSHIP — COUNTERPARTY READ" not in html


# ───────────────────────── Fix 3: cockpit AO discard ────────────────────────

def test_ao_endpoint_returns_410_signpost():
    import outputs.dashboard as dash
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dash.get_ao_dashboard())
    assert ei.value.status_code == 410
    assert "AO-OSK-001" in str(ei.value.detail)


def test_ao_nav_removed_viewao_retained():
    src = open("outputs/static/index.html").read()
    assert 'data-tab="ao-dashboard"' not in src   # nav discarded
    assert 'id="aoDot"' not in src
    assert 'id="viewAO"' in src                    # deep-link view retained (CRD doctrine)
    assert "AO_FLIGHT_RELATIONSHIP_1" in src       # tombstone present
