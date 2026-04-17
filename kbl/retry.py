"""Retry ladders + circuit breaker for Anthropic API and local Ollama.

DLQ caller contract (R1.M2): both `call_anthropic_with_retry` and
`call_gemma_with_retry` re-raise on exhausted retries. Callers MUST wrap
with try/except that marks the signal `status='failed'` + logs ERROR.
The KBL-B pipeline is the canonical caller; KBL-A's pipeline_tick stub
does not invoke these functions yet.

Qwen cold-swap logic (Gemma ladder attempt 4) records `qwen_active_since`
as ISO-8601 UTC (R1.B2 — never the literal string 'NOW()').
"""

from __future__ import annotations

import logging as _stdlib_logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from anthropic import Anthropic, APIError, RateLimitError

from kbl.config import cfg, cfg_int
from kbl.logging import emit_log
from kbl.runtime_state import get_state, increment_state, set_state

ANTHROPIC_BACKOFFS = [10, 30, 120]
CIRCUIT_CLEAR_WAIT_SECONDS = 600  # 10 min per D8
OLLAMA_TIMEOUT = 180  # R1.S9: Qwen cold-swap warm-up can exceed 60s

_local = _stdlib_logging.getLogger("kbl")


class InvalidJSONError(Exception):
    """Raised when Ollama returns output that doesn't parse as JSON."""


def call_anthropic_with_retry(
    anthropic: Anthropic,
    model: str,
    messages: list,
    max_tokens: int,
    skip_circuit: bool = False,
) -> Any:
    """Anthropic call with 10s/30s/120s backoff ladder + 3×5xx → circuit open.

    skip_circuit=True is the health-check path (check_and_clear_anthropic_circuit).
    """
    if not skip_circuit and get_state("anthropic_circuit_open") == "true":
        raise RuntimeError("anthropic_circuit_open")

    last_error: Exception | None = None
    for attempt, backoff in enumerate([0] + ANTHROPIC_BACKOFFS):
        if backoff > 0:
            time.sleep(backoff)
        try:
            resp = anthropic.messages.create(
                model=model, messages=messages, max_tokens=max_tokens
            )
            set_state("anthropic_5xx_counter", "0")
            return resp
        except RateLimitError as e:
            last_error = e
            emit_log(
                "WARN",
                "retry_anthropic",
                None,
                f"429 on attempt {attempt + 1}, backing off",
            )
            continue
        except APIError as e:
            last_error = e
            status = getattr(e, "status_code", None)
            if status is not None and 500 <= status < 600:
                counter = increment_state("anthropic_5xx_counter")
                emit_log(
                    "WARN",
                    "retry_anthropic",
                    None,
                    f"5xx on attempt {attempt + 1}, counter={counter}",
                )
                if counter >= 3:
                    set_state("anthropic_circuit_open", "true")
                    set_state("anthropic_5xx_counter", "0")
                    emit_log(
                        "CRITICAL",
                        "circuit_breaker",
                        None,
                        "Anthropic circuit opened (3× consecutive 5xx)",
                    )
                    break
            continue

    raise last_error or RuntimeError("anthropic retry exhausted")


def check_and_clear_anthropic_circuit(anthropic: Anthropic) -> bool:
    """Health check — dedicated maintenance task (NOT called by pipeline_tick
    directly; pipeline_tick just skips the tick when circuit is open).
    Returns True if circuit now clear."""
    if get_state("anthropic_circuit_open") != "true":
        return True
    try:
        anthropic.messages.create(
            model="claude-haiku-4",
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
        )
        set_state("anthropic_circuit_open", "false")
        # INFO stays local only per R1.S2 invariant — emit_log rejects INFO.
        _local.info("[circuit_breaker] Anthropic circuit cleared by health check")
        return True
    except Exception as e:
        emit_log("WARN", "circuit_breaker", None, f"Health check still failing: {e}")
        return False


def call_gemma_with_retry(signal: dict, prompt_template: str) -> dict:
    """Gemma ladder: full prompt → pared prompt → temp=0.3 → Qwen cold-swap → raise."""
    model = cfg("ollama_model", "gemma4:latest")
    fallback = cfg("ollama_fallback", "qwen2.5:14b")

    # Attempt 1: full prompt, temp=0
    try:
        return _call_ollama(model, prompt_template.format(**signal), temp=0)
    except Exception as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 1 failed: {e}")

    # Attempt 2: pared prompt, temp=0
    try:
        pared = _pare_prompt(prompt_template).format(**signal)
        return _call_ollama(model, pared, temp=0)
    except Exception as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 2 failed: {e}")

    # Attempt 3: full prompt, temp=0.3
    try:
        return _call_ollama(model, prompt_template.format(**signal), temp=0.3)
    except Exception as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 3 failed: {e}")

    # Attempt 4: Qwen cold-swap. R1.B2: ISO-8601 timestamp, not 'NOW()' literal.
    try:
        set_state("qwen_active", "true")
        if not get_state("qwen_active_since"):
            set_state("qwen_active_since", datetime.now(timezone.utc).isoformat())
        result = _call_ollama(fallback, prompt_template.format(**signal), temp=0)
        increment_state("qwen_swap_count_today")
        return result
    except Exception as e:
        emit_log("ERROR", "retry_gemma", signal.get("id"), f"Qwen also failed: {e}")
        raise  # DLQ contract (R1.M2): caller must catch + mark 'failed'.


def maybe_recover_gemma() -> None:
    """R1.S8 either-condition: recover after N signals OR M hours elapsed.

    Intended caller: pipeline_tick (top of tick) or dedicated maintenance
    task. Cheap — 3 reads + optional 3 writes.
    """
    if get_state("qwen_active") != "true":
        return

    try:
        swap_count = int(get_state("qwen_swap_count_today") or "0")
    except ValueError:
        swap_count = 0
    active_since_raw = get_state("qwen_active_since")

    count_trigger = swap_count >= cfg_int("pipeline_qwen_recovery_after_signals", 10)

    hours_trigger = False
    if active_since_raw:
        try:
            active_since = datetime.fromisoformat(active_since_raw)
            elapsed = datetime.now(timezone.utc) - active_since
            threshold = timedelta(hours=cfg_int("pipeline_qwen_recovery_after_hours", 1))
            hours_trigger = elapsed >= threshold
        except ValueError:
            pass  # malformed → count-trigger only

    if count_trigger or hours_trigger:
        reasons = []
        if count_trigger:
            reasons.append(f"count={swap_count}")
        if hours_trigger:
            reasons.append("hours_elapsed")
        set_state("qwen_active", "false")
        set_state("qwen_active_since", "")
        set_state("qwen_swap_count_today", "0")
        emit_log(
            "WARN",
            "qwen_recovery",
            None,
            f"Recovered to Gemma (triggers: {', '.join(reasons)})",
        )


def _pare_prompt(template: str) -> str:
    """Strip vault-context chunks, keep instruction + signal + schema.
    KBL-A identity implementation; KBL-B refines with real stripping logic."""
    return template


def _call_ollama(model: str, prompt: str, temp: float = 0) -> dict:
    """Local Ollama call returning parsed JSON."""
    import json

    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": temp, "seed": 42, "top_p": 0.9},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return json.loads(data["response"])
    except (json.JSONDecodeError, KeyError) as e:
        body = data.get("response", "")
        raise InvalidJSONError(f"Ollama returned invalid JSON: {body[:200]}") from e
