"""GROK_4_5_WEEK_TRIAL_1 — weekly reservation ledger tests.

Pure-unit coverage for the week/lock helpers + config; live-PG coverage
(auto-skips without TEST_DATABASE_URL / NEON creds) for the reserve/settle/
release/sweep accounting, the weekly cap hard-block, and the advisory-lock
budget identity. Each live test uses a UNIQUE past week so rows never collide
across tests in a shared DB.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator import xai_week_ledger as ledger


# ─────────────────────────── pure unit ───────────────────────────

def test_week_start_is_monday():
    # 2026-07-14 is a Tuesday → Monday is 2026-07-13.
    assert ledger.week_start(date(2026, 7, 14)) == date(2026, 7, 13)
    # A Monday maps to itself.
    assert ledger.week_start(date(2026, 7, 13)) == date(2026, 7, 13)
    # A Sunday maps back to the same week's Monday.
    assert ledger.week_start(date(2026, 7, 19)) == date(2026, 7, 13)


def test_lock_key_unique_per_week_and_int32():
    k1 = ledger._lock_key(date(2026, 7, 13))
    k2 = ledger._lock_key(date(2026, 7, 20))
    assert k1 != k2
    assert 0 < k1 < 2**31  # int4-safe for pg_advisory_xact_lock(int, int)


def test_reserve_rejects_nonpositive_amount():
    out = ledger.reserve("b4_runtime", 0.0, "ref", conn="unused")
    assert out["granted"] is False
    assert out["reason"] == "invalid_amount"


# ─────────────────────────── live-PG ───────────────────────────

@pytest.fixture
def pg_conn(needs_live_pg):
    import psycopg2
    conn = psycopg2.connect(needs_live_pg)
    ledger.ensure_xai_week_ledger_tables(conn)
    yield conn
    try:
        conn.close()
    except Exception:
        pass


def _uniq_week(offset_weeks: int) -> date:
    # Deterministic distinct past Mondays, far from any real trial week.
    base = date(2001, 1, 1)  # a Monday
    return base + timedelta(weeks=offset_weeks)


def test_reserve_settle_releases_residual(pg_conn):
    week = _uniq_week(10)
    ref = uuid.uuid4().hex
    r = ledger.reserve("b4_runtime", 1.00, ref, week=week, conn=pg_conn)
    assert r["granted"] is True
    # effective_used should now reflect the full reservation.
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b["open_reserves_usd"] == pytest.approx(1.00)
    assert b["effective_used_usd"] == pytest.approx(1.00)

    # Settle a smaller actual → residual returns to the pool.
    s = ledger.settle(ref, 0.30, "b4_runtime", week=week, conn=pg_conn)
    assert s["settled"] is True
    assert s["released_residual_usd"] == pytest.approx(0.70)

    b2 = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b2["settled_usd"] == pytest.approx(0.30)
    assert b2["open_reserves_usd"] == pytest.approx(0.0)
    assert b2["effective_used_usd"] == pytest.approx(0.30)


def test_settle_actual_exceeds_reserve_tops_up(pg_conn):
    # P1-1: actual spend > reservation must post the excess to the cap, not drop it.
    week = _uniq_week(20)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 1.00, ref, week=week, conn=pg_conn)
    s = ledger.settle(ref, 1.50, "b4_runtime", week=week, conn=pg_conn)  # actual > reserved
    assert s["settled"] is True
    assert s["topup_usd"] == pytest.approx(0.50)
    assert s["released_residual_usd"] == pytest.approx(0.0)
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b["settled_usd"] == pytest.approx(1.50)
    assert b["open_reserves_usd"] == pytest.approx(0.0)
    # The full actual spend (incl. the excess over the reservation) hits the cap.
    assert b["effective_used_usd"] == pytest.approx(1.50)


def test_cap_counts_overspend_on_next_reserve(pg_conn, monkeypatch):
    # After an over-settle, the next reserve sees the true (higher) usage.
    week = _uniq_week(21)
    monkeypatch.setattr(ledger, "WEEKLY_CAP_USD", 2.0)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 1.0, ref, week=week, conn=pg_conn)
    ledger.settle(ref, 1.8, "b4_runtime", week=week, conn=pg_conn)  # overspend to 1.8
    # remaining = 2.0 - 1.8 = 0.2; a 0.5 reserve must be blocked.
    r = ledger.reserve("b4_runtime", 0.5, uuid.uuid4().hex, week=week, conn=pg_conn)
    assert r["granted"] is False
    assert r["reason"] == "weekly_cap_reached"


def test_settle_is_idempotent_on_retry(pg_conn):
    # P1-4: a settle whose ack is lost after commit gets retried. The retry must be
    # a no-op — no second settle/top-up row, no double cap burn.
    week = _uniq_week(22)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 1.00, ref, week=week, conn=pg_conn)
    s1 = ledger.settle(ref, 0.40, "b4_runtime", week=week, conn=pg_conn)
    assert s1["settled"] is True
    assert not s1.get("idempotent")
    b1 = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b1["settled_usd"] == pytest.approx(0.40)
    assert b1["effective_used_usd"] == pytest.approx(0.40)

    # Simulate the lost-ack retry: same ref, same actual.
    s2 = ledger.settle(ref, 0.40, "b4_runtime", week=week, conn=pg_conn)
    assert s2["settled"] is True
    assert s2.get("idempotent") is True
    assert s2["reason"] == "already_settled"

    # Even a retry with a DIFFERENT actual must not re-settle.
    s3 = ledger.settle(ref, 0.99, "b4_runtime", week=week, conn=pg_conn)
    assert s3.get("idempotent") is True

    b2 = ledger.remaining_budget(week=week, conn=pg_conn)
    # Unchanged from the first settle — no double count.
    assert b2["settled_usd"] == pytest.approx(0.40)
    assert b2["effective_used_usd"] == pytest.approx(0.40)
    # Exactly one settle row exists for this ref.
    cur = pg_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM xai_week_ledger WHERE request_ref=%s AND kind='settle'",
                (ref,))
    assert cur.fetchone()[0] == 1
    cur.close()


def test_settle_unique_index_blocks_raw_double_settle(pg_conn):
    # P1-4 DB-level guard: a direct second settle INSERT (bypassing _has_settle)
    # is rejected by the partial unique index.
    import psycopg2
    week = _uniq_week(23)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 1.00, ref, week=week, conn=pg_conn)
    ledger.settle(ref, 0.50, "b4_runtime", week=week, conn=pg_conn)
    cur = pg_conn.cursor()
    with pytest.raises(psycopg2.IntegrityError):
        cur.execute(
            "INSERT INTO xai_week_ledger (week_start, route, kind, amount_usd, request_ref) "
            "VALUES (%s,'b4_runtime','settle',%s,%s)", (week, 0.10, ref))
    pg_conn.rollback()
    cur.close()


def test_release_frees_full_hold(pg_conn):
    week = _uniq_week(11)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 2.50, ref, week=week, conn=pg_conn)
    rel = ledger.release(ref, "b4_runtime", reason="call_failed", week=week, conn=pg_conn)
    assert rel["released"] is True
    assert rel["released_usd"] == pytest.approx(2.50)
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b["effective_used_usd"] == pytest.approx(0.0)


def test_weekly_cap_hard_block(pg_conn, monkeypatch):
    week = _uniq_week(12)
    monkeypatch.setattr(ledger, "WEEKLY_CAP_USD", 10.0)
    # Reserve up to the cap.
    r1 = ledger.reserve("b4_runtime", 9.0, uuid.uuid4().hex, week=week, conn=pg_conn)
    assert r1["granted"] is True
    # This would push effective_used to 12 > 10 → hard block, no row written.
    r2 = ledger.reserve("b4_runtime", 3.0, uuid.uuid4().hex, week=week, conn=pg_conn)
    assert r2["granted"] is False
    assert r2["reason"] == "weekly_cap_reached"
    # A reservation that fits exactly is still granted.
    r3 = ledger.reserve("b4_runtime", 1.0, uuid.uuid4().hex, week=week, conn=pg_conn)
    assert r3["granted"] is True
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b["effective_used_usd"] == pytest.approx(10.0)
    assert b["remaining_usd"] == pytest.approx(0.0)


def test_warn_flag_trips(pg_conn, monkeypatch):
    week = _uniq_week(13)
    monkeypatch.setattr(ledger, "WEEKLY_CAP_USD", 10.0)
    monkeypatch.setattr(ledger, "WEEKLY_WARN_USD", 8.0)
    r = ledger.reserve("b4_runtime", 8.5, uuid.uuid4().hex, week=week, conn=pg_conn)
    assert r["granted"] is True
    assert r["over_warn"] is True


def test_sweep_releases_stale_reserve(pg_conn):
    week = _uniq_week(14)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 4.0, ref, week=week, conn=pg_conn)
    # Backdate the reserve row so it is older than the TTL.
    cur = pg_conn.cursor()
    cur.execute(
        "UPDATE xai_week_ledger SET created_at = NOW() - INTERVAL '2 hours' "
        "WHERE request_ref = %s AND kind = 'reserve'", (ref,))
    pg_conn.commit()
    cur.close()

    swept = ledger.sweep_stale_reserves(ttl_min=30, conn=pg_conn)
    assert swept["swept"] >= 1
    assert swept["released_usd"] >= 4.0 - 1e-9
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    # The stale hold for this week is released.
    assert b["open_reserves_usd"] == pytest.approx(0.0)


def test_sweep_ignores_settled_reserve(pg_conn):
    week = _uniq_week(15)
    ref = uuid.uuid4().hex
    ledger.reserve("b4_runtime", 4.0, ref, week=week, conn=pg_conn)
    ledger.settle(ref, 4.0, "b4_runtime", week=week, conn=pg_conn)
    cur = pg_conn.cursor()
    cur.execute(
        "UPDATE xai_week_ledger SET created_at = NOW() - INTERVAL '2 hours' "
        "WHERE request_ref = %s", (ref,))
    pg_conn.commit()
    cur.close()
    swept = ledger.sweep_stale_reserves(ttl_min=30, conn=pg_conn)
    # This ref already settled → must NOT be swept again (no double release).
    b = ledger.remaining_budget(week=week, conn=pg_conn)
    assert b["settled_usd"] == pytest.approx(4.0)
    assert b["effective_used_usd"] == pytest.approx(4.0)
