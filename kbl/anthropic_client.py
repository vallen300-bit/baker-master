"""Thin Anthropic SDK wrapper for Step 5 Opus synthesis.

Surface:
    call_opus(system, user, *, max_tokens=4096, extended_thinking=False)
        -> OpusResponse

``OpusResponse`` captures the tokens/cost/latency/stop-reason telemetry
Step 5 needs for the cost ledger. Cost is derived from the SDK's
``usage`` object using the pricing table in ``kbl.cost.PRICING`` — we
never heuristic-derive token counts on the happy path.

Prompt caching:
    The ``system`` argument is sent as a single content block with
    ``cache_control={"type": "ephemeral"}`` so the stable template is
    prompt-cacheable per Anthropic caching rules (§1.2 of B3's prompt —
    the system template is stable across signals by design).

Error surface:
    - Transport / 5xx / 429 / timeout          → AnthropicUnavailableError
      (caller's R3 retry ladder catches this)
    - 4xx user error (bad request, auth, etc.) → OpusRequestError
      (retry would not help — caller bypasses the ladder)

Model:
    Default ``claude-opus-4-7`` (1M-context). Env override:
    ``KBL_STEP5_MODEL`` — allows burn-in on Sonnet 4.6 without a code
    change if needed. ``ANTHROPIC_API_KEY`` is required; missing →
    RuntimeError at module import (fail-fast; Render catches it at boot).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import anthropic
from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)

from kbl.exceptions import AnthropicUnavailableError, OpusRequestError

# ---------------------------- constants ----------------------------

_DEFAULT_MODEL = "claude-opus-4-7"
_MODEL_ENV = "KBL_STEP5_MODEL"

_API_KEY_ENV = "ANTHROPIC_API_KEY"

# Pricing in USD per 1M tokens (mirrors kbl.cost.PRICING shape so
# operators can still tune rates via the same env-var family). These are
# EUR-treated-as-USD per §9.2 reconciliation — single-currency accounting
# for Phase 1. Phase 2 introduces proper multi-ccy handling.
_PRICE_OPUS_INPUT_PER_M = float(os.getenv("PRICE_OPUS4_IN", "15.00"))
_PRICE_OPUS_OUTPUT_PER_M = float(os.getenv("PRICE_OPUS4_OUT", "75.00"))
# Prompt-caching multipliers (Anthropic public pricing: cache writes are
# 1.25x base input; cache reads are 0.1x base input — i.e. ~90% discount).
_PRICE_OPUS_CACHE_WRITE_MUL = 1.25
_PRICE_OPUS_CACHE_READ_MUL = 0.10


# ---------------------------- response dataclass ----------------------------


@dataclass(frozen=True)
class OpusResponse:
    """Captured telemetry + text from a single call_opus() invocation.

    All token counts default to 0 when the SDK doesn't surface them (e.g.
    some error paths where usage is absent). ``cost_usd`` is a Decimal so
    the caller can sum precisely across a day without float drift.

    ``stop_reason`` is surfaced so the caller can distinguish clean
    ``end_turn`` completions from ``max_tokens`` truncations — a
    truncated frontmatter-stopping-mid-YAML is a parse-retry trigger.
    """

    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal
    latency_ms: int
    stop_reason: Optional[str]
    model_id: str


# ---------------------------- client singleton ----------------------------


def _require_api_key() -> str:
    """Fail-fast read. Render deploy catches missing key at boot."""
    key = os.environ.get(_API_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_API_KEY_ENV} env var not set — Step 5 Opus client cannot "
            "initialize. Set in Render env config."
        )
    return key


# Lazily-initialized so the import doesn't side-effect in test suites
# that stub the env — but we validate the key was present at first use,
# matching the fail-fast contract.
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=_require_api_key())
    return _client


def _reset_client_for_tests() -> None:
    """Test hook — drops the cached client so monkeypatched env vars
    land on the next call."""
    global _client
    _client = None


# ---------------------------- cost calculation ----------------------------


def _compute_cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> Decimal:
    """Per-call cost in USD derived from the SDK's usage object.

    Cache reads are discounted (~10% of base input). Cache writes are a
    small markup (1.25x base input). The ``input_tokens`` figure the SDK
    reports is the count of tokens that hit the base-rate path — i.e.
    tokens NOT served from cache. So the three streams sum disjointly;
    we multiply each by its own rate and sum.
    """
    base_in_cost = input_tokens * _PRICE_OPUS_INPUT_PER_M
    base_out_cost = output_tokens * _PRICE_OPUS_OUTPUT_PER_M
    cache_read_cost = cache_read_tokens * _PRICE_OPUS_INPUT_PER_M * _PRICE_OPUS_CACHE_READ_MUL
    cache_write_cost = cache_write_tokens * _PRICE_OPUS_INPUT_PER_M * _PRICE_OPUS_CACHE_WRITE_MUL
    total_per_m = base_in_cost + base_out_cost + cache_read_cost + cache_write_cost
    # Divide by 1M AFTER summing to keep intermediate precision.
    return Decimal(repr(total_per_m / 1_000_000))


def _extract_usage(usage_obj: Any) -> tuple[int, int, int, int]:
    """Return ``(input, output, cache_read, cache_write)`` from the SDK's
    usage object. The SDK returns different attribute shapes across
    versions; we tolerate missing attrs by defaulting to 0 rather than
    raising — a missing usage field is not a pipeline failure, it just
    reduces cost-ledger precision for that call."""
    def _val(obj: Any, attr: str) -> int:
        raw = getattr(obj, attr, None)
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    return (
        _val(usage_obj, "input_tokens"),
        _val(usage_obj, "output_tokens"),
        _val(usage_obj, "cache_read_input_tokens"),
        _val(usage_obj, "cache_creation_input_tokens"),
    )


def _extract_text(content: Any) -> str:
    """Concatenate all text blocks in the response content list.

    Opus responses on a non-streaming ``messages.create`` return a list
    of content blocks; for our synthesis prompt we only emit a single
    text block, but tolerate multi-block responses by joining with empty
    strings so a future ``extended_thinking`` content addition doesn't
    break text extraction."""
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", "")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


# ---------------------------- public entry ----------------------------


def call_opus(
    system: str,
    user: str,
    *,
    max_tokens: int = 4096,
    extended_thinking: bool = False,
    model: Optional[str] = None,
    client: Optional[anthropic.Anthropic] = None,
) -> OpusResponse:
    """Single Opus synthesis call with prompt caching on the system block.

    Args:
        system: stable template text — sent as a cache-control=ephemeral
            content block so the template is reused across signals.
        user: per-signal content (signal text + entities + context blocks).
        max_tokens: response cap. Opus default 4096; callers emitting
            longer Silver drafts bump this.
        extended_thinking: reserved for future use (thinking config
            support in the SDK). Currently a no-op — Step 5 doesn't need
            thinking mode in Phase 1 per B3 spec §1.2.
        model: override the env/default. Mostly for tests.
        client: inject a stubbed SDK client for tests; production omits.

    Returns:
        ``OpusResponse`` — text, tokens, cost, latency, stop reason, model id.

    Raises:
        AnthropicUnavailableError: transport / 5xx / 429 / timeout.
        OpusRequestError: 4xx user-error (bad request, auth, invalid model).
    """
    chosen_model = model or os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)
    cli = client or _get_client()

    system_blocks = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    kwargs: dict[str, Any] = {
        "model": chosen_model,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": [{"role": "user", "content": user}],
    }

    start = time.monotonic()
    try:
        response = cli.messages.create(**kwargs)
    except (APITimeoutError, APIConnectionError) as e:
        raise AnthropicUnavailableError(
            f"Anthropic transport failure: {e}"
        ) from e
    except RateLimitError as e:
        raise AnthropicUnavailableError(
            f"Anthropic rate limit (429): {e}"
        ) from e
    except APIStatusError as e:
        status = getattr(e, "status_code", None)
        if status is not None and 500 <= status < 600:
            raise AnthropicUnavailableError(
                f"Anthropic HTTP {status}: {e}"
            ) from e
        # Any non-5xx status from APIStatusError is a user error (4xx).
        raise OpusRequestError(
            f"Anthropic HTTP {status} (request error, not retryable): {e}"
        ) from e
    except APIError as e:
        # Catch-all for other SDK exceptions. Treat as transport failure
        # — conservative bias, caller's R3 ladder can decide to give up.
        raise AnthropicUnavailableError(
            f"Anthropic SDK error: {e}"
        ) from e
    latency_ms = int((time.monotonic() - start) * 1000)

    input_tok, output_tok, cache_read_tok, cache_write_tok = _extract_usage(
        getattr(response, "usage", None)
    )
    cost = _compute_cost_usd(
        input_tok, output_tok, cache_read_tok, cache_write_tok
    )
    text = _extract_text(getattr(response, "content", None))
    stop_reason = getattr(response, "stop_reason", None)
    response_model = getattr(response, "model", chosen_model)

    return OpusResponse(
        text=text,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cache_read_tokens=cache_read_tok,
        cache_write_tokens=cache_write_tok,
        cost_usd=cost,
        latency_ms=latency_ms,
        stop_reason=stop_reason,
        model_id=str(response_model),
    )
