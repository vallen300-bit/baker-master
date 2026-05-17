"""Tests for kbl.grok_client — xAI Grok Responses API + Live Search.

All HTTP is mocked via ``httpx.Client.request``. No live API contact in CI.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from kbl.grok_client import (
    GrokAuthError,
    GrokClient,
    GrokForbiddenError,
    GrokRateLimitError,
    GrokServerError,
    GrokTransportError,
    GrokValidationError,
    _cost_usd_from_usage,
    _flatten_output_text,
    _parse_retry_after,
    _shape_tweet_citation,
    _shape_web_citation,
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-stub-test-key-do-not-deploy")
    monkeypatch.delenv("XAI_BASE_URL", raising=False)


def _make_response(
    status_code: int,
    json_body: Any = None,
    *,
    headers: dict | None = None,
    text: str = "",
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.content = b"x" if json_body is not None or text else b""
    resp.text = text
    if json_body is not None:
        resp.json = MagicMock(return_value=json_body)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


def _make_http_client_mock(response_or_side_effect: Any) -> MagicMock:
    mock = MagicMock()
    if isinstance(response_or_side_effect, list):
        mock.request = MagicMock(side_effect=response_or_side_effect)
    else:
        mock.request = MagicMock(return_value=response_or_side_effect)
    mock.close = MagicMock(return_value=None)
    return mock


def _ask_response_body(text: str = "hello", **usage_overrides: Any) -> dict:
    usage = {"input_tokens": 32, "output_tokens": 9, "total_tokens": 41}
    usage.update(usage_overrides)
    return {
        "id": "resp-abc",
        "object": "response",
        "status": "completed",
        "model": "grok-4.3",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": usage,
    }


def _search_response_body(*, citations: list[Any], summary: str = "summary", model: str = "grok-4.3") -> dict:
    return {
        "id": "resp-search",
        "object": "response",
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": summary}],
            }
        ],
        "citations": citations,
        "usage": {"input_tokens": 64, "output_tokens": 256, "total_tokens": 320},
    }


# --------------------------- init / env ---------------------------


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(GrokAuthError, match="XAI_API_KEY"):
        GrokClient()


def test_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    client = GrokClient()
    assert client._base_url == "https://api.x.ai/v1"


def test_base_url_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_BASE_URL", "https://custom.example/v1/")
    client = GrokClient()
    assert client._base_url == "https://custom.example/v1"


def test_auth_header_uses_bearer() -> None:
    client = GrokClient()
    headers = client._headers()
    assert headers["Authorization"].startswith("Bearer xai-stub-test-key-")
    assert headers["Content-Type"] == "application/json"


# --------------------------- ask() happy path ---------------------------


def test_ask_parses_response_and_returns_text() -> None:
    body = _ask_response_body(text="hello world")
    http = _make_http_client_mock(_make_response(200, body))
    client = GrokClient(_http_client=http)
    out = client.ask("hi", max_output_tokens=100)
    assert out["text"] == "hello world"
    assert out["model"] == "grok-4.3"
    assert out["tokens_in"] == 32
    assert out["tokens_out"] == 9
    assert out["total_tokens"] == 41
    assert out["raw_id"] == "resp-abc"
    # cost: 32 * 1.25 + 9 * 2.50 = 40 + 22.5 = 62.5 / 1M = 0.0000625
    assert out["cost_usd"] == pytest.approx(0.0000625, rel=1e-3)


def test_ask_body_uses_default_model_and_passes_overrides() -> None:
    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    client = GrokClient(_http_client=http)
    client.ask(
        "compute pi",
        model="grok-4.20-0309-reasoning",
        max_output_tokens=200,
        temperature=0.3,
        instructions="be terse",
    )
    sent_body = http.request.call_args.kwargs["json"]
    assert sent_body["model"] == "grok-4.20-0309-reasoning"
    assert sent_body["input"] == "compute pi"
    assert sent_body["max_output_tokens"] == 200
    assert sent_body["temperature"] == 0.3
    assert sent_body["instructions"] == "be terse"
    # no search_parameters on plain ask
    assert "search_parameters" not in sent_body


# --------------------------- x_search() ---------------------------


def test_x_search_returns_summary_and_tweets() -> None:
    citations = [
        {
            "url": "https://x.com/elonmusk/status/123",
            "author": "elonmusk",
            "date": "2026-05-17T10:00:00Z",
            "text": "Grok 4.3 is live.",
            "favorite_count": 1234,
            "view_count": 50000,
            "repost_count": 200,
        },
        "https://x.com/xai/status/456",
    ]
    body = _search_response_body(citations=citations, summary="Two tweets.")
    http = _make_http_client_mock(_make_response(200, body))
    client = GrokClient(_http_client=http)
    out = client.x_search("Grok 4.3 launch", max_results=5)
    assert out["summary"] == "Two tweets."
    assert len(out["tweets"]) == 2
    assert out["tweets"][0]["author"] == "elonmusk"
    assert out["tweets"][0]["engagement"]["favorites"] == 1234
    assert out["tweets"][1]["url"] == "https://x.com/xai/status/456"
    # request body
    sent_body = http.request.call_args.kwargs["json"]
    sp = sent_body["search_parameters"]
    assert sp["mode"] == "on"
    assert sp["sources"] == [{"type": "x"}]
    assert sp["max_search_results"] == 5
    assert sp["return_citations"] is True


def test_web_search_adds_news_source_and_freshness_window() -> None:
    body = _search_response_body(citations=[], summary="empty")
    http = _make_http_client_mock(_make_response(200, body))
    client = GrokClient(_http_client=http)
    client.web_search("EU construction defect law 2026", freshness_days=14)
    sent_body = http.request.call_args.kwargs["json"]
    sp = sent_body["search_parameters"]
    assert {"type": "web"} in sp["sources"]
    assert {"type": "news"} in sp["sources"]
    assert "from_date" in sp  # freshness window applied


def test_web_search_skip_news_and_no_freshness() -> None:
    body = _search_response_body(citations=[])
    http = _make_http_client_mock(_make_response(200, body))
    client = GrokClient(_http_client=http)
    client.web_search("anything", freshness_days=None, include_news=False)
    sent_body = http.request.call_args.kwargs["json"]
    sp = sent_body["search_parameters"]
    assert sp["sources"] == [{"type": "web"}]
    assert "from_date" not in sp


def test_web_search_citations_are_shaped() -> None:
    citations = [
        {"url": "https://example.com/a", "title": "A", "date": "2026-05-10", "snippet": "snippet a"},
        {"link": "https://example.com/b", "description": "snippet b"},
    ]
    body = _search_response_body(citations=citations)
    http = _make_http_client_mock(_make_response(200, body))
    client = GrokClient(_http_client=http)
    out = client.web_search("q", freshness_days=None)
    assert out["citations"][0]["title"] == "A"
    assert out["citations"][1]["url"] == "https://example.com/b"
    assert out["citations"][1]["snippet"] == "snippet b"


# --------------------------- error mapping ---------------------------


def test_401_raises_auth_error() -> None:
    http = _make_http_client_mock(_make_response(401, {"error": "Invalid API key"}))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokAuthError, match="Invalid API key"):
        client.ask("x")


def test_403_raises_forbidden() -> None:
    http = _make_http_client_mock(_make_response(403, {"error": "forbidden"}))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokForbiddenError):
        client.ask("x")


def test_422_raises_validation_error() -> None:
    http = _make_http_client_mock(_make_response(422, {"error": "bad body"}))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokValidationError):
        client.ask("x")


def test_5xx_raises_server_error_no_retry() -> None:
    http = _make_http_client_mock(_make_response(503, {"error": "down"}))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokServerError):
        client.ask("x")
    assert http.request.call_count == 1, "5xx must not retry"


def test_non_json_2xx_raises_server_error() -> None:
    http = _make_http_client_mock(_make_response(200, None, text="not json"))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokServerError, match="non-JSON body"):
        client.ask("x")


# --------------------------- 429 retry ---------------------------


def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    ok_body = _ask_response_body()
    http = _make_http_client_mock(
        [
            _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "1"}),
            _make_response(200, ok_body),
        ]
    )
    client = GrokClient(_sleep=lambda s: sleeps.append(s), _http_client=http)
    out = client.ask("x")
    assert out["text"] == "hello"
    assert http.request.call_count == 2
    assert sleeps == [1.0]


def test_429_budget_exhaustion_raises() -> None:
    sleeps: list[float] = []
    rate_limited = _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "0"})
    http = _make_http_client_mock([rate_limited, rate_limited, rate_limited, rate_limited])
    client = GrokClient(max_retries=3, _sleep=lambda s: sleeps.append(s), _http_client=http)
    with pytest.raises(GrokRateLimitError, match="budget"):
        client.ask("x")
    assert http.request.call_count == 4


def test_parse_retry_after_fallback() -> None:
    assert _parse_retry_after(None) == 30.0
    assert _parse_retry_after("not-a-number") == 30.0
    assert _parse_retry_after("5") == 5.0


# --------------------------- transport errors ---------------------------


def test_timeout_raises_transport_error() -> None:
    http = MagicMock()
    http.request = MagicMock(side_effect=httpx.TimeoutException("slow"))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokTransportError, match="timeout"):
        client.ask("x")


def test_http_error_raises_transport_error() -> None:
    http = MagicMock()
    http.request = MagicMock(side_effect=httpx.ConnectError("refused"))
    client = GrokClient(_http_client=http)
    with pytest.raises(GrokTransportError, match="transport"):
        client.ask("x")


# --------------------------- shaping helpers ---------------------------


def test_flatten_output_text_handles_mixed_blocks() -> None:
    output = [
        {
            "type": "message",
            "content": [
                {"type": "reasoning", "text": "thinking..."},
                {"type": "output_text", "text": "answer "},
                {"type": "output_text", "text": "part two"},
            ],
        },
        # non-dict junk must be ignored
        "stray",
        {"type": "message", "content": "string content"},
    ]
    assert _flatten_output_text(output) == "answer part twostring content"


def test_shape_tweet_citation_handles_string_and_dict() -> None:
    assert _shape_tweet_citation("https://x.com/a/1")["url"] == "https://x.com/a/1"
    tweet = _shape_tweet_citation(
        {"url": "u", "handle": "h", "created_at": "d", "snippet": "s", "favorites": 5}
    )
    assert tweet["author"] == "h"
    assert tweet["date"] == "d"
    assert tweet["text"] == "s"
    assert tweet["engagement"]["favorites"] == 5


def test_shape_web_citation_handles_string_and_dict() -> None:
    assert _shape_web_citation("https://example.com")["url"] == "https://example.com"
    cite = _shape_web_citation({"link": "u", "title": "T", "published_at": "d", "description": "s"})
    assert cite["url"] == "u"
    assert cite["title"] == "T"
    assert cite["date"] == "d"
    assert cite["snippet"] == "s"


def test_cost_usd_prefers_ticks_when_provided() -> None:
    # 1 USD = 10^10 ticks per xAI docs: 12345 ticks → $1.2345e-6 ($0.0000012345)
    assert _cost_usd_from_usage({"cost_in_usd_ticks": 12345}) == pytest.approx(1.2345e-6)


def test_cost_usd_falls_back_to_token_rates() -> None:
    # 1M input + 1M output → 1.25 + 2.50 = 3.75
    assert _cost_usd_from_usage({"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(3.75)


def test_cost_usd_zero_when_empty() -> None:
    assert _cost_usd_from_usage({}) == 0.0


# --------------------------- http_client reuse ---------------------------


def test_http_client_reused_across_requests() -> None:
    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    client = GrokClient(_http_client=http)
    for _ in range(4):
        client.ask("x")
    assert http.request.call_count == 4


def test_close_releases_underlying_client() -> None:
    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    client = GrokClient(_http_client=http)
    client.close()
    http.close.assert_called_once()


# --------------------------- dispatch_grok cost-governor wiring ---------------------------


def test_dispatch_grok_logs_cost_after_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """dispatch_grok must call cost_monitor.log_api_cost with normalized token counts."""
    import tools.grok as grok_mod
    from kbl import grok_client as _client_mod

    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    monkeypatch.setattr(
        grok_mod,
        "_get_client",
        lambda: _client_mod.GrokClient(_http_client=http),
    )
    monkeypatch.setattr(
        "orchestrator.cost_monitor.check_circuit_breaker",
        lambda: (True, 0.0),
    )
    log_calls: list[dict] = []
    monkeypatch.setattr(
        "orchestrator.cost_monitor.log_api_cost",
        lambda **kwargs: log_calls.append(kwargs),
    )

    result = grok_mod.dispatch_grok("baker_grok_ask", {"prompt": "hi", "matter_slug": "hagenauer"})

    assert "Error" not in result
    assert len(log_calls) == 1
    call = log_calls[0]
    assert call["model"] == "grok-4.3"
    assert call["input_tokens"] == 32
    assert call["output_tokens"] == 9
    assert call["source"] == "grok_realtime"
    assert call["matter_slug"] == "hagenauer"


def test_dispatch_grok_blocks_when_circuit_breaker_tripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """When check_circuit_breaker returns (False, …), dispatch_grok must NOT call Grok."""
    import tools.grok as grok_mod
    from kbl import grok_client as _client_mod

    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    fake_client = _client_mod.GrokClient(_http_client=http)
    monkeypatch.setattr(grok_mod, "_get_client", lambda: fake_client)
    monkeypatch.setattr(
        "orchestrator.cost_monitor.check_circuit_breaker",
        lambda: (False, 150.00),
    )
    log_calls: list[dict] = []
    monkeypatch.setattr(
        "orchestrator.cost_monitor.log_api_cost",
        lambda **kwargs: log_calls.append(kwargs),
    )

    result = grok_mod.dispatch_grok("baker_grok_ask", {"prompt": "hi"})

    assert result.startswith("Error: cost circuit breaker tripped")
    assert "€150.00" in result
    assert http.request.call_count == 0
    assert log_calls == []


def test_dispatch_grok_cost_monitor_import_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """If cost_monitor.check_circuit_breaker raises, dispatch_grok still serves the call."""
    import tools.grok as grok_mod
    from kbl import grok_client as _client_mod

    http = _make_http_client_mock(_make_response(200, _ask_response_body()))
    monkeypatch.setattr(
        grok_mod,
        "_get_client",
        lambda: _client_mod.GrokClient(_http_client=http),
    )

    def _boom() -> None:
        raise RuntimeError("cost_monitor down")

    monkeypatch.setattr(
        "orchestrator.cost_monitor.check_circuit_breaker", _boom
    )
    monkeypatch.setattr(
        "orchestrator.cost_monitor.log_api_cost",
        lambda **kwargs: None,
    )

    result = grok_mod.dispatch_grok("baker_grok_ask", {"prompt": "hi"})
    assert "Error" not in result
    assert http.request.call_count == 1


# --------------------------- live smoke test (env-gated) ---------------------------


@pytest.mark.skipif(
    not os.environ.get("TEST_XAI_API_KEY"),
    reason="TEST_XAI_API_KEY env var not set — skipping live xAI smoke test",
)
def test_live_grok_ask_smoke() -> None:
    """One real Grok ask() call against the live xAI Responses API.

    Gated by ``TEST_XAI_API_KEY`` so CI stays green without the key. Mocks
    alone can't catch wire-format errors (e.g. input field shape, search_parameters
    vs tools array). Run locally with::

        TEST_XAI_API_KEY=<real-key> XAI_API_KEY=<real-key> \\
          pytest tests/test_grok_client.py::test_live_grok_ask_smoke -v
    """
    # Re-construct client so the autouse stub key fixture doesn't poison the call.
    real_key = os.environ["TEST_XAI_API_KEY"]
    client = GrokClient(api_key=real_key)
    try:
        out = client.ask("Say the word 'pong'. Nothing else.", max_output_tokens=16)
    finally:
        client.close()
    assert out["text"], "live grok ask returned empty text — wire format may be off"
    assert out["tokens_in"] > 0, "live grok ask returned zero input_tokens — usage block may be off"
