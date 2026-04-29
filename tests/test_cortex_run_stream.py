"""Tests for outputs/cortex_run_stream.py — CORTEX_MANUAL_INVOKE_1.

Pure unit tests of the streaming + rate-limit + cost-warn helpers. DB
calls are mocked at the SentinelStoreBack._get_global_instance() level so
the suite runs without TEST_DATABASE_URL.

Coverage:
1. _sse formats payload as a single SSE data block
2. runs_in_last_hour returns COUNT(*) from cortex_cycles
3. runs_in_last_hour returns 0 on conn==None (DB unavailable, fail-open)
4. specialist_calls_today joins cortex_phase_outputs to cortex_cycles
5. _snapshot_cycle returns latest row + phase-output count, or None
6. stream_cycle_events emits started → phase_changed → terminal sequence
7. stream_cycle_events emits terminal=failed when maybe_run_cycle raises
8. stream_cycle_events emits terminal=timeout on asyncio.TimeoutError
"""
from __future__ import annotations

import asyncio
import json
from typing import Iterator
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal psycopg2-style cursor that returns scripted results."""

    def __init__(self, scripted_rows):
        # scripted_rows: list of rows to be returned by successive fetchone()
        self._scripted = list(scripted_rows)
        self._calls = []

    def execute(self, sql, params=None):
        self._calls.append((sql, params))

    def fetchone(self):
        if not self._scripted:
            return None
        return self._scripted.pop(0)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, scripted_rows):
        self._scripted = scripted_rows
        self.rollback_called = False

    def cursor(self):
        return _FakeCursor(self._scripted)

    def rollback(self):
        self.rollback_called = True


class _FakeStore:
    """Stand-in for SentinelStoreBack that returns _FakeConn instances."""

    def __init__(self, conn=None):
        self._conn = conn

    def _get_conn(self):
        return self._conn

    def _put_conn(self, conn):
        pass


def _patch_store(monkeypatch, conn):
    """Make _get_store() return a _FakeStore wrapping conn (or None)."""
    import outputs.cortex_run_stream as mod
    monkeypatch.setattr(mod, "_get_store", lambda: _FakeStore(conn))


# ---------------------------------------------------------------------------
# Test 1 — _sse format
# ---------------------------------------------------------------------------

def test_sse_format_single_data_block():
    from outputs.cortex_run_stream import _sse
    out = _sse({"type": "started", "x": 1})
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    body = out[len("data: "):-2]
    assert json.loads(body) == {"type": "started", "x": 1}


# ---------------------------------------------------------------------------
# Test 2 — runs_in_last_hour COUNT(*)
# ---------------------------------------------------------------------------

def test_runs_in_last_hour_returns_count(monkeypatch):
    from outputs.cortex_run_stream import runs_in_last_hour
    conn = _FakeConn(scripted_rows=[(3,)])
    _patch_store(monkeypatch, conn)
    assert runs_in_last_hour("oskolkov") == 3


# ---------------------------------------------------------------------------
# Test 3 — runs_in_last_hour fail-open on conn==None
# ---------------------------------------------------------------------------

def test_runs_in_last_hour_db_unavailable_returns_zero(monkeypatch):
    from outputs.cortex_run_stream import runs_in_last_hour
    _patch_store(monkeypatch, None)
    assert runs_in_last_hour("oskolkov") == 0


# ---------------------------------------------------------------------------
# Test 4 — specialist_calls_today joins phase_outputs to cycles
# ---------------------------------------------------------------------------

def test_specialist_calls_today_returns_count(monkeypatch):
    from outputs.cortex_run_stream import specialist_calls_today
    conn = _FakeConn(scripted_rows=[(17,)])
    _patch_store(monkeypatch, conn)
    assert specialist_calls_today("oskolkov") == 17


def test_specialist_calls_today_db_unavailable_returns_zero(monkeypatch):
    from outputs.cortex_run_stream import specialist_calls_today
    _patch_store(monkeypatch, None)
    assert specialist_calls_today("oskolkov") == 0


# ---------------------------------------------------------------------------
# Test 5 — _snapshot_cycle returns row + count, or None
# ---------------------------------------------------------------------------

def test_snapshot_cycle_returns_dict(monkeypatch):
    from outputs.cortex_run_stream import _snapshot_cycle
    conn = _FakeConn(scripted_rows=[
        ("uuid-1234", "in_flight", "load"),  # cycle row
        (5,),                                 # phase output count
    ])
    _patch_store(monkeypatch, conn)
    snap = _snapshot_cycle(matter_slug="oskolkov", triggered_by="director_manual")
    assert snap == {
        "cycle_id": "uuid-1234",
        "status": "in_flight",
        "current_phase": "load",
        "phase_outputs_count": 5,
    }


def test_snapshot_cycle_returns_none_when_no_cycle(monkeypatch):
    from outputs.cortex_run_stream import _snapshot_cycle
    conn = _FakeConn(scripted_rows=[None])  # cycle row missing
    _patch_store(monkeypatch, conn)
    assert _snapshot_cycle(
        matter_slug="movie", triggered_by="director_manual",
    ) is None


def test_snapshot_cycle_returns_none_when_db_unavailable(monkeypatch):
    from outputs.cortex_run_stream import _snapshot_cycle
    _patch_store(monkeypatch, None)
    assert _snapshot_cycle(
        matter_slug="oskolkov", triggered_by="scan_intent",
    ) is None


# ---------------------------------------------------------------------------
# Test 6 — stream_cycle_events emits started → phase_changed → terminal
# ---------------------------------------------------------------------------


class _FakeCycleResult:
    def __init__(self):
        self.cycle_id = "cycle-xyz"
        self.status = "proposed"
        self.current_phase = "archive"
        self.cost_dollars = 0.42
        self.cost_tokens = 12345
        self.aborted_reason = None


@pytest.mark.asyncio
async def test_stream_cycle_events_emits_full_sequence(monkeypatch):
    from outputs.cortex_run_stream import stream_cycle_events
    import outputs.cortex_run_stream as mod

    # Speed up polling so the test runs <1s
    monkeypatch.setattr(mod, "POLL_INTERVAL_SECONDS", 0.01)

    snapshots = [
        {"cycle_id": "c-1", "status": "in_flight", "current_phase": "sense",
         "phase_outputs_count": 1},
        {"cycle_id": "c-1", "status": "in_flight", "current_phase": "load",
         "phase_outputs_count": 2},
    ]
    snap_iter = iter(snapshots)

    def _fake_snapshot(*, matter_slug, triggered_by):
        try:
            return next(snap_iter)
        except StopIteration:
            return snapshots[-1]

    monkeypatch.setattr(mod, "_snapshot_cycle", _fake_snapshot)

    async def _fake_cycle(**_kw):
        # Cycle resolves quickly so polling exits
        await asyncio.sleep(0.05)
        return _FakeCycleResult()

    monkeypatch.setattr(
        "orchestrator.cortex_runner.maybe_run_cycle",
        _fake_cycle,
    )

    events = []
    async for chunk in stream_cycle_events(
        matter_slug="oskolkov",
        director_question="Smoke test SSE stream — preserves payload.",
        triggered_by="director_manual",
    ):
        # Parse SSE data line into JSON
        line = chunk.strip()
        assert line.startswith("data: ")
        events.append(json.loads(line[len("data: "):]))

    types = [e["type"] for e in events]
    assert types[0] == "started"
    assert "phase_changed" in types
    assert types[-1] == "terminal"
    terminal = events[-1]
    assert terminal["status"] == "proposed"
    assert terminal["cycle_id"] == "cycle-xyz"
    assert terminal["cost_dollars"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Test 7 — terminal=failed when maybe_run_cycle raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_cycle_events_terminal_failed_on_exception(monkeypatch):
    from outputs.cortex_run_stream import stream_cycle_events
    import outputs.cortex_run_stream as mod
    monkeypatch.setattr(mod, "POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(mod, "_snapshot_cycle", lambda **_: None)

    async def _raise(**_kw):
        await asyncio.sleep(0.01)
        raise RuntimeError("boom-from-runner")

    monkeypatch.setattr(
        "orchestrator.cortex_runner.maybe_run_cycle", _raise,
    )

    events = []
    async for chunk in stream_cycle_events(
        matter_slug="oskolkov",
        director_question="trigger a runner exception path",
        triggered_by="director_manual",
    ):
        events.append(json.loads(chunk.strip()[len("data: "):]))

    assert events[0]["type"] == "started"
    assert events[-1]["type"] == "terminal"
    assert events[-1]["status"] == "failed"
    assert "boom-from-runner" in events[-1]["error"]


# ---------------------------------------------------------------------------
# Test 8 — terminal=timeout on asyncio.TimeoutError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_cycle_events_terminal_timeout(monkeypatch):
    from outputs.cortex_run_stream import stream_cycle_events
    import outputs.cortex_run_stream as mod
    monkeypatch.setattr(mod, "POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(mod, "_snapshot_cycle", lambda **_: None)

    async def _timeout(**_kw):
        await asyncio.sleep(0.01)
        raise asyncio.TimeoutError()

    monkeypatch.setattr(
        "orchestrator.cortex_runner.maybe_run_cycle", _timeout,
    )

    events = []
    async for chunk in stream_cycle_events(
        matter_slug="oskolkov",
        director_question="trigger a timeout path here",
        triggered_by="director_manual",
    ):
        events.append(json.loads(chunk.strip()[len("data: "):]))

    assert events[-1]["type"] == "terminal"
    assert events[-1]["status"] == "timeout"
