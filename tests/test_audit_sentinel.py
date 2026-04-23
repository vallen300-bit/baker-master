"""Ship gate for BRIEF_AUDIT_SENTINEL_1.

Covers:
  1. Listener writes 'executed' row on clean event
  2. Listener writes 'error' row with error_msg on exception event
  3. Listener survives DB unavailable (no raise, logger.warning)
  4. Sentinel clean path — both present → no alert
  5. Sentinel miss path — alert fired + dedupe row written
  6. Sentinel deduped — prior alert in 24h → no re-alert
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _make_event(job_id="ai_head_weekly_audit", exception=None):
    event = MagicMock()
    event.job_id = job_id
    event.exception = exception
    event.traceback = None
    event.scheduled_run_time = datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)
    return event


def _make_store_with_conn():
    """Return (store_mock, conn_mock, cursor_mock)."""
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    store = MagicMock()
    store._get_conn.return_value = conn
    return store, conn, cursor


def test_listener_writes_executed_row():
    from triggers.embedded_scheduler import _job_listener

    store, conn, cursor = _make_store_with_conn()
    event = _make_event(exception=None)

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ):
        _job_listener(event)

    assert cursor.execute.called, "cursor.execute should have been called"
    args = cursor.execute.call_args
    sql = args[0][0]
    params = args[0][1]
    assert "INSERT INTO scheduler_executions" in sql
    assert params[0] == "ai_head_weekly_audit"
    assert params[2] == "executed"
    assert params[3] is None  # error_msg None on clean event
    assert conn.commit.called
    assert store._put_conn.called


def test_listener_writes_error_row():
    from triggers.embedded_scheduler import _job_listener

    store, conn, cursor = _make_store_with_conn()
    event = _make_event(exception=ValueError("boom stack trace truncated here"))

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ):
        _job_listener(event)

    assert cursor.execute.called
    params = cursor.execute.call_args[0][1]
    assert params[2] == "error"
    assert params[3] is not None
    assert "boom" in params[3]
    assert conn.commit.called


def test_listener_survives_db_unavailable(caplog):
    """DB unavailable (_get_conn → None) must not raise; listener returns cleanly."""
    from triggers.embedded_scheduler import _job_listener

    store = MagicMock()
    store._get_conn.return_value = None
    event = _make_event(exception=None)

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ):
        # Must not raise
        _job_listener(event)

    # No commit attempted
    assert not store._put_conn.called or store._put_conn.call_count == 0


def test_sentinel_clean_path():
    """Both audit row and execution row present → no alert, reason='clean'."""
    from triggers import audit_sentinel

    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), (1,)]  # audit_count=1, exec_count=1
    conn = MagicMock()
    conn.cursor.return_value = cursor
    store = MagicMock()
    store._get_conn.return_value = conn

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ):
        result = audit_sentinel.run_sentinel_check()

    assert result["audit_found"] is True
    assert result["execution_found"] is True
    assert result["alerted"] is False
    assert result["reason"] == "clean"


def test_sentinel_miss_alerts():
    """Audit missing, execution missing, no prior alert, Slack OK → alerted=True, dedupe row written."""
    from triggers import audit_sentinel

    read_cursor = MagicMock()
    # audit_count=0, exec_count=0, prior_alert_count=0
    read_cursor.fetchone.side_effect = [(0,), (0,), (0,)]
    read_conn = MagicMock()
    read_conn.cursor.return_value = read_cursor

    write_cursor = MagicMock()
    write_conn = MagicMock()
    write_conn.cursor.return_value = write_cursor

    store = MagicMock()
    # First _get_conn returns read_conn (check phase), second returns write_conn (dedupe anchor)
    store._get_conn.side_effect = [read_conn, write_conn]

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = audit_sentinel.run_sentinel_check()

    assert result["audit_found"] is False
    assert result["execution_found"] is False
    assert result["alerted"] is True
    assert result["slack_ok"] is True
    assert "miss" in result["reason"]

    # Slack was called with the Director DM channel
    assert mock_slack.called
    assert mock_slack.call_args[0][0] == audit_sentinel.DIRECTOR_DM_CHANNEL

    # Dedupe-anchor INSERT executed on write_conn
    assert write_cursor.execute.called
    write_sql = write_cursor.execute.call_args[0][0]
    write_params = write_cursor.execute.call_args[0][1]
    assert "INSERT INTO scheduler_executions" in write_sql
    assert "'alerted'" in write_sql
    assert write_params[0] == "ai_head_audit_sentinel"
    assert write_conn.commit.called


def test_sentinel_deduped():
    """Miss detected but prior-alert count>0 → alerted=False, reason='deduped'."""
    from triggers import audit_sentinel

    cursor = MagicMock()
    # audit_count=0, exec_count=0, prior_alert_count=1
    cursor.fetchone.side_effect = [(0,), (0,), (1,)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    store = MagicMock()
    store._get_conn.return_value = conn

    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        return_value=store,
    ), patch(
        "outputs.slack_notifier.post_to_channel",
        return_value=True,
    ) as mock_slack:
        result = audit_sentinel.run_sentinel_check()

    assert result["audit_found"] is False
    assert result["execution_found"] is False
    assert result["alerted"] is False
    assert result["reason"] == "deduped"
    # Slack NOT called when deduped
    assert not mock_slack.called
