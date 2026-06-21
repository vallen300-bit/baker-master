"""Evidence lifecycle state machine (AC5) + partner-safe promotion gate (AC6/AC8).

Lifecycle (ontology #2):

    raw_signal → research_artifact → verified_evidence → shared_view → action_linked

Rules:

* **Forward by one step** is the only self-service transition.
* **Back / skip / same-state** transitions are denied UNLESS an explicit admin
  override records a reason (and the actor is a human Brisen admin).
* Entering ``shared_view`` is the partner-safe promotion — it ALWAYS goes through
  the AC6 human-ratify gate (``engine.evaluate(..., PROMOTE)``) and requires
  non-null confidence (AC8), no matter which path reaches it.
* Every transition records actor, timestamp, source_refs, confidence,
  freshness/last_reviewed, prior/new state (AC5).
* Promotion records proposer, approver, approval_timestamp, rationale, source
  evidence (AC6). AI may *propose*; only a human admin may *approve* (T4).

The state machine is pure: it mutates the in-memory ``EvidenceItem``, writes an
``AuditEvent`` to the injected sink, and (optionally) calls a ``recorder`` to
persist the structured row. DB persistence lives in :mod:`policy.store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from policy import engine
from policy.audit import AuditSink, default_sink
from policy.models import (
    LIFECYCLE_ORDER,
    Action,
    AuditEvent,
    EvidenceItem,
    LifecycleState,
    Org,
    Principal,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _index(state: LifecycleState) -> int:
    return LIFECYCLE_ORDER.index(state)


def is_forward_by_one(prior: LifecycleState, new: LifecycleState) -> bool:
    """True iff ``new`` is exactly one step after ``prior`` in the lifecycle."""

    try:
        return _index(new) == _index(prior) + 1
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TransitionRecord:
    object_id: str
    actor_org: str
    actor_role: str
    prior_state: str
    new_state: str
    timestamp: str
    source_refs: tuple[str, ...]
    confidence: Optional[float]
    last_reviewed: Optional[str]
    override_reason: Optional[str]


@dataclass(frozen=True)
class PromotionProposal:
    object_id: str
    proposer_org: str
    proposer_role: str
    proposer_is_ai: bool
    target_state: str
    rationale: str
    source_evidence: tuple[str, ...]
    proposed_at: str


@dataclass(frozen=True)
class PromotionRecord:
    object_id: str
    proposer_org: str
    proposer_role: str
    approver_org: str
    approver_role: str
    approval_timestamp: str
    rationale: str
    source_evidence: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Exceptions — denials raise (fail-closed; callers cannot ignore an ``ok`` flag)
# --------------------------------------------------------------------------- #
class TransitionDenied(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(f"transition denied: {reason_code}")
        self.reason_code = reason_code


class PromotionDenied(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(f"promotion denied: {reason_code}")
        self.reason_code = reason_code


Recorder = Callable[[Any], None]


def _audit(
    sink: AuditSink,
    *,
    event_type: str,
    actor: Principal,
    object_id: str,
    allow: bool,
    reason_code: str,
    detail: Mapping[str, Any],
) -> None:
    sink.write(
        AuditEvent(
            event_type=event_type,
            principal_org=getattr(actor.org, "value", str(actor.org)),
            principal_role=actor.role,
            action=None,
            object_id=object_id,
            object_type=None,
            allow=allow,
            reason_code=reason_code,
            detail=dict(detail),
        )
    )


def _is_human_brisen_admin(actor: Principal) -> bool:
    from policy.models import PROMOTION_APPROVER_ROLES

    return (
        not actor.is_ai
        and actor.org is Org.BRISEN
        and actor.role in PROMOTION_APPROVER_ROLES
    )


# --------------------------------------------------------------------------- #
# Transition
# --------------------------------------------------------------------------- #
def transition(
    item: EvidenceItem,
    new_state: LifecycleState,
    actor: Principal,
    *,
    source_refs: tuple[str, ...] = (),
    confidence: Optional[float] = None,
    last_reviewed: Optional[str] = None,
    override_reason: Optional[str] = None,
    sink: Optional[AuditSink] = None,
    recorder: Optional[Recorder] = None,
) -> TransitionRecord:
    """Apply a lifecycle transition. Raises ``TransitionDenied`` on any violation.

    On success mutates ``item.lifecycle_state`` (and ``item.confidence`` /
    ``item.last_reviewed`` when supplied), writes an audit row, and persists via
    ``recorder`` if given.
    """

    sink = sink or default_sink()
    prior = item.lifecycle_state

    if not isinstance(new_state, LifecycleState):
        _audit(
            sink,
            event_type="transition",
            actor=actor,
            object_id=item.object_id,
            allow=False,
            reason_code="invalid_target_state",
            detail={"target": str(new_state)},
        )
        raise TransitionDenied("invalid_target_state")

    forward = is_forward_by_one(prior, new_state)

    # Back / skip / same-state requires an admin override with a reason.
    if not forward:
        if override_reason is None:
            _audit(
                sink,
                event_type="transition",
                actor=actor,
                object_id=item.object_id,
                allow=False,
                reason_code="invalid_transition",
                detail={"prior": prior.value, "new": new_state.value},
            )
            raise TransitionDenied("invalid_transition")
        if not _is_human_brisen_admin(actor):
            _audit(
                sink,
                event_type="transition",
                actor=actor,
                object_id=item.object_id,
                allow=False,
                reason_code="override_requires_admin",
                detail={"prior": prior.value, "new": new_state.value},
            )
            raise TransitionDenied("override_requires_admin")

    # Entering shared_view is the partner-safe promotion — always human-ratified
    # (AC6) with non-null confidence (AC8), regardless of forward vs override path.
    if new_state is LifecycleState.SHARED_VIEW:
        decision = engine.evaluate(actor, item, Action.PROMOTE, sink=sink)
        if not decision.allow:
            raise TransitionDenied(decision.reason_code.value)
        effective_conf = confidence if confidence is not None else item.confidence
        if effective_conf is None:
            _audit(
                sink,
                event_type="transition",
                actor=actor,
                object_id=item.object_id,
                allow=False,
                reason_code="shared_view_requires_confidence",
                detail={"prior": prior.value, "new": new_state.value},
            )
            raise TransitionDenied("shared_view_requires_confidence")

    # Apply.
    record = TransitionRecord(
        object_id=item.object_id,
        actor_org=getattr(actor.org, "value", str(actor.org)),
        actor_role=actor.role,
        prior_state=prior.value,
        new_state=new_state.value,
        timestamp=_now(),
        source_refs=tuple(source_refs),
        confidence=confidence if confidence is not None else item.confidence,
        last_reviewed=last_reviewed if last_reviewed is not None else item.last_reviewed,
        override_reason=override_reason,
    )
    item.lifecycle_state = new_state
    if confidence is not None:
        item.confidence = confidence
    if last_reviewed is not None:
        item.last_reviewed = last_reviewed

    _audit(
        sink,
        event_type="transition",
        actor=actor,
        object_id=item.object_id,
        allow=True,
        reason_code="transition_applied",
        detail={
            "prior": record.prior_state,
            "new": record.new_state,
            "override_reason": override_reason,
            "confidence_present": record.confidence is not None,
        },
    )
    if recorder is not None:
        recorder(record)
    return record


# --------------------------------------------------------------------------- #
# Promotion (AC6) — propose (AI ok) then approve (human admin only)
# --------------------------------------------------------------------------- #
def propose_promotion(
    item: EvidenceItem,
    proposer: Principal,
    *,
    rationale: str,
    source_evidence: tuple[str, ...] = (),
    sink: Optional[AuditSink] = None,
    recorder: Optional[Recorder] = None,
) -> PromotionProposal:
    """Record a proposal to promote ``item`` to ``shared_view``. No state change.

    AI principals MAY propose (that is their whole job, AC6). Only Brisen-internal
    principals may propose a partner-safe promotion; an external principal cannot.
    """

    sink = sink or default_sink()
    if proposer.org is not Org.BRISEN:
        _audit(
            sink,
            event_type="promotion",
            actor=proposer,
            object_id=item.object_id,
            allow=False,
            reason_code="propose_requires_brisen",
            detail={"stage": "propose"},
        )
        raise PromotionDenied("propose_requires_brisen")

    proposal = PromotionProposal(
        object_id=item.object_id,
        proposer_org=proposer.org.value,
        proposer_role=proposer.role,
        proposer_is_ai=proposer.is_ai,
        target_state=LifecycleState.SHARED_VIEW.value,
        rationale=rationale,
        source_evidence=tuple(source_evidence),
        proposed_at=_now(),
    )
    _audit(
        sink,
        event_type="promotion",
        actor=proposer,
        object_id=item.object_id,
        allow=True,
        reason_code="promotion_proposed",
        detail={"stage": "propose", "is_ai": proposer.is_ai},
    )
    if recorder is not None:
        recorder(proposal)
    return proposal


def approve_promotion(
    item: EvidenceItem,
    approver: Principal,
    proposal: PromotionProposal,
    *,
    confidence: Optional[float] = None,
    source_refs: tuple[str, ...] = (),
    last_reviewed: Optional[str] = None,
    sink: Optional[AuditSink] = None,
    transition_recorder: Optional[Recorder] = None,
    promotion_recorder: Optional[Recorder] = None,
) -> PromotionRecord:
    """Finalise a proposed promotion: move ``item`` to ``shared_view`` (AC6).

    Authorisation runs through :func:`transition` (which enforces the AC6 human-
    admin gate + AC8 confidence). Records the AC6 audit row carrying proposer,
    approver, approval_timestamp, rationale, and source evidence.
    """

    sink = sink or default_sink()
    # transition() enforces the human-admin promote gate + confidence; it raises
    # TransitionDenied (a PromotionDenied for callers) on any violation.
    try:
        transition(
            item,
            LifecycleState.SHARED_VIEW,
            approver,
            source_refs=source_refs,
            confidence=confidence,
            last_reviewed=last_reviewed,
            sink=sink,
            recorder=transition_recorder,
        )
    except TransitionDenied as exc:
        _audit(
            sink,
            event_type="promotion",
            actor=approver,
            object_id=item.object_id,
            allow=False,
            reason_code=exc.reason_code,
            detail={"stage": "approve"},
        )
        raise PromotionDenied(exc.reason_code) from exc

    record = PromotionRecord(
        object_id=item.object_id,
        proposer_org=proposal.proposer_org,
        proposer_role=proposal.proposer_role,
        approver_org=approver.org.value,
        approver_role=approver.role,
        approval_timestamp=_now(),
        rationale=proposal.rationale,
        source_evidence=tuple(proposal.source_evidence),
    )
    _audit(
        sink,
        event_type="promotion",
        actor=approver,
        object_id=item.object_id,
        allow=True,
        reason_code="promotion_approved",
        detail={
            "stage": "approve",
            "proposer_role": proposal.proposer_role,
            "approver_role": approver.role,
        },
    )
    if promotion_recorder is not None:
        promotion_recorder(record)
    return record
