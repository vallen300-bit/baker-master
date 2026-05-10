"""Tier B autonomous-action budget runtime.

Forward-looking gate: future call-sites (B4 6-phase loop, B5 substrate push,
Cortex Phase 5) call ``enforce_tier_b(action)`` BEFORE committing. Returns
``Decision(verdict='PASS' | 'PAUSE_REQUIRED', ...)``. On PAUSE_REQUIRED the
candidate is queued in ``tier_b_pending``; Director ratify card is emitted
via the GOLD visual template (separate workflow domain — see
``orchestrator/tier_b_ratify.py``).

Caps (D8 Conservative tier, Director-ratified 2026-05-10):
    PER_ACTION    = €100
    DAILY_POOL    = €500
    MONTHLY_POOL  = €2,500
    Reset         = 1st of calendar month, 00:00 UTC

Cost source (Q2 mixed model):
    Primary  : ``tier_b_action_classes`` registry lookup
    Fallback : committer self-declares with ``action_class='novel:<descriptor>'``
               + ``self_cost_eur`` (flagged for AID monthly review)

Atomicity: cost-resolve, counter-read, and pending-insert all run inside a
single SERIALIZABLE transaction so two simultaneous committers can't both
see headroom and together exceed cap. Postgres surfaces serialization
failures as exceptions; the caller is expected to retry.
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


@dataclass(frozen=True)
class TierBAction:
    """Candidate Tier-B action under enforcement."""

    action_class: str
    committer_agent: str
    payload: dict
    self_cost_eur: Optional[float] = None


@dataclass(frozen=True)
class Decision:
    """Result of ``enforce_tier_b()`` — caller routes by ``verdict``."""

    verdict: Literal["PASS", "PAUSE_REQUIRED"]
    cost_eur: float
    reason: str
    pending_id: Optional[int] = None


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
        """Return ``(cost_eur, source_tag)``; ``source_tag`` ∈ {registry, self_declared}."""
        if action.action_class.startswith("novel:"):
            if action.self_cost_eur is None:
                raise ValueError(
                    f"action_class={action.action_class!r} requires self_cost_eur"
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
    # Counter math (read-driven)
    # ------------------------------------------------------------------

    def _current_totals(self) -> tuple[float, float]:
        """Return ``(day_total_eur, month_total_eur)`` for committed Tier-B actions.

        UTC calendar boundaries. Excludes paused (uncommitted) candidates.
        """
        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot read Tier-B totals")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B'
                   AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
                """
            )
            day_total = float(cur.fetchone()[0])

            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B'
                   AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
                """
            )
            month_total = float(cur.fetchone()[0])

            cur.close()
            return day_total, month_total
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def enforce(self, action: TierBAction) -> Decision:
        """Decide PASS or PAUSE_REQUIRED for a candidate Tier-B action.

        Atomicity: cost-resolve, counter-read, and pending-insert run inside
        one SERIALIZABLE transaction. Cap evaluation order: per-action →
        daily → monthly. The first cap that would be exceeded wins.
        """
        cost_eur, source_tag = self._resolve_cost(action)

        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot enforce Tier-B")
        # Promote the connection to SERIALIZABLE for the read+insert sequence
        # so two simultaneous committers can't both see headroom and together
        # exceed cap. Postgres surfaces serialization failures as a
        # psycopg2.errors.SerializationFailure exception which propagates to
        # the caller; caller retries.
        old_iso = conn.isolation_level
        try:
            conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
            )
        except Exception:
            # Older psycopg2 / driver edge case — fall back to in-txn SET.
            cur = conn.cursor()
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cur.close()
        try:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
                """
            )
            day_total = float(cur.fetchone()[0])

            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
                """
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

            conn.commit()
            cur.close()
            return Decision(
                verdict="PASS",
                cost_eur=cost_eur,
                reason=(
                    f"PASS via {source_tag} — projected day=€{day_total + cost_eur:.2f}, "
                    f"month=€{month_total + cost_eur:.2f}"
                ),
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            # Restore the connection's isolation level before returning to the
            # pool so the next caller is not surprised by SERIALIZABLE.
            try:
                conn.set_isolation_level(old_iso)
            except Exception:
                pass
            self._store._put_conn(conn)

    @staticmethod
    def _jsonify(payload: dict) -> str:
        return json.dumps(payload, default=str)


def enforce_tier_b(action: TierBAction) -> Decision:
    """Module-level shorthand. Call this from runtime call-sites."""
    return TierBRuntime._get_global_instance().enforce(action)
