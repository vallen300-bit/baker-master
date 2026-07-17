"""DROPBOX_SEARCH_TOOL_1 — vertical tests for baker_dropbox_search.

Covers DropboxClient.search() + _resolve_path_root_header() (mocked httpx) and the
_dispatch("baker_dropbox_search", ...) MCP surface. No network, no live Dropbox.

Fail-closed contract (codex G0 #12338/#12343): a path-root resolution failure MUST
raise DropboxPathRootError — never a plausible home-namespace-only result.
"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from triggers import dropbox_client as dbx
from triggers.dropbox_client import DropboxClient, DropboxPathRootError
from baker_mcp import baker_mcp_server as srv


def _make_client(monkeypatch, handler):
    """Build a DropboxClient with a pre-set token and a MockTransport-backed client
    so no request ever hits the network."""
    def _fake_token_post(url, data=None, timeout=None):
        return httpx.Response(
            200,
            json={"access_token": "tok", "expires_in": 14400},
            request=httpx.Request("POST", url),
        )

    # Stub module-level token refresh so __init__ / _ensure_token never call out.
    monkeypatch.setattr(dbx.httpx, "post", _fake_token_post)
    client = DropboxClient()
    client._access_token = "tok"
    client._token_expires_at = time.time() + 9999
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


_TEAM_ACCOUNT = {"root_info": {"root_namespace_id": "NS_ROOT", "home_namespace_id": "NS_HOME"}}


def _search_matches_response():
    return httpx.Response(200, json={"matches": [
        {
            "match_type": {".tag": "filename"},
            "metadata": {"metadata": {
                ".tag": "file",
                "path_display": "/Swiss Projects/x.pdf",
                "name": "x.pdf",
                "server_modified": "2026-01-01T00:00:00Z",
                "size": 100,
            }},
        },
        # non-file entry must be skipped
        {"metadata": {"metadata": {".tag": "folder", "path_display": "/dir"}}},
    ]})


# ---------------------------------------------------------------------------
# (a) search() parses matches + applies path-root header on a team-space account
# ---------------------------------------------------------------------------
def test_search_parses_matches_and_applies_path_root(monkeypatch):
    captured = {}

    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            return httpx.Response(200, json=_TEAM_ACCOUNT)
        if "search_v2" in url:
            captured["path_root"] = request.headers.get("Dropbox-API-Path-Root")
            return _search_matches_response()
        return httpx.Response(404)

    client = _make_client(monkeypatch, handler)
    results = client.search("Hagenauer")

    assert len(results) == 1
    assert results[0]["path"] == "/Swiss Projects/x.pdf"
    assert results[0]["name"] == "x.pdf"
    assert results[0]["match_type"] == "filename"
    assert results[0]["size_bytes"] == 100
    # header pinned to the TEAM root namespace, not home
    assert captured["path_root"] == json.dumps({".tag": "root", "root": "NS_ROOT"})


# ---------------------------------------------------------------------------
# get_current_account must send the literal `null` body, not an empty body.
# Dropbox no-arg RPC endpoints 500 on an empty body + JSON content-type
# (verified live 2026-07-17). Regression lock for the brief's wrong assumption.
# ---------------------------------------------------------------------------
def test_get_current_account_sends_literal_null_body(monkeypatch):
    captured = {}

    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            captured["body"] = request.content
            captured["ctype"] = request.headers.get("Content-Type")
            return httpx.Response(200, json=_TEAM_ACCOUNT)
        if "search_v2" in url:
            return _search_matches_response()
        return httpx.Response(404)

    client = _make_client(monkeypatch, handler)
    client.search("x")
    assert captured["body"] == b"null"
    assert captured["ctype"] == "application/json"


# ---------------------------------------------------------------------------
# Non-team account (root_ns == home_ns) → no path-root header sent
# ---------------------------------------------------------------------------
def test_search_no_path_root_header_for_non_team_account(monkeypatch):
    captured = {}

    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            return httpx.Response(200, json={"root_info": {"root_namespace_id": "NS", "home_namespace_id": "NS"}})
        if "search_v2" in url:
            captured["path_root"] = request.headers.get("Dropbox-API-Path-Root")
            return _search_matches_response()
        return httpx.Response(404)

    client = _make_client(monkeypatch, handler)
    results = client.search("x")
    assert len(results) == 1
    assert captured["path_root"] is None


# ---------------------------------------------------------------------------
# (b) _dispatch formats results
# ---------------------------------------------------------------------------
def test_dispatch_formats_results(monkeypatch):
    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            return httpx.Response(200, json=_TEAM_ACCOUNT)
        if "search_v2" in url:
            return _search_matches_response()
        return httpx.Response(404)

    client = _make_client(monkeypatch, handler)
    monkeypatch.setattr(DropboxClient, "_get_global_instance", classmethod(lambda cls: client))

    out = srv._dispatch("baker_dropbox_search", {"query": "Hagenauer"})
    assert "Dropbox Search — 1 match(es) for 'Hagenauer'" in out
    assert "/Swiss Projects/x.pdf" in out
    assert "filename" in out


def test_dispatch_no_matches_message(monkeypatch):
    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            return httpx.Response(200, json=_TEAM_ACCOUNT)
        return httpx.Response(200, json={"matches": []})

    client = _make_client(monkeypatch, handler)
    monkeypatch.setattr(DropboxClient, "_get_global_instance", classmethod(lambda cls: client))
    out = srv._dispatch("baker_dropbox_search", {"query": "zzz"})
    assert out == "No Dropbox matches for 'zzz'."


# ---------------------------------------------------------------------------
# (c) empty query → error string (no client needed; returns before instantiation)
# ---------------------------------------------------------------------------
def test_dispatch_empty_query_returns_error():
    assert srv._dispatch("baker_dropbox_search", {"query": "   "}) == "Error: query is required."
    assert srv._dispatch("baker_dropbox_search", {}) == "Error: query is required."


# ---------------------------------------------------------------------------
# (d) HTTPStatusError surfaces status + body excerpt (Lesson #97)
# ---------------------------------------------------------------------------
def test_dispatch_surfaces_http_error_status_and_body(monkeypatch):
    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            return httpx.Response(200, json=_TEAM_ACCOUNT)
        return httpx.Response(500, text="error_summary/search_failed/boom")

    client = _make_client(monkeypatch, handler)
    monkeypatch.setattr(DropboxClient, "_get_global_instance", classmethod(lambda cls: client))
    out = srv._dispatch("baker_dropbox_search", {"query": "x"})
    assert out.startswith("Error: dropbox search failed:")
    assert "status=500" in out
    assert "error_summary/search_failed/boom" in out


# ---------------------------------------------------------------------------
# (e) FAIL-CLOSED: get_current_account failure → DropboxPathRootError, not cached
# ---------------------------------------------------------------------------
def test_search_fails_closed_on_path_root_resolution_failure(monkeypatch):
    calls = {"account": 0}

    def handler(request):
        url = str(request.url)
        if "get_current_account" in url:
            calls["account"] += 1
            return httpx.Response(500, text="account boom")
        if "search_v2" in url:
            raise AssertionError("search_v2 must NOT run while path-root is unresolved")
        return httpx.Response(404)

    client = _make_client(monkeypatch, handler)

    with pytest.raises(DropboxPathRootError) as ei:
        client.search("x")
    assert "refusing home-namespace fallback" in str(ei.value)

    # not cached — leaves resolver unresolved for retry
    assert client._path_root_header is None

    with pytest.raises(DropboxPathRootError):
        client.search("x")
    # resolver was attempted again (not silently degraded to a cached empty header)
    assert calls["account"] == 2
