"""Tests for orchestrator/cortex_phase3_invoker.py — Phase 3b specialist
invocation with 60s/2-retry/fail-forward (CORTEX_3T_FORMALIZE_1B).

Brief: ``briefs/BRIEF_CORTEX_3T_FORMALIZE_1B.md``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orchestrator import cortex_phase3_invoker as invoker


# --------------------------------------------------------------------------
# Stub harness
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple] = []

    def execute(self, q, params=None):
        self.queries.append((q, params))

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
        self.conn = _FakeConn()
        self.put_count = 0

    def _get_conn(self):
        return self.conn

    def _put_conn(self, c):
        self.put_count += 1


def _make_cap(slug):
    """Mimic CapabilityDef enough for invoker to use it."""
    return SimpleNamespace(slug=slug, name=slug)


def _agent_result(answer="OK", in_tok=100, out_tok=50, elapsed_ms=500):
    return SimpleNamespace(
        answer=answer,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        elapsed_ms=elapsed_ms,
        iterations=1,
        tool_calls=[],
        timed_out=False,
    )


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Returns (set_run_single_behavior, get_store, set_lookup_capability,
    staging_root)."""
    state = {
        "behavior": lambda cap, q: _agent_result(),
        "captured_calls": [],
        "registered": {},  # slug → CapabilityDef-ish
    }
    store = _FakeStore()

    class _FakeRunner:
        def run_single(self, cap, question, **kw):
            state["captured_calls"].append((cap.slug, question))
            return state["behavior"](cap, question)

    monkeypatch.setattr(invoker, "_get_store", lambda: store)
    monkeypatch.setattr(invoker, "_get_capability_runner", lambda: _FakeRunner())
    monkeypatch.setattr(invoker, "_get_capability_def",
                        lambda slug: state["registered"].get(slug))
    monkeypatch.setattr(invoker, "_calc_cost_eur",
                        lambda i, o: (i + o) * 0.0001)  # deterministic
    monkeypatch.setattr(invoker, "STAGING_ROOT", tmp_path / "stage")

    def set_behavior(fn):
        state["behavior"] = fn

    def register_caps(*slugs):
        for s in slugs:
            state["registered"][s] = _make_cap(s)

    return set_behavior, store, register_caps, state, tmp_path


# ==========================================================================
# 1. Success path
# ==========================================================================


def test_success_returns_specialist_output(patched):
    set_behavior, store, register_caps, state, _ = patched
    register_caps("legal")
    set_behavior(lambda c, q: _agent_result(answer="legal advice", in_tok=200, out_tok=100))

    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="c1", matter_slug="oskolkov", signal_text="lawsuit incoming",
        capabilities_to_invoke=["legal"],
        phase2_context={"matter_config": "x"},
    ))
    assert len(result.outputs) == 1
    out = result.outputs[0]
    assert out.success is True
    assert out.output_text == "legal advice"
    assert out.cost_tokens == 300
    assert out.cost_dollars == pytest.approx(0.03)
    assert out.attempts == 1


def test_question_includes_signal_and_matter_brain(patched):
    set_behavior, _, register_caps, state, _ = patched
    register_caps("finance")

    asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="c2", matter_slug="oskolkov",
        signal_text="invoice overdue",
        capabilities_to_invoke=["finance"],
        phase2_context={"matter_config": "Oskolkov is finance-heavy",
                        "state": "open invoices=3"},
    ))
    slug, question = state["captured_calls"][0]
    assert slug == "finance"
    assert "invoice overdue" in question
    assert "Oskolkov is finance-heavy" in question
    assert "open invoices=3" in question


# ==========================================================================
# 2. Capability not registered → fail-forward
# ==========================================================================


def test_unknown_capability_records_failure_and_continues(patched):
    set_behavior, _, register_caps, state, _ = patched
    register_caps("legal")  # only legal — 'finance' missing

    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="c3", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["legal", "finance"],
        phase2_context={},
    ))
    by_slug = {o.capability_slug: o for o in result.outputs}
    assert by_slug["legal"].success is True
    assert by_slug["finance"].success is False
    assert "not in active registry" in by_slug["finance"].error


# ==========================================================================
# 3. Timeout fires → 2 retries → fail-forward
# ==========================================================================


def test_timeout_triggers_retries_then_fail_forward(patched, monkeypatch):
    """run_single hangs → asyncio.wait_for raises → 2 retries → fail."""
    set_behavior, _, register_caps, state, _ = patched
    register_caps("slow")

    # Force timeout by making asyncio.wait_for always raise TimeoutError
    async def _always_timeout(awaitable, timeout):
        # Cancel the awaitable cleanly to avoid asyncio warnings
        if hasattr(awaitable, "close"):
            try:
                awaitable.close()
            except Exception:
                pass
        raise asyncio.TimeoutError()

    monkeypatch.setattr(invoker.asyncio, "wait_for", _always_timeout)

    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="c4", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["slow"], phase2_context={},
    ))
    assert len(result.outputs) == 1
    out = result.outputs[0]
    assert out.success is False
    assert "timeout" in (out.error or "")
    assert out.attempts == 3  # 1 initial + 2 retries


def test_exception_triggers_retries_then_fail_forward(patched):
    set_behavior, _, register_caps, _, _ = patched
    register_caps("flaky")

    def _raise(c, q):
        raise RuntimeError("upstream broken")
    set_behavior(_raise)

    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="c5", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["flaky"], phase2_context={},
    ))
    out = result.outputs[0]
    assert out.success is False
    assert "upstream broken" in (out.error or "")
    assert out.attempts == 3


# ==========================================================================
# 4. Partial-failure synthesis input
# ==========================================================================


def test_partial_failure_one_of_many(patched):
    set_behavior, _, register_caps, state, _ = patched
    register_caps("a", "b", "c")

    def _behavior(cap, q):
        if cap.slug == "b":
            raise RuntimeError("b broken")
        return _agent_result(answer=f"out-{cap.slug}")
    set_behavior(_behavior)

    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cP", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["a", "b", "c"], phase2_context={},
    ))
    by = {o.capability_slug: o for o in result.outputs}
    assert by["a"].success and by["c"].success
    assert by["b"].success is False


# ==========================================================================
# 5. Persistence — INSERT + UPDATE
# ==========================================================================


def test_persist_writes_specialist_invocation_artifact(patched):
    set_behavior, store, register_caps, _, _ = patched
    register_caps("legal")

    asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cQ", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["legal"], phase2_context={},
    ))
    inserts = [q for q in store.conn.cur.queries
               if "INSERT INTO cortex_phase_outputs" in q[0]]
    assert len(inserts) == 1
    assert "'reason', 4, 'specialist_invocation'" in inserts[0][0]


def test_persist_bumps_cycle_cost_after_loop(patched):
    set_behavior, store, register_caps, _, _ = patched
    register_caps("a", "b")
    set_behavior(lambda c, q: _agent_result(in_tok=100, out_tok=50))

    asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cR", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["a", "b"], phase2_context={},
    ))
    updates = [q for q in store.conn.cur.queries if "UPDATE cortex_cycles" in q[0]]
    assert len(updates) == 1
    # Total: (100+50)*2 = 300 tokens; cost = 300 * 0.0001 = 0.03
    assert updates[0][1] == (300, pytest.approx(0.03), "cR")


# ==========================================================================
# 6. Staging file write
# ==========================================================================


def test_staging_file_written_on_success(patched):
    set_behavior, _, register_caps, _, tmp_path = patched
    register_caps("legal")
    set_behavior(lambda c, q: _agent_result(answer="legal opinion text"))

    asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cycle-99", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["legal"], phase2_context={},
    ))
    staging_dir = tmp_path / "stage" / "cycle-99"
    assert staging_dir.is_dir()
    files = list(staging_dir.glob("legal-*.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert "legal opinion text" in body
    assert "cycle-99" in body


def test_staging_file_skipped_on_failure(patched):
    set_behavior, _, register_caps, _, tmp_path = patched
    register_caps("flaky")

    def _raise(c, q):
        raise RuntimeError("nope")
    set_behavior(_raise)

    asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cycle-fail", matter_slug="x", signal_text="...",
        capabilities_to_invoke=["flaky"], phase2_context={},
    ))
    staging_dir = tmp_path / "stage" / "cycle-fail"
    # Either dir doesn't exist or is empty
    if staging_dir.is_dir():
        assert not list(staging_dir.glob("*.md"))


# ==========================================================================
# 7. Empty list guard
# ==========================================================================


def test_empty_list_returns_empty_result(patched):
    _, _, _, _, _ = patched
    result = asyncio.run(invoker.run_phase3b_invocations(
        cycle_id="cE", matter_slug="x", signal_text="...",
        capabilities_to_invoke=[], phase2_context={},
    ))
    assert result.outputs == []
    assert result.total_cost_tokens == 0
