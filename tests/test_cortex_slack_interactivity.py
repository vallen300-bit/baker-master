"""Tests for CORTEX_SLACK_INTERACTIVITY_1.

Brief: briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md

Coverage:
1. test_happy_path_approve     — valid sig + valid payload → 200, cortex_approve scheduled
2. test_reject_path            — action_id=cortex_reject → cortex_reject scheduled
3. test_bad_signature          → 403, NO handler invoked
4. test_stale_timestamp        → 403 (>5min skew)
5. test_missing_payload_field  → 400
6. test_unknown_action         → 400, NO handler invoked
7. test_no_cycle_id            → 400, NO handler invoked
8. test_gold_select_checkbox_noop → 200 no-op (no handler call, no response_url update)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from unittest.mock import AsyncMock, patch

# Set the secret env BEFORE importing modules — config.slack.signing_secret is
# read at config-instance creation. We also force it onto the loaded singleton.
os.environ["SLACK_SIGNING_SECRET"] = "test_slack_secret_8675309"

from config.settings import config as _cfg  # noqa: E402
_cfg.slack.signing_secret = "test_slack_secret_8675309"

from fastapi.testclient import TestClient  # noqa: E402

from outputs.dashboard import app  # noqa: E402


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


SECRET = "test_slack_secret_8675309"


def _sign(body: bytes, ts: str, secret: str = SECRET) -> str:
    """Compute the Slack v0 signature header value for (ts, body)."""
    base = f"v0:{ts}:{body.decode('utf-8')}"
    return "v0=" + hmac.new(
        secret.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _payload_form(
    action_id: str,
    *,
    cycle_id: str = "cyc-1",
    proposal_id: str = "prop-1",
    value_override: str | None = None,
) -> bytes:
    """Build a form-encoded Slack interactivity body."""
    if value_override is not None:
        value = value_override
    else:
        value = json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id})
    payload = {
        "type": "block_actions",
        "user": {"id": "U1", "name": "vallen300"},
        "channel": {"id": "D0AFY28N030"},
        "message": {
            "ts": "1.001",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": "Proposal"}},
                {"type": "actions", "block_id": "cortex_actions_x", "elements": []},
            ],
        },
        "response_url": "https://hooks.slack.com/x",
        "actions": [
            {
                "action_id": action_id,
                "block_id": "cortex_actions_x",
                "value": value,
                "type": "button",
            }
        ],
    }
    return urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()


# --------------------------------------------------------------------------
# Test 1 — happy path approve
# --------------------------------------------------------------------------


def test_happy_path_approve():
    """Valid sig + valid payload + action_id=cortex_approve →
    200 + cortex_approve scheduled in BackgroundTask."""
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "triggers.slack_interactivity._post_response_update",
    ), patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 200, resp.text

    # FastAPI's TestClient drives BackgroundTasks to completion after the
    # response is generated; the patched handler MUST have been awaited.
    h.assert_awaited_once()


# --------------------------------------------------------------------------
# Test 2 — reject path
# --------------------------------------------------------------------------


def test_reject_path():
    """action_id=cortex_reject → cortex_reject is the handler scheduled."""
    body = _payload_form("cortex_reject")
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "triggers.slack_interactivity._post_response_update",
    ), patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as approve_h, patch(
        "orchestrator.cortex_phase5_act.cortex_reject",
        new=AsyncMock(return_value={"ok": True}),
    ) as reject_h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 200, resp.text

    reject_h.assert_awaited_once()
    approve_h.assert_not_awaited()


# --------------------------------------------------------------------------
# Test 3 — bad signature → 403, NO handler scheduled
# --------------------------------------------------------------------------


def test_bad_signature():
    """Forged signature → 403, no Phase 5 handler invoked, no
    response_url update fired."""
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()))
    bad_sig = "v0=" + "0" * 64

    with patch(
        "triggers.slack_interactivity._post_response_update",
    ) as resp_update, patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": bad_sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 403, resp.text

    h.assert_not_awaited()
    resp_update.assert_not_called()


# --------------------------------------------------------------------------
# Test 4 — stale timestamp → 403 (>5min replay window)
# --------------------------------------------------------------------------


def test_stale_timestamp():
    """Timestamp older than 5 minutes → 403 (replay protection)."""
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()) - 1000)  # 1000s in the past
    sig = _sign(body, ts)

    with patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 403, resp.text

    h.assert_not_awaited()


# --------------------------------------------------------------------------
# Test 5 — missing 'payload' field in form body → 400
# --------------------------------------------------------------------------


def test_missing_payload_field():
    """Form body without a 'payload=' field → 400."""
    body = b"foo=bar"  # signed correctly but missing payload field
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 400, resp.text

    h.assert_not_awaited()


# --------------------------------------------------------------------------
# Test 6 — unknown action_id → 400, no handler scheduled
# --------------------------------------------------------------------------


def test_unknown_action():
    """action_id not in {approve,edit,refresh,reject,gold_select_*} → 400."""
    body = _payload_form("cortex_unknown_thing")
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 400, resp.text

    h.assert_not_awaited()


# --------------------------------------------------------------------------
# Test 7 — missing cycle_id in value JSON → 400
# --------------------------------------------------------------------------


def test_no_cycle_id():
    """Button value JSON without cycle_id → 400 (no handler scheduled)."""
    body = _payload_form("cortex_approve", value_override="{}")
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 400, resp.text

    h.assert_not_awaited()


# --------------------------------------------------------------------------
# Test 8 — gold-select checkbox is a no-op (200, no handler call)
# --------------------------------------------------------------------------


def test_gold_select_checkbox_noop():
    """action_id=cortex_gold_select_<id> → 200 immediately, no handler call."""
    body = _payload_form("cortex_gold_select_xyz", value_override="checked")
    ts = str(int(time.time()))
    sig = _sign(body, ts)

    with patch(
        "triggers.slack_interactivity._post_response_update",
    ) as resp_update, patch(
        "orchestrator.cortex_phase5_act.cortex_approve",
        new=AsyncMock(return_value={"ok": True}),
    ) as approve_h, patch(
        "orchestrator.cortex_phase5_act.cortex_edit",
        new=AsyncMock(return_value={"ok": True}),
    ) as edit_h, patch(
        "orchestrator.cortex_phase5_act.cortex_refresh",
        new=AsyncMock(return_value={"ok": True}),
    ) as refresh_h, patch(
        "orchestrator.cortex_phase5_act.cortex_reject",
        new=AsyncMock(return_value={"ok": True}),
    ) as reject_h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 200, resp.text

    # No Phase 5 handler called for the no-op checkbox path.
    approve_h.assert_not_awaited()
    edit_h.assert_not_awaited()
    refresh_h.assert_not_awaited()
    reject_h.assert_not_awaited()
    # No response_url update fired for the no-op (returns immediately).
    resp_update.assert_not_called()
