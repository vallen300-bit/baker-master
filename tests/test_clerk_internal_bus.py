"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2d-1 — internal agent bus wired into Clerk.

baker_inbox_read / baker_inbox_post / baker_inbox_ack are ALLOW (internal
coordination per the system prompt — NOT an external-to-human send) and routed
through the governed baker_mcp._dispatch (the same path the MCP server uses), which
hits the brisen-lab HTTP daemon.

Tests patch _dispatch — no live bus calls.
"""
from __future__ import annotations

import pytest

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _classify_tool,
    _CLERK_BUS_TOOLS,
    _GROUNDING_TOOLS,
    CLERK_ALLOW,
    CLERK_DENY,
)

BUS = list(_CLERK_BUS_TOOLS)


# ── registration + classification ────────────────────────────────────────────

def test_bus_tools_registered():
    names = {t["name"] for t in ClerkToolRegistry().tools}
    for n in BUS:
        assert n in names, f"{n} not registered"


@pytest.mark.parametrize("name", BUS)
def test_bus_tools_are_allow_class(name):
    assert _classify_tool(name) == CLERK_ALLOW


def test_bus_tools_not_grounding():
    # Bus post/ack/read are coordination, not Baker-data lookups — not grounding.
    for n in BUS:
        assert n not in _GROUNDING_TOOLS


def test_external_sends_still_denied_not_confused_with_bus():
    # The internal bus is ALLOW; external-to-human sends remain DENY.
    for n in ("whatsapp_send", "slack_send", "baker_gmail_send", "email_send"):
        assert _classify_tool(n) == CLERK_DENY


# ── routing through the governed _dispatch ───────────────────────────────────

@pytest.mark.parametrize("name,args", [
    ("baker_inbox_read", {"terminal": "clerk"}),
    ("baker_inbox_post", {"recipient": "lead", "body": "hi", "topic": "x"}),
    ("baker_inbox_ack", {"message_id": 123}),
])
def test_bus_tool_routes_through_dispatch(monkeypatch, name, args):
    seen = {}
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch",
                        lambda n, a: seen.update({"n": n, "a": a}) or "BUS OK")
    out = ClerkToolRegistry().execute(name, args)
    assert out == "BUS OK"
    assert seen == {"n": name, "a": args}


def test_bus_dispatch_failure_is_fault_tolerant(monkeypatch):
    def boom(n, a):
        raise RuntimeError("bus daemon down")
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch", boom)
    out = ClerkToolRegistry().execute("baker_inbox_post", {"recipient": "lead", "body": "x"})
    assert "error" in out.lower() or out.startswith("Error")


# ── run()-level: ALLOW class executes through the policy gate ─────────────────

def _cfg():
    from config.settings import Qwen3Config
    return Qwen3Config(base_url="https://q/v1", api_key="k", model="qwen3-coder",
                       backend="qwen3_hosted", max_steps=12, task_timeout_s=180)


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses); self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs); return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_inbox_post_runs_through_policy_gate(monkeypatch):
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch",
                        lambda n, a: '{"message_id": 999, "posted": true}')
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("p1", "baker_inbox_post",
                      {"recipient": "lead", "body": "status", "topic": "fyi"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Posted to lead.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("post a status note to lead on the bus")
    assert result["status"] == "ready"
    assert any(c["name"] == "baker_inbox_post" for c in result["tool_calls"])
