"""Tests for kbl.voyage_client — minimal urllib-based embedder wrapper."""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import VoyageUnavailableError
from kbl.voyage_client import embed


def _fake_response(payload: dict):
    ctx = MagicMock()
    ctx.read.return_value = json.dumps(payload).encode("utf-8")
    ctx.__enter__ = lambda self: ctx
    ctx.__exit__ = lambda self, *a: False
    return ctx


def test_embed_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    payload = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response(payload)
        out = embed("hello")
    assert out == [0.1, 0.2, 0.3]
    req = m_open.call_args.args[0]
    assert req.full_url == "https://api.voyageai.com/v1/embeddings"
    body = json.loads(req.data.decode("utf-8"))
    assert body["input"] == ["hello"]
    assert body["model"] == "voyage-3"
    assert req.headers["Authorization"] == "Bearer test-key"


def test_embed_host_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    monkeypatch.setenv("VOYAGE_API_HOST", "https://proxy.example")
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response({"data": [{"embedding": [0.0]}]})
        embed("x")
    assert m_open.call_args.args[0].full_url == "https://proxy.example/v1/embeddings"


def test_embed_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    monkeypatch.setenv("KBL_VOYAGE_MODEL", "voyage-large-2")
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response({"data": [{"embedding": [0.0]}]})
        embed("x")
    body = json.loads(m_open.call_args.args[0].data.decode("utf-8"))
    assert body["model"] == "voyage-large-2"


def test_embed_empty_text_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with pytest.raises(ValueError, match="non-empty text"):
        embed("")


def test_embed_missing_api_key_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
        embed("hello")


def test_embed_http_error_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "http://x", 503, "service unavailable", {}, None
        ),
    ):
        with pytest.raises(VoyageUnavailableError, match="HTTP 503"):
            embed("x")


def test_embed_timeout_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
        with pytest.raises(VoyageUnavailableError, match="unreachable"):
            embed("x", timeout=1)


def test_embed_url_error_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(VoyageUnavailableError, match="unreachable"):
            embed("x")


def test_embed_malformed_envelope_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with patch("urllib.request.urlopen") as m_open:
        bad = MagicMock()
        bad.read.return_value = b"not json"
        bad.__enter__ = lambda self: bad
        bad.__exit__ = lambda self, *a: False
        m_open.return_value = bad
        with pytest.raises(VoyageUnavailableError, match="non-JSON envelope"):
            embed("x")


def test_embed_response_missing_embedding_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "k")
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response({"data": []})
        with pytest.raises(VoyageUnavailableError, match="missing data"):
            embed("x")
