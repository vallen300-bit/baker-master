"""GROK_4_5_WEEK_TRIAL_1 — trial-route governor unit tests (no DB).

Exercises the route flag, exact-model allowlist, conservative reservation
estimate, actual-USD flooring, and the reserve→call→settle / release-on-failure
orchestration with the ledger + client monkeypatched out.
"""
from __future__ import annotations

import json

import pytest

from orchestrator import xai_trial_route as trial


# ─────────────────────────── route flag ───────────────────────────

def test_enabled_routes_unset_is_empty(monkeypatch):
    monkeypatch.delenv("GROK45_ENABLED_ROUTES", raising=False)
    assert trial.enabled_routes() == frozenset()
    assert trial.is_route_enabled("b4_runtime") is False


def test_enabled_routes_blank_is_empty(monkeypatch):
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "   ")
    assert trial.enabled_routes() == frozenset()


def test_enabled_routes_parses_comma_list(monkeypatch):
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "b4_runtime, researcher_channel ")
    assert trial.enabled_routes() == frozenset({"b4_runtime", "researcher_channel"})
    assert trial.is_route_enabled("b4_runtime") is True
    assert trial.is_route_enabled("researcher_shadow_synth") is False


def test_is_route_enabled_rejects_unknown_route_in_env(monkeypatch):
    # P2: a route string that is NOT a brief-scoped KNOWN_ROUTES key must never
    # enable, even if someone lists it (typo, stale config) in the env.
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "b4_runtime, bogus_route")
    assert "bogus_route" not in trial.KNOWN_ROUTES
    assert trial.is_route_enabled("bogus_route") is False
    assert trial.is_route_enabled("b4_runtime") is True


# ─────────────────────────── reservation math ───────────────────────────

def test_estimate_reserve_is_conservative():
    # est input tokens = ceil(chars/3)+floor; reserve must exceed a naive
    # chars/4 token cost and be strictly positive.
    prompt = "x" * 3000
    reserve = trial.estimate_reserve_usd(prompt, None, max_output_tokens=4000,
                                         include_tool_allowance=False)
    assert reserve > 0
    # grok-4.5 = $2/M in, $6/M out. Naive input tokens ~ 3000/4 = 750.
    naive_in_cost = (750 * 2.0) / 1_000_000.0
    out_cost = (4000 * 6.0) / 1_000_000.0
    assert reserve >= naive_in_cost + out_cost  # over-reserves input


def test_estimate_reserve_tool_allowance_adds():
    base = trial.estimate_reserve_usd("hi", None, 100, include_tool_allowance=False)
    with_tool = trial.estimate_reserve_usd("hi", None, 100, include_tool_allowance=True)
    assert with_tool > base


def test_actual_usd_floors_on_model_rate():
    # payload cost_usd computed at grok-4.3 rate would undercount; we floor on 4.5.
    tokens_in, tokens_out = 1_000_000, 1_000_000
    model_rate = (tokens_in * 2.0 + tokens_out * 6.0) / 1_000_000.0  # $8
    low_payload = {"cost_usd": 3.75}  # 4.3-rate fallback ($1.25+$2.50)
    assert trial._actual_usd(low_payload, tokens_in, tokens_out) == pytest.approx(model_rate)


def test_actual_usd_takes_payload_when_higher():
    # authoritative ticks may include a surcharge above the token rate.
    tokens_in, tokens_out = 1000, 1000
    high_payload = {"cost_usd": 5.0}
    assert trial._actual_usd(high_payload, tokens_in, tokens_out) == pytest.approx(5.0)


# ─────────────────────────── governed call ───────────────────────────

class _FakeClient:
    def __init__(self, payload=None, raises=None):
        self._payload = payload or {"text": "ok", "model": "grok-4.5",
                                    "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.0}
        self._raises = raises
        self.calls = []

    def ask(self, prompt, model, max_output_tokens, instructions=None, timeout=None):
        self.calls.append({"prompt": prompt, "model": model,
                           "max_output_tokens": max_output_tokens})
        if self._raises:
            raise self._raises
        return dict(self._payload)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "b4_runtime")
    # neutralize DB-touching audit writes
    monkeypatch.setattr(trial.ledger, "write_call_audit", lambda **k: None)


def test_unknown_route_rejected_loud_and_skips_client(enabled, monkeypatch):
    # P2: an unknown route fails loud with a DISTINCT reason (route_unknown), not
    # route_disabled, and never touches the client.
    client = _FakeClient()
    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="not_a_real_route")
    assert ei.value.info["reason"] == "route_unknown"
    assert "known_routes" in ei.value.info
    assert client.calls == []


def test_unknown_route_audits_before_client_build(monkeypatch):
    # codex #11398 double-fault: an unknown route + a client factory that raises
    # (e.g. XAI_API_KEY absent) must STILL write the blocked_route_unknown audit row
    # and NEVER invoke the factory — validation precedes client construction. The old
    # eager `client=_get_client()` arg raised before case (0) could audit → 0 rows.
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "b4_runtime")
    rows = []
    monkeypatch.setattr(trial.ledger, "write_call_audit", lambda **k: rows.append(k))
    built = []

    def boom():
        built.append(True)
        raise RuntimeError("XAI_API_KEY missing")

    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=boom, prompt="hi", route="not_a_real_route")
    assert ei.value.info["reason"] == "route_unknown"
    assert built == []  # factory never called — route validated first
    assert len(rows) == 1
    assert rows[0]["outcome"] == "blocked_route_unknown"
    assert rows[0]["error_class"] == "route_unknown"


def test_client_init_failure_on_valid_route_audits_and_skips_reserve(monkeypatch):
    # A valid, enabled route whose client cannot be built (missing key) is itself a
    # rejected attempt: audit blocked_client_init, fail loud, and take NO reservation
    # (the build happens before reserve, so no hold leaks).
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "b4_runtime")
    rows = []
    monkeypatch.setattr(trial.ledger, "write_call_audit", lambda **k: rows.append(k))
    reserved = []
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: reserved.append(k) or {"granted": True, "reason": "ok"})

    def boom():
        raise RuntimeError("XAI_API_KEY missing")

    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=boom, prompt="hi", route="b4_runtime")
    assert ei.value.info["reason"] == "client_init_failed"
    assert reserved == []  # no hold taken
    assert [r["outcome"] for r in rows] == ["blocked_client_init"]


def test_reservation_week_threaded_to_settle(enabled, monkeypatch):
    # P1-3: the week captured at reserve time must be passed to settle, so a call
    # crossing Monday 00:00Z settles in the SAME week it reserved in.
    seen = {}
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: (seen.update({"reserve_week": k.get("week")}),
                                     {"granted": True, "reason": "ok"})[1])
    monkeypatch.setattr(trial.ledger, "settle",
                        lambda ref, actual, route, **k: (
                            seen.update({"settle_week": k.get("week")}),
                            {"settled": True, "released_residual_usd": 0.0})[1])
    monkeypatch.setattr(trial, "_settle_into_api_cost_log", lambda *a, **k: None)
    client = _FakeClient()
    trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert seen["reserve_week"] is not None
    assert seen["reserve_week"] == seen["settle_week"]


def test_reservation_week_threaded_to_release_on_failure(enabled, monkeypatch):
    # P1-3: the same pinned week must reach release() when the call fails.
    seen = {}
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: (seen.update({"reserve_week": k.get("week")}),
                                     {"granted": True, "reason": "ok"})[1])
    monkeypatch.setattr(trial.ledger, "release",
                        lambda ref, route, **k: seen.update({"release_week": k.get("week")}))
    monkeypatch.setattr(trial.ledger, "settle", lambda *a, **k: {"settled": True})
    client = _FakeClient(raises=RuntimeError("xai 500"))
    with pytest.raises(trial.GrokTrialError):
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert seen["reserve_week"] is not None
    assert seen["reserve_week"] == seen["release_week"]


def test_route_disabled_raises_and_skips_client(monkeypatch):
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "")
    monkeypatch.setattr(trial.ledger, "write_call_audit", lambda **k: None)
    client = _FakeClient()
    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert ei.value.info["reason"] == "route_disabled"
    assert client.calls == []


def test_model_not_allowed_fails_loud(enabled, monkeypatch):
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: {"granted": True, "reason": "ok"})
    client = _FakeClient()
    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime",
                           model="grok-4.3")
    assert ei.value.info["reason"] == "model_not_allowed"
    assert client.calls == []  # no fallback, no call


def test_weekly_cap_block_skips_client(enabled, monkeypatch):
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: {"granted": False, "reason": "weekly_cap_reached",
                                     "remaining_usd": 0.0, "cap_usd": 150.0,
                                     "effective_used_usd": 150.0})
    released = []
    monkeypatch.setattr(trial.ledger, "release",
                        lambda *a, **k: released.append(a))
    client = _FakeClient()
    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert ei.value.info["reason"] == "weekly_cap_reached"
    assert client.calls == []
    assert released == []  # nothing was reserved, so nothing to release


def test_happy_path_settles_and_forces_grok45(enabled, monkeypatch):
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: {"granted": True, "reason": "ok"})
    settled = {}
    monkeypatch.setattr(trial.ledger, "settle",
                        lambda ref, actual, route, **k: settled.update(
                            {"ref": ref, "actual": actual, "route": route})
                        or {"settled": True, "released_residual_usd": 0.0})
    logged = {}
    monkeypatch.setattr(trial, "_settle_into_api_cost_log",
                        lambda ti, to, actual, ms: logged.update({"actual": actual}))
    client = _FakeClient(payload={"text": "a", "model": "grok-4.5",
                                  "tokens_in": 1000, "tokens_out": 1000, "cost_usd": 0.0})
    out = trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert client.calls[0]["model"] == "grok-4.5"  # allowlist enforced
    assert out["_trial"]["route"] == "b4_runtime"
    assert out["_trial"]["model"] == "grok-4.5"
    assert out["_trial"]["settle_ok"] is True
    # actual = 1000*2/M + 1000*6/M = 0.008
    assert settled["actual"] == pytest.approx(0.008)
    assert logged["actual"] == pytest.approx(0.008)


def test_settle_failure_retained_and_audited(enabled, monkeypatch):
    """P1-2: a persistent settle failure must NOT release the reserve, must NOT
    claim outcome=ok, and must surface settle_ok=False (spend stays counted)."""
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: {"granted": True, "reason": "ok"})
    attempts = {"n": 0}

    def _fail_settle(ref, actual, route, **k):
        attempts["n"] += 1
        return {"settled": False, "reason": "ledger_unavailable"}
    monkeypatch.setattr(trial.ledger, "settle", _fail_settle)
    released = []
    monkeypatch.setattr(trial.ledger, "release",
                        lambda *a, **k: released.append(a))
    audit = {}
    monkeypatch.setattr(trial.ledger, "write_call_audit",
                        lambda **k: audit.update(k))
    monkeypatch.setattr(trial, "_settle_into_api_cost_log", lambda *a, **k: None)

    client = _FakeClient(payload={"text": "a", "model": "grok-4.5",
                                  "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.0})
    out = trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert attempts["n"] == trial._SETTLE_MAX_ATTEMPTS   # retried
    assert released == []                                # reservation RETAINED
    assert audit.get("outcome") == "settle_failed"       # audit reflects failure
    assert out["_trial"]["settle_ok"] is False


def test_call_failure_releases_reservation(enabled, monkeypatch):
    monkeypatch.setattr(trial.ledger, "reserve",
                        lambda **k: {"granted": True, "reason": "ok"})
    released = []
    monkeypatch.setattr(trial.ledger, "release",
                        lambda ref, route, **k: released.append((ref, route)))
    settle_called = []
    monkeypatch.setattr(trial.ledger, "settle",
                        lambda *a, **k: settle_called.append(a))
    client = _FakeClient(raises=RuntimeError("xai 500"))
    with pytest.raises(trial.GrokTrialError) as ei:
        trial.run_grok_ask(client_factory=lambda: client, prompt="hi", route="b4_runtime")
    assert ei.value.info["reason"] == "grok_call_failed"
    assert ei.value.info["error_class"] == "RuntimeError"
    assert len(released) == 1          # reservation released
    assert settle_called == []         # never settled


# ─────────────────────────── dispatcher integration ───────────────────────────

def test_dispatch_grok45_trial_only_without_route(monkeypatch):
    """Raw model='grok-4.5' with no enabled route is rejected (no ungoverned 4.5)."""
    pytest.importorskip("mcp")  # tools.grok imports mcp.types; skip if absent (local)
    from tools import grok as grok_tools
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "")
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker",
                        lambda: (True, 0.0))

    class _C:
        def ask(self, *a, **k):
            raise AssertionError("client should not be called")
    monkeypatch.setattr(grok_tools, "_get_client", lambda: _C())
    out = grok_tools.dispatch_grok("baker_grok_ask",
                                   {"prompt": "hi", "model": "grok-4.5"})
    assert "trial-only" in out


def test_dispatch_route_disabled_falls_back_to_normal(monkeypatch):
    """A route that is not enabled behaves as a normal grok-4.3 call."""
    pytest.importorskip("mcp")  # tools.grok imports mcp.types; skip if absent (local)
    from tools import grok as grok_tools
    monkeypatch.setenv("GROK45_ENABLED_ROUTES", "")
    monkeypatch.setattr("orchestrator.cost_monitor.check_circuit_breaker",
                        lambda: (True, 0.0))
    monkeypatch.setattr("orchestrator.cost_monitor.log_api_cost",
                        lambda *a, **k: None, raising=False)

    seen = {}

    class _C:
        def ask(self, prompt, max_output_tokens=4000, model="grok-4.3",
                instructions=None, timeout=None):
            seen["model"] = model
            return {"text": "a", "model": model}
    monkeypatch.setattr(grok_tools, "_get_client", lambda: _C())
    out = grok_tools.dispatch_grok("baker_grok_ask",
                                   {"prompt": "hi", "route": "b4_runtime"})
    assert seen["model"] == "grok-4.3"  # disabled route → normal path
    assert json.loads(out)["model"] == "grok-4.3"
