"""
Integration tests for the /api/scan SSE endpoint.
Tests the endpoint contract; does NOT require live Claude API.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    # Patch heavy dependencies before importing the app
    with patch("outputs.dashboard._get_retriever") as mock_ret, \
         patch("outputs.dashboard._get_store") as mock_store, \
         patch("outputs.dashboard.anthropic") as mock_anthropic:

        # Mock retriever returns empty context
        mock_retriever_inst = MagicMock()
        mock_retriever_inst.search_all_collections.return_value = []
        mock_ret.return_value = mock_retriever_inst

        # Mock store
        mock_store_inst = MagicMock()
        mock_store_inst.log_decision.return_value = 1
        mock_store.return_value = mock_store_inst

        # Mock Claude streaming
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_stream_ctx.text_stream = iter(["Hello", " from", " Baker"])

        mock_claude = MagicMock()
        mock_claude.messages.stream.return_value = mock_stream_ctx
        mock_anthropic.Anthropic.return_value = mock_claude

        from outputs.dashboard import app
        yield TestClient(app)


def test_scan_returns_sse_stream(client):
    """POST /api/scan should return text/event-stream with data lines."""
    resp = client.post(
        "/api/scan",
        json={"question": "What deals are active?"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    body = resp.text
    # Should contain SSE data lines
    assert "data:" in body
    # Should end with [DONE]
    assert "[DONE]" in body


def test_scan_rejects_empty_question(client):
    """POST /api/scan should reject empty question."""
    resp = client.post("/api/scan", json={"question": ""})
    assert resp.status_code == 422  # Pydantic validation error


def test_scan_accepts_history(client):
    """POST /api/scan should accept history array."""
    resp = client.post(
        "/api/scan",
        json={
            "question": "Tell me more about that",
            "history": [
                {"role": "user", "content": "What is the Atlas deal?"},
                {"role": "assistant", "content": "The Atlas deal is..."},
            ],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
