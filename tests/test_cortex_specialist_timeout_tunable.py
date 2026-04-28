"""CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1 — env-override behavior.

Brief: ``briefs/BRIEF_CORTEX_SPECIALIST_TIMEOUT_TUNABLE_1.md``.
"""
from __future__ import annotations

import importlib


def test_specialist_timeout_env_override(monkeypatch):
    """CORTEX_SPECIALIST_TIMEOUT_S env var overrides hardcoded default."""
    import orchestrator.cortex_phase3_invoker as inv

    # Default (no env set) should be 180 post-this-PR
    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
    importlib.reload(inv)
    assert inv.SPECIALIST_TIMEOUT_S == 180

    # Env override
    monkeypatch.setenv("CORTEX_SPECIALIST_TIMEOUT_S", "240")
    importlib.reload(inv)
    assert inv.SPECIALIST_TIMEOUT_S == 240

    # Reload back to default for other tests
    monkeypatch.delenv("CORTEX_SPECIALIST_TIMEOUT_S", raising=False)
    importlib.reload(inv)
    assert inv.SPECIALIST_TIMEOUT_S == 180
