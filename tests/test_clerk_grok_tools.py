"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2a — live web/X search via Grok wiring.

Registers baker_grok_web_search / baker_grok_x_search / baker_grok_ask into Clerk's
tool loop (read-only ALLOW per the capability policy). Tests use an injected fake
Grok client — no live xAI calls.
"""
from __future__ import annotations

import json

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _classify_tool,
    CLERK_ALLOW,
)


class _FakeGrok:
    def __init__(self):
        self.calls = []

    def web_search(self, query, allowed_domains=None, excluded_domains=None):
        self.calls.append(("web_search", query, allowed_domains, excluded_domains))
        return {"summary": f"web: {query}", "citations": [{"url": "https://x.test/a"}], "model": "grok-4.3"}

    def x_search(self, query, from_date=None, to_date=None, allowed_x_handles=None, excluded_x_handles=None):
        self.calls.append(("x_search", query, from_date, to_date))
        return {"summary": f"x: {query}", "tweets": [{"id": "1"}], "model": "grok-4.3"}

    def ask(self, prompt, instructions=None):
        self.calls.append(("ask", prompt, instructions))
        return {"text": f"answer: {prompt}", "model": "grok-4.3"}


def _reg():
    return ClerkToolRegistry(grok_client=_FakeGrok())


# ── registration + classification ────────────────────────────────────────────

def test_grok_tools_registered():
    names = [t["name"] for t in ClerkToolRegistry().tools]
    for n in ("baker_grok_web_search", "baker_grok_x_search", "baker_grok_ask"):
        assert n in names


def test_grok_tools_are_allow_class():
    for n in ("baker_grok_web_search", "baker_grok_x_search", "baker_grok_ask"):
        assert _classify_tool(n) == CLERK_ALLOW


# ── handlers shape output + pass args through ────────────────────────────────

def test_grok_web_search_shapes_result_and_passes_filters():
    grok = _FakeGrok()
    reg = ClerkToolRegistry(grok_client=grok)
    out = json.loads(reg.execute("baker_grok_web_search", {
        "query": "nvidia earnings", "allowed_domains": ["reuters.com"], "excluded_domains": [],
    }))
    assert out["source"] == "grok_web"
    assert out["summary"] == "web: nvidia earnings"
    assert out["citations"] == [{"url": "https://x.test/a"}]
    # excluded_domains [] normalizes to None; allowed passes through
    assert grok.calls == [("web_search", "nvidia earnings", ["reuters.com"], None)]


def test_grok_x_search_shapes_result():
    out = json.loads(_reg().execute("baker_grok_x_search", {"query": "what's hot on AI"}))
    assert out["source"] == "grok_x"
    assert out["summary"] == "x: what's hot on AI"
    assert out["tweets"] == [{"id": "1"}]


def test_grok_ask_shapes_result():
    out = json.loads(_reg().execute("baker_grok_ask", {"prompt": "define IRR"}))
    assert out["source"] == "grok_ask"
    assert out["text"] == "answer: define IRR"


def test_grok_requires_query_or_prompt():
    reg = _reg()
    assert json.loads(reg.execute("baker_grok_web_search", {}))["error"] == "query is required"
    assert json.loads(reg.execute("baker_grok_x_search", {"query": "   "}))["error"] == "query is required"
    assert json.loads(reg.execute("baker_grok_ask", {}))["error"] == "prompt is required"


def test_grok_failure_renders_as_error_not_crash(monkeypatch):
    class _BoomGrok:
        def web_search(self, *a, **k):
            from kbl.grok_client import GrokError
            raise GrokError("xai down")
    reg = ClerkToolRegistry(grok_client=_BoomGrok())
    out = json.loads(reg.execute("baker_grok_web_search", {"query": "x"}))
    assert "error" in out  # fault-tolerant: never crashes the tool loop


# ── run()-level: ALLOW class -> executes through the policy gate ──────────────

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


def test_grok_web_search_runs_through_policy_gate():
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("g1", "baker_grok_web_search", {"query": "nvidia"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Per live web: ...")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=_reg(), cfg=_cfg())
    result = agent.run("search the web for nvidia earnings")
    assert result["status"] == "ready"
    assert any(c["name"] == "baker_grok_web_search" for c in result["tool_calls"])
