"""Source-registry logic: fail-closed validation + Step-1 policy integration (Step 2).

This module is the bridge between registry metadata and the LIVE Step-1 policy
engine. It NEVER decides external visibility itself:

* ``record_to_evidence_item`` maps a ``SourceRecord`` to a Step-1 ``EvidenceItem``.
* ``external_projection_for`` calls ``policy.engine.partner_projection`` (which
  calls ``policy.engine.evaluate``) — the SAME control every other surface uses
  (AC4/T3). A denial returns a redacted *hidden* row, never a payload.

Validation is fail-closed (AC1/AC7/T10): a record missing any required field —
or a hidden row missing its redaction_reason — raises ``RegistryInvalidError`` and
yields NO payload, never a default-public row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from policy import engine
from policy.audit import AuditSink, default_sink
from policy.models import EvidenceItem, Org, Principal
from policy.sources.models import (
    OBJECT_TYPE_TO_POLICY,
    CollectionStatus,
    ProvenanceClass,
    RegistryChange,
    SourceDomain,
    SourceRecord,
)

# Classifications that, if set on a source, are an external-facing exposure that
# requires human ratification to APPLY (AC10).
from policy.models import PARTNER_SAFE_CLASSES, PARTNER_VISIBLE_STATES, EXTERNAL_ORGS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegistryInvalidError(RuntimeError):
    """Raised when a SourceRecord is missing required metadata. Fail closed (AC1)."""

    def __init__(self, field: str, detail: str = "") -> None:
        super().__init__(f"registry invalid: {field} {detail}".strip())
        self.field = field


class RegistryBypassError(RuntimeError):
    """Raised when a metadata change that increases external exposure is applied
    without human ratification (AC10/T4)."""


# Base fields every record must carry (AC1). Booleans are checked for presence,
# not truthiness, so ``False`` is a valid explicit value.
_REQUIRED_FIELDS = (
    "source_id", "domain", "source_type", "object_type", "owner_org",
    "classification", "lifecycle_state", "provenance_class", "collection_status",
    "freshness",
)


def validate_record(rec: SourceRecord) -> None:
    """Raise ``RegistryInvalidError`` if ``rec`` is missing required metadata.

    Fail-closed: a registry caller MUST call this before persisting or projecting
    a record. Missing required fields never default to public (AC1/T10).
    """

    for f in _REQUIRED_FIELDS:
        val = getattr(rec, f, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise RegistryInvalidError(f, "is required")

    if not isinstance(rec.domain, SourceDomain):
        raise RegistryInvalidError("domain", "must be one of the 8 source domains")

    # booleans must be explicitly set (not None) — fail closed on omission
    for f in ("raw_body_available_internal", "external_projection_available"):
        if getattr(rec, f, None) is None:
            raise RegistryInvalidError(f, "is required (no default-public)")

    if rec.is_gap:
        # gap rows are first-class but carry NO payload (AC8): owner/reason/next.
        for f in ("gap_owner", "gap_reason", "gap_next_action"):
            if not getattr(rec, f, None):
                raise RegistryInvalidError(f, "is required for a gap row")
        if rec.external_projection_available:
            raise RegistryInvalidError(
                "external_projection_available", "gap rows cannot be externally visible"
            )
        return

    # non-gap rows must link to a Step-1 policy object
    if not rec.policy_object_id:
        raise RegistryInvalidError("policy_object_id", "is required for a non-gap source")

    # AC7: a hidden row MUST explain why, else it is registry-invalid (fail closed)
    if not rec.external_projection_available and not rec.redaction_reason:
        raise RegistryInvalidError(
            "redaction_reason", "is required when external_projection_available is False"
        )


def record_to_evidence_item(rec: SourceRecord) -> EvidenceItem:
    """Build the Step-1 ``EvidenceItem`` used for policy evaluation.

    ``raw_body`` / ``title`` carry only internal sentinels — the registry holds NO
    content. They exist so the projection's redaction is exercised (AC6): if any
    code path ever leaked them, the projection test would catch it.

    A non-gap record MUST carry ``policy_object_id``. There is NO ``source_id``
    fallback (deputy-codex F1, AC1/T9): falling back to ``source_id`` would leak an
    opaque source identifier into the external projection's ``object_id``. Missing
    ``policy_object_id`` fails closed.
    """

    if not rec.policy_object_id:
        raise RegistryInvalidError("policy_object_id", "required to build evidence item")

    return EvidenceItem(
        object_id=rec.policy_object_id,
        object_type=OBJECT_TYPE_TO_POLICY[rec.object_type],
        classification=rec.classification,
        lifecycle_state=rec.lifecycle_state,
        owner_org=rec.owner_org,
        owner=rec.gap_owner or "brisen-evidence-team",
        sensitivity=rec.sensitivity,
        allowed_orgs=rec.allowed_orgs,
        allowed_roles=rec.allowed_roles,
        confidence=rec.confidence,
        source_refs=rec.provenance_refs,
        source_type=rec.source_type,
        claim=rec.claim or rec.name,
        freshness=rec.freshness,
        last_reviewed=rec.freshness,
        raw_body="<internal raw body present>" if rec.raw_body_available_internal else None,
        title=rec.name,
    )


def internal_view(rec: SourceRecord) -> Mapping[str, Any]:
    """Full internal inventory view (Brisen-only). Keeps full provenance refs."""

    return {
        "source_id": rec.source_id,
        "domain": rec.domain.value,
        "source_type": rec.source_type,
        "object_type": rec.object_type.value,
        "owner_org": rec.owner_org.value,
        "classification": rec.classification.value,
        "lifecycle_state": rec.lifecycle_state.value,
        "sensitivity": rec.sensitivity.value if rec.sensitivity else None,
        "never_external": rec.is_never_external,
        "collection_status": rec.collection_status.value,
        "raw_body_available_internal": rec.raw_body_available_internal,
        "external_projection_available": rec.external_projection_available,
        "redaction_reason": rec.redaction_reason,
        "provenance_class": rec.provenance_class.value,
        "provenance_refs": list(rec.provenance_refs),   # internal-only
        "freshness": rec.freshness,
        "gap": {
            "owner": rec.gap_owner,
            "reason": rec.gap_reason,
            "next_action": rec.gap_next_action,
        } if rec.is_gap else None,
    }


def external_projection_for(
    principal: Principal,
    rec: SourceRecord,
    *,
    sink: Optional[AuditSink] = None,
) -> Optional[Mapping[str, Any]]:
    """Return the partner-safe external view of ``rec`` for ``principal``, or
    ``None`` if the LIVE policy engine hides it.

    The decision is made by ``policy.engine.partner_projection`` — NOT by any
    registry flag (AC4/T3). The registry's ``external_projection_available`` is a
    pre-filter ONLY; the final control is the policy evaluation. A gap row, a
    never-external source, a cross-partner classification, or a missing grant all
    resolve to ``None`` here because the engine denies them.
    """

    sink = sink or default_sink()

    # Fail-closed FIRST (deputy-codex F1, AC1/T9): a registry-invalid record — e.g.
    # a non-gap row missing policy_object_id — must NEVER yield an external
    # payload. validate_record raises RegistryInvalidError, which propagates so the
    # caller surfaces registry-invalid rather than leaking a default/fallback id.
    validate_record(rec)

    if rec.is_gap:
        return None  # gap rows carry no payload, never externally visible (AC8)

    # Pre-filter (cheap, non-authoritative): if the registry already marks the
    # source hidden, skip — but the engine remains the final word for everything
    # the registry *thinks* is visible.
    if not rec.external_projection_available:
        return None

    item = record_to_evidence_item(rec)
    try:
        projection = engine.partner_projection(principal, item, sink=sink)
    except engine.ProjectionDenied:
        return None  # policy engine hid it — final control (T1/T3/T4/T5/T8)

    # Augment with audience-safe provenance only (AC9): provenance_class +
    # source_count (already in projection) + freshness. NEVER raw refs / ids.
    enriched = dict(projection)
    enriched["provenance_class"] = rec.provenance_class.value
    enriched.pop("title", None)   # defence in depth — title must never be present
    enriched.pop("raw_body", None)
    return enriched


# --------------------------------------------------------------------------- #
# AC10 — auditable registry change flow (AI proposes, human ratifies exposure)
# --------------------------------------------------------------------------- #
_EXPOSURE_FIELDS = frozenset(
    {"classification", "external_projection_available", "allowed_orgs", "lifecycle_state"}
)


def _increases_external_exposure(field: str, new_value: Any, rec: SourceRecord) -> bool:
    """True if changing ``field`` to ``new_value`` could make ``rec`` more
    externally visible (and therefore needs human ratification, AC10)."""

    if field == "external_projection_available":
        return bool(new_value) and not rec.external_projection_available
    if field == "classification":
        return new_value in PARTNER_SAFE_CLASSES
    if field == "lifecycle_state":
        return new_value in PARTNER_VISIBLE_STATES
    if field == "allowed_orgs":
        new_orgs = set(new_value or ())
        added = new_orgs - set(rec.allowed_orgs)
        return any(o in EXTERNAL_ORGS for o in added)
    return False


def propose_registry_change(
    rec: SourceRecord,
    field: str,
    new_value: Any,
    proposer: Principal,
    *,
    rationale: str,
    decision_source: str,
) -> RegistryChange:
    """Record a PROPOSED registry change. AI may propose anything; this never
    mutates ``rec`` (AC10). Use :func:`apply_registry_change` to ratify."""

    return RegistryChange(
        source_id=rec.source_id,
        field=field,
        prior_value=str(getattr(rec, field, None)),
        new_value=str(new_value),
        actor_org=proposer.org.value,
        actor_role=proposer.role,
        actor_is_ai=proposer.is_ai,
        rationale=rationale,
        decision_source=decision_source,
        timestamp=_now(),
        increases_external_exposure=_increases_external_exposure(field, new_value, rec),
    )


def apply_registry_change(
    rec: SourceRecord,
    field: str,
    new_value: Any,
    approver: Principal,
    *,
    rationale: str,
    decision_source: str,
    recorder: Optional[Any] = None,
) -> RegistryChange:
    """Apply a registry metadata change, recording the audit row (AC10).

    A change that increases external exposure requires a HUMAN Brisen principal
    (AI cannot ratify exposure — T4). Mutates ``rec`` and returns the audit record;
    persists via ``recorder`` if given.
    """

    increases = _increases_external_exposure(field, new_value, rec)
    if increases and (approver.is_ai or approver.org is not Org.BRISEN):
        raise RegistryBypassError(
            f"making source {rec.source_id} externally visible (field={field}) "
            f"requires a human Brisen approver; got is_ai={approver.is_ai} "
            f"org={approver.org.value}"
        )

    change = RegistryChange(
        source_id=rec.source_id,
        field=field,
        prior_value=str(getattr(rec, field, None)),
        new_value=str(new_value),
        actor_org=approver.org.value,
        actor_role=approver.role,
        actor_is_ai=approver.is_ai,
        rationale=rationale,
        decision_source=decision_source,
        timestamp=_now(),
        increases_external_exposure=increases,
    )
    setattr(rec, field, new_value)
    # Re-validate post-change — a change must never leave the row registry-invalid.
    validate_record(rec)
    if recorder is not None:
        recorder(change)
    return change
