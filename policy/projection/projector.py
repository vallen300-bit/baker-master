"""Projection builder — turns an evidence item into an audience ProjectionItem (Step 4).

This is the bridge to the LIVE Step-1 engine. It decides NOTHING about visibility on
its own:

* The projection STATE is computed deterministically from lifecycle + never-external
  sensitivity + the audience grant (cross-role isolation: an item not granted to the
  audience's org is ABSENT, returns ``None`` — not a hidden stub).
* For an EXTERNAL visible item, the display body is built ONLY by
  ``policy.engine.partner_projection`` (the sole safe-body builder). If the engine
  denies, the item fails closed to ``blocked_by_policy`` with NO body — so removing
  the engine call leaves no external content (derived-only / no-second-engine tests).
* For the ``brisen_internal`` preview, the full internal body is gated by
  ``policy.engine.evaluate(..., READ)`` — a SEPARATE path from the external serializer.

``raw_signal`` / ``research_artifact`` never project externally; only ``shared_view``
and ``action_linked`` are externally visible; ``verified_evidence`` is a
``projectable_candidate`` awaiting evidence-admin approval to ``shared_view``.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from policy import engine
from policy.audit import AuditSink, default_sink
from policy.models import (
    Action,
    EvidenceItem,
    LifecycleState,
    Org,
    Principal,
)
from policy.search.routing import RouteTarget
from policy.projection.models import (
    AUDIENCE_ORG,
    AUDIENCE_PRINCIPAL_ROLE,
    EXTERNAL_AUDIENCES,
    AudienceRole,
    ProjectionItem,
    ProjectionState,
)

# Lifecycle states that can ever be externally projected (shared_view / action_linked).
EXTERNAL_VISIBLE_LIFECYCLE: frozenset[LifecycleState] = frozenset({
    LifecycleState.SHARED_VIEW,
    LifecycleState.ACTION_LINKED,
})

# Lifecycle states that never project externally (Step-3 amber + research).
NON_PROJECTABLE_LIFECYCLE: frozenset[LifecycleState] = frozenset({
    LifecycleState.RAW_SIGNAL,
    LifecycleState.RESEARCH_ARTIFACT,
})


def resolve_audience_principal(audience_role: AudienceRole) -> Principal:
    """Server-side principal for an audience (Sprint-0 simulated users).

    This is the AUTHORITATIVE identity — the spoof guard (T10) builds the principal
    here from the audience role, never from client-supplied org/role params."""

    org = AUDIENCE_ORG[audience_role]
    if audience_role in EXTERNAL_AUDIENCES:
        return Principal(org, AUDIENCE_PRINCIPAL_ROLE[audience_role])
    return Principal(Org.BRISEN, "internal_team")


def _opaque_item_id(source_object_id: str, audience_role: AudienceRole) -> str:
    """Opaque, non-enumerable projection id (AC4 — never the raw source id)."""

    seed = f"ai-hotel-projection::{audience_role.value}::{source_object_id}"
    return "prj_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _section_for(item: EvidenceItem, route_target: Optional[RouteTarget]) -> RouteTarget:
    return route_target or RouteTarget.EXECUTIVE_SUMMARY


def build_projection_item(
    audience_role: AudienceRole,
    item: EvidenceItem,
    *,
    route_target: Optional[RouteTarget] = None,
    revoked: bool = False,
    revoked_by: Optional[str] = None,
    revoke_reason: Optional[str] = None,
    stale: bool = False,
    action_safe_text: Optional[str] = None,
    sink: Optional[AuditSink] = None,
) -> Optional[ProjectionItem]:
    """Build the ProjectionItem for ``item`` and ``audience_role``, or ``None`` if the
    item belongs to a DIFFERENT external audience (absent — cross-role isolation).

    The state machine is deterministic + fail-closed; for external visible states the
    body is built by ``partner_projection`` and a denial downgrades to
    ``blocked_by_policy`` with no body.
    """

    sink = sink or default_sink()
    principal = resolve_audience_principal(audience_role)
    org = AUDIENCE_ORG[audience_role]
    external = audience_role in EXTERNAL_AUDIENCES

    # Cross-role isolation: an external item not granted to this org is ABSENT.
    if external and org not in item.allowed_orgs:
        return None

    section = _section_for(item, route_target)
    pid = _opaque_item_id(item.object_id, audience_role)

    # --- deterministic state ---
    if revoked:
        state = ProjectionState.REVOKED
    elif external and item.sensitivity is not None:
        state = ProjectionState.BLOCKED_BY_POLICY            # never-external hard deny
    elif item.lifecycle_state in NON_PROJECTABLE_LIFECYCLE:
        state = ProjectionState.NOT_PROJECTABLE              # raw_signal / research_artifact
    elif stale:
        state = ProjectionState.STALE_PROJECTION
    elif item.lifecycle_state is LifecycleState.VERIFIED_EVIDENCE:
        state = ProjectionState.PROJECTABLE_CANDIDATE        # verified, awaiting approval
    elif item.lifecycle_state is LifecycleState.SHARED_VIEW:
        state = ProjectionState.PROJECTED_SHARED_VIEW
    elif item.lifecycle_state is LifecycleState.ACTION_LINKED:
        state = ProjectionState.ACTION_LINKED_VISIBLE
    else:
        state = ProjectionState.NOT_PROJECTABLE

    # --- internal preview: full body via the internal READ allow (separate path) ---
    if not external:
        decision = engine.evaluate(principal, item, Action.READ, sink=sink)
        if not decision.allow:
            # internal cannot read this Brisen object -> not projectable to preview
            return _stub(pid, audience_role, item, section, ProjectionState.NOT_PROJECTABLE)
        return _internal_item(pid, audience_role, item, section, state,
                              revoked_at=None, action_safe_text=action_safe_text)

    # --- external visible states must be built by the engine (sole body builder) ---
    if state in (ProjectionState.PROJECTED_SHARED_VIEW, ProjectionState.ACTION_LINKED_VISIBLE):
        try:
            proj = engine.partner_projection(principal, item, sink=sink)
        except engine.ProjectionDenied:
            # fail closed — eligible by lifecycle but engine denied (missing grant/
            # confidence): no external body, mark blocked.
            return _stub(pid, audience_role, item, section, ProjectionState.BLOCKED_BY_POLICY)
        return _external_item(pid, audience_role, item, section, state, proj,
                              action_safe_text=action_safe_text)

    # --- external non-visible states: content-free stub (counted, never content) ---
    return _stub(pid, audience_role, item, section, state,
                 revoked_by=revoked_by, revoke_reason=revoke_reason)


# --------------------------------------------------------------------------- #
# Item constructors
# --------------------------------------------------------------------------- #
def _external_item(pid, audience_role, item, section, state, proj, *, action_safe_text):
    """Build a VISIBLE external item. Every display field comes from ``proj`` (the
    partner_projection output) — never from raw source text."""

    confidence = proj.get("confidence")
    claim = proj.get("claim") or "(verified item)"
    src_count = proj.get("source_count")
    return ProjectionItem(
        projection_item_id=pid,
        audience_role=audience_role,
        source_evidence_item_id=item.object_id,                  # INTERNAL only
        lifecycle_state=getattr(item.lifecycle_state, "value", item.lifecycle_state),
        dashboard_section=section,
        display_title=claim,
        display_summary=claim,
        evidence_confidence=confidence,
        confidence_reason=f"verified evidence (confidence {confidence})",
        source_label_safe=proj.get("source_type") or "verified_source",
        citation_or_provenance_safe=f"{src_count} source(s)" if src_count is not None else "n/a",
        freshness=proj.get("freshness"),
        last_verified_at=proj.get("last_reviewed"),
        owner=proj.get("owner"),                                  # INTERNAL only
        visibility_reason="approved partner-safe projection",
        redaction_applied=True,
        redaction_reason="raw source fields removed for partner view",  # internal detail
        redaction_reason_safe="partner-safe summary only",
        action_safe_text=action_safe_text if state is ProjectionState.ACTION_LINKED_VISIBLE else None,
        audit_trace_id=f"aud_{pid}",                             # INTERNAL only
        projection_state=state,
    )


def _internal_item(pid, audience_role, item, section, state, *, revoked_at, action_safe_text):
    """Build a full internal-preview item (Brisen-only serializer)."""

    return ProjectionItem(
        projection_item_id=pid,
        audience_role=audience_role,
        source_evidence_item_id=item.object_id,
        lifecycle_state=getattr(item.lifecycle_state, "value", item.lifecycle_state),
        dashboard_section=section,
        display_title=item.claim or item.title or "(internal item)",
        display_summary=item.claim or "",
        evidence_confidence=item.confidence,
        confidence_reason=f"internal preview (confidence {item.confidence})",
        source_label_safe=item.source_type or "internal_source",
        citation_or_provenance_safe=f"{len(item.source_refs)} source ref(s)",
        freshness=item.freshness,
        last_verified_at=item.last_reviewed,
        owner=item.owner,
        reviewer=item.owner,
        visibility_reason="internal preview",
        redaction_applied=False,
        action_linked_id=None,
        action_safe_text=action_safe_text,
        audit_trace_id=f"aud_{pid}",
        revoked_at=revoked_at,
        projection_state=state,
    )


def _stub(pid, audience_role, item, section, state, *, revoked_by=None, revoke_reason=None):
    """A content-free stub for a non-visible state. Carries the source id + state for
    internal/admin + counts; the EXTERNAL serializer emits NONE of its content."""

    return ProjectionItem(
        projection_item_id=pid,
        audience_role=audience_role,
        source_evidence_item_id=item.object_id,                  # INTERNAL only
        lifecycle_state=getattr(item.lifecycle_state, "value", item.lifecycle_state),
        dashboard_section=section,
        display_title="",          # no content
        display_summary="",
        evidence_confidence=None,
        confidence_reason="",
        source_label_safe="",
        citation_or_provenance_safe="",
        freshness=None,
        last_verified_at=None,
        visibility_reason=state.value,
        redaction_applied=False,
        revoked_by=revoked_by,                                   # INTERNAL only
        revoke_reason=revoke_reason,                             # INTERNAL only
        audit_trace_id=f"aud_{pid}",
        projection_state=state,
    )
