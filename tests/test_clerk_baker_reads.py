"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2b — Baker MCP pure-SELECT reads wired into Clerk.

13 cheap PG reads + baker_health are registered (ALLOW) and routed through the
governed baker_mcp.baker_mcp_server._dispatch — the same sync path the MCP server's
call_tool uses. baker_scan is reclassified APPROVAL and intentionally NOT wired
(it routes to an expensive Opus /api/scan run).

Tests patch _dispatch — no live DB.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _classify_tool,
    _CLERK_BAKER_READ_TOOLS,
    _GROUNDING_TOOLS,
    CLERK_ALLOW,
    CLERK_APPROVAL,
)

READS = list(_CLERK_BAKER_READ_TOOLS)


# ── registration + classification ────────────────────────────────────────────

def test_all_baker_reads_registered():
    names = {t["name"] for t in ClerkToolRegistry().tools}
    for n in READS:
        assert n in names, f"{n} not registered"


@pytest.mark.parametrize("name", READS)
def test_baker_reads_are_allow_class(name):
    assert _classify_tool(name) == CLERK_ALLOW


def test_registered_read_schemas_reused_from_mcp():
    # Schemas come from the MCP TOOLS source of truth — a parametrized read like
    # baker_vip_contacts must carry its 'search' property, not an empty schema.
    tools = {t["name"]: t for t in ClerkToolRegistry().tools}
    vip = tools["baker_vip_contacts"]
    assert vip["input_schema"]["type"] == "object"
    assert "search" in vip["input_schema"]["properties"]


def test_baker_reads_count_as_grounding():
    # A 'what deadlines do we have' lookup answered via baker_deadlines is grounded —
    # so the reads must be in _GROUNDING_TOOLS (no false fabrication-retry).
    for n in READS:
        assert n in _GROUNDING_TOOLS


# ── baker_scan deferred + APPROVAL (fail-safe) ───────────────────────────────

def test_baker_scan_is_approval_and_not_registered():
    assert _classify_tool("baker_scan") == CLERK_APPROVAL
    names = {t["name"] for t in ClerkToolRegistry().tools}
    assert "baker_scan" not in names  # deferred from PR 2b


# ── routing through the governed _dispatch ───────────────────────────────────

def test_read_routes_through_dispatch(monkeypatch):
    seen = {}
    def fake_dispatch(name, args):
        seen["name"] = name; seen["args"] = args
        return "Baker Deadlines\n- thing due"
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch", fake_dispatch)

    out = ClerkToolRegistry().execute("baker_deadlines", {"status": "active", "limit": 5})
    assert out == "Baker Deadlines\n- thing due"
    assert seen == {"name": "baker_deadlines", "args": {"status": "active", "limit": 5}}


def test_read_dispatch_failure_is_fault_tolerant(monkeypatch):
    def boom(name, args):
        raise RuntimeError("db down")
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch", boom)
    out = ClerkToolRegistry().execute("baker_vip_contacts", {"search": "x"})
    # execute() try/except renders it as a clean error, never crashes the loop
    assert "error" in out.lower() or out.startswith("Error")


# ── the policy gate still keeps writes out of this read batch ─────────────────

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


def test_write_tool_still_blocked_by_gate(monkeypatch):
    # A mutation tool name must never reach _dispatch — the policy gate returns
    # pending_approval before execute().
    called = {"hit": False}
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch",
                        lambda n, a: called.__setitem__("hit", True) or "should-not-run")
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("w1", "baker_add_deadline", {"text": "x"})], "tool_use", 10, 5),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("add a deadline")
    assert result["status"] == "pending_approval"
    assert called["hit"] is False


def test_read_runs_through_policy_gate_and_grounds(monkeypatch):
    monkeypatch.setattr("baker_mcp.baker_mcp_server._dispatch",
                        lambda n, a: "Baker Deadlines\n- RG7 filing due 2026-06-20")
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("d1", "baker_deadlines", {"status": "active"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("You have 1 active deadline: RG7 filing.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("what deadlines do we have")
    assert result["status"] == "ready"   # grounded by baker_deadlines, no fabrication-retry
    assert any(c["name"] == "baker_deadlines" for c in result["tool_calls"])
