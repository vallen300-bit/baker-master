"""Tests for BAKER-PROMPT-CACHING-1.

Locks in:
  - `_build_cached_system_and_tools` shape (Anthropic ephemeral block on system,
    cache_control on the LAST tool entry only)
  - kill switch via BAKER_PROMPT_CACHE_ENABLED=false → passthrough strings
  - Gemini guard (is_gemini_model true → passthrough strings, never list)
  - `calculate_cost_eur` honours 90% discount on read + 25% premium on write
  - `log_api_cost` accepts the new cache token kwargs without breaking
    existing callers (default 0)
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


# -----------------------------------------------------------------------------
# Cost calc
# -----------------------------------------------------------------------------


def test_calculate_cost_eur_zero_cache_matches_legacy_formula():
    from orchestrator.cost_monitor import calculate_cost_eur, MODEL_COSTS, USD_TO_EUR
    model = "claude-opus-4-6"
    in_tok = 1000
    out_tok = 500
    expected_usd = (
        in_tok / 1_000_000 * MODEL_COSTS[model]["input"]
        + out_tok / 1_000_000 * MODEL_COSTS[model]["output"]
    )
    expected = round(expected_usd * USD_TO_EUR, 6)
    assert calculate_cost_eur(model, in_tok, out_tok) == expected


def test_calculate_cost_eur_cache_read_billed_at_10_percent():
    from orchestrator.cost_monitor import calculate_cost_eur, MODEL_COSTS, USD_TO_EUR
    model = "claude-opus-4-6"
    rate_in = MODEL_COSTS[model]["input"]
    base = calculate_cost_eur(model, 0, 0, cache_read_input_tokens=1_000_000)
    expected = round(rate_in * 0.10 * USD_TO_EUR, 6)
    assert base == expected


def test_calculate_cost_eur_cache_creation_billed_at_125_percent():
    from orchestrator.cost_monitor import calculate_cost_eur, MODEL_COSTS, USD_TO_EUR
    model = "claude-opus-4-6"
    rate_in = MODEL_COSTS[model]["input"]
    base = calculate_cost_eur(model, 0, 0, cache_creation_input_tokens=1_000_000)
    expected = round(rate_in * 1.25 * USD_TO_EUR, 6)
    assert base == expected


# -----------------------------------------------------------------------------
# _build_cached_system_and_tools
# -----------------------------------------------------------------------------


def _reload_agent_module(monkeypatch, *, enabled: bool, gemini: bool):
    """Reload orchestrator.agent so the module-level PROMPT_CACHE_ENABLED is
    re-read from the patched env, and stub is_gemini_model on the fly.
    """
    monkeypatch.setenv("BAKER_PROMPT_CACHE_ENABLED", "true" if enabled else "false")
    import orchestrator.agent as agent_mod
    importlib.reload(agent_mod)

    # Stub the lazy gemini import inside the helper. The helper imports
    # `is_gemini_model` from orchestrator.gemini_client at call time.
    import orchestrator.gemini_client as gc
    monkeypatch.setattr(gc, "is_gemini_model", lambda _m: gemini)
    return agent_mod


def test_build_caches_system_and_marks_last_tool(monkeypatch):
    agent_mod = _reload_agent_module(monkeypatch, enabled=True, gemini=False)
    tools = [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}]
    sys_v, tools_v = agent_mod._build_cached_system_and_tools(
        "STATIC PROMPT", tools, "claude-opus-4-6")

    # System: list with one ephemeral block.
    assert isinstance(sys_v, list) and len(sys_v) == 1
    assert sys_v[0]["type"] == "text"
    assert sys_v[0]["text"] == "STATIC PROMPT"
    assert sys_v[0]["cache_control"] == {"type": "ephemeral"}

    # Tools: cache_control on LAST entry only, others untouched.
    assert isinstance(tools_v, list) and len(tools_v) == 3
    assert "cache_control" not in tools_v[0]
    assert "cache_control" not in tools_v[1]
    assert tools_v[-1]["cache_control"] == {"type": "ephemeral"}
    assert tools_v[-1]["name"] == "t3"

    # Original tools list must not be mutated (defensive copy).
    assert "cache_control" not in tools[-1]


def test_build_kill_switch_returns_passthrough(monkeypatch):
    agent_mod = _reload_agent_module(monkeypatch, enabled=False, gemini=False)
    tools = [{"name": "t1"}, {"name": "t2"}]
    sys_v, tools_v = agent_mod._build_cached_system_and_tools(
        "STATIC", tools, "claude-opus-4-6")
    assert sys_v == "STATIC"
    assert tools_v is tools  # exact passthrough, no copy


def test_build_gemini_guard_returns_passthrough(monkeypatch):
    agent_mod = _reload_agent_module(monkeypatch, enabled=True, gemini=True)
    tools = [{"name": "t1"}]
    sys_v, tools_v = agent_mod._build_cached_system_and_tools(
        "STATIC", tools, "gemini-2.5-flash")
    assert sys_v == "STATIC"
    assert tools_v is tools


def test_build_handles_empty_tools(monkeypatch):
    agent_mod = _reload_agent_module(monkeypatch, enabled=True, gemini=False)
    sys_v, tools_v = agent_mod._build_cached_system_and_tools(
        "STATIC", None, "claude-opus-4-6")
    assert isinstance(sys_v, list) and sys_v[0]["cache_control"] == {"type": "ephemeral"}
    assert tools_v is None


# -----------------------------------------------------------------------------
# log_api_cost backwards compatibility
# -----------------------------------------------------------------------------


def test_log_api_cost_accepts_legacy_signature(monkeypatch):
    """Pre-existing positional callers (model, in, out, source) keep working."""
    from orchestrator import cost_monitor

    # No DB available in unit tests — function tolerates that path and
    # returns the computed cost regardless.
    monkeypatch.setattr(cost_monitor, "calculate_cost_eur", lambda *a, **kw: 0.42)

    fake_store_mod = MagicMock()
    fake_store_mod.SentinelStoreBack._get_global_instance.return_value = None
    monkeypatch.setitem(__import__("sys").modules, "memory.store_back", fake_store_mod)

    out = cost_monitor.log_api_cost("claude-opus-4-6", 100, 50, source="agent_loop")
    assert out == 0.42


def test_log_api_cost_passes_cache_kwargs_to_calc(monkeypatch):
    from orchestrator import cost_monitor

    captured = {}

    def fake_calc(model, in_t, out_t, cache_creation_input_tokens=0,
                  cache_read_input_tokens=0):
        captured["create"] = cache_creation_input_tokens
        captured["read"] = cache_read_input_tokens
        return 0.0

    monkeypatch.setattr(cost_monitor, "calculate_cost_eur", fake_calc)
    fake_store_mod = MagicMock()
    fake_store_mod.SentinelStoreBack._get_global_instance.return_value = None
    monkeypatch.setitem(__import__("sys").modules, "memory.store_back", fake_store_mod)

    cost_monitor.log_api_cost(
        "claude-opus-4-6", 100, 50, source="agent_loop",
        cache_creation_input_tokens=42, cache_read_input_tokens=999,
    )
    assert captured == {"create": 42, "read": 999}
