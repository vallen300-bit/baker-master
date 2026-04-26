"""Tests for AMEX_RECURRING_DEADLINE_1 — recurrence on deadlines.

Covers:
  * compute_next_due() — 4 recurrence types × edge cases (Feb / leap year / end-of-month).
  * _maybe_respawn_recurring() — happy path, idempotency, cap-rate + alert,
    null-recurrence skip, unknown-recurrence skip, missing-anchor skip,
    priority/severity propagation, chain root resolution.
  * Amendment H — 3 completion paths reference _maybe_respawn_recurring.
  * Auto-dismiss SQL excludes recurring rows (`AND recurrence IS NULL`).
  * dismiss_deadline UX for recurring (default keeps chain alive).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pytest

from orchestrator.deadline_manager import (
    RECURRENCE_VALUES,
    _maybe_respawn_recurring,
    compute_next_due,
)


# ---------------------------------------------------------------------------
# Fake psycopg2 conn/cursor — drives _maybe_respawn_recurring without Postgres.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.queries: list[tuple[str, object]] = []
        self.fetchone_queue: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        if not self.fetchone_queue:
            return None
        return self.fetchone_queue.pop(0)

    def fetchall(self):
        return []

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cur = cursor

    def cursor(self):
        return self._cur

    def commit(self):
        self._cur.commits += 1

    def rollback(self):
        self._cur.rollbacks += 1


def _row_for_deadline(
    *,
    id_: int = 1438,
    description: str = "Pay AmEx",
    priority: str = "high",
    source_type: str = "manual",
    source_snippet: str = "AmEx monthly",
    recurrence: str | None = "monthly",
    anchor: date | None = date(2026, 5, 3),
    count: int = 0,
    parent_deadline_id: int | None = None,
    severity: str = "firm",
    matter_slug: str | None = None,
):
    return (
        id_, description, priority, source_type, source_snippet,
        recurrence, anchor, count, parent_deadline_id, severity, matter_slug,
    )


# ---------------------------------------------------------------------------
# compute_next_due — happy paths + edge cases
# ---------------------------------------------------------------------------


def test_compute_next_due_monthly_normal():
    assert compute_next_due("monthly", date(2026, 4, 3)) == date(2026, 5, 3)


def test_compute_next_due_monthly_jan31_to_feb_clamps():
    """relativedelta clamps Jan 31 → Feb 28 in non-leap year."""
    assert compute_next_due("monthly", date(2026, 1, 31)) == date(2026, 2, 28)


def test_compute_next_due_monthly_feb29_leap_year():
    """relativedelta clamps Jan 31 → Feb 29 in leap year."""
    assert compute_next_due("monthly", date(2024, 1, 31)) == date(2024, 2, 29)


def test_compute_next_due_weekly():
    assert compute_next_due("weekly", date(2026, 4, 3)) == date(2026, 4, 10)


def test_compute_next_due_quarterly():
    assert compute_next_due("quarterly", date(2026, 4, 3)) == date(2026, 7, 3)


def test_compute_next_due_quarterly_anchor_30th_of_nov_to_feb():
    """Nov 30 + 3 months = Feb 28/29 — relativedelta clamps."""
    assert compute_next_due("quarterly", date(2026, 11, 30)) == date(2027, 2, 28)


def test_compute_next_due_annual():
    assert compute_next_due("annual", date(2026, 4, 3)) == date(2027, 4, 3)


def test_compute_next_due_annual_leap_year_feb29():
    """Feb 29 + 1 year = Feb 28 next non-leap year."""
    assert compute_next_due("annual", date(2024, 2, 29)) == date(2025, 2, 28)


def test_compute_next_due_unknown_recurrence_raises():
    with pytest.raises(ValueError, match="unknown recurrence"):
        compute_next_due("daily", date(2026, 4, 3))


def test_compute_next_due_accepts_datetime():
    """Convenience: datetime passed instead of date — uses the date portion."""
    dt = datetime(2026, 4, 3, 12, 30, tzinfo=timezone.utc)
    assert compute_next_due("monthly", dt) == date(2026, 5, 3)


def test_recurrence_values_constant_complete():
    """Constant exposes exactly the 4 supported types."""
    assert RECURRENCE_VALUES == {"monthly", "weekly", "quarterly", "annual"}


# ---------------------------------------------------------------------------
# _maybe_respawn_recurring — driven by fake conn
# ---------------------------------------------------------------------------


def test_respawn_inserts_child_with_correct_anchor_and_chain():
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(),                    # SELECT deadline
        None,                                   # idempotency: no existing child
        (0,),                                   # cap-rate: 0 recent
        (4711,),                                # INSERT RETURNING id
    ]
    new_id = _maybe_respawn_recurring(1438, conn=_FakeConn(cur))

    assert new_id == 4711

    insert_q = next(q for q in cur.queries if "INSERT INTO deadlines" in q[0])
    params = insert_q[1]
    # params order matches the INSERT statement:
    # description, due_date, source_type, source_id, source_snippet,
    # priority, severity, matter_slug, recurrence, next_anchor, count+1, root_id
    assert params[0] == "Pay AmEx"
    assert params[1] == datetime(2026, 6, 3, tzinfo=timezone.utc)
    assert params[5] == "high"
    assert params[6] == "firm"
    assert params[8] == "monthly"
    assert params[9] == date(2026, 6, 3)
    assert params[10] == 1
    assert params[11] == 1438


def test_respawn_idempotent_returns_existing_child():
    """Child with same root + anchor already exists → return existing id, no INSERT."""
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(),
        (9999,),  # existing child found
    ]
    new_id = _maybe_respawn_recurring(1438, conn=_FakeConn(cur))
    assert new_id == 9999
    assert not any("INSERT INTO deadlines" in q[0] for q in cur.queries)


def test_respawn_cap_rate_skips_and_alerts(monkeypatch):
    """Recent child created within 24h → log + Slack DM, return None."""
    alerts: list[tuple[int, int, str]] = []

    def _fake_alert(parent_id, root_id, recurrence):
        alerts.append((parent_id, root_id, recurrence))

    monkeypatch.setattr(
        "orchestrator.deadline_manager._alert_respawn_cap_hit",
        _fake_alert,
    )
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(),
        None,         # no idempotent child
        (1,),         # cap-rate: 1 recent → trip guard
    ]
    new_id = _maybe_respawn_recurring(1438, conn=_FakeConn(cur))
    assert new_id is None
    assert alerts == [(1438, 1438, "monthly")]
    assert not any("INSERT INTO deadlines" in q[0] for q in cur.queries)


def test_respawn_skips_when_recurrence_null():
    cur = _FakeCursor()
    cur.fetchone_queue = [_row_for_deadline(recurrence=None)]
    assert _maybe_respawn_recurring(1438, conn=_FakeConn(cur)) is None
    # Only the initial SELECT — no idempotency probe, no INSERT.
    assert len(cur.queries) == 1


def test_respawn_skips_unknown_recurrence_value():
    cur = _FakeCursor()
    cur.fetchone_queue = [_row_for_deadline(recurrence="biennially")]
    assert _maybe_respawn_recurring(1438, conn=_FakeConn(cur)) is None
    assert len(cur.queries) == 1


def test_respawn_skips_when_anchor_missing():
    cur = _FakeCursor()
    cur.fetchone_queue = [_row_for_deadline(anchor=None)]
    assert _maybe_respawn_recurring(1438, conn=_FakeConn(cur)) is None
    assert len(cur.queries) == 1


def test_respawn_uses_root_id_when_chain_already_exists():
    """parent_deadline_id != None → child links to root, not to immediate parent."""
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(id_=4712, parent_deadline_id=1438, count=2),
        None,
        (0,),
        (4713,),
    ]
    new_id = _maybe_respawn_recurring(4712, conn=_FakeConn(cur))
    assert new_id == 4713
    insert_q = next(q for q in cur.queries if "INSERT INTO deadlines" in q[0])
    params = insert_q[1]
    assert params[10] == 3      # count incremented from 2 → 3
    assert params[11] == 1438   # root, not the immediate parent 4712


def test_respawn_propagates_priority_and_severity():
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(priority="critical", severity="hard"),
        None,
        (0,),
        (5000,),
    ]
    _maybe_respawn_recurring(1438, conn=_FakeConn(cur))
    insert_q = next(q for q in cur.queries if "INSERT INTO deadlines" in q[0])
    params = insert_q[1]
    assert params[5] == "critical"
    assert params[6] == "hard"


def test_respawn_idempotency_query_uses_root_and_next_anchor():
    cur = _FakeCursor()
    cur.fetchone_queue = [
        _row_for_deadline(id_=4712, parent_deadline_id=1438, anchor=date(2026, 5, 3)),
        (4711,),  # existing
    ]
    _maybe_respawn_recurring(4712, conn=_FakeConn(cur))
    idem_q = cur.queries[1]
    assert "parent_deadline_id" in idem_q[0]
    assert "recurrence_anchor_date" in idem_q[0]
    assert idem_q[1] == (1438, date(2026, 6, 3))


# ---------------------------------------------------------------------------
# Amendment H — 3 completion paths must reference _maybe_respawn_recurring.
# ---------------------------------------------------------------------------


def test_amendment_h_three_paths_call_helper():
    """All 3 completion-path call sites must reference the respawn helper."""
    files = [
        REPO / "orchestrator" / "deadline_manager.py",
        REPO / "triggers" / "clickup_trigger.py",
        REPO / "models" / "deadlines.py",
    ]
    for path in files:
        assert "_maybe_respawn_recurring" in path.read_text(encoding="utf-8"), (
            f"Amendment H violation: {path.name} does not reference _maybe_respawn_recurring"
        )


# ---------------------------------------------------------------------------
# Auto-dismiss exclusions — `AND recurrence IS NULL` must guard both paths.
# ---------------------------------------------------------------------------


def test_auto_dismiss_overdue_sql_excludes_recurring():
    src = (REPO / "orchestrator" / "deadline_manager.py").read_text(encoding="utf-8")
    func_start = src.index("def _auto_dismiss_overdue_deadlines")
    func_end = src.index("\ndef ", func_start + 1)
    body = src[func_start:func_end]
    assert "recurrence IS NULL" in body, (
        "_auto_dismiss_overdue_deadlines must skip recurring rows"
    )


def test_auto_dismiss_soft_sql_excludes_recurring():
    src = (REPO / "orchestrator" / "deadline_manager.py").read_text(encoding="utf-8")
    func_start = src.index("def _auto_dismiss_soft_deadlines")
    func_end = src.index("\ndef ", func_start + 1)
    body = src[func_start:func_end]
    assert "recurrence IS NULL" in body, (
        "_auto_dismiss_soft_deadlines must skip recurring rows"
    )


# ---------------------------------------------------------------------------
# dismiss_deadline UX — recurring default keeps chain alive; explicit stop halts.
# ---------------------------------------------------------------------------


def test_dismiss_recurring_default_returns_keep_chain_message(monkeypatch):
    """Default scope='instance' on a recurring row → chain stays active in message."""
    from orchestrator import deadline_manager as dm

    monkeypatch.setattr(
        dm, "_find_deadline_by_text",
        lambda s: {
            "id": 1438, "description": "Pay AmEx",
            "due_date": datetime(2026, 5, 3, tzinfo=timezone.utc),
            "recurrence": "monthly", "parent_deadline_id": None,
        },
    )
    monkeypatch.setattr(
        "models.deadlines.update_deadline",
        lambda *a, **kw: True,
    )
    msg = dm.dismiss_deadline("amex")
    assert "Recurrence kept active" in msg
    assert "halt" in msg.lower()


def test_dismiss_recurring_with_scope_recurrence_halts_chain(monkeypatch):
    from orchestrator import deadline_manager as dm

    halted: list[int] = []
    monkeypatch.setattr(
        dm, "_find_deadline_by_text",
        lambda s: {
            "id": 1438, "description": "Pay AmEx",
            "due_date": datetime(2026, 5, 3, tzinfo=timezone.utc),
            "recurrence": "monthly", "parent_deadline_id": None,
        },
    )
    monkeypatch.setattr(
        "models.deadlines.update_deadline",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        dm, "_halt_recurrence_chain",
        lambda root_id: halted.append(root_id) or True,
    )
    msg = dm.dismiss_deadline("amex", scope="recurrence")
    assert halted == [1438]
    assert "Recurrence stopped" in msg


def test_dismiss_non_recurring_unchanged_behavior(monkeypatch):
    """Non-recurring deadline → no chain-related text in message."""
    from orchestrator import deadline_manager as dm

    monkeypatch.setattr(
        dm, "_find_deadline_by_text",
        lambda s: {
            "id": 99, "description": "One-shot task",
            "due_date": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "recurrence": None,
        },
    )
    monkeypatch.setattr(
        "models.deadlines.update_deadline",
        lambda *a, **kw: True,
    )
    msg = dm.dismiss_deadline("one-shot")
    assert "Recurrence" not in msg
    assert "Deadline dismissed" in msg
