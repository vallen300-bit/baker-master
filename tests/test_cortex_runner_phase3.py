"""Tests for orchestrator/cortex_runner.py — Phase 3 wiring (1B replacement
of the 1A awaiting_reason stub).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.

Distinct from test_cortex_runner_phase126.py: those cover Phase 1/2/6;
this module covers the new Phase 3 integration (signal_text plumbing,
3a→3b→3c invocation order, status transition + cost accumulation,
graceful handling of Phase 3 inner failures).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator import cortex_runner as runner


# --------------------------------------------------------------------------
# Shared captured-SQL stub harness (mirrors phase126 shape)
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple] = []

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

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

    def _put_conn(self, c):
        self.put_count += 1


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(runner, "_get_store", lambda: store)
    return store


@pytest.fixture
def stub_phase2_loader(monkeypatch):
    async def _stub(matter_slug, days=14):
        return {"matter_config": "MATTER_BRAIN", "vault_available": True}
    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _stub,
    )


@pytest.fixture
def stub_phase3(monkeypatch):
    """Stub the 3 Phase-3 entry points so the runner test doesn't need to
    re-test the inner modules. Each captures call kwargs + returns a
    deterministic SimpleNamespace mimicking the dataclass results."""
    captured = {"3a": [], "3b": [], "3c": []}
    behavior = {
        "3a_result": SimpleNamespace(
            summary="s", signal_classification="threat",
            capabilities_to_invoke=["legal"], reasoning_notes="r",
            cost_tokens=10, cost_dollars=0.001,
        ),
        "3b_result": SimpleNamespace(
            outputs=[SimpleNamespace(capability_slug="legal", success=True,
                                      output_text="advice", error=None,
                                      cost_tokens=20, cost_dollars=0.002)],
            total_cost_tokens=20, total_cost_dollars=0.002,
        ),
        "3c_result": SimpleNamespace(
            proposal_text="proposal", structured_actions=[],
            cost_tokens=30, cost_dollars=0.003,
        ),
        "3a_raise": None, "3b_raise": None, "3c_raise": None,
    }

    async def _3a(**kw):
        captured["3a"].append(kw)
        if behavior["3a_raise"]:
            raise behavior["3a_raise"]
        return behavior["3a_result"]

    async def _3b(**kw):
        captured["3b"].append(kw)
        if behavior["3b_raise"]:
            raise behavior["3b_raise"]
        return behavior["3b_result"]

    async def _3c(**kw):
        captured["3c"].append(kw)
        if behavior["3c_raise"]:
            raise behavior["3c_raise"]
        return behavior["3c_result"]

    monkeypatch.setattr(
        "orchestrator.cortex_phase3_reasoner.run_phase3a_meta_reason", _3a)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_invoker.run_phase3b_invocations", _3b)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_synthesizer.run_phase3c_synthesize", _3c)

    return captured, behavior


# ==========================================================================
# 1. Phase 3 wiring + status transition
# ==========================================================================


def test_phase3_runs_in_order_3a_3b_3c(fake_store, stub_phase2_loader, stub_phase3):
    captured, _ = stub_phase3
    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="oskolkov", triggered_by="director",
        director_question="signal text X",
    ))
    assert len(captured["3a"]) == 1
    assert len(captured["3b"]) == 1
    assert len(captured["3c"]) == 1
    assert cycle.status == "proposed"


def test_phase3_success_status_proposed(fake_store, stub_phase2_loader, stub_phase3):
    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="movie", triggered_by="cron",
    ))
    assert cycle.status == "proposed"
    assert cycle.current_phase == "archive"


# ==========================================================================
# 2. Cost accumulation across 3a + 3b + 3c
# ==========================================================================


def test_cost_accumulates_across_phase3(fake_store, stub_phase2_loader, stub_phase3):
    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="oskolkov", triggered_by="director",
        director_question="x",
    ))
    # 3a: 10 + 3b: 20 + 3c: 30 = 60 tokens
    assert cycle.cost_tokens == 60
    assert cycle.cost_dollars == pytest.approx(0.001 + 0.002 + 0.003)


# ==========================================================================
# 3. signal_text plumbing
# ==========================================================================


def test_signal_text_threaded_from_director_question(
    fake_store, stub_phase2_loader, stub_phase3,
):
    captured, _ = stub_phase3
    asyncio.run(runner.maybe_run_cycle(
        matter_slug="oskolkov", triggered_by="director",
        director_question="please analyze this offer",
    ))
    # All three Phase-3 calls receive signal_text=director_question
    for phase_kw in (captured["3a"][0], captured["3b"][0], captured["3c"][0]):
        assert phase_kw.get("signal_text") == "please analyze this offer"


def test_signal_text_empty_string_when_no_director_question(
    fake_store, stub_phase2_loader, stub_phase3,
):
    captured, _ = stub_phase3
    asyncio.run(runner.maybe_run_cycle(
        matter_slug="oskolkov", triggered_by="signal", trigger_signal_id=42,
    ))
    assert captured["3a"][0]["signal_text"] == ""


def test_signal_text_in_phase2_load_context(
    fake_store, stub_phase2_loader, stub_phase3,
):
    """Phase 3 receives the full phase2_load_context with signal_text key."""
    captured, _ = stub_phase3
    asyncio.run(runner.maybe_run_cycle(
        matter_slug="oskolkov", triggered_by="director",
        director_question="hi",
    ))
    ctx = captured["3a"][0]["phase2_context"]
    assert ctx.get("signal_text") == "hi"
    assert ctx.get("matter_config") == "MATTER_BRAIN"


# ==========================================================================
# 4. Phase 3 inner failure → status='failed', no exception
# ==========================================================================


def test_phase3a_failure_marks_status_failed_no_raise(
    fake_store, stub_phase2_loader, stub_phase3,
):
    """Phase 3 catches its own exceptions and sets status='failed' without
    re-raising. The cycle still completes (Phase 6 archives)."""
    _, behavior = stub_phase3
    behavior["3a_raise"] = RuntimeError("anthropic 503")

    # Should NOT raise
    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    assert cycle.status == "failed"
    assert "phase3_error" in (cycle.aborted_reason or "")


def test_phase3c_failure_marks_status_failed(
    fake_store, stub_phase2_loader, stub_phase3,
):
    _, behavior = stub_phase3
    behavior["3c_raise"] = RuntimeError("synth DB write failed")

    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    assert cycle.status == "failed"


def test_phase6_archive_runs_even_on_phase3_failure(
    fake_store, stub_phase2_loader, stub_phase3,
):
    """Quality Checkpoint #10: Phase 6 ALWAYS runs."""
    _, behavior = stub_phase3
    behavior["3b_raise"] = RuntimeError("3b explosion")

    asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    # Search every captured query — Phase 6 archive INSERT should be there
    sql_blob = " | ".join(
        q[0] for c in fake_store.conns for q in c.cur.queries
    )
    assert "'archive', 6, 'cycle_archive'" in sql_blob


# ==========================================================================
# 5. Capabilities-to-invoke threaded into 3b
# ==========================================================================


def test_3a_capabilities_to_invoke_passed_to_3b(
    fake_store, stub_phase2_loader, stub_phase3,
):
    captured, behavior = stub_phase3
    behavior["3a_result"] = SimpleNamespace(
        summary="", signal_classification="other",
        capabilities_to_invoke=["legal", "finance"], reasoning_notes="",
        cost_tokens=0, cost_dollars=0.0,
    )
    asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    assert captured["3b"][0]["capabilities_to_invoke"] == ["legal", "finance"]


def test_3a_and_3b_results_threaded_into_3c(
    fake_store, stub_phase2_loader, stub_phase3,
):
    captured, behavior = stub_phase3
    asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    assert captured["3c"][0]["phase3a_result"] is behavior["3a_result"]
    assert captured["3c"][0]["phase3b_result"] is behavior["3b_result"]


# ==========================================================================
# 6. Cycle ID propagated to Phase 3 calls
# ==========================================================================


def test_cycle_id_propagated_to_all_phase3_calls(
    fake_store, stub_phase2_loader, stub_phase3,
):
    captured, _ = stub_phase3
    cycle = asyncio.run(runner.maybe_run_cycle(
        matter_slug="x", triggered_by="director",
    ))
    assert captured["3a"][0]["cycle_id"] == cycle.cycle_id
    assert captured["3b"][0]["cycle_id"] == cycle.cycle_id
    assert captured["3c"][0]["cycle_id"] == cycle.cycle_id
