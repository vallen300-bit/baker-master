"""BRIEF_PROACTIVE_PM_SENTINEL_1 tests — unit + SQL-assertion + integration DDL smoke.

Unit tests (no DB):
  * SLA defaults (PM-level + fallback)
  * DISMISS_REASONS canonical set
  * alert formatters (quiet-thread + dismiss-pattern)
  * suggestion rule branches
  * snooze-count / cooldown helper SQL shape (FakeCursor)

Endpoint tests (TestClient, auth-bypassed):
  * wrong_thread rethread_hint server-side turn lookup — added 2026-04-24
    fix-back. Skip gracefully if ``outputs.dashboard`` cannot be imported
    (pre-existing Python 3.9 / PEP-604 incompat in the import chain; passes
    on CI 3.10+ same as the other TestClient suites in this repo).

Integration tests (require live PG via ``needs_live_pg`` — skip cleanly when
TEST_DATABASE_URL + NEON_API_KEY both absent):
  * DDL smoke — capability_threads.sla_hours + alerts.dismiss_reason +
    idx_alerts_sentinel_dismiss_pattern all present.
"""
from __future__ import annotations

import pytest


def _dashboard_importable() -> bool:
    """Return True iff outputs.dashboard imports cleanly in the current env.
    Pre-existing Python 3.9 / PEP-604 fail in tools/ingest/extractors.py:275
    breaks local-dev import; CI (3.10+) clears it.
    """
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable in this env (Python 3.9 PEP-604 "
           "issue in tools/ingest/extractors.py:275 — pre-existing, clears on 3.10+)",
)


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


# ─── Endpoint: wrong_thread rethread_hint server-side turn lookup ───
# Added 2026-04-24 fix-back after PR #58: sentinel alert's source_id is a
# thread_id but Phase 2 re-thread endpoint operates on a turn_id. The endpoint
# now looks up the most-recent turn while the cursor is still open.

class _EndpointFakeCursor:
    """Multi-query cursor with queued responses.

    _queue is a list of ("SELECT"|"UPDATE", rows-or-None) entries consumed in
    order. SELECT responses populate fetchone(); UPDATE entries just advance.
    """

    def __init__(self, queue):
        self._queue = list(queue)
        self._pending = None

    def execute(self, sql, params=None):
        if not self._queue:
            raise AssertionError(f"Unexpected query: {sql[:80]}...")
        _kind, payload = self._queue.pop(0)
        self._pending = payload

    def fetchone(self):
        out = self._pending
        self._pending = None
        return out

    def close(self):
        pass


class _EndpointFakeConn:
    def __init__(self, queue):
        self._queue = queue
        self.rolled_back = False
        self.committed = False

    def cursor(self, *a, **kw):
        return _EndpointFakeCursor(self._queue)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _EndpointFakeStore:
    def __init__(self, queue):
        self._queue = queue
        self.store_correction_calls = []

    def _get_conn(self):
        return _EndpointFakeConn(self._queue)

    def _put_conn(self, c):
        pass

    def store_correction(self, **kw):
        self.store_correction_calls.append(kw)
        return True


def _endpoint_client(monkeypatch, queue):
    """Wire up TestClient with BAKER_API_KEY + fake store override."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-key")

    from outputs import dashboard as _dash
    from outputs.dashboard import app, verify_api_key

    fake = _EndpointFakeStore(queue)
    monkeypatch.setattr(_dash, "_get_store", lambda: fake)
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app), fake


def test_wrong_thread_rethread_hint_source_wires_latest_turn_id():
    """Local-runnable source assertion: the fix-back landed correctly.

    Verifies the rethread_hint block in outputs/dashboard.py both:
      (a) queries capability_turns for the latest turn_id, AND
      (b) propagates the captured local `latest_turn_id` into the hint
          (NOT hardcoded None).

    Complements the TestClient tests below which skip on Python 3.9 due
    to a pre-existing PEP-604 import bug unrelated to this fix-back.
    """
    from pathlib import Path
    src = Path("outputs/dashboard.py").read_text()

    # The lookup SQL must be present
    assert "SELECT turn_id FROM capability_turns" in src
    assert 'ORDER BY created_at DESC' in src
    assert 'LIMIT 1' in src

    # The rethread_hint must carry the looked-up value (NOT hardcoded None)
    # The fix-back replaces the literal "turn_id_hint": None placement.
    assert '"turn_id_hint": latest_turn_id,' in src

    # Guardrail: old hardcoded-None placement should not remain in the
    # rethread_hint block. The only remaining "turn_id_hint": None allowed is
    # the JS-side absent-hint comment, never the server-side response.
    rethread_hint_block_idx = src.find('"rethread_endpoint": "/api/pm/threads/re-thread"')
    assert rethread_hint_block_idx > 0
    # Walk back ~300 chars and confirm the correct wiring sits nearby
    block_window = src[max(0, rethread_hint_block_idx - 400):rethread_hint_block_idx + 200]
    assert '"turn_id_hint": latest_turn_id,' in block_window
    assert '"turn_id_hint": None,' not in block_window


@_skip_without_dashboard
def test_wrong_thread_rethread_hint_populates_latest_turn_id(monkeypatch):
    """wrong_thread dismiss should carry the most-recent turn_id in the thread."""
    # DictCursor rows support dict-style access; a plain dict with the right
    # keys is enough for the endpoint which reads row["matter_slug"] etc.
    alert_row = {
        "id": 42,
        "source": "proactive_pm_sentinel",
        "source_id": "thread-uuid-abc",
        "matter_slug": "ao_pm",
        "structured_actions": {},
    }
    # Latest-turn lookup hits `cur.fetchone()[0]` — return a tuple-ish row.
    latest_turn_row = ("turn-uuid-LATEST",)
    queue = [
        ("SELECT", alert_row),        # alert lookup
        ("UPDATE", None),              # dismiss UPDATE
        ("SELECT", latest_turn_row),  # wrong_thread turn lookup
    ]
    client, _fake = _endpoint_client(monkeypatch, queue)
    try:
        resp = client.post(
            "/api/sentinel/feedback",
            json={"alert_id": 42, "verdict": "dismiss", "dismiss_reason": "wrong_thread"},
        )
    finally:
        from outputs.dashboard import app, verify_api_key
        app.dependency_overrides.pop(verify_api_key, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "dismiss"
    assert body["status"] == "dismissed"
    assert "rethread_hint" in body
    assert body["rethread_hint"]["turn_id_hint"] == "turn-uuid-LATEST"
    assert body["rethread_hint"]["thread_id"] == "thread-uuid-abc"
    assert body["rethread_hint"]["pm_slug"] == "ao_pm"
    assert body["rethread_hint"]["rethread_endpoint"] == "/api/pm/threads/re-thread"


@_skip_without_dashboard
def test_wrong_thread_rethread_hint_null_when_no_turns(monkeypatch):
    """Empty thread → turn_id_hint is None, response still 200."""
    alert_row = {
        "id": 43,
        "source": "proactive_pm_sentinel",
        "source_id": "thread-empty",
        "matter_slug": "ao_pm",
        "structured_actions": {},
    }
    queue = [
        ("SELECT", alert_row),  # alert lookup
        ("UPDATE", None),        # dismiss UPDATE
        ("SELECT", None),        # no turn rows
    ]
    client, _fake = _endpoint_client(monkeypatch, queue)
    try:
        resp = client.post(
            "/api/sentinel/feedback",
            json={"alert_id": 43, "verdict": "dismiss", "dismiss_reason": "wrong_thread"},
        )
    finally:
        from outputs.dashboard import app, verify_api_key
        app.dependency_overrides.pop(verify_api_key, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rethread_hint"]["turn_id_hint"] is None
    assert body["rethread_hint"]["thread_id"] == "thread-empty"


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
