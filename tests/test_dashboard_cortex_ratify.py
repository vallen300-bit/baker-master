"""Tests for DASHBOARD_CORTEX_RATIFY_PANEL_1 — new web ratify panel.

Covers the two new read-only endpoints:
  - GET /api/cortex/cycles/pending
  - GET /api/cortex/cycles/{cycle_id}/trace

Plus a regression-style guard that POST /cortex/cycle/{id}/action keeps
accepting the four canonical actions (approve / edit / refresh / reject),
since the new Pending tab calls this existing endpoint.

Mirrors the stub/monkeypatch pattern in test_cortex_proposal_endpoint.py
so the suite stays DB-free.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ─── Test infrastructure (mirrors test_cortex_proposal_endpoint.py) ───


def _set_api_key(monkeypatch, key="test-key-ratify"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = key
    from outputs.dashboard import verify_api_key
    dash.app.dependency_overrides.pop(verify_api_key, None)


class _StubCursor:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0
        self._last_sql = ""

    def execute(self, sql, params=None):
        self._last_sql = sql

    def fetchone(self):
        if self._idx >= len(self._results):
            return None
        r = self._results[self._idx]
        self._idx += 1
        # If the stored result is a list (multi-row), do not auto-advance — caller used fetchall.
        return r

    def fetchall(self):
        if self._idx >= len(self._results):
            return []
        r = self._results[self._idx]
        self._idx += 1
        if r is None:
            return []
        if isinstance(r, list):
            return r
        return [r]

    def close(self):
        pass


class _StubConn:
    def __init__(self, cursor_results):
        self._cursor_results = cursor_results

    def cursor(self, cursor_factory=None):
        return _StubCursor(self._cursor_results)

    def commit(self):
        pass

    def rollback(self):
        pass


class _StubStore:
    def __init__(self, cursor_results):
        self._cr = cursor_results

    def _get_conn(self):
        return _StubConn(self._cr)

    def _put_conn(self, conn):
        pass


def _client():
    from outputs.dashboard import app
    return TestClient(app)


def _hdr():
    return {"X-Baker-Key": "test-key-ratify"}


# ─── Source-level guards (run in any Python — no import required) ───


def test_pending_route_is_registered_in_dashboard_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/cortex/cycles/pending"' in src
    assert 'async def list_cortex_cycles_pending' in src
    assert 'tags=["cortex"]' in src
    assert 'dependencies=[Depends(verify_api_key)]' in src
    assert "status = 'tier_b_pending'" in src


def test_trace_route_is_registered_in_dashboard_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/cortex/cycles/{cycle_id}/trace"' in src
    assert 'async def get_cortex_cycle_trace' in src
    assert 'FROM cortex_phase_outputs' in src
    assert "Invalid cycle_id" in src


def test_pending_tab_button_in_static_index_html():
    src = Path("outputs/static/index.html").read_text()
    assert 'id="cortexTabPending"' in src
    assert "_cortexTab('pending')" in src
    # Cache-bust bumped (CORTEX_DIRECTOR_CARD_V1_1)
    assert "app.js?v=118" in src
    assert "style.css?v=77" in src


def test_cortex_ratify_js_helpers_exist():
    src = Path("outputs/static/app.js").read_text()
    for fn in (
        "_renderCortexPending",
        "_cortexPendingToggle",
        "_cortexPendingExpansionHtml",
        "_cortexPendingTier2Html",
        "_cortexPhaseTraceHtml",
        "_cortexSpecialistBreakdownHtml",
        "_cortexCitationsHtml",
        "_cortexPendingAction",
        "_cortexPendingEdit",
        "_cortexPendingReject",
        # CORTEX_DIRECTOR_CARD_V1 — plain-English card renderer
        "_cortexDirectorCardHtml",
    ):
        assert fn in src, f"missing JS helper: {fn}"
    # Pending tab polls /pending
    assert "/api/cortex/cycles/pending" in src
    # Toggle wires both proposal + trace endpoints
    assert "/proposal" in src and "/trace" in src


# ─── /api/cortex/cycles/pending — TestClient happy + auth + empty ───


def _pending_row(cyc_id, proposal_text=None, director_card=None,
                 triggered_by="scan_intent", is_smoke=False):
    return {
        "cycle_id": cyc_id,
        "matter_slug": "hagenauer-rg7",
        "triggered_by": triggered_by,
        "current_phase": "propose",
        "cost_dollars": 1.23,
        "cost_tokens": 4567,
        "started_at": None,
        "age_minutes": 12.5,
        "proposal_text": proposal_text,
        "director_card": director_card,
        "is_smoke": is_smoke,
    }


def _sample_director_card():
    """9-field card payload matching the schema from CORTEX_DIRECTOR_CARD_V1."""
    return {
        "matter": "Hagenauer RG7",
        "situation": "The administrator missed a filing deadline.",
        "action": "Send a follow-up letter giving 7 days.",
        "rationale": "We need to preserve our position. A polite letter costs nothing.",
        "downside": "Admin could push back on tone.",
        "no_action_consequence": "Deadline expires uncontested.",
        "cost": {"ai_money_eur": 0.0034, "real_world_money_eur": None, "action_sends_money": False},
        "recommendation": "approve",
        "confidence": "medium",
    }


def test_pending_returns_200_with_cycles(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    rows = [_pending_row(cyc_id, proposal_text="x" * 250)]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([rows]))

    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    c = body["cycles"][0]
    assert c["cycle_id"] == cyc_id
    assert c["matter_slug"] == "hagenauer-rg7"
    assert c["has_proposal"] is True
    # Preview truncated to 200
    assert len(c["proposal_preview"]) == 200


def test_pending_returns_empty_when_no_cycles(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([[]]))
    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200
    body = resp.json()
    assert body["cycles"] == []
    assert body["count"] == 0


def test_pending_rejects_missing_api_key(monkeypatch):
    _set_api_key(monkeypatch)
    resp = _client().get("/api/cortex/cycles/pending")   # no header
    # verify_api_key returns 401 on missing/invalid key (outputs/dashboard.py:113)
    assert resp.status_code == 401


def test_pending_marks_has_proposal_false_when_no_synthesis(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    rows = [_pending_row(cyc_id, proposal_text=None)]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([rows]))

    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200
    c = resp.json()["cycles"][0]
    assert c["has_proposal"] is False
    assert c["proposal_preview"] == ""


# ─── Director Card (Phase 4.5) — CORTEX_DIRECTOR_CARD_V1 ───


def test_pending_returns_director_card_when_present(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    card = _sample_director_card()
    rows = [_pending_row(cyc_id, proposal_text="**Proposed:** Send letter.", director_card=card)]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([rows]))

    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200, resp.text
    c = resp.json()["cycles"][0]
    assert c["has_director_card"] is True
    assert isinstance(c["director_card"], dict)
    assert c["director_card"]["matter"] == "Hagenauer RG7"
    assert c["director_card"]["recommendation"] == "approve"
    assert c["director_card"]["confidence"] == "medium"


def test_pending_director_card_null_when_absent(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    rows = [_pending_row(cyc_id, proposal_text="x", director_card=None)]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([rows]))

    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200
    c = resp.json()["cycles"][0]
    assert c["has_director_card"] is False
    assert c["director_card"] is None


# ─── CORTEX_DIRECTOR_CARD_V1_1 — smoke-cycle filter ───
#
# Stub note: _StubCursor doesn't evaluate the CTE WHERE clause, so the test
# pre-filters the rows passed to the stub to match what the SQL would return.
# Each test asserts (a) the request was accepted with the right query param,
# (b) the response shape includes is_smoke + smoke_hidden_count + include_smoke.


def test_pending_filters_smoke_by_default(monkeypatch):
    """Default GET — smoke cycles excluded; real cycles returned with
    is_smoke=False and smoke_hidden_count > 0 surfaced."""
    _set_api_key(monkeypatch)
    real_id = str(uuid.uuid4())
    real_rows = [_pending_row(real_id, proposal_text="legitimate ask",
                              triggered_by="scan_intent", is_smoke=False)]
    hidden_row = {"hidden": 2}
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store",
                        lambda: _StubStore([real_rows, hidden_row]))

    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["smoke_hidden_count"] == 2
    assert body["include_smoke"] is False
    c = body["cycles"][0]
    assert c["cycle_id"] == real_id
    assert c["is_smoke"] is False


def test_pending_include_smoke_true_returns_all(monkeypatch):
    """include_smoke=true returns the full set; smoke_hidden_count=0 since
    nothing is hidden in that mode; at least one row carries is_smoke=True."""
    _set_api_key(monkeypatch)
    rows = [
        _pending_row(str(uuid.uuid4()), proposal_text="real ask",
                     triggered_by="scan_intent", is_smoke=False),
        _pending_row(str(uuid.uuid4()), proposal_text="Smoke #3 health check",
                     triggered_by="self_wake_smoke", is_smoke=True),
        _pending_row(str(uuid.uuid4()), proposal_text="another real",
                     triggered_by="director_manual", is_smoke=False),
    ]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([rows]))

    resp = _client().get(
        "/api/cortex/cycles/pending?include_smoke=true", headers=_hdr(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 3
    assert body["smoke_hidden_count"] == 0
    assert body["include_smoke"] is True
    smoke_flags = [c["is_smoke"] for c in body["cycles"]]
    assert True in smoke_flags
    assert False in smoke_flags


def test_pending_signal_text_smoke_marker_via_proposal_text(monkeypatch):
    """A cycle triggered manually but whose synthesis proposal_text opens
    with 'Smoke #' MUST be flagged is_smoke=True and hidden by default
    (signal_text was the original brief framing but signal_text is not a
    column on cortex_cycles — proposal_text is the actual carrier)."""
    _set_api_key(monkeypatch)
    smoke_id = str(uuid.uuid4())
    smoke_row = _pending_row(
        smoke_id,
        proposal_text="Smoke #4 health check — generated by self-wake.",
        triggered_by="director_manual",
        is_smoke=True,
    )
    # Default GET hides it: stub returns empty visible rows + hidden=1.
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store",
                        lambda: _StubStore([[], {"hidden": 1}]))
    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 0
    assert body["smoke_hidden_count"] == 1

    # include_smoke=true: the smoke row surfaces and carries is_smoke=True.
    monkeypatch.setattr(dashboard, "_get_store",
                        lambda: _StubStore([[smoke_row]]))
    resp = _client().get(
        "/api/cortex/cycles/pending?include_smoke=true", headers=_hdr(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["cycles"][0]["is_smoke"] is True


def test_pending_heartbeat_triggered_by_is_smoke(monkeypatch):
    """A cycle with triggered_by='heartbeat' is smoke; hidden by default,
    surfaced with is_smoke=True under include_smoke=true."""
    _set_api_key(monkeypatch)
    hb_id = str(uuid.uuid4())
    hb_row = _pending_row(
        hb_id,
        proposal_text="anything",
        triggered_by="heartbeat",
        is_smoke=True,
    )
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store",
                        lambda: _StubStore([[], {"hidden": 1}]))
    resp = _client().get("/api/cortex/cycles/pending", headers=_hdr())
    assert resp.json()["smoke_hidden_count"] == 1
    assert resp.json()["count"] == 0

    monkeypatch.setattr(dashboard, "_get_store",
                        lambda: _StubStore([[hb_row]]))
    resp = _client().get(
        "/api/cortex/cycles/pending?include_smoke=true", headers=_hdr(),
    )
    body = resp.json()
    assert body["count"] == 1
    assert body["cycles"][0]["is_smoke"] is True


def test_pending_route_source_contains_smoke_detection_clauses():
    """Source-level guard: the SQL CTE in the dashboard must reference
    triggered_by ILIKE patterns + LEFT(proposal_text, 200) ILIKE pattern
    so smoke detection survives any future re-edit of the route."""
    src = Path("outputs/dashboard.py").read_text()
    assert "include_smoke" in src
    assert "is_smoke" in src
    assert "smoke_hidden_count" in src
    # triggered_by ILIKE branch present
    assert "ILIKE '%%smoke%%'" in src or "ILIKE '%smoke%'" in src
    # proposal_text LEFT(...) branch present
    assert "LEFT(COALESCE(b.proposal_text" in src or "LEFT(COALESCE(syn.proposal_text" in src


# ─── /api/cortex/cycles/{cycle_id}/trace — happy + 400 + 404 ───


def test_trace_returns_200_with_phase_outputs(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    cycle_row = {
        "cycle_id": cyc_id,
        "matter_slug": "movie",
        "status": "tier_b_pending",
        "current_phase": "propose",
        "cost_dollars": 0.81,
        "cost_tokens": 1234,
        "started_at": None,
        "completed_at": None,
    }
    phase_rows = [
        {"phase": "sense",   "phase_order": 1, "artifact_type": "cycle_init",     "payload": {"k": "v"}, "created_at": None},
        {"phase": "load",    "phase_order": 2, "artifact_type": "phase2_context", "payload": {"k": "v"}, "created_at": None},
        {"phase": "reason",  "phase_order": 3, "artifact_type": "phase3_reason",  "payload": {"specialists": [{"name": "legal", "cost_dollars": 0.05}]}, "created_at": None},
        {"phase": "propose", "phase_order": 4, "artifact_type": "synthesis",      "payload": {"proposal_text": "go"}, "created_at": None},
    ]
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([cycle_row, phase_rows]))

    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/trace", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cycle_id"] == cyc_id
    assert body["count"] == 4
    phases = [o["phase"] for o in body["phase_outputs"]]
    assert phases == ["sense", "load", "reason", "propose"]


def test_trace_returns_400_on_bad_cycle_id(monkeypatch):
    _set_api_key(monkeypatch)
    resp = _client().get("/api/cortex/cycles/not-a-uuid/trace", headers=_hdr())
    assert resp.status_code == 400


def test_trace_returns_404_when_cycle_missing(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([None]))
    cyc_id = str(uuid.uuid4())
    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/trace", headers=_hdr())
    assert resp.status_code == 404


def test_trace_requires_api_key(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/trace")   # no header
    # verify_api_key returns 401 on missing/invalid key (outputs/dashboard.py:113)
    assert resp.status_code == 401


# ─── Regression guard — /cortex/cycle/{id}/action still accepts all 4 ───


def test_action_endpoint_dispatches_each_canonical_action(monkeypatch):
    _set_api_key(monkeypatch)
    captured = []

    async def make_stub(name):
        async def stub(*, cycle_id, body):
            captured.append((name, cycle_id, body.get("action")))
            return {"ok": True, "stub": name}
        return stub

    from orchestrator import cortex_phase5_act as p5
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        for name in ("cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"):
            monkeypatch.setattr(p5, name, loop.run_until_complete(make_stub(name)))
    finally:
        loop.close()

    cyc_id = "cyc-ratify-1"
    for action in ("approve", "edit", "refresh", "reject"):
        resp = _client().post(
            f"/cortex/cycle/{cyc_id}/action",
            json={"action": action, "edits": "e", "reason": "r", "selected_gold_files": []},
            headers=_hdr(),
        )
        assert resp.status_code == 200, resp.text
    expected_names = {"cortex_approve", "cortex_edit", "cortex_refresh", "cortex_reject"}
    assert {c[0] for c in captured} == expected_names
