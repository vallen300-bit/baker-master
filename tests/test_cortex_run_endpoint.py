"""Tests for POST /api/cortex/run — CORTEX_MANUAL_INVOKE_1.

Coverage:
1. Auth: missing X-Baker-Key → 401, no stream / no cycle invoked
2. Validation: short director_question → 422
3. Whitelist: matter without cortex-config.md → 400
4. Rate limit: 6th call in same hour → 429
5. Cost-warn: ≥30 specialist invocations triggers Slack post; run still proceeds (200)
6. Happy path: 200 + text/event-stream + at least 1 SSE chunk emitted
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


def _set_api_key(monkeypatch, key="test-key-123"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = key
    # Defensive: clear any leftover dependency_override from a prior test
    # (test_cortex_action_endpoint.py:62 globally bypasses verify_api_key
    # via app.dependency_overrides and never cleans up). Without this,
    # the unauthorized test below would see verify_api_key as a no-op and
    # return 200 instead of 401.
    from outputs.dashboard import verify_api_key
    dash.app.dependency_overrides.pop(verify_api_key, None)


# ---------------------------------------------------------------------------
# Test 1 — missing X-Baker-Key → 401
# ---------------------------------------------------------------------------

def test_run_endpoint_unauthorized(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.post(
        "/api/cortex/run",
        json={
            "matter_slug": "oskolkov",
            "director_question": "Smoke run on cortex stream — long enough.",
            "triggered_by": "director_manual",
        },
        # NO X-Baker-Key
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Test 2 — short director_question → 422
# ---------------------------------------------------------------------------

def test_run_endpoint_validation_short_question(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.post(
        "/api/cortex/run",
        json={
            "matter_slug": "oskolkov",
            "director_question": "tooshort",  # <10
            "triggered_by": "director_manual",
        },
        headers={"X-Baker-Key": "test-key-123"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Test 3 — matter without cortex-config.md → 400
# ---------------------------------------------------------------------------

def test_run_endpoint_no_cortex_config_rejected(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    with patch(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        return_value=False,
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json={
                "matter_slug": "kitzbuhel-six-senses",
                "director_question": "Should fail — no config exists.",
                "triggered_by": "director_manual",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
    assert resp.status_code == 400, resp.text
    assert "not Cortex-enabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 4 — rate limit: 6th call in last hour → 429
# ---------------------------------------------------------------------------

def test_run_endpoint_rate_limited_at_cap(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    with patch(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        return_value=True,
    ), patch(
        "outputs.cortex_run_stream.runs_in_last_hour", return_value=5,
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json={
                "matter_slug": "oskolkov",
                "director_question": "6th call should hit the cap",
                "triggered_by": "director_manual",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )
    assert resp.status_code == 429, resp.text
    assert "Rate limit" in resp.json()["detail"]
    assert "cap=5" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 5 — cost-warn ≥ 30 specialists/24h → Slack post + 200
# ---------------------------------------------------------------------------

def test_run_endpoint_cost_warn_posts_slack_and_runs(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    async def _fake_stream(**_kw):
        yield 'data: {"type":"started"}\n\n'
        yield 'data: {"type":"terminal","status":"proposed"}\n\n'

    mock_post = MagicMock(return_value=True)

    with patch(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        return_value=True,
    ), patch(
        "outputs.cortex_run_stream.runs_in_last_hour", return_value=0,
    ), patch(
        "outputs.cortex_run_stream.specialist_calls_today", return_value=42,
    ), patch(
        "outputs.cortex_run_stream.stream_cycle_events", _fake_stream,
    ), patch(
        "outputs.slack_notifier.post_to_channel", mock_post,
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json={
                "matter_slug": "oskolkov",
                "director_question": "Run despite cost-warn — should still 200",
                "triggered_by": "director_manual",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    # Slack DM fired exactly once
    assert mock_post.call_count == 1
    # Stream content delivered
    assert b"started" in resp.content
    assert b"terminal" in resp.content


# ---------------------------------------------------------------------------
# Test 6 — happy path: 200 + SSE content-type + at least one chunk
# ---------------------------------------------------------------------------

def test_run_endpoint_happy_path_streams(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    async def _fake_stream(**_kw):
        yield 'data: {"type":"started"}\n\n'
        yield 'data: {"type":"phase_changed","phase":"sense"}\n\n'
        yield 'data: {"type":"terminal","status":"proposed"}\n\n'

    with patch(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        return_value=True,
    ), patch(
        "outputs.cortex_run_stream.runs_in_last_hour", return_value=0,
    ), patch(
        "outputs.cortex_run_stream.specialist_calls_today", return_value=0,
    ), patch(
        "outputs.cortex_run_stream.stream_cycle_events", _fake_stream,
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json={
                "matter_slug": "oskolkov",
                "director_question": "Smoke run — confirm SSE pass-through works.",
                "triggered_by": "director_manual",
            },
            headers={"X-Baker-Key": "test-key-123"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.content.decode("utf-8")
    assert "started" in body
    assert "phase_changed" in body
    assert "terminal" in body


# ---------------------------------------------------------------------------
# CORTEX_NOTIFICATION_DEFER_1 — gate matrix (defer_invoke × defer_matter)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "defer_invoke,defer_matter,expect_slack_post",
    [
        (False, False, True),   # default — DM fires
        (True,  False, False),  # per-invoke suppresses
        (False, True,  False),  # per-matter suppresses
        (True,  True,  False),  # both suppress (no double-fire)
    ],
)
def test_cortex_run_cost_warn_defer_matrix(
    monkeypatch, defer_invoke, defer_matter, expect_slack_post,
):
    """CORTEX_NOTIFICATION_DEFER_1: cost-warn Slack DM gated on
    (per-invoke OR per-matter) defer flags. Logger always fires."""
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    async def _fake_stream(**_kw):
        yield 'data: {"type":"started"}\n\n'
        yield 'data: {"type":"terminal","status":"proposed"}\n\n'

    mock_post = MagicMock(return_value=True)

    with patch(
        "triggers.cortex_pre_review_gate.matter_has_cortex_config",
        return_value=True,
    ), patch(
        "outputs.cortex_run_stream.runs_in_last_hour", return_value=0,
    ), patch(
        "outputs.cortex_run_stream.specialist_calls_today", return_value=42,
    ), patch(
        "outputs.cortex_run_stream.stream_cycle_events", _fake_stream,
    ), patch(
        "triggers.cortex_pre_review_gate.matter_notification_deferred",
        return_value=defer_matter,
    ), patch(
        "outputs.slack_notifier.post_to_channel", mock_post,
    ):
        body = {
            "matter_slug": "oskolkov",
            "director_question": "defer-matrix smoke test — long enough.",
            "triggered_by": "director_manual",
        }
        if defer_invoke:
            body["defer_notification"] = True
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json=body,
            headers={"X-Baker-Key": "test-key-123"},
        )

    assert resp.status_code == 200, resp.text
    expected_calls = 1 if expect_slack_post else 0
    assert mock_post.call_count == expected_calls, (
        f"defer_invoke={defer_invoke} defer_matter={defer_matter}: "
        f"expected slack_post calls={expected_calls}, got {mock_post.call_count}"
    )
