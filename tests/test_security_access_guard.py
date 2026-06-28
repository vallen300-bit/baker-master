"""Vertical tests for BREACH_DETECT_PHASE1_1 — security access guard.

TDD-first (brief Hard Gate): these 4 cases are written BEFORE the implementation
and define the public seam of ``security/access_guard.py`` + the middleware.

The 4 brief cases:
  1. Freeze gate: BAKER_SECURITY_FREEZE=1 (or DB global_freeze) -> protected route
     503; /health + /api/security/* still 200.
  2. A successful request writes EXACTLY ONE security_access_log row with NO
     body/secret columns (metadata only).
  3. An auth-failure (401) is logged AND increments the per-key auth-fail counter
     that feeds the tripwire.
  4. Simulated bulk read (N requests in window) -> EXACTLY ONE Slack alarm
     (rate-limited, not N alarms).

No live DB required: the freeze env backstop is DB-free, and the audit/alarm
paths are exercised with a FakeConn / monkeypatched seams so the suite runs on a
plain ``pytest`` from any clone.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from security import access_guard as guard


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        # Answer the freeze SELECT if the freeze DB-path is exercised.
        if "FROM security_freeze" in sql:
            self._conn._last = (False, "")
        else:
            self._conn._last = None

    def fetchone(self):
        return self._conn._last

    def fetchall(self):
        return []

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.executed = []
        self.committed = 0
        self.rolled_back = 0
        self._last = None

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def _build_app() -> FastAPI:
    """Minimal app carrying the real middleware — no dashboard.py import."""
    app = FastAPI()
    app.middleware("http")(guard.security_guard_middleware)

    @app.get("/api/email/list")
    def _protected():
        return {"ok": True}

    @app.get("/health")
    def _health():
        return {"status": "ok"}

    @app.get("/api/security/status")
    def _sec_status():
        return {"frozen": False}

    @app.get("/api/email/locked")
    def _needs_auth():
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return app


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Reset in-memory guard state + clear the freeze env between tests."""
    monkeypatch.delenv("BAKER_SECURITY_FREEZE", raising=False)
    guard.reset_state()
    yield
    guard.reset_state()


# --------------------------------------------------------------------------- #
# Case 1 — freeze gate
# --------------------------------------------------------------------------- #
def test_freeze_blocks_protected_but_exempts_health_and_security(monkeypatch):
    # Audit path is irrelevant to this case; keep it DB-free.
    monkeypatch.setattr(guard, "record_and_evaluate", lambda *a, **k: None)
    monkeypatch.setenv("BAKER_SECURITY_FREEZE", "1")
    client = TestClient(_build_app())

    r = client.get("/api/email/list")
    assert r.status_code == 503
    assert r.json().get("error") == "service_frozen"

    assert client.get("/health").status_code == 200
    assert client.get("/api/security/status").status_code == 200


def test_freeze_env_backstop_independent_of_db(monkeypatch):
    """Env backstop must win even if the DB freeze read would fail."""
    monkeypatch.setattr(guard, "_get_store_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setenv("BAKER_SECURITY_FREEZE", "1")
    frozen, reason = guard.is_frozen()
    assert frozen is True
    assert "env" in reason.lower()


# --------------------------------------------------------------------------- #
# Case 2 — audit row is metadata-only, exactly one per request
# --------------------------------------------------------------------------- #
def test_successful_request_writes_one_metadata_only_row(monkeypatch):
    monkeypatch.setattr(guard, "is_frozen", lambda: (False, ""))
    fake = _FakeConn()
    monkeypatch.setattr(guard, "_get_store_conn", lambda: fake)
    monkeypatch.setattr(guard, "_put_store_conn", lambda conn: None)

    client = TestClient(_build_app())
    assert client.get("/api/email/list").status_code == 200

    inserts = [(sql, p) for (sql, p) in fake.executed if "INSERT INTO security_access_log" in sql]
    assert len(inserts) == 1, f"expected exactly one audit INSERT, got {len(inserts)}"

    # The schema/insert must carry ONLY metadata columns — no body/secret/raw key.
    forbidden = ("body", "secret", "password", "raw_key", "token", "content", "payload")
    for col in guard.ACCESS_LOG_COLUMNS:
        assert not any(f in col.lower() for f in forbidden), f"forbidden column: {col}"

    sql, params = inserts[0]
    assert "body" not in sql.lower() and "secret" not in sql.lower()
    # key_fp must be a short hash, never the raw key.
    meta_keys = dict(zip(guard.ACCESS_LOG_COLUMNS, params))
    assert meta_keys["key_fp"] != "supersecretkey"
    assert len(str(meta_keys["key_fp"])) <= 16


# --------------------------------------------------------------------------- #
# Case 3 — 401 logged + per-key auth-fail counter increments
# --------------------------------------------------------------------------- #
def test_auth_failure_logged_and_counted(monkeypatch):
    monkeypatch.setattr(guard, "is_frozen", lambda: (False, ""))
    fake = _FakeConn()
    monkeypatch.setattr(guard, "_get_store_conn", lambda: fake)
    monkeypatch.setattr(guard, "_put_store_conn", lambda conn: None)

    client = TestClient(_build_app())
    r = client.get("/api/email/locked", headers={"X-Baker-Key": "wrong-key"})
    assert r.status_code == 401

    inserts = [s for (s, _) in fake.executed if "INSERT INTO security_access_log" in s]
    assert len(inserts) == 1  # the 401 is still audited

    key_fp = guard._hash("wrong-key")
    assert guard.get_auth_fail_count(key_fp) == 1

    # A second failure with the same bad key increments to 2.
    client.get("/api/email/locked", headers={"X-Baker-Key": "wrong-key"})
    assert guard.get_auth_fail_count(key_fp) == 2


# --------------------------------------------------------------------------- #
# Case 4 — bulk read trips exactly one rate-limited alarm
# --------------------------------------------------------------------------- #
def test_bulk_read_fires_single_alarm(monkeypatch):
    monkeypatch.setattr(guard, "is_frozen", lambda: (False, ""))
    monkeypatch.setattr(guard, "_get_store_conn", lambda: None)  # audit no-ops, fail-open
    monkeypatch.setattr(guard, "_put_store_conn", lambda conn: None)
    monkeypatch.setattr(guard, "BULK_READ_THRESHOLD", 5)
    monkeypatch.setattr(guard, "WINDOW_SECONDS", 3600)
    monkeypatch.setattr(guard, "ALARM_WINDOW_SECONDS", 3600)

    alarms = []
    monkeypatch.setattr(guard, "security_alarm_send", lambda text, dedupe_key="": alarms.append(text) or True)

    client = TestClient(_build_app())
    for _ in range(8):
        client.get("/api/email/list", headers={"X-Baker-Key": "same-key"})

    assert len(alarms) == 1, f"expected exactly one rate-limited alarm, got {len(alarms)}"


def test_alarm_bypasses_director_block_flags(monkeypatch):
    """Slack alarm fires even when both Director email/WA blocks are on."""
    monkeypatch.setenv("BAKER_BLOCK_EMAIL_TO_DIRECTOR", "true")
    monkeypatch.setenv("BAKER_BLOCK_WA_TO_DIRECTOR", "true")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

    posted = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json

        class _R:
            status_code = 200

        return _R()

    import requests

    monkeypatch.setattr(requests, "post", _fake_post)
    sent = guard.security_alarm_send("breach tripwire test", dedupe_key="")
    assert sent is True
    assert "slack.com" in posted.get("url", "")


# --------------------------------------------------------------------------- #
# Addendum (#4518) — retention prune is bounded, batched, honors the window
# --------------------------------------------------------------------------- #
def test_prune_access_log_batched_and_bounded(monkeypatch):
    class _PruneCursor:
        def __init__(self, conn):
            self._c = conn
            self.rowcount = 0

        def execute(self, sql, params=None):
            self._c.calls.append((sql, params))
            self.rowcount = self._c.counts.pop(0) if self._c.counts else 0

        def close(self):
            pass

    class _PruneConn:
        def __init__(self, counts):
            self.counts = list(counts)
            self.calls = []
            self.commits = 0

        def cursor(self):
            return _PruneCursor(self)

        def commit(self):
            self.commits += 1

        def rollback(self):
            pass

    # Two full batches then a short tail -> loop terminates after 3 DELETEs.
    fake = _PruneConn(counts=[5000, 5000, 17])
    monkeypatch.setattr(guard, "_get_store_conn", lambda: fake)
    monkeypatch.setattr(guard, "_put_store_conn", lambda c: None)
    monkeypatch.setenv("BAKER_SECURITY_LOG_RETENTION_DAYS", "90")

    deleted = guard.prune_access_log(batch_size=5000)
    assert deleted == 5000 + 5000 + 17
    assert len(fake.calls) == 3
    assert all("DELETE FROM security_access_log" in s for s, _ in fake.calls)
    # Every DELETE is LIMIT-bounded and carries the retention window (90 days).
    for sql, params in fake.calls:
        assert "LIMIT" in sql.upper()
        assert 90 in (params or ())
        assert 5000 in (params or ())


def test_prune_retention_days_default_and_env(monkeypatch):
    monkeypatch.delenv("BAKER_SECURITY_LOG_RETENTION_DAYS", raising=False)
    assert guard.retention_days() == 90
    monkeypatch.setenv("BAKER_SECURITY_LOG_RETENTION_DAYS", "30")
    assert guard.retention_days() == 30
    monkeypatch.setenv("BAKER_SECURITY_LOG_RETENTION_DAYS", "garbage")
    assert guard.retention_days() == 90  # fault-tolerant fallback
