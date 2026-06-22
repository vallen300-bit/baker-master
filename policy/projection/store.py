"""Parameterized-SQL persistence for the projection surface (Step 4).

Same discipline as Steps 1-3: parameterized SQL only, every DB call wrapped, and
``except`` FAILS CLOSED (``ProjectionStoreUnavailableError``) — it never returns raw
rows, another audience's items, or a default-public payload (T10). Read paths
(``load_*``) are NON-MUTATING (deputy-codex T8/AC9: viewing/listing mutates nothing).

Persists: ``projection_item`` (internal record — raw source ids stay server-side),
``projection_audit_log`` (approve/revoke/refresh/deny), ``projection_redaction``,
``projection_snapshot`` (view-packet metadata for cache/version tracking).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Mapping, Optional

from policy.projection.models import (
    ProjectionAuditLog,
    ProjectionItem,
    ProjectionRedaction,
)

logger = logging.getLogger("policy.projection.store")

ConnFactory = Callable[[], Any]


def _default_conn_factory() -> Any:
    from kbl.db import get_conn

    return get_conn()


class ProjectionStoreUnavailableError(RuntimeError):
    """Raised when the projection store cannot be reached. ALWAYS fail closed (T10)."""


def _enum(v: Any) -> Any:
    return getattr(v, "value", v)


def save_projection_item(
    item: ProjectionItem, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Upsert a projection_item (internal record). Fail closed on DB error."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projection_item (
                        projection_item_id, audience_role, source_evidence_item_id,
                        lifecycle_state, dashboard_section, display_title,
                        display_summary, evidence_confidence, confidence_reason,
                        source_label_safe, citation_or_provenance_safe, freshness,
                        last_verified_at, owner, reviewer, visibility_reason,
                        redaction_applied, redaction_reason, redaction_reason_safe,
                        action_linked_id, action_safe_text, revoked_at, revoked_by,
                        revoke_reason, audit_trace_id, projection_state, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (projection_item_id) DO UPDATE SET
                        lifecycle_state = EXCLUDED.lifecycle_state,
                        projection_state = EXCLUDED.projection_state,
                        revoked_at = EXCLUDED.revoked_at,
                        revoked_by = EXCLUDED.revoked_by,
                        revoke_reason = EXCLUDED.revoke_reason,
                        redaction_applied = EXCLUDED.redaction_applied,
                        updated_at = now()
                    """,
                    (
                        item.projection_item_id, _enum(item.audience_role),
                        item.source_evidence_item_id, item.lifecycle_state,
                        _enum(item.dashboard_section), item.display_title,
                        item.display_summary, item.evidence_confidence,
                        item.confidence_reason, item.source_label_safe,
                        item.citation_or_provenance_safe, item.freshness,
                        item.last_verified_at, item.owner, item.reviewer,
                        item.visibility_reason, item.redaction_applied,
                        item.redaction_reason, item.redaction_reason_safe,
                        item.action_linked_id, item.action_safe_text,
                        item.revoked_at, item.revoked_by, item.revoke_reason,
                        item.audit_trace_id, _enum(item.projection_state),
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("save_projection_item failed for %s", item.projection_item_id)
        raise ProjectionStoreUnavailableError(str(exc)) from exc


def record_projection_audit(
    audit: ProjectionAuditLog, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Append a projection_audit_log row. Fail closed. Audit is RETAINED across
    revoke (test 8) — this is append-only, never deleted on revoke."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projection_audit_log (
                        event_type, audience_role, projection_item_id, actor_org,
                        actor_role, actor_is_ai, allow, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        audit.event_type, audit.audience_role, audit.projection_item_id,
                        audit.actor_org, audit.actor_role, audit.actor_is_ai,
                        audit.allow, audit.reason,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_projection_audit failed")
        raise ProjectionStoreUnavailableError(str(exc)) from exc


def record_redaction(
    redaction: ProjectionRedaction, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Append a projection_redaction row (what was removed + safe reason). Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projection_redaction (
                        projection_item_id, removed_field, reason_safe)
                    VALUES (%s, %s, %s)
                    """,
                    (redaction.projection_item_id, redaction.removed_field,
                     redaction.reason_safe),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_redaction failed")
        raise ProjectionStoreUnavailableError(str(exc)) from exc


def save_snapshot(
    audience_role: str,
    policy_version: str,
    projection_version: str,
    visible_count: int,
    fingerprint: str,
    *,
    conn_factory: ConnFactory = _default_conn_factory,
) -> None:
    """Persist view-packet snapshot metadata (cache/version tracking). Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projection_snapshot (
                        audience_role, policy_version, projection_version,
                        visible_count, fingerprint)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (audience_role, policy_version, projection_version,
                     visible_count, fingerprint),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("save_snapshot failed")
        raise ProjectionStoreUnavailableError(str(exc)) from exc


def load_projection_items(
    audience_role: str,
    *,
    limit: int = 200,
    conn_factory: ConnFactory = _default_conn_factory,
) -> List[Mapping[str, Any]]:
    """NON-MUTATING read of stored projection_item rows for an audience (bounded).

    Fail closed: any DB error raises rather than returning a partial/default payload.
    """

    limit = max(1, min(int(limit), 500))
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM projection_item WHERE audience_role = %s "
                    "ORDER BY id LIMIT %s",
                    (audience_role, limit),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("load_projection_items failed — failing closed")
        raise ProjectionStoreUnavailableError(str(exc)) from exc
