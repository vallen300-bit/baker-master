"""Ship gate for BRIEF_STALE_CYCLE_NUDGE_SENTINEL_1.

Covers the 6 brief-required scenarios. All hermetic — no live DB, no live
ClickUp. Mocks `ClickUpClient.create_task` and the SELECT/UPDATE flows on
SentinelStoreBack.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SELECT_COLS = [
    ("cycle_id",), ("matter_slug",), ("created_at",), ("days_stale",),
]


def _stale_row(
    cycle_id: str = "11111111-1111-1111-1111-111111111111",
    matter_slug: str = "ao",
    days_stale: int = 4,
) -> Tuple[Any, ...]:
    """Row tuple mirroring the SELECT projection in _fetch_stale_cycles."""
    return (cycle_id, matter_slug, None, days_stale)


def _make_store(select_rows: List[Tuple] = None, update_failures: set = None):
    """Build a MagicMock store with per-call _get_conn queueing.

    `select_rows` — rows the SELECT returns on the first _get_conn() call.
    `update_failures` — set of cycle_ids whose UPDATE should raise. The
    sentinel calls _get_conn() once for the SELECT then once per UPDATE.
    """
    store = MagicMock()
    update_failures = update_failures or set()
    update_call_count = {"i": 0}

    # SELECT conn
    select_cur = MagicMock()
    select_cur.fetchall.return_value = select_rows if select_rows is not None else []
    select_cur.description = _SELECT_COLS
    select_conn = MagicMock()
    select_conn.cursor.return_value = select_cur

    update_conns: List[MagicMock] = []
    update_cursors: List[MagicMock] = []
    for row in select_rows or []:
        cid = row[0]
        cur = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value = cur
        if cid in update_failures:
            cur.execute.side_effect = RuntimeError(f"UPDATE failed for {cid}")
        update_conns.append(conn)
        update_cursors.append(cur)

    call_queue = [select_conn] + update_conns

    def _next_conn():
        if call_queue:
            return call_queue.pop(0)
        c = MagicMock()
        c.cursor.return_value = MagicMock()
        return c

    store._get_conn.side_effect = _next_conn
    store._put_conn = MagicMock()
    store._select_cursor = select_cur
    store._update_cursors = update_cursors
    return store


def _run(store, clickup_client, monkeypatch):
    """Patch sentinel_health + the store/client lookups and invoke the entry point."""
    from triggers import stale_cycle_nudge_sentinel as mod

    fake_health = MagicMock()
    monkeypatch.setattr(mod, "logger", MagicMock())  # silence

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "clickup_client.ClickUpClient._get_global_instance",
        return_value=clickup_client,
    ), patch.dict(
        "sys.modules", {"triggers.sentinel_health": fake_health},
    ):
        return mod.run_stale_cycle_nudge_sentinel(), fake_health


# ---------------------------------------------------------------------------
# Test 1 — kill switch honored
# ---------------------------------------------------------------------------


def test_skipped_when_clickup_readonly(monkeypatch):
    monkeypatch.setenv("BAKER_CLICKUP_READONLY", "true")
    store = _make_store(select_rows=[_stale_row()])
    client = MagicMock()

    result, fake_health = _run(store, client, monkeypatch)

    assert result["skipped_readonly"] is True
    assert result["nudged"] == 0
    assert client.create_task.call_count == 0
    # Zero PG writes — neither SELECT nor UPDATE should have been issued.
    assert store._get_conn.call_count == 0
    # And no sentinel_health roundtrip — kill-switch is operator state.
    assert fake_health.report_success.call_count == 0
    assert fake_health.report_failure.call_count == 0


# ---------------------------------------------------------------------------
# Test 2 — no stale cycles, no work
# ---------------------------------------------------------------------------


def test_returns_zero_when_no_stale_cycles(monkeypatch):
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    store = _make_store(select_rows=[])
    client = MagicMock()

    result, fake_health = _run(store, client, monkeypatch)

    assert result["checked"] == 0
    assert result["nudged"] == 0
    assert result["skipped_readonly"] is False
    assert client.create_task.call_count == 0
    assert fake_health.report_success.call_count == 1


# ---------------------------------------------------------------------------
# Test 3 — one stale cycle past threshold gets nudged
# ---------------------------------------------------------------------------


def test_nudges_cycle_older_than_threshold(monkeypatch):
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    row = _stale_row(cycle_id="aaaaaaaa-1111-1111-1111-111111111111",
                     matter_slug="oskolkov", days_stale=4)
    store = _make_store(select_rows=[row])
    client = MagicMock()
    client.create_task.return_value = {"id": "ck-task-1"}

    result, fake_health = _run(store, client, monkeypatch)

    assert result["checked"] == 1
    assert result["nudged"] == 1
    assert result["errors"] == 0
    assert client.create_task.call_count == 1

    # ClickUp args: list_id is the Handoff Notes list, name includes matter
    # slug + 8-char id + age, tags include the matter slug.
    kwargs = client.create_task.call_args.kwargs
    assert kwargs["list_id"] == "901521426367"
    assert "oskolkov" in kwargs["name"]
    assert "aaaaaaaa" in kwargs["name"]
    assert "4d" in kwargs["name"]
    assert "oskolkov" in kwargs["tags"]
    assert "stale-cycle" in kwargs["tags"]

    # UPDATE was issued for the row's cycle_id.
    upd_cur = store._update_cursors[0]
    assert upd_cur.execute.call_count == 1
    sql, params = upd_cur.execute.call_args.args
    assert "UPDATE cortex_cycles" in sql
    assert "last_nudge_at" in sql
    assert params == ("aaaaaaaa-1111-1111-1111-111111111111",)


# ---------------------------------------------------------------------------
# Test 4 — recently-nudged cycles filtered by SQL
# ---------------------------------------------------------------------------


def test_skips_cycle_nudged_within_window(monkeypatch):
    """Anti-spam SQL filter excludes rows with last_nudge_at within 7d.

    Tested at the boundary: SELECT returns [] when the WHERE clause filters
    the candidate out. We verify the SQL carries the correct re-nudge clause.
    """
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    store = _make_store(select_rows=[])
    client = MagicMock()

    result, _ = _run(store, client, monkeypatch)

    assert result["checked"] == 0
    assert result["nudged"] == 0
    # Verify the SELECT clause carries the re-nudge predicate.
    sql_executed = store._select_cursor.execute.call_args.args[0]
    assert "last_nudge_at IS NULL" in sql_executed
    assert "INTERVAL '7 days'" in sql_executed
    assert "INTERVAL '3 days'" in sql_executed
    assert "LIMIT 10" in sql_executed


# ---------------------------------------------------------------------------
# Test 5 — re-nudge after window elapses
# ---------------------------------------------------------------------------


def test_renudges_cycle_after_window(monkeypatch):
    """SQL filter passes the row when last_nudge_at is older than 7d.

    Tested at the boundary: the SELECT returns the row (production WHERE clause
    is responsible for the time math). The sentinel must then re-nudge.
    """
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    row = _stale_row(cycle_id="cccccccc-3333-3333-3333-333333333333",
                     matter_slug="movie", days_stale=11)
    store = _make_store(select_rows=[row])
    client = MagicMock()
    client.create_task.return_value = {"id": "ck-task-2"}

    result, _ = _run(store, client, monkeypatch)

    assert result["nudged"] == 1
    assert client.create_task.call_count == 1


# ---------------------------------------------------------------------------
# Test 6 — one bad row doesn't block the others
# ---------------------------------------------------------------------------


def test_one_row_failure_does_not_block_others(monkeypatch):
    monkeypatch.delenv("BAKER_CLICKUP_READONLY", raising=False)
    row1 = _stale_row(cycle_id="11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                      matter_slug="ao", days_stale=5)
    row2 = _stale_row(cycle_id="22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                      matter_slug="hagenauer", days_stale=6)
    row3 = _stale_row(cycle_id="33333333-cccc-cccc-cccc-cccccccccccc",
                      matter_slug="movie", days_stale=7)
    store = _make_store(select_rows=[row1, row2, row3])
    client = MagicMock()

    def _ck_side_effect(**kwargs):
        # Fail only the middle one.
        if "hagenauer" in kwargs.get("name", ""):
            raise RuntimeError("simulated ClickUp 500")
        return {"id": "ok"}

    client.create_task.side_effect = _ck_side_effect

    result, _ = _run(store, client, monkeypatch)

    assert result["checked"] == 3
    assert result["nudged"] == 2
    assert result["errors"] == 1
    assert client.create_task.call_count == 3
