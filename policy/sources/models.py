"""Object model for the AI Hotel Lab source registry (Step 2).

Vocabulary follows the lead's build defaults (bus #3657, pending codex-arch
refinement which the enum-stable design absorbs cleanly):

* **8 source domains exactly** — no ``misc`` / catch-all (AC2).
* Object types per lead default #1.
* **Classification REUSES Step-1's 7-value enum unchanged** (lead default #2) —
  ``policy.models.Classification`` is the single source of truth; we do NOT add
  enum values. ``internal_only`` / ``sensitive_partner`` map to
  ``brisen_confidential``.
* **never-external is a SEPARATE hard-deny dimension, not a classification value**
  (lead default #2). We reuse Step-1's ``Sensitivity`` enum for it — the SAME
  mechanism the Step-1 engine hard-denies on (``NEVER_EXTERNAL_SENSITIVITIES``).
  Setting ``SourceRecord.sensitivity`` makes a source never-external; the policy
  engine enforces it. This is reuse, not a second control (T3/T4).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

# Step-1 single-source-of-truth enums — reused, never duplicated.
from policy.models import (
    Classification,
    LifecycleState,
    ObjectType,
    Org,
    Sensitivity,
)


class SourceDomain(str, enum.Enum):
    """Exactly the 8 source domains (codex-arch #3651, AC2). No catch-all."""

    BAKER_INTERNAL_MEMORY = "baker_internal_memory"
    VAULT_PROJECT_ROOMS = "vault_project_rooms"
    DROPBOX_PROJECT_FILES = "dropbox_project_files"
    COMMS_EMAIL_WA_SLACK = "comms_email_wa_slack"
    FIELD_EVIDENCE = "field_evidence"
    OPEN_WEB = "open_web"
    SITE_SEARCH_PUBLIC = "site_search_public"
    MARKET_CAPITAL_RESIDENCE = "market_capital_residence"


class SourceObjectType(str, enum.Enum):
    """Registry object types (lead default #1)."""

    CLAIM = "claim"
    SITE_SIGNAL = "site_signal"
    PARTNER_SIGNAL = "partner_signal"
    COMPETITOR_SIGNAL = "competitor_signal"
    FINANCING_SIGNAL = "financing_signal"
    RESIDENCE_SIGNAL = "residence_signal"
    PR_SIGNAL = "pr_signal"
    ACTION = "action"
    DOCUMENT = "document"
    NOTE = "note"
    IMAGE_VIDEO = "image_video"


class CollectionStatus(str, enum.Enum):
    """Whether a source is actually wired into collection (AC2/AC8)."""

    WIRED = "wired"        # collection live
    PARTIAL = "partial"    # some coverage, known holes
    GAP = "gap"            # not wired — explicit gap row, NO payload


class ProvenanceClass(str, enum.Enum):
    """Audience-safe provenance summary (AC9). The class is partner-visible; the
    raw provenance refs are internal-only and never leave Brisen."""

    FIRST_PARTY = "first_party"
    PARTNER_PROVIDED = "partner_provided"
    PUBLIC = "public"
    DERIVED = "derived"


# Map a registry object type → the Step-1 ObjectType used for policy evaluation.
# The policy engine does not gate on object_type, so this is informational; the
# mapping keeps the EvidenceItem well-typed without inventing engine vocabulary.
OBJECT_TYPE_TO_POLICY: dict[SourceObjectType, ObjectType] = {
    SourceObjectType.CLAIM: ObjectType.CLAIM,
    SourceObjectType.SITE_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.PARTNER_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.COMPETITOR_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.FINANCING_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.RESIDENCE_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.PR_SIGNAL: ObjectType.SIGNAL,
    SourceObjectType.ACTION: ObjectType.ACTION,
    SourceObjectType.DOCUMENT: ObjectType.DOCUMENT,
    SourceObjectType.NOTE: ObjectType.DOCUMENT,
    SourceObjectType.IMAGE_VIDEO: ObjectType.DOCUMENT,
}


@dataclass
class SourceRecord:
    """One row in the source registry (AC1).

    Required fields are validated fail-closed by ``registry.validate_record`` —
    missing required metadata FAILS CLOSED, never defaults to public (AC1/T10).

    ``sensitivity`` (reused Step-1 ``Sensitivity``) is the never-external hard-deny
    dimension. ``raw_body_available_internal`` is internal inventory metadata only
    — it NEVER surfaces any raw body/title/snippet/identifier externally (AC6).
    """

    # --- identity / classification (required) ---
    source_id: str                       # opaque, non-enumerable (AC9)
    domain: SourceDomain
    source_type: str                     # e.g. "city_planning_portal"
    object_type: SourceObjectType
    owner_org: Org
    classification: Classification       # REUSED Step-1 enum (AC3)
    lifecycle_state: LifecycleState
    provenance_class: ProvenanceClass
    collection_status: CollectionStatus
    raw_body_available_internal: bool
    external_projection_available: bool
    freshness: str                       # last_seen / freshness marker

    # --- grant gates (Step-1 decides with these; classification ≠ grant) ---
    allowed_orgs: frozenset[Org] = field(default_factory=frozenset)
    allowed_roles: frozenset[str] = field(default_factory=frozenset)

    # --- never-external hard-deny dimension (reused Step-1 mechanism) ---
    sensitivity: Optional[Sensitivity] = None

    # --- link to the Step-1 policy object (required unless gap) ---
    policy_object_id: Optional[str] = None

    # --- redaction (required when external_projection_available is False, AC7) ---
    redaction_reason: Optional[str] = None

    # --- internal-only provenance refs (NEVER external — AC9) ---
    provenance_refs: tuple[str, ...] = ()

    # --- optional descriptive / confidence ---
    name: Optional[str] = None
    claim: Optional[str] = None
    confidence: Optional[float] = None

    # --- gap fields (required when collection_status is GAP, AC8) ---
    gap_owner: Optional[str] = None
    gap_reason: Optional[str] = None
    gap_next_action: Optional[str] = None

    @property
    def is_gap(self) -> bool:
        return self.collection_status is CollectionStatus.GAP

    @property
    def is_never_external(self) -> bool:
        return self.sensitivity is not None

    @property
    def source_count(self) -> int:
        return len(self.provenance_refs)


@dataclass(frozen=True)
class RegistryChange:
    """An auditable change to registry metadata (AC10).

    A change that makes a source externally visible requires HUMAN ratification
    (``registry.apply_registry_change``); AI may only propose.
    """

    source_id: str
    field: str
    prior_value: Optional[str]
    new_value: Optional[str]
    actor_org: str
    actor_role: str
    actor_is_ai: bool
    rationale: str
    decision_source: str
    timestamp: str
    increases_external_exposure: bool
