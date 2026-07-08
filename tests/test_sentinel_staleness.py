"""COCKPIT_REFERENCE_DESK_1 Fix 2 — honest staleness overlay.

A sentinel that silently stops (no failures, just no successes) must not keep
showing 'healthy' forever. `_apply_staleness` is a read-time overlay symmetric to
`_apply_retirement`: it flips a row to 'stale' when its last_success_at is older
than the per-source threshold, without ever writing the sentinel_health table.

DB-free by design: the overlay is a pure function over a list of dict rows.
"""
from datetime import datetime, timedelta, timezone

import triggers.sentinel_health as sh


def _row(source, status, age_hours=None, *, naive=False):
    """Build a sentinel_health-shaped row whose last_success_at is `age_hours`
    old (None => never succeeded)."""
    ls = None
    if age_hours is not None:
        ls = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        if naive:
            ls = ls.replace(tzinfo=None)
    return {"source": source, "status": status, "last_success_at": ls}


def test_old_success_flips_healthy_to_stale():
    # 30 days old, well past every threshold.
    rows = sh._apply_staleness([_row("calendar", "healthy", age_hours=24 * 30)])
    assert rows[0]["status"] == "stale"


def test_recent_success_stays_healthy():
    rows = sh._apply_staleness([_row("email", "healthy", age_hours=1)])
    assert rows[0]["status"] == "healthy"


def test_down_outranks_stale():
    # A hard-down sentinel keeps 'down' even though it's also long-silent.
    rows = sh._apply_staleness([_row("clickup", "down", age_hours=24 * 30)])
    assert rows[0]["status"] == "down"


def test_disabled_outranks_stale():
    # A retired source stays 'disabled' after the retirement overlay.
    rows = sh._apply_staleness([_row("exchange", "disabled", age_hours=24 * 30)])
    assert rows[0]["status"] == "disabled"


def test_null_last_success_left_unknown():
    # Never succeeded => not our job; the existing 'unknown' logic owns it.
    rows = sh._apply_staleness([_row("browser", "unknown", age_hours=None)])
    assert rows[0]["status"] == "unknown"


def test_naive_last_success_at_is_handled():
    # Rows can arrive with a tz-naive timestamp; overlay must not crash and must
    # treat it as UTC.
    rows = sh._apply_staleness([_row("calendar", "healthy", age_hours=24 * 30, naive=True)])
    assert rows[0]["status"] == "stale"


def test_per_source_threshold_email_short_browser_long():
    # 100h old: email (6h threshold) is stale; browser (168h threshold) is not.
    rows = sh._apply_staleness([
        _row("email", "healthy", age_hours=100),
        _row("browser", "healthy", age_hours=100),
    ])
    by_src = {r["source"]: r["status"] for r in rows}
    assert by_src["email"] == "stale"
    assert by_src["browser"] == "healthy"


def test_unlisted_source_uses_default_threshold():
    # An unlisted source uses _STALE_AFTER_HOURS_DEFAULT (48h).
    fresh = sh._apply_staleness([_row("mystery_source", "healthy", age_hours=40)])
    assert fresh[0]["status"] == "healthy"
    old = sh._apply_staleness([_row("mystery_source", "healthy", age_hours=60)])
    assert old[0]["status"] == "stale"


def test_stacks_after_retirement():
    # The real call site is _apply_staleness(_apply_retirement(rows)): a retired
    # source is disabled first, then staleness must not override it, while a live
    # silent source flips to stale.
    rows = [
        {"source": "exchange", "status": "down",
         "last_success_at": datetime.now(timezone.utc) - timedelta(days=90)},
        {"source": "calendar", "status": "healthy",
         "last_success_at": datetime.now(timezone.utc) - timedelta(days=40)},
    ]
    out = sh._apply_staleness(sh._apply_retirement(rows))
    by_src = {r["source"]: r["status"] for r in out}
    assert by_src["exchange"] == "disabled"
    assert by_src["calendar"] == "stale"


def test_config_has_expected_sources():
    # The brief pins these per-source thresholds; keep them in the map.
    for src in ("email", "graph_mail", "whatsapp", "clickup", "todoist",
                "calendar", "rss", "browser"):
        assert src in sh._STALE_AFTER_HOURS, src
    assert isinstance(sh._STALE_AFTER_HOURS_DEFAULT, int)
