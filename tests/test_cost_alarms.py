"""Tests for orchestrator/cost_monitor.py tiered-alarm + matter-attribution
behavior (BAKER-COST-INSTRUMENTATION-1).

Coverage:
  - COST_TIERS list shape + COST_ALERT_EUR backwards-compat alias
  - log_api_cost() signature accepts matter_slug + persists it to api_cost_log
  - check_circuit_breaker() walks tiers in ascending order, fires one Slack
    message per (date, tier) pair, hard-stop unchanged
  - DB-backed tier idempotence via cost_alert_state (process restart does
    not re-fire today's alarms)
  - BAKER_COST_ALARMS_ENABLED=false suppresses tier alarms but NOT hard stop
  - post_daily_cost_summary() shape + idempotence + suppression

These tests mock out the global SentinelStoreBack singleton so they run
without a live database.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import cost_monitor


# --------------------------- mock conn harness ---------------------------


class _Cursor:
    def __init__(self, claim_results):
        self.queries: list[tuple] = []
        self.claim_results = list(claim_results)
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        s = sql.lower().strip()
        if "insert into cost_alert_state" in s:
            self.rowcount = 1 if (self.claim_results and self.claim_results.pop(0)) else 0
        else:
            self.rowcount = 0

    def close(self):
        pass


class _Conn:
    def __init__(self, claim_results=None):
        self._cursor = _Cursor(claim_results or [])
        self.committed = 0
        self.rolled_back = 0

    def cursor(self, *a, **kw):
        return self._cursor

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _Store:
    def __init__(self, conn):
        self.conn = conn

    def _get_conn(self):
        return self.conn

    def _put_conn(self, _conn):
        return None


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test gets a clean in-process state for the hard-stop guard."""
    cost_monitor._hard_stop_sent_date = None
    yield
    cost_monitor._hard_stop_sent_date = None


# --------------------------- COST_TIERS shape ---------------------------


def test_cost_tiers_ascending() -> None:
    """Tiers are walked in ascending order; brief design-decision #1."""
    thresholds = [t[0] for t in cost_monitor.COST_TIERS]
    assert thresholds == sorted(thresholds), "COST_TIERS must be sorted ascending"
    labels = [t[1] for t in cost_monitor.COST_TIERS]
    assert labels == ["info", "warn", "critical"]


def test_cost_alert_eur_alias_points_at_info_tier() -> None:
    """A2: COST_ALERT_EUR alias kept and points at COST_TIERS[0][0]."""
    assert cost_monitor.COST_ALERT_EUR == cost_monitor.COST_TIERS[0][0]


# --------------------------- log_api_cost signature ---------------------------


def test_log_api_cost_accepts_matter_slug_kwarg() -> None:
    """A3: matter_slug is a kwarg on log_api_cost."""
    conn = _Conn()
    store = _Store(conn)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        cost_eur = cost_monitor.log_api_cost(
            model="gemini-2.5-flash",
            input_tokens=100,
            output_tokens=200,
            source="test",
            matter_slug="oskolkov",
        )
    assert cost_eur is not None
    assert cost_eur >= 0
    insert_calls = [q for q, _ in conn._cursor.queries if "insert into api_cost_log" in q.lower()]
    assert insert_calls, "expected an INSERT into api_cost_log"
    # Last bound param is matter_slug.
    _sql, params = next(
        (q, p) for q, p in conn._cursor.queries if "insert into api_cost_log" in q.lower()
    )
    assert params[-1] == "oskolkov"


def test_log_api_cost_matter_slug_defaults_to_none() -> None:
    """Pass-through None for callers that don't have a slug in scope."""
    conn = _Conn()
    store = _Store(conn)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        cost_monitor.log_api_cost(
            model="gemini-2.5-flash",
            input_tokens=10,
            output_tokens=20,
            source="pipeline",
        )
    _sql, params = next(
        (q, p) for q, p in conn._cursor.queries if "insert into api_cost_log" in q.lower()
    )
    assert params[-1] is None


# --------------------------- _claim_tier_alert ---------------------------


def test_claim_tier_alert_returns_true_first_time() -> None:
    conn = _Conn(claim_results=[True])
    store = _Store(conn)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        ok = cost_monitor._claim_tier_alert(date(2026, 5, 5), "warn")
    assert ok is True


def test_claim_tier_alert_returns_false_on_conflict() -> None:
    """Second claim of same (date, tier_label) hits ON CONFLICT DO NOTHING."""
    conn = _Conn(claim_results=[False])
    store = _Store(conn)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=store):
        ok = cost_monitor._claim_tier_alert(date(2026, 5, 5), "warn")
    assert ok is False


def test_claim_tier_alert_degrades_open_on_db_failure() -> None:
    """If the DB is unreachable, return True so the alarm still fires."""
    with patch(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        side_effect=Exception("db offline"),
    ):
        ok = cost_monitor._claim_tier_alert(date(2026, 5, 5), "info")
    assert ok is True


# --------------------------- check_circuit_breaker ---------------------------


def test_check_circuit_breaker_fires_each_tier_once_idempotent() -> None:
    """A4: tiered alarms fire idempotently per (date, tier)."""
    sent: list[tuple[float, str]] = []

    def _fake_send(daily_cost, threshold, label, emoji):
        sent.append((threshold, label))

    # Each tier claim succeeds the first time and fails the second time.
    claim_state = {("info"): [True, False], ("warn"): [True, False],
                   ("critical"): [True, False]}

    def _fake_claim(_d, label):
        return claim_state[label].pop(0)

    with patch.object(cost_monitor, "get_daily_cost", return_value=120.0), \
            patch.object(cost_monitor, "_send_tiered_alarm", _fake_send), \
            patch.object(cost_monitor, "_send_hard_stop_alert", lambda _c: None), \
            patch.object(cost_monitor, "_claim_tier_alert", _fake_claim), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", True):
        # First call — all three tiers fire (claim_state True for each).
        allowed, _ = cost_monitor.check_circuit_breaker()
        # Second call — claims now return False; nothing new sent.
        allowed2, _ = cost_monitor.check_circuit_breaker()

    assert {label for _t, label in sent} == {"info", "warn", "critical"}
    assert len(sent) == 3, "exactly one Slack message per tier on first crossing"
    # Hard stop blocks at 120 >= 100 default — both calls return False.
    assert allowed is False
    assert allowed2 is False


def test_check_circuit_breaker_walks_tiers_only_for_crossed_thresholds() -> None:
    """At €45, only the info tier fires (warn=60, critical=100 not crossed)."""
    sent: list[str] = []

    def _fake_send(daily_cost, threshold, label, emoji):
        sent.append(label)

    with patch.object(cost_monitor, "get_daily_cost", return_value=45.0), \
            patch.object(cost_monitor, "_send_tiered_alarm", _fake_send), \
            patch.object(cost_monitor, "_send_hard_stop_alert", lambda _c: None), \
            patch.object(cost_monitor, "_claim_tier_alert", lambda *_a: True), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", True):
        allowed, daily = cost_monitor.check_circuit_breaker()

    assert sent == ["info"]
    assert allowed is True
    assert daily == 45.0


def test_alarms_disabled_suppresses_tiers_but_not_hard_stop() -> None:
    """A5: BAKER_COST_ALARMS_ENABLED=false → no tier alarms; hard stop still blocks."""
    tier_sent: list[str] = []
    hard_sent: list[float] = []

    with patch.object(cost_monitor, "get_daily_cost", return_value=200.0), \
            patch.object(cost_monitor, "_send_tiered_alarm",
                         lambda *a: tier_sent.append(a[2])), \
            patch.object(cost_monitor, "_send_hard_stop_alert",
                         lambda c: hard_sent.append(c)), \
            patch.object(cost_monitor, "_claim_tier_alert", lambda *_a: True), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", False):
        allowed, _ = cost_monitor.check_circuit_breaker()

    assert tier_sent == [], "tier alarms suppressed"
    assert hard_sent == [200.0], "hard stop fires regardless"
    assert allowed is False


def test_hard_stop_unchanged_below_threshold_allows() -> None:
    """A9: existing hard-stop logic preserved bit-for-bit at 99.99 < 100."""
    with patch.object(cost_monitor, "get_daily_cost", return_value=99.99), \
            patch.object(cost_monitor, "_send_tiered_alarm", lambda *a: None), \
            patch.object(cost_monitor, "_send_hard_stop_alert", lambda c: None), \
            patch.object(cost_monitor, "_claim_tier_alert", lambda *_a: True), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", True):
        allowed, daily = cost_monitor.check_circuit_breaker()
    assert allowed is True
    assert daily == 99.99


def test_hard_stop_in_process_dedup_within_same_day() -> None:
    """Hard stop alert sent once per process per UTC day."""
    sent: list[float] = []

    with patch.object(cost_monitor, "get_daily_cost", return_value=150.0), \
            patch.object(cost_monitor, "_send_tiered_alarm", lambda *a: None), \
            patch.object(cost_monitor, "_send_hard_stop_alert",
                         lambda c: sent.append(c)), \
            patch.object(cost_monitor, "_claim_tier_alert", lambda *_a: True), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", True):
        cost_monitor.check_circuit_breaker()
        cost_monitor.check_circuit_breaker()
        cost_monitor.check_circuit_breaker()

    assert len(sent) == 1


# --------------------------- post_daily_cost_summary ---------------------------


def test_post_daily_cost_summary_returns_breakdown_when_disabled() -> None:
    """Suppressed when alarms disabled, but caller still gets the dict."""
    fake = {"date": "2026-05-05", "total_eur": 12.0, "call_count": 3,
            "by_source": {"capability_runner": {"cost": 12.0, "calls": 3}},
            "by_matter": {}, "by_model": {}}
    claim = MagicMock(return_value=True)
    with patch.object(cost_monitor, "get_daily_breakdown", return_value=fake), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", False), \
            patch.object(cost_monitor, "_claim_tier_alert", claim):
        result = cost_monitor.post_daily_cost_summary(date(2026, 5, 5))
    assert result == fake
    claim.assert_not_called()


def test_post_daily_cost_summary_idempotent_per_day() -> None:
    """A6: scheduler retry on the same day must not double-post."""
    fake = {"date": "2026-05-05", "total_eur": 1.0, "call_count": 1,
            "by_source": {}, "by_matter": {}, "by_model": {}}
    posts: list[str] = []

    def _fake_post(*_args, **kwargs):
        posts.append(kwargs.get("json", {}).get("text", ""))
        return MagicMock(status_code=200)

    # First call — claim succeeds. Second call — claim fails (already today).
    claims = iter([True, False])

    with patch.object(cost_monitor, "get_daily_breakdown", return_value=fake), \
            patch.object(cost_monitor, "COST_ALARMS_ENABLED", True), \
            patch.object(cost_monitor, "_claim_tier_alert",
                         lambda *_a: next(claims)), \
            patch("os.getenv", return_value="xoxb-test"), \
            patch("requests.post", side_effect=_fake_post):
        cost_monitor.post_daily_cost_summary(date(2026, 5, 5))
        cost_monitor.post_daily_cost_summary(date(2026, 5, 5))

    assert len(posts) == 1, "second invocation must be a no-op"
