"""View-packet assembly + SEPARATE serializers for the projection surface (Step 4).

Three serializers, deliberately SEPARATE (deputy-codex T9/AC10 serializer boundary):

* ``_serialize_external_item`` — restricts output to ``EXTERNAL_ITEM_ALLOWLIST``. It is
  structurally impossible for it to emit an internal field (denial reason, source id,
  audit trace, owner, raw URL): it copies ONLY allowlisted keys.
* ``_serialize_internal_item`` — full internal preview (Brisen-only).
* ``_serialize_admin_item`` — internal + projection-decision metadata.

Cross-role isolation (test 3) is automatic: ``build_projection_item`` returns ``None``
for items not granted to the audience's org, so another audience's items are ABSENT
from the packet, its counts, its facets, and its audit. ``view_as`` reuses the SAME
external builder so it is byte-identical to the real external packet (test 9). The
server-side principal fixture (``serve_external_packet``) defeats org/role spoofing
(T10). A snapshot cache is revalidated by fingerprint at response time (T11).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional

from policy.audit import AuditSink, default_sink
from policy.models import EvidenceItem, Org, Principal
from policy.search.routing import RouteTarget
from policy.projection.models import (
    AUDIENCE_ORG,
    AUDIENCE_PRINCIPAL_ROLE,
    EXTERNAL_AUDIENCES,
    EXTERNAL_BLOCKED_STATES,
    EXTERNAL_ITEM_ALLOWLIST,
    AudienceRole,
    ProjectionItem,
    ProjectionState,
    ViewPacket,
)
from policy.projection.projector import build_projection_item

POLICY_VERSION = "step1-policy-core-1"
PROJECTION_VERSION = "step4-partner-projection-1"

_AUDIENCE_LABEL: Mapping[AudienceRole, str] = {
    AudienceRole.BRISEN_INTERNAL: "Brisen internal preview",
    AudienceRole.NVIDIA_LIGHTHOUSE: "NVIDIA — AI-hospitality lighthouse",
    AudienceRole.MOHG_OPS_STANDARDS: "Mandarin Oriental — ops / brand standards",
    AudienceRole.VENUE_OWNER_SITE_DILIGENCE: "Venue owner — site diligence",
}


class SpoofDenied(RuntimeError):
    """Raised when a principal's claimed audience does not match its server-side org/
    role (deputy-codex T10). The packet is built from the authoritative principal."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectionCandidate:
    """An evidence item offered for projection, with its projection metadata."""

    item: EvidenceItem
    route_target: Optional[RouteTarget] = None
    revoked: bool = False
    revoked_by: Optional[str] = None
    revoke_reason: Optional[str] = None
    stale: bool = False
    action_safe_text: Optional[str] = None


# --------------------------------------------------------------------------- #
# Serializers (SEPARATE — T9 boundary)
# --------------------------------------------------------------------------- #
def _serialize_external_item(i: ProjectionItem) -> Mapping[str, Any]:
    """External serializer: ONLY allowlisted fields (AC4). Anything not on the
    allowlist is structurally impossible to emit."""

    full = {
        "projection_item_id": i.projection_item_id,
        "audience_role": i.audience_role.value,
        "dashboard_section": i.dashboard_section.value,
        "display_title": i.display_title,
        "display_summary": i.display_summary,
        "evidence_confidence": i.evidence_confidence,
        "confidence_reason": i.confidence_reason,
        "source_label_safe": i.source_label_safe,
        "citation_or_provenance_safe": i.citation_or_provenance_safe,
        "evidence_status": i.lifecycle_state,        # safe lifecycle label
        "projection_state": i.projection_state.value,
        "freshness": i.freshness,
        "last_verified_at": i.last_verified_at,
        "visibility_reason": i.visibility_reason,
        "redaction_applied": i.redaction_applied,
        "redaction_reason_safe": i.redaction_reason_safe,
        "action_safe_text": i.action_safe_text,
    }
    return {k: full[k] for k in EXTERNAL_ITEM_ALLOWLIST if k in full}


def _serialize_internal_item(i: ProjectionItem) -> Mapping[str, Any]:
    """Internal-preview serializer (Brisen-only): full fields, including internal ids."""

    return {
        "projection_item_id": i.projection_item_id,
        "audience_role": i.audience_role.value,
        "source_evidence_item_id": i.source_evidence_item_id,
        "lifecycle_state": i.lifecycle_state,
        "dashboard_section": i.dashboard_section.value,
        "display_title": i.display_title,
        "display_summary": i.display_summary,
        "evidence_confidence": i.evidence_confidence,
        "source_label_safe": i.source_label_safe,
        "freshness": i.freshness,
        "owner": i.owner,
        "reviewer": i.reviewer,
        "visibility_reason": i.visibility_reason,
        "projection_state": i.projection_state.value,
        "audit_trace_id": i.audit_trace_id,
    }


def _serialize_admin_item(i: ProjectionItem) -> Mapping[str, Any]:
    """Evidence-admin serializer: internal fields + projection decision metadata."""

    base = dict(_serialize_internal_item(i))
    base.update({
        "redaction_applied": i.redaction_applied,
        "redaction_reason": i.redaction_reason,
        "revoked_at": i.revoked_at,
        "revoked_by": i.revoked_by,
        "revoke_reason": i.revoke_reason,
        "action_linked_id": i.action_linked_id,
    })
    return base


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _assemble(
    audience_role: AudienceRole,
    candidates: Iterable[ProjectionCandidate],
    *,
    sink: Optional[AuditSink],
) -> List[ProjectionItem]:
    out: List[ProjectionItem] = []
    for c in candidates:
        pi = build_projection_item(
            audience_role, c.item,
            route_target=c.route_target, revoked=c.revoked, revoked_by=c.revoked_by,
            revoke_reason=c.revoke_reason, stale=c.stale,
            action_safe_text=c.action_safe_text, sink=sink,
        )
        if pi is not None:
            out.append(pi)
    return out


def build_external_packet(
    audience_role: AudienceRole,
    candidates: Iterable[ProjectionCandidate],
    *,
    generated_at: Optional[str] = None,
    sink: Optional[AuditSink] = None,
) -> ViewPacket:
    """Build the partner-safe external packet for ``audience_role`` (allowlist only).

    ``generated_at`` is injectable so ``view-as`` can be byte-identical to the real
    external packet (the only otherwise-varying field)."""

    if audience_role not in EXTERNAL_AUDIENCES:
        raise ValueError(f"{audience_role} is not an external audience")
    sink = sink or default_sink()
    generated_at = generated_at or _now()

    items = _assemble(audience_role, candidates, sink=sink)
    visible = [i for i in items if i.is_externally_visible]
    action_linked = [i for i in visible
                     if i.projection_state is ProjectionState.ACTION_LINKED_VISIBLE]

    sections: dict[str, Any] = {}
    for i in visible:
        sections.setdefault(i.dashboard_section.value, []).append(_serialize_external_item(i))
    if not visible:
        # deputy-codex F1 (#3762): an external empty state is GENERIC — it must NOT
        # reveal that hidden/blocked/stale material exists or why. The detailed
        # blocked/stale reason stays internal/admin only. (This overrides codex-arch's
        # "blocked/stale counts" packet note for EXTERNAL audiences — the #3738
        # security rubric is stricter and binding.)
        sections = {"_empty_state": "no_items_available"}

    return ViewPacket(
        audience_role=audience_role,
        audience_label=_AUDIENCE_LABEL[audience_role],
        is_external=True,
        sections=sections,
        visible_count=len(visible),
        blocked_count=0,   # F1: external never reveals hidden/blocked counts
        stale_count=0,     # F1: external never reveals stale counts
        action_linked_count=len(action_linked),   # visible action-linked only
        last_generated_at=generated_at,
        policy_version=POLICY_VERSION,
        projection_version=PROJECTION_VERSION,
    )


def build_internal_preview_packet(
    candidates: Iterable[ProjectionCandidate],
    *,
    generated_at: Optional[str] = None,
    sink: Optional[AuditSink] = None,
) -> ViewPacket:
    """Brisen internal preview (full fields, separate serializer)."""

    generated_at = generated_at or _now()
    items = _assemble(AudienceRole.BRISEN_INTERNAL, candidates, sink=sink)
    sections: dict[str, Any] = {}
    for i in items:
        sections.setdefault(i.dashboard_section.value, []).append(_serialize_internal_item(i))
    if not items:
        sections = {"_empty_state": "no_items"}
    visible = [i for i in items if i.projection_state in (
        ProjectionState.PROJECTED_SHARED_VIEW, ProjectionState.ACTION_LINKED_VISIBLE,
        ProjectionState.PROJECTABLE_CANDIDATE)]
    return ViewPacket(
        audience_role=AudienceRole.BRISEN_INTERNAL,
        audience_label=_AUDIENCE_LABEL[AudienceRole.BRISEN_INTERNAL],
        is_external=False,
        sections=sections,
        visible_count=len(visible),
        blocked_count=len([i for i in items if i.projection_state in EXTERNAL_BLOCKED_STATES]),
        stale_count=len([i for i in items if i.projection_state is ProjectionState.STALE_PROJECTION]),
        action_linked_count=len([i for i in items
                                 if i.projection_state is ProjectionState.ACTION_LINKED_VISIBLE]),
        last_generated_at=generated_at,
        policy_version=POLICY_VERSION,
        projection_version=PROJECTION_VERSION,
    )


# --------------------------------------------------------------------------- #
# view-as (parity) + spoof guard + cache revalidation
# --------------------------------------------------------------------------- #
def _is_admin_or_internal(principal: Principal) -> bool:
    from policy.projection.models import ADMIN_ROLES

    return principal.org is Org.BRISEN and (
        principal.role in ADMIN_ROLES or principal.role == "internal_team"
    )


def view_as(
    actor: Principal,
    audience_role: AudienceRole,
    candidates: Iterable[ProjectionCandidate],
    *,
    generated_at: Optional[str] = None,
    sink: Optional[AuditSink] = None,
) -> ViewPacket:
    """Brisen-internal/admin view-as-partner. Returns the SAME external packet a real
    external user would get (test 9 byte-identical). External actors cannot view-as."""

    if not _is_admin_or_internal(actor):
        raise SpoofDenied(
            f"view-as requires a Brisen internal/admin actor; got "
            f"{getattr(actor.org, 'value', actor.org)}/{actor.role}"
        )
    if audience_role not in EXTERNAL_AUDIENCES:
        raise ValueError(f"{audience_role} is not an external audience")
    return build_external_packet(audience_role, candidates,
                                 generated_at=generated_at, sink=sink)


def audience_for_principal(principal: Principal) -> AudienceRole:
    """Resolve the AUTHORITATIVE audience for an authenticated principal (server-side).

    External principals map to their own audience by org+role; a principal whose
    org/role does not match any known external audience cannot be served externally."""

    for role in EXTERNAL_AUDIENCES:
        if (AUDIENCE_ORG[role] is principal.org
                and AUDIENCE_PRINCIPAL_ROLE[role] == principal.role):
            return role
    raise SpoofDenied(
        f"no external audience for principal "
        f"{getattr(principal.org, 'value', principal.org)}/{principal.role}"
    )


def serve_external_packet(
    authenticated_principal: Principal,
    requested_audience: AudienceRole,
    candidates: Iterable[ProjectionCandidate],
    *,
    generated_at: Optional[str] = None,
    cache: Optional[dict] = None,
    sink: Optional[AuditSink] = None,
) -> ViewPacket:
    """Serve an external packet, built from the SERVER-SIDE principal (T10 spoof guard).

    The packet is built for the principal's AUTHORITATIVE audience. If the caller asks
    for a different audience (tampered org/role/param), it is denied — a partner can
    never coax another audience's packet. A snapshot ``cache`` (if provided) is
    revalidated by candidate fingerprint at response time (T11): a stale cache after a
    policy/source/lifecycle change is never served."""

    true_audience = audience_for_principal(authenticated_principal)
    if true_audience is not requested_audience:
        raise SpoofDenied(
            f"principal {authenticated_principal.org.value}/{authenticated_principal.role} "
            f"cannot be served audience {requested_audience.value}"
        )

    cand_list = list(candidates)
    fp = _fingerprint(true_audience, cand_list)
    if cache is not None and cache.get("fingerprint") == fp:
        return cache["packet"]   # still valid — same audience + same underlying state

    packet = build_external_packet(true_audience, cand_list,
                                   generated_at=generated_at, sink=sink)
    if cache is not None:
        cache["fingerprint"] = fp
        cache["packet"] = packet
    return packet


def external_item_audit(
    authenticated_principal: Principal,
    projection_item_id: str,
    candidates: Iterable[ProjectionCandidate],
    *,
    sink: Optional[AuditSink] = None,
) -> Optional[Mapping[str, Any]]:
    """The `{item}/audit` endpoint for an EXTERNAL principal — audience-scoped.

    Returns a SAFE audit summary ONLY if ``projection_item_id`` is a visible item in
    the caller's OWN audience packet. Another audience's item is ABSENT (returns
    ``None``) — an external principal can never read another audience's audit (test 3
    cross-role isolation across `{item}/audit`). The summary carries no internal
    fields (no source id, no actor identity, no denial reason)."""

    true_audience = audience_for_principal(authenticated_principal)
    packet = build_external_packet(true_audience, candidates, sink=sink)
    for section in packet.sections.values():
        if not isinstance(section, list):
            continue
        for item in section:
            if item.get("projection_item_id") == projection_item_id:
                return {
                    "projection_item_id": item["projection_item_id"],
                    "audience_role": item["audience_role"],
                    "projection_state": item["projection_state"],
                    "evidence_status": item.get("evidence_status"),
                    "last_verified_at": item.get("last_verified_at"),
                    "visibility_reason": item.get("visibility_reason"),
                }
    return None   # not in this audience's packet — absent, not denied-with-detail


def _fingerprint(audience_role: AudienceRole, candidates: List[ProjectionCandidate]) -> str:
    """Stable fingerprint of the audience + EVERY externally-observable input.

    deputy-codex F2 (#3762): the fingerprint must change whenever anything that could
    alter the EXTERNAL payload changes — not just visibility inputs. It therefore
    covers every externally-serialized field (claim/title/summary, source_type/label,
    source_refs/count, freshness, last_reviewed, route_target/section, action_safe_text)
    in addition to the visibility inputs (lifecycle, classification, sensitivity,
    grants, confidence, revoke, stale). Otherwise a cached packet could serve stale
    partner text or a stale source count (T11)."""

    parts = [audience_role.value]
    for c in candidates:
        it = c.item
        parts.append("|".join(str(x) for x in (
            it.object_id,
            getattr(it.lifecycle_state, "value", it.lifecycle_state),
            getattr(it.classification, "value", it.classification),
            getattr(it.sensitivity, "value", it.sensitivity) if it.sensitivity else "-",
            sorted(getattr(o, "value", o) for o in it.allowed_orgs),
            it.confidence,
            c.revoked, c.stale,
            # externally-serialized payload fields (F2):
            it.claim, it.title, it.source_type, len(it.source_refs),
            it.freshness, it.last_reviewed,
            getattr(c.route_target, "value", c.route_target),
            c.action_safe_text,
        )))
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]
