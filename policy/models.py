"""Object model for the AI Hotel Lab policy/evidence core.

All vocabulary here is BINDING per codex-arch ontology amendments (#3625, folded
into the dispatch brief). Schema enums are ``snake_case``; partner-facing UI labels
come later and are NOT this layer's concern.

Key amendments encoded:

* ``evidence_item`` is the term (not "evidence object").
* Lifecycle terminal state is ``action_linked`` (not "action"); ``action`` stays an
  *object_type*. Evidence does not become an action — it links to one.
* 7 classifications, incl. ``partner_safe_venue_owner`` (venue-owner is a confirmed
  external role).
* **Classification ≠ grant**: a ``partner_safe_*`` tag is necessary, not sufficient;
  ``allowed_orgs`` / ``allowed_roles`` still decide (defends T3 misclassification,
  T6 cross-partner bleed).
* ``claim`` added as an object_type — the first dashboard asks *which claims are
  verified enough to show*; confidence attaches to claims for partner view.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


# --------------------------------------------------------------------------- #
# Enums (all values snake_case for DB storage)
# --------------------------------------------------------------------------- #
class Org(str, enum.Enum):
    """Principal organisations. ``brisen`` is internal; the rest are external."""

    BRISEN = "brisen"
    NVIDIA = "nvidia"
    MOHG = "mohg"
    VENUE_OWNER = "venue_owner"


class Action(str, enum.Enum):
    """Actions a principal may attempt against an evidence_item (AC1, ≥ 8)."""

    READ = "read"
    SEARCH = "search"
    EXPORT = "export"
    PROMOTE = "promote"
    DEMOTE = "demote"
    ANNOTATE = "annotate"
    ASSIGN_ACTION = "assign_action"
    VIEW_AUDIT = "view_audit"


class ObjectType(str, enum.Enum):
    """Object types (ontology #6 — ``claim`` added; ``action`` stays a type)."""

    CLAIM = "claim"
    PROJECT = "project"
    SITE = "site"
    PARTNER = "partner"
    SIGNAL = "signal"
    EVIDENCE = "evidence"
    DECISION = "decision"
    ACTION = "action"
    RISK = "risk"
    DOCUMENT = "document"
    SOURCE = "source"


class LifecycleState(str, enum.Enum):
    """Evidence lifecycle (ontology #2 — terminal state is ``action_linked``)."""

    RAW_SIGNAL = "raw_signal"
    RESEARCH_ARTIFACT = "research_artifact"
    VERIFIED_EVIDENCE = "verified_evidence"
    SHARED_VIEW = "shared_view"
    ACTION_LINKED = "action_linked"


class Classification(str, enum.Enum):
    """The 7 classifications (ontology #3). Classification alone never grants."""

    BRISEN_RAW = "brisen_raw"
    BRISEN_CONFIDENTIAL = "brisen_confidential"
    PARTNER_SAFE_NVIDIA = "partner_safe_nvidia"
    PARTNER_SAFE_MOHG = "partner_safe_mohg"
    PARTNER_SAFE_VENUE_OWNER = "partner_safe_venue_owner"
    PUBLIC_SOURCE = "public_source"
    EXPORTABLE = "exportable"


class Sensitivity(str, enum.Enum):
    """Never-external content categories (AC4). Orthogonal to ``Classification``.

    These are HARD-DENY for any external principal and beat any allow — even a
    (mistaken) ``partner_safe_*`` classification cannot override them (defends T3
    misclassification + T1 confused-deputy). An item with no never-external
    category carries ``sensitivity = None``.
    """

    EMAIL_WA_RAW = "email_wa_raw"
    STRATEGY_NOTE = "strategy_note"
    VENDOR_NEGOTIATION = "vendor_negotiation"
    FINANCIAL = "financial"
    LEGAL = "legal"


# --------------------------------------------------------------------------- #
# Derived constant sets
# --------------------------------------------------------------------------- #
EXTERNAL_ORGS: frozenset[Org] = frozenset({Org.NVIDIA, Org.MOHG, Org.VENUE_OWNER})

# Org → its allowed role slugs (ontology #5). Brisen seeded as a single org with
# three roles — NO separate Brisen-Director org.
ROLES_BY_ORG: Mapping[Org, frozenset[str]] = {
    Org.BRISEN: frozenset({"director", "internal_team", "evidence_admin"}),
    Org.NVIDIA: frozenset({"ai_hospitality_lighthouse_lead"}),
    Org.MOHG: frozenset({"ops_standards_lead"}),
    Org.VENUE_OWNER: frozenset({"site_diligence_lead"}),
}

# Brisen roles permitted to FINALISE a partner-safe promotion (AC6 human ratify).
PROMOTION_APPROVER_ROLES: frozenset[str] = frozenset({"director", "evidence_admin"})

# Each external org → the single ``partner_safe_*`` classification it may ever see.
PARTNER_SAFE_FOR_ORG: Mapping[Org, Classification] = {
    Org.NVIDIA: Classification.PARTNER_SAFE_NVIDIA,
    Org.MOHG: Classification.PARTNER_SAFE_MOHG,
    Org.VENUE_OWNER: Classification.PARTNER_SAFE_VENUE_OWNER,
}

PARTNER_SAFE_CLASSES: frozenset[Classification] = frozenset(PARTNER_SAFE_FOR_ORG.values())

# Classifications that may NEVER reach an external principal via read/search,
# regardless of any allow (AC4 reinforcement at the classification layer).
NEVER_EXTERNAL_CLASSES: frozenset[Classification] = frozenset(
    {Classification.BRISEN_RAW, Classification.BRISEN_CONFIDENTIAL}
)

# All never-external sensitivity categories (AC4 hard-deny set).
NEVER_EXTERNAL_SENSITIVITIES: frozenset[Sensitivity] = frozenset(Sensitivity)

# Lifecycle order — index defines legal forward-by-one transitions (AC5).
LIFECYCLE_ORDER: tuple[LifecycleState, ...] = (
    LifecycleState.RAW_SIGNAL,
    LifecycleState.RESEARCH_ARTIFACT,
    LifecycleState.VERIFIED_EVIDENCE,
    LifecycleState.SHARED_VIEW,
    LifecycleState.ACTION_LINKED,
)

# Lifecycle states in which an item may be projected to an external partner.
# Both shared_view and the terminal action_linked (which always follows
# shared_view) are partner-visible; everything earlier is internal-only (AC7).
PARTNER_VISIBLE_STATES: frozenset[LifecycleState] = frozenset(
    {LifecycleState.SHARED_VIEW, LifecycleState.ACTION_LINKED}
)

# Actions an external principal may ever be ALLOWED (still gated below). Promote/
# demote/annotate/assign_action are internal-only — defends T9 privilege creep.
EXTERNAL_ALLOWED_ACTIONS: frozenset[Action] = frozenset(
    {Action.READ, Action.SEARCH, Action.EXPORT, Action.VIEW_AUDIT}
)

# Fields a partner audit row is redacted to (AC7). Nothing else leaks.
PARTNER_AUDIT_FIELDS: tuple[str, ...] = (
    "claim",
    "source_type",
    "freshness",
    "confidence",
    "owner",
)


# --------------------------------------------------------------------------- #
# Reason codes — every decision carries exactly one (AC1)
# --------------------------------------------------------------------------- #
class Reason(str, enum.Enum):
    # --- input validation (fail-closed) ---
    INVALID_ACTION = "invalid_action"
    INVALID_CLASSIFICATION = "invalid_classification"
    INVALID_LIFECYCLE_STATE = "invalid_lifecycle_state"
    INVALID_OBJECT_TYPE = "invalid_object_type"
    UNKNOWN_ORG = "unknown_org"
    INVALID_ROLE_FOR_ORG = "invalid_role_for_org"

    # --- hard deny ---
    HARD_DENY_NEVER_EXTERNAL = "hard_deny_never_external"

    # --- promotion (AC6) ---
    DENY_PROMOTE_AI_CANNOT_FINALIZE = "deny_promote_ai_cannot_finalize"
    DENY_PROMOTE_REQUIRES_HUMAN_ADMIN = "deny_promote_requires_human_admin"
    ALLOW_PROMOTE = "allow_promote"

    # --- export (AC8 / T8) ---
    DENY_EXPORT_NOT_EXPORTABLE = "deny_export_not_exportable"
    ALLOW_EXPORT = "allow_export"

    # --- external read/search gates ---
    DENY_EXTERNAL_ACTION_NOT_PERMITTED = "deny_external_action_not_permitted"
    DENY_NOT_SHARED_VIEW = "deny_not_shared_view"
    DENY_CLASSIFICATION_ORG_MISMATCH = "deny_classification_org_mismatch"
    DENY_CLASSIFICATION_NOT_PARTNER_VISIBLE = "deny_classification_not_partner_visible"
    DENY_NOT_IN_ALLOWED_ORGS = "deny_not_in_allowed_orgs"
    DENY_PARTNER_SAFE_MISSING_CONFIDENCE = "deny_partner_safe_missing_confidence"
    ALLOW_PARTNER_READ = "allow_partner_read"
    ALLOW_PARTNER_VIEW_AUDIT = "allow_partner_view_audit"

    # --- internal ---
    ALLOW_INTERNAL = "allow_internal"

    # --- catch-all ---
    DENY_DEFAULT = "deny_default"


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Principal:
    """A simulated actor (Sprint-0 has no real SSO).

    ``is_ai`` distinguishes an AI proposer from a human: AI may propose a
    promotion but can never finalise one (AC6).
    """

    org: Org
    role: str
    is_ai: bool = False
    principal_id: Optional[str] = None

    @property
    def is_external(self) -> bool:
        return self.org in EXTERNAL_ORGS


@dataclass
class EvidenceItem:
    """A protected evidence_item. The unit confidence attaches to (ontology #6).

    ``allowed_orgs`` / ``allowed_roles`` are the explicit grant gates — a
    classification tag alone never grants access (ontology #4). ``raw_body`` /
    ``title`` are internal-only fields and are NEVER included in a partner
    projection (AC7).
    """

    object_id: str
    object_type: ObjectType
    classification: Classification
    lifecycle_state: LifecycleState
    owner_org: Org = Org.BRISEN
    owner: Optional[str] = None
    sensitivity: Optional[Sensitivity] = None
    allowed_orgs: frozenset[Org] = field(default_factory=frozenset)
    allowed_roles: frozenset[str] = field(default_factory=frozenset)
    confidence: Optional[float] = None
    source_refs: tuple[str, ...] = ()
    source_type: Optional[str] = None
    claim: Optional[str] = None
    freshness: Optional[str] = None
    last_reviewed: Optional[str] = None
    # internal-only payload — never projected to a partner
    raw_body: Optional[str] = None
    title: Optional[str] = None


@dataclass(frozen=True)
class PolicyDecision:
    """Result of ``engine.evaluate`` — allow/deny + reason_code + evaluated inputs."""

    allow: bool
    reason_code: Reason
    evaluated: Mapping[str, Any]

    def __bool__(self) -> bool:  # convenience: ``if decision:``
        return self.allow


@dataclass(frozen=True)
class AuditEvent:
    """One audited policy event (AC9). Written to ``policy_audit_log`` or logged."""

    event_type: str  # decision | promotion | transition | projection
    principal_org: str
    principal_role: str
    action: Optional[str]
    object_id: Optional[str]
    object_type: Optional[str]
    allow: bool
    reason_code: str
    detail: Mapping[str, Any] = field(default_factory=dict)
