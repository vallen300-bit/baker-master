"""Object model for the AI Hotel Lab search + routing layer (Step 3).

Vocabulary is BINDING per codex-arch product framing (bus #3679). This layer is a
CONSUMER of the Step-1 policy engine + Step-2 source registry — it adds NO new
permission vocabulary and forks NO taxonomy:

* ``Org`` / ``Classification`` / ``LifecycleState`` / ``Sensitivity`` / ``Action``
  come from :mod:`policy.models` (Step-1, single source of truth).
* ``SourceDomain`` / ``SourceObjectType`` come from :mod:`policy.sources.models`
  (Step-2, single source of truth).
* This module adds ONLY the search/routing-specific vocabulary: the 5 ``SearchMode``
  values, the 13 ``RouteTarget`` values, the ``RoutingMethod`` discriminator, and
  the amber ``RawSignal`` record (16 fields). Routing NEVER decides external
  visibility — that stays the Step-1 engine's job.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# Step-1 / Step-2 single-source-of-truth enums — reused, never duplicated.
from policy.models import Classification, LifecycleState, Org
from policy.sources.models import SourceDomain, SourceObjectType


# --------------------------------------------------------------------------- #
# Search modes (codex-arch #3679 — exactly 5)
# --------------------------------------------------------------------------- #
class SearchMode(str, enum.Enum):
    """The 5 search modes. ``web_live_hook`` is DEFINED only (no crawling in Step 3)."""

    INTERNAL_GLOBAL = "internal_global"      # all permitted internal sources (Brisen role)
    PARTNER_SAFE = "partner_safe"            # projected/approved material for an external role
    SOURCE_DOMAIN = "source_domain"          # filter by Step-2 domain
    SECTION = "section"                       # search within a route_target / audience view
    WEB_LIVE_HOOK = "web_live_hook"          # hook only; any web result enters raw_signal first


# --------------------------------------------------------------------------- #
# Routing targets (codex-arch #3679 — exactly 13, stable)
# --------------------------------------------------------------------------- #
class RouteTarget(str, enum.Enum):
    """The 13 dashboard route targets. Stable enum — do NOT add values without an
    explicit AH1 brief (Step-5 navigation binds to these)."""

    EXECUTIVE_SUMMARY = "executive_summary"
    FIELD_EVIDENCE = "field_evidence"
    SANTA_CLARA_SITE_THESIS = "santa_clara_site_thesis"
    NVIDIA_LIGHTHOUSE = "nvidia_lighthouse"
    MANDARIN_ORIENTAL_OPERATOR_LOGIC = "mandarin_oriental_operator_logic"
    MARKET_PROOF_COMPETITIVE_SET = "market_proof_competitive_set"
    BUSINESS_CASE_FINANCING = "business_case_financing"
    RESIDENCE_BUYERS = "residence_buyers"
    MARKETING_PR = "marketing_pr"
    VENDORS_FUTURE_OPERATING_LAYER = "vendors_future_operating_layer"
    EXECUTION_ROADMAP = "execution_roadmap"
    SOURCE_GAP_UNASSIGNED_REVIEW = "source_gap_unassigned_review"
    RISK_PERMISSIONS_REVIEW = "risk_permissions_review"


class RoutingMethod(str, enum.Enum):
    """How a route was decided. ``llm`` is assist-only (proposes, never finalises);
    ``human_override`` always wins and is audited."""

    RULE = "rule"
    LLM = "llm"
    HUMAN_OVERRIDE = "human_override"


# Route targets that are review/triage buckets, not confident content placements.
REVIEW_TARGETS: frozenset[RouteTarget] = frozenset(
    {RouteTarget.RISK_PERMISSIONS_REVIEW, RouteTarget.SOURCE_GAP_UNASSIGNED_REVIEW}
)


# --------------------------------------------------------------------------- #
# Routing records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RoutingSuggestion:
    """A proposed route. NEVER finalises a placement and NEVER mutates policy.

    ``method`` records whether a deterministic rule or the LLM assist proposed it.
    ``rule_no`` is the 1-11 deterministic rule index (``None`` for LLM-only).
    """

    route_target: RouteTarget
    route_reason: str
    method: RoutingMethod
    confidence: float
    secondary_targets: tuple[RouteTarget, ...] = ()
    rule_no: Optional[int] = None

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "route_target": self.route_target.value,
            "route_reason": self.route_reason,
            "method": self.method.value,
            "confidence": self.confidence,
            "secondary_targets": [t.value for t in self.secondary_targets],
            "rule_no": self.rule_no,
        }


@dataclass(frozen=True)
class RoutingOverride:
    """A human override of a routing suggestion (AC5). Audited; never mutates policy.

    The override changes ONLY the route_target (where a result is filed). It can
    never widen visibility — classification / allowed_orgs / lifecycle are owned by
    the Step-1 engine and are untouched here (governance invariant: route overrides
    never silently mutate policy).
    """

    signal_id: str
    prior_target: RouteTarget
    new_target: RouteTarget
    actor_org: str
    actor_role: str
    actor_is_ai: bool
    rationale: str
    timestamp: str

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "signal_id": self.signal_id,
            "prior_target": self.prior_target.value,
            "new_target": self.new_target.value,
            "actor_org": self.actor_org,
            "actor_role": self.actor_role,
            "actor_is_ai": self.actor_is_ai,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


# --------------------------------------------------------------------------- #
# Raw amber signal (codex-arch #3679 — all 16 fields)
# --------------------------------------------------------------------------- #
@dataclass
class RawSignal:
    """An amber raw-signal record — useful but UNCONFIRMED material (AC4).

    Lifecycle is FIXED at ``raw_signal``: a search result enters here and can never
    skip ahead. Promotion to ``verified_evidence`` / ``shared_view`` happens ONLY
    through the existing Step-1 lifecycle gate (``policy.lifecycle``) — there is no
    promotion path on this dataclass (AC7).

    The 16 codex-arch fields (grouped):

    1.  ``signal_id``                       opaque id
    2.  ``source_id``                       Step-2 registry source
    3.  ``source_domain``                   Step-2 domain
    4.  ``object_type``                     Step-2 object type
    5.  ``raw_summary_internal``            internal-only summary (NEVER external)
    6.  ``projected_summary_external``      partner-safe summary (projection-built, may be None)
    7.  ``proposed_route_target``           routing suggestion target
    8.  ``route_reason``                    routing suggestion reason
    9.  ``confidence``                      routing/evidence confidence
    10. ``lifecycle_state``                 FIXED raw_signal
    11. ``classification`` / ``allowed_view`` / ``allowed_org``  (classification + allowed_orgs)
    12. ``owner`` / ``reviewer``            ownership
    13. ``freshness`` / ``observed_at``     recency
    14. ``evidence_needed_to_confirm``      what would promote it
    15. ``duplicate_of`` / ``related_signal_ids``  dedup links
    16. ``audit_trail``                     append-only event refs
    """

    signal_id: str                                          # 1
    source_id: str                                          # 2
    source_domain: SourceDomain                             # 3
    object_type: SourceObjectType                           # 4
    raw_summary_internal: str                              # 5 — internal-only
    proposed_route_target: RouteTarget                     # 7
    route_reason: str                                      # 8
    classification: Classification                         # 11a
    owner: str                                            # 12a
    freshness: str                                         # 13a
    observed_at: str                                       # 13b
    evidence_needed_to_confirm: str                       # 14

    projected_summary_external: Optional[str] = None       # 6 — projection-built only
    confidence: Optional[float] = None                     # 9
    lifecycle_state: LifecycleState = LifecycleState.RAW_SIGNAL  # 10 — FIXED
    allowed_orgs: frozenset[Org] = field(default_factory=frozenset)  # 11b allowed_view/org
    allowed_roles: frozenset[str] = field(default_factory=frozenset)  # 11c
    reviewer: Optional[str] = None                         # 12b
    policy_object_id: Optional[str] = None                 # link to Step-1 object for promotion
    duplicate_of: Optional[str] = None                     # 15a
    related_signal_ids: tuple[str, ...] = ()               # 15b
    audit_trail: tuple[str, ...] = ()                      # 16

    def internal_view(self) -> Mapping[str, Any]:
        """Full internal inventory view (Brisen-only)."""

        return {
            "signal_id": self.signal_id,
            "source_id": self.source_id,
            "source_domain": self.source_domain.value,
            "object_type": self.object_type.value,
            "raw_summary_internal": self.raw_summary_internal,
            "proposed_route_target": self.proposed_route_target.value,
            "route_reason": self.route_reason,
            "confidence": self.confidence,
            "lifecycle_state": self.lifecycle_state.value,
            "classification": self.classification.value,
            "allowed_orgs": sorted(o.value for o in self.allowed_orgs),
            "owner": self.owner,
            "reviewer": self.reviewer,
            "freshness": self.freshness,
            "observed_at": self.observed_at,
            "evidence_needed_to_confirm": self.evidence_needed_to_confirm,
            "duplicate_of": self.duplicate_of,
            "related_signal_ids": list(self.related_signal_ids),
        }


# --------------------------------------------------------------------------- #
# Search query + result records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SearchResult:
    """One search hit. The body is ALWAYS audience-scoped:

    * external principals get ``body`` built ONLY from ``partner_projection``
      (never raw source text);
    * internal principals get the internal inventory view.

    Every result carries a ``routing`` suggestion (AC3). ``result_ref`` is the
    object handle (policy object_id for external, source_id for internal) — never a
    raw path / message-id / provenance ref.
    """

    result_ref: str
    projected: bool                       # True => body is a partner projection
    body: Mapping[str, Any]
    routing: RoutingSuggestion
    policy_reason_code: str


@dataclass(frozen=True)
class SearchResultSet:
    """The full result of a search. ``zero_result`` rows never leak hidden material:
    a zero-result set carries a ``source_gap`` candidate, never a 'N hidden' count
    (governance invariant: zero-results never reveal the existence of hidden rows)."""

    mode: SearchMode
    query: str
    results: tuple[SearchResult, ...]
    zero_result_route: Optional[RouteTarget] = None
    zero_result_reason: Optional[str] = None

    @property
    def result_count(self) -> int:
        return len(self.results)

    @property
    def is_zero_result(self) -> bool:
        return not self.results
