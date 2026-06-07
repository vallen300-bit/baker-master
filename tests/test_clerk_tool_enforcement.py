"""CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1 — regression tests.

The bug: Qwen3 on tool_choice="auto" sometimes answers a lookup WITHOUT calling
a search tool and fabricates "No documents found" (tool_calls=[], iterations=1).
This guards the two-layer fix: prompt mandate + structural forced-retry/fail-loud.

Acceptance criteria from the dispatch:
  (1) softer-phrasing lookup -> a real search tool_call fires (forced retry);
  (2) the model can't emit "found N"/"no documents found" with empty tool_calls
      (guard catches -> forced retry, or fail-loud non-answer if no tool fires);
  (3) non-lookup chit-chat still answers WITHOUT a forced search (no over-trigger).

Pure unit tests — fake model client, no live Qwen/DB.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from config.settings import Qwen3Config
from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _CLERK_SEARCH_FAILLOUD_MSG,
    _asserts_unsubstantiated_lookup,
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
    return Qwen3Config(
        base_url="https://qwen.example/v1",
        api_key="test-key",
        model="qwen3-coder",
        backend="qwen3_hosted",
        max_steps=max_steps,
        task_timeout_s=timeout,
    )


# ── assertion detector (anti-over-trigger) ───────────────────────────────────

@pytest.mark.parametrize("text", [
    "No documents found for Peter Storer.",
    "Found 35 documents about Peter Storer.",
    "I searched and found nothing.",
    "No results found.",
    "found nothing",
    "couldn't find any emails",
    "Search returned no matches.",
    # CLERK_QWEN3_GUARD_COVERAGE_1 — codex FAIL-M1 proven gaps (must now be True):
    "I could not locate any documents about Peter Storer",
    "I do not see any documents about Peter Storer",
    "There do not appear to be documents about Peter Storer",
    # + siblings
    "I couldn't locate any emails",
    "I can't see any results",
    "cannot find any matches",
    "unable to find any records",
    "does not appear to be any transcripts",
    "No files found",
])
def test_lookup_assertion_detected(text):
    assert _asserts_unsubstantiated_lookup(text) is True


@pytest.mark.parametrize("text", [
    "Hello! How can I help you today?",
    "I can search documents, emails, and transcripts for you.",
    "Here is the draft you asked for.",
    "I'm Clerk, Brisen's document clerk.",
    "",
    # CLERK_QWEN3_GUARD_COVERAGE_1 — anti-over-trigger: idiomatic "see"/"no"
    # phrases that are NOT lookup outcomes must stay False.
    "There is no need to worry.",
    "I do not see why not, here is the plan.",
    "I do not see how that helps.",
    "I can't wait to help!",
])
def test_non_lookup_text_not_flagged(text):
    assert _asserts_unsubstantiated_lookup(text) is False


@pytest.mark.parametrize("fabrication", [
    "I could not locate any documents about Peter Storer.",
    "I do not see any documents about Peter Storer.",
    "There do not appear to be documents about Peter Storer.",
])
def test_widened_absence_phrasings_trigger_forced_retry(fabrication):
    # CLERK_QWEN3_GUARD_COVERAGE_1: each codex-proven phrasing, emitted with ZERO
    # tool calls, must now trip the guard. With no tool on the forced retry, that
    # is the fail-loud non-answer (never the fabricated absence).
    client = _FakeClient([
        _ToolResponse([_TextBlock(fabrication)], "end_turn", 10, 5),
        _ToolResponse([_TextBlock(fabrication)], "end_turn", 9, 4),  # forced retry, still no tool
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("find documents about Peter Storer")
    assert result["status"] == "needs_retry"
    assert result["answer"] == _CLERK_SEARCH_FAILLOUD_MSG
    assert len(client.messages.calls) == 2  # one forced retry, bounded
    assert client.messages.calls[1].get("tool_choice") == "required"


# ── (1)+(2) guard forces a search retry; (1) tool fires on retry ─────────────

def test_lookup_without_tool_call_forces_search_then_succeeds(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "outputs.dashboard",
        SimpleNamespace(search_documents_core=lambda *a, **k: {
            "results": [{"id": 1, "title": "storer.pdf", "summary": "Peter Storer"}],
            "total": 35, "mode": "semantic",
        }),
    )
    client = _FakeClient([
        # call 1: fabricated lookup answer, NO tool call
        _ToolResponse([_TextBlock("No documents found for Peter Storer.")], "end_turn", 10, 5),
        # call 2 (forced retry): now calls baker_search
        _ToolResponse([_ToolUseBlock("c1", "baker_search", {"query": "Peter Storer"})], "tool_use", 12, 6),
        # call 3: final grounded answer
        _ToolResponse([_TextBlock("Found 35 documents about Peter Storer.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("how many documents mention Peter Storer")

    assert result["status"] == "ready"
    assert any(c["name"] == "baker_search" for c in result["tool_calls"]), "a real search must fire"
    # the forced retry call must request tool_choice="required"
    calls = client.messages.calls
    assert calls[0].get("tool_choice") == "auto"
    assert calls[1].get("tool_choice") == "required"


def test_forced_retry_still_no_tool_fails_loud_not_fabricated():
    client = _FakeClient([
        _ToolResponse([_TextBlock("No documents found for Peter Storer.")], "end_turn", 10, 5),
        # forced retry STILL no tool call (e.g. backend ignored tool_choice=required)
        _ToolResponse([_TextBlock("Still no documents found.")], "end_turn", 9, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("find documents about Peter Storer")

    assert result["status"] != "ready"
    assert result["status"] == "needs_retry"
    assert result["answer"] == _CLERK_SEARCH_FAILLOUD_MSG
    # critical: must NOT surface the fabricated empty
    assert "no documents found" not in result["answer"].lower()
    assert result["tool_calls"] == []
    # bounded to exactly one forced retry (2 model calls total, no loop)
    assert len(client.messages.calls) == 2


# ── (3) chit-chat is not over-triggered ──────────────────────────────────────

def test_chitchat_answers_without_forced_search():
    client = _FakeClient([
        _ToolResponse([_TextBlock("Hello! I can help you search Baker's documents and emails. What do you need?")], "end_turn", 6, 3),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("hi, what can you do?")

    assert result["status"] == "ready"
    assert result["iterations"] == 1
    assert result["tool_calls"] == []
    # no forced retry: exactly one model call, and it was the normal "auto" call
    assert len(client.messages.calls) == 1
    assert client.messages.calls[0].get("tool_choice") == "auto"
