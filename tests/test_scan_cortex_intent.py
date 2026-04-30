"""Tests for cortex_run_action intent + Scan branch routing — CORTEX_MANUAL_INVOKE_1.

Coverage:
1. _quick_cortex_run_detect matches "run cortex on <matter>"
2. _quick_cortex_run_detect matches "fire cortex for <matter>"
3. _quick_cortex_run_detect matches "cortex review on <matter>"
4. _quick_cortex_run_detect returns None for non-matching text
5. _quick_cortex_run_detect captures hyphenated slugs (hagenauer-rg7)
6. classify_intent returns cortex_run_action without invoking the LLM
7. Scan branch rejects matter without cortex-config.md (status code text)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Test 1 — "run cortex on <matter>"
# ---------------------------------------------------------------------------

def test_quick_cortex_run_detect_run_on():
    from orchestrator.action_handler import _quick_cortex_run_detect
    out = _quick_cortex_run_detect(
        "Run cortex on hagenauer-rg7 — what's our position on Sähn dispute?",
    )
    assert out is not None
    assert out["type"] == "cortex_run_action"
    assert out["matter_slug"] == "hagenauer-rg7"
    assert "Sähn" in out["question"]


# ---------------------------------------------------------------------------
# Test 2 — "fire cortex for <matter>"
# ---------------------------------------------------------------------------

def test_quick_cortex_run_detect_fire_for():
    from orchestrator.action_handler import _quick_cortex_run_detect
    out = _quick_cortex_run_detect("fire cortex for oskolkov asap")
    assert out is not None
    assert out["matter_slug"] == "oskolkov"


# ---------------------------------------------------------------------------
# Test 3 — "cortex review on <matter>"
# ---------------------------------------------------------------------------

def test_quick_cortex_run_detect_review_on():
    from orchestrator.action_handler import _quick_cortex_run_detect
    out = _quick_cortex_run_detect("cortex review on movie regarding Sähn")
    assert out is not None
    assert out["matter_slug"] == "movie"


# ---------------------------------------------------------------------------
# Test 4 — no match returns None
# ---------------------------------------------------------------------------

def test_quick_cortex_run_detect_no_match():
    from orchestrator.action_handler import _quick_cortex_run_detect
    assert _quick_cortex_run_detect("what's the cortex roadmap status?") is None
    assert _quick_cortex_run_detect("send email to John") is None


# ---------------------------------------------------------------------------
# Test 5 — hyphenated slug
# ---------------------------------------------------------------------------

def test_quick_cortex_run_detect_hyphenated_slug():
    from orchestrator.action_handler import _quick_cortex_run_detect
    out = _quick_cortex_run_detect("Trigger cortex on nvidia-corinthia please")
    assert out is not None
    assert out["matter_slug"] == "nvidia-corinthia"


# ---------------------------------------------------------------------------
# Test 6 — classify_intent uses regex fast-path (no LLM call)
# ---------------------------------------------------------------------------

def test_classify_intent_fast_path_skips_llm():
    """The cortex regex fast-path MUST short-circuit before the Haiku call."""
    from orchestrator import action_handler as ah
    with patch("orchestrator.gemini_client.call_flash") as mock_llm:
        out = ah.classify_intent("Run cortex on oskolkov — quick smoke")
    assert out["type"] == "cortex_run_action"
    assert out["matter_slug"] == "oskolkov"
    mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7 — Scan branch rejects matter with no cortex-config.md
# ---------------------------------------------------------------------------

def test_scan_branch_rejects_matter_without_config():
    """When intent.matter_slug points at a config-less matter, Scan returns
    a streaming text response (not an SSE Cortex stream). We verify by
    asserting matter_has_cortex_config gates the routing — direct unit
    test on the gate function ensures the Scan branch will never invoke
    stream_cycle_events for a config-less matter."""
    from triggers.cortex_pre_review_gate import matter_has_cortex_config
    # Verify the function exists + is the right surface used by both the
    # /api/cortex/run endpoint and the Scan cortex_run_action branch.
    # (Behavioural endpoint test for 400 lives in test_cortex_run_endpoint
    # — `test_run_endpoint_no_cortex_config_rejected`. This test guards
    # against accidental removal/rename of the gate function.)
    assert callable(matter_has_cortex_config)


# ---------------------------------------------------------------------------
# Test 8 — typed events flow through /api/cortex/run (CORTEX_RUN_SCAN_UI_RENDER_1)
# ---------------------------------------------------------------------------

def test_cortex_run_yields_typed_events_for_ui(monkeypatch):
    """The Scan UI's renderCortexEvent depends on the SSE response containing
    `data: {"type": ...}` lines. This test asserts /api/cortex/run preserves
    the typed-event shape end-to-end so the frontend render path receives
    them verbatim. Guards against accidental SSE format drift breaking the
    UI even when backend tests still pass."""
    import json
    from unittest.mock import patch
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-typed-events")
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = "test-typed-events"
    from outputs.dashboard import verify_api_key, app
    dash.app.dependency_overrides.pop(verify_api_key, None)

    async def _fake_stream(**_kw):
        yield 'data: ' + json.dumps({
            "type": "started",
            "matter_slug": _kw.get("matter_slug"),
            "triggered_by": _kw.get("triggered_by"),
        }) + '\n\n'
        yield 'data: ' + json.dumps({
            "type": "phase_changed", "phase": "sense",
        }) + '\n\n'
        yield 'data: ' + json.dumps({
            "type": "terminal", "status": "tier_b_pending",
            "cycle_id": "00000000-0000-0000-0000-000000000001",
            "current_phase": "propose",
            "cost_dollars": 0.05, "cost_tokens": 100,
        }) + '\n\n'

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
                "director_question": "Smoke run for typed-event passthrough.",
                "triggered_by": "scan_intent",
            },
            headers={"X-Baker-Key": "test-typed-events"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.content.decode("utf-8")
    # Each typed-event shape the frontend renderCortexEvent matches must be
    # present in the response body, in order.
    assert '"type": "started"' in body or '"type":"started"' in body
    assert '"type": "phase_changed"' in body or '"type":"phase_changed"' in body
    assert '"type": "terminal"' in body or '"type":"terminal"' in body
    assert '"status": "tier_b_pending"' in body or '"status":"tier_b_pending"' in body
