"""Cortex Phase 4.5 — Director Card translation.

Converts the technical ``proposal_text`` written by Phase 3c synthesis into a
plain-English 9-field JSON card the Director can ratify in ≤30 seconds.
Runs AFTER Phase 4 has persisted ``proposal_card`` + flipped status to
``tier_b_pending``; fail-open by design — the cycle is already reachable
by the Director when this module fires, so any error here MUST NOT raise.

Brief: ``briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# --- Model / pricing constants ------------------------------------------------

# Primary: Gemini 2.5 Pro via orchestrator.gemini_client.
# Fallback: Anthropic Sonnet 4.6 on ANY Gemini call/parse/schema failure.
# Director-ratified 2026-05-20: Haiku-distrust on Director-facing surfaces.
_PRIMARY_MODEL = "gemini-2.5-pro"
_PRIMARY_MODEL_ENV = "GEMINI_MODEL_DIRECTOR_CARD"
_FALLBACK_MODEL = "claude-sonnet-4-6"
_FALLBACK_MODEL_ENV = "ANTHROPIC_MODEL_DIRECTOR_CARD_FALLBACK"
_ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

# USD per 1M tokens — Gemini 2.5 Pro public list pricing (May 2026):
# input $1.25 / output $5.00. Sonnet 4.6 fallback: $3.00 / $15.00.
_PRICE_GEMINI_PRO_INPUT_PER_M = float(os.getenv("PRICE_GEMINI_PRO_IN", "1.25"))
_PRICE_GEMINI_PRO_OUTPUT_PER_M = float(os.getenv("PRICE_GEMINI_PRO_OUT", "5.00"))
_PRICE_SONNET_INPUT_PER_M = float(os.getenv("PRICE_SONNET4_IN", "3.00"))
_PRICE_SONNET_OUTPUT_PER_M = float(os.getenv("PRICE_SONNET4_OUT", "15.00"))

_MAX_TOKENS = 600
_TEMPERATURE = 0.0
_PROPOSAL_INPUT_TRIM = 6000  # guard against pathological proposal_text length

# 9-field card schema. Required keys; nested structure for ``cost``.
_REQUIRED_TOP = (
    "matter",
    "situation",
    "action",
    "rationale",
    "downside",
    "no_action_consequence",
    "cost",
    "recommendation",
    "confidence",
)
_REQUIRED_COST = ("ai_money_eur", "real_world_money_eur", "action_sends_money")
_RECO_ALLOWED = {"approve", "reject", "edit"}
_CONF_ALLOWED = {"high", "medium", "low"}

# Strip rules: no HTML, no markdown links, no javascript: schemes — applied to
# every string field after JSON parse. Card-rendering surface uses ``esc()``
# on the way out too, but defense-in-depth: poison the source first.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_JS_SCHEME_RE = re.compile(r"javascript\s*:", re.IGNORECASE)


# --- Prompt (pinned verbatim from brief §Prompt contract) ---------------------

SYSTEM_PROMPT = """You translate technical AI-generated proposals into plain English for a non-technical executive (Chairman of a real-estate / capital group) who must ratify or reject each proposal in under 30 seconds.

Output ONLY a JSON object with these 9 fields. No prose, no markdown, no explanation. If you cannot extract a field from the input, write "unclear — needs Director review" — never invent.

{
  "matter": "<matter name in plain English, not a slug>",
  "situation": "<one sentence: what's going on right now>",
  "action": "<one sentence: what the system wants to do>",
  "rationale": "<two sentences maximum: why this action makes sense>",
  "downside": "<one line: the worst plausible outcome if the Chairman approves>",
  "no_action_consequence": "<one line: what happens if the Chairman rejects or does nothing>",
  "cost": {
    "ai_money_eur": <float, AI compute cost in EUR>,
    "real_world_money_eur": <float or null, money the action sends/spends>,
    "action_sends_money": <true|false>
  },
  "recommendation": "approve|reject|edit",
  "confidence": "high|medium|low"
}

Rules:
- Plain English. No jargon. No agent / system / pipeline / capability terminology.
- Use the matter's plain name, never the slug.
- "downside" and "no_action_consequence" are mandatory and always populated.
- "confidence" reflects the underlying proposal's internal confidence, not your translation confidence.
- Never embed HTML, markdown links, or JavaScript in any field. Strip them from the source if present.
"""

# Sentinel returned when translation fails — frontend falls back to
# ``proposal_text`` rendering when ``director_card`` is None, but callers
# can still distinguish "never tried" from "tried and failed" by writing
# the sentinel into a separate artifact_type if they want to. For now the
# runner-side wrapper discards on failure and writes nothing.
FAIL_OPEN_SENTINEL: Optional[dict] = None


# --- Store accessor (test hook) ----------------------------------------------


def _get_store():
    """Resolve the SentinelStoreBack singleton via the canonical accessor.

    Module-level indirection lets tests monkeypatch the store.
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


# --- Anthropic fallback client (lazy, test-overridable) ----------------------

_anthropic_client = None


def _get_anthropic_fallback_client():
    """Return a cached ``anthropic.Anthropic`` client used for the Sonnet 4.6
    fallback path. Lazy so tests can stub the SDK before first use."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        key = os.environ.get(_ANTHROPIC_API_KEY_ENV)
        if not key:
            raise RuntimeError(f"{_ANTHROPIC_API_KEY_ENV} env var not set")
        _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _reset_client_for_tests() -> None:
    global _anthropic_client
    _anthropic_client = None


# --- Sanitization -------------------------------------------------------------


def _sanitize_string(value: Any) -> str:
    """Strip HTML tags, markdown links, and ``javascript:`` schemes from a
    string field. Returns "" for non-string input — schema validator will
    flag missing field separately."""
    if not isinstance(value, str):
        return ""
    # Markdown link → keep label, drop target.
    cleaned = _MD_LINK_RE.sub(r"\1", value)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _JS_SCHEME_RE.sub("", cleaned)
    return cleaned.strip()


def _sanitize_card(card: dict) -> dict:
    """Apply ``_sanitize_string`` to every string-valued field, including
    those inside the ``cost`` sub-object."""
    out: dict = {}
    for k, v in card.items():
        if k == "cost" and isinstance(v, dict):
            out[k] = {ck: cv for ck, cv in v.items()}
        elif isinstance(v, str):
            out[k] = _sanitize_string(v)
        else:
            out[k] = v
    return out


# --- Schema validation -------------------------------------------------------


def _validate_card_schema(card: Any) -> Optional[str]:
    """Return None on valid, else a short error string. Used by the entry
    point to log + fail-open, and exposed for the backfill script to
    surface bad rows."""
    if not isinstance(card, dict):
        return f"card is not a dict: {type(card).__name__}"
    for k in _REQUIRED_TOP:
        if k not in card:
            return f"missing required field: {k}"
    cost = card.get("cost")
    if not isinstance(cost, dict):
        return "cost field must be an object"
    for k in _REQUIRED_COST:
        if k not in cost:
            return f"missing cost.{k}"
    if not isinstance(cost.get("action_sends_money"), bool):
        return "cost.action_sends_money must be bool"
    try:
        float(cost.get("ai_money_eur"))
    except (TypeError, ValueError):
        return "cost.ai_money_eur must be a number"
    rw = cost.get("real_world_money_eur")
    if rw is not None:
        try:
            float(rw)
        except (TypeError, ValueError):
            return "cost.real_world_money_eur must be a number or null"
    if card.get("recommendation") not in _RECO_ALLOWED:
        return f"recommendation must be one of {sorted(_RECO_ALLOWED)}"
    if card.get("confidence") not in _CONF_ALLOWED:
        return f"confidence must be one of {sorted(_CONF_ALLOWED)}"
    for k in ("matter", "situation", "action", "rationale", "downside", "no_action_consequence"):
        if not isinstance(card.get(k), str):
            return f"{k} must be a string"
    return None


# --- Cost computation --------------------------------------------------------


def _compute_gemini_pro_cost_eur(input_tokens: int, output_tokens: int) -> float:
    """Per-call EUR cost for Gemini 2.5 Pro. Pricing table is USD-per-1M;
    §9.2 reconciliation in kbl.cost treats USD == EUR for Phase-1
    single-currency accounting."""
    total_per_m = (
        input_tokens * _PRICE_GEMINI_PRO_INPUT_PER_M
        + output_tokens * _PRICE_GEMINI_PRO_OUTPUT_PER_M
    )
    return float(total_per_m / 1_000_000.0)


def _compute_sonnet_cost_eur(input_tokens: int, output_tokens: int) -> float:
    """Per-call EUR cost for Sonnet 4.6 fallback. Same USD==EUR caveat."""
    total_per_m = (
        input_tokens * _PRICE_SONNET_INPUT_PER_M
        + output_tokens * _PRICE_SONNET_OUTPUT_PER_M
    )
    return float(total_per_m / 1_000_000.0)


# --- JSON extraction helpers -------------------------------------------------


def _extract_text(content: Any) -> str:
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            t = getattr(block, "text", "")
            if isinstance(t, str):
                parts.append(t)
    return "".join(parts)


def _parse_json_response(raw: str) -> Optional[dict]:
    """Tolerate a model that wraps JSON in code-fences or adds a leading
    sentence. Strict JSON only after extraction."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        # Strip first fence line and trailing fence.
        s = re.sub(r"^```(?:json)?\s*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
    # If model added prose before the JSON, find the first '{' and parse from there.
    if not s.startswith("{"):
        idx = s.find("{")
        if idx == -1:
            return None
        s = s[idx:]
    try:
        return json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return None


# --- Public entry ------------------------------------------------------------


def translate_to_director_card(
    *,
    cycle_id: str,
    proposal_text: str,
    matter_slug: str,
    cost_telemetry: Optional[dict] = None,
) -> Optional[dict]:
    """Translate technical ``proposal_text`` into a 9-field Director Card.

    Primary: Gemini 2.5 Pro via ``orchestrator.gemini_client.generate``.
    Fallback (on any Gemini call / parse / schema failure): Anthropic
    Sonnet 4.6. Both paths share ``SYSTEM_PROMPT``, schema validation,
    and sanitization. The card on return has ``_meta.fallback_used``
    stamped (False on Gemini path, True on Sonnet path) so audit /
    cost reconciliation can attribute spend.

    Args:
        cycle_id: parent Cortex cycle id (for logging only).
        proposal_text: the Phase 3c synthesis output. May be empty —
            translator returns None in that case.
        matter_slug: matter slug for the cycle (used in the user prompt
            so the model has the slug → plain-name mapping anchor).
        cost_telemetry: optional dict from runner with cycle cost-so-far.
            Currently surfaced into the user prompt but not enforced.

    Returns:
        9-field card dict on success. ``FAIL_OPEN_SENTINEL`` (None) on
        double failure. Never raises.
    """
    if not proposal_text:
        return None

    primary_model = os.environ.get(_PRIMARY_MODEL_ENV, _PRIMARY_MODEL)
    fallback_model = os.environ.get(_FALLBACK_MODEL_ENV, _FALLBACK_MODEL)
    user_text = _build_user_prompt(
        matter_slug=matter_slug,
        proposal_text=proposal_text[:_PROPOSAL_INPUT_TRIM],
        cost_telemetry=cost_telemetry or {},
    )

    # --- Primary: Gemini 2.5 Pro --------------------------------------------
    try:
        from orchestrator.gemini_client import generate as gemini_generate
        resp = gemini_generate(
            model=primary_model,
            messages=[{"role": "user", "content": user_text}],
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
        )
        raw_text = getattr(resp, "text", "") or ""
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        parsed = _parse_json_response(raw_text)
        if parsed is not None:
            sanitized = _sanitize_card(parsed)
            err = _validate_card_schema(sanitized)
            if err is None:
                sanitized["_meta"] = {
                    "model": primary_model,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "card_gen_cost_eur": _compute_gemini_pro_cost_eur(in_tok, out_tok),
                    "fallback_used": False,
                }
                return sanitized
            logger.warning(
                "[phase4_5] cycle %s: gemini schema invalid (%s); trying Sonnet fallback",
                cycle_id, err,
            )
        else:
            logger.warning(
                "[phase4_5] cycle %s: gemini returned non-JSON; trying Sonnet fallback",
                cycle_id,
            )
    except Exception as e:
        logger.warning(
            "[phase4_5] cycle %s: gemini call failed (%s); trying Sonnet fallback",
            cycle_id, e,
        )

    # --- Fallback: Anthropic Sonnet 4.6 -------------------------------------
    try:
        client = _get_anthropic_fallback_client()
    except Exception as e:
        logger.warning(
            "[phase4_5] cycle %s: no anthropic client for fallback: %s", cycle_id, e
        )
        return FAIL_OPEN_SENTINEL

    try:
        response = client.messages.create(
            model=fallback_model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as e:
        logger.warning(
            "[phase4_5] cycle %s: sonnet fallback also failed: %s", cycle_id, e
        )
        return FAIL_OPEN_SENTINEL

    raw_text = _extract_text(getattr(response, "content", None))
    parsed = _parse_json_response(raw_text)
    if parsed is None:
        logger.warning(
            "[phase4_5] cycle %s: sonnet fallback returned non-JSON", cycle_id
        )
        return FAIL_OPEN_SENTINEL

    sanitized = _sanitize_card(parsed)
    err = _validate_card_schema(sanitized)
    if err:
        logger.warning(
            "[phase4_5] cycle %s: sonnet fallback schema invalid: %s", cycle_id, err
        )
        return FAIL_OPEN_SENTINEL

    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0)
    out_tok = int(getattr(usage, "output_tokens", 0) or 0)
    sanitized["_meta"] = {
        "model": getattr(response, "model", fallback_model),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "card_gen_cost_eur": _compute_sonnet_cost_eur(in_tok, out_tok),
        "fallback_used": True,
    }
    return sanitized


def _build_user_prompt(
    *,
    matter_slug: str,
    proposal_text: str,
    cost_telemetry: dict,
) -> str:
    """Render the per-cycle user message. The system prompt holds the
    schema + rules; the user message just carries the inputs."""
    cycle_cost = cost_telemetry.get("cost_dollars")
    cycle_tokens = cost_telemetry.get("cost_tokens")
    lines = [
        f"Matter slug: {matter_slug}",
    ]
    if cycle_cost is not None:
        lines.append(f"Cycle AI compute cost so far (EUR): {cycle_cost}")
    if cycle_tokens is not None:
        lines.append(f"Cycle token count so far: {cycle_tokens}")
    lines.append("")
    lines.append("Technical proposal to translate:")
    lines.append("---")
    lines.append(proposal_text)
    lines.append("---")
    lines.append("")
    lines.append("Return only the 9-field JSON object. No prose.")
    return "\n".join(lines)


# --- Persistence -------------------------------------------------------------


def persist_director_card(cycle_id: str, card: dict) -> bool:
    """Write a ``director_card`` artifact row. Returns True on success,
    False on any DB error (never raises — same fail-open contract)."""
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        logger.error("[phase4_5] persist: no DB connection")
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs
                (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'propose', 9, 'director_card', %s::jsonb)
            """,
            (cycle_id, json.dumps(card, default=str)),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("[phase4_5] persist failed for %s: %s", cycle_id, e)
        return False
    finally:
        store._put_conn(conn)


# --- Runner-facing wrapper ---------------------------------------------------


async def run_phase4_5_director_card(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cost_telemetry: Optional[dict] = None,
) -> Optional[dict]:
    """Generate + persist a Director Card. Never raises.

    Sync work under the hood (Anthropic SDK is sync); the ``async`` shell
    keeps the runner's await contract intact and lets a future migration
    to ``AsyncAnthropic`` be a one-line swap.
    """
    card = translate_to_director_card(
        cycle_id=cycle_id,
        proposal_text=proposal_text,
        matter_slug=matter_slug,
        cost_telemetry=cost_telemetry,
    )
    if card is None:
        return None
    persisted = persist_director_card(cycle_id, card)
    if not persisted:
        # Card was generated but not stored — return it anyway for tests /
        # backfill callers that drive persistence externally.
        return card
    return card
