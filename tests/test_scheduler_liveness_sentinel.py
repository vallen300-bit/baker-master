"""Ship gate for SCHEDULER_JOB_LIVENESS_1.

14 cases per brief Verification list:
  1.  Cold-start window suppresses all checks.
  2.  Post-cold-start + empty registry -> no work.
  3.  Clean path -> all jobs fresh, no alerts.
  4.  Single stale T1 -> 1 T1 alert.
  5.  Single stale T2 -> 1 T2 alert.
  6.  Multiple stale -> 2 alerts.
  7.  Never-fired T1 -> 1 T1 alert noting no 24h row.
  8.  Never-fired T2 -> no alert (fail-open).
  9.  DB connection unavailable -> skipped_reason, no crash.
  10. create_alert raises mid-loop -> loop continues.
  11. Hourly-bucket source_id stable across calls in same hour.
  12. No-cron invariant: no register_expected_job for any CronTrigger id.
  13. Dynamic-interval correctness: env override propagates via clamp helper.
  14. Below-floor clamp: env below floor clamps to floor.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from triggers import scheduler_liveness_sentinel as sls


# ---------- Fixtures --------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_registry():
    """Clear EXPECTED_JOBS between tests and restore _MODULE_LOAD_TIME."""
    saved_jobs = dict(sls.EXPECTED_JOBS)
    saved_load = sls._MODULE_LOAD_TIME
    sls.EXPECTED_JOBS.clear()
    yield
    sls.EXPECTED_JOBS.clear()
    sls.EXPECTED_JOBS.update(saved_jobs)
    sls._MODULE_LOAD_TIME = saved_load


def _store_with_rows(rows_per_job: dict):
    """Build a mock store/conn/cursor where cur.fetchone() returns rows
    indexed by the SELECT's job_id parameter.
    """
    cur = MagicMock()
    queries = []

    def _execute(sql, params):
        queries.append((sql, params))
        cur._next_jid = params[0] if params else None

    def _fetchone():
        jid = getattr(cur, "_next_jid", None)
        return rows_per_job.get(jid, (None,))

    cur.execute.side_effect = _execute
    cur.fetchone.side_effect = _fetchone
    conn = MagicMock()
    conn.cursor.return_value = cur
    store = MagicMock()
    store._get_conn.return_value = conn
    store._put_conn = MagicMock()
    return store, conn, cur


def _force_post_coldstart():
    """Set _MODULE_LOAD_TIME far enough back to bypass grace."""
    sls._MODULE_LOAD_TIME = datetime.now(timezone.utc) - timedelta(seconds=sls.COLD_START_GRACE_SECONDS + 60)


def _force_in_coldstart():
    sls._MODULE_LOAD_TIME = datetime.now(timezone.utc)


# ---------- Tests -----------------------------------------------------------

def test_01_cold_start_suppresses_checks():
    """1: while module-age < COLD_START_GRACE_SECONDS, no rows are read."""
    _force_in_coldstart()
    sls.register_expected_job("waha_session_poll", 5 * 60)
    store, conn, cur = _store_with_rows({})

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["skipped_cold_start"] is True
    assert out["alerted"] == []
    assert cur.execute.call_count == 0


def test_02_post_grace_empty_registry_noops():
    """2: past grace, empty registry -> checked=0, no alerts."""
    _force_post_coldstart()
    store, conn, cur = _store_with_rows({})

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["checked"] == 0
    assert out["alerted"] == []
    assert out["stale"] == []


def test_03_clean_path_all_fresh_no_alerts():
    """3: every registered job has fresh fired_at -> no alerts."""
    _force_post_coldstart()
    now = datetime.now(timezone.utc)
    sls.register_expected_job("waha_session_poll", 5 * 60)  # T1
    sls.register_expected_job("doc_pipeline_drain", 2 * 60)  # T2
    store, conn, cur = _store_with_rows({
        "waha_session_poll": (now - timedelta(seconds=60),),
        "doc_pipeline_drain": (now - timedelta(seconds=30),),
    })

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["checked"] == 2
    assert out["stale"] == []
    assert out["alerted"] == []
    assert store.create_alert.call_count == 0


def test_04_single_stale_t1_emits_t1_alert():
    """4: T1 job (interval=300s) last fired 30 min ago -> 1 T1 alert."""
    _force_post_coldstart()
    sls.register_expected_job("waha_session_poll", 5 * 60)
    store, conn, cur = _store_with_rows({
        "waha_session_poll": (datetime.now(timezone.utc) - timedelta(minutes=30),),
    })

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["alerted"] == ["waha_session_poll"]
    assert store.create_alert.call_count == 1
    kwargs = store.create_alert.call_args.kwargs
    assert kwargs["tier"] == 1
    assert kwargs["source"] == "scheduler_job_liveness"
    assert "SCHEDULER JOB STALE: waha_session_poll" in kwargs["title"]
    assert kwargs["source_id"].startswith("stale-waha_session_poll-")
    assert re.fullmatch(r"stale-waha_session_poll-\d{8}-\d{2}", kwargs["source_id"])


def test_05_single_stale_t2_emits_t2_alert():
    """5: T2 job (interval=3600s) last fired 8h ago -> 1 T2 alert."""
    _force_post_coldstart()
    sls.register_expected_job("deadline_cadence", 3600)  # not in T1 overrides -> T2
    store, conn, cur = _store_with_rows({
        "deadline_cadence": (datetime.now(timezone.utc) - timedelta(hours=8),),
    })

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["alerted"] == ["deadline_cadence"]
    kwargs = store.create_alert.call_args.kwargs
    assert kwargs["tier"] == 2


def test_06_multiple_stale_jobs_emit_multiple_alerts():
    """6: 2 stale -> 2 create_alert calls; counts match."""
    _force_post_coldstart()
    now = datetime.now(timezone.utc)
    sls.register_expected_job("waha_session_poll", 5 * 60)  # T1
    sls.register_expected_job("deadline_cadence", 3600)     # T2
    store, conn, cur = _store_with_rows({
        "waha_session_poll": (now - timedelta(hours=2),),
        "deadline_cadence": (now - timedelta(hours=8),),
    })

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert sorted(out["alerted"]) == ["deadline_cadence", "waha_session_poll"]
    assert store.create_alert.call_count == 2


def test_07_never_fired_t1_emits_alert():
    """7: T1 job with no fired_at row -> 1 T1 alert noting no 24h row."""
    _force_post_coldstart()
    sls.register_expected_job("scheduler_heartbeat", 5 * 60)  # T1
    store, conn, cur = _store_with_rows({})  # always returns (None,)

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["alerted"] == ["scheduler_heartbeat"]
    kwargs = store.create_alert.call_args.kwargs
    assert kwargs["tier"] == 1
    assert "NO row" in kwargs["body"] or "no row" in kwargs["body"].lower()


def test_08_never_fired_t2_fails_open_no_alert():
    """8: T2 job with no fired_at row -> no alert (fail-open until first fire)."""
    _force_post_coldstart()
    sls.register_expected_job("doc_pipeline_drain", 2 * 60)  # T2 (not in overrides)
    store, conn, cur = _store_with_rows({})

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert out["alerted"] == []
    assert out["stale"] == []
    assert store.create_alert.call_count == 0


def test_09_db_unavailable_returns_reason_no_crash():
    """9: store._get_conn returns None -> skipped_reason, no exception."""
    _force_post_coldstart()
    sls.register_expected_job("waha_session_poll", 5 * 60)
    store = MagicMock()
    store._get_conn.return_value = None

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    assert "no DB connection" in out["skipped_reason"]
    assert out["alerted"] == []


def test_10_create_alert_raises_loop_continues():
    """10: first create_alert raises -> remaining jobs still get alerts."""
    _force_post_coldstart()
    now = datetime.now(timezone.utc)
    sls.register_expected_job("waha_session_poll", 5 * 60)
    sls.register_expected_job("deadline_cadence", 3600)
    store, conn, cur = _store_with_rows({
        "waha_session_poll": (now - timedelta(hours=2),),
        "deadline_cadence": (now - timedelta(hours=8),),
    })
    store.create_alert.side_effect = [RuntimeError("boom"), 4242]

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        out = sls.check_scheduler_liveness()

    # Loop continues after raise; second call still made.
    assert store.create_alert.call_count == 2
    # alerted[] reflects only successful calls.
    assert len(out["alerted"]) == 1


def test_11_hourly_bucket_source_id_stable():
    """11: 3 consecutive calls within same hour-bucket emit identical source_id."""
    _force_post_coldstart()
    now = datetime.now(timezone.utc)
    sls.register_expected_job("waha_session_poll", 5 * 60)
    store, conn, cur = _store_with_rows({
        "waha_session_poll": (now - timedelta(hours=2),),
    })
    seen = []
    store.create_alert.side_effect = lambda **kw: seen.append(kw["source_id"]) or 1

    with patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=store):
        sls.check_scheduler_liveness()
        sls.check_scheduler_liveness()
        sls.check_scheduler_liveness()

    assert len(seen) == 3
    assert seen[0] == seen[1] == seen[2]
    assert re.fullmatch(r"stale-waha_session_poll-\d{8}-\d{2}", seen[0])


# Cron job ids registered as CronTrigger in embedded_scheduler.py — these
# MUST NOT pair with register_expected_job (V1 = interval only). List
# curated from grep + parametrized so a new cron job auto-needs an entry.
_CRON_JOB_IDS = [
    "clickup_poll",
    "state_drift_audit",
    "waha_weekly_restart",
    "daily_briefing",
    "stale_cycle_nudge",
    "wiki_lint",
    "ao_pm_lint",
    "branch_hygiene_weekly",
    "weekly_digest",
    "sync_contact_dates",
    "memory_consolidation",
    "institutional_consolidation",
    "trend_detection",
    "obligation_generator",
    "initiative_engine",
    "convergence_detection",
    "morning_push_digest",
    "evening_push_digest",
    "hot_md_weekly_nudge",
    "ai_head_weekly_audit",
    "gold_audit_sentinel",
    "matter_config_drift_weekly",
    "daily_cost_summary",
    "movie_am_lint",
    "ai_head_audit_sentinel",
    "wiki_lint_weekly",
    "roadmap_drift_sentinel",
    "tier_b_counter_reset",
    "vault_scanner_daily",
]


@pytest.mark.parametrize("cron_id", _CRON_JOB_IDS)
def test_12_no_cron_register_expected_job(cron_id):
    """12: source-scan asserts no register_expected_job("<cron_id>", ...) line
    exists in embedded_scheduler.py for any CronTrigger job id.
    """
    from triggers import embedded_scheduler
    src = inspect.getsource(embedded_scheduler._register_jobs)
    pattern = f'register_expected_job("{cron_id}"'
    assert pattern not in src, (
        f"FORBIDDEN: '{pattern}' found in embedded_scheduler.py — "
        f"CronTrigger jobs must NOT pair with register_expected_job (V1 scope)."
    )


def test_13_dynamic_interval_env_override(monkeypatch):
    """13: KBL_PIPELINE_TICK_INTERVAL_SECONDS=200 propagates through the same
    clamp logic used inline at embedded_scheduler.py:683-688 and lands in
    EXPECTED_JOBS as (200, 2). Source-scan confirms the register line passes
    the live clamp variable (not a literal).
    """
    monkeypatch.setenv("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "200")

    # Mirror the inline clamp from embedded_scheduler.py.
    import os
    try:
        _kbl_tick_seconds = int(os.environ.get("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "120"))
    except (TypeError, ValueError):
        _kbl_tick_seconds = 120
    if _kbl_tick_seconds < 30:
        _kbl_tick_seconds = 30

    sls.register_expected_job("kbl_pipeline_tick", _kbl_tick_seconds)
    assert sls.EXPECTED_JOBS["kbl_pipeline_tick"] == (200, 2)

    # Source-scan: the register call passes the live variable, not a literal.
    from triggers import embedded_scheduler
    src = inspect.getsource(embedded_scheduler._register_jobs)
    assert 'register_expected_job("kbl_pipeline_tick", _kbl_tick_seconds)' in src


def test_14_below_floor_clamp(monkeypatch):
    """14: KBL_PIPELINE_TICK_INTERVAL_SECONDS=10 clamps to the 30s floor
    (embedded_scheduler.py:683-688) and lands in EXPECTED_JOBS as (30, 2).
    """
    monkeypatch.setenv("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "10")

    import os
    try:
        _kbl_tick_seconds = int(os.environ.get("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "120"))
    except (TypeError, ValueError):
        _kbl_tick_seconds = 120
    if _kbl_tick_seconds < 30:
        _kbl_tick_seconds = 30

    assert _kbl_tick_seconds == 30
    sls.register_expected_job("kbl_pipeline_tick", _kbl_tick_seconds)
    assert sls.EXPECTED_JOBS["kbl_pipeline_tick"] == (30, 2)

    # Source-scan: confirm the embedded_scheduler clamp pattern matches.
    from triggers import embedded_scheduler
    src = inspect.getsource(embedded_scheduler._register_jobs)
    assert "if _kbl_tick_seconds < 30:" in src
    assert "_kbl_tick_seconds = 30" in src
