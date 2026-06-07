"""Tests for kbl.perplexity_client — Perplexity Sonar chat-completions API.

All HTTP is mocked via a fake httpx.Client.request. No live API contact in CI.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from kbl.perplexity_client import (
    PerplexityAuthError,
    PerplexityClient,
    PerplexityForbiddenError,
    PerplexityRateLimitError,
    PerplexityServerError,
    PerplexityTransportError,
    PerplexityValidationError,
    _cost_usd_from_usage,
    _merge_citations,
    _parse_retry_after,
    _shape_ask_response,
    _shape_citation,
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-stub-test-key-do-not-deploy")
    monkeypatch.delenv("PERPLEXITY_BASE_URL", raising=False)


def _make_response(status_code, json_body=None, *, headers=None, text=""):
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


def _http_mock(response_or_list):
    mock = MagicMock()
    if isinstance(response_or_list, list):
        mock.request = MagicMock(side_effect=response_or_list)
    else:
        mock.request = MagicMock(return_value=response_or_list)
    mock.close = MagicMock(return_value=None)
    return mock


def _completion_body(text="hello", *, citations=None, search_results=None, model="sonar", **usage):
    u = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    u.update(usage)
    body: dict[str, Any] = {
        "id": "cmpl-abc",
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": u,
    }
    if citations is not None:
        body["citations"] = citations
    if search_results is not None:
        body["search_results"] = search_results
    return body


# ── construction ─────────────────────────────────────────────────────────────

def test_missing_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    with pytest.raises(PerplexityAuthError):
        PerplexityClient()


def test_explicit_key_overrides_env(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    c = PerplexityClient(api_key="explicit", _http_client=_http_mock(_make_response(200, {})))
    assert c._api_key == "explicit"


# ── ask happy path + shaping ─────────────────────────────────────────────────

def test_ask_returns_shaped_payload():
    body = _completion_body(
        "Mandarin Oriental Vienna is Brisen-owned.",
        search_results=[{"title": "MO VIE", "url": "https://mo.test/vie", "date": "2026-01-01"}],
        citations=["https://mo.test/vie", "https://other.test/x"],
    )
    client = PerplexityClient(_http_client=_http_mock(_make_response(200, body)))
    out = client.ask("who owns MO Vienna")
    assert out["text"] == "Mandarin Oriental Vienna is Brisen-owned."
    assert out["model"] == "sonar"
    assert out["tokens_in"] == 20 and out["tokens_out"] == 10
    # rich search_result wins the URL tie; the second bare citation is kept
    assert out["citations"][0] == {"url": "https://mo.test/vie", "title": "MO VIE",
                                   "date": "2026-01-01", "snippet": ""}
    assert out["citations"][1]["url"] == "https://other.test/x"


def test_ask_sends_instructions_as_system_message():
    captured = {}
    def _req(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _make_response(200, _completion_body())
    http = MagicMock(); http.request = MagicMock(side_effect=_req); http.close = MagicMock()
    client = PerplexityClient(_http_client=http)
    client.ask("q", instructions="be terse", search_domain_filter=["sec.gov"])
    assert captured["messages"][0] == {"role": "system", "content": "be terse"}
    assert captured["messages"][1] == {"role": "user", "content": "q"}
    assert captured["search_domain_filter"] == ["sec.gov"]


# ── error mapping ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,exc", [
    (401, PerplexityAuthError),
    (403, PerplexityForbiddenError),
    (422, PerplexityValidationError),
    (500, PerplexityServerError),
])
def test_http_error_mapping(status, exc):
    client = PerplexityClient(_http_client=_http_mock(_make_response(status, {"error": {"message": "x"}})))
    with pytest.raises(exc):
        client.ask("q")


def test_429_retries_then_succeeds():
    seq = [_make_response(429, {}, headers={"Retry-After": "0"}),
           _make_response(200, _completion_body("ok"))]
    client = PerplexityClient(_http_client=_http_mock(seq), _sleep=lambda *_: None)
    assert client.ask("q")["text"] == "ok"


def test_429_exhausts_retry_budget():
    seq = [_make_response(429, {}, headers={"Retry-After": "0"}) for _ in range(5)]
    client = PerplexityClient(_http_client=_http_mock(seq), max_retries=2, _sleep=lambda *_: None)
    with pytest.raises(PerplexityRateLimitError):
        client.ask("q")


def test_transport_error_mapped():
    http = MagicMock()
    http.request = MagicMock(side_effect=httpx.TimeoutException("boom"))
    http.close = MagicMock()
    client = PerplexityClient(_http_client=http)
    with pytest.raises(PerplexityTransportError):
        client.ask("q")


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_shape_citation_string_and_dict():
    assert _shape_citation("https://a.test")["url"] == "https://a.test"
    d = _shape_citation({"url": "https://b.test", "title": "T", "date": "2026", "snippet": "s"})
    assert d == {"url": "https://b.test", "title": "T", "date": "2026", "snippet": "s"}


def test_merge_citations_dedups_by_url_rich_wins():
    payload = {
        "search_results": [{"title": "rich", "url": "https://dup.test"}],
        "citations": ["https://dup.test", "https://unique.test"],
    }
    merged = _merge_citations(payload)
    urls = [c["url"] for c in merged]
    assert urls == ["https://dup.test", "https://unique.test"]
    assert merged[0]["title"] == "rich"  # rich source won the tie


def test_parse_retry_after_fallback():
    assert _parse_retry_after(None) == 30.0
    assert _parse_retry_after("nonsense") == 30.0
    assert _parse_retry_after("5") == 5.0


def test_cost_usd_from_usage_by_model():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert _cost_usd_from_usage(usage, "sonar") == round(2.00, 8)
    assert _cost_usd_from_usage(usage, "sonar-pro") == round(18.00, 8)
    assert _cost_usd_from_usage({}, "sonar") == 0.0


def test_shape_ask_response_tolerates_empty_choices():
    out = _shape_ask_response({"model": "sonar", "usage": {}}, "sonar")
    assert out["text"] == "" and out["citations"] == []
