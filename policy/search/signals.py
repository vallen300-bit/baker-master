"""Amber raw-signal capture + promotion-by-existing-gate (Step 3).

A search result can be saved as an amber **raw signal** (AC4): useful but
UNCONFIRMED material that lands at ``lifecycle_state=raw_signal`` and is never
trusted evidence. Promotion to verified/shared is NOT implemented here — it reuses
the Step-1 lifecycle gate (:mod:`policy.lifecycle`) so there is exactly ONE
promotion path (AC7):

    raw_signal → research_artifact → verified_evidence → shared_view → action_linked

``raw_signal_to_evidence_item`` bridges an amber signal into the Step-1 object model
so ``policy.lifecycle.transition`` / ``propose_promotion`` / ``approve_promotion``
can drive it forward. Because the lifecycle only allows forward-by-one self-service
transitions and gates entry to ``shared_view`` behind a human-admin promote, a raw
search result can NEVER skip straight to ``shared_view`` (done rubric #6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from policy.models import (
    Classification,
    EvidenceItem,
    LifecycleState,
    Org,
    Principal,
)
from policy.sources.models import OBJECT_TYPE_TO_POLICY, SourceRecord
from policy.search.models import RawSignal
from policy.search.routing import RoutingSuggestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def signal_from_record(
    rec: SourceRecord,
    suggestion: RoutingSuggestion,
    *,
    signal_id: str,
    raw_summary_internal: str,
    evidence_needed_to_confirm: str,
    projected_summary_external: Optional[str] = None,
    reviewer: Optional[str] = None,
    duplicate_of: Optional[str] = None,
    related_signal_ids: tuple[str, ...] = (),
) -> RawSignal:
    """Build an amber :class:`RawSignal` from a Step-2 record + routing suggestion.

    Lifecycle is FIXED at ``raw_signal`` (AC4). The external summary, if supplied,
    must already be projection-built — this function does not generate one from raw
    text. Classification / allowed_orgs are carried verbatim from the record so the
    Step-1 engine remains the visibility control on any later promotion.
    """

    return RawSignal(
        signal_id=signal_id,
        source_id=rec.source_id,
        source_domain=rec.domain,
        object_type=rec.object_type,
        raw_summary_internal=raw_summary_internal,
        proposed_route_target=suggestion.route_target,
        route_reason=suggestion.route_reason,
        classification=rec.classification,
        owner=rec.gap_owner or "brisen-evidence-team",
        freshness=rec.freshness,
        observed_at=_now(),
        evidence_needed_to_confirm=evidence_needed_to_confirm,
        projected_summary_external=projected_summary_external,
        confidence=suggestion.confidence,
        lifecycle_state=LifecycleState.RAW_SIGNAL,   # FIXED — never anything else here
        allowed_orgs=rec.allowed_orgs,
        allowed_roles=rec.allowed_roles,
        reviewer=reviewer,
        policy_object_id=rec.policy_object_id,
        duplicate_of=duplicate_of,
        related_signal_ids=related_signal_ids,
        audit_trail=(f"captured:{_now()}",),
    )


def save_raw_signal(
    signal: RawSignal,
    *,
    recorder: Optional[Callable[[RawSignal], None]] = None,
) -> RawSignal:
    """Persist an amber signal at ``raw_signal`` (AC4). Refuses any non-raw state.

    A signal must enter the system as ``raw_signal`` — a caller cannot hand-build a
    higher lifecycle state and save it to skip the promotion gate (defends the same
    bypass ``policy.store.save_item`` guards against). Promotion happens ONLY through
    :func:`promote_via_lifecycle`.
    """

    if signal.lifecycle_state is not LifecycleState.RAW_SIGNAL:
        raise ValueError(
            f"raw signal {signal.signal_id} must be saved at raw_signal, "
            f"got {signal.lifecycle_state.value}; promote via the lifecycle gate"
        )
    if recorder is not None:
        recorder(signal)
    return signal


def raw_signal_to_evidence_item(signal: RawSignal) -> EvidenceItem:
    """Bridge an amber signal into the Step-1 object model for lifecycle promotion.

    Carries classification / allowed_orgs / confidence verbatim so the Step-1 engine
    and lifecycle gate remain the sole authority on any forward movement. Requires
    ``policy_object_id`` (no source_id fallback — same fail-closed rule as Step-2 F1).
    """

    if not signal.policy_object_id:
        raise ValueError(
            f"raw signal {signal.signal_id} has no policy_object_id; cannot bridge "
            f"to an evidence_item for promotion (fail closed, no identifier fallback)"
        )

    return EvidenceItem(
        object_id=signal.policy_object_id,
        object_type=OBJECT_TYPE_TO_POLICY[signal.object_type],
        classification=signal.classification,
        lifecycle_state=signal.lifecycle_state,
        owner_org=Org.BRISEN,
        owner=signal.owner,
        allowed_orgs=signal.allowed_orgs,
        allowed_roles=signal.allowed_roles,
        confidence=signal.confidence,
        claim=signal.projected_summary_external,
        freshness=signal.freshness,
        last_reviewed=signal.observed_at,
    )


def confirm_to_research_artifact(
    signal: RawSignal,
    item: EvidenceItem,
    actor: Principal,
    *,
    source_refs: tuple[str, ...] = (),
    sink=None,
    recorder=None,
):
    """Forward an amber signal one step (raw_signal → research_artifact) via the
    Step-1 lifecycle. This is the confirmation step that begins the promotion path;
    it produces NO partner visibility on its own.
    """

    from policy import lifecycle

    record = lifecycle.transition(
        item,
        LifecycleState.RESEARCH_ARTIFACT,
        actor,
        source_refs=source_refs,
        sink=sink,
        recorder=recorder,
    )
    signal.lifecycle_state = item.lifecycle_state
    signal.audit_trail = signal.audit_trail + (f"confirmed:{record.timestamp}",)
    return record
