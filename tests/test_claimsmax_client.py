"""Tests for kbl.claimsmax_client — ClaimsMax v1 REST surface.

All HTTP is mocked via ``httpx.Client.request``. No live API contact in CI.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from kbl import claimsmax_client
from kbl.claimsmax_client import (
    ClaimsmaxAuthError,
    ClaimsmaxClient,
    ClaimsmaxNotFoundError,
    ClaimsmaxRateLimitError,
    ClaimsmaxServerError,
    ClaimsmaxTransportError,
    ClaimsmaxValidationError,
    _parse_retry_after,
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAIMSMAX_API_KEY", "stub-test-key-do-not-deploy")
    monkeypatch.delenv("CLAIMSMAX_BASE_URL", raising=False)


def _make_response(status_code: int, json_body: Any = None, *, headers: dict | None = None, text: str = "") -> MagicMock:
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


def _patched_client(response_or_side_effect: Any):
    """Patch ``httpx.Client`` to return a context manager whose ``request``
    yields either a single response or a side_effect sequence."""
    inner = MagicMock()
    if isinstance(response_or_side_effect, list):
        inner.request = MagicMock(side_effect=response_or_side_effect)
    else:
        inner.request = MagicMock(return_value=response_or_side_effect)
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    return patch.object(claimsmax_client.httpx, "Client", return_value=ctx), inner


# --------------------------- init / env ---------------------------


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAIMSMAX_API_KEY", raising=False)
    with pytest.raises(ClaimsmaxAuthError, match="CLAIMSMAX_API_KEY"):
        ClaimsmaxClient()


def test_default_base_url_trailing_slash_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAIMSMAX_BASE_URL", "https://custom.example/api/v1")  # no trailing slash
    client = ClaimsmaxClient()
    assert client._base_url == "https://custom.example/api/v1/"


def test_auth_header_uses_bearer() -> None:
    client = ClaimsmaxClient()
    headers = client._headers()
    assert headers["Authorization"].startswith("Bearer stub-test-key-")


# --------------------------- happy path ---------------------------


def test_search_parses_response() -> None:
    body = {"total": 2, "page": 1, "per_page": 25, "results": [{"doc_id": "abc"}], "query_ms": 50}
    p, inner = _patched_client(_make_response(200, body))
    with p:
        client = ClaimsmaxClient()
        out = client.search("Pagitsch defects", filters={"l1": ["report"]}, l3_tags_required=["x"])
    assert out["total"] == 2
    call = inner.request.call_args
    assert call.args[0] == "POST"
    assert call.args[1].endswith("/search")
    sent_body = call.kwargs["json"]
    assert sent_body["query"] == "Pagitsch defects"
    assert sent_body["filters"] == {"l1": ["report"]}
    assert sent_body["l3_tags_required"] == ["x"]


def test_get_document_passes_include_text_param() -> None:
    p, inner = _patched_client(_make_response(200, {"id": "doc-1"}))
    with p:
        client = ClaimsmaxClient()
        client.get_document("doc-1", include_text=True)
    assert inner.request.call_args.kwargs["params"] == {"include_text": "true"}


def test_investigate_start_returns_run_id() -> None:
    p, inner = _patched_client(_make_response(200, {"run_id": "r-1", "status": "running"}))
    with p:
        client = ClaimsmaxClient()
        out = client.investigate_start("find evidence", language="en")
    assert out == {"run_id": "r-1", "status": "running"}


def test_investigate_status_flow() -> None:
    """Two-call mock: still running, then complete."""
    running = _make_response(200, {"run_id": "r-1", "status": "running", "step_count": 3})
    complete = _make_response(
        200,
        {"run_id": "r-1", "status": "complete", "step_count": 12, "report": "# done"},
    )
    p, _inner = _patched_client([running, complete])
    with p:
        client = ClaimsmaxClient()
        first = client.investigate_status("r-1")
        second = client.investigate_status("r-1")
    assert first["status"] == "running"
    assert second["status"] == "complete"
    assert second["report"] == "# done"


# --------------------------- error mapping ---------------------------


def test_401_raises_auth_error() -> None:
    p, _ = _patched_client(_make_response(401, {"detail": "Invalid API key"}))
    with p:
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxAuthError, match="Invalid API key"):
            client.search("x")


def test_404_raises_not_found() -> None:
    p, _ = _patched_client(_make_response(404, {"detail": "Document not found"}))
    with p:
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxNotFoundError, match="Document not found"):
            client.get_document("missing")


def test_422_raises_validation_error() -> None:
    p, _ = _patched_client(_make_response(422, {"detail": "bad body"}))
    with p:
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxValidationError):
            client.search("x")


def test_5xx_raises_server_error_no_retry() -> None:
    p, inner = _patched_client(_make_response(503, {"detail": "down"}))
    with p:
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxServerError):
            client.search("x")
    assert inner.request.call_count == 1, "5xx must not retry"


# --------------------------- 429 retry ---------------------------


def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    body_ok = {"total": 0, "results": []}
    p, inner = _patched_client(
        [
            _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "1"}),
            _make_response(200, body_ok),
        ]
    )
    with p:
        client = ClaimsmaxClient(_sleep=lambda s: sleeps.append(s))
        out = client.search("x")
    assert out == body_ok
    assert inner.request.call_count == 2
    assert sleeps == [1.0]


def test_429_budget_exhaustion_raises() -> None:
    sleeps: list[float] = []
    rate_limited = _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "0"})
    # 1 initial + 3 retries = 4 attempts; after 3 retries we raise.
    p, inner = _patched_client([rate_limited, rate_limited, rate_limited, rate_limited])
    with p:
        client = ClaimsmaxClient(max_retries=3, _sleep=lambda s: sleeps.append(s))
        with pytest.raises(ClaimsmaxRateLimitError, match="budget"):
            client.search("x")
    assert inner.request.call_count == 4


def test_parse_retry_after_fallback() -> None:
    assert _parse_retry_after(None) == 30.0
    assert _parse_retry_after("not-a-number") == 30.0
    assert _parse_retry_after("5") == 5.0


# --------------------------- transport errors ---------------------------


def test_timeout_raises_transport_error() -> None:
    inner = MagicMock()
    inner.request = MagicMock(side_effect=httpx.TimeoutException("slow"))
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch.object(claimsmax_client.httpx, "Client", return_value=ctx):
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxTransportError, match="timeout"):
            client.search("x")


def test_http_error_raises_transport_error() -> None:
    inner = MagicMock()
    inner.request = MagicMock(side_effect=httpx.ConnectError("refused"))
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch.object(claimsmax_client.httpx, "Client", return_value=ctx):
        client = ClaimsmaxClient()
        with pytest.raises(ClaimsmaxTransportError, match="transport"):
            client.search("x")


# --------------------------- /ask placeholder ---------------------------


def test_ask_raises_not_implemented() -> None:
    client = ClaimsmaxClient()
    with pytest.raises(NotImplementedError, match="vendor bug"):
        client.ask(question="anything")
