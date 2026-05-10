"""Live-PG integration test for ``GET /api/admin/tier-b-status``.

Coverage:
    * 200 + JSON shape (caps, current totals, headroom, pending, recent)
    * caps reflect Director-ratified D8 constants (€100 / €500 / €2500)
    * pending list surfaces a paused row
    * recent_committed list surfaces a committed row
    * auth required (no key → 401/403)
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


_TEST_API_KEY = "tier-b-test-key"


@pytest.fixture
def client(tier_b_test_store, monkeypatch):
    """FastAPI TestClient bound to ``outputs.dashboard.app``.

    Forces ``_BAKER_API_KEY`` to a known test value so ``verify_api_key``
    enforces (401/403) rather than returning 503 "API disabled". The
    module-level constant is captured at import time, so monkeypatching the
    env alone is insufficient — we also patch the captured value.
    """
    monkeypatch.setenv("BAKER_API_KEY", _TEST_API_KEY)
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", _TEST_API_KEY, raising=False)
    return TestClient(dashboard.app)


def _api_key() -> str:
    return _TEST_API_KEY


def test_tier_b_status_shape(clean_baker_actions, client):
    resp = client.get(
        "/api/admin/tier-b-status",
        headers={"X-Baker-Key": _api_key()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "caps" in body
    assert body["caps"]["per_action_eur"] == 100.00
    assert body["caps"]["daily_pool_eur"] == 500.00
    assert body["caps"]["monthly_pool_eur"] == 2500.00

    assert "current" in body
    cur = body["current"]
    for k in (
        "day_total_eur",
        "month_total_eur",
        "day_remaining_eur",
        "month_remaining_eur",
    ):
        assert k in cur, f"missing {k} in current"

    assert isinstance(body["pending"], list)
    assert isinstance(body["recent_committed"], list)
    # On a fresh truncate the lists are empty.
    assert body["pending"] == []
    assert body["recent_committed"] == []


def test_tier_b_status_surfaces_pending_and_recent(
    clean_baker_actions,
    register_class,
    seed_committed_today,
    client,
):
    """Seed one committed + one pending row; both must show in the response."""
    register_class("test.synthetic", 1.00)
    register_class("test.too_big", 200.00)
    seed_committed_today(
        class_name="test.synthetic", count=1, agent="ah1", eur_cost=1.00,
    )

    # Trigger a PAUSE_REQUIRED so a tier_b_pending row exists.
    from orchestrator.tier_b_runtime import TierBAction, enforce_tier_b

    decision = enforce_tier_b(
        TierBAction(
            action_class="test.too_big",
            committer_agent="b3",
            payload={"surface": True},
        )
    )
    assert decision.verdict == "PAUSE_REQUIRED"

    resp = client.get(
        "/api/admin/tier-b-status",
        headers={"X-Baker-Key": _api_key()},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["pending"]) == 1
    pending_row = body["pending"][0]
    assert pending_row["action_class"] == "test.too_big"
    assert pending_row["reason_paused"] == "per_action_cap"
    assert pending_row["committer_agent"] == "b3"

    assert len(body["recent_committed"]) == 1
    recent_row = body["recent_committed"][0]
    assert recent_row["action_class"] == "test.synthetic"
    assert recent_row["committer_agent"] == "ah1"

    # Day/month totals reflect the €1 committed row.
    assert body["current"]["day_total_eur"] == 1.00
    assert body["current"]["month_total_eur"] == 1.00
    assert body["current"]["day_remaining_eur"] == 499.00
    assert body["current"]["month_remaining_eur"] == 2499.00


def test_tier_b_status_requires_api_key(client):
    """No / wrong key ⇒ unauthorized (401/403)."""
    resp = client.get("/api/admin/tier-b-status")
    assert resp.status_code in (401, 403)
