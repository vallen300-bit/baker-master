from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator import waiting_room as wr


MIGRATION = Path("migrations/20260628b_router_second_look_and_waiting_room.sql")


def _conn(fetchone=(1, True), fetchall=None) -> MagicMock:
    conn = MagicMock()
    calls = []

    def _cursor():
        cur = MagicMock()
        cur.fetchone.return_value = fetchone
        cur.fetchall.return_value = fetchall or []

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
    assert "CREATE TABLE IF NOT EXISTS waiting_room_items" in sql
    assert "flight_type TEXT NOT NULL" in sql
    assert "dedup_key TEXT UNIQUE" in sql
    for status in ("waiting", "ready", "nudged", "released", "cancelled"):
        assert status in sql


def test_upsert_idempotency() -> None:
    conn = _conn(fetchone=(9, False))
    out = wr.upsert_item(
        conn,
        flight_type="chartered",
        item_type="brief",
        item_ref="BRIEF_X",
        owner_slug="lead",
        reason_code="awaiting_director",
        dedup_key="same",
    )
    assert out["inserted"] is False
    assert "ON CONFLICT (dedup_key) DO UPDATE" in conn._calls[0][0]


def test_flight_type_validation() -> None:
    with pytest.raises(ValueError, match="invalid flight_type"):
        wr.upsert_item(_conn(), flight_type="cargo", item_type="x", item_ref="1")


def test_status_transitions() -> None:
    conn = _conn(fetchone=(12, "released"))
    out = wr.set_status(conn, item_id=12, status="released")
    assert out == {"ok": True, "id": 12, "status": "released"}
    with pytest.raises(ValueError, match="invalid status"):
        wr.set_status(conn, item_id=12, status="done")


def test_cooldown_nudge_eligibility() -> None:
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    assert wr.is_nudge_eligible(
        status="waiting",
        ready_after=now - timedelta(minutes=1),
        last_nudge_at=None,
        now=now,
    )
    assert not wr.is_nudge_eligible(
        status="waiting",
        ready_after=now + timedelta(minutes=1),
        last_nudge_at=None,
        now=now,
    )
    assert not wr.is_nudge_eligible(
        status="nudged",
        ready_after=None,
        last_nudge_at=now - timedelta(minutes=10),
        now=now,
        cooldown_seconds=3600,
    )


def test_disabled_scheduler_nudge_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAITING_ROOM_NUDGE_ENABLED", raising=False)
    conn = _conn()
    assert wr.run_nudge_tick(conn)["skipped"] is True
    assert conn._calls == []
    scheduler = MagicMock()
    assert wr.register_waiting_room_workers(scheduler) == []
    scheduler.add_job.assert_not_called()
