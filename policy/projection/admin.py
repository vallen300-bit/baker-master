"""Evidence-admin actions for the projection surface (Step 4).

Evidence-admin can approve / revoke / refresh a projection, each AUDITED. Approval
reuses the EXISTING Step-1 lifecycle promotion gate (``propose_promotion`` /
``approve_promotion``) — there is NO new promotion path. Only a human Brisen admin
(``director`` / ``evidence_admin``) may run these; AI proposers and external
principals are rejected (the lifecycle gate also enforces the human-ratify rule, this
is defence in depth + a clear audited denial).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from policy import lifecycle
from policy.audit import AuditSink, default_sink
from policy.models import EvidenceItem, LifecycleState, Org, Principal
from policy.projection.models import (
    ADMIN_ROLES,
    ProjectionAuditLog,
    ProjectionItem,
    ProjectionState,
)


class ProjectionAdminDenied(RuntimeError):
    """Raised when a non-human / non-Brisen-admin attempts an evidence-admin action."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(f"projection admin denied: {reason_code}")
        self.reason_code = reason_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_human_admin(actor: Principal) -> None:
    if actor.is_ai or actor.org is not Org.BRISEN or actor.role not in ADMIN_ROLES:
        raise ProjectionAdminDenied("requires_human_brisen_evidence_admin")


def _audit(actor: Principal, event_type: str, *, projection_item_id, allow, reason,
           audience_role="") -> ProjectionAuditLog:
    return ProjectionAuditLog(
        event_type=event_type,
        audience_role=audience_role,
        projection_item_id=projection_item_id,
        actor_org=getattr(actor.org, "value", str(actor.org)),
        actor_role=actor.role,
        actor_is_ai=actor.is_ai,
        allow=allow,
        reason=reason,
        timestamp=_now(),
    )


def approve_projection(
    item: EvidenceItem,
    admin: Principal,
    *,
    rationale: str,
    confidence: Optional[float] = None,
    source_refs: tuple[str, ...] = (),
    sink: Optional[AuditSink] = None,
    transition_recorder: Optional[Callable] = None,
    promotion_recorder: Optional[Callable] = None,
    audit_recorder: Optional[Callable[[ProjectionAuditLog], None]] = None,
) -> ProjectionAuditLog:
    """Approve a verified_evidence item for external projection by promoting it to
    ``shared_view`` THROUGH the existing Step-1 lifecycle gate (AC5). Audited.

    Raises ``ProjectionAdminDenied`` for a non-human/non-Brisen-admin actor BEFORE any
    promotion attempt; the lifecycle gate independently enforces the human-ratify rule.
    """

    try:
        _require_human_admin(admin)
    except ProjectionAdminDenied as exc:
        rec = _audit(admin, "approve", projection_item_id=item.object_id,
                     allow=False, reason=exc.reason_code)
        if audit_recorder is not None:
            audit_recorder(rec)
        raise

    sink = sink or default_sink()
    proposal = lifecycle.propose_promotion(item, admin, rationale=rationale,
                                           source_evidence=source_refs, sink=sink)
    lifecycle.approve_promotion(
        item, admin, proposal, confidence=confidence, source_refs=source_refs,
        sink=sink, transition_recorder=transition_recorder,
        promotion_recorder=promotion_recorder,
    )
    rec = _audit(admin, "approve", projection_item_id=item.object_id, allow=True,
                 reason="promoted_to_shared_view")
    if audit_recorder is not None:
        audit_recorder(rec)
    return rec


def revoke_projection(
    projection_item: ProjectionItem,
    admin: Principal,
    *,
    reason: str,
    audit_recorder: Optional[Callable[[ProjectionAuditLog], None]] = None,
) -> ProjectionAuditLog:
    """Revoke a live projection (AC5). The item leaves the external view but the audit
    row is RETAINED (test 8). Human Brisen admin only."""

    try:
        _require_human_admin(admin)
    except ProjectionAdminDenied as exc:
        rec = _audit(admin, "revoke",
                     projection_item_id=projection_item.projection_item_id,
                     allow=False, reason=exc.reason_code,
                     audience_role=projection_item.audience_role.value)
        if audit_recorder is not None:
            audit_recorder(rec)
        raise

    projection_item.revoked_at = _now()
    projection_item.revoked_by = admin.role
    projection_item.revoke_reason = reason
    projection_item.projection_state = ProjectionState.REVOKED
    rec = _audit(admin, "revoke",
                 projection_item_id=projection_item.projection_item_id,
                 allow=True, reason=reason,
                 audience_role=projection_item.audience_role.value)
    if audit_recorder is not None:
        audit_recorder(rec)
    return rec


def refresh_projection(
    projection_item: ProjectionItem,
    admin: Principal,
    *,
    stale: bool,
    audit_recorder: Optional[Callable[[ProjectionAuditLog], None]] = None,
) -> ProjectionAuditLog:
    """Refresh a projection's freshness state (AC5). If the underlying evidence is
    stale, mark ``stale_projection`` (routes internally to Execution Roadmap, test 8).
    Human Brisen admin only."""

    _require_human_admin(admin)
    if stale:
        projection_item.projection_state = ProjectionState.STALE_PROJECTION
    rec = _audit(admin, "refresh",
                 projection_item_id=projection_item.projection_item_id,
                 allow=True, reason="stale" if stale else "fresh",
                 audience_role=projection_item.audience_role.value)
    if audit_recorder is not None:
        audit_recorder(rec)
    return rec
