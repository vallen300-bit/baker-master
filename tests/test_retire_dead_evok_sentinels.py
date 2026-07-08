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

# COCKPIT_REFERENCE_DESK_2 (ruling bus #7525/#7527, Director-informed 2026-07-09)
# expanded retirement beyond the original 3 Evok sources. The retired set is now
# a growing single-control-point list, not "exactly the Evok three".
CRD2_RETIRED = [
    "browser", "calendar", "slack", "initiative_engine",
    "obligation_generator", "fireflies", "fireflies_backfill",
]


def test_evok_sources_remain_retired():
    # The original RETIRE_DEAD_EVOK_SENTINELS_1 guarantee still holds: the 3 Evok
    # sources are retired. (Was test_retired_set_is_exactly_the_three_evok_sources;
    # reconciled for CRD_2's ratified retirement expansion.)
    for src in RETIRED:
        assert src in sh.RETIRED_SOURCES, src


def test_retired_set_is_exactly_evok_plus_crd2():
    # Single control point: the retired set is exactly Evok + the CRD_2 seven.
    # A stray addition here should fail loudly (this set is Director-ratified).
    assert sh.RETIRED_SOURCES == frozenset(RETIRED) | frozenset(CRD2_RETIRED)


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
# COCKPIT_REFERENCE_DESK_2 removed "slack" and "fireflies" from this live list —
# both are now retired watermark sources (see RETIRED_WATERMARK_SOURCES); their
# retirement is asserted in test_sentinel_staleness.py.
LIVE_WATERMARK_SOURCES = [
    "email_poll", "todoist", "dropbox", "whatsapp_resync",
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


# ---- RETIRED_SOURCE_STALE_ALERT_CLEANUP_1 -----------------------------------
# A retired source must not leave a dangling fired alert behind. PR #315 stopped
# *future* fires; these prove the *existing* fired alert is resolved/cleared.


class _CaptureCur:
    """Cursor stub that records the last UPDATE's SQL + params and reports a
    configurable rowcount."""

    def __init__(self, rowcount=1):
        self.sql = None
        self.params = None
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def close(self):
        pass


class _CaptureConn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False
        self.rolled_back = False

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _patch_capture(monkeypatch, cur):
    conn = _CaptureConn(cur)
    monkeypatch.setattr(sh, "_get_conn", lambda: (conn, object()))
    monkeypatch.setattr(sh, "_put_conn", lambda store, c: None)
    monkeypatch.setattr(sh, "_ensure_table", lambda c: None)
    return conn


def test_clear_retired_source_alerts_resolves_dangling_with_source_retired(monkeypatch):
    """The dangling fired alert is UPDATEd to status=resolved with
    exit_reason='source-retired' (a legit resolution, not a user dismiss)."""
    cur = _CaptureCur(rowcount=1)
    conn = _patch_capture(monkeypatch, cur)

    cleared = sh.clear_retired_source_alerts()

    assert cleared == 1
    assert conn.committed is True
    sql = " ".join(cur.sql.split())
    assert "UPDATE alerts" in sql
    assert "status = 'resolved'" in sql
    assert "exit_reason = 'source-retired'" in sql
    # exact source_id match (ANY of an explicit list), never a title LIKE heuristic
    assert "source_id = ANY(" in sql
    assert "title" not in sql.lower()
    assert "like" not in sql.lower()
    # only sentinel_health stale-watermark alerts, and only still-active ones
    assert "source = 'sentinel_health'" in sql
    assert "status NOT IN ('resolved', 'dismissed')" in sql


def test_clear_retired_source_alerts_scoped_to_retired_watermarks_only(monkeypatch):
    """The source_id list passed to the UPDATE covers exactly the retired
    watermark source_ids and never a live one (email_poll)."""
    cur = _CaptureCur(rowcount=2)
    _patch_capture(monkeypatch, cur)

    sh.clear_retired_source_alerts()

    (source_ids,) = cur.params  # single %s param = the list
    assert "stale_watermark_exchange_poll" in source_ids
    assert "stale_watermark_exchange_poll_sent" in source_ids
    assert "stale_watermark_email_poll" not in source_ids
    # one source_id per retired watermark source, nothing extra
    assert set(source_ids) == {
        f"stale_watermark_{wm}" for wm in sh.RETIRED_WATERMARK_SOURCES
    }


def test_clear_retired_source_alerts_does_not_call_resolve_alert(monkeypatch):
    """Must use the scoped UPDATE, NOT store_back.resolve_alert (which fires
    dismiss_related_alerts -> over-resolve risk)."""
    cur = _CaptureCur(rowcount=1)
    _patch_capture(monkeypatch, cur)

    import memory.store_back as msb

    def _boom(self, alert_id):  # pragma: no cover - must never run
        raise AssertionError("resolve_alert must not be used for retired cleanup")

    monkeypatch.setattr(msb.SentinelStoreBack, "resolve_alert", _boom)

    # No exception => resolve_alert was never touched.
    assert sh.clear_retired_source_alerts() == 1


def test_check_stale_watermarks_clears_orphan_alerts(monkeypatch):
    """check_stale_watermarks() runs the orphan cleanup so retiring a source
    self-heals (acceptance #2: never leaves an orphaned fired alert)."""
    calls = {"n": 0}

    def _spy():
        calls["n"] += 1
        return 1

    monkeypatch.setattr(sh, "clear_retired_source_alerts", _spy)
    # Make the rest of check_stale_watermarks a cheap no-op: no DB.
    monkeypatch.setattr(sh, "_get_conn", lambda: (None, None))

    sh.check_stale_watermarks()

    assert calls["n"] == 1
