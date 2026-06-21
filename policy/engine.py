"""The policy decision function — the single server-side control point.

``evaluate(principal, item, action)`` returns a ``PolicyDecision`` (allow/deny +
reason_code + evaluated inputs). EVERY future surface — search, read, digest,
partner projection, audit, export — calls this same function before constructing a
response (AC2). UI/client filters are never the control.

Design invariants:

* **Default-deny.** The function returns deny unless a rule explicitly allows
  (the final fall-through is ``DENY_DEFAULT``).
* **Fail-closed input validation.** An unknown action / classification / lifecycle
  state / org / role denies immediately — a malicious client cannot widen access
  by passing a bogus category or view param (AC10 negative test, T1).
* **Hard-deny beats allow.** Never-external sensitivity categories deny any
  external principal regardless of classification or explicit grant (AC4, T3).
* **Classification ≠ grant.** A ``partner_safe_*`` tag is necessary, not
  sufficient: lifecycle state, the matching-org check, the explicit
  ``allowed_orgs`` gate, and non-null confidence must ALL pass (ontology #4;
  T6 cross-partner bleed, T7 stale-as-trusted).

The decision is pure (no I/O). Auditing is via an injected sink so the logic is
DB-free and unit-testable while AC9 ("writes audit or structured log") still holds.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from policy.audit import AuditSink, default_sink
from policy.models import (
    EXTERNAL_ALLOWED_ACTIONS,
    NEVER_EXTERNAL_SENSITIVITIES,
    PARTNER_AUDIT_FIELDS,
    PARTNER_SAFE_CLASSES,
    PARTNER_SAFE_FOR_ORG,
    PARTNER_VISIBLE_STATES,
    PROMOTION_APPROVER_ROLES,
    ROLES_BY_ORG,
    Action,
    AuditEvent,
    Classification,
    EvidenceItem,
    LifecycleState,
    Org,
    PolicyDecision,
    Principal,
    Reason,
)


def _evaluated(principal: Principal, item: EvidenceItem, action: Action) -> dict[str, Any]:
    """The inputs the decision was made on (returned in every decision, AC1)."""

    return {
        "principal_org": getattr(principal.org, "value", principal.org),
        "role": principal.role,
        "is_ai": principal.is_ai,
        "object_type": getattr(item.object_type, "value", item.object_type),
        "object_id": item.object_id,
        "action": getattr(action, "value", action),
        "lifecycle_state": getattr(item.lifecycle_state, "value", item.lifecycle_state),
        "classification": getattr(item.classification, "value", item.classification),
        "sensitivity": getattr(item.sensitivity, "value", item.sensitivity)
        if item.sensitivity is not None
        else None,
        "allowed_orgs": sorted(getattr(o, "value", o) for o in item.allowed_orgs),
        "confidence_present": item.confidence is not None,
    }


def _decide(principal: Principal, item: EvidenceItem, action: Action) -> PolicyDecision:
    """Pure decision pipeline. First matching rule wins; otherwise default-deny."""

    ev = _evaluated(principal, item, action)

    def deny(reason: Reason) -> PolicyDecision:
        return PolicyDecision(allow=False, reason_code=reason, evaluated=ev)

    def allow(reason: Reason) -> PolicyDecision:
        return PolicyDecision(allow=True, reason_code=reason, evaluated=ev)

    # --- 0. input validation — fail closed on any unknown enum value (T1, AC10) ---
    if not isinstance(action, Action):
        return deny(Reason.INVALID_ACTION)
    if not isinstance(item.classification, Classification):
        return deny(Reason.INVALID_CLASSIFICATION)
    if not isinstance(item.lifecycle_state, LifecycleState):
        return deny(Reason.INVALID_LIFECYCLE_STATE)
    if not isinstance(principal.org, Org):
        return deny(Reason.UNKNOWN_ORG)
    if principal.role not in ROLES_BY_ORG.get(principal.org, frozenset()):
        return deny(Reason.INVALID_ROLE_FOR_ORG)

    external = principal.is_external

    # --- 1. HARD never-external deny — beats any allow (AC4, T3 misclassification) ---
    if external and item.sensitivity in NEVER_EXTERNAL_SENSITIVITIES:
        return deny(Reason.HARD_DENY_NEVER_EXTERNAL)

    # --- 2. promotion is special: only a HUMAN Brisen admin may finalise (AC6, T4) ---
    if action is Action.PROMOTE:
        if principal.is_ai:
            return deny(Reason.DENY_PROMOTE_AI_CANNOT_FINALIZE)
        if principal.org is not Org.BRISEN or principal.role not in PROMOTION_APPROVER_ROLES:
            return deny(Reason.DENY_PROMOTE_REQUIRES_HUMAN_ADMIN)
        return allow(Reason.ALLOW_PROMOTE)

    # --- 3. export gating (AC8 / T8) — ONLY exportable, for anyone ---
    if action is Action.EXPORT:
        if item.classification is not Classification.EXPORTABLE:
            return deny(Reason.DENY_EXPORT_NOT_EXPORTABLE)
        if external:
            if item.lifecycle_state not in PARTNER_VISIBLE_STATES:
                return deny(Reason.DENY_NOT_SHARED_VIEW)
            if principal.org not in item.allowed_orgs:
                return deny(Reason.DENY_NOT_IN_ALLOWED_ORGS)
        return allow(Reason.ALLOW_EXPORT)

    # --- 4. internal Brisen branch ---
    if not external:
        # internal roles may read/search/annotate/assign_action/view_audit/demote
        # any Brisen-owned object. promote handled above; export handled above.
        if action in (
            Action.READ,
            Action.SEARCH,
            Action.ANNOTATE,
            Action.ASSIGN_ACTION,
            Action.VIEW_AUDIT,
            Action.DEMOTE,
        ):
            return allow(Reason.ALLOW_INTERNAL)
        return deny(Reason.DENY_DEFAULT)

    # --- 5. external branch: read / search / view_audit only ---
    if action not in EXTERNAL_ALLOWED_ACTIONS:
        return deny(Reason.DENY_EXTERNAL_ACTION_NOT_PERMITTED)

    # 5a. lifecycle gate — partner sees only shared_view / action_linked (AC7)
    if item.lifecycle_state not in PARTNER_VISIBLE_STATES:
        return deny(Reason.DENY_NOT_SHARED_VIEW)

    # 5b. classification gate — matching partner_safe_<org> or public_source only
    allowed_class = PARTNER_SAFE_FOR_ORG[principal.org]
    if item.classification == allowed_class or item.classification is Classification.PUBLIC_SOURCE:
        pass
    elif item.classification in PARTNER_SAFE_CLASSES:
        # partner_safe for a DIFFERENT org — cross-partner bleed (T6)
        return deny(Reason.DENY_CLASSIFICATION_ORG_MISMATCH)
    else:
        # brisen_raw / brisen_confidential / exportable are not partner-readable
        return deny(Reason.DENY_CLASSIFICATION_NOT_PARTNER_VISIBLE)

    # 5c. explicit grant gate — classification is necessary, not sufficient (T3/T6)
    if principal.org not in item.allowed_orgs:
        return deny(Reason.DENY_NOT_IN_ALLOWED_ORGS)
    if item.allowed_roles and principal.role not in item.allowed_roles:
        return deny(Reason.DENY_NOT_IN_ALLOWED_ORGS)

    # 5d. confidence gate — anything shown to a partner must carry confidence (AC8, T7)
    if item.confidence is None:
        return deny(Reason.DENY_PARTNER_SAFE_MISSING_CONFIDENCE)

    if action is Action.VIEW_AUDIT:
        return allow(Reason.ALLOW_PARTNER_VIEW_AUDIT)
    return allow(Reason.ALLOW_PARTNER_READ)


def evaluate(
    principal: Principal,
    item: EvidenceItem,
    action: Action,
    *,
    sink: Optional[AuditSink] = None,
) -> PolicyDecision:
    """Authoritative policy decision. Always audits (AC9).

    A defensive outer ``try/except`` guarantees fail-closed (T10): any unexpected
    error in the decision pipeline returns a deny with **no object payload**, never
    an allow. There is no broad ``except`` that returns unfiltered objects.
    """

    sink = sink or default_sink()
    try:
        decision = _decide(principal, item, action)
    except Exception as exc:  # noqa: BLE001 - fail closed, never fail open
        decision = PolicyDecision(
            allow=False,
            reason_code=Reason.DENY_DEFAULT,
            evaluated={"error": type(exc).__name__},
        )

    sink.write(
        AuditEvent(
            event_type="decision",
            principal_org=getattr(principal.org, "value", str(principal.org)),
            principal_role=principal.role,
            action=getattr(action, "value", str(action)),
            object_id=item.object_id,
            object_type=getattr(item.object_type, "value", str(item.object_type)),
            allow=decision.allow,
            reason_code=decision.reason_code.value,
            detail=dict(decision.evaluated),
        )
    )
    return decision


def is_allowed(principal: Principal, item: EvidenceItem, action: Action, **kw) -> bool:
    """Convenience boolean wrapper around :func:`evaluate`."""

    return evaluate(principal, item, action, **kw).allow


# --------------------------------------------------------------------------- #
# Partner-safe projection (AC7) — a DERIVED view, never raw-table exposure.
# --------------------------------------------------------------------------- #
class ProjectionDenied(RuntimeError):
    """Raised by :func:`partner_projection` when the principal may not read the item."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(f"projection denied: {reason_code}")
        self.reason_code = reason_code


def partner_projection(
    principal: Principal,
    item: EvidenceItem,
    *,
    sink: Optional[AuditSink] = None,
) -> Mapping[str, Any]:
    """Return the partner-safe DERIVED view of ``item`` for ``principal``.

    Calls :func:`evaluate` first (AC2: same control). On deny, raises
    ``ProjectionDenied`` and returns NO payload (fail-closed). On allow, returns
    ONLY the partner-safe fields — never ``raw_body`` / ``title`` / snippet /
    audit-note / internal allow-lists (AC7, T2/T5 leakage).
    """

    sink = sink or default_sink()
    decision = evaluate(principal, item, Action.READ, sink=sink)
    if not decision.allow:
        raise ProjectionDenied(decision.reason_code.value)

    projection = {
        "object_id": item.object_id,
        "object_type": getattr(item.object_type, "value", item.object_type),
        "claim": item.claim,
        "source_type": item.source_type,
        "confidence": item.confidence,
        "freshness": item.freshness,
        "last_reviewed": item.last_reviewed,
        "owner": item.owner,
    }
    sink.write(
        AuditEvent(
            event_type="projection",
            principal_org=getattr(principal.org, "value", str(principal.org)),
            principal_role=principal.role,
            action="read",
            object_id=item.object_id,
            object_type=getattr(item.object_type, "value", str(item.object_type)),
            allow=True,
            reason_code=decision.reason_code.value,
            detail={"projected_fields": sorted(projection.keys())},
        )
    )
    return projection


def redact_audit_for_partner(audit_row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Redact a raw audit row to the partner-safe field set (AC7, T5).

    Partner audit shows only claim / source_type / freshness / confidence / owner.
    Internal fields (raw bodies, audit notes, reason internals, allow-lists,
    actor identities) are dropped.
    """

    return {k: audit_row.get(k) for k in PARTNER_AUDIT_FIELDS}
