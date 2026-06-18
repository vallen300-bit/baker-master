"""Tests for the Cortex dispatch hook.

History:
  * CORTEX_3T_FORMALIZE_1C wired ``_dispatch_cortex_for_inserted`` into
    ``kbl/bridge/alerts_to_signal.py`` post-INSERT.
  * CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1 (2026-04-30) moved the dispatch
    out of the bridge — the bridge fired BEFORE Step 1 canonicalized
    ``primary_matter`` so the cost-gate's ``matter_has_cortex_config``
    always missed on raw classifier labels. Dispatch now lives in
    ``kbl.steps.step6_finalize.dispatch_cortex_after_finalize``,
    invoked post-commit by ``kbl/pipeline_tick.py``.

Coverage:
  * Source-level assertion that the bridge no longer dispatches.
  * ``triggers.cortex_pipeline.maybe_dispatch`` — env-flag-gated,
    never-raises, drives ``maybe_trigger_cortex`` on a fresh event loop.

Helper-level tests for ``dispatch_cortex_after_finalize`` live in
``tests/test_step6_cortex_dispatch.py``.
"""
from __future__ import annotations

import pytest

from kbl.bridge import alerts_to_signal as bridge
from triggers import cortex_pipeline


# --------------------------------------------------------------------------
# bridge module — must NOT dispatch any more
# --------------------------------------------------------------------------


def test_bridge_module_no_longer_dispatches_cortex():
    """Bridge tick must not import or call cortex_pipeline.maybe_dispatch.

    CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1: dispatch moved to Step 6 finalize.
    """
    src = open("kbl/bridge/alerts_to_signal.py").read()
    assert "maybe_dispatch" not in src
    assert "_dispatch_cortex_for_inserted" not in src
    # Helper symbol must also be gone from the public API.
    assert not hasattr(bridge, "_dispatch_cortex_for_inserted")


# --------------------------------------------------------------------------
# triggers.cortex_pipeline.maybe_dispatch
# --------------------------------------------------------------------------


def test_maybe_dispatch_no_op_when_flag_off(monkeypatch):
    """Flag off (default) → no dispatch call, no async loop spin-up."""
    monkeypatch.delenv("CORTEX_PIPELINE_ENABLED", raising=False)
    triggered = []

    async def _fake_trigger(**kw):
        triggered.append(kw)

    monkeypatch.setattr(cortex_pipeline, "maybe_trigger_cortex", _fake_trigger)
    cortex_pipeline.maybe_dispatch(signal_id=42, matter_slug="ao")
    assert triggered == []


def test_maybe_dispatch_skips_when_no_matter_slug(monkeypatch):
    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")
    triggered = []

    async def _fake_trigger(**kw):
        triggered.append(kw)

    monkeypatch.setattr(cortex_pipeline, "maybe_trigger_cortex", _fake_trigger)
    cortex_pipeline.maybe_dispatch(signal_id=42, matter_slug=None)
    assert triggered == []


def test_maybe_dispatch_fires_when_flag_on(monkeypatch):
    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")
    triggered = []

    async def _fake_trigger(*, signal_id, matter_slug):
        triggered.append((signal_id, matter_slug))

    monkeypatch.setattr(cortex_pipeline, "maybe_trigger_cortex", _fake_trigger)
    cortex_pipeline.maybe_dispatch(signal_id=99, matter_slug="ao")
    assert triggered == [(99, "ao")]


def test_maybe_dispatch_swallows_runner_exception(monkeypatch, caplog):
    """Cortex runner blowing up must NOT escape — bridge tick already committed."""
    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")

    async def _kaboom(**kw):
        raise RuntimeError("cortex offline")

    monkeypatch.setattr(cortex_pipeline, "maybe_trigger_cortex", _kaboom)
    with caplog.at_level("ERROR"):
        cortex_pipeline.maybe_dispatch(signal_id=1, matter_slug="ao")  # must not raise
    assert any("cortex offline" in r.message for r in caplog.records)


def test_maybe_dispatch_flag_default_off():
    """Source-level: env flag is documented + default is OFF until DRY_RUN passes."""
    src = open("triggers/cortex_pipeline.py").read()
    assert "CORTEX_PIPELINE_ENABLED" in src
    assert '"false"' in src   # default is "false" string


# --------------------------------------------------------------------------
# Step 6 wire-up source assertion
# --------------------------------------------------------------------------


def test_step6_finalize_dispatches_cortex_after_commit_in_source():
    """The dispatch call now lives in Step 6 finalize, called by
    pipeline_tick AFTER each finalize commit (CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1).
    """
    finalize_src = open("kbl/steps/step6_finalize.py").read()
    assert "def dispatch_cortex_after_finalize" in finalize_src
    assert "maybe_dispatch" in finalize_src

    tick_src = open("kbl/pipeline_tick.py").read()
    # 6 process_signal_* variants each fire dispatch after Step 6 commit.
    occurrences = tick_src.count("step6_finalize.dispatch_cortex_after_finalize")
    assert occurrences >= 6, (
        f"expected dispatch_cortex_after_finalize wired into all 6 "
        f"finalize call sites, found {occurrences}"
    )


def test_insert_signal_returns_id_not_bool():
    """Refactor preserved truthiness but the function now returns the id."""
    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return (777,)
    row = bridge.map_alert_to_signal({
        "id": 1, "tier": 1, "title": "t", "body": "b",
        "matter_slug": "ao", "source": "x", "source_id": "y",
        "tags": [], "structured_actions": [], "contact_id": None,
        "created_at": None,
    })
    result = bridge._insert_signal_if_new(_Cur(), row)
    assert result == 777
    assert result is not True   # not a bool any more


def test_insert_signal_returns_none_on_duplicate():
    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return None
    row = bridge.map_alert_to_signal({
        "id": 1, "tier": 1, "title": "t", "body": "b",
        "matter_slug": "ao", "source": "x", "source_id": "y",
        "tags": [], "structured_actions": [], "contact_id": None,
        "created_at": None,
    })
    assert bridge._insert_signal_if_new(_Cur(), row) is None


# --------------------------------------------------------------------------
# CORTEX_LITE_REBASE_1 WP-C — Lite mode must never fall through to direct-fire
# --------------------------------------------------------------------------
# NOTE (b1 deviation from brief, documented in ship report): the brief's first
# test omitted CORTEX_PIPELINE_ENABLED=true, which makes maybe_dispatch early-
# return before maybe_trigger_cortex runs — i.e. the test would pass vacuously
# and prove nothing (Lesson #8). We set the flag so the suppression path is
# actually exercised. Assertion is unchanged: Lite mode must not direct-fire.


def test_maybe_trigger_lite_secret_missing_does_not_direct_fire(monkeypatch):
    calls = []

    async def _fake_cycle(**kwargs):
        calls.append(kwargs)

    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LIVE_PIPELINE", "true")
    monkeypatch.setenv("CORTEX_GATE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.delenv("CORTEX_GATE_SECRET", raising=False)
    monkeypatch.setattr("orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle)
    cortex_pipeline.maybe_dispatch(signal_id=42, matter_slug="oskolkov")
    assert calls == []


def test_maybe_trigger_lite_gate_exception_does_not_direct_fire(monkeypatch):
    calls = []

    async def _fake_cycle(**kwargs):
        calls.append(kwargs)

    def _boom(**kwargs):
        raise RuntimeError("slack down")

    monkeypatch.setenv("CORTEX_PIPELINE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LIVE_PIPELINE", "true")
    monkeypatch.setenv("CORTEX_GATE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_LITE_ENABLED", "true")
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    monkeypatch.setattr("triggers.cortex_pre_review_gate.post_gate", _boom)
    monkeypatch.setattr("orchestrator.cortex_runner.maybe_run_cycle", _fake_cycle)
    cortex_pipeline.maybe_dispatch(signal_id=43, matter_slug="oskolkov")
    assert calls == []
