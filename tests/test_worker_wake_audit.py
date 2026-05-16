"""Tests for POST /api/worker/wake + GET /api/worker/digest.

WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Coverage:
  /api/worker/wake
    1. Missing X-Baker-Key  -> 401
    2. Valid payload         -> 200 + INSERT executed with expected columns
    3. Missing required field -> 422 (FastAPI/Pydantic auto-validation)
    4. Invalid worker_slug    -> 422 (Pydantic pattern constraint)

  /api/worker/digest
    5. Missing X-Baker-Key   -> 401
    6. Valid since=ISO        -> 200 + aggregated dict + SELECT executed
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------

_API_KEY = "test-key-worker-wake"


def _set_api_key(monkeypatch, key: str = _API_KEY):
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = key
    from outputs.dashboard import verify_api_key
    dash.app.dependency_overrides.pop(verify_api_key, None)


def _make_fake_store(fetchone_result=(42,), fetchall_result=None):
    """Build a fake `store` whose `_get_conn()` returns a fake conn whose
    cursor exposes execute() + fetchone() / fetchall() + supports the `with`
    context-manager pattern used in the endpoints."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    cur.fetchall.return_value = fetchall_result or []
    cur.__enter__ = lambda self: cur
    cur.__exit__ = lambda self, *a: None

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()

    store = MagicMock()
    store._get_conn.return_value = conn
    store._put_conn = MagicMock()
    return store, conn, cur


# ---------------------------------------------------------------------------
# /api/worker/wake — 1. unauthorized
# ---------------------------------------------------------------------------

def test_worker_wake_unauthorized(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.post(
        "/api/worker/wake",
        json={
            "worker_slug": "b1",
            "wake_ts": "2026-05-15T00:00:00+00:00",
            "messages_drained": 1,
            "message_ids": [42],
            "claude_exit_code": 0,
            "claude_stdout_tokens": 100,
            "duration_seconds": 1.5,
            "cost_eur_est": 0.01,
        },
        # NO X-Baker-Key
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# /api/worker/wake — 2. valid payload writes audit row
# ---------------------------------------------------------------------------

def test_worker_wake_valid_payload_writes_row(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    store, conn, cur = _make_fake_store(fetchone_result=(123,))
    with patch("outputs.dashboard._get_store", return_value=store):
        client = TestClient(app)
        resp = client.post(
            "/api/worker/wake",
            headers={"X-Baker-Key": _API_KEY},
            json={
                "worker_slug": "b1",
                "wake_ts": "2026-05-15T01:00:00+00:00",
                "messages_drained": 2,
                "message_ids": [10, 11],
                "claude_exit_code": 0,
                "claude_stdout_tokens": 2500,
                "claude_stderr_truncated": "",
                "duration_seconds": 12.3,
                "cost_eur_est": 0.25,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"ok": True, "id": 123}

    # Confirm SQL was executed + parameter shape
    assert cur.execute.called
    sql_text, params = cur.execute.call_args[0]
    assert "INSERT INTO baker_actions" in sql_text
    # Column-list fail-loud assertion against schema drift
    for col in (
        "action_type", "payload", "trigger_source", "success",
        "tier", "cost_eur", "action_class",
        "committer_agent", "committed_at", "self_cost_eur",
    ):
        assert col in sql_text, f"missing column {col!r} in INSERT"
    # Sanity-check param mapping
    assert params[0] == "worker_wake"
    payload_json = json.loads(params[1])
    assert payload_json["worker_slug"] == "b1"
    assert payload_json["claude_exit_code"] == 0
    assert params[2] == "self_wake_worker"
    assert params[3] is True                 # success (exit_code == 0)
    assert params[4] == "B"                  # tier
    assert float(params[5]) == 0.25          # cost_eur
    assert params[6] == "worker.wake.b_code"
    assert params[7] == "worker-b1"
    assert params[8] == "2026-05-15T01:00:00+00:00"
    assert float(params[9]) == 0.25          # self_cost_eur
    assert conn.commit.called
    assert store._put_conn.called


# ---------------------------------------------------------------------------
# /api/worker/wake — 3. missing required field → 422
# ---------------------------------------------------------------------------

def test_worker_wake_missing_field(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": _API_KEY},
        json={
            "worker_slug": "b1",
            # Missing: wake_ts, messages_drained, claude_exit_code, ...
        },
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# /api/worker/wake — 4. invalid worker_slug (Pydantic pattern) → 422
# ---------------------------------------------------------------------------

def test_worker_wake_invalid_slug(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": _API_KEY},
        json={
            "worker_slug": "b9",  # Not b1-b4
            "wake_ts": "2026-05-15T00:00:00+00:00",
            "messages_drained": 0,
            "message_ids": [],
            "claude_exit_code": 0,
            "claude_stdout_tokens": 0,
            "duration_seconds": 0,
            "cost_eur_est": 0,
        },
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# /api/worker/digest — 5. unauthorized
# ---------------------------------------------------------------------------

def test_worker_digest_unauthorized(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.get(
        "/api/worker/digest",
        params={"since": "2026-05-14T00:00:00+00:00"},
        # NO X-Baker-Key
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# /api/worker/digest — 6. aggregates and returns expected shape
# ---------------------------------------------------------------------------

def test_worker_digest_aggregates(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    # Two synthetic groupings: worker-b1 + worker-b3
    rows = [
        ("worker-b1", 5, 12_345, 1, 0.50),
        ("worker-b3", 2, 4_000, 0, 0.20),
    ]
    store, conn, cur = _make_fake_store(fetchall_result=rows)
    with patch("outputs.dashboard._get_store", return_value=store):
        client = TestClient(app)
        resp = client.get(
            "/api/worker/digest",
            params={"since": "2026-05-14T00:00:00+00:00"},
            headers={"X-Baker-Key": _API_KEY},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["b1"] == {"wake_count": 5, "total_tokens": 12_345, "fail_count": 1, "breaker_tripped": False}
    assert body["b3"] == {"wake_count": 2, "total_tokens": 4_000,  "fail_count": 0, "breaker_tripped": False}
    assert abs(body["total_cost_eur"] - 0.70) < 1e-6

    # Verify SELECT shape
    sql_text, params = cur.execute.call_args[0]
    assert "FROM baker_actions" in sql_text
    assert "action_class = 'worker.wake.b_code'" in sql_text
    assert "payload->>'claude_stdout_tokens'" in sql_text
    assert "GROUP BY committer_agent" in sql_text
    assert "LIMIT 100" in sql_text
    assert params == ("2026-05-14T00:00:00+00:00",)
    assert store._put_conn.called
