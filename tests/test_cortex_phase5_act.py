"""Tests for orchestrator/cortex_phase5_act.py — CORTEX_3T_FORMALIZE_1C.

Coverage: cortex_approve / _edit / _refresh / _reject handlers + helpers
(_is_fresh fail-open, _load_cycle, _archive_cycle SQL, _write_feedback_ledger
schema match, _write_gold_proposals via gold_proposer (Amendment A1), DRY_RUN
gate).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator import cortex_phase5_act as p5


# --------------------------------------------------------------------------
# Captured-SQL stub harness
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows=None):
        self.queries: list[tuple] = []
        self._rows = list(rows) if rows else []

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows_per_query=None):
        self.cur = _FakeCursor(rows=rows_per_query)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self, rows=None):
        self.conns: list[_FakeConn] = []
        self._rows = rows or []

    def _get_conn(self):
        c = _FakeConn(rows_per_query=list(self._rows))
        self.conns.append(c)
        return c

    def _put_conn(self, c):
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(p5, "_get_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def _reset_dry_run(monkeypatch):
    monkeypatch.delenv("CORTEX_DRY_RUN", raising=False)


@pytest.fixture(autouse=True)
def _bypass_cas(monkeypatch):
    """CORTEX_PHASE5_IDEMPOTENCY_1: existing tests focus on non-CAS behavior;
    the CAS guard is exercised in `test_cortex_phase5_idempotency.py`. Bypass
    here so the prior assertions against handler bodies still hold.
    """
    monkeypatch.setattr(p5, "_cas_lock_cycle", lambda *a, **kw: None)
    monkeypatch.setattr(p5, "_cas_release_to_proposed", lambda *a, **kw: None)


# --------------------------------------------------------------------------
# _archive_cycle
# --------------------------------------------------------------------------


def test_archive_cycle_updates_and_inserts(fake_store):
    p5._archive_cycle("cyc-1", status="approved", director_action="gold_approved")
    cur = fake_store.conns[0].cur
    sqls = [q[0] for q in cur.queries]
    assert any("UPDATE cortex_cycles" in s and "status=%s" in s for s in sqls)
    assert any("INSERT INTO cortex_phase_outputs" in s and "'archive'" in s for s in sqls)
    assert fake_store.conns[0].committed is True


# --------------------------------------------------------------------------
# _write_feedback_ledger — schema match (Lesson #44 — verify columns first)
# --------------------------------------------------------------------------


def test_feedback_ledger_uses_canonical_columns(fake_store):
    p5._write_feedback_ledger(
        cycle_id="cyc-1", action="ignore", reason="not relevant",
        target_matter="oskolkov",
    )
    cur = fake_store.conns[0].cur
    sql = cur.queries[0][0]
    # Per migrations/20260418_loop_infrastructure.sql
    assert "action_type" in sql
    assert "target_matter" in sql
    assert "payload" in sql
    assert "director_note" in sql
    # Brief's stale references must not have leaked into the insert
    assert "feedback_type" not in sql


def test_feedback_ledger_payload_includes_cycle_id(fake_store):
    p5._write_feedback_ledger(
        cycle_id="cyc-XYZ", action="ignore", reason="r", target_matter="m",
    )
    params = fake_store.conns[0].cur.queries[0][1]
    payload_json = params[2]
    payload = json.loads(payload_json)
    assert payload["cycle_id"] == "cyc-XYZ"
    assert payload["reason"] == "r"


# --------------------------------------------------------------------------
# cortex_reject path
# --------------------------------------------------------------------------


def test_cortex_reject_archives_and_writes_feedback(monkeypatch, fake_store):
    captured = {}

    async def _go():
        # _load_cycle returns matter_slug for feedback_ledger
        monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "m"})
        monkeypatch.setattr(p5, "_archive_cycle",
                            lambda cid, **kw: captured.update({"archive": (cid, kw)}))
        monkeypatch.setattr(p5, "_write_feedback_ledger",
                            lambda **kw: captured.update({"feedback": kw}))
        return await p5.cortex_reject(cycle_id="cyc-r", body={"reason": "stale"})

    result = asyncio.run(_go())
    assert result["status"] == "rejected"
    assert captured["archive"][0] == "cyc-r"
    assert captured["archive"][1]["status"] == "rejected"
    assert captured["feedback"]["action"] == "ignore"
    assert captured["feedback"]["target_matter"] == "m"


def test_cortex_reject_default_reason_when_missing(monkeypatch):
    captured = {}
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "m"})
    monkeypatch.setattr(p5, "_archive_cycle", lambda cid, **kw: None)
    monkeypatch.setattr(p5, "_write_feedback_ledger",
                        lambda **kw: captured.update({"reason": kw["reason"]}))
    result = asyncio.run(p5.cortex_reject(cycle_id="x", body={}))
    assert result["reason"] == "no_reason_given"
    assert captured["reason"] == "no_reason_given"


# --------------------------------------------------------------------------
# cortex_edit path
# --------------------------------------------------------------------------


def test_cortex_edit_persists_edited_text(fake_store):
    result = asyncio.run(p5.cortex_edit(cycle_id="cyc-e", body={"edits": "new draft"}))
    assert result["status"] == "edits_saved"
    cur = fake_store.conns[0].cur
    sqls = [q[0] for q in cur.queries]
    assert any("INSERT INTO cortex_phase_outputs" in s and "director_edit" in s for s in sqls)
    payload = cur.queries[0][1][1]   # json string
    assert "new draft" in payload


def test_cortex_edit_no_edits_returns_warning(fake_store):
    result = asyncio.run(p5.cortex_edit(cycle_id="x", body={"edits": "   "}))
    assert result["warning"] == "no_edits_provided"


# --------------------------------------------------------------------------
# cortex_approve — DRY_RUN, freshness, full path
# --------------------------------------------------------------------------


def test_cortex_approve_returns_freshness_warning_when_not_fresh(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "m"})
    monkeypatch.setattr(p5, "_is_fresh", lambda cid: False)
    result = asyncio.run(p5.cortex_approve(cycle_id="x", body={}))
    assert result["warning"] == "freshness_check_failed"
    assert result["advice"] == "refresh_first"


def test_cortex_approve_dry_run_skips_execute(monkeypatch):
    monkeypatch.setenv("CORTEX_DRY_RUN", "true")
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: {"matter_slug": "ao", "structured_actions": [{"a": 1}]})
    monkeypatch.setattr(p5, "_is_fresh", lambda cid: True)
    archive_calls = []
    monkeypatch.setattr(p5, "_archive_cycle",
                        lambda cid, **kw: archive_calls.append((cid, kw)))
    write_called = []
    monkeypatch.setattr(p5, "_write_gold_proposals",
                        lambda **kw: write_called.append(kw))
    propagate_calls = []
    monkeypatch.setattr(p5, "_propagate_curated_via_macmini",
                        lambda **kw: propagate_calls.append(kw))
    result = asyncio.run(p5.cortex_approve(
        cycle_id="cyc-d", body={"selected_gold_files": ["a.md"]},
    ))
    assert result["status"] == "dry_run_approved"
    assert write_called == []   # no Gold writes in dry run
    assert propagate_calls == []   # no propagation in dry run
    assert archive_calls and archive_calls[0][1]["director_action"] == "gold_approved"


def test_cortex_approve_writes_gold_then_propagates_then_archives(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle",
                        lambda cid: {"matter_slug": "ao",
                                     "structured_actions": [{"a": 1}, {"b": 2}],
                                     "proposal_text": "P", "synthesis_confidence": 0.9})
    monkeypatch.setattr(p5, "_is_fresh", lambda cid: True)
    order = []
    monkeypatch.setattr(
        p5, "_write_gold_proposals",
        lambda **kw: (
            order.append("gold"),
            {"written": 2, "total": 2, "failed_files": [], "errors": []},
        )[1],
    )
    monkeypatch.setattr(p5, "_propagate_curated_via_macmini",
                        lambda **kw: order.append("propagate"))
    monkeypatch.setattr(p5, "_archive_cycle",
                        lambda cid, **kw: order.append("archive"))

    result = asyncio.run(p5.cortex_approve(
        cycle_id="cyc-a",
        body={"selected_gold_files": ["a.md", "b.md"]},
    ))
    assert order == ["gold", "propagate", "archive"]
    assert result["status"] == "approved"
    assert result["gold_files_written"] == 2
    assert result["actions_logged"] == 2
    # Full-success path: no warning fields
    assert "warning" not in result
    assert "failed_files" not in result


def test_cortex_approve_no_cycle_returns_error(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {})
    result = asyncio.run(p5.cortex_approve(cycle_id="missing", body={}))
    assert result["error"] == "cycle_not_found"


# --------------------------------------------------------------------------
# _is_fresh — fail-OPEN on DB error (Quality Checkpoint #3)
# --------------------------------------------------------------------------


def test_is_fresh_fails_open_on_db_error(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "m"})
    class _Boom:
        def cursor(self):
            class C:
                def execute(self, *a, **k): raise RuntimeError("DB down")
                def close(self): pass
            return C()
        def rollback(self): pass

    class _BoomStore:
        conns = []
        def _get_conn(self): return _Boom()
        def _put_conn(self, c): pass

    monkeypatch.setattr(p5, "_get_store", lambda: _BoomStore())
    assert p5._is_fresh("cyc-x") is True   # fail open → safe to act


def test_is_fresh_returns_false_when_recent_email_matches(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "ao"})
    class _Store:
        def __init__(self):
            self.cur = _FakeCursor(rows=[(1,)])
            self.conn = _FakeConn(rows_per_query=[(1,)])
        def _get_conn(self):
            return self.conn
        def _put_conn(self, c): pass
    monkeypatch.setattr(p5, "_get_store", lambda: _Store())
    assert p5._is_fresh("cyc-1") is False


# --------------------------------------------------------------------------
# _write_gold_proposals — uses gold_proposer per Amendment A1
# --------------------------------------------------------------------------


def test_write_gold_proposals_calls_gold_proposer_propose(monkeypatch):
    proposed = []

    def _fake_propose(entry, *, matter=None, vault_root=None):
        proposed.append({"entry": entry, "matter": matter})
        return Path("/tmp/x")

    import kbl.gold_proposer as gp
    monkeypatch.setattr(gp, "propose", _fake_propose)
    result = p5._write_gold_proposals(
        cycle_id="cyc-aaaa-1234",
        matter_slug="oskolkov",
        selected_files=["funds-flow.md", "deadlines.md"],
        cycle_data={"proposal_text": "PT", "synthesis_confidence": 0.7},
    )
    # CORTEX_PHASE5_IDEMPOTENCY_1: rich dict return shape
    assert result == {
        "written": 2, "total": 2, "failed_files": [], "errors": [],
    }
    assert {p["matter"] for p in proposed} == {"oskolkov"}
    assert proposed[0]["entry"].proposer == "cortex-3t"
    assert proposed[0]["entry"].cortex_cycle_id == "cyc-aaaa-1234"
    assert proposed[0]["entry"].confidence == 0.7


def test_write_gold_proposals_continues_on_individual_failure(monkeypatch):
    calls = []

    def _flaky_propose(entry, *, matter=None, vault_root=None):
        calls.append(entry.topic)
        if "second" in entry.topic:
            raise RuntimeError("vault offline")
        return Path("/tmp/x")

    import kbl.gold_proposer as gp
    monkeypatch.setattr(gp, "propose", _flaky_propose)
    result = p5._write_gold_proposals(
        cycle_id="cyc-zzz",
        matter_slug="movie",
        selected_files=["first.md", "second.md", "third.md"],
        cycle_data={"proposal_text": "", "synthesis_confidence": 0.1},
    )
    assert result["written"] == 2   # second one failed, first + third succeeded
    assert result["total"] == 3
    assert len(calls) == 3           # all 3 attempted
    # The failed entry's topic includes "second.md"; failed_files captures filename.
    assert result["failed_files"] == ["second.md"]
    assert result["errors"] == ["vault offline"]


def test_write_gold_proposals_empty_returns_zero():
    result = p5._write_gold_proposals(
        cycle_id="x", matter_slug="m",
        selected_files=[], cycle_data={},
    )
    assert result == {"written": 0, "total": 0, "failed_files": [], "errors": []}


# --------------------------------------------------------------------------
# _propagate_curated_via_macmini — fallback when env unset
# --------------------------------------------------------------------------


def test_propagate_logs_only_when_mac_mini_host_unset(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MAC_MINI_HOST", raising=False)
    monkeypatch.setattr(p5, "STAGING_ROOT", tmp_path)
    cycle_dir = tmp_path / "cyc-1"
    cycle_dir.mkdir()
    (cycle_dir / "a.md").write_text("x")
    with caplog.at_level("INFO"):
        p5._propagate_curated_via_macmini(cycle_id="cyc-1", matter_slug="ao")
    assert any("log-only" in r.message for r in caplog.records)


def test_propagate_skips_when_no_staged_files(monkeypatch, tmp_path):
    monkeypatch.setattr(p5, "STAGING_ROOT", tmp_path)
    # No directory created → returns silently
    p5._propagate_curated_via_macmini(cycle_id="missing", matter_slug="ao")


# --------------------------------------------------------------------------
# cortex_refresh — invokes Phase 2/3a/3b/3c → run_phase4_propose
# --------------------------------------------------------------------------


def test_cortex_refresh_returns_new_proposal_id(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {"matter_slug": "ao",
                                                          "signal_text": "ping"})

    # Patch the imports used inside cortex_refresh by stubbing modules
    async def _fake_phase2_load(cycle):
        cycle.phase2_load_context = {"signal_text": "ping"}

    async def _fake_phase3a(**kw):
        return SimpleNamespace(capabilities_to_invoke=[], cost_tokens=0, cost_dollars=0.0)

    async def _fake_phase3b(**kw):
        return SimpleNamespace(total_cost_tokens=0, total_cost_dollars=0.0)

    async def _fake_phase3c(**kw):
        return SimpleNamespace(proposal_text="x", structured_actions=[],
                               cost_tokens=0, cost_dollars=0.0)

    async def _fake_phase4(**kw):
        return SimpleNamespace(proposal_id="new-prop-uuid-7777")

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

    result = asyncio.run(p5.cortex_refresh(cycle_id="cyc-r", body={}))
    assert result["status"] == "refreshed"
    assert result["new_proposal_id"] == "new-prop-uuid-7777"


def test_cortex_refresh_no_cycle(monkeypatch):
    monkeypatch.setattr(p5, "_load_cycle", lambda cid: {})
    result = asyncio.run(p5.cortex_refresh(cycle_id="missing", body={}))
    assert result["error"] == "cycle_not_found"
