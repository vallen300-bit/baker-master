"""Tests for BAKER_MCP_EXTENSION_1 — 4 new MCP tools wrapping live REST endpoints.

Brief: ``briefs/BRIEF_BAKER_MCP_EXTENSION_1.md``.

Tools exercised:
  - ``baker_scan``           → POST /api/scan or /api/scan/client-pm (SSE)
  - ``baker_search``         → GET /api/search/unified
  - ``baker_ingest_text``    → POST /api/ingest (multipart, text-only)
  - ``baker_health``         → GET /health (public)

All HTTP traffic is stubbed via ``httpx.MockTransport`` so the suite is
hermetic — no live Baker required.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

from baker_mcp import baker_mcp_server as srv


# --------------------------------------------------------------------------
# Helpers — build httpx.MockTransport plumbing and inject into srv.httpx.Client
# --------------------------------------------------------------------------


@pytest.fixture
def patch_httpx(monkeypatch):
    """Yield a setter that replaces ``srv.httpx.Client`` with a Mock-Transport-
    backed client routed at a user-supplied request handler.

    Usage::

        def handler(request: httpx.Request) -> httpx.Response: ...
        patch_httpx(handler)
    """

    def _install(handler, *, raise_on_request=None):
        """Install a transport. If raise_on_request is set, transport raises that
        exception on every request (used to simulate timeouts / network errors)."""

        if raise_on_request is not None:
            def _err_handler(request: httpx.Request) -> httpx.Response:
                raise raise_on_request

            transport = httpx.MockTransport(_err_handler)
        else:
            transport = httpx.MockTransport(handler)

        # Capture the original Client class so timeout-positional kwargs etc. still work.
        OriginalClient = httpx.Client

        class _PatchedClient(OriginalClient):
            def __init__(self, *args, **kwargs):
                kwargs.pop("transport", None)
                super().__init__(*args, transport=transport, **kwargs)

        monkeypatch.setattr(srv.httpx, "Client", _PatchedClient)
        return transport

    return _install


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Pin BAKER_INTERNAL_URL + BAKER_API_KEY to predictable values per test."""
    monkeypatch.setenv("BAKER_INTERNAL_URL", "http://localhost:8080")
    monkeypatch.setenv("BAKER_API_KEY", "test-key")


def _sse_body(events: list[dict | str]) -> bytes:
    """Encode a list of dict events (or raw strings) as SSE bytes."""
    parts = []
    for evt in events:
        if isinstance(evt, str):
            parts.append(f"data: {evt}\n\n")
        else:
            parts.append(f"data: {json.dumps(evt)}\n\n")
    return "".join(parts).encode("utf-8")


# ==========================================================================
# 1. Registration / schema sanity (covers all 4 tools)
# ==========================================================================


def test_all_four_new_tools_registered():
    names = {t.name for t in srv.TOOLS}
    assert "baker_scan" in names
    assert "baker_search" in names
    assert "baker_ingest_text" in names
    assert "baker_health" in names


def test_total_tool_count_is_thirty():
    """Was 26 + 4 new = 30 (per brief verification #2)."""
    assert len(srv.TOOLS) == 30


def test_baker_scan_schema_requires_query():
    tool = next(t for t in srv.TOOLS if t.name == "baker_scan")
    assert "query" in tool.inputSchema["required"]
    assert "capability_slug" in tool.inputSchema["properties"]


def test_baker_search_schema_caps_limit_at_50():
    tool = next(t for t in srv.TOOLS if t.name == "baker_search")
    assert tool.inputSchema["properties"]["limit"]["maximum"] == 50


def test_baker_ingest_text_schema_requires_title_and_content():
    tool = next(t for t in srv.TOOLS if t.name == "baker_ingest_text")
    assert set(tool.inputSchema["required"]) == {"title", "content"}


def test_baker_health_schema_takes_no_args():
    tool = next(t for t in srv.TOOLS if t.name == "baker_health")
    assert tool.inputSchema["properties"] == {}


# ==========================================================================
# 2. baker_scan
# ==========================================================================


def test_scan_routes_to_client_pm_when_capability_slug_provided(patch_httpx):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["x_baker_key"] = request.headers.get("X-Baker-Key")
        body = _sse_body([
            {"status": "retrieving"},
            {"capabilities": ["ao_pm"]},
            {"token": "Hello "},
            {"token": "AO."},
            "[DONE]",
        ])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "status?", "capability_slug": "ao_pm"})
    assert out == "Hello AO."
    assert captured["url"] == "http://localhost:8080/api/scan/client-pm"
    assert captured["body"]["capability_slug"] == "ao_pm"
    assert captured["x_baker_key"] == "test-key"


def test_scan_routes_to_auto_classifier_when_no_capability_slug(patch_httpx):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        body = _sse_body([{"token": "Auto-routed answer."}])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "what's up?"})
    assert out == "Auto-routed answer."
    assert captured["url"] == "http://localhost:8080/api/scan"


def test_scan_empty_query_returns_error(patch_httpx):
    out = srv._dispatch("baker_scan", {"query": "   "})
    assert out.startswith("Error:") and "query is required" in out


def test_scan_http_error_returns_error_string(patch_httpx):
    def handler(request):
        return httpx.Response(500, text="server boom")

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "anything"})
    assert out.startswith("Error: scan returned HTTP 500")


def test_scan_timeout_returns_error_string(patch_httpx):
    patch_httpx(None, raise_on_request=httpx.TimeoutException("slow"))
    out = srv._dispatch("baker_scan", {"query": "anything"})
    assert out == "Error: scan timed out after 60s"


def test_scan_skips_non_token_events(patch_httpx):
    """Only `token` deltas are accumulated. status / capabilities / tool_call /
    screenshot / task_id / __citations__ / [DONE] are metadata."""

    def handler(request):
        body = _sse_body([
            {"status": "retrieving"},
            {"capabilities": ["ao_pm"]},
            {"tool_call": {"name": "x"}},
            {"screenshot": "http://x"},
            {"token": "Real "},
            {"task_id": "t1"},
            "__citations__{\"ignored\": true}",
            {"token": "answer."},
            "[DONE]",
        ])
        return httpx.Response(200, content=body)

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "x"})
    assert out == "Real answer."


def test_scan_server_error_event_surfaces_as_error(patch_httpx):
    def handler(request):
        body = _sse_body([{"error": "capability not found"}])
        return httpx.Response(200, content=body)

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "x"})
    assert out == "Error from scan: capability not found"


def test_scan_empty_stream_returns_friendly_marker(patch_httpx):
    def handler(request):
        return httpx.Response(200, content=_sse_body([]))

    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "x"})
    assert "empty response" in out


def test_scan_internal_url_override_propagates(patch_httpx, monkeypatch):
    captured = {}

    def handler(request):
        captured["host"] = request.url.host
        return httpx.Response(200, content=_sse_body([{"token": "ok"}]))

    monkeypatch.setenv("BAKER_INTERNAL_URL", "http://invalid:9999")
    patch_httpx(handler)
    out = srv._dispatch("baker_scan", {"query": "x"})
    assert out == "ok"
    assert captured["host"] == "invalid"


# ==========================================================================
# 3. baker_search
# ==========================================================================


def test_search_happy_path_renders_results(patch_httpx):
    def handler(request):
        assert request.url.path == "/api/search/unified"
        assert request.url.params.get("q") == "MO Vienna"
        return httpx.Response(200, json={
            "query": "MO Vienna",
            "results": [
                {"source": "emails", "content": "Hagenauer email...", "score": 0.91},
                {"source": "meetings", "content": "Vienna check-in...", "score": 0.87},
            ],
            "total": 2,
            "sources_searched": ["emails", "meetings"],
        })

    patch_httpx(handler)
    out = srv._dispatch("baker_search", {"query": "MO Vienna"})
    assert "MO Vienna" in out
    assert "Hagenauer email" in out
    assert "Vienna check-in" in out
    assert "score: 0.91" in out


def test_search_empty_query_returns_error():
    out = srv._dispatch("baker_search", {"query": ""})
    assert out.startswith("Error:") and "query is required" in out


def test_search_http_error_returns_error_string(patch_httpx):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    patch_httpx(handler)
    out = srv._dispatch("baker_search", {"query": "x"})
    assert out.startswith("Error: search returned HTTP 401")


def test_search_timeout_returns_error_string(patch_httpx):
    patch_httpx(None, raise_on_request=httpx.TimeoutException("slow"))
    out = srv._dispatch("baker_search", {"query": "x"})
    assert out == "Error: search timed out after 15s"


def test_search_limit_clamped_to_50(patch_httpx):
    captured = {}

    def handler(request):
        captured["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json={"query": "x", "results": [], "total": 0})

    patch_httpx(handler)
    srv._dispatch("baker_search", {"query": "x", "limit": 9999})
    assert captured["limit"] == "50"


def test_search_no_results_returns_friendly_marker(patch_httpx):
    def handler(request):
        return httpx.Response(200, json={"query": "x", "results": [], "total": 0})

    patch_httpx(handler)
    out = srv._dispatch("baker_search", {"query": "x"})
    assert out == "No results for: x"


def test_search_passes_x_baker_key_header(patch_httpx):
    captured = {}

    def handler(request):
        captured["key"] = request.headers.get("X-Baker-Key")
        return httpx.Response(200, json={"results": [], "total": 0})

    patch_httpx(handler)
    srv._dispatch("baker_search", {"query": "x"})
    assert captured["key"] == "test-key"


# ==========================================================================
# 4. baker_ingest_text
# ==========================================================================


def test_ingest_happy_path_returns_summary(patch_httpx):
    captured = {}

    def handler(request):
        captured["url_path"] = request.url.path
        # Multipart: capture form fields and filename via the raw body
        captured["content_type"] = request.headers.get("content-type", "")
        captured["raw_body"] = request.content
        return httpx.Response(200, json={
            "status": "success",
            "filename": "memo.md",
            "collection": "baker-documents",
            "chunks": 3,
            "dedup": False,
        })

    patch_httpx(handler)
    out = srv._dispatch("baker_ingest_text", {
        "title": "memo.md",
        "content": "Hello Baker.",
    })
    assert "Ingested: memo.md" in out
    assert "Chunks: 3" in out
    assert captured["url_path"] == "/api/ingest"
    assert "multipart/form-data" in captured["content_type"]


def test_ingest_missing_title_or_content_returns_error():
    assert srv._dispatch("baker_ingest_text", {"title": "x"}).startswith("Error:")
    assert srv._dispatch("baker_ingest_text", {"content": "y"}).startswith("Error:")
    assert srv._dispatch("baker_ingest_text", {}).startswith("Error:")


def test_ingest_auto_appends_md_when_no_extension(patch_httpx):
    captured = {}

    def handler(request):
        captured["raw_body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, json={
            "status": "success",
            "filename": "untitled.md",
            "collection": "baker-documents",
            "chunks": 1,
            "dedup": False,
        })

    patch_httpx(handler)
    out = srv._dispatch("baker_ingest_text", {
        "title": "untitled",
        "content": "body",
    })
    # The multipart filename in the body should be the .md-suffixed form
    assert 'filename="untitled.md"' in captured["raw_body"]
    assert "Ingested: untitled.md" in out


def test_ingest_http_error_returns_error_string(patch_httpx):
    def handler(request):
        return httpx.Response(400, text="invalid project")

    patch_httpx(handler)
    out = srv._dispatch("baker_ingest_text", {
        "title": "x.md",
        "content": "body",
        "project": "bogus",
    })
    assert out.startswith("Error: ingest returned HTTP 400")


def test_ingest_passes_project_and_role_form_fields(patch_httpx):
    captured = {}

    def handler(request):
        captured["raw_body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, json={
            "status": "success",
            "filename": "x.md",
            "collection": "baker-documents",
            "chunks": 1,
            "dedup": False,
        })

    patch_httpx(handler)
    srv._dispatch("baker_ingest_text", {
        "title": "x.md",
        "content": "body",
        "project": "rg7",
        "role": "chairman",
    })
    body = captured["raw_body"]
    assert 'name="project"' in body and "rg7" in body
    assert 'name="role"' in body and "chairman" in body


def test_ingest_passes_collection_as_query_param(patch_httpx):
    captured = {}

    def handler(request):
        captured["collection"] = request.url.params.get("collection")
        return httpx.Response(200, json={
            "status": "success",
            "filename": "x.md",
            "collection": "baker-emails",
            "chunks": 1,
            "dedup": False,
        })

    patch_httpx(handler)
    srv._dispatch("baker_ingest_text", {
        "title": "x.md",
        "content": "body",
        "collection": "baker-emails",
    })
    assert captured["collection"] == "baker-emails"


def test_ingest_cleans_up_tempfile_on_success(patch_httpx, monkeypatch):
    created_paths: list[str] = []
    real_tempfile = srv.tempfile.NamedTemporaryFile

    def _spy_tempfile(*args, **kwargs):
        f = real_tempfile(*args, **kwargs)
        created_paths.append(f.name)
        return f

    monkeypatch.setattr(srv.tempfile, "NamedTemporaryFile", _spy_tempfile)

    def handler(request):
        return httpx.Response(200, json={
            "status": "success",
            "filename": "x.md",
            "collection": "baker-documents",
            "chunks": 1,
            "dedup": False,
        })

    patch_httpx(handler)
    srv._dispatch("baker_ingest_text", {"title": "x.md", "content": "body"})
    assert created_paths, "expected NamedTemporaryFile to have been used"
    for p in created_paths:
        assert not os.path.exists(p), f"tempfile leaked: {p}"


def test_ingest_cleans_up_tempfile_on_http_error(patch_httpx, monkeypatch):
    created_paths: list[str] = []
    real_tempfile = srv.tempfile.NamedTemporaryFile

    def _spy_tempfile(*args, **kwargs):
        f = real_tempfile(*args, **kwargs)
        created_paths.append(f.name)
        return f

    monkeypatch.setattr(srv.tempfile, "NamedTemporaryFile", _spy_tempfile)

    def handler(request):
        return httpx.Response(500, text="boom")

    patch_httpx(handler)
    srv._dispatch("baker_ingest_text", {"title": "x.md", "content": "body"})
    assert created_paths
    for p in created_paths:
        assert not os.path.exists(p)


# ==========================================================================
# 5. baker_health
# ==========================================================================


def test_health_happy_path_renders_all_fields(patch_httpx):
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={
            "status": "healthy",
            "database": "connected",
            "scheduler": "running",
            "scheduled_jobs": 12,
            "sentinels_healthy": 7,
            "sentinels_down": 0,
            "sentinels_down_list": [],
            "vault_mirror_last_pull": "2026-04-28T09:00:00+00:00",
            "vault_mirror_commit_sha": "abcdef0123456789abcdef",
            "timestamp": "2026-04-28T10:00:00+00:00",
        })

    patch_httpx(handler)
    out = srv._dispatch("baker_health", {})
    assert "Status: healthy" in out
    assert "Database: connected" in out
    assert "Scheduler: running" in out
    assert "Scheduled jobs: 12" in out
    assert "Sentinels healthy: 7" in out
    assert "Sentinels down: 0" in out
    assert "Vault mirror last pull: 2026-04-28T09:00:00+00:00" in out
    # SHA truncated to 12 chars
    assert "Vault mirror sha: abcdef012345" in out
    assert "Timestamp: 2026-04-28T10:00:00+00:00" in out


def test_health_no_auth_header_required(patch_httpx):
    """Brief §Fix4 says /health is public — tool should not require X-Baker-Key.

    We assert by making the helper succeed even when BAKER_API_KEY is unset.
    """
    captured = {}

    def handler(request):
        captured["x_baker_key"] = request.headers.get("X-Baker-Key", "<absent>")
        return httpx.Response(200, json={"status": "ok"})

    patch_httpx(handler)
    out = srv._dispatch("baker_health", {})
    # Helper does not set X-Baker-Key for /health
    assert captured["x_baker_key"] == "<absent>"
    assert out.startswith("Status: ok")


def test_health_http_error_returns_error_string(patch_httpx):
    def handler(request):
        return httpx.Response(503, text="down for maintenance")

    patch_httpx(handler)
    out = srv._dispatch("baker_health", {})
    assert out.startswith("Error: health returned HTTP 503")


def test_health_timeout_returns_error_string(patch_httpx):
    patch_httpx(None, raise_on_request=httpx.TimeoutException("slow"))
    out = srv._dispatch("baker_health", {})
    assert out == "Error: health probe timed out after 10s"


def test_health_renders_question_marks_for_missing_fields(patch_httpx):
    """Graceful degradation — partial responses must not crash."""
    def handler(request):
        return httpx.Response(200, json={"status": "degraded"})

    patch_httpx(handler)
    out = srv._dispatch("baker_health", {})
    assert "Status: degraded" in out
    assert "Database: ?" in out
    assert "Scheduler: ?" in out


def test_health_renders_sentinels_down_list_when_present(patch_httpx):
    def handler(request):
        return httpx.Response(200, json={
            "status": "degraded",
            "sentinels_down": 2,
            "sentinels_down_list": ["gmail_imap", "whatsapp"],
        })

    patch_httpx(handler)
    out = srv._dispatch("baker_health", {})
    assert "Sentinels down: 2" in out
    assert "down: gmail_imap, whatsapp" in out
