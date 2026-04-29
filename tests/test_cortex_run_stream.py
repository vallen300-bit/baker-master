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
9. F-1 fix — _snapshot_cycle disambiguates concurrent taps via since_ts
10. F-1 fix — stream_cycle_events isolates concurrent runs by sse_anchor
"""
from __future__ import annotations

import asyncio
import datetime
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

    def _fake_snapshot(*, matter_slug, triggered_by, since_ts=None):
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


# ---------------------------------------------------------------------------
# F-1 FIX (PR #88 AI Head B re-review)
# Test 9 — _snapshot_cycle disambiguates concurrent same-trigger taps via
# since_ts. The fake cursor inspects the executed SQL + params and serves
# the appropriate "row" so we don't need a live PG instance to prove the
# disambiguation logic works end-to-end.
# ---------------------------------------------------------------------------


class _DisambiguationCursor:
    """Cursor stand-in that responds to _snapshot_cycle SQL by selecting
    among 2 fake cycle rows based on the WHERE clause + ORDER BY.

    Models two cortex_cycles rows for the same (matter_slug, triggered_by)
    started 1s apart:
        cycle_a started_at = T0
        cycle_b started_at = T0 + 1s
    """

    T0 = datetime.datetime(2026, 4, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)
    CYCLE_A_ID = "aaaaaaaa-1111-2222-3333-444444444444"
    CYCLE_B_ID = "bbbbbbbb-5555-6666-7777-888888888888"

    def __init__(self):
        self._last_sql = None
        self._last_params = None
        self._rows_to_serve: list = []

    def execute(self, sql, params=None):
        self._last_sql = sql
        self._last_params = params

        if "FROM cortex_cycles" in sql:
            # _snapshot_cycle SQL — select cycle row based on filters
            since_ts = None
            ascending = "ORDER BY started_at ASC" in sql
            if "AND started_at >= %s" in sql:
                since_ts = params[2]

            cycle_a = (self.CYCLE_A_ID, "in_flight", "load", self.T0)
            cycle_b = (
                self.CYCLE_B_ID,
                "in_flight",
                "sense",
                self.T0 + datetime.timedelta(seconds=1),
            )
            candidates = [cycle_a, cycle_b]

            if since_ts is not None:
                candidates = [c for c in candidates if c[3] >= since_ts]

            if not candidates:
                self._rows_to_serve = [None]
                return

            if ascending:
                candidates.sort(key=lambda r: r[3])
            else:
                candidates.sort(key=lambda r: r[3], reverse=True)

            picked = candidates[0]
            # Strip started_at (4th col) — query only selects 3 cols
            self._rows_to_serve = [picked[:3]]
        elif "FROM cortex_phase_outputs" in sql:
            # phase_outputs_count query
            self._rows_to_serve = [(7,)]
        else:
            self._rows_to_serve = [None]

    def fetchone(self):
        if not self._rows_to_serve:
            return None
        return self._rows_to_serve.pop(0)

    def close(self):
        pass


class _DisambiguationConn:
    def __init__(self):
        self._cursor = _DisambiguationCursor()

    def cursor(self):
        return self._cursor

    def rollback(self):
        pass


def test_snapshot_cycle_disambiguates_concurrent_taps(monkeypatch):
    """F-1: with two cycles on same (matter, trigger) 1s apart:
       - since_ts before both → returns oldest (cycle_a)
       - since_ts between them → returns cycle_b (only candidate ≥ anchor)
       - since_ts=None → backward-compat: returns latest by DESC (cycle_b)
    """
    from outputs.cortex_run_stream import _snapshot_cycle
    import outputs.cortex_run_stream as mod

    conn = _DisambiguationConn()
    monkeypatch.setattr(mod, "_get_store", lambda: _FakeStore(conn))

    T0 = _DisambiguationCursor.T0
    A = _DisambiguationCursor.CYCLE_A_ID
    B = _DisambiguationCursor.CYCLE_B_ID

    # Anchor 1s before cycle_a → both cycles are eligible; ASC → oldest = cycle_a
    snap_a = _snapshot_cycle(
        matter_slug="oskolkov",
        triggered_by="director_manual",
        since_ts=T0 - datetime.timedelta(seconds=1),
    )
    assert snap_a is not None
    assert snap_a["cycle_id"] == A
    assert snap_a["current_phase"] == "load"

    # Anchor 0.5s after cycle_a → cycle_a filtered out; only cycle_b matches
    snap_b = _snapshot_cycle(
        matter_slug="oskolkov",
        triggered_by="director_manual",
        since_ts=T0 + datetime.timedelta(milliseconds=500),
    )
    assert snap_b is not None
    assert snap_b["cycle_id"] == B
    assert snap_b["current_phase"] == "sense"

    # Backward compat — since_ts=None → DESC → latest cycle (cycle_b)
    snap_legacy = _snapshot_cycle(
        matter_slug="oskolkov",
        triggered_by="director_manual",
        since_ts=None,
    )
    assert snap_legacy is not None
    assert snap_legacy["cycle_id"] == B


# ---------------------------------------------------------------------------
# Test 10 — stream_cycle_events isolates concurrent runs via sse_anchor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_cycle_events_concurrent_isolation(monkeypatch):
    """F-1: two stream_cycle_events generators run concurrently. The fake
    snapshot mirrors the disambiguation logic — given a since_ts, return
    the oldest cycle that started ≥ that anchor. Each stream must see
    ONLY its own cycle_id in phase_changed events, never the sibling's.
    """
    from outputs.cortex_run_stream import stream_cycle_events
    import outputs.cortex_run_stream as mod

    monkeypatch.setattr(mod, "POLL_INTERVAL_SECONDS", 0.005)
    # Shrink the SSE anchor slack so the unit test can stage two
    # concurrent streams without a 2s real-time wait. Production keeps
    # 2s to absorb create_task → Phase 1 INSERT latency.
    monkeypatch.setattr(mod, "SSE_ANCHOR_SLACK_SECONDS", 0.01)

    # Cycle A is created when stream A starts; cycle B is created when
    # stream B starts (anchored later). Each cycle has its own row in
    # the fake DB; the snapshot helper picks based on since_ts.
    cycle_rows = []  # list of (cycle_id, started_at, current_phase)

    async def _fake_cycle_a(**_kw):
        # Insert row "A" right after the test starts stream A
        cycle_rows.append((
            "cycle-A",
            datetime.datetime.now(datetime.timezone.utc),
            "sense",
        ))
        await asyncio.sleep(0.05)
        # Bump phase
        if cycle_rows:
            old = cycle_rows[0]
            cycle_rows[0] = (old[0], old[1], "load")
        await asyncio.sleep(0.05)
        result = _FakeCycleResult()
        result.cycle_id = "cycle-A"
        return result

    async def _fake_cycle_b(**_kw):
        cycle_rows.append((
            "cycle-B",
            datetime.datetime.now(datetime.timezone.utc),
            "sense",
        ))
        await asyncio.sleep(0.05)
        if len(cycle_rows) >= 2:
            old = cycle_rows[1]
            cycle_rows[1] = (old[0], old[1], "load")
        await asyncio.sleep(0.05)
        result = _FakeCycleResult()
        result.cycle_id = "cycle-B"
        return result

    def _fake_snapshot(*, matter_slug, triggered_by, since_ts=None):
        if not cycle_rows:
            return None
        if since_ts is None:
            picked = max(cycle_rows, key=lambda r: r[1])
        else:
            candidates = [r for r in cycle_rows if r[1] >= since_ts]
            if not candidates:
                return None
            picked = min(candidates, key=lambda r: r[1])
        return {
            "cycle_id": picked[0],
            "status": "in_flight",
            "current_phase": picked[2],
            "phase_outputs_count": 1,
        }

    monkeypatch.setattr(mod, "_snapshot_cycle", _fake_snapshot)

    async def _collect(matter, question, triggered_by, runner):
        monkeypatch.setattr(
            "orchestrator.cortex_runner.maybe_run_cycle", runner,
        )
        out = []
        async for chunk in stream_cycle_events(
            matter_slug=matter,
            director_question=question,
            triggered_by=triggered_by,
        ):
            out.append(json.loads(chunk.strip()[len("data: "):]))
        return out

    # Run stream A first; let it spawn cycle A. Then 0.05s later start
    # stream B — its sse_anchor will be after cycle_A's started_at, so
    # the disambiguation query MUST exclude cycle_A even though it's
    # also a director_manual cycle on the same matter.
    monkeypatch.setattr(
        "orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle_a,
    )
    task_a = asyncio.create_task(
        _collect(
            "oskolkov",
            "stream A — first tap",
            "director_manual",
            _fake_cycle_a,
        )
    )

    # Small gap so cycle_A's row lands BEFORE stream_B captures sse_anchor
    await asyncio.sleep(0.02)

    monkeypatch.setattr(
        "orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle_b,
    )
    task_b = asyncio.create_task(
        _collect(
            "oskolkov",
            "stream B — second tap",
            "director_manual",
            _fake_cycle_b,
        )
    )

    events_a, events_b = await asyncio.gather(task_a, task_b)

    # Each stream's phase_changed events MUST reference only its own cycle_id
    a_phase_cycle_ids = {
        e.get("cycle_id") for e in events_a if e.get("type") == "phase_changed"
    }
    b_phase_cycle_ids = {
        e.get("cycle_id") for e in events_b if e.get("type") == "phase_changed"
    }

    assert a_phase_cycle_ids == {"cycle-A"}, (
        f"stream A leaked sibling cycle_ids: {a_phase_cycle_ids}"
    )
    assert b_phase_cycle_ids == {"cycle-B"}, (
        f"stream B leaked sibling cycle_ids: {b_phase_cycle_ids}"
    )
