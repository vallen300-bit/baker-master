"""Tests for orchestrator/cortex_runner.py — Phase 1 (sense), Phase 2 (load),
and Phase 6 (archive) coverage for sub-brief CORTEX_3T_FORMALIZE_1A.

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md``.

Test strategy: fixture-only (no live DB) using captured-SQL stubs in the
shape of ``tests/test_capability_threads.py``. SQL-assertion tests
(Lesson #42 cousin) verify the EXACT canonical column names and table
references make it into the queries — fixture-only tests don't catch
schema drift, but SQL-assertion tests do.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from orchestrator import cortex_runner as runner


# --------------------------------------------------------------------------
# Captured-SQL stub harness
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple] = []  # list[(sql, params)]
        self._rows = []
        self.rowcount = 1

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self):
        self.conns: list[_FakeConn] = []
        self.put_count = 0

    def _get_conn(self):
        c = _FakeConn()
        self.conns.append(c)
        return c

    def _put_conn(self, conn):
        self.put_count += 1


@pytest.fixture
def fake_store(monkeypatch):
    """Replace runner._get_store and loaders' SentinelStoreBack._get_global_instance
    with a captured-SQL fake."""
    store = _FakeStore()
    monkeypatch.setattr(runner, "_get_store", lambda: store)
    return store


@pytest.fixture
def stub_phase2_loader(monkeypatch):
    """Default Phase 2 to a no-op returning a dict — overridden per test."""
    async def _stub(matter_slug: str, days: int = 14):
        return {"matter_config": "", "vault_available": False}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context",
        _stub,
    )
    return _stub


@pytest.fixture(autouse=True)
def _stub_phase3(monkeypatch, request):
    """1B autouse: stub the 3 Phase-3 entry points + their store helpers.

    Without this, the 1A-scope tests would hit the real anthropic client
    + the real SentinelStoreBack (which transitively tries to init voyageai
    in CI). We replace the entry points with deterministic no-ops so the
    runner-level tests can verify Phase 6 archive + status transitions
    without needing to re-test the inner Phase 3 modules.
    """
    # Skip if test explicitly opts out (none in this file currently)
    if "no_phase3_stub" in request.keywords:
        yield
        return

    from types import SimpleNamespace

    async def _3a(**kw):
        return SimpleNamespace(
            summary="", signal_classification="other",
            capabilities_to_invoke=[], reasoning_notes="",
            cost_tokens=0, cost_dollars=0.0,
        )

    async def _3b(**kw):
        return SimpleNamespace(
            outputs=[], total_cost_tokens=0, total_cost_dollars=0.0,
        )

    async def _3c(**kw):
        return SimpleNamespace(
            proposal_text="", structured_actions=[],
            cost_tokens=0, cost_dollars=0.0,
        )

    monkeypatch.setattr(
        "orchestrator.cortex_phase3_reasoner.run_phase3a_meta_reason", _3a)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_invoker.run_phase3b_invocations", _3b)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_synthesizer.run_phase3c_synthesize", _3c)

    # 1C wired Phase 4 into the cycle. Phase-1/2/6-isolation tests stub it
    # to a no-op so they keep their original 1A/1B-shape assertions
    # (status='proposed' after Phase 3c, archive runs as before).
    async def _phase4_noop(cycle):
        return False

    monkeypatch.setattr(runner, "_phase4_propose", _phase4_noop)
    yield


def _all_sql(store: _FakeStore) -> str:
    """Concatenate every SQL string captured across every conn into one blob."""
    return " | ".join(q[0] for c in store.conns for q in c.cur.queries)


def _all_params(store: _FakeStore) -> list:
    """Flatten every params tuple across every conn."""
    out = []
    for c in store.conns:
        for q in c.cur.queries:
            out.append(q[1])
    return out


# ==========================================================================
# 1. Cycle skeleton + happy path
# ==========================================================================


def test_cycle_id_is_uuid(fake_store, stub_phase2_loader):
    cycle = asyncio.run(
        runner.maybe_run_cycle(
            matter_slug="oskolkov",
            triggered_by="director",
        )
    )
    uuid.UUID(cycle.cycle_id)  # raises if not a valid UUID
    assert cycle.matter_slug == "oskolkov"
    assert cycle.triggered_by == "director"


def test_status_terminates_at_proposed_in_1b_scope(fake_store, stub_phase2_loader):
    """1B: Phase 3 runs — status flips to 'proposed' after 3c synthesis.

    Was 'awaiting_reason' under 1A; with 1B's reasoning Phase wired in,
    the cycle now reaches 'proposed' (or 'failed' on Phase 3 exception).
    """
    cycle = asyncio.run(
        runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron")
    )
    assert cycle.status == "proposed"
    assert cycle.current_phase == "archive"  # final phase before return


# ==========================================================================
# 2. Phase 1 — sense
# ==========================================================================


def test_phase1_inserts_cycle_row(fake_store, stub_phase2_loader):
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="signal"))
    sql = _all_sql(fake_store)
    assert "INSERT INTO cortex_cycles" in sql
    assert "matter_slug" in sql
    assert "triggered_by" in sql


def test_phase1_inserts_sense_artifact_with_correct_phase(fake_store, stub_phase2_loader):
    """SQL-assertion (Lesson #42): the phase='sense' artifact row exists."""
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="signal"))
    sql = _all_sql(fake_store)
    assert "INSERT INTO cortex_phase_outputs" in sql
    assert "'sense', 1, 'cycle_init'" in sql


def test_phase1_payload_is_valid_json(fake_store, stub_phase2_loader):
    """Brief snippet had string-interp injection risk; verify json.dumps used."""
    asyncio.run(runner.maybe_run_cycle(
        matter_slug='trick"matter', triggered_by="signal",
    ))
    # Locate the params for the sense INSERT
    sense_payload = None
    for params in _all_params(fake_store):
        if params and isinstance(params, tuple):
            for v in params:
                if isinstance(v, str) and v.startswith("{") and "matter_slug" in v:
                    sense_payload = v
                    break
    assert sense_payload is not None
    # Round-trip through json — would raise if injection broke quoting
    parsed = json.loads(sense_payload)
    assert parsed["matter_slug"] == 'trick"matter'


# ==========================================================================
# 3. Phase 2 — load
# ==========================================================================


def test_phase2_calls_load_phase2_context_with_matter_slug(fake_store, monkeypatch):
    received = {}

    async def _capture(matter_slug, days=14):
        received["matter_slug"] = matter_slug
        received["days"] = days
        return {"matter_config": "abc"}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _capture
    )
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))
    assert received["matter_slug"] == "oskolkov"


def test_phase2_inserts_phase2_context_artifact(fake_store, stub_phase2_loader):
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))
    sql = _all_sql(fake_store)
    assert "'load', 2, 'phase2_context'" in sql


def test_phase2_updates_last_loaded_at(fake_store, stub_phase2_loader):
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))
    sql = _all_sql(fake_store)
    assert "UPDATE cortex_cycles" in sql
    assert "last_loaded_at=NOW()" in sql


def test_phase2_loader_returned_dict_persists_in_cycle_state(fake_store, monkeypatch):
    """Ensure the loader's return value is captured on the CortexCycle dataclass."""
    async def _ctx(matter_slug, days=14):
        return {"matter_config": "MATTER_CFG", "state": "STATE"}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _ctx
    )
    cycle = asyncio.run(
        runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron")
    )
    assert cycle.phase2_load_context["matter_config"] == "MATTER_CFG"


# ==========================================================================
# 4. Phase 6 — archive (always runs, even on failure)
# ==========================================================================


def test_phase6_writes_archive_artifact(fake_store, stub_phase2_loader):
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))
    sql = _all_sql(fake_store)
    assert "'archive', 6, 'cycle_archive'" in sql


def test_phase6_sets_completed_at_and_final_status(fake_store, stub_phase2_loader):
    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))
    sql = _all_sql(fake_store)
    # Phase 6 UPDATE references completed_at + status
    assert "completed_at=NOW()" in sql
    assert "current_phase='archive'" in sql


def test_phase6_archive_runs_even_when_phase2_fails(fake_store, monkeypatch):
    """Quality Checkpoint #10: Phase 6 ALWAYS runs even when an earlier phase raises."""
    async def _boom(matter_slug, days=14):
        raise RuntimeError("phase 2 explosion")

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _boom
    )

    with pytest.raises(RuntimeError):
        asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))

    sql = _all_sql(fake_store)
    # Phase 6 archive artifact STILL written despite Phase 2 fail
    assert "'archive', 6, 'cycle_archive'" in sql


def test_failed_cycle_marks_status_failed_in_archive(fake_store, monkeypatch):
    async def _boom(matter_slug, days=14):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _boom
    )

    with pytest.raises(RuntimeError):
        asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron"))

    # Find the Phase 6 UPDATE — its params should carry status='failed'
    found_failed = False
    for params in _all_params(fake_store):
        if params and isinstance(params, tuple) and "failed" in params:
            found_failed = True
            break
    assert found_failed, "Phase 6 UPDATE should set status='failed' on cycle failure"


def test_phase1_db_failure_rolls_back_and_propagates(monkeypatch):
    """Phase 1 INSERT failure → rollback called, archive still fires."""
    class _RaisingCursor(_FakeCursor):
        def execute(self, q, params=None):
            super().execute(q, params)
            if "INSERT INTO cortex_cycles" in q:
                raise RuntimeError("db down")

    class _RaisingConn(_FakeConn):
        def cursor(self):
            self.cur = _RaisingCursor()
            return self.cur

    class _RaisingStore(_FakeStore):
        def _get_conn(self):
            c = _RaisingConn()
            self.conns.append(c)
            return c

    store = _RaisingStore()
    monkeypatch.setattr(runner, "_get_store", lambda: store)

    async def _stub(matter_slug, days=14):
        return {}
    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _stub
    )

    with pytest.raises(RuntimeError):
        asyncio.run(
            runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="signal")
        )
    # Phase 1's conn should have been rolled back
    assert any(c.rolled_back for c in store.conns)


# ==========================================================================
# 5. 5-minute absolute timeout
# ==========================================================================


def test_short_timeout_aborts_long_running_phase(fake_store, monkeypatch):
    """Verification #6: 5-min absolute timeout fires asyncio.TimeoutError when
    the inner cycle exceeds CORTEX_CYCLE_TIMEOUT_SECONDS.

    We simulate by overriding the constant to 0.05s and stubbing Phase 2 to
    sleep 1s.
    """
    monkeypatch.setattr(runner, "CYCLE_TIMEOUT_SECONDS", 0)  # immediate timeout

    async def _slow(matter_slug, days=14):
        await asyncio.sleep(1.0)
        return {}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _slow
    )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="cron")
        )


def test_timeout_marks_existing_cycle_failed(fake_store, monkeypatch):
    """When Phase 2 hangs and timeout fires AFTER Phase 1's INSERT committed,
    the timeout handler issues an UPDATE...status='failed' for in-flight rows.
    """
    monkeypatch.setattr(runner, "CYCLE_TIMEOUT_SECONDS", 0)

    async def _slow(matter_slug, days=14):
        await asyncio.sleep(1.0)
        return {}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _slow
    )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            runner.maybe_run_cycle(
                matter_slug="oskolkov",
                triggered_by="cron",
                trigger_signal_id=42,
            )
        )

    sql = _all_sql(fake_store)
    # Best-effort recovery query MUST emit an UPDATE that sets status='failed'
    assert "UPDATE cortex_cycles SET status='failed'" in sql
