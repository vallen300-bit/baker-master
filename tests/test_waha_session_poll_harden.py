"""Tests for BRIEF_WAHA_SESSION_POLL_HARDEN_1.

12 cases covering:
  1.  STARTING once → no alert; starting_streak == 1.
  2.  STARTING ×3 consecutive → T1 alert WAHA SESSION STUCK STARTING; streak == 3.
  3.  WORKING after 2× STARTING → no alert; both streaks reset; report_success called.
  4.  UNKNOWN once → no alert; non_healthy_streak == 1.
  5.  UNKNOWN ×2 consecutive → T1 alert WAHA SESSION UNKNOWN STATUS.
  6.  SCAN_QR_CODE → T1 alert WAHA SESSION: SCAN_QR_CODE; both streaks reset.
  7.  Webhooks union missing 'session.status' → T1 alert WAHA WEBHOOK CONFIG DRIFT.
  8.  Webhooks union missing 'message.any' → T1 alert WAHA WEBHOOK CONFIG DRIFT.
  9.  Webhooks union has both → no drift alert.
  10. Source-id dedupe stability — STARTING ×3 emits stable starting-stuck-YYYYMMDD-HH.
  11. Counter reset across transitions — STARTING → WORKING → STARTING = tick 1, not 2.
  12. report_failure raising does not crash the poll.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sentinel_health(monkeypatch):
    """Fresh import of triggers.sentinel_health with module state reset.

    Some sibling tests replace memory.store_back with a MagicMock and do not
    restore it; force a clean re-import so our monkeypatches land on the real
    target. Also reset _WAHA_POLL_STATE so tests are independent.
    """
    for mod in ("triggers.sentinel_health", "triggers.waha_client",
                "memory.store_back", "memory"):
        sys.modules.pop(mod, None)
    sh = importlib.import_module("triggers.sentinel_health")
    sh._WAHA_POLL_STATE["non_healthy_streak"] = 0
    sh._WAHA_POLL_STATE["starting_streak"] = 0
    return sh


@pytest.fixture
def alert_spy(sentinel_health, monkeypatch):
    """Captures every store_back.create_alert call (title, source_id, body)."""
    captured: list[dict] = []

    class _Store:
        def create_alert(self, **kwargs):
            captured.append(kwargs)

    fake_store = _Store()

    class _SentinelStoreBack:
        @staticmethod
        def _get_global_instance():
            return fake_store

    fake_module = MagicMock()
    fake_module.SentinelStoreBack = _SentinelStoreBack
    monkeypatch.setitem(sys.modules, "memory.store_back", fake_module)

    # Stub report_success / report_failure so we count calls without touching DB
    success_calls: list[str] = []
    failure_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(sentinel_health, "report_success",
                        lambda source: success_calls.append(source))
    monkeypatch.setattr(sentinel_health, "report_failure",
                        lambda source, error: failure_calls.append((source, error)))

    return captured, success_calls, failure_calls


def _patch_get_session_status(monkeypatch, response):
    """Inject a fake triggers.waha_client.get_session_status returning `response`."""
    fake_waha_client = MagicMock()
    fake_waha_client.get_session_status = lambda _headers_override=None: response
    fake_waha_client.monitor_headers = lambda: {}
    monkeypatch.setitem(sys.modules, "triggers.waha_client", fake_waha_client)


def _ok_webhooks():
    """Webhooks union covering both required events — never trips drift check."""
    return {"webhooks": [{"events": ["session.status", "message.any"]}]}


# ----------------------------------------------------------------------------
# Case 1 — STARTING once → no alert, streak == 1
# ----------------------------------------------------------------------------
def test_case_1_starting_once_no_alert(sentinel_health, alert_spy, monkeypatch):
    captured, _, failures = alert_spy
    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})

    sentinel_health.poll_waha_session()

    starting_alerts = [a for a in captured if a.get("title") == "WAHA SESSION STUCK STARTING"]
    assert starting_alerts == []
    assert failures == []
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 1
    assert sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] == 0


# ----------------------------------------------------------------------------
# Case 2 — STARTING ×3 → T1 alert STUCK STARTING
# ----------------------------------------------------------------------------
def test_case_2_starting_three_ticks_alerts(sentinel_health, alert_spy, monkeypatch):
    captured, _, failures = alert_spy
    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})

    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()

    starting_alerts = [a for a in captured if a.get("title") == "WAHA SESSION STUCK STARTING"]
    assert len(starting_alerts) == 1
    assert starting_alerts[0]["tier"] == 1
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 3
    assert len(failures) == 1
    assert "STARTING stuck for 3 ticks" in failures[0][1]


# ----------------------------------------------------------------------------
# Case 3 — WORKING after STARTING resets both counters + reports success
# ----------------------------------------------------------------------------
def test_case_3_working_after_starting_resets(sentinel_health, alert_spy, monkeypatch):
    captured, successes, _ = alert_spy

    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 2

    _patch_get_session_status(monkeypatch, {"status": "WORKING", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()

    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 0
    assert sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] == 0
    assert successes == ["waha_session_poll"]
    starting_alerts = [a for a in captured if a.get("title") == "WAHA SESSION STUCK STARTING"]
    assert starting_alerts == []


# ----------------------------------------------------------------------------
# Case 4 — UNKNOWN once → no alert, non_healthy_streak == 1
# ----------------------------------------------------------------------------
def test_case_4_unknown_once_no_alert(sentinel_health, alert_spy, monkeypatch):
    captured, _, failures = alert_spy
    _patch_get_session_status(monkeypatch, {"status": "UNKNOWN", "config": _ok_webhooks()})

    sentinel_health.poll_waha_session()

    unknown_alerts = [a for a in captured if a.get("title") == "WAHA SESSION UNKNOWN STATUS"]
    assert unknown_alerts == []
    assert failures == []
    assert sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] == 1
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 0


# ----------------------------------------------------------------------------
# Case 5 — UNKNOWN ×2 → T1 alert UNKNOWN STATUS
# ----------------------------------------------------------------------------
def test_case_5_unknown_two_ticks_alerts(sentinel_health, alert_spy, monkeypatch):
    captured, _, failures = alert_spy
    _patch_get_session_status(monkeypatch, {"status": "UNKNOWN", "config": _ok_webhooks()})

    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()

    unknown_alerts = [a for a in captured if a.get("title") == "WAHA SESSION UNKNOWN STATUS"]
    assert len(unknown_alerts) == 1
    assert unknown_alerts[0]["tier"] == 1
    assert sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] == 2
    assert len(failures) == 1
    assert "Unknown status 'UNKNOWN' for 2 ticks" in failures[0][1]


# ----------------------------------------------------------------------------
# Case 6 — SCAN_QR_CODE → immediate T1 alert; both counters reset
# ----------------------------------------------------------------------------
def test_case_6_scan_qr_immediate_alert(sentinel_health, alert_spy, monkeypatch):
    captured, _, failures = alert_spy
    # Pre-load streaks to verify reset
    sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] = 1
    sentinel_health._WAHA_POLL_STATE["starting_streak"] = 1

    _patch_get_session_status(monkeypatch, {"status": "SCAN_QR_CODE", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()

    dead_alerts = [a for a in captured if a.get("title") == "WAHA SESSION: SCAN_QR_CODE"]
    assert len(dead_alerts) == 1
    assert dead_alerts[0]["tier"] == 1
    assert sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] == 0
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 0
    assert len(failures) == 1
    assert "SCAN_QR_CODE" in failures[0][1]


# ----------------------------------------------------------------------------
# Case 7 — webhook union missing session.status → drift alert
# ----------------------------------------------------------------------------
def test_case_7_drift_missing_session_status(sentinel_health, alert_spy, monkeypatch):
    captured, _, _ = alert_spy
    _patch_get_session_status(monkeypatch, {
        "status": "WORKING",
        "config": {"webhooks": [{"events": ["message.any"]}]},
    })

    sentinel_health.poll_waha_session()

    drift_alerts = [a for a in captured if a.get("title") == "WAHA WEBHOOK CONFIG DRIFT"]
    assert len(drift_alerts) == 1
    assert "['session.status']" in drift_alerts[0]["body"]
    assert drift_alerts[0]["tier"] == 1


# ----------------------------------------------------------------------------
# Case 8 — webhook union missing message.any → drift alert
# ----------------------------------------------------------------------------
def test_case_8_drift_missing_message_any(sentinel_health, alert_spy, monkeypatch):
    captured, _, _ = alert_spy
    _patch_get_session_status(monkeypatch, {
        "status": "WORKING",
        "config": {"webhooks": [{"events": ["session.status"]}]},
    })

    sentinel_health.poll_waha_session()

    drift_alerts = [a for a in captured if a.get("title") == "WAHA WEBHOOK CONFIG DRIFT"]
    assert len(drift_alerts) == 1
    assert "['message.any']" in drift_alerts[0]["body"]


# ----------------------------------------------------------------------------
# Case 9 — webhook union covers both → no drift alert (status branch may still fire)
# ----------------------------------------------------------------------------
def test_case_9_drift_clean_no_alert(sentinel_health, alert_spy, monkeypatch):
    captured, _, _ = alert_spy
    # Spread required events across TWO webhooks to prove union semantics
    _patch_get_session_status(monkeypatch, {
        "status": "WORKING",
        "config": {
            "webhooks": [
                {"events": ["session.status"]},
                {"events": ["message.any"]},
            ],
        },
    })

    sentinel_health.poll_waha_session()

    drift_alerts = [a for a in captured if a.get("title") == "WAHA WEBHOOK CONFIG DRIFT"]
    assert drift_alerts == []


# ----------------------------------------------------------------------------
# Case 10 — source-id dedupe stability for STARTING-stuck within same hour
# ----------------------------------------------------------------------------
def test_case_10_source_id_dedupe_stable_template(sentinel_health, alert_spy, monkeypatch):
    captured, _, _ = alert_spy
    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})

    # 3 ticks crosses grace → first alert
    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()
    sentinel_health.poll_waha_session()
    # 4th tick within same hour → would re-emit same source_id (store_back dedupes)
    sentinel_health.poll_waha_session()

    starting_alerts = [a for a in captured if a.get("title") == "WAHA SESSION STUCK STARTING"]
    assert len(starting_alerts) == 2  # spy doesn't dedupe; store_back would
    expected_hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d-%H")
    expected_source_id = f"starting-stuck-{expected_hour_bucket}"
    for alert in starting_alerts:
        assert alert["source_id"] == expected_source_id


# ----------------------------------------------------------------------------
# Case 11 — counter reset across transitions: STARTING → WORKING → STARTING = tick 1
# ----------------------------------------------------------------------------
def test_case_11_counter_reset_across_transitions(sentinel_health, alert_spy, monkeypatch):
    _, _, _ = alert_spy

    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 1

    _patch_get_session_status(monkeypatch, {"status": "WORKING", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 0

    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()
    assert sentinel_health._WAHA_POLL_STATE["starting_streak"] == 1


# ----------------------------------------------------------------------------
# Case 12 — create_alert (store-back) raising does not crash the poll.
#
# Brief Verification #12: "report_failure raises → poll does not crash
# (try/except Exception wrapping the store-back call already in place;
# verify still wraps in refactor)". The wrapper is around each create_alert
# call site — we verify the wrapper is preserved for every branch that
# alerts (DEAD, STARTING-stuck, UNKNOWN-stuck, webhook-drift).
# ----------------------------------------------------------------------------
def test_case_12_create_alert_raise_no_crash(sentinel_health, monkeypatch):
    # Stub report_success/report_failure so they don't touch DB.
    monkeypatch.setattr(sentinel_health, "report_success", lambda source: None)
    monkeypatch.setattr(sentinel_health, "report_failure", lambda source, error: None)

    class _Boom:
        def create_alert(self, **_kwargs):
            raise RuntimeError("simulated store_back outage")

    class _SentinelStoreBack:
        @staticmethod
        def _get_global_instance():
            return _Boom()

    fake_module = MagicMock()
    fake_module.SentinelStoreBack = _SentinelStoreBack
    monkeypatch.setitem(sys.modules, "memory.store_back", fake_module)

    # DEAD branch — alert path raises, poll must not propagate.
    _patch_get_session_status(monkeypatch, {"status": "STOPPED", "config": _ok_webhooks()})
    sentinel_health.poll_waha_session()  # no exception expected

    # STARTING-stuck branch — alert path raises, poll must not propagate.
    sentinel_health._WAHA_POLL_STATE["starting_streak"] = 0
    _patch_get_session_status(monkeypatch, {"status": "STARTING", "config": _ok_webhooks()})
    for _ in range(3):
        sentinel_health.poll_waha_session()

    # UNKNOWN-stuck branch — alert path raises, poll must not propagate.
    sentinel_health._WAHA_POLL_STATE["non_healthy_streak"] = 0
    _patch_get_session_status(monkeypatch, {"status": "UNKNOWN", "config": _ok_webhooks()})
    for _ in range(2):
        sentinel_health.poll_waha_session()

    # Webhook-drift branch — alert path raises, poll must not propagate.
    _patch_get_session_status(monkeypatch, {
        "status": "WORKING", "config": {"webhooks": [{"events": ["message.any"]}]},
    })
    sentinel_health.poll_waha_session()
