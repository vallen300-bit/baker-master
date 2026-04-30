"""classify_triaga_outcome tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.4.

Pure-Python — no DB.
"""
from __future__ import annotations

from datetime import timedelta

from orchestrator.cortex_phase6_reflector import (
    TRIAGA_TTL_DAYS,
    classify_triaga_outcome,
)


def test_gold_approved_helpful():
    assert classify_triaga_outcome("gold_approved", timedelta(days=1)) == "helpful"


def test_gold_modified_helpful():
    assert classify_triaga_outcome("gold_modified", timedelta(days=1)) == "helpful"


def test_gold_rejected_harmful():
    assert classify_triaga_outcome("gold_rejected", timedelta(days=1)) == "harmful"


def test_refresh_requested_pending():
    """refresh_requested = re-run, not a final outcome."""
    assert (
        classify_triaga_outcome("refresh_requested", timedelta(days=1)) == "pending"
    )


def test_aged_no_action_stale():
    """director_action=None + age >= TTL -> stale."""
    assert (
        classify_triaga_outcome(None, timedelta(days=TRIAGA_TTL_DAYS + 1))
        == "stale"
    )


def test_recent_no_action_pending():
    assert classify_triaga_outcome(None, timedelta(days=1)) == "pending"


def test_unknown_value_pending_default():
    """Defensive: unknown director_action value -> 'pending'.

    Per brief §7 risks: 'director_action semantics drift (e.g., new value
    added like gold_approved_with_changes) -> classify returns pending
    (default branch) — safe non-action'.
    """
    assert (
        classify_triaga_outcome("gold_approved_with_changes", timedelta(days=1))
        == "pending"
    )


def test_aged_unknown_value_still_pending_not_stale():
    """Unknown value beats TTL: stale only fires when director_action is None."""
    assert (
        classify_triaga_outcome("gold_approved_with_changes", timedelta(days=99))
        == "pending"
    )


def test_aged_exactly_at_ttl_boundary():
    """age == TTL_DAYS exactly should classify as stale (>= boundary)."""
    assert (
        classify_triaga_outcome(None, timedelta(days=TRIAGA_TTL_DAYS))
        == "stale"
    )
