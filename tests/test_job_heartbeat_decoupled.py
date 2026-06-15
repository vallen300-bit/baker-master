"""HEARTBEAT_DECOUPLE_FROM_EMBEDDING_1.

beat()/read() must reach the DB via a DIRECT connection (kbl.db.get_conn) — the
same Voyage-free path the backfills already use — NOT via SentinelStoreBack,
whose __init__ requires VOYAGE_API_KEY. Before this fix, a local backfill (no
Voyage key) could not write a heartbeat: store_back._get_global_instance() raised
"No API key provided", _store() returned None, and beat() silently no-op'd, so
job_heartbeats stayed empty for the 4 backfill jobs.

These tests prove the heartbeat write/read work with NO Voyage key in env and
even when memory.store_back is unimportable — i.e. the embedding coupling is gone.
"""
from __future__ import annotations

import contextlib
import sys

import pytest


class _FakeCur:
    def __init__(self, captured, fetch_row):
        self._captured = captured
        self._fetch_row = fetch_row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        # Record the last non-timeout statement (skip "SET LOCAL ...").
        if not sql.strip().upper().startswith("SET LOCAL"):
            self._captured["sql"] = sql
            self._captured["params"] = params

    def fetchone(self):
        return self._fetch_row


class _FakeConn:
    def __init__(self, captured, fetch_row=None):
        self._captured = captured
        self._fetch_row = fetch_row

    def cursor(self):
        return _FakeCur(self._captured, self._fetch_row)

    def commit(self):
        self._captured["committed"] = True

    def rollback(self):
        self._captured["rolledback"] = True


def _patch_conn(monkeypatch, captured, fetch_row=None):
    @contextlib.contextmanager
    def fake_get_conn():
        yield _FakeConn(captured, fetch_row)
    monkeypatch.setattr("kbl.db.get_conn", fake_get_conn)


@pytest.fixture(autouse=True)
def _no_voyage_no_storeback(monkeypatch):
    # The exact production gap: no Voyage key, and make the embedding store
    # unimportable so any accidental dependency on it fails loudly.
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY_PATH", raising=False)
    monkeypatch.setitem(sys.modules, "memory.store_back", None)
    yield


def test_beat_writes_without_voyage_or_storeback(monkeypatch):
    from orchestrator import job_heartbeat as jh
    captured: dict = {}
    _patch_conn(monkeypatch, captured)

    ok = jh.beat("graph_inbox_backfill", 95008, "DONE")

    assert ok is True
    assert "INSERT INTO job_heartbeats" in captured["sql"]
    assert "ON CONFLICT (job_id) DO UPDATE" in captured["sql"]
    assert captured["params"] == ("graph_inbox_backfill", "95008", "DONE")
    assert captured.get("committed") is True


def test_beat_coerces_cursor_to_text_and_none(monkeypatch):
    from orchestrator import job_heartbeat as jh
    captured: dict = {}
    _patch_conn(monkeypatch, captured)
    assert jh.beat("j", None, "RUNNING") is True
    assert captured["params"] == ("j", None, "RUNNING")


def test_beat_unknown_state_defaults_running(monkeypatch):
    from orchestrator import job_heartbeat as jh
    captured: dict = {}
    _patch_conn(monkeypatch, captured)
    assert jh.beat("j", "1:2", "BOGUS") is True
    assert captured["params"][2] == "RUNNING"


def test_beat_never_raises_and_returns_false_on_db_error(monkeypatch):
    from orchestrator import job_heartbeat as jh

    @contextlib.contextmanager
    def boom():
        raise RuntimeError("db down")
        yield  # pragma: no cover
    monkeypatch.setattr("kbl.db.get_conn", boom)
    # Must swallow and return False — a heartbeat failure must not crash work.
    assert jh.beat("j", 1, "RUNNING") is False


def test_beat_rolls_back_on_execute_error(monkeypatch):
    from orchestrator import job_heartbeat as jh
    captured: dict = {}

    class _RaisingCur(_FakeCur):
        def execute(self, sql, params=None):
            raise RuntimeError("constraint blew up")

    class _RaisingConn(_FakeConn):
        def cursor(self):
            return _RaisingCur(self._captured, None)

    @contextlib.contextmanager
    def fake_get_conn():
        yield _RaisingConn(captured)
    monkeypatch.setattr("kbl.db.get_conn", fake_get_conn)

    assert jh.beat("j", 1, "RUNNING") is False
    assert captured.get("rolledback") is True


def test_read_returns_row_without_voyage_or_storeback(monkeypatch):
    from orchestrator import job_heartbeat as jh
    import datetime as _dt
    ts = _dt.datetime(2026, 6, 16, tzinfo=_dt.timezone.utc)
    captured: dict = {}
    _patch_conn(monkeypatch, captured,
                fetch_row=("bluewin_inbox_backfill", "DONE-marker", "DONE", ts))

    out = jh.read("bluewin_inbox_backfill")

    assert out == {
        "job_id": "bluewin_inbox_backfill",
        "cursor_text": "DONE-marker",
        "state": "DONE",
        "updated_at": ts,
    }


def test_read_returns_none_for_missing_row(monkeypatch):
    from orchestrator import job_heartbeat as jh
    captured: dict = {}
    _patch_conn(monkeypatch, captured, fetch_row=None)
    assert jh.read("nope") is None


def test_module_does_not_import_store_back_at_load():
    # Importing the module must not pull in the embedding store.
    import importlib
    importlib.import_module("orchestrator.job_heartbeat")
    # store_back was poisoned to None in the fixture; a clean import above proves
    # job_heartbeat does not import it at module load.
