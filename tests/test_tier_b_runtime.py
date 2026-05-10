"""Live-PG tests for ``orchestrator/tier_b_runtime.py``.

Coverage:
    * cost resolve (registry hit / novel:* + self_cost / unknown class)
    * enforce verdict matrix:
        - PASS under caps
        - per_action_cap (€>100)
        - daily_cap (pool-wide)
        - monthly_cap (pool-wide)
    * pool-wide isolation between agents (AH1 spend visible to B3 enforce)
    * pending_id round-trip on PAUSE_REQUIRED

Gated on ``needs_live_pg`` — auto-skips when neither ``TEST_DATABASE_URL``
nor ``NEON_API_KEY`` + ``NEON_PROJECT_ID`` are set.
"""
from __future__ import annotations

import pytest

from orchestrator.tier_b_runtime import (
    DAILY_POOL_CAP_EUR,
    MONTHLY_POOL_CAP_EUR,
    PER_ACTION_CAP_EUR,
    Decision,
    TierBAction,
    enforce_tier_b,
)


def test_cap_constants_match_d8_ratification():
    """Smoke check that the Director-ratified D8 caps are intact."""
    assert PER_ACTION_CAP_EUR == 100.00
    assert DAILY_POOL_CAP_EUR == 500.00
    assert MONTHLY_POOL_CAP_EUR == 2500.00


def test_pass_under_caps(clean_baker_actions, register_class):
    register_class("test.synthetic", 1.00)
    action = TierBAction(
        action_class="test.synthetic",
        committer_agent="b3",
        payload={"smoke": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.cost_eur == 1.00
    assert decision.pending_id is None
    assert decision.reservation_id is not None
    assert isinstance(decision.reservation_id, int)


def test_per_action_cap_paused(clean_baker_actions, register_class):
    register_class("test.expensive_one_shot", 150.00)
    action = TierBAction(
        action_class="test.expensive_one_shot",
        committer_agent="b3",
        payload={"over_per_action": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "per_action_cap" in decision.reason
    assert decision.pending_id is not None
    assert decision.cost_eur == 150.00


def test_daily_cap_paused(
    clean_baker_actions,
    register_class,
    seed_committed_today,
):
    """5 × €99.80 prior committed today + a €5 candidate ⇒ daily PAUSE."""
    register_class("test.med", 99.80)
    register_class("test.five", 5.00)
    seed_committed_today(class_name="test.med", count=5, agent="ah1", eur_cost=99.80)
    # 5 × 99.80 = €499 committed; new €5 ⇒ €504 ⇒ exceeds €500 daily cap.
    action = TierBAction(
        action_class="test.five",
        committer_agent="b3",
        payload={"daily_break": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in decision.reason


def test_monthly_cap_paused(
    clean_baker_actions,
    register_class,
    seed_committed_this_month,
):
    """25 × €99.80 prior this-month + €10 candidate ⇒ monthly PAUSE."""
    # Push the prior into early-this-month so day-cap doesn't trip first.
    register_class("test.med", 99.80)
    register_class("test.ten", 10.00)
    seed_committed_this_month(
        class_name="test.med", count=25, agent="ah1", eur_cost=99.80,
    )
    action = TierBAction(
        action_class="test.ten",
        committer_agent="b3",
        payload={"monthly_break": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "monthly_cap" in decision.reason


def test_novel_class_requires_self_cost(clean_baker_actions):
    action = TierBAction(
        action_class="novel:custom_render_addon",
        committer_agent="b3",
        payload={},
        # self_cost_eur intentionally omitted
    )
    with pytest.raises(ValueError, match="requires self_cost_eur"):
        enforce_tier_b(action)


def test_novel_class_negative_self_cost_rejected(clean_baker_actions):
    # Brief said "no @requires_pg needed — exits before any DB call." That's
    # true of _resolve_cost's negative-check branch itself, but enforce_tier_b
    # init triggers SentinelStoreBack._get_global_instance() which demands
    # Voyage creds without the test-store patch. Use clean_baker_actions to
    # match the sibling test_novel_class_requires_self_cost pattern; the
    # ValueError still fires inside _resolve_cost, before any cap math runs.
    action = TierBAction(
        action_class="novel:cap_evasion_attempt",
        committer_agent="b3",
        payload={"test": "negative_cost"},
        self_cost_eur=-50.0,
    )
    with pytest.raises(ValueError, match="non-negative"):
        enforce_tier_b(action)


def test_novel_class_with_self_cost_passes(clean_baker_actions):
    action = TierBAction(
        action_class="novel:custom_render_addon",
        committer_agent="b3",
        payload={"adhoc": True},
        self_cost_eur=42.00,
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.cost_eur == 42.00
    assert decision.reservation_id is not None
    assert isinstance(decision.reservation_id, int)


def test_unknown_registry_class_raises(clean_baker_actions):
    action = TierBAction(
        action_class="render.does.not.exist",
        committer_agent="b3",
        payload={},
    )
    with pytest.raises(ValueError, match="unknown action_class"):
        enforce_tier_b(action)


def test_pool_wide_isolation_between_agents(
    clean_baker_actions,
    register_class,
    seed_committed_today,
):
    """Pool-wide: AH1 spends €499 today; B3 trying €5 must PAUSE."""
    register_class("test.med", 99.80)
    register_class("test.five", 5.00)
    seed_committed_today(
        class_name="test.med", count=5, agent="ah1", eur_cost=99.80,
    )
    action = TierBAction(
        action_class="test.five",
        committer_agent="b3",
        payload={},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in decision.reason


def test_pending_row_persisted_on_pause(
    clean_baker_actions,
    register_class,
    tier_b_test_store,
):
    register_class("test.too_big", 200.00)
    action = TierBAction(
        action_class="test.too_big",
        committer_agent="b3",
        payload={"trace_id": "abc-123"},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert decision.pending_id is not None

    # Verify the pending row exists with expected shape.
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT cost_eur, action_class, committer_agent, reason_paused, status "
            "FROM tier_b_pending WHERE id = %s",
            (decision.pending_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert row is not None
    cost, klass, agent, reason, status = row
    assert float(cost) == 200.00
    assert klass == "test.too_big"
    assert agent == "b3"
    assert reason == "per_action_cap"
    assert status == "pending"
