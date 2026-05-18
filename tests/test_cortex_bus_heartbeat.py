"""Tests for Cortex phase-boundary bus heartbeat to brisen-lab.

Brief: ``briefs/BRIEF_BAKER_CORTEX_BUS_HEARTBEAT_1.md`` (Fix #1 of cortex-card-fixes).

Coverage:
  1. _emit_cortex_heartbeat — correct topic + headers + body for a phase
  2. _emit_cortex_heartbeat — swallows httpx connect errors (no raise)
  3. _emit_cortex_heartbeat — swallows timeouts (no raise)
  4. _emit_cortex_heartbeat — skips when BRISEN_LAB_TERMINAL_KEY_CORTEX unset
  5. run_cycle — emits all five phase heartbeats + ratify-required on happy path
  6. run_cycle — emits failed heartbeat on outer-block exception
  7. run_cycle — continues when heartbeat helper itself raises (belt-and-suspenders)
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from orchestrator import cortex_runner as runner


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def cycle():
    """Minimal CortexCycle fixture suitable for helper-level tests."""
    c = runner.CortexCycle(
        cycle_id="cycle-test-1234",
        matter_slug="oskolkov",
        triggered_by="test",
    )
    return c


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv("BRISEN_LAB_TERMINAL_KEY_CORTEX", "test-cortex-key")
    monkeypatch.setenv("BRISEN_LAB_URL", "https://brisen-lab.test")
    return None


class _RecorderClient:
    """Captures the first POST call. Stand-in for httpx.AsyncClient."""

    captured: dict = {}

    def __init__(self, *a, **kw):
        type(self).init_kwargs = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).captured = {"url": url, "headers": headers or {}, "json": json or {}}
        return SimpleNamespace(status_code=200)


@pytest.fixture
def recorder_httpx(monkeypatch):
    """Replace httpx.AsyncClient inside runner with a recorder."""
    _RecorderClient.captured = {}
    _RecorderClient.init_kwargs = {}
    monkeypatch.setattr("httpx.AsyncClient", _RecorderClient)
    return _RecorderClient


# --------------------------------------------------------------------------
# 1. _emit_cortex_heartbeat: correct topic, headers, body
# --------------------------------------------------------------------------


def test_emit_cortex_heartbeat_posts_correct_topic(cycle, key_env, recorder_httpx):
    asyncio.run(runner._emit_cortex_heartbeat(cycle, "sense", "ok"))

    captured = recorder_httpx.captured
    assert captured["url"] == "https://brisen-lab.test/msg/"
    assert captured["headers"]["X-Terminal-Key"] == "test-cortex-key"
    assert captured["headers"]["Content-Type"] == "application/json"

    body = captured["json"]
    assert body["from_terminal"] == "cortex"
    assert body["to_terminals"] == ["lead"]
    assert body["topic"] == "cortex/oskolkov/cycle-phase/sense"
    assert body["kind"] == "heartbeat"
    assert "cycle_id=cycle-test-1234" in body["body"]
    assert "matter=oskolkov" in body["body"]
    assert "phase=sense" in body["body"]
    assert "status=ok" in body["body"]


# --------------------------------------------------------------------------
# 2. _emit_cortex_heartbeat: swallows ConnectError
# --------------------------------------------------------------------------


class _RaisingClient:
    """httpx.AsyncClient stand-in that raises a given exception from .post()."""

    exc_to_raise: BaseException | None = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **kw):
        if type(self).exc_to_raise is not None:
            raise type(self).exc_to_raise


@pytest.fixture
def raising_httpx(monkeypatch):
    def _set(exc):
        _RaisingClient.exc_to_raise = exc
        monkeypatch.setattr("httpx.AsyncClient", _RaisingClient)
    return _set


def test_emit_cortex_heartbeat_swallows_http_errors(cycle, key_env, raising_httpx, caplog):
    raising_httpx(httpx.ConnectError("nope"))
    with caplog.at_level(logging.WARNING, logger="orchestrator.cortex_runner"):
        result = asyncio.run(runner._emit_cortex_heartbeat(cycle, "sense", "ok"))
    assert result is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        getattr(r, "error_class", "") == "ConnectError" for r in warns
    ), f"warning with error_class=ConnectError not found in {[r.message for r in warns]}"


# --------------------------------------------------------------------------
# 3. _emit_cortex_heartbeat: swallows asyncio.TimeoutError
# --------------------------------------------------------------------------


def test_emit_cortex_heartbeat_swallows_timeout(cycle, key_env, raising_httpx, caplog):
    raising_httpx(asyncio.TimeoutError())
    with caplog.at_level(logging.WARNING, logger="orchestrator.cortex_runner"):
        result = asyncio.run(runner._emit_cortex_heartbeat(cycle, "load", "ok"))
    assert result is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        getattr(r, "error_class", "") == "TimeoutError" for r in warns
    ), f"warning with error_class=TimeoutError not found"


# --------------------------------------------------------------------------
# 4. _emit_cortex_heartbeat: skips entirely when env key missing
# --------------------------------------------------------------------------


def test_emit_cortex_heartbeat_skips_when_key_missing(cycle, monkeypatch, caplog):
    monkeypatch.delenv("BRISEN_LAB_TERMINAL_KEY_CORTEX", raising=False)

    called = {"flag": False}

    class _ShouldNotBeCalled:
        def __init__(self, *a, **kw):
            called["flag"] = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **kw):
            called["flag"] = True

    monkeypatch.setattr("httpx.AsyncClient", _ShouldNotBeCalled)

    with caplog.at_level(logging.WARNING, logger="orchestrator.cortex_runner"):
        result = asyncio.run(runner._emit_cortex_heartbeat(cycle, "sense", "ok"))

    assert result is None
    assert called["flag"] is False, "httpx.AsyncClient must NOT be instantiated when key missing"
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        getattr(r, "error_class", "") == "MissingKey" for r in warns
    ), "warning with error_class=MissingKey expected when env var unset"


# --------------------------------------------------------------------------
# Cycle-level fixtures
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries = []
        self.rowcount = 1

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

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def __init__(self):
        self.conns = []

    def _get_conn(self):
        c = _FakeConn()
        self.conns.append(c)
        return c

    def _put_conn(self, conn):
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(runner, "_get_store", lambda: store)
    return store


@pytest.fixture
def stub_phase2(monkeypatch):
    async def _stub(matter_slug, days=14):
        return {"matter_config": "", "vault_available": False}

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _stub
    )


@pytest.fixture
def stub_phase3(monkeypatch):
    async def _3a(**kw):
        return SimpleNamespace(
            summary="", signal_classification="other",
            capabilities_to_invoke=[], reasoning_notes="",
            cost_tokens=0, cost_dollars=0.0,
        )

    async def _3b(**kw):
        return SimpleNamespace(outputs=[], total_cost_tokens=0, total_cost_dollars=0.0)

    async def _3c(**kw):
        return SimpleNamespace(
            proposal_text="Short summary of the proposal.",
            structured_actions=[], cost_tokens=0, cost_dollars=0.0,
        )

    monkeypatch.setattr(
        "orchestrator.cortex_phase3_reasoner.run_phase3a_meta_reason", _3a)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_invoker.run_phase3b_invocations", _3b)
    monkeypatch.setattr(
        "orchestrator.cortex_phase3_synthesizer.run_phase3c_synthesize", _3c)


# --------------------------------------------------------------------------
# 5. run_cycle: 5 phase heartbeats + 1 ratify-required on happy path
# --------------------------------------------------------------------------


def test_run_cycle_emits_all_five_phase_heartbeats_on_happy_path(
    fake_store, stub_phase2, stub_phase3, monkeypatch
):
    """Happy path: phase4 succeeds AND the unconditional archive emit fires.

    Brief Change 2 mandates phase-boundary emits at every transition. To make
    the lab card semantics symmetric ("cycle finalized" always fires), the
    archive heartbeat fires in the finally block whether Phase 6 actually
    ran or was skipped (proposal_card_posted=True path).
    """
    # Phase 4 succeeds — flips status to tier_b_pending + returns True.
    async def _phase4_ok(cycle):
        cycle.proposal_id = "prop-123"
        cycle.status = "tier_b_pending"
        return True

    monkeypatch.setattr(runner, "_phase4_propose", _phase4_ok)

    heartbeat_calls = []
    ratify_calls = []

    async def _record_hb(cycle, phase, status):
        heartbeat_calls.append((phase, status))

    async def _record_ratify(cycle):
        ratify_calls.append(cycle.cycle_id)

    monkeypatch.setattr(runner, "_emit_cortex_heartbeat", _record_hb)
    monkeypatch.setattr(runner, "_emit_cortex_ratify_required", _record_ratify)

    asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="test"))

    phases_in_order = [c[0] for c in heartbeat_calls]
    assert phases_in_order == ["sense", "load", "reason", "propose", "archive"], (
        f"expected 5 phase heartbeats in order; got {phases_in_order}"
    )
    assert heartbeat_calls[0] == ("sense", "ok")
    assert heartbeat_calls[1] == ("load", "ok")
    assert heartbeat_calls[2] == ("reason", "proposed")
    assert heartbeat_calls[3] == ("propose", "tier_b_pending")
    assert heartbeat_calls[4] == ("archive", "tier_b_pending")
    assert len(ratify_calls) == 1


# --------------------------------------------------------------------------
# 6. run_cycle: emits failed heartbeat on outer exception
# --------------------------------------------------------------------------


def test_run_cycle_emits_failed_heartbeat_on_outer_exception(
    fake_store, stub_phase3, monkeypatch
):
    """Phase 2 raises → outer except emits a `failed` heartbeat with
    current_phase=`load`. Then the finally still fires `archive` (status=failed).
    """
    async def _phase2_boom(matter_slug, days=14):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "orchestrator.cortex_phase2_loaders.load_phase2_context", _phase2_boom
    )

    heartbeat_calls = []

    async def _record_hb(cycle, phase, status):
        heartbeat_calls.append((phase, status))

    monkeypatch.setattr(runner, "_emit_cortex_heartbeat", _record_hb)

    with pytest.raises(RuntimeError):
        asyncio.run(runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="test"))

    assert heartbeat_calls[0] == ("sense", "ok")
    # The outer-except emit carries phase=cycle.current_phase ("load") + status="failed".
    assert ("load", "failed") in heartbeat_calls, (
        f"expected failed heartbeat with phase=load; got {heartbeat_calls}"
    )
    # Trailing archive emit fires from the finally block.
    assert heartbeat_calls[-1][0] == "archive"
    assert heartbeat_calls[-1][1] == "failed"


# --------------------------------------------------------------------------
# 7. run_cycle: cycle completes when heartbeat helper raises (belt-and-suspenders)
# --------------------------------------------------------------------------


def test_run_cycle_continues_when_heartbeat_raises(
    fake_store, stub_phase2, stub_phase3, monkeypatch
):
    """If _emit_cortex_heartbeat itself leaks an exception past its own
    try/except (regression scenario), the cycle must still archive
    successfully — every call site has a belt-and-suspenders try/except.
    """
    async def _phase4_noop(cycle):
        return False

    monkeypatch.setattr(runner, "_phase4_propose", _phase4_noop)

    async def _bad_hb(cycle, phase, status):
        raise RuntimeError("simulated heartbeat regression")

    async def _bad_ratify(cycle):
        raise RuntimeError("simulated ratify regression")

    monkeypatch.setattr(runner, "_emit_cortex_heartbeat", _bad_hb)
    monkeypatch.setattr(runner, "_emit_cortex_ratify_required", _bad_ratify)

    # Cycle must NOT raise — the wrappers swallow the exception.
    cycle = asyncio.run(
        runner.maybe_run_cycle(matter_slug="oskolkov", triggered_by="test")
    )

    # Cycle completed cleanly through Phase 6 archive (proposed terminal state).
    assert cycle.status == "proposed"
    assert cycle.current_phase == "archive"
