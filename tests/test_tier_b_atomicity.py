"""Live-PG tests for Pattern B atomicity closure.

The headline test is ``test_concurrent_enforcers_one_passes_one_pauses``
— the precursor's hard acceptance criterion. Two enforcers at €495
day-total racing on a €5 candidate: exactly one PASSes, one PAUSEs.

Coverage:
    * PASS path writes a reservation row (committed_at IS NULL,
      reserved_at IS NOT NULL) inside SERIALIZABLE
    * confirm flips committed_at and is idempotent on second call
    * cancel deletes the reservation row and is idempotent
    * sweep removes expired orphans + leaves fresh reservations alone
    * concurrent-load atomicity (THE ship-gate)
"""
from __future__ import annotations

import threading

from orchestrator.tier_b_runtime import (
    RESERVATION_TTL_MINUTES,
    Decision,
    TierBAction,
    cancel_tier_b,
    confirm_tier_b,
    enforce_tier_b,
)


# ----------------------------------------------------------------------
# Reservation row shape
# ----------------------------------------------------------------------


def test_pass_writes_reservation_row(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    action = TierBAction(
        action_class="test.synthetic",
        committer_agent="b3",
        payload={"reservation_shape": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.reservation_id is not None

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tier, cost_eur, committed_at, reserved_at, "
            "       committer_agent, action_class "
            "FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert row is not None
    tier, cost, committed_at, reserved_at, agent, klass = row
    assert tier == "B"
    assert float(cost) == 1.00
    assert committed_at is None
    assert reserved_at is not None
    assert agent == "b3"
    assert klass == "test.synthetic"


# ----------------------------------------------------------------------
# confirm / cancel lifecycle
# ----------------------------------------------------------------------


def test_confirm_marks_committed(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert decision.verdict == "PASS"
    assert confirm_tier_b(decision.reservation_id) is True

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT committed_at FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        (committed_at,) = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert committed_at is not None

    # Idempotent — second confirm returns False (already committed).
    assert confirm_tier_b(decision.reservation_id) is False


def test_cancel_removes_reservation(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert decision.verdict == "PASS"
    assert cancel_tier_b(decision.reservation_id) is True

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert row is None  # reservation deleted

    # Idempotent — second cancel returns False (row gone).
    assert cancel_tier_b(decision.reservation_id) is False


def test_cancel_after_confirm_is_noop(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Cancel after the action committed should NOT delete the row."""
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    confirm_tier_b(decision.reservation_id)
    assert cancel_tier_b(decision.reservation_id) is False

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT committed_at FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        (committed_at,) = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert committed_at is not None  # row still committed, intact


# ----------------------------------------------------------------------
# Reservation counts toward cap (TTL window)
# ----------------------------------------------------------------------


def test_reservation_counts_toward_cap_within_ttl(
    clean_baker_actions, register_class,
):
    """Reservation alone (no confirm) blocks a 2nd PASS that would breach cap."""
    register_class("test.big_one", 99.00)
    # First call reserves €99 (no confirm).
    first = enforce_tier_b(TierBAction(
        action_class="test.big_one", committer_agent="ah1", payload={},
    ))
    assert first.verdict == "PASS"

    # Stack reservations until just under €500. 5 × €99 = €495 reserved.
    for _ in range(4):
        d = enforce_tier_b(TierBAction(
            action_class="test.big_one", committer_agent="ah1", payload={},
        ))
        assert d.verdict == "PASS"

    # Sixth call (would push to €594 reserved) → daily cap PAUSE.
    sixth = enforce_tier_b(TierBAction(
        action_class="test.big_one", committer_agent="b3", payload={},
    ))
    assert sixth.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in sixth.reason


# ----------------------------------------------------------------------
# THE ship-gate: concurrent enforcers at €495 day-total + €5 candidate
# ----------------------------------------------------------------------


def test_concurrent_enforcers_one_passes_one_pauses(
    clean_baker_actions, register_class, seed_committed_today,
):
    """Hard acceptance criterion (B4_PRECURSOR §3.3).

    Seed €495 day-total. Two enforcers race a €5 candidate.

      • First-to-commit reaches €500 day-total (at cap, NOT over → PASS).
        Reservation row makes the second enforcer's cap-read see €500.
      • Second-to-commit sees €500 + €5 = €505 > €500 → PAUSE_REQUIRED.

    Pre-Pattern-B failure mode: both enforcers SELECT €495, both eval
    PASS (€500 not > €500), both commit, pool over-spends to €505.
    Pattern B fix: PASS path INSERTs reservation inside SERIALIZABLE; SSI
    rw-conflict on the second commit raises SerializationFailure; retry
    sees the now-€500 reserved total and PAUSEs.

    Seed math: 5 × €99 = €495 committed today. The seed helper takes an
    explicit ``eur_cost`` argument that is written directly onto each
    seeded ``baker_actions`` row — it does NOT consult the registered
    price for ``class_name``, so reusing ``test.synthetic`` here (whose
    registered price is €1) is harmless: the helper writes €99/row. The
    candidate ``test.five`` (€5) is what actually races through
    ``enforce_tier_b()``, and IS resolved via the registry.
    """
    register_class("test.five", 5.00)
    # Seed €495 already committed today: 5 × €99.
    seed_committed_today(
        class_name="test.synthetic", count=5, agent="ah1", eur_cost=99.00,
    )

    decisions: list[Decision] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2, timeout=10)

    def _race(committer: str) -> None:
        action = TierBAction(
            action_class="test.five",
            committer_agent=committer,
            payload={"committer": committer},
        )
        try:
            # Wait for both threads at the barrier so the SELECTs race.
            barrier.wait()
            # Retry up to 3 times on SerializationFailure — Postgres SSI
            # surfaces it as a deferrable error; caller is expected to
            # retry. Each retry runs a fresh enforce() with fresh reads.
            for _attempt in range(3):
                try:
                    decisions.append(enforce_tier_b(action))
                    return
                except Exception as e:
                    if "could not serialize" in str(e).lower() or (
                        e.__class__.__name__ == "SerializationFailure"
                    ):
                        continue
                    raise
            raise RuntimeError("3 SerializationFailure retries exhausted")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=_race, args=("ah1",))
    t2 = threading.Thread(target=_race, args=("b3",))
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"unexpected errors: {errors}"
    assert len(decisions) == 2, f"expected 2 decisions, got {decisions}"

    verdicts = sorted(d.verdict for d in decisions)
    assert verdicts == ["PASS", "PAUSE_REQUIRED"], (
        f"Pattern B atomicity failure: both threads got {verdicts} at "
        f"€495 seeded day-total. Race winner reserves €5 (→ €500 at cap, "
        f"PASS). Loser must see the €500 reserved total and PAUSE. If both "
        f"got PASS, SSI failed to detect the rw-conflict — the brief's "
        f"atomicity argument is invalidated; revert and re-design."
    )

    # The PAUSE should cite daily_cap.
    paused = next(d for d in decisions if d.verdict == "PAUSE_REQUIRED")
    assert "daily_cap" in paused.reason


# ----------------------------------------------------------------------
# Sweep job
# ----------------------------------------------------------------------


def test_sweep_deletes_expired_orphans(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Sweep removes reservations with reserved_at past TTL."""
    register_class("test.synthetic", 1.00)
    fresh = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert fresh.verdict == "PASS"

    # Manually age a 2nd reservation past TTL by direct SQL.
    expired_id = _seed_reserved(
        tier_b_test_store,
        cost_eur=1.00,
        agent="ah1",
        reserved_at_offset_minutes=-(RESERVATION_TTL_MINUTES + 1),
    )

    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    deleted = tier_b_reservation_sweep()
    assert deleted == 1  # only the expired one

    # Fresh reservation untouched.
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (fresh.reservation_id,),
        )
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (expired_id,),
        )
        assert cur.fetchone() is None
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)


def test_sweep_leaves_committed_alone(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Sweep MUST NOT touch committed rows even if they're old."""
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    confirm_tier_b(decision.reservation_id)

    # Age the reserved_at past TTL (committed_at is set so it's a no-op
    # target for sweep, but we want to prove it).
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE baker_actions "
            "   SET reserved_at = NOW() AT TIME ZONE 'UTC' - INTERVAL '1 hour' "
            " WHERE id = %s",
            (decision.reservation_id,),
        )
        conn.commit()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)

    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    deleted = tier_b_reservation_sweep()
    assert deleted == 0

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (decision.reservation_id,),
        )
        assert cur.fetchone() is not None
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _seed_reserved(
    store, *, cost_eur: float, agent: str, reserved_at_offset_minutes: int,
) -> int:
    """Insert a reservation row at a specific reserved_at offset.

    Used to seed expired/orphan reservations for sweep tests.
    """
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, payload, trigger_source, success,
                 tier, cost_eur, committed_at, reserved_at,
                 committer_agent, action_class)
            VALUES (
                'tier_b_reservation', '{}'::jsonb, 'test_seed', TRUE,
                'B', %s, NULL,
                (NOW() AT TIME ZONE 'UTC') + (%s || ' minutes')::interval,
                %s, 'test.synthetic'
            )
            RETURNING id
            """,
            (cost_eur, str(reserved_at_offset_minutes), agent),
        )
        new_id = int(cur.fetchone()[0])
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
    return new_id
