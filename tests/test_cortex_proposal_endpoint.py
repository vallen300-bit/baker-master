"""Tests for GET /api/cortex/cycles/{cycle_id}/proposal — CORTEX_RUN_SCAN_UI_RENDER_1.

Read-only endpoint that surfaces the propose-phase synthesis text the Scan
UI renders inside its terminal card. Mirrors the auth + monkeypatch pattern
in tests/test_cortex_run_endpoint.py.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


def _set_api_key(monkeypatch, key="test-key-proposal"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = key
    from outputs.dashboard import verify_api_key
    dash.app.dependency_overrides.pop(verify_api_key, None)


class _StubCursor:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0

    def execute(self, sql, params=None):
        self._last_sql = sql

    def fetchone(self):
        if self._idx >= len(self._results):
            return None
        r = self._results[self._idx]
        self._idx += 1
        return r

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
    return {"X-Baker-Key": "test-key-proposal"}


def test_proposal_returns_200_with_synthesis(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    cycle_row = {
        "cycle_id": cyc_id,
        "matter_slug": "hagenauer-rg7",
        "triggered_by": "scan_intent",
        "status": "tier_b_pending",
        "current_phase": "propose",
        "cost_dollars": 1.46,
        "cost_tokens": 4922,
        "started_at": None,
        "completed_at": None,
        "aborted_reason": None,
    }
    syn_row = {
        "payload": {"proposal_text": "# State of Play\n\nTest proposal."},
        "created_at": None,
    }
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([cycle_row, syn_row]))

    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_proposal"] is True
    assert body["proposal_text"].startswith("# State of Play")
    assert body["matter_slug"] == "hagenauer-rg7"
    assert body["status"] == "tier_b_pending"
    assert body["cost_dollars"] == pytest.approx(1.46)
    assert body["cost_tokens"] == 4922


def test_proposal_returns_404_when_cycle_missing(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([None]))
    cyc_id = str(uuid.uuid4())
    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_hdr())
    assert resp.status_code == 404, resp.text


def test_proposal_returns_400_for_invalid_uuid(monkeypatch):
    _set_api_key(monkeypatch)
    resp = _client().get("/api/cortex/cycles/not-a-uuid/proposal", headers=_hdr())
    assert resp.status_code == 400, resp.text


def test_proposal_returns_has_proposal_false_when_no_synthesis(monkeypatch):
    _set_api_key(monkeypatch)
    cyc_id = str(uuid.uuid4())
    cycle_row = {
        "cycle_id": cyc_id,
        "matter_slug": "movie",
        "triggered_by": "signal",
        "status": "running",
        "current_phase": "load",
        "cost_dollars": 0.0,
        "cost_tokens": 0,
        "started_at": None,
        "completed_at": None,
        "aborted_reason": None,
    }
    from outputs import dashboard
    monkeypatch.setattr(dashboard, "_get_store", lambda: _StubStore([cycle_row, None]))
    resp = _client().get(f"/api/cortex/cycles/{cyc_id}/proposal", headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_proposal"] is False
    assert body["proposal_text"] is None
    assert body["current_phase"] == "load"
