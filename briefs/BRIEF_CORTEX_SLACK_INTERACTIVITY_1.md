# BRIEF: CORTEX_SLACK_INTERACTIVITY_1 — Wire the 4 proposal-card buttons

## Context

Cortex V1 is LIVE on AO matter. Proposal cards land in Director's Slack DM with 4 buttons: ✅ Approve / ✏️ Edit / 🔄 Refresh / ❌ Reject. **Buttons are visible but inert.** No Slack interactivity endpoint exists; tapping does nothing.

Phase 5 action handlers ALREADY EXIST in `orchestrator/cortex_phase5_act.py`:
- `cortex_approve(cycle_id, body)` — freshness check → execute structured_actions → write Gold via `gold_proposer.propose` → propagate staged curated → archive
- `cortex_edit(cycle_id, body)` — save edited proposal text; cycle stays tier_b_pending
- `cortex_refresh(cycle_id, body)` — re-run Phase 2 + Phase 3; replace card in place
- `cortex_reject(cycle_id, body)` — archive status='rejected' + feedback_ledger
All have idempotency CAS guard (`_cas_lock_cycle` in same file).

This brief WIRES those handlers behind a Slack interactivity endpoint.

## Estimated time: ~3-4h
## Complexity: Medium
## Trigger class: HIGH

This PR ships:
- New external HTTP endpoint receiving Slack payloads
- New auth surface (Slack request signature HMAC verification)
- Calls handlers that write Gold + execute structured_actions

→ B1 situational review REQUIRED per RA-24 (external API + auth + writes affect Gold/matter state). Builder ≠ B1.

**Build assignment:** B2. **Review assignment:** B1 (formal) + AI Head A (/security-review + structural).

## Slack payload reference

When Director taps a button, Slack POSTs `application/x-www-form-urlencoded` with one field:
```
payload=<JSON>
```
The JSON looks like:
```json
{
  "type": "block_actions",
  "user": {"id": "U0AFJLAP1BR", "name": "vallen300"},
  "channel": {"id": "D0AFY28N030"},
  "message": {"ts": "1745891234.001", "blocks": [...]},
  "response_url": "https://hooks.slack.com/actions/T.../...",
  "actions": [
    {
      "action_id": "cortex_approve",
      "block_id": "cortex_actions_<proposal_id>",
      "value": "{\"cycle_id\":\"7dc3201b-...\",\"proposal_id\":\"17e38f4d-...\"}",
      "type": "button"
    }
  ]
}
```

`value` is JSON-encoded — contains `cycle_id` + `proposal_id`. Parse it. Hand `cycle_id` + the full payload (as `body`) to the matching Phase 5 handler.

Slack expects HTTP 200 within **3 seconds** or it retries (and possibly shows error to user). Handlers do real work (LLM, DB, SSH). → Use `BackgroundTasks` to schedule the handler async; respond 200 immediately.

## Implementation

### File 1: NEW `triggers/slack_interactivity.py` (~220 LOC)

```python
"""CORTEX_SLACK_INTERACTIVITY_1: handle Director's button taps on proposal cards.

Endpoint: POST /webhook/slack/interactive
Auth: Slack request signature HMAC-SHA256 (SLACK_SIGNING_SECRET) — same
pattern as triggers/slack_events.py:_verify_signature.

Payload: application/x-www-form-urlencoded with single field 'payload' = JSON.
The JSON's actions[0].action_id selects the handler:
    cortex_approve   → orchestrator.cortex_phase5_act.cortex_approve
    cortex_edit      → orchestrator.cortex_phase5_act.cortex_edit
    cortex_refresh   → orchestrator.cortex_phase5_act.cortex_refresh
    cortex_reject    → orchestrator.cortex_phase5_act.cortex_reject
    cortex_gold_select_<id> → no-op (checkbox state captured downstream)

Slack 3s budget: handlers run as BackgroundTasks. Endpoint responds 200
immediately with an ephemeral 'Processing…' update via response_url.

Idempotency: handlers themselves use _cas_lock_cycle (existing). Double-tap
is harmless — second call sees status already-advanced + bails 200.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from config.settings import config

logger = logging.getLogger("sentinel.slack_interactivity")

router = APIRouter()


# --------------------------------------------------------------------------
# Signature verification (mirrors triggers/slack_events.py:_verify_signature)
# --------------------------------------------------------------------------


def _verify_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature. Returns True if valid."""
    secret = config.slack.signing_secret
    if not secret:
        # Fail CLOSED on the interactivity surface — handlers write Gold +
        # execute structured_actions. Different policy than the event
        # webhook (which fails open for polling-only setups).
        logger.error("SLACK_SIGNING_SECRET not set — refusing interactivity payload")
        return False

    try:
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("Slack interactivity rejected: timestamp too old")
            return False
    except (ValueError, TypeError):
        return False

    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


# --------------------------------------------------------------------------
# response_url update helper
# --------------------------------------------------------------------------


def _post_response_update(response_url: str, body: dict) -> None:
    """POST a JSON payload to Slack's response_url to update the original card.

    Per Slack docs response_url accepts up to 5 invocations within 30 min.
    Body shapes used here:
      {"replace_original": true, "blocks": [...new blocks with footer...]}
      {"replace_original": false, "text": "Processing…", "response_type": "ephemeral"}
    """
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            response_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as e:
        logger.warning(f"response_url POST failed: {e}")


def _decision_footer_blocks(action_id: str, user_name: str, status_msg: str) -> list[dict]:
    """Footer block appended after action — replaces the original 4-button row."""
    label = {
        "cortex_approve": "✅ Approved",
        "cortex_edit": "✏️ Edited",
        "cortex_refresh": "🔄 Refreshed",
        "cortex_reject": "❌ Rejected",
    }.get(action_id, action_id)
    return [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*{label}* by <@{user_name}> at <!date^{int(time.time())}^{{date_short_pretty}} {{time}}|{int(time.time())}>",
                }
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": status_msg}],
        },
    ]


# --------------------------------------------------------------------------
# Handler dispatch — runs in BackgroundTask
# --------------------------------------------------------------------------


_HANDLER_MAP: dict[str, str] = {
    "cortex_approve": "cortex_approve",
    "cortex_edit":    "cortex_edit",
    "cortex_refresh": "cortex_refresh",
    "cortex_reject":  "cortex_reject",
}


async def _run_handler(*, action_id: str, cycle_id: str, payload: dict, response_url: str) -> None:
    """BackgroundTask: invoke the matching cortex_phase5_act handler, then
    update the Slack message in place via response_url.

    Wrapped in try/except — Slack timeout already returned 200; we must not
    raise. Errors logged + posted as ephemeral update.
    """
    user_name = (payload.get("user") or {}).get("name", "director")
    try:
        from orchestrator.cortex_phase5_act import (
            cortex_approve, cortex_edit, cortex_refresh, cortex_reject,
        )
        handlers = {
            "cortex_approve": cortex_approve,
            "cortex_edit":    cortex_edit,
            "cortex_refresh": cortex_refresh,
            "cortex_reject":  cortex_reject,
        }
        fn = handlers[action_id]
        result = await fn(cycle_id=cycle_id, body=payload)
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        warning = (result or {}).get("warning") if isinstance(result, dict) else None
        if warning == "already_actioned":
            status_msg = "_(already actioned — idempotent)_"
        elif ok:
            status_msg = "_(handler completed)_"
        else:
            err = (result or {}).get("error", "handler returned not-ok")
            status_msg = f"_(handler error: {err})_"

        # Replace original message with the "decision recorded" footer.
        # Keep the original proposal blocks (above the actions row) so the
        # Director still has the proposal text in his thread for reference.
        original_blocks = ((payload.get("message") or {}).get("blocks") or [])
        new_blocks = [b for b in original_blocks if b.get("block_id", "").startswith("cortex_actions_") is False]
        new_blocks.extend(_decision_footer_blocks(action_id, user_name, status_msg))
        _post_response_update(response_url, {
            "replace_original": True,
            "blocks": new_blocks[:50],
        })
    except KeyError:
        logger.error(f"Unknown action_id in interactivity dispatch: {action_id}")
        _post_response_update(response_url, {
            "replace_original": False,
            "response_type": "ephemeral",
            "text": f"Unknown action: {action_id}",
        })
    except Exception as e:
        logger.error(f"Interactivity handler failed for action_id={action_id} cycle={cycle_id}: {e}")
        _post_response_update(response_url, {
            "replace_original": False,
            "response_type": "ephemeral",
            "text": f"Handler error — see logs. ({type(e).__name__})",
        })


# --------------------------------------------------------------------------
# Endpoint — POST /webhook/slack/interactive (registered under the
# slack_events router include path)
# --------------------------------------------------------------------------


@router.post("/slack/interactive")
async def slack_interactive(request: Request, background_tasks: BackgroundTasks):
    """Receives Director's button taps. Verifies signature, parses payload,
    dispatches handler in background, returns 200 immediately."""
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_signature(body_bytes, timestamp, signature):
        return JSONResponse({"error": "invalid_signature"}, status_code=403)

    # Slack payload arrives as application/x-www-form-urlencoded with
    # field 'payload' = JSON string.
    try:
        form = urllib.parse.parse_qs(body_bytes.decode("utf-8"))
        payload_str = (form.get("payload") or [""])[0]
        if not payload_str:
            return JSONResponse({"error": "no_payload"}, status_code=400)
        payload = json.loads(payload_str)
    except Exception as e:
        logger.warning(f"slack_interactive payload parse failed: {e}")
        return JSONResponse({"error": "bad_payload"}, status_code=400)

    actions = payload.get("actions") or []
    if not actions:
        return JSONResponse({"error": "no_actions"}, status_code=400)

    action = actions[0]
    action_id = str(action.get("action_id") or "")
    response_url = str(payload.get("response_url") or "")

    # Gold-select checkbox: no-op for now (state captured downstream by approve).
    if action_id.startswith("cortex_gold_select_"):
        return JSONResponse({}, status_code=200)

    if action_id not in _HANDLER_MAP:
        logger.warning(f"slack_interactive: unknown action_id={action_id}")
        return JSONResponse({"error": "unknown_action"}, status_code=400)

    # Parse cycle_id from button value (JSON-encoded).
    raw_value = str(action.get("value") or "")
    try:
        value_obj = json.loads(raw_value) if raw_value.startswith("{") else {}
        cycle_id = str(value_obj.get("cycle_id") or "")
    except Exception:
        cycle_id = ""
    if not cycle_id:
        logger.warning(f"slack_interactive: missing cycle_id action_id={action_id} value={raw_value[:80]}")
        return JSONResponse({"error": "no_cycle_id"}, status_code=400)

    # Schedule handler in background — Slack needs 200 within 3s.
    background_tasks.add_task(
        _run_handler,
        action_id=action_id, cycle_id=cycle_id, payload=payload, response_url=response_url,
    )

    # Optimistic ephemeral "Processing…" so Director sees instant feedback.
    if response_url:
        _post_response_update(response_url, {
            "replace_original": False,
            "response_type": "ephemeral",
            "text": f"Processing {action_id}…",
        })

    return JSONResponse({}, status_code=200)
```

### File 2: MODIFY `outputs/dashboard.py`

Register the new router. Find the existing slack_events include (line 140-141):

```python
from triggers.slack_events import router as slack_events_router
app.include_router(slack_events_router, prefix="/webhook")
```

Add immediately after:

```python
from triggers.slack_interactivity import router as slack_interactivity_router
app.include_router(slack_interactivity_router, prefix="/webhook")
```

### File 3: NEW `tests/test_cortex_slack_interactivity.py` (~250 LOC, 8 tests)

Test coverage:
1. **Happy path approve** — valid sig + valid payload → 200 + handler scheduled
2. **Happy path reject** — same shape, action=cortex_reject → 200 + handler scheduled
3. **Bad signature** → 403, NO handler scheduled
4. **Stale timestamp** (>5min old) → 403
5. **Missing payload field** → 400
6. **Unknown action_id** → 400
7. **Missing cycle_id in value JSON** → 400
8. **Gold-select checkbox** → 200 no-op (no handler call)

Use `monkeypatch.setattr` to install fake Slack signing secret + fake handler functions. Use `TestClient` against the FastAPI app. Mock `_post_response_update` to assert it's called with expected shape on success path.

```python
import hashlib, hmac, json, time
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import os

os.environ["SLACK_SIGNING_SECRET"] = "test_slack_secret_8675309"


def _sign(body: bytes, ts: str, secret: str) -> str:
    base = f"v0:{ts}:{body.decode()}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def _payload_form(action_id: str, cycle_id: str = "cyc-1", proposal_id: str = "prop-1") -> bytes:
    payload = {
        "type": "block_actions",
        "user": {"id": "U1", "name": "vallen300"},
        "channel": {"id": "D0AFY28N030"},
        "message": {"ts": "1.001", "blocks": [{"type": "header"}, {"type": "actions", "block_id": "cortex_actions_x"}]},
        "response_url": "https://hooks.slack.com/x",
        "actions": [{
            "action_id": action_id,
            "block_id": "cortex_actions_x",
            "value": json.dumps({"cycle_id": cycle_id, "proposal_id": proposal_id}),
            "type": "button",
        }],
    }
    import urllib.parse
    return urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()


def test_happy_path_approve(monkeypatch):
    from outputs.dashboard import app
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()))
    sig = _sign(body, ts, "test_slack_secret_8675309")
    with patch("triggers.slack_interactivity._post_response_update"), \
         patch("orchestrator.cortex_phase5_act.cortex_approve",
               new=AsyncMock(return_value={"ok": True})) as h:
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
    # BackgroundTask runs after the request; in test client, tasks run synchronously
    h.assert_awaited_once()


def test_bad_signature(monkeypatch):
    from outputs.dashboard import app
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()))
    bad_sig = "v0=" + "0" * 64
    with patch("orchestrator.cortex_phase5_act.cortex_approve",
               new=AsyncMock(return_value={"ok": True})) as h:
        client = TestClient(app)
        resp = client.post(
            "/webhook/slack/interactive",
            content=body,
            headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": bad_sig,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 403
    h.assert_not_awaited()


def test_stale_timestamp():
    from outputs.dashboard import app
    body = _payload_form("cortex_approve")
    ts = str(int(time.time()) - 1000)  # 1000s old
    sig = _sign(body, ts, "test_slack_secret_8675309")
    client = TestClient(app)
    resp = client.post(
        "/webhook/slack/interactive",
        content=body,
        headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403


def test_unknown_action():
    # ... action_id="cortex_unknown" → 400


def test_no_cycle_id():
    # ... value="{}" missing cycle_id → 400


def test_gold_select_checkbox_noop():
    # action_id="cortex_gold_select_xxx" → 200, no handler called


def test_missing_payload_field():
    # body without 'payload=' → 400


def test_reject_path():
    # action_id="cortex_reject" → cortex_reject called
```

(Full test bodies follow same shape as test_happy_path_approve. ~250 LOC total.)

### Key Constraints (DO NOT)

- DO NOT call handlers synchronously — Slack 3s timeout will fire before handler completes; user sees error
- DO NOT skip signature verification — handlers write Gold + execute structured_actions = real-world side effects
- DO NOT log payload contents at info level — proposal text + matter context is sensitive
- DO NOT respond with 200 if signature fails — return 403 explicitly
- DO NOT include the proposal-card body text in HTML/test output (sensitive)
- DO NOT touch `outputs/dashboard.py` other than the 2-line router include
- DO NOT modify `cortex_phase5_act.py` — handlers exist as-is
- DO NOT add a new auth mechanism — Slack signature is THE auth

## Quality Checkpoints

1. py_compile clean on `triggers/slack_interactivity.py`, `outputs/dashboard.py`
2. 8 unit tests PASS literally (`pytest tests/test_cortex_slack_interactivity.py -v`)
3. Regression PASS literally:
   - `tests/test_cortex_phase5_act.py` (existing — handlers unchanged)
   - `tests/test_cortex_phase5_idempotency.py`
   - `tests/test_cortex_pre_review_gate.py` (gate flow uses same Slack notifier)
4. Slack signature uses `hmac.compare_digest` (constant-time)
5. Endpoint responds < 3s on happy path (BackgroundTask scheduled, not awaited)
6. `SLACK_SIGNING_SECRET` already on Render (used by slack_events.py) — verify present pre-deploy

## Files Modified / Added

- `triggers/slack_interactivity.py` — NEW (~220 LOC)
- `outputs/dashboard.py` — +2 LOC (router import + include)
- `tests/test_cortex_slack_interactivity.py` — NEW (~250 LOC, 8 tests)

## Do NOT Touch

- `orchestrator/cortex_phase5_act.py` — handlers untouched (already shipped)
- `orchestrator/cortex_phase4_proposal.py` — proposal_card builder untouched
- `triggers/slack_events.py` — events router untouched (different surface)
- Existing slack_notifier callers / outputs/dashboard.py other endpoints

## After merge — A executes

1. Verify `SLACK_SIGNING_SECRET` present on Render (should already be set; used by slack_events.py)
2. Render redeploy
3. Smoke step 1 — bad signature curl: `curl -X POST .../webhook/slack/interactive -H "X-Slack-Signature: v0=garbage" -H "X-Slack-Request-Timestamp: $(date +%s)" -d 'payload={}'` → expect 403
4. Smoke step 2 — Slack workspace config: in Slack App settings, set Interactivity URL to `https://baker-master.onrender.com/webhook/slack/interactive`. Save.
5. Real test: open the AO proposal card from the earlier real cycle (`cycle_id=7dc3201b`), tap ❌ Reject (cheapest action — no Gold writes). Expect:
   - Card replaces with "❌ Rejected" footer + timestamp
   - cortex_cycles row for that cycle_id flips to status='rejected'
   - feedback_ledger row appended
6. Verify SQL: `SELECT cycle_id, status FROM cortex_cycles WHERE cycle_id='7dc3201b-...'`

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
