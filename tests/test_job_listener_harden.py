"""Ship gate for JOB_LISTENER_HARDEN_1 + SCHEDULER_LIVENESS_REVIVE_1.

REVIVE_1 changed the drop semantics: a `scheduler_executions` row is now
dropped ONLY when the bounded pooled backoff (1 immediate + 3 retries at
100/200/400ms) AND the dedicated direct-conn fallback BOTH fail. The pre-REVIVE
cases (1, 3) that recorded a drop on pooled-None alone were updated to drive the
direct fallback to failure as well; cases 2 + 4 are unchanged.

Cases:
  1.  Pooled never yields a conn AND direct fails -> drop recorded + logged.
  2.  Pooled retry succeeds on transient None -> no drop (unchanged).
  3.  Pooled backoff exhausts (4 attempts) AND direct fails -> 1 drop recorded.
  4.  Alert body includes drop-hint when count > 0 (unchanged).
  5.  (REVIVE_1 NIT 3a) Pooled None but DIRECT succeeds -> row inserted, no drop.
  6.  (REVIVE_1 NIT 3b) Pooled None AND direct raises -> drop +1, no raise.
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


def _store_always_none():
    """SentinelStoreBack mock whose pooled _get_conn() never yields a conn —
    drives the REVIVE_1 direct-fallback path on every call.
    """
    store = MagicMock()
    store._get_conn.return_value = None
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


def _direct_conn_stub():
    """Stub for a dedicated direct psycopg2 connection (fallback path)."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ---------- Tests -----------------------------------------------------------

def test_silent_skip_logs_and_counts(caplog):
    """1 (REVIVE_1): pooled pool never yields a conn AND the direct fallback
    fails -> drop recorded + WARNING logged. Fired twice -> count == 2.

    Updated from JOB_LISTENER_HARDEN_1: a drop is now recorded ONLY when the
    bounded pooled backoff AND the dedicated direct-conn fallback both fail.
    """
    store = _store_always_none()

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store), \
         patch("psycopg2.connect", side_effect=Exception("no direct endpoint")), \
         patch("time.sleep"):
        with caplog.at_level(logging.WARNING, logger="sentinel.embedded_scheduler"):
            es._job_listener(_make_event("test_job"))
            es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {"test_job": 2}
    skip_records = [r for r in caplog.records if "JOB_LISTENER_SILENT_SKIP" in r.message]
    assert len(skip_records) == 2
    assert all("job_id=test_job" in r.message for r in skip_records)


def test_retry_succeeds_on_transient_none():
    """2: first _get_conn() returns None, second returns a real conn.
    INSERT executes via the pooled path, counter NOT incremented. (Unchanged
    by REVIVE_1 — the direct fallback is never reached.)
    """
    conn, cur = _conn_stub_with_cursor()
    store = _store_with_conn_sequence([None, conn])

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store), \
         patch("time.sleep"):
        es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {}
    # Retry produced a real conn; the INSERT path ran exactly once
    assert cur.execute.call_count == 1
    insert_sql = cur.execute.call_args.args[0]
    assert "INSERT INTO scheduler_executions" in insert_sql
    conn.commit.assert_called_once()
    store._put_conn.assert_called_once_with(conn)


def test_retry_exhausts_records_drop(caplog):
    """3 (REVIVE_1): pooled backoff exhausts (1 immediate + 3 retries = 4 None
    attempts) AND the direct fallback then fails -> exactly 1 drop, 1 WARNING,
    direct attempted exactly once.
    """
    store = _store_always_none()

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store), \
         patch("psycopg2.connect", side_effect=Exception("boom")) as mock_connect, \
         patch("time.sleep"):
        with caplog.at_level(logging.WARNING, logger="sentinel.embedded_scheduler"):
            es._job_listener(_make_event("test_job"))

    assert es.get_listener_drop_counts() == {"test_job": 1}
    skip_records = [r for r in caplog.records if "JOB_LISTENER_SILENT_SKIP" in r.message]
    assert len(skip_records) == 1
    assert "job_id=test_job" in skip_records[0].message
    assert "process_drop_count=1" in skip_records[0].message
    # bounded backoff = 1 immediate + 3 retries = 4 pooled attempts
    assert store._get_conn.call_count == 4
    # direct fallback attempted exactly once
    assert mock_connect.call_count == 1


def test_direct_fallback_success_no_drop():
    """5 — REVIVE_1 NIT 3 (codex #1452) case (a): pooled pool never yields a
    conn but the dedicated direct connection SUCCEEDS -> row inserted via the
    direct path, drop-count UNCHANGED, direct connection closed.
    """
    store = _store_always_none()
    direct, dcur = _direct_conn_stub()

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store), \
         patch("psycopg2.connect", return_value=direct) as mock_connect, \
         patch("time.sleep"):
        es._job_listener(_make_event("test_job"))

    # No drop recorded — the row landed via the direct fallback
    assert es.get_listener_drop_counts() == {}
    # Direct path executed the INSERT exactly once
    assert dcur.execute.call_count == 1
    insert_sql = dcur.execute.call_args.args[0]
    assert "INSERT INTO scheduler_executions" in insert_sql
    direct.commit.assert_called_once()
    # short-lived: closed in finally
    direct.close.assert_called_once()
    # connect_timeout guard present so the fallback cannot hang
    assert mock_connect.call_args.kwargs.get("connect_timeout") == 5
    # never touched the shared pool's put path (no pooled conn was obtained)
    store._put_conn.assert_not_called()


def test_direct_fallback_failure_records_drop_no_raise():
    """6 — REVIVE_1 NIT 3 (codex #1452) case (b): pooled pool never yields a
    conn AND the direct fallback raises -> _record_listener_drop increments and
    the listener does NOT propagate the exception (scheduler must never crash).
    """
    store = _store_always_none()

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store), \
         patch("psycopg2.connect", side_effect=Exception("conn refused")), \
         patch("time.sleep"):
        # Must not raise — a failing observability write is logged, not raised.
        es._job_listener(_make_event("waha_session_poll"))

    assert es.get_listener_drop_counts() == {"waha_session_poll": 1}


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

        def _execute(sql, params=None):
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
