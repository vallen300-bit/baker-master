"""Tests for BRISEN_LAB_V2_BRIDGE_1 consumer-side MCP tools (Surface 1).

Brief: ``briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md`` §A7 + mailbox UPDATE 2026-05-05.

Tools exercised:
  - ``baker_inbox_post``  → POST /msg/<from_terminal>
  - ``baker_inbox_read``  → GET /msg/<terminal>?...
  - ``baker_inbox_ack``   → POST /msg/<id>/ack

All HTTP traffic stubbed via ``httpx.MockTransport`` — hermetic, no live daemon.

Fail-open behavior verified per AC6: HTTP 503 from V2 endpoints (flag-off state)
returns paste-block fallback instead of raising.
"""
from __future__ import annotations

import json

import httpx
import pytest

from baker_mcp import baker_mcp_server as srv


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def patch_httpx(monkeypatch):
    """Replace srv.httpx.Client with a MockTransport-backed client."""

    def _install(handler, *, raise_on_request=None):
        if raise_on_request is not None:
            def _err_handler(request):
                raise raise_on_request

            transport = httpx.MockTransport(_err_handler)
        else:
            transport = httpx.MockTransport(handler)

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
    """Pin Brisen Lab env to predictable values."""
    monkeypatch.setenv("BRISEN_LAB_URL", "https://brisen-lab.test")
    monkeypatch.setenv("BRISEN_LAB_TERMINAL_KEY", "test-terminal-key")
    monkeypatch.setenv("BAKER_ROLE", "b4")


# ==========================================================================
# 1. Registration / schema sanity
# ==========================================================================


def test_three_consumer_tools_registered():
    names = {t.name for t in srv.TOOLS}
    assert "baker_inbox_post" in names
    assert "baker_inbox_read" in names
    assert "baker_inbox_ack" in names


def test_baker_inbox_post_schema_requires_to_kind_body():
    tool = next(t for t in srv.TOOLS if t.name == "baker_inbox_post")
    assert set(tool.inputSchema["required"]) == {"to", "kind", "body"}
    assert "human_confirmation_token" in tool.inputSchema["properties"]
    assert "tier_required" in tool.inputSchema["properties"]


def test_baker_inbox_post_kind_enum_matches_brief_schema():
    """kind enum must match brief §3 schema CHECK constraint exactly (M5: no bare
    'ratify')."""
    tool = next(t for t in srv.TOOLS if t.name == "baker_inbox_post")
    enum = tool.inputSchema["properties"]["kind"]["enum"]
    assert set(enum) == {"dispatch", "broadcast", "ratify_required", "ratify_decision"}


def test_baker_inbox_read_schema_optional_terminal():
    tool = next(t for t in srv.TOOLS if t.name == "baker_inbox_read")
    assert "required" not in tool.inputSchema or not tool.inputSchema.get("required")
    assert "exclude_self" in tool.inputSchema["properties"]


def test_baker_inbox_ack_schema_takes_msg_id_or_msg_ids():
    tool = next(t for t in srv.TOOLS if t.name == "baker_inbox_ack")
    props = tool.inputSchema["properties"]
    assert "msg_id" in props
    assert "msg_ids" in props


# ==========================================================================
# 2. baker_inbox_post — happy path + auth header + URL routing
# ==========================================================================


def test_post_routes_to_from_terminal_url_and_includes_terminal_key(patch_httpx):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["x_terminal_key"] = request.headers.get("X-Terminal-Key")
        return httpx.Response(200, json={"id": 42, "thread_id": "abc-123"})

    patch_httpx(handler)
    out = srv._dispatch(
        "baker_inbox_post",
        {"to": "lead", "kind": "dispatch", "body": "hello"},
    )
    assert "42" in out
    # BAKER_ROLE=b4 → URL path /msg/b4
    assert captured["url"] == "https://brisen-lab.test/msg/b4"
    assert captured["method"] == "POST"
    assert captured["body"]["to_terminals"] == ["lead"]
    assert captured["body"]["kind"] == "dispatch"
    assert captured["body"]["body"] == "hello"
    assert captured["x_terminal_key"] == "test-terminal-key"


def test_post_coerces_to_string_to_one_element_list(patch_httpx):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"id": 1})

    patch_httpx(handler)
    srv._dispatch("baker_inbox_post", {"to": "lead", "kind": "broadcast", "body": "x"})
    assert captured["body"]["to_terminals"] == ["lead"]


def test_post_passes_array_to_through(patch_httpx):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"id": 1})

    patch_httpx(handler)
    srv._dispatch(
        "baker_inbox_post",
        {"to": ["lead", "deputy"], "kind": "broadcast", "body": "x"},
    )
    assert captured["body"]["to_terminals"] == ["lead", "deputy"]


def test_post_attaches_human_confirmation_token_header(patch_httpx):
    """Surface 3 hook will populate this; tool must pass it through verbatim."""
    captured = {}

    def handler(request):
        captured["x_hct"] = request.headers.get("X-Human-Confirmation-Token")
        return httpx.Response(200, json={"id": 7})

    patch_httpx(handler)
    srv._dispatch(
        "baker_inbox_post",
        {
            "to": "lead",
            "kind": "ratify_decision",
            "body": "approve",
            "parent_id": 99,
            "human_confirmation_token": "JWT.test.token",
        },
    )
    assert captured["x_hct"] == "JWT.test.token"


def test_post_optional_fields_passed_through(patch_httpx):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"id": 1})

    patch_httpx(handler)
    srv._dispatch(
        "baker_inbox_post",
        {
            "to": "lead",
            "kind": "ratify_required",
            "body": "ratify?",
            "topic": "cortex/aukera/capital-call/q3",
            "tier_required": "A",
            "thread_id": "tt-1",
            "parent_id": 5,
        },
    )
    body = captured["body"]
    assert body["topic"] == "cortex/aukera/capital-call/q3"
    assert body["tier_required"] == "A"
    assert body["thread_id"] == "tt-1"
    assert body["parent_id"] == 5


def test_post_from_terminal_override(patch_httpx, monkeypatch):
    """Cowork (no BAKER_ROLE) can still post as cowork-ah1 via override."""
    monkeypatch.delenv("BAKER_ROLE", raising=False)
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": 1})

    patch_httpx(handler)
    srv._dispatch(
        "baker_inbox_post",
        {"to": "lead", "kind": "dispatch", "body": "x", "from_terminal": "cowork-ah1"},
    )
    assert captured["url"] == "https://brisen-lab.test/msg/cowork-ah1"


# ==========================================================================
# 3. baker_inbox_post — fail-open + error paths
# ==========================================================================


def test_post_503_returns_paste_block_fallback(patch_httpx):
    """AC6: V2 endpoints return 503 when BRISEN_LAB_V2_ENABLED=false on daemon."""

    def handler(request):
        return httpx.Response(503, json={"error": "lab_frozen"})

    patch_httpx(handler)
    out = srv._dispatch(
        "baker_inbox_post",
        {"to": "lead", "kind": "dispatch", "body": "hello"},
    )
    assert "[brisen-lab v2 disabled" in out
    assert "paste-block fallback" in out
    assert "from_terminal: b4" in out
    assert "hello" in out


def test_post_4xx_returns_loud_error(patch_httpx):
    """Caller bug (e.g., tier-below-classification) surfaces verbatim, no fail-open."""

    def handler(request):
        return httpx.Response(
            400,
            json={"error": "tier_below_classification", "classified_tier": "A", "declared_tier": "B"},
        )

    patch_httpx(handler)
    out = srv._dispatch(
        "baker_inbox_post",
        {
            "to": "lead",
            "kind": "ratify_required",
            "body": "x",
            "topic": "cortex/aukera/capital-call/q3",
            "tier_required": "B",
        },
    )
    assert out.startswith("Error: brisen-lab POST returned HTTP 400")
    assert "tier_below_classification" in out


def test_post_timeout_returns_error_string(patch_httpx):
    patch_httpx(None, raise_on_request=httpx.TimeoutException("slow"))
    out = srv._dispatch(
        "baker_inbox_post",
        {"to": "lead", "kind": "dispatch", "body": "x"},
    )
    assert "timed out after 15s" in out
    assert out.startswith("Error:")


def test_post_missing_required_arg_returns_error():
    out = srv._dispatch("baker_inbox_post", {"kind": "dispatch", "body": "x"})
    assert out.startswith("Error:") and "to, kind, body are required" in out


def test_post_invalid_to_type_returns_error():
    out = srv._dispatch(
        "baker_inbox_post",
        {"to": 42, "kind": "dispatch", "body": "x"},
    )
    assert out.startswith("Error:") and "string or list" in out


# ==========================================================================
# 4. baker_inbox_read — happy path + filters + fail-open
# ==========================================================================


def test_read_routes_to_terminal_inbox(patch_httpx):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["x_terminal_key"] = request.headers.get("X-Terminal-Key")
        return httpx.Response(
            200,
            json=[
                {"id": 1, "kind": "dispatch", "from_terminal": "ah1", "body": "hi"},
                {"id": 2, "kind": "broadcast", "from_terminal": "daemon", "body": "ping"},
            ],
        )

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_read", {})
    # BAKER_ROLE=b4 → /msg/b4
    assert "/msg/b4" in captured["url"]
    assert captured["x_terminal_key"] == "test-terminal-key"
    assert "dispatch" in out
    assert "broadcast" in out


def test_read_passes_filters_in_querystring(patch_httpx):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    srv._dispatch(
        "baker_inbox_read",
        {
            "since": "2026-05-05T00:00:00Z",
            "kind": "dispatch",
            "topic": "cortex/aukera/",
            "exclude_self": True,
            "limit": 25,
        },
    )
    url = captured["url"]
    assert "since=" in url
    assert "kind=dispatch" in url
    assert "exclude_self=true" in url
    assert "limit=25" in url


def test_read_terminal_override(patch_httpx):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    srv._dispatch("baker_inbox_read", {"terminal": "lead"})
    assert "/msg/lead" in captured["url"]


def test_read_503_returns_empty_inbox_marker(patch_httpx):
    def handler(request):
        return httpx.Response(503, json={"error": "lab_frozen"})

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_read", {})
    assert "[brisen-lab v2 disabled" in out
    assert "empty inbox" in out


def test_read_empty_inbox_message_friendly(patch_httpx):
    def handler(request):
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_read", {})
    assert "Inbox empty for b4" in out


def test_read_4xx_returns_loud_error(patch_httpx):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_read", {})
    assert out.startswith("Error: brisen-lab GET returned HTTP 401")


def test_read_caps_limit_at_200(patch_httpx):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    patch_httpx(handler)
    srv._dispatch("baker_inbox_read", {"limit": 9999})
    assert "limit=200" in captured["url"]


# ==========================================================================
# 5. baker_inbox_ack — single + bulk + fail-open
# ==========================================================================


def test_ack_single_msg_id(patch_httpx):
    captured = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"acknowledged": True})

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_ack", {"msg_id": 42})
    assert captured == ["https://brisen-lab.test/msg/42/ack"]
    assert "200" in out


def test_ack_bulk_msg_ids(patch_httpx):
    captured = []

    def handler(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"acknowledged": True})

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_ack", {"msg_ids": [1, 2, 3]})
    assert len(captured) == 3
    assert "https://brisen-lab.test/msg/1/ack" in captured
    assert "https://brisen-lab.test/msg/3/ack" in captured
    payload = json.loads(out)
    assert len(payload["acked"]) == 3
    assert all(r["status"] == 200 for r in payload["acked"])


def test_ack_503_silent_v2_disabled(patch_httpx):
    """Drain side fail-open: 503 records v2_disabled but never raises (mailbox surface 5)."""

    def handler(request):
        return httpx.Response(503)

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_ack", {"msg_id": 7})
    payload = json.loads(out)
    assert payload["acked"][0]["status"] == "v2_disabled"


def test_ack_missing_args_error():
    out = srv._dispatch("baker_inbox_ack", {})
    assert out.startswith("Error:") and "msg_id or msg_ids is required" in out


def test_ack_non_int_ids_error():
    out = srv._dispatch("baker_inbox_ack", {"msg_ids": ["abc"]})
    assert out.startswith("Error:") and "must be integers" in out


def test_ack_terminal_key_header_attached(patch_httpx):
    captured = {}

    def handler(request):
        captured["x_terminal_key"] = request.headers.get("X-Terminal-Key")
        return httpx.Response(200, json={"ok": True})

    patch_httpx(handler)
    srv._dispatch("baker_inbox_ack", {"msg_id": 1})
    assert captured["x_terminal_key"] == "test-terminal-key"


def test_ack_per_msg_failure_does_not_abort_loop(patch_httpx):
    """One bad msg in a bulk batch must not cause others to be skipped."""
    seen = []

    def handler(request):
        path = str(request.url)
        seen.append(path)
        if "/msg/2/ack" in path:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json={"acknowledged": True})

    patch_httpx(handler)
    out = srv._dispatch("baker_inbox_ack", {"msg_ids": [1, 2, 3]})
    payload = json.loads(out)
    statuses = {r["msg_id"]: r["status"] for r in payload["acked"]}
    assert statuses == {1: 200, 2: 404, 3: 200}
    assert len(seen) == 3


# ==========================================================================
# 6. Caller-terminal env defaults
# ==========================================================================


def test_caller_terminal_defaults_to_baker_role_lowercased(monkeypatch):
    monkeypatch.setenv("BAKER_ROLE", "Lead")
    assert srv._brisen_lab_caller_terminal() == "lead"


def test_caller_terminal_defaults_to_cowork_when_no_baker_role(monkeypatch):
    monkeypatch.delenv("BAKER_ROLE", raising=False)
    assert srv._brisen_lab_caller_terminal() == "cowork"


def test_caller_terminal_strips_whitespace(monkeypatch):
    monkeypatch.setenv("BAKER_ROLE", "  b2  ")
    assert srv._brisen_lab_caller_terminal() == "b2"
