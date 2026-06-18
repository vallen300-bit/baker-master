"""HEALTH_TRIAGE 2026-06-18 — report_success() must clear last_error_msg.

A sentinel that recovers flips status->healthy and consecutive_failures->0, but
pre-fix the stale last_error_msg lingered in the row forever, so /api/health kept
surfacing weeks-old error text on a healthy sentinel (false "wedge" alarms for
plaud_backfill + doc_pipeline). report_success() now NULLs last_error_msg on the
recovery upsert; last_error_at is left intact as a historical marker.
"""
import triggers.sentinel_health as sh


class _Cur:
    """Cursor stub: records every execute, returns a prior status for the SELECT."""

    def __init__(self, prev_status="down"):
        self.calls = []
        self._prev_status = prev_status

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (self._prev_status,)

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _patch(monkeypatch, cur):
    conn = _Conn(cur)
    monkeypatch.setattr(sh, "_get_conn", lambda: (conn, object()))
    monkeypatch.setattr(sh, "_put_conn", lambda store, c: None)
    monkeypatch.setattr(sh, "_ensure_table", lambda c: None)
    monkeypatch.setattr(sh, "_fire_recovery_alert", lambda source: None)
    return conn


def test_report_success_nulls_last_error_msg(monkeypatch):
    cur = _Cur(prev_status="healthy")
    conn = _patch(monkeypatch, cur)

    sh.report_success("plaud_backfill")

    # The recovery upsert is the last execute; it must NULL last_error_msg.
    upsert_sql = cur.calls[-1][0]
    assert "ON CONFLICT" in upsert_sql
    assert "last_error_msg = NULL" in upsert_sql
    assert "status = 'healthy'" in upsert_sql
    assert conn.committed is True


def test_report_success_preserves_last_error_at(monkeypatch):
    # Historical marker must NOT be wiped — only the displayed message clears.
    cur = _Cur(prev_status="healthy")
    _patch(monkeypatch, cur)

    sh.report_success("doc_pipeline")

    upsert_sql = cur.calls[-1][0]
    assert "last_error_at" not in upsert_sql.split("DO UPDATE SET", 1)[1]


def test_report_success_noop_for_retired_still_holds(monkeypatch):
    # Retirement guard precedes any DB work — no execute should happen.
    cur = _Cur()
    _patch(monkeypatch, cur)

    for src in sh.RETIRED_SOURCES:
        assert sh.report_success(src) is None
    assert cur.calls == []
