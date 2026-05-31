"""Ship gate for JOB_LISTENER_HARDEN_1.

4 cases per brief Tests section:
  1.  Silent skip logs + counts (no retry success).
  2.  Retry succeeds on transient None — no drop recorded.
  3.  Retry exhausts on persistent None — drop recorded.
  4.  Alert body includes drop-hint when count > 0.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from triggers import embedded_scheduler as es
from triggers import scheduler_liveness_sentinel as sls


# ---------- Fixtures --------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_drop_counter():
    """Clear module-level drop counter between tests (process-local leak guard)."""
    es._listener_drop_count.clear()
    yield
    es._listener_drop_count.clear()


def _make_event(job_id: str = "test_job", with_exception: bool = False):
    """Build a synthetic apscheduler JobExecutionEvent stub with the attrs
    _job_listener reads: job_id, exception, traceback, scheduled_run_time.
    """
    event = MagicMock()
    event.job_id = job_id
    event.exception = Exception("boom") if with_exception else None
    event.traceback = None
    event.scheduled_run_time = datetime.now(timezone.utc)
    return event


def _store_with_conn_sequence(conn_sequence):
    """Build a mock SentinelStoreBack whose _get_conn() returns each item
    from conn_sequence on successive calls.
    """
    store = MagicMock()
    store._get_conn.side_effect = list(conn_sequence)
    store._put_conn = MagicMock()
    return store


def _conn_stub_with_cursor():
    """Real-enough conn stub that supports the INSERT path."""
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.close = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    return conn, cur


# ---------- Tests -----------------------------------------------------------

def test_silent_skip_logs_and_counts(caplog):
    """1: persistent conn=None on both calls -> drop recorded + WARNING logged.
    Fired twice -> count == 2 + 2 warnings.
    """
    store = _store_with_conn_sequence([None, None, None, None])

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        with caplog.at_level(logging.WARNING, logger="sentinel.embedded_scheduler"):
            es._job_listener(_make_event("test_job"))
            es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {"test_job": 2}
    skip_records = [r for r in caplog.records if "JOB_LISTENER_SILENT_SKIP" in r.message]
    assert len(skip_records) == 2
    assert all("job_id=test_job" in r.message for r in skip_records)
    # Retry was exercised: 2 calls per fire = 4 total
    assert store._get_conn.call_count == 4


def test_retry_succeeds_on_transient_none():
    """2: first _get_conn() returns None, second returns a real conn.
    INSERT executes, counter NOT incremented.
    """
    conn, cur = _conn_stub_with_cursor()
    store = _store_with_conn_sequence([None, conn])

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {}
    # Retry produced a real conn; the INSERT path ran exactly once
    assert cur.execute.call_count == 1
    insert_sql = cur.execute.call_args.args[0]
    assert "INSERT INTO scheduler_executions" in insert_sql
    conn.commit.assert_called_once()
    store._put_conn.assert_called_once_with(conn)


def test_retry_exhausts_records_drop(caplog):
    """3: both _get_conn() calls return None -> 1 drop recorded, 1 WARNING."""
    store = _store_with_conn_sequence([None, None])

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        with caplog.at_level(logging.WARNING, logger="sentinel.embedded_scheduler"):
            es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {"test_job": 1}
    skip_records = [r for r in caplog.records if "JOB_LISTENER_SILENT_SKIP" in r.message]
    assert len(skip_records) == 1
    assert "job_id=test_job" in skip_records[0].message
    assert "process_drop_count=1" in skip_records[0].message
    assert store._get_conn.call_count == 2


def test_alert_body_includes_drop_hint():
    """4: when get_listener_drop_counts() returns {waha_session_poll: 3},
    the alert body for that stale job includes JOB_LISTENER_SILENT_SKIP +
    'dropped 3 write(s)'.

    Patch target per brief codex #1421: triggers.embedded_scheduler.get_listener_drop_counts
    (sentinel does local 'from triggers.embedded_scheduler import ...' inside its
    alert-emit try block).
    """
    # Force the sentinel past cold-start grace
    sls._MODULE_LOAD_TIME = (
        datetime.now(timezone.utc) - timedelta(seconds=sls.COLD_START_GRACE_SECONDS + 60)
    )

    saved_registry = dict(sls.EXPECTED_JOBS)
    sls.EXPECTED_JOBS.clear()
    try:
        sls.register_expected_job("waha_session_poll", 5 * 60)  # T1, 300s

        # Build a store whose SELECT returns last_fired = 30 min ago -> stale
        cur = MagicMock()

        def _execute(sql, params):
            cur._next_jid = params[0] if params else None
        def _fetchone():
            jid = getattr(cur, "_next_jid", None)
            if jid == "waha_session_poll":
                return (datetime.now(timezone.utc) - timedelta(minutes=30),)
            return (None,)
        cur.execute.side_effect = _execute
        cur.fetchone.side_effect = _fetchone
        cur.close = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.rollback = MagicMock()
        store = MagicMock()
        store._get_conn.return_value = conn
        store._put_conn = MagicMock()
        store.create_alert = MagicMock()

        with patch("memory.store_back.SentinelStoreBack._get_global_instance",
                   return_value=store), \
             patch("triggers.embedded_scheduler.get_listener_drop_counts",
                   return_value={"waha_session_poll": 3}):
            out = sls.check_scheduler_liveness()

        assert out["alerted"] == ["waha_session_poll"]
        assert store.create_alert.call_count == 1
        body = store.create_alert.call_args.kwargs["body"]
        assert "JOB_LISTENER_SILENT_SKIP" in body
        assert "dropped 3 write(s)" in body

        # Negative half: when count == 0, the hint must NOT appear
        store.create_alert.reset_mock()
        with patch("memory.store_back.SentinelStoreBack._get_global_instance",
                   return_value=store), \
             patch("triggers.embedded_scheduler.get_listener_drop_counts",
                   return_value={}):
            sls.check_scheduler_liveness()
        body2 = store.create_alert.call_args.kwargs["body"]
        assert "JOB_LISTENER_SILENT_SKIP" not in body2
    finally:
        sls.EXPECTED_JOBS.clear()
        sls.EXPECTED_JOBS.update(saved_registry)
