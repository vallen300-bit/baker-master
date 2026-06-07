"""CLERK_FULL_CAPABILITY_POLICY_1 — capability-class policy regression tests.

One maintainable policy replaces the ad-hoc name-fragment denylist:
  ALLOW    — reads/search/analysis + Clerk drafting into its own working-folder.
  APPROVAL — real mutations; pending_approval unless a server-issued action-key for
             THIS exact (tool, args) is in the run's approved set (model can't self-approve).
  DENY     — money/payment + external-to-human sends; refused even WITH a valid key.
  UNKNOWN  — fail-closed: any unclassified tool is DENIED until explicitly mapped.

Pure unit tests — fake model client, no live Qwen/DB.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from orchestrator.clerk_runtime import (
    ClerkAgent,
    ClerkToolRegistry,
    _ToolResponse,
    _TextBlock,
    _ToolUseBlock,
    _classify_tool,
    _clerk_action_key,
    CLERK_ALLOW,
    CLERK_APPROVAL,
    CLERK_DENY,
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
        base_url="https://qwen.example/v1", api_key="test-key", model="qwen3-coder",
        backend="qwen3_hosted", max_steps=max_steps, task_timeout_s=timeout,
    )


# ── _classify_tool: every class + fail-closed default ────────────────────────

@pytest.mark.parametrize("name", [
    "baker_search", "email_search", "document_fetch", "transcripts_by_matter",
    "format_convert", "file_save", "baker_deadlines", "baker_raw_query",
    "baker_grok_web_search", "baker_inbox_post",
])
def test_classify_allow(name):
    assert _classify_tool(name) == CLERK_ALLOW


@pytest.mark.parametrize("name", [
    "baker_vault_write", "baker_raw_write", "baker_ingest_text", "baker_store_decision",
    "baker_add_deadline", "baker_upsert_vip", "baker_upsert_matter",
])
def test_classify_approval(name):
    assert _classify_tool(name) == CLERK_APPROVAL


@pytest.mark.parametrize("name", [
    "baker_gmail_send", "gmail_send", "email_send", "whatsapp_send", "slack_send",
    "baker_payment", "baker_wire", "some_payout_tool", "wire_funds",
])
def test_classify_deny(name):
    assert _classify_tool(name) == CLERK_DENY


@pytest.mark.parametrize("name", ["", "frobnicate", "totally_new_tool", "baker_unmapped_xyz"])
def test_classify_unknown_is_denied_fail_closed(name):
    assert _classify_tool(name) == CLERK_DENY


# ── _clerk_action_key: stable + args-sensitive ───────────────────────────────

def test_action_key_stable_and_args_sensitive():
    a = _clerk_action_key("baker_raw_write", {"sql": "UPDATE x SET y=1"})
    b = _clerk_action_key("baker_raw_write", {"sql": "UPDATE x SET y=1"})
    c = _clerk_action_key("baker_raw_write", {"sql": "UPDATE x SET y=2"})
    d = _clerk_action_key("baker_store_decision", {"sql": "UPDATE x SET y=1"})
    assert a == b           # same tool+args -> same key
    assert a != c           # different args -> different key
    assert a != d           # different tool -> different key
    # key order doesn't matter (canonicalized)
    assert _clerk_action_key("t", {"a": 1, "b": 2}) == _clerk_action_key("t", {"b": 2, "a": 1})


# ── run()-level enforcement: ALLOW / APPROVAL / DENY / UNKNOWN ────────────────

def test_allow_tool_runs(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "outputs.dashboard",
        SimpleNamespace(search_documents_core=lambda *a, **k: {
            "results": [{"id": 1, "title": "n.pdf", "summary": "x"}], "total": 3, "mode": "semantic",
        }),
    )
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("c1", "baker_search", {"query": "nvidia"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("3 documents.")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("how many documents mention nvidia")
    assert result["status"] == "ready"
    assert any(c["name"] == "baker_search" for c in result["tool_calls"])


def test_approval_tool_returns_pending_not_executed():
    # An APPROVAL-class tool with no approved action-key -> pending_approval, never run.
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("w1", "baker_raw_write", {"sql": "UPDATE deals SET x=1"})], "tool_use", 10, 5),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("update the deals table")
    assert result["status"] == "pending_approval"
    assert result["pending_tool"] == "baker_raw_write"
    assert result["tool_calls"] == []           # never executed
    assert len(client.messages.calls) == 1      # aborted at the gate


def test_approval_tool_runs_when_action_key_approved():
    # The gate must PASS when the exact (tool,args) action-key is server-approved.
    args = {"sql": "UPDATE deals SET x=1"}
    key = _clerk_action_key("baker_raw_write", args)
    agent = ClerkAgent(registry=ClerkToolRegistry(), cfg=_cfg(), approved_actions={key})
    block = agent._policy_gate(
        SimpleNamespace(name="baker_raw_write", input=args),
        [], agent._new_usage_totals(), [],
    )
    assert block is None                         # approved -> proceeds past the gate
    # and a DIFFERENT args value with the same approval set is still pending
    block2 = agent._policy_gate(
        SimpleNamespace(name="baker_raw_write", input={"sql": "DROP TABLE deals"}),
        [], agent._new_usage_totals(), [],
    )
    assert block2 is not None and block2["status"] == "pending_approval"


def test_deny_tool_refused_even_with_valid_action_key():
    # DENY is unconditional: a valid approval key must NOT let it run.
    args = {"to": "x@y.com", "body": "hi"}
    key = _clerk_action_key("whatsapp_send", args)
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("s1", "whatsapp_send", args)], "tool_use", 10, 5),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg(), approved_actions={key})
    result = agent.run("send a whatsapp")
    assert result["status"] == "blocked"
    assert result["denied_tool"] == "whatsapp_send"
    assert result["tool_calls"] == []
    assert len(client.messages.calls) == 1


def test_unknown_tool_denied_fail_closed():
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("u1", "frobnicate_files", {"x": 1})], "tool_use", 10, 5),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("do the thing")
    assert result["status"] == "blocked"
    assert result["denied_tool"] == "frobnicate_files"
    assert result["tool_calls"] == []
