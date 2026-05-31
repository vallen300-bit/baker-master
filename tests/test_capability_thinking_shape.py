"""SPECIALIST-THINKING-2 regression guards: extended-thinking request shape.

Opus 4.7/4.8 reject manual extended thinking
(``{"type": "enabled", "budget_tokens": N}``) with HTTP 400
("thinking.type.enabled is not supported for this model"). Adaptive thinking is
the only accepted mode; depth is controlled by ``output_config.effort``, which
replaced ``budget_tokens``. These tests lock the request shape so a future edit
can't silently reintroduce the manual syntax and re-break live calls.

Live-verified 2026-05-31 against claude-opus-4-7 and claude-opus-4-8:
  - manual enabled+budget_tokens -> HTTP 400 on both models
  - adaptive + output_config.effort -> accepted (stop_reason=tool_use)
"""
from orchestrator.capability_runner import (
    _THINKING_EFFORT,
    _adaptive_thinking_params,
)

_VALID_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def test_adaptive_thinking_params_is_adaptive_not_manual():
    params = _adaptive_thinking_params()
    # Adaptive mode only — manual budget_tokens 400s on Opus 4.7/4.8.
    assert params["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in params["thinking"]
    assert params["thinking"].get("type") != "enabled"


def test_adaptive_thinking_params_carries_effort_not_budget():
    params = _adaptive_thinking_params()
    # Depth is controlled by output_config.effort, not a manual token budget.
    assert params["output_config"] == {"effort": _THINKING_EFFORT}


def test_adaptive_thinking_params_effort_override():
    params = _adaptive_thinking_params(effort="high")
    assert params["output_config"]["effort"] == "high"
    assert params["thinking"]["type"] == "adaptive"


def test_default_thinking_effort_is_a_valid_level():
    assert _THINKING_EFFORT in _VALID_EFFORT_LEVELS
