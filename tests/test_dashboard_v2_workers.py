"""BAKER_DASHBOARD_V2_PIPELINE_ACTIVATION_1: tests for the activation workers.

Pure-logic + monkeypatched seams — no DB, no LLM, no real scheduler. Proves:
- AC1: all flags OFF (default) => zero-op (ticks skip, registration adds no job),
- AC2: producer, when enabled, calls both bridges bounded + aggregates counts
       (idempotency is the bridges' ON CONFLICT; producer surfaces created/skipped),
- AC3: verifier processes <= MAX_PER_TICK and stops on the cost breaker,
- AC4: ticks are fault-tolerant — a bridge/verify/queue failure never raises,
- AC5: no new model selection — verify_candidate is called with no model override,
- registration is flag-gated (jobs appear only when enabled).
"""
from __future__ import annotations

import orchestrator.dashboard_v2_workers as w
import orchestrator.candidate_ingest as ci
import orchestrator.candidate_verifier as cv


# Flag env names, cleared before every test so defaults (OFF) are exercised.
_FLAGS = (
    "DASHBOARD_V2_BRIDGE_ENABLED", "DASHBOARD_V2_VERIFIER_ENABLED",
    "DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "DASHBOARD_V2_BRIDGE_MAX_PER_TICK",
    "DASHBOARD_V2_BRIDGE_INTERVAL_SECONDS", "DASHBOARD_V2_VERIFIER_INTERVAL_SECONDS",
)


def _clear(monkeypatch):
    for f in _FLAGS:
        monkeypatch.delenv(f, raising=False)


class _FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger, *, id=None, **kw):
        self.jobs.append(id)


# --- AC1: flags OFF (default) => zero-op --------------------------------------

def test_default_flags_are_off(monkeypatch):
    _clear(monkeypatch)
    assert w.bridge_enabled() is False
    assert w.verifier_enabled() is False
    assert w.verifier_max_per_tick() == 0


def test_producer_tick_zero_op_when_disabled(monkeypatch):
    _clear(monkeypatch)
    called = []
    monkeypatch.setattr(ci, "bridge_pending_alerts", lambda **k: called.append("a"))
    monkeypatch.setattr(ci, "bridge_active_deadlines", lambda **k: called.append("d"))
    res = w.run_candidate_producer_tick()
    assert res["skipped"] is True
    assert called == [], "no bridge call may happen with the flag off"


def test_verifier_tick_zero_op_when_disabled(monkeypatch):
    _clear(monkeypatch)
    called = []
    monkeypatch.setattr(cv, "verify_candidate", lambda cid, **k: called.append(cid))
    monkeypatch.setattr(ci, "list_candidates", lambda **k: called.append("listed") or [])
    res = w.run_verifier_queue_tick()
    assert res["skipped"] is True
    assert called == [], "no queue read / LLM call may happen with the flag off"


def test_verifier_tick_zero_op_when_cap_zero(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    # cap defaults to 0 => still a no-op even though the flag is on
    res = w.run_verifier_queue_tick()
    assert res["skipped"] is True and "MAX_PER_TICK" in res["reason"]


def test_registration_adds_no_jobs_when_disabled(monkeypatch):
    _clear(monkeypatch)
    sched = _FakeScheduler()
    registered = w.register_dashboard_v2_workers(sched)
    assert registered == [] and sched.jobs == []


# --- AC2: producer, when enabled, bridges bounded + aggregates ----------------

def test_producer_calls_both_bridges_bounded(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_BRIDGE_MAX_PER_TICK", "50")
    seen = {}
    monkeypatch.setattr(ci, "bridge_pending_alerts",
                        lambda **k: seen.update(alerts=k.get("limit")) or
                        {"ok": True, "bridged": 3, "skipped": 1, "failed": 0, "scanned": 4})
    monkeypatch.setattr(ci, "bridge_active_deadlines",
                        lambda **k: seen.update(deadlines=k.get("limit")) or
                        {"ok": True, "bridged": 2, "skipped": 0, "failed": 0, "scanned": 2})
    res = w.run_candidate_producer_tick()
    assert seen == {"alerts": 50, "deadlines": 50}
    assert res["ok"] and res["bridged"] == 5 and res["skipped"] == 1 and res["scanned"] == 6


def test_producer_idempotent_rerun_counts_skips(monkeypatch):
    """Second run over the same pool: the bridges' ON CONFLICT yields created=False
    -> the producer surfaces them as `skipped`, not `bridged` (idempotent)."""
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_BRIDGE_ENABLED", "true")
    monkeypatch.setattr(ci, "bridge_pending_alerts",
                        lambda **k: {"ok": True, "bridged": 0, "skipped": 4, "failed": 0, "scanned": 4})
    monkeypatch.setattr(ci, "bridge_active_deadlines",
                        lambda **k: {"ok": True, "bridged": 0, "skipped": 2, "failed": 0, "scanned": 2})
    res = w.run_candidate_producer_tick()
    assert res["bridged"] == 0 and res["skipped"] == 6


# --- AC3: verifier cap + cost breaker -----------------------------------------

def test_verifier_respects_cap(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "3")
    # queue returns MORE than the cap; worker must process at most cap
    monkeypatch.setattr(ci, "list_candidates",
                        lambda **k: [{"id": i} for i in range(10)])
    calls = []
    monkeypatch.setattr(cv, "verify_candidate",
                        lambda cid, **k: calls.append((cid, k)) or {"ok": True})
    res = w.run_verifier_queue_tick()
    assert res["processed"] == 3 and res["promoted"] == 3
    assert len(calls) == 3
    # AC5: no model override passed — verify_candidate owns model selection
    assert all(k == {} for _, k in calls)


def test_verifier_stops_on_cost_breaker(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "5")
    monkeypatch.setattr(ci, "list_candidates",
                        lambda **k: [{"id": i} for i in range(5)])
    seq = iter([{"ok": True}, {"ok": False, "error": "cost_hard_stop"}])
    monkeypatch.setattr(cv, "verify_candidate", lambda cid, **k: next(seq))
    res = w.run_verifier_queue_tick()
    assert res["cost_stopped"] is True
    assert res["promoted"] == 1 and res["processed"] == 1  # 2nd call stopped the tick


def test_verifier_counts_refused_and_parks(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "3")
    monkeypatch.setattr(ci, "list_candidates", lambda **k: [{"id": 1}, {"id": 2}, {"id": 3}])
    seq = iter([
        {"ok": True},
        {"ok": False, "error": "verification_refused", "reasons": ["verdict_reject"]},
        {"ok": False, "error": "source_not_found"},  # pre-model, no cost -> NOT parked
    ])
    monkeypatch.setattr(cv, "verify_candidate", lambda cid, **k: next(seq))
    parked = []
    monkeypatch.setattr(ci, "mark_candidate_auto_refused",
                        lambda cid, **k: parked.append(cid) or {"ok": True, "parked": True})
    res = w.run_verifier_queue_tick()
    assert res["promoted"] == 1 and res["refused"] == 1 and res["errored"] == 1
    # only the verification_refused candidate (id 2) is parked; source_not_found is not
    assert parked == [2] and res["parked"] == 1


def test_refused_candidate_parked_not_reverified_next_tick(monkeypatch):
    """G2 F1 regression: a refused candidate is parked out of the awaiting queue,
    so a SECOND tick does NOT call verify_candidate on it again (no repeat cost)."""
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "5")

    # Stateful fake DB: id 7 starts awaiting; parking flips it to auto_refused.
    state = {7: "awaiting_verification"}

    def _list(**k):
        st = k.get("status")
        return [{"id": cid} for cid, s in state.items() if s == st]

    verify_calls = []

    def _verify(cid, **k):
        verify_calls.append(cid)
        return {"ok": False, "error": "verification_refused", "reasons": ["verdict_reject"]}

    def _park(cid, **k):
        if state.get(cid) == "awaiting_verification":
            state[cid] = "auto_refused"
            return {"ok": True, "parked": True}
        return {"ok": True, "parked": False}

    monkeypatch.setattr(ci, "list_candidates", _list)
    monkeypatch.setattr(cv, "verify_candidate", _verify)
    monkeypatch.setattr(ci, "mark_candidate_auto_refused", _park)

    t1 = w.run_verifier_queue_tick()
    t2 = w.run_verifier_queue_tick()

    assert verify_calls == [7], "2nd tick must NOT re-verify the parked candidate"
    assert t1["refused"] == 1 and t1["parked"] == 1
    assert t2["processed"] == 0 and t2["refused"] == 0  # queue empty 2nd tick
    assert state[7] == "auto_refused"


def test_park_failure_is_contained(monkeypatch):
    """A failed park (degraded DB) logs but never crashes the tick (AC4)."""
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "2")
    monkeypatch.setattr(ci, "list_candidates", lambda **k: [{"id": 1}])
    monkeypatch.setattr(cv, "verify_candidate",
                        lambda cid, **k: {"ok": False, "error": "verification_refused"})

    def _boom(cid, **k):
        raise RuntimeError("park db down")
    monkeypatch.setattr(ci, "mark_candidate_auto_refused", _boom)
    res = w.run_verifier_queue_tick()  # must not raise
    assert res["refused"] == 1 and res["parked"] == 0


# --- AC4: fault tolerance -----------------------------------------------------

def test_producer_one_bridge_failing_does_not_crash(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_BRIDGE_ENABLED", "true")
    def _boom(**k):
        raise RuntimeError("db down")
    monkeypatch.setattr(ci, "bridge_pending_alerts", _boom)
    monkeypatch.setattr(ci, "bridge_active_deadlines",
                        lambda **k: {"ok": True, "bridged": 1, "skipped": 0, "failed": 0, "scanned": 1})
    res = w.run_candidate_producer_tick()  # must not raise
    assert res["ok"] is False and res["bridged"] == 1  # other bridge still ran


def test_verifier_candidate_raise_is_contained(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "2")
    monkeypatch.setattr(ci, "list_candidates", lambda **k: [{"id": 1}, {"id": 2}])
    def _boom(cid, **k):
        raise RuntimeError("verifier blew up")
    monkeypatch.setattr(cv, "verify_candidate", _boom)
    res = w.run_verifier_queue_tick()  # must not raise
    assert res["errored"] == 2 and res["promoted"] == 0


def test_verifier_queue_read_failure_contained(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "2")
    def _boom(**k):
        raise RuntimeError("select failed")
    monkeypatch.setattr(ci, "list_candidates", _boom)
    res = w.run_verifier_queue_tick()
    assert res["ok"] is False and res["error"] == "queue_read_failed"


# --- registration when enabled ------------------------------------------------

def test_registration_adds_jobs_when_enabled(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "5")
    sched = _FakeScheduler()
    registered = w.register_dashboard_v2_workers(sched)
    assert set(registered) == {"dashboard_v2_candidate_producer", "dashboard_v2_verifier_queue"}
    assert set(sched.jobs) == set(registered)


def test_verifier_cap_clamped_to_ceiling(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DASHBOARD_V2_VERIFIER_MAX_PER_TICK", "9999")
    assert w.verifier_max_per_tick() == w._VERIFIER_HARD_CEILING
