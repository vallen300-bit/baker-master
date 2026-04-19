"""Tests for kbl.anthropic_client — Opus SDK wrapper."""
from __future__ import annotations

import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kbl import anthropic_client
from kbl.anthropic_client import (
    OpusResponse,
    _compute_cost_usd,
    _extract_text,
    _extract_usage,
    call_opus,
)
from kbl.exceptions import AnthropicUnavailableError, OpusRequestError


@pytest.fixture(autouse=True)
def _clear_module_client(monkeypatch: pytest.MonkeyPatch):
    """Reset the lazy client singleton around every test so
    monkeypatched env vars land."""
    anthropic_client._reset_client_for_tests()
    yield
    anthropic_client._reset_client_for_tests()


# --------------------------- _require_api_key ---------------------------


def test_require_api_key_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        anthropic_client._require_api_key()


def test_require_api_key_returns_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert anthropic_client._require_api_key() == "sk-test-123"


# --------------------------- cost computation ---------------------------


def test_compute_cost_with_cache_read_discount() -> None:
    """1K base input + 1K cache read — cache read costs ~10% of base."""
    cost = _compute_cost_usd(
        input_tokens=1000,
        output_tokens=0,
        cache_read_tokens=1000,
        cache_write_tokens=0,
    )
    # 1000 * 15/1M + 1000 * 15 * 0.1 / 1M = 0.015 + 0.0015 = 0.0165 USD
    assert cost == Decimal("0.0165")


def test_compute_cost_with_cache_write_markup() -> None:
    """Cache writes cost 1.25x base input rate."""
    cost = _compute_cost_usd(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=1000,
    )
    # 1000 * 15 * 1.25 / 1M = 0.01875 USD
    assert cost == Decimal("0.01875")


def test_compute_cost_zero_tokens_is_zero() -> None:
    assert _compute_cost_usd(0, 0, 0, 0) == Decimal("0")


def test_compute_cost_output_dominates_opus_pricing() -> None:
    """Output is 5x input rate — verify."""
    input_cost = _compute_cost_usd(1000, 0, 0, 0)
    output_cost = _compute_cost_usd(0, 1000, 0, 0)
    # 15/M * 1000 vs 75/M * 1000
    assert input_cost == Decimal("0.015")
    assert output_cost == Decimal("0.075")
    assert output_cost == input_cost * 5


# --------------------------- _extract_usage ---------------------------


def test_extract_usage_returns_zeros_for_missing_attrs() -> None:
    usage = SimpleNamespace()
    assert _extract_usage(usage) == (0, 0, 0, 0)


def test_extract_usage_full_attrs() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=200,
        cache_read_input_tokens=50,
        cache_creation_input_tokens=25,
    )
    assert _extract_usage(usage) == (100, 200, 50, 25)


def test_extract_usage_tolerates_none_values() -> None:
    usage = SimpleNamespace(
        input_tokens=None,
        output_tokens=None,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
    )
    assert _extract_usage(usage) == (0, 0, 0, 0)


# --------------------------- _extract_text ---------------------------


def test_extract_text_concatenates_text_blocks() -> None:
    content = [
        SimpleNamespace(type="text", text="Hello "),
        SimpleNamespace(type="text", text="world"),
    ]
    assert _extract_text(content) == "Hello world"


def test_extract_text_ignores_non_text_blocks() -> None:
    """Extended-thinking blocks shouldn't leak into synthesis text."""
    content = [
        SimpleNamespace(type="thinking", text="internal"),
        SimpleNamespace(type="text", text="output"),
    ]
    assert _extract_text(content) == "output"


def test_extract_text_empty_returns_empty() -> None:
    assert _extract_text([]) == ""
    assert _extract_text(None) == ""


# --------------------------- call_opus ---------------------------


def _mock_ok_response() -> SimpleNamespace:
    """Build a stand-in for SDK Message response."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="---\ntitle: x\n---\n\nbody")],
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=300,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=1000,
        ),
        stop_reason="end_turn",
        model="claude-opus-4-7",
    )


def test_call_opus_happy_path_returns_response_with_cost() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_ok_response()

    resp = call_opus(
        system="system template",
        user="user block",
        client=mock_client,
    )

    assert isinstance(resp, OpusResponse)
    assert resp.text == "---\ntitle: x\n---\n\nbody"
    assert resp.input_tokens == 500
    assert resp.output_tokens == 300
    assert resp.cache_write_tokens == 1000
    assert resp.cost_usd > 0
    assert resp.stop_reason == "end_turn"
    assert resp.model_id == "claude-opus-4-7"


def test_call_opus_system_block_has_cache_control() -> None:
    """Prompt-caching contract: system block is sent with
    cache_control=ephemeral so the stable template is cacheable."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_ok_response()

    call_opus(system="stable sys", user="user", client=mock_client)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_blocks = call_kwargs["system"]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert system_blocks[0]["text"] == "stable sys"
    assert system_blocks[0]["type"] == "text"


def test_call_opus_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_STEP5_MODEL", "claude-sonnet-4-6")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_ok_response()

    call_opus(system="s", user="u", client=mock_client)

    assert mock_client.messages.create.call_args.kwargs["model"] == (
        "claude-sonnet-4-6"
    )


def test_call_opus_explicit_model_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_STEP5_MODEL", "claude-sonnet-4-6")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_ok_response()

    call_opus(system="s", user="u", client=mock_client, model="claude-opus-4-7")

    assert mock_client.messages.create.call_args.kwargs["model"] == (
        "claude-opus-4-7"
    )


def test_call_opus_prompt_cache_hit_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache-hit path: second call returns cache_read_tokens > 0 and
    base input_tokens drops — verify we surface that shape correctly."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="body")],
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=100,
            cache_read_input_tokens=3000,  # cached system block served cheap
            cache_creation_input_tokens=0,
        ),
        stop_reason="end_turn",
        model="claude-opus-4-7",
    )

    resp = call_opus(system="s", user="u", client=mock_client)
    # The whole point: cache hits should read as cache_read_tokens > 0.
    assert resp.cache_read_tokens == 3000
    assert resp.cache_write_tokens == 0


# --------------------------- error paths ---------------------------


def _raise_as(cli: MagicMock, exc: BaseException) -> None:
    """Wire the mock client to raise ``exc`` from messages.create."""
    cli.messages.create.side_effect = exc


def test_call_opus_timeout_raises_unavailable() -> None:
    """``APITimeoutError`` → AnthropicUnavailableError."""
    from anthropic import APITimeoutError

    mock_client = MagicMock()
    # APITimeoutError requires a request arg in the SDK; inject bare instance.
    _raise_as(mock_client, APITimeoutError(request=MagicMock()))

    with pytest.raises(AnthropicUnavailableError):
        call_opus(system="s", user="u", client=mock_client)


def test_call_opus_rate_limit_raises_unavailable() -> None:
    """``RateLimitError`` → AnthropicUnavailableError (not OpusRequestError).
    Rate-limiting is transient; retrying recovers."""
    from anthropic import RateLimitError

    mock_client = MagicMock()
    err = RateLimitError(
        message="rate limit",
        response=MagicMock(status_code=429),
        body={"error": {"message": "rate limit"}},
    )
    _raise_as(mock_client, err)

    with pytest.raises(AnthropicUnavailableError, match="rate limit"):
        call_opus(system="s", user="u", client=mock_client)


def test_call_opus_4xx_raises_request_error() -> None:
    """4xx is NOT retryable — distinct error class."""
    from anthropic import BadRequestError

    mock_client = MagicMock()
    err = BadRequestError(
        message="invalid model",
        response=MagicMock(status_code=400),
        body={"error": {"message": "invalid model"}},
    )
    _raise_as(mock_client, err)

    with pytest.raises(OpusRequestError):
        call_opus(system="s", user="u", client=mock_client)


def test_call_opus_5xx_raises_unavailable() -> None:
    """5xx IS retryable — AnthropicUnavailableError so the R3 ladder
    picks it up."""
    from anthropic import InternalServerError

    mock_client = MagicMock()
    err = InternalServerError(
        message="server error",
        response=MagicMock(status_code=500),
        body={"error": {"message": "server error"}},
    )
    _raise_as(mock_client, err)

    with pytest.raises(AnthropicUnavailableError):
        call_opus(system="s", user="u", client=mock_client)


# --------------------------- live-API smoke ---------------------------


requires_api_key = pytest.mark.skipif(
    not os.environ.get("KBL_STEP5_LIVE_API"),
    reason="KBL_STEP5_LIVE_API unset — skipping live Opus smoke test",
)


@requires_api_key
def test_call_opus_live_smoke_under_1_cent() -> None:
    """One real Opus call on a tiny prompt. Verifies end-to-end wiring
    (SDK import, auth, response shape, cost calc). Capped to <$0.01."""
    resp = call_opus(
        system="You are a helper. Reply with a single word.",
        user="Say ok.",
        max_tokens=16,
    )
    assert isinstance(resp, OpusResponse)
    assert resp.text.strip()
    assert resp.cost_usd < Decimal("0.01")
    assert resp.model_id.startswith("claude-")
