"""Ship gate for BRIEF_CORTEX_ARCHIVE_FAILURE_ALERTING_1.

Covers the 6 brief-required scenarios plus 4 unit tests on helpers:

  Brief scenarios (entry-point coverage):
    1. happy path no-stuck — empty result set, no Slack post
    2. one stuck cycle in `proposed` past 15min — alert posted + dedup row
    3. two stuck cycles — two alerts, two dedup rows
    4. already-alerted cycle — NO duplicate alert (dedup honored)
    5. one `archive_failed` cycle — alert with action_type='cortex_alert_archive_failed'
    6. mixed: one stuck + one archive_failed + one already-alerted — exactly 2 alerts

  Helper unit coverage:
    7. _format_alert_text builds well-formed message for stuck mode
    8. _format_alert_text handles archive_failed mode framing
    9. _record_alert returns True on new INSERT, False on dedup
   10. _detect builds correct SQL with status filter + dedup NOT IN

All tests are hermetic — no live DB, no Slack network calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store():
    """Returns a MagicMock store whose _get_conn yields a fresh per-call mock conn.

    Each _get_conn() call returns its own (conn, cursor) pair so different code
    paths (detector vs record_alert) don't share cursor state. Caller can drive
    per-call behavior via _set_next_conn(...).
    """
    store = MagicMock()
    store._conn_queue = []  # FIFO of preconfigured (conn, cursor) tuples

    def _next_conn():
        if store._conn_queue:
            conn, _cur = store._conn_queue.pop(0)
            return conn
        # default: a fresh empty cursor
        cur = MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = None
        cur.description = []
        conn = MagicMock()
        conn.cursor.return_value = cur
        return conn

    store._get_conn.side_effect = _next_conn
    return store


def _push_conn(store, *, fetchall=None, fetchone=None, description=None):
    """Pre-queue a (conn, cursor) tuple with the given fetch behavior."""
    cur = MagicMock()
    cur.fetchall.return_value = fetchall if fetchall is not None else []
    cur.fetchone.return_value = fetchone
    cur.description = description if description is not None else _DETECT_COLS
    conn = MagicMock()
    conn.cursor.return_value = cur
    store._conn_queue.append((conn, cur))
    return conn, cur


# Column shape returned by the SELECT in _detect (see sentinel module)
_DETECT_COLS = [
    ("cycle_id",), ("matter_slug",), ("status",),
    ("started_at",), ("current_phase",), ("age_seconds",),
]


def _stuck_row(cycle_id="11111111-1111-1111-1111-111111111111",
               matter_slug="ao", status="proposed", phase="propose",
               age_seconds=1200):
    """Row tuple mirroring the SELECT projection in _detect."""
    return (cycle_id, matter_slug, status,
            datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            phase, age_seconds)


# ---------------------------------------------------------------------------
# Scenario 1 — happy path no-stuck
# ---------------------------------------------------------------------------


def test_happy_path_no_stuck_no_alerts():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()
    # Two detector queries, both return []
    _push_conn(store, fetchall=[])  # Detector A
    _push_conn(store, fetchall=[])  # Detector B

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel"
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["stuck_found"] == 0
    assert result["archive_failed_found"] == 0
    assert result["alerts_posted"] == 0
    assert result["alerts_deduped"] == 0
    assert result["errors"] == 0
    assert not mock_slack.called


# ---------------------------------------------------------------------------
# Scenario 2 — one stuck cycle, alert posted + dedup row written
# ---------------------------------------------------------------------------


def test_one_stuck_cycle_emits_alert_and_dedup():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()
    row = _stuck_row()

    # Detector A returns 1 row, Detector B returns 0
    _push_conn(store, fetchall=[row])           # Detector A
    _push_conn(store, fetchone=(42,))            # _record_alert — INSERT writes
    _push_conn(store, fetchall=[])               # Detector B

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["stuck_found"] == 1
    assert result["alerts_posted"] == 1
    assert result["alerts_deduped"] == 0
    assert mock_slack.call_count == 1
    # Slack called with Director DM channel + message containing cycle_id
    call_args = mock_slack.call_args
    assert call_args[0][0] == mod.DIRECTOR_DM_CHANNEL
    assert "11111111" in call_args[0][1]


# ---------------------------------------------------------------------------
# Scenario 3 — two stuck cycles, two alerts, two dedup rows
# ---------------------------------------------------------------------------


def test_two_stuck_cycles_two_alerts():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()
    row1 = _stuck_row(cycle_id="22222222-2222-2222-2222-222222222222")
    row2 = _stuck_row(cycle_id="33333333-3333-3333-3333-333333333333", status="in_flight")

    _push_conn(store, fetchall=[row1, row2])    # Detector A
    _push_conn(store, fetchone=(101,))           # record_alert row1 → new
    _push_conn(store, fetchone=(102,))           # record_alert row2 → new
    _push_conn(store, fetchall=[])               # Detector B

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["stuck_found"] == 2
    assert result["alerts_posted"] == 2
    assert result["alerts_deduped"] == 0
    assert mock_slack.call_count == 2


# ---------------------------------------------------------------------------
# Scenario 4 — already-alerted cycle: dedup honored, no Slack
# ---------------------------------------------------------------------------


def test_already_alerted_dedup_honored():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()
    row = _stuck_row()

    _push_conn(store, fetchall=[row])           # Detector A returns the row
    _push_conn(store, fetchone=None)             # _record_alert: INSERT wrote 0 rows
    _push_conn(store, fetchall=[])               # Detector B

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel"
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["stuck_found"] == 1
    assert result["alerts_posted"] == 0
    assert result["alerts_deduped"] == 1
    assert not mock_slack.called


# ---------------------------------------------------------------------------
# Scenario 5 — archive_failed cycle, distinct action_type used
# ---------------------------------------------------------------------------


def test_archive_failed_cycle_emits_alert_with_correct_action_type():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()
    row = _stuck_row(
        cycle_id="44444444-4444-4444-4444-444444444444",
        status="archive_failed",
        phase="archive",
    )

    _push_conn(store, fetchall=[])               # Detector A
    _push_conn(store, fetchall=[row])           # Detector B
    record_alert_conn, record_alert_cur = _push_conn(store, fetchone=(201,))  # _record_alert: new

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["archive_failed_found"] == 1
    assert result["alerts_posted"] == 1
    # Slack message should reflect archive_failed framing
    msg = mock_slack.call_args[0][1]
    assert "archive failure" in msg.lower()
    # Verify INSERT used the archive_failed action_type
    insert_call = record_alert_cur.execute.call_args
    insert_params = insert_call[0][1]
    assert mod.ACTION_TYPE_ARCHIVE_FAILED in insert_params


# ---------------------------------------------------------------------------
# Scenario 6 — mixed: 1 stuck-new + 1 archive_failed-new + 1 stuck-deduped → 2 alerts
# ---------------------------------------------------------------------------


def test_mixed_one_stuck_one_archive_one_deduped():
    from triggers import cortex_stuck_cycle_sentinel as mod
    store = _make_store()

    row_stuck_new = _stuck_row(cycle_id="55555555-5555-5555-5555-555555555555")
    row_stuck_dup = _stuck_row(cycle_id="66666666-6666-6666-6666-666666666666")
    row_archive = _stuck_row(
        cycle_id="77777777-7777-7777-7777-777777777777",
        status="archive_failed",
        phase="archive",
    )

    _push_conn(store, fetchall=[row_stuck_new, row_stuck_dup])  # Detector A returns BOTH
    _push_conn(store, fetchone=(301,))                          # row_stuck_new → INSERTed
    _push_conn(store, fetchone=None)                             # row_stuck_dup → deduped
    _push_conn(store, fetchall=[row_archive])                   # Detector B
    _push_conn(store, fetchone=(302,))                           # row_archive → INSERTed

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = mod.run_cortex_stuck_cycle_sentinel()

    assert result["stuck_found"] == 2
    assert result["archive_failed_found"] == 1
    assert result["alerts_posted"] == 2
    assert result["alerts_deduped"] == 1
    assert mock_slack.call_count == 2


# ---------------------------------------------------------------------------
# Helper-level unit tests
# ---------------------------------------------------------------------------


def test_format_alert_text_stuck_mode():
    from triggers.cortex_stuck_cycle_sentinel import _format_alert_text
    row = {
        "cycle_id": "abc-123",
        "matter_slug": "ao",
        "status": "proposed",
        "current_phase": "propose",
        "age_seconds": 1200,
    }
    text = _format_alert_text(row, "stuck")
    assert "Cortex stuck cycle" in text
    assert "abc-123" in text
    assert "ao" in text
    assert "proposed" in text
    assert "20.0 min" in text  # 1200/60


def test_format_alert_text_archive_failed_mode():
    from triggers.cortex_stuck_cycle_sentinel import _format_alert_text
    row = {
        "cycle_id": "def-456",
        "matter_slug": "movie",
        "status": "archive_failed",
        "current_phase": "archive",
        "age_seconds": 5,
    }
    text = _format_alert_text(row, "archive_failed")
    assert "archive failure" in text.lower()
    assert "def-456" in text
    assert "Phase 6" in text


def test_record_alert_returns_true_on_insert_false_on_dedup():
    """_record_alert should reflect whether the INSERT wrote a row."""
    from triggers.cortex_stuck_cycle_sentinel import _record_alert
    store_new = _make_store()
    _push_conn(store_new, fetchone=(999,))
    assert _record_alert(store_new, "abc", "ao", "cortex_alert_stuck") is True

    store_dup = _make_store()
    _push_conn(store_dup, fetchone=None)
    assert _record_alert(store_dup, "abc", "ao", "cortex_alert_stuck") is False


def test_detect_query_filters_by_status_and_excludes_already_alerted():
    """Detector SQL must include status filter, threshold predicate, and
    NOT IN dedup against the matching action_type."""
    from triggers.cortex_stuck_cycle_sentinel import _detect_stuck_cycles, ACTION_TYPE_STUCK
    store = _make_store()
    conn, cur = _push_conn(store, fetchall=[])
    _detect_stuck_cycles(store)

    sql = cur.execute.call_args[0][0]
    params = cur.execute.call_args[0][1]
    assert "cortex_cycles" in sql
    assert "status = ANY(%s)" in sql
    assert "started_at < NOW() - INTERVAL '15 minutes'" in sql
    assert "cycle_id::text NOT IN" in sql
    assert "target_task_id" in sql
    # Status list passed as first param; action_type bound at the end
    assert "in_flight" in params[0]
    assert "awaiting_reason" in params[0]
    assert "proposed" in params[0]
    # tier_b_pending is explicitly EXCLUDED in V1
    assert "tier_b_pending" not in params[0]
    assert params[-1] == ACTION_TYPE_STUCK
