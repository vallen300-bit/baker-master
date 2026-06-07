"""CLERK_DIRECTOR_FACING_REGISTER_1 — regression tests.

The Director talks to Clerk Qwen3 directly and wants a light Director-facing
register: bottom-line first, plain English (no jargon), and a one-line
"Recommendation: X - why" ONLY when Clerk surfaces a real choice.

HARD CONSTRAINT (from dispatch #2280): the register is an output-phrasing layer
only. It must NOT weaken the just-merged tool-use mandate + grounding guard
(#320/#321/#322) — a retrieval question must STILL force a real search tool call
before answering, even when the answer is phrased in the Director-facing register.

Pure unit tests — fake model client, no live Qwen/DB.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _CLERK_SYSTEM_PROMPT,
)


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _cfg(max_steps=12, timeout=180):
    from config.settings import Qwen3Config

    return Qwen3Config(
        base_url="https://qwen.example/v1",
        api_key="test-key",
        model="qwen3-coder",
        backend="qwen3_hosted",
        max_steps=max_steps,
        task_timeout_s=timeout,
    )


# ── (a)+(b) the register guidance is present in the system prompt ─────────────

def test_director_register_guidance_in_prompt():
    prompt = " ".join(_CLERK_SYSTEM_PROMPT.split())
    # bottom-line-first + plain-English/no-jargon + the Recommendation contract
    assert "DIRECTOR-FACING REGISTER" in prompt
    assert "bottom-line answer first" in prompt
    assert "spell out jargon" in prompt
    assert "Recommendation:" in prompt
    # the Recommendation line is conditional on a real choice, not on every answer
    assert "ONLY when" in prompt
    assert "no decision" in prompt
    # it is explicitly a phrasing layer that never overrides tool-use
    assert "never overrides the mandatory tool-use rule" in prompt


def test_register_layer_does_not_remove_tool_use_mandate():
    # HARD CONSTRAINT: the #320/#321/#322 mandate text must survive VERBATIM.
    prompt = " ".join(_CLERK_SYSTEM_PROMPT.split())
    assert "MANDATORY TOOL USE FOR LOOKUPS" in prompt
    assert "you MUST call a search" in prompt
    assert (
        'NEVER claim you searched, report a count, or say "no documents/results/ '
        'matches found" unless you actually called a search tool'
    ) in prompt
    assert "If you have not searched yet, call the tool now instead of answering" in prompt
    # the no-fabrication / plain-text rules also remain
    assert "Never invent, guess, or fabricate email addresses" in prompt
    assert "plain text only" in prompt


# ── (c) HARD CONSTRAINT: Director-facing answer still fires a real search ─────

def test_director_facing_lookup_still_forces_real_search(monkeypatch):
    # The model first answers a Director-style lookup in the new register WITHOUT
    # calling a search tool. The structural guard must still force a search retry,
    # and a real baker_search must fire before the answer is accepted.
    monkeypatch.setitem(
        sys.modules,
        "outputs.dashboard",
        SimpleNamespace(search_documents_core=lambda *a, **k: {
            "results": [{"id": 1, "title": "storer.pdf", "summary": "Peter Storer"}],
            "total": 35, "mode": "semantic",
        }),
    )
    client = _FakeClient([
        # call 1: Director-facing-phrased answer, but NO tool call (the risk case)
        _ToolResponse(
            [_TextBlock(
                "Bottom line: I count 35 documents mentioning Peter Storer. "
                "Recommendation: review the most recent three - they cover the live thread."
            )],
            "end_turn", 10, 5,
        ),
        # call 2 (forced retry): now calls baker_search
        _ToolResponse([_ToolUseBlock("c1", "baker_search", {"query": "Peter Storer"})], "tool_use", 12, 6),
        # call 3: final grounded, still Director-facing answer
        _ToolResponse([_TextBlock("Bottom line: 35 documents mention Peter Storer.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("how many documents mention Peter Storer")

    assert result["status"] == "ready"
    assert any(c["name"] == "baker_search" for c in result["tool_calls"]), \
        "register must NOT suppress the forced real search"
    calls = client.messages.calls
    assert calls[0].get("tool_choice") == "auto"
    assert calls[1].get("tool_choice") == "required"


def test_register_phrased_fabrication_without_tool_still_fails_loud():
    # A Director-facing "Recommendation"-styled answer that fabricated a result with
    # ZERO tool calls must STILL be caught by the structural guard (fail-loud), not
    # surfaced. The register cannot become a fabrication escape hatch.
    from orchestrator.clerk_runtime import _CLERK_SEARCH_FAILLOUD_MSG

    fabricated = (
        "Bottom line: I found no documents about Peter Storer. "
        "Recommendation: try a different spelling."
    )
    client = _FakeClient([
        _ToolResponse([_TextBlock(fabricated)], "end_turn", 10, 5),
        _ToolResponse([_TextBlock(fabricated)], "end_turn", 9, 4),  # forced retry, still no tool
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("how many documents mention Peter Storer")

    assert result["status"] == "needs_retry"
    assert result["answer"] == _CLERK_SEARCH_FAILLOUD_MSG
    assert "no documents" not in result["answer"].lower()
    assert len(client.messages.calls) == 2  # bounded to one forced retry
