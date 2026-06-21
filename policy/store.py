"""Parameterized-SQL persistence for the policy core + fail-closed visible-item query.

This is the DB boundary. The engine + lifecycle are pure; this module persists the
object model, the audit trail (``DbAuditSink``), transitions, and promotions, and
provides ``query_visible_items`` — the read path that filters candidate rows
through ``engine.evaluate`` server-side (AC2) and FAILS CLOSED on any DB/config
problem (AC9 / T10): a missing policy store returns a visible error with NO object
payload, never an unfiltered list.

Parameterized SQL only (no string interpolation of values). Every DB call is
wrapped; the ``except`` re-raises ``PolicyUnavailableError`` (fail closed) rather
than returning objects.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Optional

from policy.audit import AuditSink
from policy.engine import evaluate, partner_projection
from policy.models import (
    Action,
    AuditEvent,
    Classification,
    EvidenceItem,
    LifecycleState,
    ObjectType,
    Org,
    Principal,
    Sensitivity,
)

logger = logging.getLogger("policy.store")

# A connection factory is a context manager yielding a psycopg2 connection.
ConnFactory = Callable[[], Any]


def _default_conn_factory() -> Any:
    # Imported lazily so unit tests that never touch the DB don't import psycopg2
    # config, and so a missing DATABASE_URL surfaces only on actual DB use.
    from kbl.db import get_conn

    return get_conn()


class PolicyUnavailableError(RuntimeError):
    """Raised when the policy store cannot be reached. ALWAYS fail closed (T10).

    Callers must surface this as a visible error and return NO object payload —
    never degrade to returning unfiltered objects.
    """


# --------------------------------------------------------------------------- #
# Serialisation helpers
# --------------------------------------------------------------------------- #
def _enum_val(v: Any) -> Any:
    return getattr(v, "value", v)


def _row_to_item(row: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        object_id=row["object_id"],
        object_type=ObjectType(row["object_type"]),
        classification=Classification(row["classification"]),
        lifecycle_state=LifecycleState(row["lifecycle_state"]),
        owner_org=Org(row["owner_org"]),
        owner=row.get("owner"),
        sensitivity=Sensitivity(row["sensitivity"]) if row.get("sensitivity") else None,
        allowed_orgs=frozenset(Org(o) for o in (row.get("allowed_orgs") or [])),
        allowed_roles=frozenset(row.get("allowed_roles") or []),
        confidence=row.get("confidence"),
        source_refs=tuple(row.get("source_refs") or []),
        source_type=row.get("source_type"),
        claim=row.get("claim"),
        freshness=row.get("freshness"),
        last_reviewed=row.get("last_reviewed"),
        raw_body=row.get("raw_body"),
        title=row.get("title"),
    )


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def save_item(item: EvidenceItem, *, conn_factory: ConnFactory = _default_conn_factory) -> None:
    """Upsert an evidence_item keyed on object_id. Parameterized SQL only."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO policy_evidence_items (
                        object_id, object_type, classification, lifecycle_state,
                        sensitivity, owner_org, owner, allowed_orgs, allowed_roles,
                        confidence, source_refs, source_type, claim, freshness,
                        last_reviewed, raw_body, title, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
                            %s::jsonb, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (object_id) DO UPDATE SET
                        object_type     = EXCLUDED.object_type,
                        classification  = EXCLUDED.classification,
                        lifecycle_state = EXCLUDED.lifecycle_state,
                        sensitivity     = EXCLUDED.sensitivity,
                        owner_org       = EXCLUDED.owner_org,
                        owner           = EXCLUDED.owner,
                        allowed_orgs    = EXCLUDED.allowed_orgs,
                        allowed_roles   = EXCLUDED.allowed_roles,
                        confidence      = EXCLUDED.confidence,
                        source_refs     = EXCLUDED.source_refs,
                        source_type     = EXCLUDED.source_type,
                        claim           = EXCLUDED.claim,
                        freshness       = EXCLUDED.freshness,
                        last_reviewed   = EXCLUDED.last_reviewed,
                        raw_body        = EXCLUDED.raw_body,
                        title           = EXCLUDED.title,
                        updated_at      = now()
                    """,
                    (
                        item.object_id,
                        _enum_val(item.object_type),
                        _enum_val(item.classification),
                        _enum_val(item.lifecycle_state),
                        _enum_val(item.sensitivity) if item.sensitivity else None,
                        _enum_val(item.owner_org),
                        item.owner,
                        json.dumps(sorted(_enum_val(o) for o in item.allowed_orgs)),
                        json.dumps(sorted(item.allowed_roles)),
                        item.confidence,
                        json.dumps(list(item.source_refs)),
                        item.source_type,
                        item.claim,
                        item.freshness,
                        item.last_reviewed,
                        item.raw_body,
                        item.title,
                    ),
                )
            conn.commit()
    except PolicyUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail loud, surface as unavailable
        logger.exception("policy.store.save_item failed for object_id=%s", item.object_id)
        raise PolicyUnavailableError(str(exc)) from exc


def load_item(
    object_id: str, *, conn_factory: ConnFactory = _default_conn_factory
) -> Optional[EvidenceItem]:
    """Load one evidence_item by object_id, or ``None`` if absent. Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM policy_evidence_items WHERE object_id = %s",
                    (object_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d[0] for d in cur.description]
                return _row_to_item(dict(zip(cols, row)))
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("policy.store.load_item failed for object_id=%s", object_id)
        raise PolicyUnavailableError(str(exc)) from exc


def record_transition(record: Any, *, conn_factory: ConnFactory = _default_conn_factory) -> None:
    """Persist a ``lifecycle.TransitionRecord``. Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO policy_lifecycle_transitions (
                        object_id, actor_org, actor_role, prior_state, new_state,
                        source_refs, confidence, last_reviewed, override_reason)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        record.object_id,
                        record.actor_org,
                        record.actor_role,
                        record.prior_state,
                        record.new_state,
                        json.dumps(list(record.source_refs)),
                        record.confidence,
                        record.last_reviewed,
                        record.override_reason,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("policy.store.record_transition failed")
        raise PolicyUnavailableError(str(exc)) from exc


def record_promotion(record: Any, *, conn_factory: ConnFactory = _default_conn_factory) -> None:
    """Persist a ``lifecycle.PromotionRecord`` (AC6). Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO policy_promotions (
                        object_id, proposer_org, proposer_role, approver_org,
                        approver_role, approval_timestamp, rationale, source_evidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        record.object_id,
                        record.proposer_org,
                        record.proposer_role,
                        record.approver_org,
                        record.approver_role,
                        record.approval_timestamp,
                        record.rationale,
                        json.dumps(list(record.source_evidence)),
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("policy.store.record_promotion failed")
        raise PolicyUnavailableError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Read path — same control, fail closed (AC2 / T10)
# --------------------------------------------------------------------------- #
def query_visible_items(
    principal: Principal,
    action: Action = Action.READ,
    *,
    object_ids: Optional[List[str]] = None,
    project: bool = False,
    conn_factory: ConnFactory = _default_conn_factory,
    sink: Optional[AuditSink] = None,
) -> List[Any]:
    """Return ONLY the items ``principal`` may ``action``, filtered server-side.

    Loads candidate rows (all, or the given ``object_ids``) and runs
    ``engine.evaluate`` on each — the SAME policy function every other surface
    uses (AC2). ``project=True`` returns partner-safe projections (AC7) instead of
    full items, for external callers.

    Fail-closed (T10): if the store is unreachable or the query errors, raises
    ``PolicyUnavailableError`` and returns NO payload. There is no fallback that
    returns unfiltered objects.
    """

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if object_ids is not None:
                    cur.execute(
                        "SELECT * FROM policy_evidence_items WHERE object_id = ANY(%s)",
                        (list(object_ids),),
                    )
                else:
                    cur.execute("SELECT * FROM policy_evidence_items")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 - FAIL CLOSED: no payload on any error
        logger.exception("policy.store.query_visible_items failed — failing closed")
        raise PolicyUnavailableError(str(exc)) from exc

    visible: List[Any] = []
    for row in rows:
        item = _row_to_item(row)
        decision = evaluate(principal, item, action, sink=sink)
        if not decision.allow:
            continue
        if project:
            # partner_projection re-evaluates (defensive double-check) + redacts.
            visible.append(partner_projection(principal, item, sink=sink))
        else:
            visible.append(item)
    return visible


# --------------------------------------------------------------------------- #
# DB audit sink (AC9)
# --------------------------------------------------------------------------- #
class DbAuditSink:
    """Persist ``AuditEvent``s to ``policy_audit_log``.

    A write failure is logged, never raised: the policy decision is already made
    and returned by the time the sink runs, so an audit-store outage must not flip
    a deny to an allow (T10). Use a ``LoggingAuditSink`` as the in-process fallback.
    """

    def __init__(self, conn_factory: ConnFactory = _default_conn_factory) -> None:
        self._conn_factory = conn_factory

    def write(self, event: AuditEvent) -> None:
        try:
            with self._conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO policy_audit_log (
                            event_type, principal_org, principal_role, action,
                            object_id, object_type, allow, reason_code, detail)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            event.event_type,
                            event.principal_org,
                            event.principal_role,
                            event.action,
                            event.object_id,
                            event.object_type,
                            event.allow,
                            event.reason_code,
                            json.dumps(dict(event.detail)),
                        ),
                    )
                conn.commit()
        except Exception:  # noqa: BLE001 - audit write must never break the caller
            logger.exception("policy.store.DbAuditSink write failed (non-fatal)")
