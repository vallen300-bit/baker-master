"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2c — gmail + claimsmax READS wired into Clerk.

3 gmail reads + 3 claimsmax reads (ALLOW), routed through the governed
tools.gmail.dispatch_gmail / tools.claimsmax.dispatch_claimsmax (the same sync
entrypoints the MCP server uses). The cost/side-effect claimsmax tools stay out:
ask = UNMAPPED -> default-DENY (fail-safe); investigate/save/convert = APPROVAL.

Tests patch the dispatchers — no live Gmail/ClaimsMax calls.
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
    _CLERK_GMAIL_READ_TOOLS,
    _CLERK_CLAIMSMAX_READ_TOOLS,
    _GROUNDING_TOOLS,
    CLERK_ALLOW,
    CLERK_APPROVAL,
    CLERK_DENY,
)

READS = list(_CLERK_GMAIL_READ_TOOLS) + list(_CLERK_CLAIMSMAX_READ_TOOLS)


# ── registration + classification ────────────────────────────────────────────

def test_all_2c_reads_registered():
    names = {t["name"] for t in ClerkToolRegistry().tools}
    for n in READS:
        assert n in names, f"{n} not registered"


@pytest.mark.parametrize("name", READS)
def test_2c_reads_are_allow_class(name):
    assert _classify_tool(name) == CLERK_ALLOW


def test_2c_reads_count_as_grounding():
    for n in READS:
        assert n in _GROUNDING_TOOLS


def test_gmail_schema_reused_from_source():
    tools = {t["name"]: t for t in ClerkToolRegistry().tools}
    assert tools["baker_gmail_search"]["input_schema"]["type"] == "object"


# ── cost/side-effect claimsmax tools stay OUT (fail-safe) ────────────────────

def test_claimsmax_cost_tools_not_registered_and_gated():
    names = {t["name"] for t in ClerkToolRegistry().tools}
    # ask = LLM Q&A (cost): unmapped -> default-DENY, NOT registered
    assert "baker_claimsmax_ask" not in names
    assert _classify_tool("baker_claimsmax_ask") == CLERK_DENY
    # investigate / save / convert = cost/side-effect -> APPROVAL, NOT registered
    for n in ("baker_claimsmax_investigate", "baker_claimsmax_save_investigation",
              "baker_claimsmax_convert_to_html", "baker_claimsmax_convert_to_pdf"):
        assert n not in names
        assert _classify_tool(n) == CLERK_APPROVAL


def test_gmail_send_denied():
    assert _classify_tool("baker_gmail_send") == CLERK_DENY


# ── routing through the governed dispatchers ─────────────────────────────────

def test_gmail_read_routes_through_dispatch_gmail(monkeypatch):
    seen = {}
    monkeypatch.setattr("tools.gmail.dispatch_gmail",
                        lambda n, a: seen.update({"n": n, "a": a}) or "GMAIL RESULT")
    out = ClerkToolRegistry().execute("baker_gmail_search", {"query": "from:peter"})
    assert out == "GMAIL RESULT"
    assert seen == {"n": "baker_gmail_search", "a": {"query": "from:peter"}}


def test_claimsmax_read_routes_through_dispatch_claimsmax(monkeypatch):
    seen = {}
    monkeypatch.setattr("tools.claimsmax.dispatch_claimsmax",
                        lambda n, a: seen.update({"n": n, "a": a}) or "CM RESULT")
    out = ClerkToolRegistry().execute("baker_claimsmax_search", {"query": "stonework"})
    assert out == "CM RESULT"
    assert seen == {"n": "baker_claimsmax_search", "a": {"query": "stonework"}}


def test_dispatch_failure_is_fault_tolerant(monkeypatch):
    def boom(n, a):
        raise RuntimeError("gmail down")
    monkeypatch.setattr("tools.gmail.dispatch_gmail", boom)
    out = ClerkToolRegistry().execute("baker_gmail_read_message", {"message_id": "x"})
    assert "error" in out.lower() or out.startswith("Error")


# ── policy gate still keeps cost/write tools out ─────────────────────────────

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


def test_claimsmax_investigate_blocked_by_gate(monkeypatch):
    hit = {"v": False}
    monkeypatch.setattr("tools.claimsmax.dispatch_claimsmax",
                        lambda n, a: hit.__setitem__("v", True) or "ran")
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("i1", "baker_claimsmax_investigate", {"query": "x"})], "tool_use", 10, 5),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("investigate the trade")
    assert result["status"] == "pending_approval"
    assert hit["v"] is False


def test_gmail_read_runs_through_gate_and_grounds(monkeypatch):
    monkeypatch.setattr("tools.gmail.dispatch_gmail",
                        lambda n, a: "Found 2 emails from Peter Storer.")
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("g1", "baker_gmail_search", {"query": "from:peter"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("2 emails from Peter.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("find emails from Peter")
    assert result["status"] == "ready"   # grounded by the gmail read
    assert any(c["name"] == "baker_gmail_search" for c in result["tool_calls"])
