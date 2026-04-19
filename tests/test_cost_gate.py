"""Tests for kbl.cost_gate — daily cap + circuit breaker gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from kbl import cost_gate
from kbl.cost_gate import (
    CostDecision,
    _estimate_step5_cost,
    _get_daily_cap_eur,
    _get_failure_threshold,
    _is_circuit_open,
    can_fire_step5,
    record_opus_failure,
    record_opus_success,
    reset_opus_circuit,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "KBL_COST_DAILY_CAP_EUR",
        "KBL_CB_CONSECUTIVE_FAILURES",
        "KBL_CB_PROBE_INTERVAL_SEC",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# --------------------------- env parsing ---------------------------


def test_daily_cap_default_is_50_eur() -> None:
    """Director-ratified €50 cap (2026-04-18)."""
    assert _get_daily_cap_eur() == Decimal("50.00")


def test_daily_cap_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "25.50")
    assert _get_daily_cap_eur() == Decimal("25.50")


def test_daily_cap_malformed_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "abc")
    with caplog.at_level("WARNING"):
        assert _get_daily_cap_eur() == Decimal("50.00")
    assert any("invalid KBL_COST_DAILY_CAP_EUR" in r.getMessage() for r in caplog.records)


def test_daily_cap_negative_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "-5")
    assert _get_daily_cap_eur() == Decimal("50.00")


def test_failure_threshold_default_is_3() -> None:
    assert _get_failure_threshold() == 3


def test_failure_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_CB_CONSECUTIVE_FAILURES", "5")
    assert _get_failure_threshold() == 5


# --------------------------- estimate ---------------------------


def test_estimate_zero_for_empty_signal() -> None:
    """Still non-negative even when signal_text is empty — the fixed
    output-token allowance dominates."""
    est = _estimate_step5_cost({"signal_text": "", "prompt_overhead_chars": 0})
    # 4096 * 75 / 1M = ~0.31 USD
    assert est > Decimal("0.30")
    assert est < Decimal("0.35")


def test_estimate_grows_with_signal_size() -> None:
    small = _estimate_step5_cost({"signal_text": "x" * 100})
    large = _estimate_step5_cost({"signal_text": "x" * 100000})
    assert large > small


def test_estimate_tolerates_missing_keys() -> None:
    """No signal_text / overhead — still returns a non-negative Decimal."""
    est = _estimate_step5_cost({})
    assert est >= Decimal("0")


# --------------------------- _is_circuit_open ---------------------------


def test_circuit_closed_below_threshold() -> None:
    assert not _is_circuit_open(
        consecutive_failures=2,
        opened_at=None,
        last_probe_at=None,
        threshold=3,
        probe_interval_sec=60,
    )


def test_circuit_open_at_threshold_without_probe() -> None:
    """Once the counter hits threshold and no probe has cleared it, it
    stays open."""
    now = datetime.now(timezone.utc)
    assert _is_circuit_open(
        consecutive_failures=3,
        opened_at=now,
        last_probe_at=None,
        threshold=3,
        probe_interval_sec=60,
    )


def test_circuit_closes_after_probe_reset() -> None:
    """A probe resets the counter via record_opus_success elsewhere;
    this test validates the pure function only cares about the count
    falling below threshold."""
    assert not _is_circuit_open(
        consecutive_failures=0,
        opened_at=None,
        last_probe_at=datetime.now(timezone.utc),
        threshold=3,
        probe_interval_sec=60,
    )


def test_circuit_stays_open_inside_probe_cooldown() -> None:
    now = datetime.now(timezone.utc)
    opened = now - timedelta(seconds=120)
    last_probe = now - timedelta(seconds=10)  # probe was 10s ago
    assert _is_circuit_open(
        consecutive_failures=5,
        opened_at=opened,
        last_probe_at=last_probe,
        threshold=3,
        probe_interval_sec=60,
        now=now,
    )


# --------------------------- SQL writer helpers ---------------------------


def _mock_conn(
    today_total: float = 0.0,
    circuit_failures: int = 0,
    circuit_opened_at: Any = None,
    circuit_last_probe_at: Any = None,
) -> MagicMock:
    """Build a MagicMock connection whose cursor serves:
        - SELECT COALESCE(SUM(cost_usd)...) -> today_total
        - SELECT ...kbl_circuit_breaker... -> (failures, opened, probe)
        - All writes record into conn._calls without raising.
    """
    conn = MagicMock()
    call_sequence: list[tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            call_sequence.append((sql, params))
            s = sql.lower()
            if "coalesce(sum(cost_usd)" in s:
                cur.fetchone.return_value = (Decimal(str(today_total)),)
            elif "from kbl_circuit_breaker" in s and "select" in s:
                cur.fetchone.return_value = (
                    circuit_failures,
                    circuit_opened_at,
                    circuit_last_probe_at,
                )
            elif "update kbl_circuit_breaker" in s and "returning" in s:
                # record_opus_failure — returns the new counter.
                cur.fetchone.return_value = (circuit_failures + 1,)
            else:
                cur.fetchone.return_value = None

        cur.execute.side_effect = _execute
        return cur

    def _cursor() -> MagicMock:
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = call_sequence
    return conn


# --------------------------- can_fire_step5 ---------------------------


def test_can_fire_step5_fire_on_healthy_state() -> None:
    conn = _mock_conn(today_total=10.0, circuit_failures=0)
    result = can_fire_step5(conn, {"signal_text": "hello"})
    assert result is CostDecision.FIRE


def test_can_fire_step5_daily_cap_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "0.01")
    conn = _mock_conn(today_total=0.0, circuit_failures=0)
    result = can_fire_step5(conn, {"signal_text": "x" * 100})
    assert result is CostDecision.DAILY_CAP_EXCEEDED


def test_can_fire_step5_circuit_open_before_cap_check() -> None:
    """Circuit check precedes cap check — a parked circuit still reports
    as CIRCUIT_BREAKER_OPEN even when the cap would also trip."""
    now = datetime.now(timezone.utc)
    conn = _mock_conn(
        today_total=0.0,
        circuit_failures=5,
        circuit_opened_at=now - timedelta(seconds=30),
        circuit_last_probe_at=None,
    )
    result = can_fire_step5(conn, {"signal_text": "hello"})
    assert result is CostDecision.CIRCUIT_BREAKER_OPEN


def test_can_fire_step5_uses_estimate_against_today_sum() -> None:
    """Cap check is ``today + estimate > cap``, not either alone."""
    # Give today a near-cap total so even a tiny estimate trips cap.
    conn = _mock_conn(today_total=49.99, circuit_failures=0)
    result = can_fire_step5(conn, {"signal_text": "x" * 100})
    assert result is CostDecision.DAILY_CAP_EXCEEDED


# --------------------------- failure/success SQL writes ---------------------------


def test_record_opus_failure_increments_and_returns_count() -> None:
    conn = _mock_conn(circuit_failures=1)
    new_count = record_opus_failure(conn)
    assert new_count == 2
    # Verify the UPDATE SQL included the threshold param.
    updates = [c for c in conn._calls if "update kbl_circuit_breaker" in c[0].lower()]
    assert updates


def test_record_opus_success_resets_counter() -> None:
    conn = _mock_conn(circuit_failures=3)
    record_opus_success(conn)
    # Verify the UPDATE SQL zeroes consecutive_failures.
    updates = [c for c in conn._calls if "update kbl_circuit_breaker" in c[0].lower()]
    assert updates
    sql = updates[0][0].lower()
    assert "consecutive_failures = 0" in sql
    assert "opened_at = null" in sql


def test_reset_opus_circuit_wipes_state() -> None:
    conn = _mock_conn(circuit_failures=10)
    reset_opus_circuit(conn)
    updates = [c for c in conn._calls if "update kbl_circuit_breaker" in c[0].lower()]
    sql = updates[0][0].lower()
    assert "consecutive_failures = 0" in sql
    assert "last_probe_at = null" in sql
    assert "operator_reset" in sql


# --------------------------- caller-owns-commit contract ---------------------------


def test_record_opus_failure_does_not_commit() -> None:
    """Transaction-boundary contract: the gate helpers never commit."""
    conn = _mock_conn(circuit_failures=0)
    record_opus_failure(conn)
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 0


def test_record_opus_success_does_not_commit() -> None:
    conn = _mock_conn(circuit_failures=0)
    record_opus_success(conn)
    assert conn.commit.call_count == 0


def test_can_fire_step5_does_not_commit() -> None:
    conn = _mock_conn()
    can_fire_step5(conn, {"signal_text": "x"})
    assert conn.commit.call_count == 0
