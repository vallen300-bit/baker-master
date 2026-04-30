"""Tests for ``kbl.steps.step6_finalize.dispatch_cortex_after_finalize``.

CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1 (2026-04-30): the post-Step-6 hook
that fires Cortex dispatch with the canonical ``primary_matter`` written
by Step 1 triage. Replaces the broken bridge-side dispatch which fired
before canonicalization.

Coverage:
  * Idempotent INSERT-IF-NOT-EXISTS in ``baker_actions``.
  * Outcome routing: invoked / skip_no_matter / skip_no_config.
  * Never-raises envelope on every failure mode.
  * Source assertion that the helper exists with the right name.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from kbl.steps import step6_finalize


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fetchone_seq):
        self._seq = list(fetchone_seq)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if not self._seq:
            return None
        return self._seq.pop(0)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cur = cursor
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _FakeStore:
    """Mimics SentinelStoreBack singleton interface used by the helper."""

    def __init__(self, conn):
        self.conn = conn

    @classmethod
    def _get_global_instance(cls):
        return cls._instance

    def _get_conn(self):
        return self.conn

    def _put_conn(self, conn):
        pass


@contextmanager
def _patched(monkeypatch, *, fetchone_seq, has_config, expect_dispatch=False):
    """Wire FakeStore + matter_has_cortex_config + maybe_dispatch monkeypatches.

    ``fetchone_seq`` is the ordered list of return values for each
    ``fetchone()`` call inside the helper. The helper does:
        1. SELECT primary_matter FROM signal_queue ...   → row 1
        2. INSERT ... RETURNING id                        → row 2 (or None)
    """
    cur = _FakeCursor(fetchone_seq)
    conn = _FakeConn(cur)
    store = _FakeStore(conn)
    type(store)._instance = store

    # Ensure no real DB / vault import paths run.
    monkeypatch.setattr(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        lambda slug: has_config,
    )

    dispatch_calls = []

    def _fake_maybe_dispatch(*, signal_id, matter_slug):
        dispatch_calls.append((signal_id, matter_slug))

    monkeypatch.setattr(
        "triggers.cortex_pipeline.maybe_dispatch", _fake_maybe_dispatch,
    )

    yield {"conn": conn, "cur": cur, "dispatch_calls": dispatch_calls}


# --------------------------------------------------------------------------
# happy path — canonical matter with config → invoke
# --------------------------------------------------------------------------


def test_dispatch_invokes_when_canonical_matter_has_config(monkeypatch):
    with _patched(
        monkeypatch,
        fetchone_seq=[
            ("hagenauer-rg7",),  # SELECT primary_matter
            (12345,),            # INSERT ... RETURNING id
        ],
        has_config=True,
    ) as ctx:
        result = step6_finalize.dispatch_cortex_after_finalize(101)

    assert result["outcome"] == "invoked"
    assert result["fired"] is True
    assert result["primary_matter"] == "hagenauer-rg7"
    assert ctx["dispatch_calls"] == [(101, "hagenauer-rg7")]
    assert ctx["conn"].committed == 1


def test_dispatch_skip_no_config_when_canonical_but_no_brain(monkeypatch):
    with _patched(
        monkeypatch,
        fetchone_seq=[("brisen-internal",), (888,)],
        has_config=False,
    ) as ctx:
        result = step6_finalize.dispatch_cortex_after_finalize(202)

    assert result["outcome"] == "skip_no_config"
    assert result["fired"] is False
    assert result["primary_matter"] == "brisen-internal"
    assert ctx["dispatch_calls"] == []
    # Audit row is still written even when gate is skipped — per brief §4.
    assert ctx["conn"].committed == 1


def test_dispatch_skip_no_matter_when_primary_matter_null(monkeypatch):
    with _patched(
        monkeypatch,
        fetchone_seq=[(None,), (999,)],
        has_config=True,
    ) as ctx:
        result = step6_finalize.dispatch_cortex_after_finalize(303)

    assert result["outcome"] == "skip_no_matter"
    assert result["fired"] is False
    assert result["primary_matter"] is None
    assert ctx["dispatch_calls"] == []
    assert ctx["conn"].committed == 1


def test_dispatch_skip_no_matter_when_signal_row_missing(monkeypatch):
    """Race: signal_queue row deleted between Step 6 commit and dispatch."""
    with _patched(
        monkeypatch,
        fetchone_seq=[None, (1,)],
        has_config=True,
    ) as ctx:
        result = step6_finalize.dispatch_cortex_after_finalize(404)

    assert result["outcome"] == "skip_no_matter"
    assert result["fired"] is False
    assert ctx["dispatch_calls"] == []


# --------------------------------------------------------------------------
# idempotency — INSERT-IF-NOT-EXISTS
# --------------------------------------------------------------------------


def test_dispatch_skips_when_already_dispatched(monkeypatch):
    """Re-run on R3 reflip / crash recovery → INSERT returns no row → skip."""
    with _patched(
        monkeypatch,
        fetchone_seq=[
            ("hagenauer-rg7",),  # SELECT primary_matter
            None,                # INSERT ... RETURNING (none — already exists)
        ],
        has_config=True,
    ) as ctx:
        result = step6_finalize.dispatch_cortex_after_finalize(101)

    assert result["outcome"] == "already_dispatched"
    assert result["fired"] is False
    assert ctx["dispatch_calls"] == []  # gate not re-invoked


# --------------------------------------------------------------------------
# never-raises
# --------------------------------------------------------------------------


def test_dispatch_swallows_db_exception(monkeypatch, caplog):
    """DB unavailable → log + return; do not propagate."""
    class _RaisingStore:
        @classmethod
        def _get_global_instance(cls):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "memory.store_back.SentinelStoreBack",
        _RaisingStore,
    )

    with caplog.at_level("ERROR"):
        result = step6_finalize.dispatch_cortex_after_finalize(1)

    assert result["outcome"] == "error"
    assert result["fired"] is False
    assert "db down" in result.get("error", "")


def test_dispatch_swallows_runner_exception(monkeypatch):
    """maybe_dispatch raising must not propagate; audit row still landed."""
    with _patched(
        monkeypatch,
        fetchone_seq=[("hagenauer-rg7",), (1,)],
        has_config=True,
    ) as ctx:
        def _kaboom(**kw):
            raise RuntimeError("cortex offline")

        monkeypatch.setattr(
            "triggers.cortex_pipeline.maybe_dispatch", _kaboom,
        )
        # Must not raise.
        result = step6_finalize.dispatch_cortex_after_finalize(101)

    # Outcome reflects intent (we tried to invoke); fired=False because
    # the runner raised.
    assert result["outcome"] == "invoked"
    assert result["fired"] is False
    # Audit row still committed before the runner call.
    assert ctx["conn"].committed == 1


# --------------------------------------------------------------------------
# audit row payload
# --------------------------------------------------------------------------


def test_dispatch_writes_canonical_action_type_and_payload(monkeypatch):
    with _patched(
        monkeypatch,
        fetchone_seq=[("lilienmatt",), (42,)],
        has_config=True,
    ) as ctx:
        step6_finalize.dispatch_cortex_after_finalize(7)

    # Find the INSERT call in the cursor's recorded executions.
    inserts = [
        e for e in ctx["cur"].executed
        if e[0].lstrip().startswith("INSERT INTO baker_actions")
    ]
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "cortex:dispatch:" in sql  # LIKE clause
    action_type, target_task_id, payload_json, source, success, dup_check = params
    assert action_type == "cortex:dispatch:invoked"
    assert target_task_id == "7"
    assert source == "step6_finalize_post_commit"
    assert success is True
    assert dup_check == "7"
    parsed = json.loads(payload_json)
    assert parsed == {
        "signal_id": 7,
        "primary_matter": "lilienmatt",
        "outcome": "invoked",
    }


# --------------------------------------------------------------------------
# source assertion
# --------------------------------------------------------------------------


def test_dispatch_helper_exists_in_step6_module():
    src = open("kbl/steps/step6_finalize.py").read()
    assert "def dispatch_cortex_after_finalize" in src
    assert "cortex:dispatch:invoked" in src
    assert "cortex:dispatch:skip_no_matter" in src
    assert "cortex:dispatch:skip_no_config" in src
