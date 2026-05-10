"""Live-PG tests for ``triggers/tier_b_reset.tier_b_counter_reset``.

Coverage:
    * audit row written with prior calendar-month label
    * actions_count + final_month_total reflect last-month committed rows
    * fresh DB (no prior-month activity) still writes a row with zero totals
"""
from __future__ import annotations

from datetime import datetime, timezone


def _expected_period_label(now_utc: datetime) -> str:
    if now_utc.month == 1:
        prev_year, prev_month = now_utc.year - 1, 12
    else:
        prev_year, prev_month = now_utc.year, now_utc.month - 1
    return f"{prev_year:04d}-{prev_month:02d}"


def test_reset_writes_audit_row_when_idle(
    clean_baker_actions,
    tier_b_test_store,
):
    """No prior-month activity → audit row with zero totals."""
    from triggers.tier_b_reset import tier_b_counter_reset

    tier_b_counter_reset()

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT period_label, final_month_total, actions_count "
            "FROM tier_b_counter_resets ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)

    assert row is not None, "tier_b_counter_resets row not written"
    period_label, final_month_total, actions_count = row
    assert period_label == _expected_period_label(datetime.now(timezone.utc))
    assert float(final_month_total) == 0.0
    assert int(actions_count) == 0


def test_reset_captures_last_month_totals(
    clean_baker_actions,
    register_class,
    seed_committed_last_month,
    tier_b_test_store,
):
    """Seed a single €123.45 row in prior month; reset should capture it."""
    from triggers.tier_b_reset import tier_b_counter_reset

    register_class("test.synthetic", 1.00)
    seed_committed_last_month(
        class_name="test.synthetic", total_eur=123.45, agent="ah1",
    )
    tier_b_counter_reset()

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT period_label, final_month_total, actions_count "
            "FROM tier_b_counter_resets ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)

    assert row is not None
    period_label, final_month_total, actions_count = row
    assert period_label == _expected_period_label(datetime.now(timezone.utc))
    assert float(final_month_total) == 123.45
    assert int(actions_count) == 1
