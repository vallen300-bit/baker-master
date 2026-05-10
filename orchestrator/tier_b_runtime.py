"""Tier B autonomous-action budget runtime.

Forward-looking gate: future call-sites (Cortex Phase 5, B5 substrate
push, autonomous senders) call ``enforce_tier_b(action)`` BEFORE the
external side effect. On PASS the runtime reserves the budget inside a
SERIALIZABLE transaction (writes a ``baker_actions`` row with
``committed_at=NULL`` + ``reserved_at=NOW()``) and returns a
``reservation_id``. Caller performs the side effect, then calls
``confirm_tier_b(reservation_id)`` (success) or
``cancel_tier_b(reservation_id)`` (failure). On PAUSE_REQUIRED the
candidate is queued in ``tier_b_pending``; Director ratify card emitted
via ``orchestrator/tier_b_ratify.py``.

Caps (D8 Conservative tier, Director-ratified 2026-05-10):
    PER_ACTION    = €100
    DAILY_POOL    = €500
    MONTHLY_POOL  = €2,500
    Reset         = 1st of calendar month, 00:00 UTC

Cost source (Q2 mixed model):
    Primary  : ``tier_b_action_classes`` registry lookup
    Fallback : committer self-declares with ``action_class='novel:<descriptor>'``
               + ``self_cost_eur`` (flagged for AID monthly review)

Pool-wide atomicity (V2, Pattern B reservation-row, Director-ratified
2026-05-10 PM):
    PASS path INSERTs a reservation row inside SERIALIZABLE. SSI sees the
    rw-anti-dependency between the cap-read SELECT and the reservation
    INSERT; concurrent enforcers at the same day/month bucket get one
    retried (psycopg2.errors.SerializationFailure surfaces to caller, who
    retries the whole ``enforce_tier_b()`` call — second attempt sees the
    new committed/reserved totals and PAUSEs if cap blown).

    Cap reads count both committed actions AND active reservations (those
    with ``reserved_at`` within the 15-min TTL window). Expired
    reservations are swept by ``triggers/tier_b_reservation_sweep.py``
    every 5 min — caller crash between reserve and confirm/cancel
    eventually releases the budget.

    SerializationFailure idempotency: when SSI aborts a transaction, the
    aborted transaction's writes are never committed by Postgres. Caller
    can safely retry ``enforce_tier_b()`` after catching the exception —
    the retry starts clean (no partial reservation row), reads now-updated
    totals (including the winning enforcer's reservation), and
    re-evaluates the cap. No double-reservation risk.

    Audit trail: cancelled or swept reservations are DELETEd (not
    soft-deleted). Intentional — a reservation that was never confirmed
    represents an autonomous action that NEVER EXECUTED, so an audit row
    would mis-state the historical spend record. The PAUSE_REQUIRED path
    remains audited via ``tier_b_pending``; the PASS-then-confirm path is
    audited via the persisted ``baker_actions`` row (committed_at set).

    Caller contract::

        decision = enforce_tier_b(action)
        if decision.verdict == "PAUSE_REQUIRED":
            return   # ratify card already queued in tier_b_pending
        try:
            actually_execute(...)          # external side effect
            confirm_tier_b(decision.reservation_id)
        except Exception:
            cancel_tier_b(decision.reservation_id)
            raise
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal, Optional

import psycopg2.extensions

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)

# Cap constants — Director-ratified D8 Conservative tier 2026-05-10.
PER_ACTION_CAP_EUR = 100.00
DAILY_POOL_CAP_EUR = 500.00
MONTHLY_POOL_CAP_EUR = 2500.00

# Reservation TTL — Director-ratified 2026-05-10 PM. After this window
# without a confirm_tier_b()/cancel_tier_b() call, the sweep job deletes
# the reservation; budget returns to the pool. Tighter window pressures
# slow callers; looser window ties up cap on caller crash.
RESERVATION_TTL_MINUTES = 15


@dataclass(frozen=True)
class TierBAction:
    """Candidate Tier-B action under enforcement."""

    action_class: str
    committer_agent: str
    payload: dict
    self_cost_eur: Optional[float] = None


@dataclass(frozen=True)
class Decision:
    """Result of ``enforce_tier_b()`` — caller routes by ``verdict``.

    On PASS, ``reservation_id`` is the ``baker_actions.id`` of the row
    just reserved; caller MUST call confirm_tier_b/cancel_tier_b within
    ``RESERVATION_TTL_MINUTES`` or the sweep job will reclaim the budget.

    On PAUSE_REQUIRED, ``pending_id`` is the ``tier_b_pending.id`` row
    waiting on Director ratify.
    """

    verdict: Literal["PASS", "PAUSE_REQUIRED"]
    cost_eur: float
    reason: str
    reservation_id: Optional[int] = None  # set on PASS
    pending_id: Optional[int] = None      # set on PAUSE_REQUIRED


class TierBRuntime:
    """Singleton: budget enforcement gate. Use ``_get_global_instance()``."""

    _instance = None

    @classmethod
    def _get_global_instance(cls) -> "TierBRuntime":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._store = SentinelStoreBack._get_global_instance()

    # ------------------------------------------------------------------
    # Cost resolution
    # ------------------------------------------------------------------

    def _resolve_cost(self, action: TierBAction) -> tuple[float, str]:
        """Resolve (cost_eur, source_tag) for an action.

        ``source_tag`` ∈ {registry, self_declared}. Runs against a separate
        pooled connection at default isolation — NOT inside enforce()'s
        SERIALIZABLE txn. Registry rarely changes during a cycle so the
        read-skew window is acceptable for V1.
        """
        if action.action_class.startswith("novel:"):
            if action.self_cost_eur is None:
                raise ValueError(
                    f"action_class={action.action_class!r} requires self_cost_eur"
                )
            if action.self_cost_eur < 0:
                raise ValueError(
                    f"self_cost_eur must be non-negative (got {action.self_cost_eur}); "
                    f"negative values would bypass daily/monthly cap math"
                )
            return float(action.self_cost_eur), "self_declared"

        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot resolve action_class cost")
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT eur_cost FROM tier_b_action_classes "
                "WHERE class_name = %s AND deprecated_at IS NULL "
                "LIMIT 1",
                (action.action_class,),
            )
            row = cur.fetchone()
            cur.close()
            if row is None:
                raise ValueError(
                    f"unknown action_class {action.action_class!r}; "
                    f"register it in tier_b_action_classes or use 'novel:<descriptor>' with self_cost_eur"
                )
            return float(row[0]), "registry"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    # ------------------------------------------------------------------
    # Enforcement (Pattern B reservation-row)
    # ------------------------------------------------------------------

    def enforce(self, action: TierBAction) -> Decision:
        """Decide PASS or PAUSE_REQUIRED.

        Pool-wide atomicity guaranteed by SERIALIZABLE: cap-reads include
        active reservations; PASS path INSERTs a reservation row before
        commit. Concurrent enforcers at the same bucket overlap their
        read+write sets; SSI raises ``SerializationFailure`` on one,
        caller retries the whole ``enforce_tier_b()`` call.
        """
        cost_eur, source_tag = self._resolve_cost(action)

        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot enforce Tier-B")
        old_iso = conn.isolation_level
        isolation_set = False
        try:
            try:
                conn.set_isolation_level(
                    psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
                )
                isolation_set = True
            except Exception as primary_exc:
                # Older psycopg2 / driver edge case — fall back to in-txn SET.
                try:
                    cur = conn.cursor()
                    cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    cur.close()
                    isolation_set = True
                except Exception as fallback_exc:
                    # HARD-fail: atomicity argument requires SERIALIZABLE. Do
                    # NOT silently proceed at READ COMMITTED — cap can breach.
                    raise RuntimeError(
                        "failed to set SERIALIZABLE isolation: "
                        f"primary={primary_exc!r}, fallback={fallback_exc!r}"
                    ) from fallback_exc

            cur = conn.cursor()

            # Day-bucket cap read: committed today OR reserved-and-active.
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND (
                       (committed_at IS NOT NULL
                        AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'))
                    OR (committed_at IS NULL
                        AND reserved_at IS NOT NULL
                        AND reserved_at >= NOW() AT TIME ZONE 'UTC'
                                        - (%s || ' minutes')::interval)
                   )
                 LIMIT 100000
                """,
                (str(RESERVATION_TTL_MINUTES),),
            )
            day_total = float(cur.fetchone()[0])

            # Month-bucket cap read: same pattern, monthly window.
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND (
                       (committed_at IS NOT NULL
                        AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC'))
                    OR (committed_at IS NULL
                        AND reserved_at IS NOT NULL
                        AND reserved_at >= NOW() AT TIME ZONE 'UTC'
                                        - (%s || ' minutes')::interval)
                   )
                 LIMIT 100000
                """,
                (str(RESERVATION_TTL_MINUTES),),
            )
            month_total = float(cur.fetchone()[0])

            paused_reason: Optional[str] = None
            if cost_eur > PER_ACTION_CAP_EUR:
                paused_reason = "per_action_cap"
            elif day_total + cost_eur > DAILY_POOL_CAP_EUR:
                paused_reason = "daily_cap"
            elif month_total + cost_eur > MONTHLY_POOL_CAP_EUR:
                paused_reason = "monthly_cap"

            if paused_reason:
                cur.execute(
                    """
                    INSERT INTO tier_b_pending
                        (action_payload, cost_eur, action_class, committer_agent, reason_paused)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self._jsonify(action.payload),
                        cost_eur,
                        action.action_class,
                        action.committer_agent,
                        paused_reason,
                    ),
                )
                pending_id = int(cur.fetchone()[0])
                conn.commit()
                cur.close()
                return Decision(
                    verdict="PAUSE_REQUIRED",
                    cost_eur=cost_eur,
                    reason=(
                        f"{paused_reason} — cost €{cost_eur:.2f}, "
                        f"day=€{day_total:.2f}, month=€{month_total:.2f}"
                    ),
                    pending_id=pending_id,
                )

            # PASS — write reservation row inside the same SERIALIZABLE txn.
            # Critical: this INSERT is what gives SSI the rw-conflict to detect
            # against a concurrent enforcer's day/month-total SELECT.
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, payload, trigger_source, success,
                     tier, cost_eur, committed_at, reserved_at,
                     committer_agent, action_class,
                     self_cost_eur)
                VALUES (
                    'tier_b_reservation', %s::jsonb, 'tier_b_runtime', TRUE,
                    'B', %s, NULL, NOW() AT TIME ZONE 'UTC',
                    %s, %s,
                    %s
                )
                RETURNING id
                """,
                (
                    self._jsonify(action.payload),
                    cost_eur,
                    action.committer_agent,
                    action.action_class,
                    action.self_cost_eur,
                ),
            )
            reservation_id = int(cur.fetchone()[0])
            conn.commit()
            cur.close()
            return Decision(
                verdict="PASS",
                cost_eur=cost_eur,
                reason=(
                    f"PASS via {source_tag} — reserved €{cost_eur:.2f}; "
                    f"projected day=€{day_total + cost_eur:.2f}, "
                    f"month=€{month_total + cost_eur:.2f}"
                ),
                reservation_id=reservation_id,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            # Restore the connection's isolation level before returning to the
            # pool so the next caller is not surprised by SERIALIZABLE. Only
            # touch isolation if we actually changed it; on hard-fail both
            # paths above raise before mutating state.
            if isolation_set:
                try:
                    conn.set_isolation_level(old_iso)
                except Exception:
                    pass
            self._store._put_conn(conn)

    # ------------------------------------------------------------------
    # Reservation lifecycle (Pattern B)
    # ------------------------------------------------------------------

    def confirm(self, reservation_id: int) -> bool:
        """Mark a reservation as committed (post-success).

        Tiny single-row UPDATE — low conflict surface. Returns True iff a
        row was flipped from reserved to committed. Returns False if the
        row was already committed (idempotent retry), was cancelled, or
        was swept (TTL expired before caller called us).
        """
        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot confirm reservation")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE baker_actions
                   SET committed_at = NOW() AT TIME ZONE 'UTC'
                 WHERE id = %s
                   AND committed_at IS NULL
                   AND reserved_at IS NOT NULL
                RETURNING id
                """,
                (reservation_id,),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row is None:
                logger.warning(
                    "confirm_tier_b: reservation_id=%s not found or already committed/swept",
                    reservation_id,
                )
                return False
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    def cancel(self, reservation_id: int) -> bool:
        """Release a reservation (post-failure).

        DELETEs the reservation row — budget returns to the pool. Returns
        True iff a row was deleted; False if already committed (caller
        signalled failure too late) or already swept.
        """
        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot cancel reservation")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM baker_actions
                 WHERE id = %s
                   AND committed_at IS NULL
                   AND reserved_at IS NOT NULL
                RETURNING id
                """,
                (reservation_id,),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row is None:
                logger.warning(
                    "cancel_tier_b: reservation_id=%s not found or already committed",
                    reservation_id,
                )
                return False
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    @staticmethod
    def _jsonify(payload: dict) -> str:
        return json.dumps(payload, default=str)


def enforce_tier_b(action: TierBAction) -> Decision:
    """Module-level shorthand. Call this from runtime call-sites."""
    return TierBRuntime._get_global_instance().enforce(action)


def confirm_tier_b(reservation_id: int) -> bool:
    """Module-level shorthand — mark reservation committed (post-success)."""
    return TierBRuntime._get_global_instance().confirm(reservation_id)


def cancel_tier_b(reservation_id: int) -> bool:
    """Module-level shorthand — release reservation (post-failure)."""
    return TierBRuntime._get_global_instance().cancel(reservation_id)
