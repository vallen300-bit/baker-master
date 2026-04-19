"""Tests for KBL Pipeline dashboard endpoints.

Four read-only endpoints feed the Cockpit's KBL Pipeline tab:

    GET /api/kbl/signals         — recent signals (state tracker)
    GET /api/kbl/cost-rollup     — 24h cost grouped by step+model
    GET /api/kbl/silver-landed   — completed signals (vault commits)
    GET /api/kbl/mac-mini-status — latest heartbeat + age

Tests assert response shape (not exact counts) and empty-state rendering.
``kbl.db.get_conn`` is patched to yield a fake psycopg2 connection whose
cursor returns fixture rows, so no real DB is needed.

Auth is bypassed via ``app.dependency_overrides[verify_api_key]`` — the
X-Baker-Key flow itself is covered elsewhere (verify_api_key is module-
level and identical across routes).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fake DB plumbing
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal psycopg2-style cursor. Each query consumes the next queued
    result (description + rows). Enough for the KBL endpoints which each
    issue ≤2 queries in sequence.
    """

    def __init__(self, queued):
        self._queued = list(queued)
        self.description = []
        self._rows = []

    def execute(self, sql, params=None):
        if not self._queued:
            raise AssertionError(f"Unexpected query: {sql[:60]}...")
        cols, rows = self._queued.pop(0)
        self.description = [MagicMock(name=c) for c in cols]
        # psycopg2's Column objects expose a .name attribute — mirror that.
        for col_obj, col_name in zip(self.description, cols):
            col_obj.name = col_name
        self._rows = list(rows)

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, queued):
        self._cursor = _FakeCursor(queued)

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _fake_get_conn(queued):
    @contextmanager
    def _ctx():
        yield _FakeConn(queued)

    return _ctx


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "50.0")

    from outputs.dashboard import app, verify_api_key

    app.dependency_overrides[verify_api_key] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


def _patch_conn(queued):
    return patch("kbl.db.get_conn", _fake_get_conn(queued))


# ---------------------------------------------------------------------------
# /api/kbl/signals
# ---------------------------------------------------------------------------


def test_kbl_signals_happy_path(client):
    cols = ["id", "source", "primary_matter", "status", "vedana", "triage_score", "created_at"]
    rows = [
        (42, "email", "hagenauer", "completed", "urgent", 0.91, datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)),
        (41, "whatsapp", "morv", "awaiting_commit", "routine", 0.55, datetime(2026, 4, 19, 9, 55, tzinfo=timezone.utc)),
    ]
    with _patch_conn([(cols, rows)]):
        resp = client.get("/api/kbl/signals")

    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body
    assert len(body["signals"]) == 2
    first = body["signals"][0]
    assert first["id"] == 42
    assert first["status"] == "completed"
    # Dates serialize to ISO strings.
    assert first["created_at"].startswith("2026-04-19")
    # Decimal triage_score serializes to float.
    assert isinstance(first["triage_score"], float)


def test_kbl_signals_empty_state(client):
    cols = ["id", "source", "primary_matter", "status", "vedana", "triage_score", "created_at"]
    with _patch_conn([(cols, [])]):
        resp = client.get("/api/kbl/signals")

    assert resp.status_code == 200
    assert resp.json() == {"signals": []}


# ---------------------------------------------------------------------------
# /api/kbl/cost-rollup
# ---------------------------------------------------------------------------


def test_kbl_cost_rollup_happy_path(client):
    rollup_cols = ["step", "model", "calls", "total_usd", "in_tok", "out_tok"]
    rollup_rows = [
        ("step5_opus", "claude-opus-4-6", 3, 1.25, 12000, 2400),
        ("step1_triage", "gemma-3-4b", 12, 0.0, 48000, 6400),
    ]
    total_cols = ["day_total"]
    total_rows = [(1.25,)]
    with _patch_conn([(rollup_cols, rollup_rows), (total_cols, total_rows)]):
        resp = client.get("/api/kbl/cost-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["cap_eur"] == 50.0
    assert body["day_total_eur"] == pytest.approx(1.25)
    assert body["remaining_eur"] == pytest.approx(48.75)
    assert len(body["rollup"]) == 2
    assert body["rollup"][0]["step"] == "step5_opus"
    assert isinstance(body["rollup"][0]["total_usd"], float)


def test_kbl_cost_rollup_empty_state(client):
    rollup_cols = ["step", "model", "calls", "total_usd", "in_tok", "out_tok"]
    total_cols = ["day_total"]
    with _patch_conn([(rollup_cols, []), (total_cols, [(0,)])]):
        resp = client.get("/api/kbl/cost-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["rollup"] == []
    assert body["day_total_eur"] == 0.0
    assert body["remaining_eur"] == 50.0


# ---------------------------------------------------------------------------
# /api/kbl/silver-landed
# ---------------------------------------------------------------------------


def test_kbl_silver_landed_happy_path(client):
    cols = ["id", "primary_matter", "target_vault_path", "committed_at", "short_sha"]
    rows = [
        (42, "hagenauer", "wiki/hagenauer/2026-04-19_update.md",
         datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc), "a1b2c3d"),
    ]
    with _patch_conn([(cols, rows)]):
        resp = client.get("/api/kbl/silver-landed")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["silver"]) == 1
    s = body["silver"][0]
    assert s["target_vault_path"].startswith("wiki/")
    assert s["short_sha"] == "a1b2c3d"
    assert s["committed_at"].startswith("2026-04-19")


def test_kbl_silver_landed_empty_state(client):
    cols = ["id", "primary_matter", "target_vault_path", "committed_at", "short_sha"]
    with _patch_conn([(cols, [])]):
        resp = client.get("/api/kbl/silver-landed")

    assert resp.status_code == 200
    assert resp.json() == {"silver": []}


# ---------------------------------------------------------------------------
# /api/kbl/mac-mini-status
# ---------------------------------------------------------------------------


def test_kbl_mac_mini_status_happy_path(client):
    cols = ["host", "version", "created_at", "age_seconds"]
    ts = datetime.now(timezone.utc) - timedelta(seconds=45)
    rows = [("mac-mini-01", "kbl-b-v1", ts, 45.0)]
    with _patch_conn([(cols, rows)]):
        resp = client.get("/api/kbl/mac-mini-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["heartbeat"] is not None
    hb = body["heartbeat"]
    assert hb["host"] == "mac-mini-01"
    assert hb["version"] == "kbl-b-v1"
    assert hb["age_seconds"] == pytest.approx(45.0)


def test_kbl_mac_mini_status_empty_state(client):
    cols = ["host", "version", "created_at", "age_seconds"]
    with _patch_conn([(cols, [])]):
        resp = client.get("/api/kbl/mac-mini-status")

    assert resp.status_code == 200
    assert resp.json() == {"heartbeat": None}
