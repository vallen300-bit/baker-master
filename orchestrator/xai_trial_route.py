"""Grok-4.5 trial route governor — GROK_4_5_WEEK_TRIAL_1.

The single choke-point that turns an ordinary Grok call into a *governed trial
call*. Binds three controls from brief #11256 / rulings #11260:

  1. **Per-role route flag** — env ``GROK45_ENABLED_ROUTES`` (comma-list). Unset
     or empty ⇒ EVERY route OFF. A route is trial-active only if it is listed.
     Activation is one route at a time via a lead-GO env change (+ manual Render
     deploy — env PUT alone does not restart).
  2. **Exact-model allowlist** — trial routes run ``grok-4.5`` and NOTHING else.
     No grok-4.3, no lower Grok, no Claude, NO automatic fallback. A conflicting
     explicit model fails loud (never silently overridden or downgraded).
  3. **Weekly reservation ledger + per-call audit** — reserve conservatively
     before the call, settle actual + release residual after, release on failure.
     Every attempt writes one ``xai_call_audit`` row (route + cause + spend).

Known route keys (brief scope): ``b4_runtime`` (first activation candidate),
``researcher_channel`` (researcher fan-out Grok channel 4.3→4.5),
``researcher_shadow_synth`` (shadow A/B synthesis; delivered report stays Opus).
The researcher AGENT-SIDE wiring (passing those route values, running the shadow
synth) is a separate researcher lane — this module is the baker-master substrate
that governs any Grok call tagged with an enabled trial route.
"""
from __future__ import annotations

import logging
import math
import os
import uuid
from typing import Any, Optional

from orchestrator import xai_week_ledger as ledger

logger = logging.getLogger("baker.xai_trial_route")

TRIAL_MODEL = "grok-4.5"

# Brief-scoped route keys. Membership in GROK45_ENABLED_ROUTES still gates
# activation; this set documents/validates the recognized keys.
KNOWN_ROUTES: frozenset[str] = frozenset(
    {"b4_runtime", "researcher_channel", "researcher_shadow_synth"}
)

# Conservative reservation knobs.
_TOOL_ALLOWANCE_USD = float(os.getenv("BAKER_XAI_TOOL_ALLOWANCE_USD", "0.05"))
_RESERVE_INPUT_FLOOR_TOKENS = int(os.getenv("BAKER_XAI_RESERVE_INPUT_FLOOR", "512"))
_RESERVE_DEFAULT_MAX_OUT = int(os.getenv("BAKER_XAI_RESERVE_DEFAULT_MAX_OUT", "4000"))


class GrokTrialError(RuntimeError):
    """Raised for a fail-loud trial condition (route/model/budget). Carries a
    structured ``info`` dict with route + cause + spend so callers surface it."""

    def __init__(self, info: dict):
        self.info = info
        super().__init__(info.get("reason", "grok_trial_error"))


# ─────────────────────────── route flag ───────────────────────────

def enabled_routes() -> frozenset[str]:
    """Parse ``GROK45_ENABLED_ROUTES``. Unset/blank ⇒ empty set (all OFF)."""
    raw = os.getenv("GROK45_ENABLED_ROUTES", "") or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def is_route_enabled(route: Optional[str]) -> bool:
    return bool(route) and route in enabled_routes()


# ─────────────────────────── reservation estimate ───────────────────────────

def _model_rate() -> dict:
    """grok-4.5 per-million USD rates from the authoritative cost table."""
    from orchestrator.cost_monitor import MODEL_COSTS, DEFAULT_COSTS
    return MODEL_COSTS.get(TRIAL_MODEL, DEFAULT_COSTS)


def _token_cost_usd(tokens_in: int, tokens_out: int) -> float:
    rate = _model_rate()
    return (tokens_in * rate["input"] + tokens_out * rate["output"]) / 1_000_000.0


def _estimate_input_tokens(prompt: str, instructions: Optional[str]) -> int:
    """Conservative input-token estimate: chars/3 (over-estimates vs ~chars/4)
    plus a floor, so the reservation errs high."""
    chars = len(prompt or "") + len(instructions or "")
    return int(math.ceil(chars / 3.0)) + _RESERVE_INPUT_FLOOR_TOKENS


def estimate_reserve_usd(prompt: str, instructions: Optional[str],
                         max_output_tokens: int, include_tool_allowance: bool) -> float:
    """Conservative pre-call reservation = max_in + max_out + tool allowance."""
    est_in = _estimate_input_tokens(prompt, instructions)
    max_out = int(max_output_tokens or _RESERVE_DEFAULT_MAX_OUT)
    amount = _token_cost_usd(est_in, max_out)
    if include_tool_allowance:
        amount += _TOOL_ALLOWANCE_USD
    return round(amount, 6)


def _actual_usd(payload: dict, tokens_in: int, tokens_out: int) -> float:
    """Authoritative actual spend for the settle/audit. Never UNDER-bills the cap:
    max(payload cost_usd, token×grok-4.5 rate). The payload's cost_usd is only
    trustworthy when xAI returns cost ticks; its token fallback is grok-4.3 rated
    (undercounts 4.5), so we floor on the 4.5 token rate."""
    model_rate_usd = _token_cost_usd(tokens_in, tokens_out)
    payload_usd = 0.0
    try:
        v = float(payload.get("cost_usd") or 0.0)
        if v > 0 and math.isfinite(v):
            payload_usd = v
    except (TypeError, ValueError):
        payload_usd = 0.0
    return round(max(model_rate_usd, payload_usd), 6)


# ─────────────────────────── governed call ───────────────────────────

def run_grok_ask(
    client: Any,
    *,
    prompt: str,
    route: str,
    max_output_tokens: int = 4000,
    instructions: Optional[str] = None,
    model: Optional[str] = None,
    matter_slug: Optional[str] = None,
    timeout: Optional[float] = None,
    request_ref: Optional[str] = None,
) -> dict:
    """Run a governed grok-4.5 ``ask`` on a trial route. Returns the client
    payload dict augmented with ``_trial`` metadata on success.

    Raises :class:`GrokTrialError` (fail loud, no fallback) when the route is
    disabled, an off-allowlist model is requested, or the weekly cap blocks it.
    A downstream Grok failure releases the reservation and re-raises as a
    GrokTrialError carrying route + cause + spend.
    """
    request_ref = request_ref or uuid.uuid4().hex

    # (1) Route flag — disabled routes never call xAI.
    if not is_route_enabled(route):
        info = {"reason": "route_disabled", "route": route,
                "enabled_routes": sorted(enabled_routes())}
        ledger.write_call_audit(model=TRIAL_MODEL, route=route or "(none)",
                                request_ref=request_ref, outcome="blocked_route_disabled",
                                error_class="route_disabled", matter_slug=matter_slug)
        raise GrokTrialError(info)

    # (2) Exact-model allowlist — no fallback, no downgrade.
    if model is not None and model != TRIAL_MODEL:
        info = {"reason": "model_not_allowed", "route": route,
                "requested_model": model, "allowed_model": TRIAL_MODEL}
        ledger.write_call_audit(model=str(model), route=route, request_ref=request_ref,
                                outcome="blocked_model_not_allowed",
                                error_class="model_not_allowed", matter_slug=matter_slug)
        raise GrokTrialError(info)

    # (3) Conservative reservation BEFORE the call. `ask` uses no search tool.
    reserve_usd = estimate_reserve_usd(prompt, instructions, max_output_tokens,
                                       include_tool_allowance=False)
    res = ledger.reserve(route=route, amount_usd=reserve_usd, request_ref=request_ref)
    if not res.get("granted"):
        info = {"reason": res.get("reason", "reserve_denied"), "route": route,
                "reserved_usd": reserve_usd,
                "remaining_usd": res.get("remaining_usd"),
                "cap_usd": res.get("cap_usd"),
                "effective_used_usd": res.get("effective_used_usd")}
        ledger.write_call_audit(model=TRIAL_MODEL, route=route, request_ref=request_ref,
                                reserved_usd=reserve_usd,
                                outcome="blocked_" + str(res.get("reason", "reserve_denied")),
                                error_class="weekly_cap", matter_slug=matter_slug)
        logger.error("grok trial BLOCKED route=%s reason=%s reserved=%.6f remaining=%s",
                     route, info["reason"], reserve_usd, info.get("remaining_usd"))
        raise GrokTrialError(info)

    # Call — grok-4.5 only. Any failure releases the hold and fails loud.
    try:
        payload = client.ask(
            prompt=prompt,
            model=TRIAL_MODEL,
            max_output_tokens=int(max_output_tokens or _RESERVE_DEFAULT_MAX_OUT),
            instructions=instructions,
            timeout=timeout,
        )
    except Exception as e:
        ledger.release(request_ref, route, reason="call_failed")
        info = {"reason": "grok_call_failed", "route": route,
                "error_class": type(e).__name__, "cause": str(e),
                "reserved_usd": reserve_usd, "spend_usd": 0.0}
        ledger.write_call_audit(model=TRIAL_MODEL, route=route, request_ref=request_ref,
                                reserved_usd=reserve_usd, outcome="error",
                                error_class=type(e).__name__, matter_slug=matter_slug)
        logger.error("grok trial CALL FAILED route=%s cause=%s (reservation released)",
                     route, e)
        raise GrokTrialError(info) from e

    # Settle actual + release residual; mirror actual into api_cost_log.
    tokens_in = int(payload.get("tokens_in") or 0)
    tokens_out = int(payload.get("tokens_out") or 0)
    est_usd = round(_token_cost_usd(tokens_in, tokens_out), 6)
    actual_usd = _actual_usd(payload, tokens_in, tokens_out)
    settle_res = ledger.settle(request_ref, actual_usd, route)
    _settle_into_api_cost_log(tokens_in, tokens_out, actual_usd, matter_slug)
    ledger.write_call_audit(
        model=TRIAL_MODEL, route=route, request_ref=request_ref,
        tokens_in=tokens_in, tokens_out=tokens_out, reserved_usd=reserve_usd,
        est_usd=est_usd, actual_usd=actual_usd, outcome="ok", matter_slug=matter_slug,
    )
    payload = dict(payload)
    payload["_trial"] = {
        "route": route, "request_ref": request_ref, "model": TRIAL_MODEL,
        "reserved_usd": reserve_usd, "actual_usd": actual_usd, "est_usd": est_usd,
        "residual_released_usd": settle_res.get("released_residual_usd", 0.0),
    }
    return payload


def _settle_into_api_cost_log(tokens_in: int, tokens_out: int,
                              actual_usd: float, matter_slug: Optional[str]) -> None:
    """Record the trial call in api_cost_log (daily cost surface) with the
    authoritative actual USD as cost_usd_override. Non-fatal on failure."""
    try:
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost(
            model=TRIAL_MODEL, input_tokens=tokens_in, output_tokens=tokens_out,
            source="grok_realtime", matter_slug=matter_slug,
            cost_usd_override=actual_usd,
        )
    except Exception:
        logger.exception("grok trial: log_api_cost failed (non-fatal)")
