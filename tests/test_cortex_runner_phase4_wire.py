"""Tests for orchestrator/cortex_runner.py Phase 4 wire-up — CORTEX_3T_FORMALIZE_1C.

Verifies that:
  * After Phase 3c success, _phase4_propose fires.
  * On Phase 4 success, status flips to 'tier_b_pending' and Phase 6
    archive is SKIPPED (Phase 5 owns the archive on the button-press path).
  * On Phase 4 failure, status='failed' and Phase 6 archive still runs.
  * On Phase 3 failure, Phase 4 does NOT fire (no synthesis to propose).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator import cortex_runner as runner


class _FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return None

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
        self.conns = []

    def _get_conn(self):
        c = _FakeConn()
        self.conns.append(c)
        return c

    def _put_conn(self, c):
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(runner, "_get_store", lambda: store)
    return store


@pytest.fixture
def stub_phase2(monkeypatch):
    async def _stub(matter_slug, days=14):
        return {"matter_config": "M", "vault_available": True}
    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _stub,
    )


@pytest.fixture
def stub_phase3(monkeypatch):
    behavior = {"3c_raise": None}

    async def _3a(**kw):
        return SimpleNamespace(
            summary="s", signal_classification="t",
            capabilities_to_invoke=[], reasoning_notes="r",
            cost_tokens=10, cost_dollars=0.001,
        )

    async def _3b(**kw):
        return SimpleNamespace(outputs=[], total_cost_tokens=10, total_cost_dollars=0.001)

    async def _3c(**kw):
        if behavior["3c_raise"]:
            raise behavior["3c_raise"]
        return SimpleNamespace(
            proposal_text="p", structured_actions=[],
            cost_tokens=10, cost_dollars=0.001,
        )

    monkeypatch.setattr("orchestrator.cortex_phase3_reasoner.run_phase3a_meta_reason", _3a)
    monkeypatch.setattr("orchestrator.cortex_phase3_invoker.run_phase3b_invocations", _3b)
    monkeypatch.setattr("orchestrator.cortex_phase3_synthesizer.run_phase3c_synthesize", _3c)
    return behavior


# --------------------------------------------------------------------------
# Successful Phase 4 path
# --------------------------------------------------------------------------


def test_phase4_fires_after_phase3_success(monkeypatch, fake_store, stub_phase2, stub_phase3):
    fired = []

    async def _phase4(cycle):
        fired.append(cycle.cycle_id)
        cycle.status = "tier_b_pending"
        cycle.proposal_id = "prop-1"
        return True

    monkeypatch.setattr(runner, "_phase4_propose", _phase4)
    cycle = asyncio.run(runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron"))
    assert fired == [cycle.cycle_id]
    assert cycle.status == "tier_b_pending"
    assert cycle.proposal_id == "prop-1"


def test_phase6_archive_skipped_on_phase4_success(monkeypatch, fake_store, stub_phase2, stub_phase3):
    """When Phase 4 posts the card, Phase 6 archive must NOT fire — Phase 5
    owns the archive on the button-press path."""
    archive_calls = []

    async def _phase4(cycle):
        cycle.status = "tier_b_pending"
        return True

    async def _phase6(cycle):
        archive_calls.append(cycle.cycle_id)

    monkeypatch.setattr(runner, "_phase4_propose", _phase4)
    monkeypatch.setattr(runner, "_phase6_archive", _phase6)
    asyncio.run(runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron"))
    assert archive_calls == []   # Phase 6 skipped


def test_phase6_archive_runs_when_phase4_returns_false(monkeypatch, fake_store, stub_phase2, stub_phase3):
    """Phase 4 returning falsy (e.g. test stub) → Phase 6 archive still runs."""
    archive_calls = []

    async def _phase4_noop(cycle):
        return False

    async def _phase6(cycle):
        archive_calls.append(cycle.cycle_id)

    monkeypatch.setattr(runner, "_phase4_propose", _phase4_noop)
    monkeypatch.setattr(runner, "_phase6_archive", _phase6)
    cycle = asyncio.run(runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron"))
    assert archive_calls == [cycle.cycle_id]


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


def test_phase4_failure_marks_status_failed_and_archives(monkeypatch, fake_store, stub_phase2, stub_phase3):
    archive_calls = []

    async def _phase4_boom(cycle):
        raise RuntimeError("Slack API down")

    async def _phase6(cycle):
        archive_calls.append(cycle.status)

    monkeypatch.setattr(runner, "_phase4_propose", _phase4_boom)
    monkeypatch.setattr(runner, "_phase6_archive", _phase6)
    cycle = asyncio.run(runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron"))
    assert cycle.status == "failed"
    assert "phase4_error" in (cycle.aborted_reason or "")
    assert archive_calls == ["failed"]


def test_phase4_does_not_fire_when_phase3_failed(monkeypatch, fake_store, stub_phase2, stub_phase3):
    fired = []

    async def _phase4(cycle):
        fired.append(cycle.cycle_id)
        cycle.status = "tier_b_pending"
        return True

    stub_phase3["3c_raise"] = RuntimeError("synthesis exploded")
    monkeypatch.setattr(runner, "_phase4_propose", _phase4)
    # Phase 3 catches its own exceptions (sets cycle.status='failed' without
    # re-raising) so the runner returns normally — Phase 4 must NOT have fired.
    cycle = asyncio.run(runner.maybe_run_cycle(matter_slug="movie", triggered_by="cron"))
    assert fired == []
    assert cycle.status == "failed"
    assert cycle.phase3c_result is None


def test_phase4_propose_helper_calls_run_phase4_propose(monkeypatch, fake_store):
    captured = {}

    async def _stub_run_phase4(*, cycle_id, matter_slug, phase3c_result):
        captured["cycle_id"] = cycle_id
        captured["matter_slug"] = matter_slug
        captured["p3c"] = phase3c_result
        return SimpleNamespace(proposal_id="prop-99")

    import orchestrator.cortex_phase4_proposal as p4
    monkeypatch.setattr(p4, "run_phase4_propose", _stub_run_phase4)
    cycle = runner.CortexCycle(
        cycle_id="cyc-1",
        matter_slug="oskolkov",
        triggered_by="director",
    )
    cycle.phase3c_result = SimpleNamespace(proposal_text="x", structured_actions=[])
    posted = asyncio.run(runner._phase4_propose(cycle))
    assert posted is True
    assert cycle.status == "tier_b_pending"
    assert cycle.proposal_id == "prop-99"
    assert captured["cycle_id"] == "cyc-1"
    assert captured["matter_slug"] == "oskolkov"
