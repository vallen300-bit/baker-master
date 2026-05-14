"""Tests for /api/worker/wake + /api/worker/digest — BRIEF_WORKER_SELFWAKE_PHASE_1.

Tier mix:
    - Source-level: route registered, auth dep wired, action_class name correct.
    - TestClient with mocked store: 401/400/200 paths + digest aggregation
      against an in-memory fake cursor.
    - Live-PG (skips when no DB): full round-trip via clean_baker_actions
      fixture from conftest.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Importability skip guard (matches test_cortex_action_endpoint.py pattern)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Source-level checks (always run; cheap)
# ---------------------------------------------------------------------------

def test_wake_route_registered_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '@app.post("/api/worker/wake"' in src
    assert 'tags=["worker"]' in src
    assert 'dependencies=[Depends(verify_api_key)]' in src
    assert "async def worker_wake_log(request: Request):" in src


def test_digest_route_registered_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '@app.get("/api/worker/digest"' in src
    assert "async def worker_digest(since: str):" in src


def test_action_class_name_matches_brief_in_source():
    """worker.wake.b_code must be the canonical action_class name everywhere."""
    src = Path("outputs/dashboard.py").read_text()
    assert "'worker.wake.b_code'" in src
    mig = Path("migrations/20260515_worker_self_wake.sql").read_text()
    assert "'worker.wake.b_code'" in mig
    assert "ON CONFLICT (class_name) DO NOTHING" in mig


def test_wake_validates_required_fields_in_source():
    src = Path("outputs/dashboard.py").read_text()
    for field in (
        "worker_slug", "wake_ts", "messages_drained", "claude_exit_code",
        "claude_stdout_tokens", "duration_seconds", "cost_eur_est",
    ):
        assert field in src, f"required field missing from validation: {field}"
    assert "missing_fields:" in src
    assert "invalid_worker_slug:" in src


def test_wake_rollback_in_except_in_source():
    """python-backend.md rule: every except must call conn.rollback()."""
    src = Path("outputs/dashboard.py").read_text()
    # Slice from the wake handler signature (skips the comment-block mention).
    snippet = src.split("async def worker_wake_log")[1].split("# CLI runner")[0]
    # Both wake and digest handlers live in this slice; require >=2 rollback calls.
    assert snippet.count("conn.rollback()") >= 2, (
        "expected conn.rollback() in both /api/worker/wake AND /api/worker/digest "
        f"except blocks; got {snippet.count('conn.rollback()')}"
    )


# ---------------------------------------------------------------------------
# TestClient — auth + validation paths (no live PG required)
# ---------------------------------------------------------------------------

def _client_with_fake_store(monkeypatch, fake_cursor):
    """Build a TestClient where SentinelStoreBack._get_global_instance returns a
    fake store whose _get_conn() returns a connection wrapping fake_cursor.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key"

    class FakeConn:
        def __init__(self, cur):
            self._cur = cur
            self.rolled_back = False
            self.committed = False
        def cursor(self):
            return self._cur
        def commit(self):
            self.committed = True
        def rollback(self):
            self.rolled_back = True

    class FakeStore:
        def __init__(self, conn):
            self._conn = conn
            self.put_count = 0
        def _get_conn(self):
            return self._conn
        def _put_conn(self, conn):
            self.put_count += 1

    fake_conn = FakeConn(fake_cursor)
    fake_store = FakeStore(fake_conn)

    import memory.store_back as sb
    monkeypatch.setattr(sb.SentinelStoreBack, "_get_global_instance", classmethod(lambda cls: fake_store))

    client = TestClient(dash.app)
    return client, fake_store, fake_conn


class _RecordingCursor:
    """Minimal fake cursor — records execute() calls + serves canned fetchone/fetchall."""
    def __init__(self, fetchone_seq=None, fetchall_seq=None):
        self.executed = []
        self._fetchone = list(fetchone_seq or [])
        self._fetchall = list(fetchall_seq or [])
        self.closed = False
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None
    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []
    def close(self):
        self.closed = True


@_skip_without_dashboard
def test_wake_401_without_auth(monkeypatch):
    """Unauthenticated POST must 401 before touching the DB."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key"
    from fastapi.testclient import TestClient
    client = TestClient(dash.app)
    resp = client.post("/api/worker/wake", json={"worker_slug": "b1"})
    assert resp.status_code == 401


@_skip_without_dashboard
def test_wake_400_on_missing_fields(monkeypatch):
    cur = _RecordingCursor(fetchone_seq=[(123,)])
    client, store, conn = _client_with_fake_store(monkeypatch, cur)
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": "test-key"},
        json={"worker_slug": "b1"},   # missing the rest
    )
    assert resp.status_code == 400
    assert "missing_fields" in resp.json().get("detail", "")
    assert cur.executed == [], "DB must NOT be touched on validation failure"


@_skip_without_dashboard
def test_wake_400_on_bad_worker_slug(monkeypatch):
    cur = _RecordingCursor(fetchone_seq=[(123,)])
    client, store, conn = _client_with_fake_store(monkeypatch, cur)
    body = {
        "worker_slug": "ah1",   # not in {b1..b4}
        "wake_ts": "2026-05-15T00:00:00+00:00",
        "messages_drained": 1,
        "claude_exit_code": 0,
        "claude_stdout_tokens": 100,
        "duration_seconds": 1.5,
        "cost_eur_est": 0.05,
    }
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": "test-key"},
        json=body,
    )
    assert resp.status_code == 400
    assert "invalid_worker_slug" in resp.json().get("detail", "")
    assert cur.executed == []


@_skip_without_dashboard
def test_wake_200_inserts_row(monkeypatch):
    cur = _RecordingCursor(fetchone_seq=[(42,)])
    client, store, conn = _client_with_fake_store(monkeypatch, cur)
    body = {
        "worker_slug": "b1",
        "wake_ts": "2026-05-15T00:00:00+00:00",
        "messages_drained": 1,
        "message_ids": [230],
        "claude_exit_code": 0,
        "claude_stdout_tokens": 42527,
        "claude_stderr_truncated": "",
        "duration_seconds": 2.5,
        "cost_eur_est": 0.245,
    }
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": "test-key"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "id": 42}
    assert len(cur.executed) == 1
    sql, params = cur.executed[0]
    assert "INSERT INTO baker_actions" in sql
    assert "worker_wake" == params[0]
    assert "B" == params[4]
    assert "worker.wake.b_code" == params[6]
    assert "worker-b1" == params[7]
    assert "2026-05-15T00:00:00+00:00" == params[8]
    assert conn.committed is True
    assert conn.rolled_back is False


@_skip_without_dashboard
def test_wake_500_rollback_on_db_error(monkeypatch):
    """When cursor.execute raises, the conn must be rolled back + 500 returned."""
    class BoomCursor(_RecordingCursor):
        def execute(self, sql, params=None):
            raise RuntimeError("simulated db error")
    cur = BoomCursor()
    client, store, conn = _client_with_fake_store(monkeypatch, cur)
    body = {
        "worker_slug": "b1",
        "wake_ts": "2026-05-15T00:00:00+00:00",
        "messages_drained": 0,
        "claude_exit_code": 0,
        "claude_stdout_tokens": 0,
        "duration_seconds": 0.1,
        "cost_eur_est": 0.0,
    }
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": "test-key"},
        json=body,
    )
    assert resp.status_code == 500
    assert "audit_write_failed" in resp.json().get("detail", "")
    assert conn.rolled_back is True
    assert store.put_count == 1   # _put_conn called in finally


@_skip_without_dashboard
def test_digest_aggregates_by_committer(monkeypatch):
    """Digest groups by committer_agent and strips worker- prefix; sums cost."""
    cur = _RecordingCursor(
        fetchall_seq=[[
            ("worker-b1", 3, 12345, 0, 0.45),
            ("worker-b2", 1, 5000, 1, 0.10),
            ("worker-other", 99, 99, 99, 99),   # filtered out
        ]],
    )
    client, store, conn = _client_with_fake_store(monkeypatch, cur)
    resp = client.get(
        "/api/worker/digest?since=2026-05-14T00:00:00%2B00:00",
        headers={"X-Baker-Key": "test-key"},
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["b1"] == {"wake_count": 3, "total_tokens": 12345, "fail_count": 0, "breaker_tripped": False}
    assert out["b2"] == {"wake_count": 1, "total_tokens": 5000, "fail_count": 1, "breaker_tripped": False}
    assert "worker-other" not in out
    assert "other" not in out
    assert out["total_cost_eur"] == 0.55
    assert len(cur.executed) == 1
    sql, _ = cur.executed[0]
    assert "GROUP BY committer_agent" in sql
    assert "LIMIT 100" in sql


# ---------------------------------------------------------------------------
# Live-PG round-trip — uses conftest.py clean_baker_actions fixture
# ---------------------------------------------------------------------------

@_skip_without_dashboard
def test_wake_live_pg_round_trip(clean_baker_actions, register_class, monkeypatch):
    """End-to-end: POST /api/worker/wake → row in baker_actions with action_class
    set, retrievable via /api/worker/digest."""
    register_class("worker.wake.b_code", 0.10, "test-seed for selfwake-phase-1")

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key"
    from fastapi.testclient import TestClient
    client = TestClient(dash.app)

    body = {
        "worker_slug": "b1",
        "wake_ts": "2026-05-15T12:00:00+00:00",
        "messages_drained": 2,
        "message_ids": [100, 101],
        "claude_exit_code": 0,
        "claude_stdout_tokens": 42527,
        "claude_stderr_truncated": "",
        "duration_seconds": 2.5,
        "cost_eur_est": 0.25,
    }
    resp = client.post(
        "/api/worker/wake",
        headers={"X-Baker-Key": "test-key"},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["id"]
    assert isinstance(new_id, int) and new_id > 0

    # Verify the row materialized with the right shape.
    conn = clean_baker_actions._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT action_type, tier, action_class, committer_agent, "
            "       cost_eur, self_cost_eur, "
            "       (payload->>'claude_stdout_tokens')::int "
            "  FROM baker_actions WHERE id = %s",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        clean_baker_actions._put_conn(conn)
    assert row is not None
    assert row[0] == "worker_wake"
    assert row[1] == "B"
    assert row[2] == "worker.wake.b_code"
    assert row[3] == "worker-b1"
    assert float(row[4]) == 0.25
    assert float(row[5]) == 0.25
    assert int(row[6]) == 42527

    # Now /api/worker/digest should aggregate this row.
    resp = client.get(
        "/api/worker/digest?since=2026-05-15T00:00:00%2B00:00",
        headers={"X-Baker-Key": "test-key"},
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert "b1" in out
    assert out["b1"]["wake_count"] == 1
    assert out["b1"]["total_tokens"] == 42527
    assert out["b1"]["fail_count"] == 0
    assert abs(out["total_cost_eur"] - 0.25) < 1e-6
