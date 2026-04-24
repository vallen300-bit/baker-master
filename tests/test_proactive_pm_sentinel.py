"""BRIEF_PROACTIVE_PM_SENTINEL_1 tests — unit + SQL-assertion + integration DDL smoke.

Unit tests (no DB):
  * SLA defaults (PM-level + fallback)
  * DISMISS_REASONS canonical set
  * alert formatters (quiet-thread + dismiss-pattern)
  * suggestion rule branches
  * snooze-count / cooldown helper SQL shape (FakeCursor)

Integration tests (require live PG via ``needs_live_pg`` — skip cleanly when
TEST_DATABASE_URL + NEON_API_KEY both absent):
  * DDL smoke — capability_threads.sla_hours + alerts.dismiss_reason +
    idx_alerts_sentinel_dismiss_pattern all present.
"""
from __future__ import annotations


# ─── Unit: constants ───

def test_sla_defaults():
    from orchestrator.proactive_pm_sentinel import (
        PM_SLA_DEFAULT_HOURS, PM_SLA_FALLBACK_HOURS,
    )
    assert PM_SLA_DEFAULT_HOURS["ao_pm"] == 48
    assert PM_SLA_DEFAULT_HOURS["movie_am"] == 24
    assert PM_SLA_DEFAULT_HOURS.get("unknown_pm", PM_SLA_FALLBACK_HOURS) == PM_SLA_FALLBACK_HOURS


def test_dismiss_reasons_canonical():
    from orchestrator.proactive_pm_sentinel import DISMISS_REASONS
    assert DISMISS_REASONS == {
        "waiting_for_counterparty",
        "already_handled_offline",
        "low_priority",
        "wrong_thread",
    }


# ─── Unit: formatters ───

def test_format_quiet_thread_alert():
    from orchestrator.proactive_pm_sentinel import _format_quiet_thread_alert
    thread = {"thread_id": "t", "pm_slug": "ao_pm", "topic_summary": "Aukera release"}
    text = _format_quiet_thread_alert(thread, hours_silent=50.5, sla=48)
    assert "AO PM" in text
    assert "Aukera" in text
    assert "50.5" in text
    assert "48" in text


def test_format_quiet_thread_alert_handles_empty_topic():
    from orchestrator.proactive_pm_sentinel import _format_quiet_thread_alert
    thread = {"thread_id": "t", "pm_slug": "movie_am", "topic_summary": None}
    text = _format_quiet_thread_alert(thread, hours_silent=25.0, sla=24)
    assert "MOVIE AM" in text
    assert "no summary" in text.lower() or "(no summary)" in text


def test_format_dismiss_pattern_surface_waiting():
    from orchestrator.proactive_pm_sentinel import (
        _format_dismiss_pattern_surface, DISMISS_PATTERN_WINDOW_DAYS,
    )
    pattern = {"pm_slug": "ao_pm", "dismiss_reason": "waiting_for_counterparty", "n": 12}
    text = _format_dismiss_pattern_surface(pattern)
    assert "AO PM" in text
    assert "waiting for counterparty" in text
    assert "12×" in text
    assert f"{DISMISS_PATTERN_WINDOW_DAYS} days" in text


# ─── Unit: suggestion branches ───

def test_suggestion_for_waiting_proposes_higher_sla():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "waiting_for_counterparty", 15)
    # Current 48 → proposed max(48*3//2, 48+24) = 72
    assert "72" in s


def test_suggestion_for_wrong_thread_mentions_stitcher():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "wrong_thread", 10)
    assert "Stitcher" in s or "STITCH" in s or "stitch_decision" in s


def test_suggestion_for_low_priority_references_current_sla():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "low_priority", 11)
    assert "48" in s  # current ao_pm default
    assert "96" in s  # 48 * 2 floor suggestion


def test_suggestion_for_unknown_reason_falls_through():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "not_a_real_reason", 5)
    assert "investigate" in s.lower() or "manually" in s.lower()


# ─── Unit: SQL-assertion on helpers (shape-only, no DB) ───

class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else [None]
        self.queries = []
        self.rowcount = 1

    def execute(self, q, params=None):
        self.queries.append((q, params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows=None):
        self._rows = rows
        self.captured = None

    def cursor(self, *a, **kw):
        self.captured = _FakeCursor(rows=self._rows)
        return self.captured

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def __init__(self, rows=None):
        self._rows = rows
        self.conn = None

    def _get_conn(self):
        self.conn = _FakeConn(rows=self._rows)
        return self.conn

    def _put_conn(self, c):
        pass


def test_count_active_snoozes_zero_rows():
    from orchestrator.proactive_pm_sentinel import _count_active_snoozes
    store = _FakeStore(rows=[(0,)])
    assert _count_active_snoozes(store) == 0


def test_count_active_snoozes_extracts_int():
    from orchestrator.proactive_pm_sentinel import _count_active_snoozes
    store = _FakeStore(rows=[(7,)])
    assert _count_active_snoozes(store) == 7


def test_already_alerted_recently_query_filters_by_source_and_trigger():
    from orchestrator.proactive_pm_sentinel import _already_alerted_recently
    store = _FakeStore(rows=[None])
    _already_alerted_recently(store, "quiet_thread", "tid-abc", 24)
    q, params = store.conn.captured.queries[0]
    assert "'proactive_pm_sentinel'" in q
    assert "structured_actions->>'trigger'" in q
    assert params == ("tid-abc", "quiet_thread", "24")


def test_pattern_already_surfaced_uses_pattern_prefix():
    from orchestrator.proactive_pm_sentinel import _pattern_already_surfaced
    store = _FakeStore(rows=[None])
    _pattern_already_surfaced(store, "ao_pm::waiting_for_counterparty", 14)
    q, params = store.conn.captured.queries[0]
    assert "source_id = %s" in q
    assert params[0] == "pattern::ao_pm::waiting_for_counterparty"
    assert params[1] == "14"


# ─── Integration: DDL smoke (lesson #42 — fixture-only can miss schema drift) ───

def test_sentinel_schema_applied(needs_live_pg):
    """Confirms migration ran: both columns + partial index present."""
    import psycopg2
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE (table_name='capability_threads' AND column_name='sla_hours')
               OR (table_name='alerts' AND column_name='dismiss_reason')
            ORDER BY table_name, column_name
            """
        )
        cols = [(r[0], r[1]) for r in cur.fetchall()]
        assert ("alerts", "dismiss_reason") in cols
        assert ("capability_threads", "sla_hours") in cols

        cur.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE indexname = 'idx_alerts_sentinel_dismiss_pattern'
            """
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()
