"""Tests for CORTEX_PHASE5_IDEMPOTENCY_1 — CAS guard + partial-failure surfacing.

Coverage:
  * `_cas_lock_cycle` — direct CAS path: success / already_actioned / no_db.
  * 4 handlers (cortex_approve / _edit / _refresh / _reject) — for each:
      - first-fire happy path (CAS returns None, handler proceeds normally)
      - second-fire idempotent return (CAS returns warning, handler bails)
      - third-fire still idempotent (proves N retries are safe)
  * `_archive_cycle` hardened WHERE-clause path (`from_status='approving'`).
  * `_write_gold_proposals` partial-failure surfacing in `cortex_approve`:
      - all-fail   → status="approved_with_errors"     + warning
      - some-fail  → status="approved_with_partial_errors" + failed_files
      - all-ok     → status="approved" (covered in test_cortex_phase5_act.py)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator import cortex_phase5_act as p5


# --------------------------------------------------------------------------
# Captured-SQL stub harness — matches test_cortex_phase5_act.py shape
# --------------------------------------------------------------------------


class _RowsScript:
    """A scripted `fetchone` source that drains a list of rows in order.

    Each `execute(...)` resets the cursor's pointer to the next pre-scripted
    row. Tests pass `rows_per_call=[(...)]` aligned to the queries the SUT
    will issue; `None` = no row (CAS no-rows-affected path).
    """

    def __init__(self, rows_per_call):
        self._rows = list(rows_per_call)
        self._idx = -1

    def step(self):
        self._idx += 1

    def current(self):
        if 0 <= self._idx < len(self._rows):
            return self._rows[self._idx]
        return None


class _ScriptedCursor:
    def __init__(self, script: _RowsScript):
        self.queries: list[tuple] = []
        self._script = script

    def execute(self, q, params=None):
        self.queries.append((q, params))
        self._script.step()

    def fetchone(self):
        return self._script.current()

    def close(self):
        pass


class _ScriptedConn:
    def __init__(self, script: _RowsScript):
        self.cur = _ScriptedCursor(script)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _ScriptedStore:
    """Returns a fresh _ScriptedConn per `_get_conn()` call.

    Each connection has its own scripted-row sequence so a handler that
    opens conn-A for CAS, conn-B for INSERT, conn-C for archive each see
    the right rows at the right query positions.
    """

    def __init__(self, scripts_per_conn):
        self._scripts = list(scripts_per_conn)
        self.conns: list[_ScriptedConn] = []

    def _get_conn(self):
        script = self._scripts.pop(0) if self._scripts else _RowsScript([])
        c = _ScriptedConn(script)
        self.conns.append(c)
        return c

    def _put_conn(self, c):
        pass


@pytest.fixture(autouse=True)
def _reset_dry_run(monkeypatch):
    monkeypatch.delenv("CORTEX_DRY_RUN", raising=False)


# --------------------------------------------------------------------------
# _cas_lock_cycle — direct unit tests
# --------------------------------------------------------------------------


def test_cas_lock_cycle_first_fire_returns_none(monkeypatch):
    """CAS UPDATE matched → fetchone returns (cycle_id,) → returns None (success)."""
    script = _RowsScript([("cyc-1",)])   # 1 query: UPDATE...RETURNING returns row
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._cas_lock_cycle(
        "cyc-1", from_status="proposed", to_status="approving",
        action_attempted="approve",
    )
    assert result is None
    assert store.conns[0].committed is True
    # Exactly 1 query: the UPDATE.
    assert len(store.conns[0].cur.queries) == 1
    assert "UPDATE cortex_cycles" in store.conns[0].cur.queries[0][0]


def test_cas_lock_cycle_second_fire_returns_already_actioned(monkeypatch):
    """CAS UPDATE matched 0 rows → re-read returns ('approved',) → warning dict."""
    script = _RowsScript([None, ("approved",)])   # UPDATE 0-rows, then SELECT status
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._cas_lock_cycle(
        "cyc-1", from_status="proposed", to_status="approving",
        action_attempted="approve",
    )
    assert result == {
        "warning": "already_actioned",
        "current_status": "approved",
        "cycle_id": "cyc-1",
        "action_attempted": "approve",
    }
    assert store.conns[0].committed is True   # diagnostic re-read commits


def test_cas_lock_cycle_missing_cycle_returns_not_found_marker(monkeypatch):
    """CAS UPDATE 0-rows AND SELECT 0-rows → current_status='<not-found>'."""
    script = _RowsScript([None, None])   # both UPDATE and SELECT miss
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._cas_lock_cycle(
        "cyc-missing", from_status="proposed", to_status="approving",
        action_attempted="approve",
    )
    assert result["warning"] == "already_actioned"
    assert result["current_status"] == "<not-found>"


def test_cas_lock_cycle_no_db_returns_error(monkeypatch):
    """CAS without a DB connection → returns error dict (caller bails)."""
    class _NullStore:
        def _get_conn(self): return None
        def _put_conn(self, c): pass
    monkeypatch.setattr(p5, "_get_store", lambda: _NullStore())
    result = p5._cas_lock_cycle(
        "cyc-1", from_status="proposed", to_status="approving",
        action_attempted="approve",
    )
    assert result == {
        "error": "no_db_connection",
        "cycle_id": "cyc-1",
        "action_attempted": "approve",
    }


# --------------------------------------------------------------------------
# cortex_approve — first / second / third fire (3 of 12)
# --------------------------------------------------------------------------


def test_cortex_approve_first_fire_proceeds_normally(monkeypatch):
    """CAS returns None → handler runs through gold/propagate/archive normally."""
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: {"matter_slug": "ao",
                                     "structured_actions": [],
                                     "proposal_text": "", "synthesis_confidence": 0.0})
    monkeypatch.setattr(p5, "_is_fresh", lambda cid: True)
    monkeypatch.setattr(
        p5, "_write_gold_proposals",
        lambda **kw: {"written": 1, "total": 1, "failed_files": [], "errors": []},
    )
    monkeypatch.setattr(p5, "_propagate_curated_via_macmini", lambda **kw: None)
    monkeypatch.setattr(p5, "_archive_cycle", lambda cid, **kw: None)
    result = asyncio.run(p5.cortex_approve(
        cycle_id="cyc-1", body={"selected_gold_files": ["a.md"]},
    ))
    assert result["status"] == "approved"
    assert result["gold_files_written"] == 1


def test_cortex_approve_second_fire_returns_already_actioned(monkeypatch):
    """CAS returns warning → handler bails BEFORE _load_cycle / _is_fresh / writes."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "approved",
        "cycle_id": "cyc-1",
        "action_attempted": "approve",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    # Sentinels — these MUST NOT be called on second fire
    called = {"load": False, "fresh": False, "gold": False, "archive": False}
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: called.update({"load": True}) or {})
    monkeypatch.setattr(p5, "_is_fresh",
                        lambda cid: called.update({"fresh": True}) or True)
    monkeypatch.setattr(p5, "_write_gold_proposals",
                        lambda **kw: called.update({"gold": True}) or {})
    monkeypatch.setattr(p5, "_archive_cycle",
                        lambda cid, **kw: called.update({"archive": True}))
    result = asyncio.run(p5.cortex_approve(cycle_id="cyc-1", body={}))
    assert result == cas_warning
    assert not any(called.values()), f"downstream invoked on second fire: {called}"


def test_cortex_approve_third_fire_still_idempotent(monkeypatch):
    """Third (and Nth) call also returns the warning — proves N retries are safe."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "approved",
        "cycle_id": "cyc-1",
        "action_attempted": "approve",
    }
    invocations = []
    monkeypatch.setattr(p5, "_cas_lock_cycle",
                        lambda *a, **kw: invocations.append("cas") or cas_warning)
    for _ in range(3):
        result = asyncio.run(p5.cortex_approve(cycle_id="cyc-1", body={}))
        assert result == cas_warning
    assert invocations == ["cas", "cas", "cas"]


# --------------------------------------------------------------------------
# cortex_edit — first / second / third fire (3 of 12)
# --------------------------------------------------------------------------


class _FakeStoreSimple:
    """Single-conn store for cortex_edit happy path (INSERT only)."""

    def __init__(self):
        self.cur = _ScriptedCursor(_RowsScript([]))
        self.conn = _ScriptedConn(_RowsScript([]))
        self.put_called = 0

    def _get_conn(self):
        return self.conn

    def _put_conn(self, c):
        self.put_called += 1


def test_cortex_edit_first_fire_persists_then_releases(monkeypatch):
    """CAS returns None → INSERT runs → release-to-proposed runs."""
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    released = []
    monkeypatch.setattr(p5, "_cas_release_to_proposed",
                        lambda cid, *, from_status: released.append((cid, from_status)))
    store = _FakeStoreSimple()
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = asyncio.run(p5.cortex_edit(
        cycle_id="cyc-e1", body={"edits": "new draft text"},
    ))
    assert result["status"] == "edits_saved"
    assert released == [("cyc-e1", "editing")]


def test_cortex_edit_second_fire_returns_already_actioned_no_insert(monkeypatch):
    """CAS warning → no INSERT, no release."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "editing",
        "cycle_id": "cyc-e1",
        "action_attempted": "edit",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    released = []
    monkeypatch.setattr(p5, "_cas_release_to_proposed",
                        lambda *a, **kw: released.append(1))
    # _get_store should NOT be called on second fire.
    def _boom(): raise AssertionError("_get_store called on second fire")
    monkeypatch.setattr(p5, "_get_store", _boom)
    result = asyncio.run(p5.cortex_edit(
        cycle_id="cyc-e1", body={"edits": "again"},
    ))
    assert result == cas_warning
    assert released == []


def test_cortex_edit_third_fire_still_idempotent(monkeypatch):
    """Third call also returns warning — proves no race-condition skew."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "editing",
        "cycle_id": "cyc-e1",
        "action_attempted": "edit",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    monkeypatch.setattr(p5, "_cas_release_to_proposed", lambda *a, **kw: None)
    for _ in range(3):
        result = asyncio.run(p5.cortex_edit(
            cycle_id="cyc-e1", body={"edits": "still trying"},
        ))
        assert result == cas_warning


# --------------------------------------------------------------------------
# cortex_refresh — first / second / third fire (3 of 12)
# --------------------------------------------------------------------------


def test_cortex_refresh_first_fire_proceeds_then_releases(monkeypatch):
    """CAS returns None → Phase-2/3+4 run → release-to-proposed runs."""
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    released = []
    monkeypatch.setattr(p5, "_cas_release_to_proposed",
                        lambda cid, *, from_status: released.append((cid, from_status)))
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: {"matter_slug": "ao", "signal_text": "x"})

    async def _fake_phase2_load(cycle): cycle.phase2_load_context = {"signal_text": "x"}
    async def _fake_phase3a(**kw):
        return SimpleNamespace(capabilities_to_invoke=[], cost_tokens=0, cost_dollars=0.0)
    async def _fake_phase3b(**kw):
        return SimpleNamespace(total_cost_tokens=0, total_cost_dollars=0.0)
    async def _fake_phase3c(**kw):
        return SimpleNamespace(proposal_text="x", structured_actions=[],
                               cost_tokens=0, cost_dollars=0.0)
    async def _fake_phase4(**kw):
        return SimpleNamespace(proposal_id="new-1234")

    import orchestrator.cortex_runner as runner
    import orchestrator.cortex_phase3_reasoner as r3a
    import orchestrator.cortex_phase3_invoker as r3b
    import orchestrator.cortex_phase3_synthesizer as r3c
    import orchestrator.cortex_phase4_proposal as p4
    monkeypatch.setattr(runner, "_phase2_load", _fake_phase2_load)
    monkeypatch.setattr(r3a, "run_phase3a_meta_reason", _fake_phase3a)
    monkeypatch.setattr(r3b, "run_phase3b_invocations", _fake_phase3b)
    monkeypatch.setattr(r3c, "run_phase3c_synthesize", _fake_phase3c)
    monkeypatch.setattr(p4, "run_phase4_propose", _fake_phase4)

    result = asyncio.run(p5.cortex_refresh(cycle_id="cyc-r1", body={}))
    assert result["status"] == "refreshed"
    assert result["new_proposal_id"] == "new-1234"
    assert released == [("cyc-r1", "refreshing")]


def test_cortex_refresh_second_fire_returns_already_actioned(monkeypatch):
    """CAS warning → no Phase-2/3+4 work, no release."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "refreshing",
        "cycle_id": "cyc-r1",
        "action_attempted": "refresh",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    # _load_cycle should NOT be called.
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: pytest.fail("_load_cycle invoked on second fire"))
    released = []
    monkeypatch.setattr(p5, "_cas_release_to_proposed",
                        lambda *a, **kw: released.append(1))
    result = asyncio.run(p5.cortex_refresh(cycle_id="cyc-r1", body={}))
    assert result == cas_warning
    assert released == []


def test_cortex_refresh_third_fire_still_idempotent(monkeypatch):
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "refreshing",
        "cycle_id": "cyc-r1",
        "action_attempted": "refresh",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    monkeypatch.setattr(p5, "_cas_release_to_proposed", lambda *a, **kw: None)
    for _ in range(3):
        result = asyncio.run(p5.cortex_refresh(cycle_id="cyc-r1", body={}))
        assert result == cas_warning


# --------------------------------------------------------------------------
# cortex_reject — first / second / third fire (3 of 12)
# --------------------------------------------------------------------------


def test_cortex_reject_first_fire_archives_with_from_status(monkeypatch):
    """CAS returns None → archive called with from_status='rejecting'."""
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "ao"})
    archive_kw = {}
    monkeypatch.setattr(p5, "_archive_cycle",
                        lambda cid, **kw: archive_kw.update(kw))
    monkeypatch.setattr(p5, "_write_feedback_ledger", lambda **kw: None)
    result = asyncio.run(p5.cortex_reject(
        cycle_id="cyc-rj1", body={"reason": "bad fit"},
    ))
    assert result["status"] == "rejected"
    assert archive_kw["status"] == "rejected"
    assert archive_kw["from_status"] == "rejecting"


def test_cortex_reject_second_fire_returns_already_actioned(monkeypatch):
    """CAS warning → no archive, no feedback_ledger."""
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "rejected",
        "cycle_id": "cyc-rj1",
        "action_attempted": "reject",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    archive_calls = []
    feedback_calls = []
    monkeypatch.setattr(p5, "_archive_cycle",
                        lambda cid, **kw: archive_calls.append(kw))
    monkeypatch.setattr(p5, "_write_feedback_ledger",
                        lambda **kw: feedback_calls.append(kw))
    result = asyncio.run(p5.cortex_reject(cycle_id="cyc-rj1", body={}))
    assert result == cas_warning
    assert archive_calls == []
    assert feedback_calls == []


def test_cortex_reject_third_fire_still_idempotent(monkeypatch):
    cas_warning = {
        "warning": "already_actioned",
        "current_status": "rejected",
        "cycle_id": "cyc-rj1",
        "action_attempted": "reject",
    }
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: cas_warning)
    for _ in range(3):
        result = asyncio.run(p5.cortex_reject(cycle_id="cyc-rj1", body={}))
        assert result == cas_warning


# --------------------------------------------------------------------------
# _archive_cycle hardened WHERE clause (Quality Checkpoint #4)
# --------------------------------------------------------------------------


def test_archive_cycle_with_from_status_succeeds_on_match(monkeypatch):
    """from_status='approving' + UPDATE returns row → INSERT proceeds."""
    script = _RowsScript([("cyc-a1",)])   # UPDATE...RETURNING returns row; INSERT no fetchone
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._archive_cycle(
        "cyc-a1", status="approved", director_action="gold_approved",
        from_status="approving",
    )
    assert result is None   # success
    sqls = [q[0] for q in store.conns[0].cur.queries]
    # Both UPDATE and INSERT happened
    assert any("UPDATE cortex_cycles" in s and "AND status=%s" in s for s in sqls)
    assert any("INSERT INTO cortex_phase_outputs" in s for s in sqls)


def test_archive_cycle_with_from_status_returns_warning_on_mismatch(monkeypatch):
    """from_status='approving' + UPDATE returns no rows → warning, NO INSERT."""
    script = _RowsScript([None])   # UPDATE...RETURNING fetches None
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._archive_cycle(
        "cyc-a2", status="approved", director_action="gold_approved",
        from_status="approving",
    )
    assert result == {
        "warning": "archive_unexpected_state",
        "cycle_id": "cyc-a2",
        "expected_from_status": "approving",
        "target_status": "approved",
    }
    sqls = [q[0] for q in store.conns[0].cur.queries]
    # UPDATE happened, INSERT did NOT (would otherwise create duplicate audit row).
    assert any("UPDATE cortex_cycles" in s for s in sqls)
    assert not any("INSERT INTO cortex_phase_outputs" in s for s in sqls)


def test_archive_cycle_without_from_status_legacy_unconditional(monkeypatch):
    """from_status=None → unconditional UPDATE + INSERT (backward compat)."""
    script = _RowsScript([])   # legacy path doesn't fetchone
    store = _ScriptedStore([script])
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    result = p5._archive_cycle(
        "cyc-a3", status="approved", director_action="gold_approved",
    )
    assert result is None
    sqls = [q[0] for q in store.conns[0].cur.queries]
    assert any("UPDATE cortex_cycles" in s and "AND status=%s" not in s for s in sqls)
    assert any("INSERT INTO cortex_phase_outputs" in s for s in sqls)


# --------------------------------------------------------------------------
# Partial-failure surfacing in cortex_approve (OBS-2 — 2 tests)
# --------------------------------------------------------------------------


def _approve_baseline_monkeypatches(monkeypatch, *, gold_result):
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: {"matter_slug": "ao",
                                     "structured_actions": [],
                                     "proposal_text": "P", "synthesis_confidence": 0.5})
    monkeypatch.setattr(p5, "_is_fresh", lambda cid: True)
    monkeypatch.setattr(p5, "_write_gold_proposals",
                        lambda **kw: gold_result)
    monkeypatch.setattr(p5, "_propagate_curated_via_macmini", lambda **kw: None)
    monkeypatch.setattr(p5, "_archive_cycle", lambda cid, **kw: None)


def test_cortex_approve_all_gold_fails_returns_approved_with_errors(monkeypatch):
    """3 selected files, ALL fail → status='approved_with_errors' + warning."""
    _approve_baseline_monkeypatches(
        monkeypatch,
        gold_result={
            "written": 0, "total": 3,
            "failed_files": ["a.md", "b.md", "c.md"],
            "errors": ["DB down", "DB down", "DB down"],
        },
    )
    result = asyncio.run(p5.cortex_approve(
        cycle_id="cyc-pf1",
        body={"selected_gold_files": ["a.md", "b.md", "c.md"]},
    ))
    assert result["status"] == "approved_with_errors"
    assert result["warning"] == "all_gold_proposals_failed"
    assert result["gold_files_attempted"] == 3
    assert result["gold_files_written"] == 0
    assert result["errors"] == ["DB down", "DB down", "DB down"]


def test_cortex_approve_some_gold_fails_returns_approved_with_partial_errors(monkeypatch):
    """3 selected files, 2 succeed + 1 fails → status='approved_with_partial_errors'."""
    _approve_baseline_monkeypatches(
        monkeypatch,
        gold_result={
            "written": 2, "total": 3,
            "failed_files": ["b.md"],
            "errors": ["schema mismatch"],
        },
    )
    result = asyncio.run(p5.cortex_approve(
        cycle_id="cyc-pf2",
        body={"selected_gold_files": ["a.md", "b.md", "c.md"]},
    ))
    assert result["status"] == "approved_with_partial_errors"
    assert result["warning"] == "some_gold_proposals_failed"
    assert result["gold_files_attempted"] == 3
    assert result["gold_files_written"] == 2
    assert result["failed_files"] == ["b.md"]
