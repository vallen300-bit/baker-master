"""Regression tests for Brisen Lab V2 BRIDGE 1 — gate 4 code-reviewer fixes (2026-05-05).

Findings folded:
  Fix 1 [HIGH]   .claude/hooks/user-prompt-submit-confirm.py — narrow privkey
                 lifetime: del privkey must run immediately after sign(),
                 BEFORE the /auth/human-confirmation HTTP round-trip opens.
  Fix 2 [MED]    .claude/hooks/user-prompt-submit-confirm.py — drain preview
                 must NOT fall back to raw `body` when daemon omits
                 `body_preview`; emit "(preview unavailable)" placeholder.
  Fix 3 [MED]    baker_mcp/baker_mcp_server.py — MCP tool error paths must
                 parse daemon JSON `{error: ...}` and surface only the
                 `error` field — never raw resp.text (prevents leakage of
                 session_id / worker_slug fragments / internal trace ids
                 into LLM context via tool response).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from baker_mcp import baker_mcp_server as srv


# ---------------------------------------------------------------------------
# Shared fixtures (mirror test_brisen_lab_user_prompt_submit_hook.py +
# test_brisen_lab_consumer_mcp.py — kept local so this file is self-contained)
# ---------------------------------------------------------------------------

_HOOK_PATH = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "user-prompt-submit-confirm.py"


@pytest.fixture(scope="module")
def hook_mod():
    assert _HOOK_PATH.exists(), f"hook missing: {_HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("upsh_hook_gate4", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("BRISEN_LAB_URL", "https://brisen-lab.test")
    monkeypatch.setenv("BRISEN_LAB_TERMINAL_KEY", "test-terminal-key")
    monkeypatch.setenv("BRISEN_LAB_V2_ENABLED", "true")
    monkeypatch.setenv("BAKER_ROLE", "b4")
    monkeypatch.setenv("TMPDIR", "/tmp")


@pytest.fixture
def patch_httpx_srv(monkeypatch):
    """Patch httpx.Client used by baker_mcp_server (MCP tool dispatchers)."""

    def _install(handler):
        transport = httpx.MockTransport(handler)
        OriginalClient = httpx.Client

        class _PatchedClient(OriginalClient):
            def __init__(self, *args, **kwargs):
                kwargs.pop("transport", None)
                super().__init__(*args, transport=transport, **kwargs)

        monkeypatch.setattr(srv.httpx, "Client", _PatchedClient)
        return transport

    return _install


@pytest.fixture
def patch_httpx_hook(monkeypatch):
    """Patch httpx.Client globally — hook imports httpx lazily inside funcs."""

    def _install(handler):
        transport = httpx.MockTransport(handler)
        OriginalClient = httpx.Client

        class _PatchedClient(OriginalClient):
            def __init__(self, *args, **kwargs):
                kwargs.pop("transport", None)
                super().__init__(*args, transport=transport, **kwargs)

        monkeypatch.setattr(httpx, "Client", _PatchedClient)
        return transport

    return _install


def _stdin_with(envelope: dict) -> MagicMock:
    fake = MagicMock()
    fake.read.return_value = json.dumps(envelope)
    return fake


# ==========================================================================
# Fix 1 [HIGH] — privkey lifetime narrowed to immediately post-sign
# ==========================================================================


def test_privkey_deleted_between_sign_and_human_confirmation_post():
    """Source-introspection assertion: `del privkey` must appear AFTER the
    sign() call but BEFORE the /auth/human-confirmation HTTP POST.

    Closes the gap between brief §6 "key dies with it" forward-secrecy claim
    and actual code behavior. Prior code held privkey across the ~5s
    human-confirmation HTTP round-trip — fixed in this commit.

    Introspection-based per code-reviewer recommendation (the brief explicitly
    suggested introspection vs. runtime tracking, since Ed25519PrivateKey
    is a Rust-backed type with non-deterministic GC behavior).
    """
    src = _HOOK_PATH.read_text(encoding="utf-8")
    sign_idx = src.find("signature_bytes = privkey.sign(")
    # URL is built via f-string: f"{base}/auth/human-confirmation"
    confirm_post_idx = src.find("/auth/human-confirmation", sign_idx)
    # Skip the comment occurrence inside the new del-privkey rationale block;
    # we want the actual httpx POST URL site, which uses an f-string with
    # `{base}` immediately preceding the path.
    while confirm_post_idx != -1:
        # Look back ~20 chars for the f-string `{base}` marker
        prefix = src[max(0, confirm_post_idx - 20):confirm_post_idx]
        if "{base}" in prefix:
            break
        confirm_post_idx = src.find("/auth/human-confirmation", confirm_post_idx + 1)

    assert sign_idx > 0, "sign() call site not found in hook source"
    assert confirm_post_idx > sign_idx, "human-confirmation POST not found after sign()"

    # Locate the FIRST `del privkey` AFTER the sign() call (the
    # forward-secrecy-narrowing one — there may be an earlier defensive del
    # in the sign-failure branch, which is also fine).
    del_idx = src.find("del privkey", sign_idx)
    assert del_idx > sign_idx, "del privkey missing after sign() call"
    assert del_idx < confirm_post_idx, (
        "del privkey must run BEFORE the /auth/human-confirmation POST opens "
        "(narrows forward-secrecy window from ~5s HTTP round-trip to local "
        f"sign() call); del at {del_idx}, post at {confirm_post_idx}"
    )


# ==========================================================================
# Fix 2 [MED] — drain preview placeholder when body_preview omitted
# ==========================================================================


def test_drain_emits_placeholder_when_body_preview_omitted_no_raw_body_leak(
    hook_mod, monkeypatch, patch_httpx_hook, capsys
):
    """Daemon returns row WITHOUT body_preview but WITH sensitive raw body.
    Drain summary must emit "(preview unavailable)" placeholder; raw body
    MUST NOT leak into Claude's additionalContext.

    Brief §6 forbids surfacing raw body for ratify_required messages with
    structured payload (capital allocation, counterparty name, decision text).
    """
    monkeypatch.setenv("BAKER_ROLE", "b4")
    sensitive_body = (
        "RATIFY: capital call EUR 5M to Aelio Holdings — "
        "counterparty Wertheimer / Chanel — close by 2026-06-15"
    )

    def handler(request):
        url = str(request.url)
        if url.endswith("/ack"):
            return httpx.Response(200, json={})
        if "/msg/b4" in url and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "kind": "ratify_required",
                        "from_terminal": "ah1",
                        "topic": "cortex/aukera/capital-call/q3",
                        # body_preview INTENTIONALLY OMITTED — daemon edge case
                        "body": sensitive_body,
                    },
                ],
            )
        return httpx.Response(404)

    patch_httpx_hook(handler)

    with patch.object(sys, "stdin", _stdin_with({"prompt": "."})):
        with pytest.raises(SystemExit):
            hook_mod.main()

    out = capsys.readouterr().out

    # The drain summary must surface the row's metadata
    assert "Brisen Lab inbox drained" in out
    assert "[ratify_required]" in out
    assert "ah1" in out
    assert "cortex/aukera/capital-call/q3" in out

    # Placeholder MUST be emitted — fix 2's contract
    assert "(preview unavailable)" in out

    # Sensitive raw body MUST NOT leak into the drained summary
    assert "EUR 5M" not in out
    assert "Aelio" not in out
    assert "Wertheimer" not in out
    assert "Chanel" not in out
    assert "2026-06-15" not in out
    assert "RATIFY:" not in out


# ==========================================================================
# Fix 3 [MED] — MCP tool error paths surface only daemon `error` field
# ==========================================================================


def test_baker_inbox_post_4xx_surfaces_only_error_field_no_context_leak(patch_httpx_srv):
    """Daemon returns HTTP 4xx with structured JSON body containing both an
    `error` field and request-context fields (session_id, worker_slug
    fragments, internal trace id).

    MCP tool response must surface ONLY the `error` field — context fields
    MUST NOT reach the LLM via tool response.
    """

    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": "tier_below_classification",
                # Simulated daemon over-share — these MUST NOT reach the LLM
                "session_id": "sess-LEAK-abc-123",
                "worker_slug_fragment": "leaked-worker-fragment",
                "internal_trace_id": "INTERNAL-TRACE-LEAK-xyz",
                "request_id": "req-LEAK-7",
            },
        )

    patch_httpx_srv(handler)
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
    # Daemon's `error` field MUST surface (operator needs the loud signal)
    assert "tier_below_classification" in out
    # Daemon's request-context fields MUST NOT surface
    assert "sess-LEAK-abc-123" not in out
    assert "leaked-worker-fragment" not in out
    assert "INTERNAL-TRACE-LEAK-xyz" not in out
    assert "req-LEAK-7" not in out


def test_baker_inbox_read_4xx_surfaces_only_error_field_no_context_leak(patch_httpx_srv):
    """Same hardening on the read tool error path."""

    def handler(request):
        return httpx.Response(
            403,
            json={
                "error": "terminal_key_invalid",
                "session_id": "sess-LEAK-read-789",
                "header_received": "X-Terminal-Key=test-LEAK-key-fragment",
            },
        )

    patch_httpx_srv(handler)
    out = srv._dispatch("baker_inbox_read", {})
    assert out.startswith("Error: brisen-lab GET returned HTTP 403")
    assert "terminal_key_invalid" in out
    assert "sess-LEAK-read-789" not in out
    assert "test-LEAK-key-fragment" not in out


def test_baker_inbox_post_4xx_falls_back_to_truncated_text_on_non_json(patch_httpx_srv):
    """Defensive fallback: daemon returns 4xx with non-JSON body (e.g.
    upstream Render 502 HTML, or daemon misbehaves) — the helper must fall
    back to a truncated raw-text slice (≤80 chars) so operators still see
    SOMETHING actionable, but truncation prevents large-body context bloat.
    """
    long_html = "<html>" + ("X" * 500) + "</html>"  # > 80 chars

    def handler(request):
        return httpx.Response(502, text=long_html)

    patch_httpx_srv(handler)
    out = srv._dispatch(
        "baker_inbox_post",
        {"to": "lead", "kind": "dispatch", "body": "x"},
    )
    assert out.startswith("Error: brisen-lab POST returned HTTP 502")
    # Truncation must engage — full long body MUST NOT reach output
    assert long_html not in out
    # Some prefix should be present so the operator has SOMETHING
    assert "<html>" in out
