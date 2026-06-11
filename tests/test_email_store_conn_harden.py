"""EMAIL_STORE_CONN_HARDEN_1 — tests for the RCA fixes (bus #2813 / #2814).

One test block per change:
  AC1: pooled dsn_params carries keepalives (mirror direct_dsn_params values)
  AC2: stale cached conn -> one transparent retry -> caller sees success;
       reconnect failure still surfaces
  AC3: store_back pool maxconn from env, default 15
  AC4: is_processed fails CLOSED (skip) on pool exhaustion, warns with item id
"""

import logging
from unittest import mock

import pytest


# ----------------------------------------------------------------------
# AC1 — keepalives on the pooled DSN path
# ----------------------------------------------------------------------

def test_dsn_params_carries_keepalives():
    from config.settings import config

    pooled = config.postgres.dsn_params
    direct = config.postgres.direct_dsn_params
    for key in ("keepalives", "keepalives_idle", "keepalives_interval", "keepalives_count"):
        assert key in pooled, f"pooled dsn_params missing {key}"
        assert pooled[key] == direct[key], (
            f"pooled {key}={pooled[key]} must mirror direct {key}={direct[key]}"
        )


# ----------------------------------------------------------------------
# AC2 — retriever cached-conn ping: stale conn heals transparently
# ----------------------------------------------------------------------

class _StaleConn:
    """Cursor() raises the Neon idle-kill signature."""
    closed = 0

    def cursor(self):
        raise Exception("SSL connection has been closed unexpectedly")

    def close(self):
        self.closed = 1


class _HealthyConn:
    closed = 0

    class _Cur:
        def execute(self, sql):
            assert sql == "SELECT 1"

        def fetchone(self):
            return (1,)

        def close(self):
            pass

    def cursor(self):
        return self._Cur()

    def close(self):
        self.closed = 1


def _make_retriever():
    """Bare instance — bypass __init__ (Qdrant/Voyage clients not needed)."""
    from memory.retriever import SentinelRetriever
    r = SentinelRetriever.__new__(SentinelRetriever)
    r._pg_pool = None
    return r


def test_stale_conn_heals_with_single_reconnect():
    r = _make_retriever()
    stale = _StaleConn()
    fresh = _HealthyConn()
    r._pg_pool = stale

    with mock.patch("psycopg2.connect", return_value=fresh) as connect:
        conn = r._get_pg_conn()

    assert conn is fresh
    assert connect.call_count == 1
    assert stale.closed == 1, "stale conn must be closed on reset"


def test_healthy_conn_reused_without_reconnect():
    r = _make_retriever()
    healthy = _HealthyConn()
    r._pg_pool = healthy

    with mock.patch("psycopg2.connect") as connect:
        conn = r._get_pg_conn()

    assert conn is healthy
    connect.assert_not_called()


def test_reconnect_failure_still_surfaces():
    r = _make_retriever()
    r._pg_pool = _StaleConn()

    with mock.patch(
        "psycopg2.connect",
        side_effect=Exception("SSL connection has been closed unexpectedly"),
    ):
        with pytest.raises(Exception, match="SSL connection has been closed"):
            r._get_pg_conn()


# ----------------------------------------------------------------------
# AC3 — store_back pool maxconn env-overridable, default 15
# ----------------------------------------------------------------------

def _init_pool_capture(monkeypatch, env_value):
    from memory import store_back as sb

    if env_value is None:
        monkeypatch.delenv("BAKER_STOREBACK_MAXCONN", raising=False)
    else:
        monkeypatch.setenv("BAKER_STOREBACK_MAXCONN", env_value)

    captured = {}

    def fake_pool(minconn, maxconn, **kw):
        captured["minconn"] = minconn
        captured["maxconn"] = maxconn
        captured["kwargs"] = kw
        return mock.MagicMock()

    monkeypatch.setattr(sb.psycopg2.pool, "ThreadedConnectionPool", fake_pool)
    store = sb.SentinelStoreBack.__new__(sb.SentinelStoreBack)
    store._pool = None
    store._init_pool()
    return captured


def test_pool_maxconn_default_15(monkeypatch):
    captured = _init_pool_capture(monkeypatch, None)
    assert captured["maxconn"] == 15
    assert captured["minconn"] == 1


def test_pool_maxconn_env_override(monkeypatch):
    captured = _init_pool_capture(monkeypatch, "7")
    assert captured["maxconn"] == 7


def test_pool_maxconn_malformed_env_falls_back_to_default(monkeypatch, caplog):
    """G3 fix (bus #2818): a typoed tuning knob must never kill the pool."""
    with caplog.at_level(logging.WARNING, logger="sentinel.store_back"):
        captured = _init_pool_capture(monkeypatch, "not-an-int")
    assert captured["maxconn"] == 15, "malformed env must degrade to default"
    assert "BAKER_STOREBACK_MAXCONN" in " ".join(r.message for r in caplog.records)


def test_pool_maxconn_clamped_to_minimum_one(monkeypatch):
    captured = _init_pool_capture(monkeypatch, "0")
    assert captured["maxconn"] == 1


def test_pool_dsn_params_do_not_include_options(monkeypatch):
    monkeypatch.setenv("BAKER_STOREBACK_LOCK_TIMEOUT_MS", "750")
    captured = _init_pool_capture(monkeypatch, None)
    assert "options" not in captured["kwargs"]


def test_pool_strips_existing_dsn_options(monkeypatch):
    from memory import store_back as sb

    pooled = dict(sb.config.postgres.dsn_params)
    pooled["options"] = "-c lock_timeout=2000ms"
    with mock.patch.object(
        type(sb.config.postgres),
        "dsn_params",
        new_callable=mock.PropertyMock,
        return_value=pooled,
    ):
        captured = _init_pool_capture(monkeypatch, None)
    assert "options" not in captured["kwargs"]


class _BootstrapConn:
    def __init__(self):
        self.executed = []
        self.rollbacks = 0

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def close(self):
        pass

    def rollback(self):
        self.rollbacks += 1


class _BootstrapPool:
    def __init__(self, conn):
        self.conn = conn
        self.put_back = []

    def getconn(self):
        return self.conn

    def putconn(self, conn):
        self.put_back.append(conn)


def test_bootstrap_conn_sets_local_lock_timeout(monkeypatch):
    monkeypatch.setenv("BAKER_STOREBACK_LOCK_TIMEOUT_MS", "750")
    from memory import store_back as sb

    store = sb.SentinelStoreBack.__new__(sb.SentinelStoreBack)
    conn = _BootstrapConn()
    store._pool = _BootstrapPool(conn)
    store._bootstrap_lock_timeout_ms = store._parse_bootstrap_lock_timeout_ms()
    store._bootstrap_lock_timeout_enabled = True

    assert store._get_conn() is conn
    assert conn.executed == [
        ("SET LOCAL lock_timeout = %s", ("750ms",))
    ]


def test_pool_lock_timeout_malformed_env_falls_back_to_default(monkeypatch, caplog):
    monkeypatch.setenv("BAKER_STOREBACK_LOCK_TIMEOUT_MS", "bad-timeout")
    with caplog.at_level(logging.WARNING, logger="sentinel.store_back"):
        from memory import store_back as sb
        store = sb.SentinelStoreBack.__new__(sb.SentinelStoreBack)
        parsed = store._parse_bootstrap_lock_timeout_ms()
    assert parsed == 2000
    assert "BAKER_STOREBACK_LOCK_TIMEOUT_MS" in " ".join(r.message for r in caplog.records)


def test_pool_init_failure_logs_error(monkeypatch, caplog):
    from memory import store_back as sb

    def boom(*args, **kwargs):
        raise RuntimeError("unsupported startup parameter")

    monkeypatch.setattr(sb.psycopg2.pool, "ThreadedConnectionPool", boom)
    store = sb.SentinelStoreBack.__new__(sb.SentinelStoreBack)
    store._pool = None

    with caplog.at_level(logging.ERROR, logger="sentinel.store_back"):
        store._init_pool()

    assert store._pool is None
    assert any("PostgreSQL pool init failed" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# AC4 — is_processed fails CLOSED on pool exhaustion
# ----------------------------------------------------------------------

def test_is_processed_fails_closed_on_pool_exhaustion(caplog):
    from triggers.state import TriggerState

    ts = TriggerState.__new__(TriggerState)
    store = mock.MagicMock()
    store._get_conn.return_value = None  # pool exhausted
    ts._get_store = lambda: store

    with caplog.at_level(logging.WARNING, logger="sentinel.trigger_state"):
        result = ts.is_processed("email", "msg-abc-123")

    assert result is True, "pool exhaustion must fail CLOSED (skip item)"
    joined = " ".join(rec.message for rec in caplog.records)
    assert "msg-abc-123" in joined, "WARN must carry the item id"
    assert "failing CLOSED" in joined


def test_is_processed_normal_path_unaffected():
    from triggers.state import TriggerState

    ts = TriggerState.__new__(TriggerState)
    cur = mock.MagicMock()
    cur.fetchone.return_value = None  # not in trigger_log
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    store = mock.MagicMock()
    store._get_conn.return_value = conn
    ts._get_store = lambda: store

    assert ts.is_processed("email", "msg-new") is False
    store._put_conn.assert_called_once_with(conn)
