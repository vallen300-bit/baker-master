"""Cost cap + circuit breaker gate for Step 5 Opus synthesis.

Pre-call check that Step 5 must clear before calling ``call_opus``. Two
independent defenses:

    1. Daily cap (€50 Director-ratified, 2026-04-18).
       ``SELECT COALESCE(SUM(cost_usd), 0) FROM kbl_cost_ledger WHERE
        ts::date = NOW()::date`` — if today's running total plus the
        pre-call estimate would blow the cap, return DAILY_CAP_EXCEEDED.

    2. Circuit breaker (across-signal consecutive-failure count).
       Reads ``consecutive_failures`` from the ``kbl_circuit_breaker``
       row keyed ``opus_step5``. 3+ consecutive failures = open; signal
       is parked at ``paused_cost_cap`` until the probe resets. In-signal
       R3 retries do NOT increment this counter — only across-signal
       R3-exhausts do.

Currency note: ``kbl_cost_ledger.cost_usd`` is treated as EUR for Phase 1
— Director ratified a €50 cap (brief §9.2 reconciliation from the stale
$15 USD). Column name stays ``cost_usd`` to avoid a cross-cutting
migration; Phase 2 rationalizes naming alongside real multi-ccy handling.

Circuit breaker scope:
    - Opus call step (Step 5). Distinct from the pre-existing
      ``anthropic_circuit_open`` state in ``kbl_runtime_state`` — that
      one tracks per-call 5xx ladders inside a single invocation; this
      one tracks across-signal R3 failures.

Open question parked for KBL-C: probe-reset cadence. Brief §9.2 suggests
60s; inline probe during ``can_fire_step5()`` is acceptable — we do not
schedule a separate cron here. Phase 2 separates concern.
"""
from __future__ import annotations

import logging as _stdlib_logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

logger = _stdlib_logging.getLogger(__name__)

# ---------------------------- constants ----------------------------

_DAILY_CAP_ENV = "KBL_COST_DAILY_CAP_EUR"
_DEFAULT_DAILY_CAP_EUR = Decimal("50.00")

_FAILURE_THRESHOLD_ENV = "KBL_CB_CONSECUTIVE_FAILURES"
_DEFAULT_FAILURE_THRESHOLD = 3

_PROBE_INTERVAL_SEC_ENV = "KBL_CB_PROBE_INTERVAL_SEC"
_DEFAULT_PROBE_INTERVAL_SEC = 60

_CIRCUIT_KEY = "opus_step5"

# Pre-call estimate — token counts derived heuristically from prompt
# length. Conservative (overestimate) to avoid a last-€ call that
# actually exceeds the cap at settle time.
_PRICE_OPUS_INPUT_PER_M = Decimal(os.getenv("PRICE_OPUS4_IN", "15.00"))
_PRICE_OPUS_OUTPUT_PER_M = Decimal(os.getenv("PRICE_OPUS4_OUT", "75.00"))
_ESTIMATE_CHARS_PER_TOKEN = Decimal("4")
_ESTIMATE_MAX_OUTPUT_TOKENS = Decimal("4096")


# ---------------------------- decision enum ----------------------------


class CostDecision(str, Enum):
    """The three pre-call gate outcomes."""

    FIRE = "fire"
    DAILY_CAP_EXCEEDED = "daily_cap_exceeded"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"


# ---------------------------- env readers ----------------------------


def _get_daily_cap_eur() -> Decimal:
    """Parse ``KBL_COST_DAILY_CAP_EUR``. Malformed / negative → default."""
    raw = os.environ.get(_DAILY_CAP_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_DAILY_CAP_EUR
    try:
        parsed = Decimal(raw.strip())
    except InvalidOperation:
        logger.warning(
            "invalid %s=%r — falling back to default €%s",
            _DAILY_CAP_ENV,
            raw,
            _DEFAULT_DAILY_CAP_EUR,
        )
        return _DEFAULT_DAILY_CAP_EUR
    if parsed <= 0:
        logger.warning(
            "non-positive %s=%r — falling back to default €%s",
            _DAILY_CAP_ENV,
            raw,
            _DEFAULT_DAILY_CAP_EUR,
        )
        return _DEFAULT_DAILY_CAP_EUR
    return parsed


def _get_failure_threshold() -> int:
    raw = os.environ.get(_FAILURE_THRESHOLD_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_FAILURE_THRESHOLD
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r — falling back to default %d",
            _FAILURE_THRESHOLD_ENV,
            raw,
            _DEFAULT_FAILURE_THRESHOLD,
        )
        return _DEFAULT_FAILURE_THRESHOLD
    if parsed <= 0:
        return _DEFAULT_FAILURE_THRESHOLD
    return parsed


def _get_probe_interval_sec() -> int:
    raw = os.environ.get(_PROBE_INTERVAL_SEC_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_PROBE_INTERVAL_SEC
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_PROBE_INTERVAL_SEC
    return parsed if parsed > 0 else _DEFAULT_PROBE_INTERVAL_SEC


# ---------------------------- today's spend ----------------------------


def _today_spent(conn: Any) -> Decimal:
    """Sum ``kbl_cost_ledger.cost_usd`` for today UTC. See module docstring
    for the EUR-treated-as-USD note — cost_usd is the single-ccy column."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) "
            "FROM kbl_cost_ledger "
            "WHERE ts::date = (NOW() AT TIME ZONE 'UTC')::date"
        )
        row = cur.fetchone()
    if row is None:
        return Decimal("0")
    value = row[0]
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


# ---------------------------- pre-call cost estimate ----------------------------


def _estimate_step5_cost(signal: dict[str, Any]) -> Decimal:
    """Conservative per-signal Opus cost estimate in EUR.

    ``signal`` is a dict with at least the keys Step 5 has available
    after Steps 1-4: ``signal_text`` (raw signal), ``primary_matter``,
    ``related_matters``, plus any ``prompt_overhead_chars`` the caller
    wants to add (system template size). Missing keys → zero contribution.

    Intentionally simple: char-length / 4 → tokens, multiplied by the
    Opus input rate; add the fixed max-output allowance at the output
    rate. Prompt-caching hits are ignored in the estimate (it's
    conservative — the eventual settle cost is lower or equal).
    """
    signal_text = signal.get("signal_text") or ""
    overhead_chars = signal.get("prompt_overhead_chars") or 0
    total_chars = Decimal(len(signal_text) + int(overhead_chars))
    estimated_input_tokens = total_chars / _ESTIMATE_CHARS_PER_TOKEN
    input_cost = estimated_input_tokens * _PRICE_OPUS_INPUT_PER_M
    output_cost = _ESTIMATE_MAX_OUTPUT_TOKENS * _PRICE_OPUS_OUTPUT_PER_M
    total = (input_cost + output_cost) / Decimal("1000000")
    # Round up to the nearest cent — a sub-cent error rounding down at
    # the cap boundary would let a call through that the audit rejects.
    return total.quantize(Decimal("0.01")) if total > 0 else Decimal("0")


# ---------------------------- circuit breaker reads ----------------------------


def _load_circuit_state(conn: Any) -> tuple[int, Optional[datetime], Optional[datetime]]:
    """Return ``(consecutive_failures, opened_at, last_probe_at)`` for the
    Opus Step 5 circuit. Missing row → (0, None, None) — the migration
    seeds the row, but we stay defensive for pre-migration test envs."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT consecutive_failures, opened_at, last_probe_at "
            "FROM kbl_circuit_breaker "
            "WHERE circuit_key = %s",
            (_CIRCUIT_KEY,),
        )
        row = cur.fetchone()
    if row is None:
        return 0, None, None
    count, opened_at, last_probe_at = row
    return int(count or 0), opened_at, last_probe_at


def _is_circuit_open(
    consecutive_failures: int,
    opened_at: Optional[datetime],
    last_probe_at: Optional[datetime],
    threshold: int,
    probe_interval_sec: int,
    now: Optional[datetime] = None,
) -> bool:
    """Decide whether the circuit is currently open.

    Opens at ``consecutive_failures >= threshold``. Once open, stays
    open until either (a) a probe resets the counter (handled by
    ``record_opus_success`` on the next successful call) or (b) the
    caller explicitly calls ``reset_opus_circuit()``. The probe-
    interval cooldown is informational — it gives operators a clear
    timeline for recovery — but this pure function just answers the
    open/closed question.
    """
    if consecutive_failures < threshold:
        return False
    if opened_at is None:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    # If a probe has fired since the circuit opened, and it's been
    # longer than the probe interval, honor the probe attempt — caller
    # flips state on success/failure. If no probe since open, still open.
    if last_probe_at is None:
        return True
    if last_probe_at <= opened_at:
        return True
    # A probe happened post-open; respect the cooldown until the next
    # probe window. The actual reset comes from record_opus_success.
    cooldown_until = last_probe_at + timedelta(seconds=probe_interval_sec)
    return now < cooldown_until


# ---------------------------- circuit breaker writes ----------------------------


def record_opus_success(conn: Any) -> None:
    """Reset the circuit after a successful Opus call.

    Zeroes ``consecutive_failures`` and clears ``opened_at`` — the
    circuit is now closed. ``last_probe_at`` is bumped to NOW so the
    next telemetry query shows the recovery moment.

    Caller owns the commit (transaction-boundary contract — see
    ``kbl/pipeline_tick.py`` docstring).
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE kbl_circuit_breaker SET "
            "  consecutive_failures = 0, "
            "  opened_at = NULL, "
            "  last_failure_at = last_failure_at, "
            "  last_probe_at = NOW(), "
            "  updated_by = 'opus_step5' "
            "WHERE circuit_key = %s",
            (_CIRCUIT_KEY,),
        )


def record_opus_failure(conn: Any) -> int:
    """Increment consecutive_failures after an R3-exhausted Opus call.

    Returns the new counter value so the caller can decide whether to
    trip the circuit (the threshold compare is in ``can_fire_step5``).
    Sets ``opened_at`` = NOW when the counter first hits the threshold
    — subsequent failures don't update it.

    Caller owns the commit.
    """
    threshold = _get_failure_threshold()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE kbl_circuit_breaker SET "
            "  consecutive_failures = consecutive_failures + 1, "
            "  last_failure_at = NOW(), "
            "  opened_at = COALESCE(opened_at, "
            "               CASE WHEN consecutive_failures + 1 >= %s "
            "                    THEN NOW() ELSE NULL END), "
            "  updated_by = 'opus_step5' "
            "WHERE circuit_key = %s "
            "RETURNING consecutive_failures",
            (threshold, _CIRCUIT_KEY),
        )
        row = cur.fetchone()
    if row is None:
        # Defensive — migration seeds the row; only reachable pre-migration.
        return 0
    return int(row[0])


def reset_opus_circuit(conn: Any) -> None:
    """Operator-initiated reset. Wipes the counter + timestamps."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE kbl_circuit_breaker SET "
            "  consecutive_failures = 0, "
            "  opened_at = NULL, "
            "  last_probe_at = NULL, "
            "  updated_by = 'operator_reset' "
            "WHERE circuit_key = %s",
            (_CIRCUIT_KEY,),
        )


# ---------------------------- public entry ----------------------------


def can_fire_step5(conn: Any, signal: dict[str, Any]) -> CostDecision:
    """Pre-call gate. Returns ``FIRE`` when Step 5 should call Opus.

    Evaluation order:
        1. Circuit breaker: if open and still inside the probe cooldown,
           return ``CIRCUIT_BREAKER_OPEN``.
        2. Daily cap: today's spend + pre-call estimate > cap →
           ``DAILY_CAP_EXCEEDED``.
        3. Otherwise → ``FIRE``.

    Args:
        conn: live psycopg connection (caller owns lifecycle).
        signal: dict of fields needed for the cost estimate. See
            ``_estimate_step5_cost`` for the expected shape.
    """
    failures, opened_at, last_probe_at = _load_circuit_state(conn)
    threshold = _get_failure_threshold()
    probe_interval = _get_probe_interval_sec()
    if _is_circuit_open(
        failures, opened_at, last_probe_at, threshold, probe_interval
    ):
        return CostDecision.CIRCUIT_BREAKER_OPEN

    cap = _get_daily_cap_eur()
    today = _today_spent(conn)
    estimate = _estimate_step5_cost(signal)
    if today + estimate > cap:
        return CostDecision.DAILY_CAP_EXCEEDED

    return CostDecision.FIRE
