"""CLERK_FULL_CAPABILITY_POLICY_1 PR 2a — live web/X search via Grok wiring.

Registers baker_grok_web_search / baker_grok_x_search / baker_grok_ask into Clerk's
tool loop (read-only ALLOW per the capability policy). Clerk routes them through
tools.grok.dispatch_grok so they inherit the SAME cost circuit-breaker + usage
logging + timeout validation as every other Grok caller (G0 #2391 fix).

Tests use a fake Grok client (no live xAI) and patch the cost breaker.
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
    CLERK_ALLOW,
)


class _FakeGrok:
    """Stands in for kbl.grok_client.GrokClient via tools.grok._get_client."""
    def __init__(self):
        self.calls = []

    def web_search(self, query, allowed_domains=None, excluded_domains=None, timeout=None):
        self.calls.append(("web_search", query))
        return {"summary": f"web: {query}", "citations": [{"url": "https://x.test/a"}], "model": "grok-4.3"}

    def x_search(self, query, from_date=None, to_date=None, allowed_x_handles=None,
                 excluded_x_handles=None, timeout=None):
        self.calls.append(("x_search", query))
        return {"summary": f"x: {query}", "tweets": [{"id": "1"}], "model": "grok-4.3"}

    def ask(self, prompt, max_output_tokens=4000, model="grok-4.3", instructions=None, timeout=None):
        self.calls.append(("ask", prompt))
        return {"text": f"answer: {prompt}", "model": "grok-4.3"}


@pytest.fixture
def fake_grok(monkeypatch):
    grok = _FakeGrok()
    monkeypatch.setattr("tools.grok._get_client", lambda: grok)
    # breaker allows by default; cost logging is best-effort and harmless in tests
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (True, 0.0))
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost", lambda *a, **k: None, raising=False)
    return grok


# ── registration + classification ────────────────────────────────────────────

def test_grok_tools_registered():
    names = [t["name"] for t in ClerkToolRegistry().tools]
    for n in ("baker_grok_web_search", "baker_grok_x_search", "baker_grok_ask"):
        assert n in names


def test_grok_tools_are_allow_class():
    for n in ("baker_grok_web_search", "baker_grok_x_search", "baker_grok_ask"):
        assert _classify_tool(n) == CLERK_ALLOW


# ── handlers route through dispatch_grok (breaker + logging) ──────────────────

def test_grok_web_search_routes_and_returns_payload(fake_grok):
    out = json.loads(ClerkToolRegistry().execute("baker_grok_web_search", {"query": "nvidia earnings"}))
    assert out["summary"] == "web: nvidia earnings"
    assert out["citations"] == [{"url": "https://x.test/a"}]
    assert fake_grok.calls == [("web_search", "nvidia earnings")]


def test_grok_x_search_routes(fake_grok):
    out = json.loads(ClerkToolRegistry().execute("baker_grok_x_search", {"query": "what's hot on AI"}))
    assert out["summary"] == "x: what's hot on AI"
    assert out["tweets"] == [{"id": "1"}]


def test_grok_ask_routes(fake_grok):
    out = json.loads(ClerkToolRegistry().execute("baker_grok_ask", {"prompt": "define IRR"}))
    assert out["text"] == "answer: define IRR"


def test_grok_missing_required_arg_is_fault_tolerant(fake_grok):
    # dispatch_grok surfaces a clean 'Error: missing required arg' string, no crash.
    res = ClerkToolRegistry().execute("baker_grok_web_search", {})
    assert res.startswith("Error: missing required arg")
    assert fake_grok.calls == []  # never reached the client


# ── codex #11369 / #11381 regression: unknown route rejected at the PRODUCTION ──
# dispatcher, WITH the required audit row. Live probe that failed round-2:
# GROK45_ENABLED_ROUTES=bogus_route + route=bogus_route silently called grok-4.3
# (silent downgrade). Round-3 fixed the downgrade but returned early at the
# dispatcher, skipping run_grok_ask → the blocked_route_unknown xai_call_audit row
# (requirement #4: one row per attempt incl. blocked/error) was never written.
# Round-4: rejection is centralized through run_grok_ask so exactly ONE row lands.

@pytest.fixture
def capture_audit(monkeypatch):
    from orchestrator import xai_trial_route as _trial
    rows = []
    monkeypatch.setattr(_trial.ledger, "write_call_audit", lambda **k: rows.append(k))
    return rows


def test_grok_ask_unknown_route_rejected_loud_at_dispatcher(fake_grok, capture_audit, monkeypatch):
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "bogus_route")
    res = ClerkToolRegistry().execute(
        "baker_grok_ask",
        {"prompt": "define IRR", "route": "bogus_route", "matter_slug": "mo-vie"},
    )
    assert res.startswith("Error: grok trial blocked")
    assert "route_unknown" in res
    assert fake_grok.calls == []  # NO silent grok-4.3 downgrade
    # requirement #4: exactly one audit row on the rejected attempt, matter preserved.
    assert len(capture_audit) == 1
    assert capture_audit[0]["outcome"] == "blocked_route_unknown"
    assert capture_audit[0]["error_class"] == "route_unknown"
    assert capture_audit[0]["matter_slug"] == "mo-vie"


def test_grok_ask_known_but_disabled_route_falls_through_to_grok_43(fake_grok, capture_audit, monkeypatch):
    # A KNOWN route that simply is not enabled keeps the designed grok-4.3 path —
    # the fix must not over-reject known-but-off routes. It is NOT a trial attempt,
    # so no audit row is written.
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "")
    out = json.loads(ClerkToolRegistry().execute(
        "baker_grok_ask", {"prompt": "define IRR", "route": "b4_runtime"}
    ))
    assert out["text"] == "answer: define IRR"
    assert fake_grok.calls == [("ask", "define IRR")]  # normal grok-4.3
    assert capture_audit == []  # designed fallthrough is not a trial attempt


def test_grok_ask_unknown_route_audits_even_when_client_ctor_fails(capture_audit, monkeypatch):
    # codex #11398 double-fault: XAI_API_KEY absent + bogus route. The dispatcher now
    # passes a client FACTORY (_get_client) lazily, so run_grok_ask validates the
    # route and writes blocked_route_unknown BEFORE the client ctor can raise on the
    # missing key. Previously the eager client=_get_client() arg raised first → 0 rows.
    built = []

    def boom_client():
        built.append(True)
        raise RuntimeError("XAI_API_KEY missing")

    monkeypatch.setattr("tools.grok._get_client", boom_client)
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "bogus_route")
    res = ClerkToolRegistry().execute(
        "baker_grok_ask", {"prompt": "ping", "route": "bogus_route", "matter_slug": "mo-vie"}
    )
    assert res.startswith("Error: grok trial blocked")
    assert "route_unknown" in res
    assert built == []  # factory never invoked — route validated first
    assert len(capture_audit) == 1
    assert capture_audit[0]["outcome"] == "blocked_route_unknown"


# ── G0 #2391 regression: cost breaker tripped -> ZERO HTTP, blocked ───────────

def test_grok_breaker_tripped_makes_zero_calls(monkeypatch):
    grok = _FakeGrok()
    monkeypatch.setattr("tools.grok._get_client", lambda: grok)
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker", lambda: (False, 150.0))

    res = ClerkToolRegistry().execute("baker_grok_web_search", {"query": "nvidia"})

    assert "circuit breaker tripped" in res
    assert grok.calls == []  # the breaker blocked it BEFORE any xAI call


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


def test_grok_web_search_runs_through_policy_gate(fake_grok):
    client = _FakeClient([
        _ToolResponse([_ToolUseBlock("g1", "baker_grok_web_search", {"query": "nvidia"})], "tool_use", 10, 5),
        _ToolResponse([_TextBlock("Per live web: ...")], "end_turn", 8, 4),
    ])
    agent = ClerkAgent(model_client=client, registry=ClerkToolRegistry(), cfg=_cfg())
    result = agent.run("search the web for nvidia earnings")
    assert result["status"] == "ready"
    assert any(c["name"] == "baker_grok_web_search" for c in result["tool_calls"])
