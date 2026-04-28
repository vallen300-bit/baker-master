"""Tests for Amendment A2 — kbl/bridge/alerts_to_signal.py wires
``triggers.cortex_pipeline.maybe_dispatch`` after every signal_queue
INSERT commits. CORTEX_3T_FORMALIZE_1C.

Two-pronged coverage:
  (a) the bridge module's ``_dispatch_cortex_for_inserted`` helper —
      env-flag-gated, never-raises, per-signal try/except.
  (b) ``triggers.cortex_pipeline.maybe_dispatch`` — env-flag-gated, never
      raises, drives ``maybe_trigger_cortex`` on a fresh event loop.
"""
from __future__ import annotations

import pytest

from kbl.bridge import alerts_to_signal as bridge
from triggers import cortex_pipeline


# --------------------------------------------------------------------------
# bridge module — _dispatch_cortex_for_inserted
# --------------------------------------------------------------------------


def test_dispatch_helper_calls_maybe_dispatch_per_signal(monkeypatch):
    calls = []

    def _fake_maybe_dispatch(*, signal_id, matter_slug):
        calls.append((signal_id, matter_slug))

    monkeypatch.setattr(
        "triggers.cortex_pipeline.maybe_dispatch", _fake_maybe_dispatch,
    )
    bridge._dispatch_cortex_for_inserted([(101, "oskolkov"), (102, "movie")])
    assert calls == [(101, "oskolkov"), (102, "movie")]


def test_dispatch_helper_swallows_per_signal_exception(monkeypatch, caplog):
    """A poison signal must not starve siblings nor escape to caller."""
    seen = []

    def _flaky(*, signal_id, matter_slug):
        seen.append(signal_id)
        if signal_id == 102:
            raise RuntimeError("poison")

    monkeypatch.setattr("triggers.cortex_pipeline.maybe_dispatch", _flaky)
    with caplog.at_level("WARNING"):
        bridge._dispatch_cortex_for_inserted([(101, "a"), (102, "b"), (103, "c")])
    assert seen == [101, 102, 103]   # all attempted
    assert any("poison" in r.message for r in caplog.records)


def test_dispatch_helper_no_op_on_empty_list():
    bridge._dispatch_cortex_for_inserted([])  # must not raise


def test_dispatch_helper_handles_import_failure(monkeypatch, caplog):
    """If cortex_pipeline import fails, log + return — don't raise."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _bad_import(name, *a, **k):
        if name == "triggers.cortex_pipeline":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _bad_import)
    with caplog.at_level("WARNING"):
        bridge._dispatch_cortex_for_inserted([(1, "m")])
    # No exception escaped


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
# bridge wire-up source assertion
# --------------------------------------------------------------------------


def test_bridge_calls_dispatch_after_commit_in_source():
    """The dispatch call MUST happen AFTER conn.commit() — not before."""
    src = open("kbl/bridge/alerts_to_signal.py").read()
    # The post-commit dispatch is wired
    assert "_dispatch_cortex_for_inserted" in src
    commit_idx = src.find("conn.commit()\n                # Post-commit Cortex dispatch")
    assert commit_idx > 0, "expected commit followed by Cortex dispatch comment"


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
