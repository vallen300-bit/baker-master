"""COCKPIT_REFERENCE_DESK_2 Fix 4 — fireflies poller liveness honesty.

`check_new_transcripts` used to `return` on both the fetch-failure and the
empty-result paths WITHOUT touching the sentinel — so "poller dead" and "poller
alive, no new data" were indistinguishable, and the sentinel silently went stale
even while the poller ran fine every 2h. The fix:

  - fetch failure  -> report_failure("fireflies", ...)  (sentinel goes down)
  - empty result   -> report_success("fireflies")       (liveness != data novelty)

LATENT NOTE: fireflies is retired (Fix 2) AND its scan job is env-gated off in
prod (FIREFLIES_SCAN_ENABLED=false, Plaud-only cutover PR #341). `should_skip_poll`
therefore returns before these lines in every live run, so this fix is only
exercisable under unit test until fireflies is un-retired. These tests patch
should_skip_poll -> False to reach the fixed paths — they prove the blind spot is
closed, not that it runs in prod today.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import triggers.fireflies_trigger as ff


def _run_with(fetch_side_effect):
    """Run check_new_transcripts with should_skip_poll forced False and the
    sentinel report_* hooks mocked; returns (report_success_mock, report_failure_mock)."""
    watermark = datetime(2026, 6, 9, tzinfo=timezone.utc)

    rs = MagicMock(name="report_success")
    rf = MagicMock(name="report_failure")

    with patch("triggers.sentinel_health.should_skip_poll", return_value=False), \
         patch("triggers.sentinel_health.report_success", rs), \
         patch("triggers.sentinel_health.report_failure", rf), \
         patch.object(ff, "_backfill_running", False), \
         patch.object(ff.trigger_state, "get_watermark", return_value=watermark), \
         patch.object(ff, "fetch_new_transcripts", side_effect=fetch_side_effect):
        ff.check_new_transcripts()

    return rs, rf


def test_empty_result_reports_success():
    # Poller ran fine but returned no new transcripts -> sentinel must stay healthy.
    rs, rf = _run_with(fetch_side_effect=lambda _wm: [])
    rs.assert_called_once_with("fireflies")
    rf.assert_not_called()


def test_fetch_failure_reports_failure():
    # Poller fetch raised -> sentinel must go down, not silently stale.
    boom = RuntimeError("fireflies API 500")
    rs, rf = _run_with(fetch_side_effect=lambda _wm: (_ for _ in ()).throw(boom))
    assert rf.call_count == 1
    args = rf.call_args.args
    assert args[0] == "fireflies"
    assert "fetch failed" in args[1]
    rs.assert_not_called()


def test_retired_source_short_circuits_before_liveness():
    # In prod, fireflies is retired: should_skip_poll returns True (no DB), so
    # check_new_transcripts returns before ever touching the sentinel. This is the
    # honest current-state: the Fix 4 report_* calls are latent until un-retire.
    rs = MagicMock()
    rf = MagicMock()
    fetch = MagicMock()
    with patch("triggers.sentinel_health.report_success", rs), \
         patch("triggers.sentinel_health.report_failure", rf), \
         patch.object(ff, "fetch_new_transcripts", fetch):
        # real should_skip_poll — fireflies is in RETIRED_SOURCES -> True, DB-free
        ff.check_new_transcripts()
    fetch.assert_not_called()
    rs.assert_not_called()
    rf.assert_not_called()
