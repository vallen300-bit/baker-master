from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kbl import router_second_look as rsl
from kbl.steps.step4_classify import ClassifyDecision, classify


MIGRATION = Path("migrations/20260628b_router_second_look_and_waiting_room.sql")


def _conn(fetchone=(1, True), fetchall=None) -> MagicMock:
    conn = MagicMock()
    calls = []

    def _cursor():
        cur = MagicMock()
        cur.fetchone.return_value = fetchone
        cur.fetchall.return_value = fetchall or []
        cur.description = [
            ("id",), ("signal_id",), ("trigger_step",), ("reason_code",),
            ("primary_matter",), ("triage_score",), ("triage_confidence",),
            ("status",), ("decided_by",), ("decision_note",), ("payload",),
            ("dedup_key",), ("created_at",), ("updated_at",),
        ]

        def _execute(sql, params=None):
            calls.append((sql, params))

        cur.execute.side_effect = _execute
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = calls
    return conn


def test_migration_shape_parse() -> None:
    sql = MIGRATION.read_text()
    assert "-- == migrate:up ==" in sql
    assert "CREATE TABLE IF NOT EXISTS router_second_look_items" in sql
    assert "triage_confidence NUMERIC" in sql
    assert "dedup_key TEXT UNIQUE" in sql
    for reason in ("low_confidence", "scope_gate_skip", "important_source", "deadline_shape", "manual"):
        assert reason in sql


def test_record_item_disabled_env_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KBL_ROUTER_SECOND_LOOK_ENABLED", raising=False)
    conn = _conn()
    out = rsl.record_item(
        conn,
        signal_id=1,
        trigger_step="step1_triage",
        reason_code="low_confidence",
    )
    assert out["skipped"] is True
    assert conn._calls == []


def test_record_item_dedup_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_ROUTER_SECOND_LOOK_ENABLED", "true")
    conn = _conn(fetchone=(7, False))
    out = rsl.record_item(
        conn,
        signal_id=10,
        trigger_step="step1_triage",
        reason_code="low_confidence",
        primary_matter="movie",
        triage_score=70,
        triage_confidence=0.4,
        dedup_key="same",
    )
    assert out["ok"] is True
    assert out["inserted"] is False
    assert "ON CONFLICT (dedup_key) DO UPDATE" in conn._calls[0][0]


def test_enabled_low_confidence_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_ROUTER_SECOND_LOOK_ENABLED", "true")
    monkeypatch.setenv("KBL_TRIAGE_CONFIDENCE_FLOOR", "0.65")
    conn = _conn(fetchone=(3, True))
    out = rsl.record_low_confidence_if_needed(
        conn,
        signal_id=5,
        primary_matter="ao",
        triage_score=80,
        triage_confidence=0.31,
    )
    assert out["inserted"] is True
    assert conn._calls[0][1][2] == "low_confidence"


def test_isolated_record_rolls_back_failed_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_ROUTER_SECOND_LOOK_ENABLED", "true")
    conn = _conn()

    def _execute(sql, params=None):
        conn._calls.append((sql, params))
        if "INSERT INTO router_second_look_items" in sql:
            raise RuntimeError("insert failed")

    def _cursor():
        cur = MagicMock()
        cur.execute.side_effect = _execute
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor

    with pytest.raises(RuntimeError, match="insert failed"):
        rsl.record_item_isolated(
            conn,
            signal_id=1,
            trigger_step="step4_classify",
            reason_code="scope_gate_skip",
        )

    sqls = [sql for sql, _ in conn._calls]
    assert "SAVEPOINT router_second_look_audit_sp" in sqls
    assert "ROLLBACK TO SAVEPOINT router_second_look_audit_sp" in sqls
    assert "RELEASE SAVEPOINT router_second_look_audit_sp" in sqls


def test_step4_scope_gate_skip_records_second_look(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_ROUTER_SECOND_LOOK_ENABLED", "true")

    from tests.test_step4_classify import _classify_conn

    conn = _classify_conn(triage_score=80, triage_confidence=0.7, primary_matter="unknown")
    with patch("kbl.steps.step4_classify._load_allowed_scope", return_value=frozenset({"movie"})):
        result = classify(signal_id=44, conn=conn)

    assert result is ClassifyDecision.SKIP_INBOX
    inserts = [c for c in conn._calls if "router_second_look_items" in c[0]]
    assert len(inserts) == 1
    assert inserts[0][1][2] == "scope_gate_skip"


def test_step4_audit_failure_does_not_block_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_ROUTER_SECOND_LOOK_ENABLED", "true")

    from tests.test_step4_classify import _classify_conn

    conn = _classify_conn(triage_score=80, triage_confidence=0.7, primary_matter="unknown")
    with patch("kbl.steps.step4_classify._load_allowed_scope", return_value=frozenset({"movie"})), \
         patch("kbl.router_second_look.record_item", side_effect=RuntimeError("insert failed")):
        result = classify(signal_id=45, conn=conn)

    assert result is ClassifyDecision.SKIP_INBOX
    sqls = [sql for sql, _ in conn._calls]
    assert "ROLLBACK TO SAVEPOINT router_second_look_audit_sp" in sqls
    assert any(
        "step_5_decision" in sql.lower()
        and params == ("skip_inbox", False, "awaiting_opus", 45)
        for sql, params in conn._calls
    )
