"""PLAUD_TRANSCRIPT_BY_MATTER_1 — storage-layer tests for the
``store_meeting_transcript`` auto-assign behavior.

Five cases per the brief:
  T1. Auto-assigns matter_slug when classifier matches + normalize resolves.
  T2. Explicit matter_slug short-circuits the classifier (no call).
  T3. Classifier failure is non-fatal — store still returns True.
  T4. ON CONFLICT path preserves an existing matter_slug via COALESCE.
  T5. normalize() returning None on a classifier hit logs a WARNING.

DB and classifier are monkeypatched; no live PG required.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Fake DB primitives — record SQL + params so tests can assert behavior
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        self.statements.append((sql, tuple(params or ())))

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _new_store_with_fake_conn(monkeypatch) -> tuple:
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack.__new__(SentinelStoreBack)
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(store, "_get_conn", lambda: conn, raising=False)
    monkeypatch.setattr(store, "_put_conn", lambda c: None, raising=False)
    return store, conn, cur


def _insert_stmt_params(cur: _FakeCursor) -> Optional[tuple]:
    for sql, params in cur.statements:
        if "INSERT INTO meeting_transcripts" in sql:
            return params
    return None


# ---------------------------------------------------------------------------
# T1 — auto-assigns when classifier matches + normalize resolves
# ---------------------------------------------------------------------------


def test_auto_assigns_matter_slug_when_classifier_matches(monkeypatch):
    store, conn, cur = _new_store_with_fake_conn(monkeypatch)

    monkeypatch.setattr(
        "orchestrator.pipeline._match_matter_slug",
        lambda title, body, store_arg: "Hagenauer RG7",
    )
    monkeypatch.setattr("kbl.slug_registry.normalize", lambda raw: "hagenauer-rg7")

    ok = store.store_meeting_transcript(
        transcript_id="plaud_abc",
        title="Hagenauer settlement call",
        full_transcript="Detail about RG7 dispute.",
    )

    assert ok is True
    params = _insert_stmt_params(cur)
    assert params is not None
    # INSERT param order: id, title, meeting_date, duration, organizer,
    #                     participants, summary, full_transcript, source, matter_slug
    assert params[0] == "plaud_abc"
    assert params[-1] == "hagenauer-rg7"
    assert conn.committed is True


# ---------------------------------------------------------------------------
# T2 — explicit matter_slug short-circuits the classifier
# ---------------------------------------------------------------------------


def test_preserves_explicit_matter_slug(monkeypatch):
    store, conn, cur = _new_store_with_fake_conn(monkeypatch)

    classifier_invocations: list = []

    def _spy(title, body, store_arg):
        classifier_invocations.append((title, body))
        return "Should-Not-Reach"

    monkeypatch.setattr("orchestrator.pipeline._match_matter_slug", _spy)

    ok = store.store_meeting_transcript(
        transcript_id="fireflies_explicit",
        title="explicit-slug meeting",
        matter_slug="hagenauer-rg7",
    )

    assert ok is True
    assert classifier_invocations == []  # short-circuited
    params = _insert_stmt_params(cur)
    assert params is not None
    assert params[-1] == "hagenauer-rg7"


# ---------------------------------------------------------------------------
# T3 — classifier failure non-fatal — store still returns True
# ---------------------------------------------------------------------------


def test_classifier_failure_is_non_fatal(monkeypatch):
    store, conn, cur = _new_store_with_fake_conn(monkeypatch)

    def _boom(title, body, store_arg):
        raise RuntimeError("simulated matter_registry outage")

    monkeypatch.setattr("orchestrator.pipeline._match_matter_slug", _boom)

    ok = store.store_meeting_transcript(
        transcript_id="plaud_fail",
        title="Some title",
        full_transcript="body",
    )

    assert ok is True
    params = _insert_stmt_params(cur)
    assert params is not None
    assert params[-1] is None  # classifier raised → matter_slug stays None


# ---------------------------------------------------------------------------
# T4 — ON CONFLICT path uses COALESCE to preserve existing slug
# ---------------------------------------------------------------------------


def test_on_conflict_preserves_existing_matter_slug_via_coalesce(monkeypatch):
    """We don't run a live DB; verify the SQL contains the COALESCE clause
    that preserves an existing slug on re-ingest when classifier returns None.
    """
    store, conn, cur = _new_store_with_fake_conn(monkeypatch)

    monkeypatch.setattr(
        "orchestrator.pipeline._match_matter_slug",
        lambda title, body, store_arg: None,
    )
    # normalize should not even be called when classifier returns None
    monkeypatch.setattr(
        "kbl.slug_registry.normalize",
        lambda raw: pytest.fail("normalize called on None classifier result"),
    )

    ok = store.store_meeting_transcript(
        transcript_id="plaud_reingest",
        title="Some unrelated title",
        full_transcript="body",
    )

    assert ok is True
    # Look at the INSERT SQL for the COALESCE preservation clause
    insert_sql = None
    for sql, _params in cur.statements:
        if "INSERT INTO meeting_transcripts" in sql:
            insert_sql = sql
            break
    assert insert_sql is not None
    assert "COALESCE(EXCLUDED.matter_slug, meeting_transcripts.matter_slug)" in insert_sql


# ---------------------------------------------------------------------------
# T5 — normalize() returning None on a classifier hit logs WARNING
# ---------------------------------------------------------------------------


def test_normalize_returning_none_logs_warning(monkeypatch, caplog):
    store, conn, cur = _new_store_with_fake_conn(monkeypatch)

    monkeypatch.setattr(
        "orchestrator.pipeline._match_matter_slug",
        lambda title, body, store_arg: "Phantom RG",
    )
    monkeypatch.setattr("kbl.slug_registry.normalize", lambda raw: None)

    with caplog.at_level(logging.WARNING, logger="memory.store_back"):
        ok = store.store_meeting_transcript(
            transcript_id="plaud_phantom",
            title="Phantom RG sync",
            full_transcript="body",
        )

    assert ok is True
    params = _insert_stmt_params(cur)
    assert params is not None
    assert params[-1] is None
    assert any(
        "slug_registry.normalize() returned" in r.message
        for r in caplog.records
        if r.levelname == "WARNING"
    )
