"""FABLE_5_MIGRATION_1 pricing regressions."""
from __future__ import annotations

import importlib
import os
from decimal import Decimal

import pytest

from kbl import anthropic_client
from kbl.cost import PRICING, _model_key, estimate_cost
from orchestrator import cost_monitor


@pytest.fixture(autouse=True)
def _restore_anthropic_client_module(monkeypatch: pytest.MonkeyPatch):
    original_model = os.environ.get("KBL_ANTHROPIC_MODEL")
    yield
    if original_model is None:
        monkeypatch.delenv("KBL_ANTHROPIC_MODEL", raising=False)
    else:
        monkeypatch.setenv("KBL_ANTHROPIC_MODEL", original_model)
    importlib.reload(anthropic_client)


def test_kbl_cost_has_fable_pricing_and_model_key() -> None:
    assert _model_key("claude-fable-5") == "claude-fable-5"
    assert PRICING["claude-fable-5"]["input"] == 10.0
    assert PRICING["claude-fable-5"]["output"] == 50.0


def test_kbl_cost_opus_regression_still_maps_to_family_alias() -> None:
    assert _model_key("claude-opus-4-8") == "claude-opus-4"
    assert PRICING["claude-opus-4"]["input"] == 5.0
    assert PRICING["claude-opus-4"]["output"] == 25.0


def test_estimate_cost_accepts_fable_without_value_error() -> None:
    cost = estimate_cost(
        "claude-fable-5",
        "test prompt",
        max_output_tokens=100,
        anthropic=None,
    )

    assert cost > 0


def test_anthropic_client_uses_fable_pricing_when_default_model_is_fable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_ANTHROPIC_MODEL", "claude-fable-5")
    reloaded = importlib.reload(anthropic_client)

    assert reloaded._PRICE_OPUS_INPUT_PER_M == 10.0
    assert reloaded._PRICE_OPUS_OUTPUT_PER_M == 50.0
    assert reloaded._compute_cost_usd(25, 4, 0, 0) == Decimal("0.00045")


def test_anthropic_client_opus_pricing_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")
    reloaded = importlib.reload(anthropic_client)

    assert reloaded._PRICE_OPUS_INPUT_PER_M == 5.0
    assert reloaded._PRICE_OPUS_OUTPUT_PER_M == 25.0
    assert reloaded._compute_cost_usd(25, 4, 0, 0) == Decimal("0.000225")


def test_cost_monitor_has_exact_fable_entry() -> None:
    assert cost_monitor.MODEL_COSTS["claude-fable-5"] == {
        "input": 10.00,
        "output": 50.00,
    }


def test_cost_monitor_fable_calculation_and_opus_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cost_monitor, "USD_TO_EUR", 1.0)

    assert cost_monitor.calculate_cost_eur("claude-fable-5", 1_000, 1_000) == 0.06
    assert cost_monitor.calculate_cost_eur("claude-opus-4-8", 1_000, 1_000) == 0.03

