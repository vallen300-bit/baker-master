"""Tests for kbl.claimsmax_client — ClaimsMax v1 REST surface.

All HTTP is mocked via ``httpx.Client.request``. No live API contact in CI.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

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


def _make_http_client_mock(response_or_side_effect: Any) -> MagicMock:
    """Build a mock ``httpx.Client`` whose ``request`` returns a fixed response
    or iterates a side-effect sequence. Used as the ``_http_client`` injection
    point on ``ClaimsmaxClient`` — the client now holds httpx state instance-
    side so its connection pool is reused across requests."""
    mock = MagicMock()
    if isinstance(response_or_side_effect, list):
        mock.request = MagicMock(side_effect=response_or_side_effect)
    else:
        mock.request = MagicMock(return_value=response_or_side_effect)
    mock.close = MagicMock(return_value=None)
    return mock


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
    http = _make_http_client_mock(_make_response(200, body))
    client = ClaimsmaxClient(_http_client=http)
    out = client.search("Pagitsch defects", filters={"l1": ["report"]}, l3_tags_required=["x"])
    assert out["total"] == 2
    call = http.request.call_args
    assert call.args[0] == "POST"
    assert call.args[1].endswith("/search")
    sent_body = call.kwargs["json"]
    assert sent_body["query"] == "Pagitsch defects"
    assert sent_body["filters"] == {"l1": ["report"]}
    assert sent_body["l3_tags_required"] == ["x"]


def test_get_document_passes_include_text_param() -> None:
    http = _make_http_client_mock(_make_response(200, {"id": "doc-1"}))
    client = ClaimsmaxClient(_http_client=http)
    client.get_document("doc-1", include_text=True)
    assert http.request.call_args.kwargs["params"] == {"include_text": "true"}


def test_investigate_start_returns_run_id() -> None:
    http = _make_http_client_mock(_make_response(200, {"run_id": "r-1", "status": "running"}))
    client = ClaimsmaxClient(_http_client=http)
    out = client.investigate_start("find evidence", language="en")
    assert out == {"run_id": "r-1", "status": "running"}


def test_investigate_status_flow() -> None:
    """Two-call mock: still running, then complete. Same http client both calls
    — verifies the instance reuses its pooled httpx client (no re-init)."""
    running = _make_response(200, {"run_id": "r-1", "status": "running", "step_count": 3})
    complete = _make_response(
        200,
        {"run_id": "r-1", "status": "complete", "step_count": 12, "report": "# done"},
    )
    http = _make_http_client_mock([running, complete])
    client = ClaimsmaxClient(_http_client=http)
    first = client.investigate_status("r-1")
    second = client.investigate_status("r-1")
    assert first["status"] == "running"
    assert second["status"] == "complete"
    assert second["report"] == "# done"
    assert http.request.call_count == 2


def test_http_client_reused_across_requests() -> None:
    """M1 regression guard: the underlying httpx.Client is held instance-side
    so its connection pool survives across calls (no per-request rebuild)."""
    http = _make_http_client_mock(_make_response(200, {"ok": True}))
    client = ClaimsmaxClient(_http_client=http)
    for _ in range(5):
        client._request("GET", "anything")
    assert http.request.call_count == 5


def test_close_releases_underlying_client() -> None:
    http = _make_http_client_mock(_make_response(200, {"ok": True}))
    client = ClaimsmaxClient(_http_client=http)
    client.close()
    http.close.assert_called_once()


# --------------------------- error mapping ---------------------------


def test_401_raises_auth_error() -> None:
    http = _make_http_client_mock(_make_response(401, {"detail": "Invalid API key"}))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxAuthError, match="Invalid API key"):
        client.search("x")


def test_404_raises_not_found() -> None:
    http = _make_http_client_mock(_make_response(404, {"detail": "Document not found"}))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxNotFoundError, match="Document not found"):
        client.get_document("missing")


def test_422_raises_validation_error() -> None:
    http = _make_http_client_mock(_make_response(422, {"detail": "bad body"}))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxValidationError):
        client.search("x")


def test_5xx_raises_server_error_no_retry() -> None:
    http = _make_http_client_mock(_make_response(503, {"detail": "down"}))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxServerError):
        client.search("x")
    assert http.request.call_count == 1, "5xx must not retry"


# --------------------------- 429 retry ---------------------------


def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    body_ok = {"total": 0, "results": []}
    http = _make_http_client_mock(
        [
            _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "1"}),
            _make_response(200, body_ok),
        ]
    )
    client = ClaimsmaxClient(_sleep=lambda s: sleeps.append(s), _http_client=http)
    out = client.search("x")
    assert out == body_ok
    assert http.request.call_count == 2
    assert sleeps == [1.0]


def test_429_budget_exhaustion_raises() -> None:
    sleeps: list[float] = []
    rate_limited = _make_response(429, {"error": "rate_limited"}, headers={"Retry-After": "0"})
    # 1 initial + 3 retries = 4 attempts; after 3 retries we raise.
    http = _make_http_client_mock([rate_limited, rate_limited, rate_limited, rate_limited])
    client = ClaimsmaxClient(max_retries=3, _sleep=lambda s: sleeps.append(s), _http_client=http)
    with pytest.raises(ClaimsmaxRateLimitError, match="budget"):
        client.search("x")
    assert http.request.call_count == 4


def test_parse_retry_after_fallback() -> None:
    assert _parse_retry_after(None) == 30.0
    assert _parse_retry_after("not-a-number") == 30.0
    assert _parse_retry_after("5") == 5.0


# --------------------------- transport errors ---------------------------


def test_timeout_raises_transport_error() -> None:
    http = MagicMock()
    http.request = MagicMock(side_effect=httpx.TimeoutException("slow"))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxTransportError, match="timeout"):
        client.search("x")


def test_http_error_raises_transport_error() -> None:
    http = MagicMock()
    http.request = MagicMock(side_effect=httpx.ConnectError("refused"))
    client = ClaimsmaxClient(_http_client=http)
    with pytest.raises(ClaimsmaxTransportError, match="transport"):
        client.search("x")


# --------------------------- /ask ---------------------------


_ASK_RESPONSE_FIXTURE: dict[str, Any] = {
    "question": "What is the Pagitsch defect count?",
    "language": "en",
    "model": "claude-opus-4-8",
    "answer": "Per the audit, 14 defects remain open [D1].",
    "citations": [
        {
            "id": "D1",
            "doc_id": "11111111-1111-1111-1111-111111111111",
            "original_filename": "audit.pdf",
            "doc_date": "2026-05-01",
            "l1": "report",
            "l2": "audit",
            "chunk_index": 3,
            "score": 0.91,
            "snippet": "14 defects open as of audit close.",
        }
    ],
    "used_chunks": [
        {
            "citation_id": "D1",
            "doc_id": "11111111-1111-1111-1111-111111111111",
            "chunk_index": 3,
            "score": 0.91,
        }
    ],
    "confidence": 0.585,
    "query_terms": ["pagitsch", "defect"],
    "retrieval": {
        "docs_considered": 24,
        "docs_included": 5,
        "total_context_chars": 18000,
        "chunks_searched": 412,
        "query_ms": 220,
        "generation_ms": 17480,
        "total_ms": 17700,
    },
}


def test_ask_returns_response() -> None:
    http = _make_http_client_mock(_make_response(200, _ASK_RESPONSE_FIXTURE))
    client = ClaimsmaxClient(_http_client=http)
    out = client.ask(question="What is the Pagitsch defect count?", claim_id="c-7")
    assert out["answer"].startswith("Per the audit")
    assert out["citations"][0]["id"] == "D1"
    assert out["confidence"] == 0.585
    assert out["retrieval"]["docs_considered"] == 24
    call = http.request.call_args
    assert call.args[0] == "POST"
    assert call.args[1].endswith("/ask")
    sent_body = call.kwargs["json"]
    assert sent_body["question"] == "What is the Pagitsch defect count?"
    assert sent_body["claim_id"] == "c-7"
    assert sent_body["language"] == "en"
    assert out["query_terms"] == ["pagitsch", "defect"]


def test_ask_omits_claim_id_when_none() -> None:
    http = _make_http_client_mock(_make_response(200, _ASK_RESPONSE_FIXTURE))
    client = ClaimsmaxClient(_http_client=http)
    client.ask(question="anything")
    sent_body = http.request.call_args.kwargs["json"]
    assert "claim_id" not in sent_body
    assert sent_body["language"] == "en"


# --------------------------- MCP dispatch surface ---------------------------


def test_mcp_baker_claimsmax_ask_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """baker_claimsmax_ask round-trips the client payload as JSON."""
    import json as _json

    from tools import claimsmax as claimsmax_tools

    stub = MagicMock()
    stub.ask = MagicMock(return_value=_ASK_RESPONSE_FIXTURE)
    monkeypatch.setattr(claimsmax_tools, "_get_client", lambda: stub)

    out = claimsmax_tools.dispatch_claimsmax(
        "baker_claimsmax_ask",
        {"question": "What is the Pagitsch defect count?", "claim_id": "c-7"},
    )

    parsed = _json.loads(out)
    assert parsed["answer"].startswith("Per the audit")
    assert parsed["citations"][0]["id"] == "D1"
    stub.ask.assert_called_once_with(
        question="What is the Pagitsch defect count?",
        claim_id="c-7",
        language="en",
    )


def test_mcp_baker_claimsmax_ask_dispatch_omits_claim_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch path forwards claim_id=None when caller omits it."""
    from tools import claimsmax as claimsmax_tools

    stub = MagicMock()
    stub.ask = MagicMock(return_value=_ASK_RESPONSE_FIXTURE)
    monkeypatch.setattr(claimsmax_tools, "_get_client", lambda: stub)

    claimsmax_tools.dispatch_claimsmax(
        "baker_claimsmax_ask", {"question": "anything"}
    )

    stub.ask.assert_called_once_with(question="anything", claim_id=None, language="en")


def test_mcp_baker_claimsmax_ask_registered() -> None:
    """Catalog + name set carry the new tool."""
    from tools.claimsmax import CLAIMSMAX_TOOL_NAMES, CLAIMSMAX_TOOLS

    assert "baker_claimsmax_ask" in CLAIMSMAX_TOOL_NAMES
    tool = next(t for t in CLAIMSMAX_TOOLS if t.name == "baker_claimsmax_ask")
    props = tool.inputSchema["properties"]
    assert "question" in props
    assert "claim_id" in props
    assert "language" in props
    assert tool.inputSchema["required"] == ["question"]
