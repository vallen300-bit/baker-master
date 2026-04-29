"""CORTEX_SLACK_INTERACTIVITY_1: handle Director's button taps on proposal cards.

Endpoint
--------
POST /webhook/slack/interactive

Auth
----
Slack request signature HMAC-SHA256 (``SLACK_SIGNING_SECRET``). The interactivity
surface fails CLOSED on missing secret (handlers write Gold + execute
structured_actions). This is a deliberate divergence from the polling-only
``triggers/slack_events.py`` which fails OPEN.

Payload
-------
Slack POSTs ``application/x-www-form-urlencoded`` with one field ``payload``
holding a JSON string. The JSON's ``actions[0].action_id`` selects the handler:

    cortex_approve         → orchestrator.cortex_phase5_act.cortex_approve
    cortex_edit            → orchestrator.cortex_phase5_act.cortex_edit
    cortex_refresh         → orchestrator.cortex_phase5_act.cortex_refresh
    cortex_reject          → orchestrator.cortex_phase5_act.cortex_reject
    cortex_gold_select_*   → no-op (checkbox state captured downstream)

The button ``value`` field is itself a JSON string (``{"cycle_id":"...",
"proposal_id":"..."}``).

3-second budget
---------------
Slack expects HTTP 200 within 3 seconds, else retry with possible user-facing
error. Phase 5 handlers do real work (LLM, DB, Slack post). → handlers run as
``BackgroundTask``; the endpoint posts an ephemeral "Processing…" via
``response_url`` and returns 200 immediately.

Idempotency
-----------
Phase 5 handlers themselves use ``_cas_lock_cycle`` (CORTEX_PHASE5_IDEMPOTENCY_1).
Double-tap is harmless — the second invocation observes status already advanced
and returns warning='already_actioned' which we surface in the card footer.

Sensitive content
-----------------
Proposal text + matter context is sensitive and NEVER info-logged here. Only
action_id + cycle_id + user_name surface in logs at info level. Errors log
exception type and short message.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from config.settings import config

logger = logging.getLogger("sentinel.slack_interactivity")

router = APIRouter()


# --------------------------------------------------------------------------
# Signature verification — fails CLOSED
# --------------------------------------------------------------------------


def _verify_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature. Returns True iff valid + non-stale.

    Fails CLOSED on missing secret (different policy than slack_events). The
    interactivity surface dispatches to handlers that write Gold + execute
    structured_actions; we cannot accept unauthenticated requests even on a
    polling-only deploy.
    """
    secret = config.slack.signing_secret
    if not secret:
        logger.error(
            "SLACK_SIGNING_SECRET not set — refusing interactivity payload",
        )
        return False

    # Replay protection: reject timestamps > 5 min skew.
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
    # Constant-time compare — defends against timing oracle.
    return hmac.compare_digest(computed, signature)


# --------------------------------------------------------------------------
# response_url update helper
# --------------------------------------------------------------------------


def _post_response_update(response_url: str, body: dict) -> None:
    """POST a JSON payload to Slack's response_url to update the original card.

    Per Slack docs, response_url accepts up to 5 invocations within 30 min.
    Body shapes used here:
      - {"replace_original": true, "blocks": [...]}
      - {"replace_original": false, "response_type": "ephemeral", "text": ...}

    Failures are logged + swallowed — Slack already received our 200 and we
    must not raise out of a BackgroundTask.
    """
    if not response_url:
        return
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
    except Exception as e:  # noqa: BLE001
        logger.warning(f"response_url POST failed: {e}")


def _decision_footer_blocks(
    action_id: str, user_name: str, status_msg: str,
) -> list[dict]:
    """Build the footer blocks that replace the 4-button row after an action."""
    label = {
        "cortex_approve": "✅ Approved",
        "cortex_edit": "✏️ Edited",
        "cortex_refresh": "🔄 Refreshed",
        "cortex_reject": "❌ Rejected",
    }.get(action_id, action_id)
    now = int(time.time())
    return [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*{label}* by <@{user_name}> at "
                        f"<!date^{now}^{{date_short_pretty}} {{time}}|{now}>"
                    ),
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
    "cortex_edit": "cortex_edit",
    "cortex_refresh": "cortex_refresh",
    "cortex_reject": "cortex_reject",
}


async def _run_handler(
    *,
    action_id: str,
    cycle_id: str,
    payload: dict,
    response_url: str,
) -> None:
    """BackgroundTask: invoke the matching cortex_phase5_act handler, then
    update the Slack message in place via response_url.

    Wrapped in try/except — Slack already received 200; we MUST NOT raise.
    """
    user_name = (payload.get("user") or {}).get("name", "director")
    try:
        from orchestrator.cortex_phase5_act import (
            cortex_approve,
            cortex_edit,
            cortex_refresh,
            cortex_reject,
        )
        handlers = {
            "cortex_approve": cortex_approve,
            "cortex_edit": cortex_edit,
            "cortex_refresh": cortex_refresh,
            "cortex_reject": cortex_reject,
        }
        fn = handlers[action_id]
        result: Any = await fn(cycle_id=cycle_id, body=payload)

        # Result may be dict from any of the handlers; tolerate non-dict too.
        result_dict: dict = result if isinstance(result, dict) else {}
        warning = result_dict.get("warning")
        ok = bool(result_dict.get("ok", True))

        if warning == "already_actioned":
            status_msg = "_(already actioned — idempotent)_"
        elif ok:
            status_msg = "_(handler completed)_"
        else:
            err = str(result_dict.get("error", "handler returned not-ok"))[:200]
            status_msg = f"_(handler error: {err})_"

        # Replace the original 4-button row with the decision footer; keep
        # everything above the actions row so the proposal text remains in
        # the thread for reference.
        original_blocks = list(
            (payload.get("message") or {}).get("blocks") or []
        )
        new_blocks = [
            b for b in original_blocks
            if not str(b.get("block_id", "")).startswith("cortex_actions_")
        ]
        new_blocks.extend(_decision_footer_blocks(action_id, user_name, status_msg))
        _post_response_update(
            response_url,
            {"replace_original": True, "blocks": new_blocks[:50]},
        )
    except KeyError:
        logger.error(
            "Unknown action_id in interactivity dispatch: %s", action_id,
        )
        _post_response_update(
            response_url,
            {
                "replace_original": False,
                "response_type": "ephemeral",
                "text": f"Unknown action: {action_id}",
            },
        )
    except Exception as e:  # noqa: BLE001 — BackgroundTask must not propagate
        logger.error(
            "Interactivity handler failed action_id=%s cycle=%s: %s",
            action_id, cycle_id, e,
        )
        _post_response_update(
            response_url,
            {
                "replace_original": False,
                "response_type": "ephemeral",
                "text": f"Handler error — see logs. ({type(e).__name__})",
            },
        )


# --------------------------------------------------------------------------
# Endpoint — POST /webhook/slack/interactive
# (registered under the /webhook prefix in outputs/dashboard.py)
# --------------------------------------------------------------------------


@router.post("/slack/interactive")
async def slack_interactive(
    request: Request, background_tasks: BackgroundTasks,
):
    """Receives Director's button taps on Cortex proposal cards.

    Verifies Slack signature → parses payload → schedules Phase 5 handler in
    a BackgroundTask → returns 200 immediately (within Slack's 3s budget) +
    optional ephemeral 'Processing…' update via response_url.
    """
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_signature(body_bytes, timestamp, signature):
        return JSONResponse({"error": "invalid_signature"}, status_code=403)

    # Slack interactivity arrives as application/x-www-form-urlencoded with
    # a single 'payload' field that is itself a JSON string.
    try:
        form = urllib.parse.parse_qs(body_bytes.decode("utf-8"))
        payload_str = (form.get("payload") or [""])[0]
        if not payload_str:
            return JSONResponse({"error": "no_payload"}, status_code=400)
        payload = json.loads(payload_str)
    except Exception as e:  # noqa: BLE001
        logger.warning("slack_interactive payload parse failed: %s", e)
        return JSONResponse({"error": "bad_payload"}, status_code=400)

    actions = payload.get("actions") or []
    if not actions:
        return JSONResponse({"error": "no_actions"}, status_code=400)

    action = actions[0]
    action_id = str(action.get("action_id") or "")
    response_url = str(payload.get("response_url") or "")

    # Gold-select checkbox: state captured downstream by approve handler.
    if action_id.startswith("cortex_gold_select_"):
        return JSONResponse({}, status_code=200)

    if action_id not in _HANDLER_MAP:
        logger.warning("slack_interactive: unknown action_id=%s", action_id)
        return JSONResponse({"error": "unknown_action"}, status_code=400)

    # Parse cycle_id from button value (JSON-encoded by the proposal builder).
    raw_value = str(action.get("value") or "")
    cycle_id = ""
    try:
        if raw_value.startswith("{"):
            value_obj = json.loads(raw_value)
            cycle_id = str(value_obj.get("cycle_id") or "")
    except Exception:  # noqa: BLE001
        cycle_id = ""
    if not cycle_id:
        logger.warning(
            "slack_interactive: missing cycle_id action_id=%s", action_id,
        )
        return JSONResponse({"error": "no_cycle_id"}, status_code=400)

    # Schedule handler in background — Slack 3s budget.
    background_tasks.add_task(
        _run_handler,
        action_id=action_id,
        cycle_id=cycle_id,
        payload=payload,
        response_url=response_url,
    )

    # Optimistic ephemeral "Processing…" so Director sees instant feedback.
    if response_url:
        _post_response_update(
            response_url,
            {
                "replace_original": False,
                "response_type": "ephemeral",
                "text": f"Processing {action_id}…",
            },
        )

    return JSONResponse({}, status_code=200)
