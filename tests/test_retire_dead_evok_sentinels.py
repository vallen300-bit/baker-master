"""RETIRE_DEAD_EVOK_SENTINELS_1 — assert the 3 dead Evok Exchange sentinels are
retired: they are skipped, they cannot be written 'down', and they never count
toward /health's sentinels_down.

The Evok host (exchange.evok.ch) was decommissioned in the ~2026-06-03 M365
cutover; graph_mail is the live replacement. These tests are DB-free by design:
the retirement guards short-circuit before any DB access.
"""
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
