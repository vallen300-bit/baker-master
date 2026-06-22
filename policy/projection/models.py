"""Object model for the AI Hotel Lab partner-safe projection surface (Step 4).

Vocabulary is BINDING per codex-arch product framing (bus #3733) + deputy-codex
Step-4 rubric (#3738, folded into the brief). This layer is a CONSUMER of Steps 1-3:

* ``Org`` / ``Classification`` / ``LifecycleState`` from :mod:`policy.models` (Step-1).
* ``RouteTarget`` from :mod:`policy.search.models` (Step-3) for dashboard sections.
* This module adds ONLY projection vocabulary: the 4 external ``AudienceRole`` values
  (+ admin/internal capabilities), the 8 ``ProjectionState`` values, the 19-field
  ``ProjectionItem``, and the EXTERNAL field allowlist (deputy-codex AC4).

The load-bearing rule: **every external display field is projection-DERIVED (built by
`policy.engine.partner_projection`), never raw.** External packets carry ONLY the
allowlisted fields — raw ids / source ids / provenance refs / file paths / participant
lists / raw titles / internal notes / denial reasons / raw task URLs are ABSENT.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from policy.models import Org
from policy.search.models import RouteTarget


# --------------------------------------------------------------------------- #
# Audience roles (codex-arch #3733 — exactly these external audience_role values)
# --------------------------------------------------------------------------- #
class AudienceRole(str, enum.Enum):
    """The projection audiences. ``brisen_internal`` is the internal preview role;
    the other three are partner-safe-projection ONLY. Evidence-admin is a separate
    capability (see ``ADMIN_ROLES``), not an external audience."""

    BRISEN_INTERNAL = "brisen_internal"
    NVIDIA_LIGHTHOUSE = "nvidia_lighthouse"
    MOHG_OPS_STANDARDS = "mohg_ops_standards"
    VENUE_OWNER_SITE_DILIGENCE = "venue_owner_site_diligence"


EXTERNAL_AUDIENCES: frozenset[AudienceRole] = frozenset({
    AudienceRole.NVIDIA_LIGHTHOUSE,
    AudienceRole.MOHG_OPS_STANDARDS,
    AudienceRole.VENUE_OWNER_SITE_DILIGENCE,
})

# Audience role → the Step-1 Org it maps to.
AUDIENCE_ORG: Mapping[AudienceRole, Org] = {
    AudienceRole.BRISEN_INTERNAL: Org.BRISEN,
    AudienceRole.NVIDIA_LIGHTHOUSE: Org.NVIDIA,
    AudienceRole.MOHG_OPS_STANDARDS: Org.MOHG,
    AudienceRole.VENUE_OWNER_SITE_DILIGENCE: Org.VENUE_OWNER,
}

# Audience role → the simulated external principal role slug (Sprint-0 test users).
AUDIENCE_PRINCIPAL_ROLE: Mapping[AudienceRole, str] = {
    AudienceRole.NVIDIA_LIGHTHOUSE: "ai_hospitality_lighthouse_lead",
    AudienceRole.MOHG_OPS_STANDARDS: "ops_standards_lead",
    AudienceRole.VENUE_OWNER_SITE_DILIGENCE: "site_diligence_lead",
}

# Brisen roles that may run evidence-admin actions (approve/revoke/refresh, view-as,
# inspect policy decision). Evidence-admin is a capability over the internal role set.
ADMIN_ROLES: frozenset[str] = frozenset({"director", "evidence_admin"})


# --------------------------------------------------------------------------- #
# Projection states (codex-arch #3733 — exactly 8)
# --------------------------------------------------------------------------- #
class ProjectionState(str, enum.Enum):
    NOT_PROJECTABLE = "not_projectable"                       # wrong lifecycle (raw/research)
    PROJECTABLE_CANDIDATE = "projectable_candidate"          # eligible, not yet approved
    PROJECTED_SHARED_VIEW = "projected_shared_view"          # live external
    ACTION_LINKED_VISIBLE = "action_linked_visible"          # action-linked, live external
    REVOKED = "revoked"                                       # pulled from external view
    STALE_PROJECTION = "stale_projection"                    # underlying evidence stale
    BLOCKED_BY_POLICY = "blocked_by_policy"                  # engine hard-deny (never_external etc.)
    BLOCKED_BY_MISSING_CONFIRMATION = "blocked_by_missing_confirmation"  # not verified yet


# States whose items are VISIBLE in an external packet. Everything else is content-free.
EXTERNAL_VISIBLE_STATES: frozenset[ProjectionState] = frozenset({
    ProjectionState.PROJECTED_SHARED_VIEW,
    ProjectionState.ACTION_LINKED_VISIBLE,
})

# Non-visible states that still COUNT (content-free) toward an audience's own packet
# summary — surfaced as integers / empty-state reasons, never as content.
EXTERNAL_BLOCKED_STATES: frozenset[ProjectionState] = frozenset({
    ProjectionState.BLOCKED_BY_POLICY,
    ProjectionState.BLOCKED_BY_MISSING_CONFIRMATION,
})


# --------------------------------------------------------------------------- #
# The EXTERNAL field allowlist (deputy-codex AC4)
# --------------------------------------------------------------------------- #
# The ONLY keys an external packet item may carry. The external serializer builds a
# dict restricted to these — anything else is dropped. Tests assert the inverse:
# raw ids / source ids / provenance refs / paths / participants / raw titles /
# internal notes / denial reasons / raw task URLs never appear.
EXTERNAL_ITEM_ALLOWLIST: tuple[str, ...] = (
    "projection_item_id",          # opaque, non-enumerable
    "audience_role",
    "dashboard_section",           # route_target
    "display_title",               # safe, projection-derived
    "display_summary",             # safe, projection-derived
    "evidence_confidence",
    "confidence_reason",           # safe
    "source_label_safe",           # generic source type label, never a path/id
    "citation_or_provenance_safe", # provenance class + source COUNT, never raw refs
    "evidence_status",             # safe lifecycle label
    "projection_state",            # safe state
    "freshness",
    "last_verified_at",
    "visibility_reason",           # safe
    "redaction_applied",           # bool
    "redaction_reason_safe",       # curated safe reason (NOT an engine denial reason)
    "action_safe_text",            # partner-safe action text, NO urls/ids
)

# Substrings that must NEVER appear anywhere in an external payload (test guard).
FORBIDDEN_EXTERNAL_SUBSTRINGS: tuple[str, ...] = (
    "raw_body", "source_evidence_item_id", "source_id", "provenance_refs",
    "audit_trace_id", "revoked_by", "revoke_reason", "owner", "reviewer",
    "action_linked_id", "clickup.com", "github.com", "dropbox.com",
    "http://", "https://", "/admin", "reason_code",
)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class ProjectionItem:
    """A projected evidence item for one audience (codex-arch #3733 — 19 fields).

    External display fields are ALL projection-derived (built from
    ``policy.engine.partner_projection``). The internal-only fields
    (``source_evidence_item_id``, ``audit_trace_id``, ``owner``/``reviewer``,
    ``revoked_*``, ``action_linked_id``, ``redaction_reason`` internal) are NEVER
    emitted by the external serializer (deputy-codex AC4/T9).
    """

    # 1-5 identity / placement
    projection_item_id: str
    audience_role: AudienceRole
    source_evidence_item_id: str                  # INTERNAL only
    lifecycle_state: str
    dashboard_section: RouteTarget

    # 6-11 derived display (all from partner_projection)
    display_title: str
    display_summary: str
    evidence_confidence: Optional[float]
    confidence_reason: str
    source_label_safe: str
    citation_or_provenance_safe: str

    # 12-13 recency / ownership
    freshness: Optional[str]
    last_verified_at: Optional[str]
    owner: Optional[str] = None                    # INTERNAL only
    reviewer: Optional[str] = None                 # INTERNAL only

    # 14-16 visibility / redaction
    visibility_reason: str = ""
    redaction_applied: bool = False
    redaction_reason: Optional[str] = None         # INTERNAL detail
    redaction_reason_safe: Optional[str] = None    # curated, external-safe

    # 17 action linkage
    action_linked_id: Optional[str] = None         # INTERNAL only (raw id / URL)
    action_safe_text: Optional[str] = None         # external-safe action text

    # 18 revocation (INTERNAL only)
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoke_reason: Optional[str] = None

    # 19 audit
    audit_trace_id: Optional[str] = None           # INTERNAL only

    # projection state machine
    projection_state: ProjectionState = ProjectionState.PROJECTABLE_CANDIDATE

    @property
    def is_externally_visible(self) -> bool:
        return (
            self.projection_state in EXTERNAL_VISIBLE_STATES
            and self.revoked_at is None
        )


@dataclass(frozen=True)
class ProjectionAuditLog:
    """One audited projection event (approve / revoke / refresh / view / deny)."""

    event_type: str
    audience_role: str
    projection_item_id: Optional[str]
    actor_org: str
    actor_role: str
    actor_is_ai: bool
    allow: bool
    reason: str
    timestamp: str


@dataclass(frozen=True)
class ProjectionRedaction:
    """A redaction applied to a projected item (what was removed + safe reason)."""

    projection_item_id: str
    removed_field: str
    reason_safe: str


@dataclass(frozen=True)
class ViewPacket:
    """A role-specific view packet (Step-5 consumes this). For external audiences the
    items are allowlist-restricted; for internal/admin the serializer is SEPARATE."""

    audience_role: AudienceRole
    audience_label: str
    is_external: bool
    sections: Mapping[str, Any]              # route_target -> [items] | empty-state reason
    visible_count: int
    blocked_count: int
    stale_count: int
    action_linked_count: int
    last_generated_at: str
    policy_version: str
    projection_version: str

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "audience_role": self.audience_role.value,
            "audience_label": self.audience_label,
            "is_external": self.is_external,
            "sections": self.sections,
            "counts": {
                "visible": self.visible_count,
                "blocked": self.blocked_count,
                "stale": self.stale_count,
                "action_linked": self.action_linked_count,
            },
            "last_generated_at": self.last_generated_at,
            "policy_version": self.policy_version,
            "projection_version": self.projection_version,
        }
