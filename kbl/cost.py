"""Cost tracking: pre-call estimate, post-call logging, daily cap enforcement (D14).

Pricing keys are FAMILY-level aliases (claude-opus-4, claude-sonnet-4,
claude-haiku-4). Real Anthropic model IDs are versioned
(claude-opus-4-6, claude-haiku-4-5-20251001) — `_model_key()` normalizes
before looking up PRICING, and raises ValueError on unknown models
(R1.B6: stricter than silent $0, which would break cap enforcement).

Threshold alerts (80% / 95% / 100%) are day-scoped via kbl_alert_dedupe
so each pct-level fires exactly once per UTC day. Cost circuit is
self-latching at 100% and auto-cleared at UTC midnight by the purge job
calling `daily_cost_circuit_clear`.
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
import os
from datetime import date
from typing import Optional

from anthropic import Anthropic

from kbl.config import cfg_float
from kbl.db import get_conn
from kbl.logging import emit_log
from kbl.runtime_state import set_state

_local = _stdlib_logging.getLogger("kbl")

# Per-million-token prices in USD. Overridable via env for rate changes
# without a code deploy. Local models are free.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4": {
        "input": float(os.getenv("PRICE_OPUS4_IN", "15.00")),
        "output": float(os.getenv("PRICE_OPUS4_OUT", "75.00")),
    },
    "claude-sonnet-4": {
        "input": float(os.getenv("PRICE_SONNET4_IN", "3.00")),
        "output": float(os.getenv("PRICE_SONNET4_OUT", "15.00")),
    },
    "claude-haiku-4": {
        "input": float(os.getenv("PRICE_HAIKU4_IN", "0.80")),
        "output": float(os.getenv("PRICE_HAIKU4_OUT", "4.00")),
    },
    "gemma4:latest": {"input": 0.0, "output": 0.0},
    "qwen2.5:14b": {"input": 0.0, "output": 0.0},
}


def _model_key(full_id: str) -> str:
    """Normalize a full model ID to a PRICING key.

    Anthropic IDs are versioned; PRICING uses family aliases. Unknown
    models raise ValueError rather than silently logging $0 — that would
    mean the daily cap was effectively bypassed without anyone noticing.
    """
    if "opus" in full_id:
        return "claude-opus-4"
    if "sonnet" in full_id:
        return "claude-sonnet-4"
    if "haiku" in full_id:
        return "claude-haiku-4"
    if full_id in PRICING:
        return full_id
    raise ValueError(
        f"Unknown model for pricing: {full_id!r}. "
        "Add it to PRICING or update _model_key()."
    )


def estimate_cost(
    model: str,
    prompt: str,
    max_output_tokens: int,
    anthropic: Optional[Anthropic] = None,
) -> float:
    """Pre-call cost estimate in USD.

    Fallback chain for input token count:
      1. anthropic.messages.count_tokens (authoritative, requires SDK + model)
      2. Anthropic().count_tokens (legacy SDK API, may not exist)
      3. len(prompt) // 4 + 1 (conservative heuristic)
    """
    input_tokens: int | None = None
    if anthropic is not None and model.startswith("claude-"):
        try:
            resp = anthropic.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            input_tokens = resp.input_tokens
        except Exception:
            pass

    if input_tokens is None:
        try:
            from anthropic import Anthropic as _A
            input_tokens = _A().count_tokens(prompt)  # legacy
        except Exception:
            pass

    if input_tokens is None:
        input_tokens = len(prompt) // 4 + 1

    price = PRICING[_model_key(model)]
    return (input_tokens * price["input"] + max_output_tokens * price["output"]) / 1_000_000


def today_spent_usd() -> float:
    """Sum of cost_usd for today UTC."""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0)
                    FROM kbl_cost_ledger
                    WHERE ts::date = NOW()::date
                    """
                )
                return float(cur.fetchone()[0])
        except Exception:
            conn.rollback()
            raise


def check_cost_cap(
    model: str,
    prompt: str,
    max_output_tokens: int,
    anthropic: Optional[Anthropic] = None,
) -> tuple[bool, float, float]:
    """Returns (would_exceed, estimated_cost, today_total)."""
    cap = cfg_float("cost_daily_cap_usd", 15.0)
    today = today_spent_usd()
    estimate = estimate_cost(model, prompt, max_output_tokens, anthropic)
    return (today + estimate > cap, estimate, today)


def log_cost_actual(
    signal_id: int | None,
    step: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    success: bool = True,
    metadata: dict | None = None,
) -> None:
    """Post-call actual cost logging + threshold check."""
    price = PRICING[_model_key(model)]  # R1.B6: normalize before lookup
    cost = (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kbl_cost_ledger
                    (signal_id, step, model, input_tokens, output_tokens,
                     latency_ms, cost_usd, success, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        signal_id,
                        step,
                        model,
                        input_tokens,
                        output_tokens,
                        latency_ms,
                        cost,
                        success,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise

    _maybe_alert_cost_threshold()


def _maybe_alert_cost_threshold() -> None:
    """80% / 95% / 100% alerts with dedupe via kbl_alert_dedupe.

    Fires only the highest threshold crossed on any given call. 100%
    additionally flips cost_circuit_open=true so the pipeline idles
    until UTC midnight.
    """
    cap = cfg_float("cost_daily_cap_usd", 15.0)
    if cap <= 0:
        return  # misconfigured; don't divide by zero
    today = today_spent_usd()
    today_pct = today / cap * 100
    today_date = date.today().isoformat()

    thresholds = [
        (100, "cost_100pct_open_circuit"),
        (95, "cost_95pct_alert"),
        (80, "cost_80pct_alert"),
    ]
    for pct, alert_key_base in thresholds:
        if today_pct < pct:
            continue
        alert_key = f"{alert_key_base}_{today_date}"
        if _try_dedupe(alert_key):
            if pct == 100:
                set_state("cost_circuit_open", "true")
                emit_log(
                    "CRITICAL",
                    "cost_circuit",
                    None,
                    f"KBL cost cap reached today: ${today:.2f} / ${cap:.2f}. "
                    "Pipeline halted until UTC midnight.",
                )
            else:
                emit_log(
                    "WARN",
                    "cost_threshold",
                    None,
                    f"KBL cost at {pct}%: ${today:.2f} / ${cap:.2f}",
                )
        break  # only the highest crossed threshold fires


def _try_dedupe(alert_key: str) -> bool:
    """INSERT with ON CONFLICT DO NOTHING. Returns True iff this is a
    fresh alert and should be sent now."""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kbl_alert_dedupe (alert_key) VALUES (%s)
                    ON CONFLICT (alert_key) DO NOTHING
                    RETURNING alert_key
                    """,
                    (alert_key,),
                )
                inserted = cur.fetchone()
                conn.commit()
                return inserted is not None
        except Exception:
            conn.rollback()
            raise


def daily_cost_circuit_clear() -> None:
    """Reset cost_circuit_open at UTC midnight. Invoked by kbl-purge-dedupe.sh."""
    set_state("cost_circuit_open", "false")
    # INFO stays local (R1.S2 invariant) — emit_log would reject it anyway.
    _local.info("[cost_circuit] auto-cleared at UTC midnight")
