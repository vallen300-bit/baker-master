"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2d-2 — Perplexity Sonar cited ask wiring.

Registers baker_perplexity_ask into Clerk's tool loop (read-only ALLOW per the
capability policy). Clerk routes it through tools.perplexity.dispatch_perplexity so
it inherits the SAME cost circuit-breaker + usage logging + timeout validation as
every other metered caller (the G0 #2391 lesson — an ALLOW-class metered tool that
bypasses the cost governor is a blocking finding).

Tests use a fake Perplexity client (no live api.perplexity.ai) and patch the cost
breaker.
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
    _CLERK_PERPLEXITY_TOOLS,
    _GROUNDING_TOOLS,
    CLERK_ALLOW,
)


class _FakePerplexity:
    """Stands in for kbl.perplexity_client.PerplexityClient via tools.perplexity._get_client."""
    def __init__(self):
        self.calls = []

    def ask(self, prompt, model="sonar", max_tokens=4000, search_domain_filter=None,
            instructions=None, timeout=None):
        self.calls.append(("ask", prompt, model))
        return {
            "text": f"answer: {prompt}",
            "citations": [{"url": "https://src.test/a", "title": "A", "date": "", "snippet": ""}],
            "model": model,
            "tokens_in": 12,
            "tokens_out": 34,
        }


@pytest.fixture
def fake_pplx(monkeypatch):
    pplx = _FakePerplexity()
    monkeypatch.setattr("tools.perplexity._get_client", lambda: pplx)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (True, 0.0))
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost", lambda *a, **k: None, raising=False)
    return pplx


# ── registration + classification ────────────────────────────────────────────

def test_perplexity_tool_registered():
    names = {t["name"] for t in ClerkToolRegistry().tools}
    for n in _CLERK_PERPLEXITY_TOOLS:
        assert n in names, f"{n} not registered"


def test_perplexity_tool_is_allow_class():
    for n in _CLERK_PERPLEXITY_TOOLS:
        assert _classify_tool(n) == CLERK_ALLOW


def test_perplexity_counts_as_grounding():
    # A cited web answer grounds a lookup — must NOT trip the fabrication-retry.
    for n in _CLERK_PERPLEXITY_TOOLS:
        assert n in _GROUNDING_TOOLS


def test_perplexity_schema_reused_from_source():
    tools = {t["name"]: t for t in ClerkToolRegistry().tools}
    schema = tools["baker_perplexity_ask"]["input_schema"]
    assert schema["type"] == "object"
    assert "prompt" in schema["properties"]
    assert schema["required"] == ["prompt"]


# ── handler routes through dispatch_perplexity (breaker + logging) ────────────

def test_perplexity_ask_routes_and_returns_payload(fake_pplx):
    out = json.loads(ClerkToolRegistry().execute("baker_perplexity_ask", {"prompt": "who owns MO Vienna"}))
    assert out["text"] == "answer: who owns MO Vienna"
    assert out["citations"][0]["url"] == "https://src.test/a"
    assert fake_pplx.calls == [("ask", "who owns MO Vienna", "sonar")]


def test_perplexity_model_override(fake_pplx):
    json.loads(ClerkToolRegistry().execute(
        "baker_perplexity_ask", {"prompt": "deep dive", "model": "sonar-pro"}))
    assert fake_pplx.calls == [("ask", "deep dive", "sonar-pro")]


def test_perplexity_missing_required_arg_is_fault_tolerant(fake_pplx):
    res = ClerkToolRegistry().execute("baker_perplexity_ask", {})
    assert res.startswith("Error: missing required arg")
    assert fake_pplx.calls == []  # never reached the client


def test_perplexity_logs_cost_with_source(monkeypatch):
    pplx = _FakePerplexity()
    monkeypatch.setattr("tools.perplexity._get_client", lambda: pplx)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (True, 0.0))
    logged = {}
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost",
                        lambda **k: logged.update(k), raising=False)
    ClerkToolRegistry().execute("baker_perplexity_ask", {"prompt": "x", "matter_slug": "movie"})
    assert logged["source"] == "perplexity_realtime"
    assert logged["model"] == "sonar"
    assert logged["input_tokens"] == 12 and logged["output_tokens"] == 34
    assert logged["matter_slug"] == "movie"


# ── G0 #2391 regression: cost breaker tripped -> ZERO HTTP, blocked ───────────

def test_perplexity_breaker_tripped_makes_zero_calls(monkeypatch):
    pplx = _FakePerplexity()
    monkeypatch.setattr("tools.perplexity._get_client", lambda: pplx)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (False, 150.0))

    res = ClerkToolRegistry().execute("baker_perplexity_ask", {"prompt": "anything"})

    assert "circuit breaker tripped" in res
    assert pplx.calls == []  # the breaker blocked it BEFORE any Perplexity call


# ── run()-level: ALLOW class executes + grounds without fabrication-retry ─────

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


def test_perplexity_ask_runs_through_policy_gate(fake_pplx):
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("p1", "baker_perplexity_ask", {"prompt": "latest on nvidia"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Per Perplexity: ...")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("ask perplexity for the latest on nvidia")
    assert result["status"] == "ready"   # grounded by the cited web answer
    assert any(c["name"] == "baker_perplexity_ask" for c in result["tool_calls"])
