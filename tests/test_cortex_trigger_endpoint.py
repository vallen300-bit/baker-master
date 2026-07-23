"""Tests for POST /api/cortex/trigger — CORTEX_TRIGGER_ENDPOINT_1.

Brief: briefs/BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md

Coverage:
1. Happy path — valid X-Baker-Key + valid body → 200 with cycle dict
2. 401 — missing/wrong X-Baker-Key
3. 422 — Pydantic validation rejects director_question < 10 chars
4. 504 — asyncio.TimeoutError translates to HTTP 504
"""
import asyncio
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from outputs.dashboard import app


class _FakeCycle:
    """Mirror of CortexCycle dataclass fields read by the endpoint."""

    def __init__(self):
        self.cycle_id = "test-cycle-001"
        self.matter_slug = "oskolkov"
        self.triggered_by = "test"
        self.status = "tier_b_pending"
        self.current_phase = "propose"
        self.cost_tokens = 12345
        self.cost_dollars = 0.42
        self.aborted_reason = None


def test_trigger_cortex_cycle_happy_path(monkeypatch):
    """Happy path — valid key + valid body → 200 + cycle JSON; mock invoked once.

    CORTEX_RETIRE_PHASE1_1: this is now the flag-OFF (rollback) variant — the
    endpoint only reaches maybe_run_cycle when CORTEX_RETIRED=false.
    """
    monkeypatch.setenv("CORTEX_RETIRED", "false")
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    # _BAKER_API_KEY is bound at module import; rebind for this test.
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    fake_cycle = _FakeCycle()
    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=fake_cycle),
    ) as m:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "What is AO's actual intention by getting in touch with Siegfried?",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cycle_id"] == "test-cycle-001"
        assert body["matter_slug"] == "oskolkov"
        assert body["triggered_by"] == "test"
        assert body["status"] == "tier_b_pending"
        assert body["current_phase"] == "propose"
        assert body["cost_tokens"] == 12345
        assert body["cost_dollars"] == 0.42
        assert body["aborted_reason"] is None
        m.assert_awaited_once()


def test_trigger_cortex_cycle_unauthorized(monkeypatch):
    """Wrong X-Baker-Key → 401, maybe_run_cycle MUST NOT be invoked."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=_FakeCycle()),
    ) as m:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "test question content here long enough",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "wrong-key"},
        )
        assert resp.status_code == 401, resp.text
        # Auth runs before body parsing — cycle invoker MUST NOT execute.
        m.assert_not_awaited()


def test_trigger_cortex_cycle_validation_short_question(monkeypatch):
    """director_question < 10 chars → 422 from Pydantic, no cycle invoked."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=_FakeCycle()),
    ) as m:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "tooshort",  # 8 chars < 10
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
        assert resp.status_code == 422, resp.text
        # Validation rejects before handler body — cycle invoker MUST NOT execute.
        m.assert_not_awaited()


def test_trigger_cortex_cycle_timeout_translates_to_504(monkeypatch):
    """maybe_run_cycle raising asyncio.TimeoutError → HTTP 504.

    CORTEX_RETIRE_PHASE1_1: flag-OFF (rollback) variant — reaches the runner
    only when CORTEX_RETIRED=false.
    """
    monkeypatch.setenv("CORTEX_RETIRED", "false")
    monkeypatch.setenv("BAKER_API_KEY", "test-key-123")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-key-123"

    async def _raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("outputs.dashboard.maybe_run_cycle", new=_raise_timeout):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "valid length question content here",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
        assert resp.status_code == 504, resp.text
        body = resp.json()
        assert "timeout" in body["detail"].lower() or "exceeded" in body["detail"].lower()
