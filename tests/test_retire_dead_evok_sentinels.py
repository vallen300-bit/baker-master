"""RETIRE_DEAD_EVOK_SENTINELS_1 — assert the 3 dead Evok Exchange sentinels are
retired: they are skipped, they cannot be written 'down', and they never count
toward /health's sentinels_down.

The Evok host (exchange.evok.ch) was decommissioned in the ~2026-06-03 M365
cutover; graph_mail is the live replacement. These tests are DB-free by design:
the retirement guards short-circuit before any DB access.
"""
from datetime import datetime, timezone

import triggers.sentinel_health as sh


RETIRED = ["exchange", "exchange_sent", "exchange_calendar"]
LIVE = ["graph_mail", "todoist", "roadmap_drift_sentinel", "email", "clickup"]


def test_retired_set_is_exactly_the_three_evok_sources():
    assert sh.RETIRED_SOURCES == frozenset(RETIRED)


def test_should_skip_poll_true_for_retired_without_db():
    # Guard returns True before _get_conn(), so this holds even with no DB.
    for src in RETIRED:
        assert sh.should_skip_poll(src) is True, src


def test_report_failure_is_noop_for_retired():
    # No exception, no DB needed — the retired guard returns before _get_conn().
    for src in RETIRED:
        assert sh.report_failure(src, "LOGIN failed.") is None


def test_report_success_is_noop_for_retired():
    for src in RETIRED:
        assert sh.report_success(src) is None


def test_apply_retirement_collapses_down_to_disabled():
    rows = [
        {"source": "exchange", "status": "down"},
        {"source": "exchange_sent", "status": "down"},
        {"source": "exchange_calendar", "status": "down"},
        {"source": "graph_mail", "status": "healthy"},
        {"source": "todoist", "status": "down"},
    ]
    out = sh._apply_retirement(rows)
    by_src = {r["source"]: r["status"] for r in out}
    # All 3 Evok sources normalized off 'down'.
    assert by_src["exchange"] == "disabled"
    assert by_src["exchange_sent"] == "disabled"
    assert by_src["exchange_calendar"] == "disabled"
    # Live sources untouched — graph_mail stays healthy, todoist stays down
    # (todoist is out of scope and must still surface as a real failure).
    assert by_src["graph_mail"] == "healthy"
    assert by_src["todoist"] == "down"


def test_retired_sources_not_counted_in_sentinels_down():
    # Mirror the /health counting loop (dashboard health_check): only 'down'
    # rows increment sentinels_down. After retirement the Evok sources drop out.
    rows = sh._apply_retirement([
        {"source": "exchange", "status": "down"},
        {"source": "exchange_sent", "status": "down"},
        {"source": "exchange_calendar", "status": "down"},
        {"source": "graph_mail", "status": "healthy"},
    ])
    down = [r["source"] for r in rows if r.get("status") == "down"]
    assert down == []


def test_live_sources_not_retired():
    # graph_mail (the live replacement) and the out-of-scope sources must NOT be
    # in the retired set — they still flow through the normal poll/health path.
    for src in LIVE:
        assert src not in sh.RETIRED_SOURCES, src


# ---- stale-watermark retirement (G3/codex M1 on PR #315) ---------------------

# trigger_watermarks source names differ from sentinel source names.
LIVE_WATERMARK_SOURCES = [
    "email_poll", "todoist", "slack", "dropbox", "fireflies", "whatsapp_resync",
]


def test_retired_watermark_mapping_covers_exchange_poll():
    # The 'exchange' sentinel owns the 'exchange_poll' watermark — it must be
    # retired so check_stale_watermarks() stops alerting on the dead host.
    assert "exchange_poll" in sh.RETIRED_WATERMARK_SOURCES
    assert "exchange_poll_sent" in sh.RETIRED_WATERMARK_SOURCES


def test_no_live_watermark_source_is_retired():
    for src in LIVE_WATERMARK_SOURCES:
        assert src not in sh.RETIRED_WATERMARK_SOURCES, src


def test_check_stale_watermarks_skips_retired_evok_but_alerts_live(monkeypatch):
    """check_stale_watermarks() must NOT fire a STALE DATA alert for the retired
    Evok watermark (exchange_poll), but MUST still alert a genuinely stale live
    source (email_poll). Proves the skip and that no live source regresses."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    very_stale = now - timedelta(hours=200)
    # Both retired (exchange_poll) and a live source (email_poll) are far stale.
    watermarks = {"exchange_poll": very_stale, "email_poll": very_stale}

    class _FakeCur:
        def __init__(self):
            self._params = None

        def execute(self, sql, params=None):
            self._params = params

        def fetchone(self):
            src = self._params[0] if self._params else None
            if src in watermarks:
                return {"last_seen": watermarks[src], "updated_at": watermarks[src]}
            return None  # unknown / clickup sources: no row

        def close(self):
            pass

    class _FakeConn:
        def cursor(self, *a, **k):
            return _FakeCur()

    fired: list = []

    class _FakeStore:
        def create_alert(self, **kw):
            fired.append(kw.get("source_id"))

    monkeypatch.setattr(sh, "_get_conn", lambda: (_FakeConn(), object()))
    monkeypatch.setattr(sh, "_put_conn", lambda store, conn: None)
    monkeypatch.setattr(sh, "_ensure_table", lambda conn: None)
    import memory.store_back as msb
    monkeypatch.setattr(
        msb.SentinelStoreBack,
        "_get_global_instance",
        classmethod(lambda cls: _FakeStore()),
    )

    sh.check_stale_watermarks()

    assert "stale_watermark_exchange_poll" not in fired  # retired -> silenced
    assert "stale_watermark_email_poll" in fired         # live -> still alerts
