"""AI Hotel Lab — Cockpit UI backend (AI_HOTEL_LAB_COCKPIT_UI_1, Sprint-0 Step 5).

The first live operating surface over the governed Steps 1-4 backend. This module
is the SERVER-SIDE boundary: every partner/external view is built here by calling
`policy.projection` server-side, so the browser never receives raw rows, internal
ids, or source hints for an external role (AC2). There is NO second permission
engine here or in JS (T6) — visibility is decided only by `policy.engine` /
`policy.projection`.

Access model (Sprint-0): the cockpit is Brisen-authenticated (reuses the AI-Hotel
read auth gate). The role selector is a server-backed *view-as*: selecting an
external role calls `policy.projection.view_as(...)`, which returns the BYTE-
IDENTICAL external packet a real partner would receive — so the no-leak property
holds for the preview exactly as it would for a live partner session (AC3).

Data: Sprint-0 ships a curated AI-Hotel evidence seed (clearly a starting dataset,
not faked live ingestion). It flows through the REAL policy engine + projector, so
the permission boundary is exercised end-to-end. Connector liveness is reported
honestly by the Source Registry / Coverage panel + search (live vs gap/planned) —
no connector is faked (T8).
"""
from __future__ import annotations

import logging
from typing import List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from policy.models import (
    Action,
    Classification,
    EvidenceItem,
    LifecycleState,
    ObjectType,
    Org,
    Principal,
    Sensitivity,
)
from policy.projection import admin as projection_admin
from policy.projection.models import (
    AUDIENCE_ORG,
    AUDIENCE_PRINCIPAL_ROLE,
    EXTERNAL_AUDIENCES,
    AudienceRole,
)
from policy.projection.packets import (
    ProjectionCandidate,
    build_internal_preview_packet,
    external_item_audit,
    serve_external_packet,
    view_as,
)
from policy.search.models import RouteTarget

logger = logging.getLogger("baker.ai_hotel_lab")

router = APIRouter(prefix="/ai-hotel-lab", tags=["ai-hotel-lab"])

# The authenticated cockpit operator. Sprint-0: a single Brisen director session
# (the role selector drives view-as from this principal). A real partner login
# would resolve to its own external Principal — the serving functions are
# principal-driven, so that swap needs no logic change here.
_OPERATOR = Principal(org=Org.BRISEN, role="director")


# --------------------------------------------------------------------------- #
# Role resolution (server-side only — never trust a client role claim)
# --------------------------------------------------------------------------- #
_ROLE_PARAM_TO_AUDIENCE: Mapping[str, AudienceRole] = {
    "brisen": AudienceRole.BRISEN_INTERNAL,
    "brisen_internal": AudienceRole.BRISEN_INTERNAL,
    "internal_brisen": AudienceRole.BRISEN_INTERNAL,
    "nvidia": AudienceRole.NVIDIA_LIGHTHOUSE,
    "nvidia_lighthouse": AudienceRole.NVIDIA_LIGHTHOUSE,
    "mohg": AudienceRole.MOHG_OPS_STANDARDS,
    "mohg_ops_standards": AudienceRole.MOHG_OPS_STANDARDS,
    "venue": AudienceRole.VENUE_OWNER_SITE_DILIGENCE,
    "venue_owner": AudienceRole.VENUE_OWNER_SITE_DILIGENCE,
    "venue_owner_site_diligence": AudienceRole.VENUE_OWNER_SITE_DILIGENCE,
}


def _resolve_audience(role: str) -> AudienceRole:
    """Map a UI role param to an AudienceRole. Unknown role -> 400 (fail closed)."""
    audience = _ROLE_PARAM_TO_AUDIENCE.get((role or "").strip().lower())
    if audience is None:
        raise HTTPException(status_code=400, detail="unknown role")
    return audience


def _external_principal(audience: AudienceRole) -> Principal:
    """The Sprint-0 simulated external principal for an external audience."""
    return Principal(org=AUDIENCE_ORG[audience], role=AUDIENCE_PRINCIPAL_ROLE[audience])


# --------------------------------------------------------------------------- #
# Seed candidate dataset (curated AI-Hotel evidence; runs through real policy)
# --------------------------------------------------------------------------- #
def _ev(
    object_id: str,
    *,
    state: LifecycleState,
    classification: Classification,
    claim: str,
    allowed_orgs: frozenset = frozenset(),
    sensitivity: Optional[Sensitivity] = None,
    confidence: Optional[float] = None,
    source_type: str = "internal_note",
    source_refs: tuple = (),
    freshness: str = "2026-06",
    last_reviewed: Optional[str] = None,
    raw_body: Optional[str] = None,
    title: Optional[str] = None,
) -> EvidenceItem:
    return EvidenceItem(
        object_id=object_id,
        object_type=ObjectType.CLAIM,
        classification=classification,
        lifecycle_state=state,
        owner_org=Org.BRISEN,
        owner="brisen_evidence_admin",
        sensitivity=sensitivity,
        allowed_orgs=allowed_orgs,
        allowed_roles=frozenset(),
        confidence=confidence,
        source_refs=source_refs,
        source_type=source_type,
        claim=claim,
        freshness=freshness,
        last_reviewed=last_reviewed,
        raw_body=raw_body,
        title=title,
    )


def _seed_candidates() -> List[ProjectionCandidate]:
    """Curated AI-Hotel evidence across orgs / lifecycle states / sections.

    Includes externally-visible (shared/action-linked partner-safe) items, raw
    internal-only signals, a never_external item (sensitivity set), and a revoked
    and a stale example — so every threat path has live data to exercise.
    """
    C = Classification
    L = LifecycleState
    RT = RouteTarget
    cands: List[ProjectionCandidate] = []

    # --- NVIDIA partner-safe, externally visible -----------------------------
    cands.append(ProjectionCandidate(
        item=_ev(
            "nv-lighthouse-thesis",
            state=L.SHARED_VIEW, classification=C.PARTNER_SAFE_NVIDIA,
            claim="AI-hospitality lighthouse thesis validated against operator workflow.",
            allowed_orgs=frozenset({Org.NVIDIA}), confidence=0.82,
            source_type="research_artifact", source_refs=("r1", "r2"),
            last_reviewed="2026-06-18",
            raw_body="INTERNAL raw: NVIDIA call notes incl. pricing.", title="NVIDIA call raw",
        ),
        route_target=RT.NVIDIA_LIGHTHOUSE,
    ))
    cands.append(ProjectionCandidate(
        item=_ev(
            "nv-compute-action",
            state=L.ACTION_LINKED, classification=C.PARTNER_SAFE_NVIDIA,
            claim="Reference-architecture pilot scoped for the lighthouse site.",
            allowed_orgs=frozenset({Org.NVIDIA}), confidence=0.74,
            source_type="meeting", source_refs=("m9",), last_reviewed="2026-06-20",
        ),
        route_target=RT.NVIDIA_LIGHTHOUSE,
        action_safe_text="Confirm pilot scope at next joint review.",
    ))

    # --- MOHG partner-safe, externally visible -------------------------------
    cands.append(ProjectionCandidate(
        item=_ev(
            "mohg-ops-standard",
            state=L.SHARED_VIEW, classification=C.PARTNER_SAFE_MOHG,
            claim="Service-standard alignment confirmed for AI-assisted operations.",
            allowed_orgs=frozenset({Org.MOHG}), confidence=0.79,
            source_type="research_artifact", source_refs=("r7",), last_reviewed="2026-06-15",
        ),
        route_target=RT.MANDARIN_ORIENTAL_OPERATOR_LOGIC,
    ))
    # MOHG stale example
    cands.append(ProjectionCandidate(
        item=_ev(
            "mohg-stale-metric",
            state=L.SHARED_VIEW, classification=C.PARTNER_SAFE_MOHG,
            claim="Occupancy uplift estimate (under refresh).",
            allowed_orgs=frozenset({Org.MOHG}), confidence=0.6,
            source_type="market_data", source_refs=("r8",), last_reviewed="2026-04-02",
        ),
        route_target=RT.MARKET_PROOF_COMPETITIVE_SET,
        stale=True,
    ))

    # --- Venue owner partner-safe, externally visible ------------------------
    cands.append(ProjectionCandidate(
        item=_ev(
            "venue-site-diligence",
            state=L.SHARED_VIEW, classification=C.PARTNER_SAFE_VENUE_OWNER,
            claim="Santa Clara site diligence supports the operating thesis.",
            allowed_orgs=frozenset({Org.VENUE_OWNER}), confidence=0.71,
            source_type="site_evidence", source_refs=("s3", "s4"), last_reviewed="2026-06-19",
        ),
        route_target=RT.SANTA_CLARA_SITE_THESIS,
    ))
    # Venue revoked example
    cands.append(ProjectionCandidate(
        item=_ev(
            "venue-revoked-item",
            state=L.SHARED_VIEW, classification=C.PARTNER_SAFE_VENUE_OWNER,
            claim="Prior site note (withdrawn).",
            allowed_orgs=frozenset({Org.VENUE_OWNER}), confidence=0.5,
            source_type="site_evidence", source_refs=("s9",), last_reviewed="2026-05-30",
        ),
        route_target=RT.SANTA_CLARA_SITE_THESIS,
        revoked=True, revoked_by="brisen_evidence_admin", revoke_reason="superseded",
    ))

    # --- Brisen-confidential, internal-only (must NOT reach any external) -----
    cands.append(ProjectionCandidate(
        item=_ev(
            "brisen-financing-strategy",
            state=L.VERIFIED_EVIDENCE, classification=C.BRISEN_CONFIDENTIAL,
            claim="Financing structure and negotiation posture.",
            confidence=0.9, source_type="strategy_note", source_refs=("f1", "f2"),
            sensitivity=Sensitivity.FINANCIAL, last_reviewed="2026-06-21",
            raw_body="INTERNAL raw: term sheet figures.", title="Financing strategy raw",
        ),
        route_target=RT.BUSINESS_CASE_FINANCING,
    ))
    # --- Raw signal, internal-only -------------------------------------------
    cands.append(ProjectionCandidate(
        item=_ev(
            "raw-competitor-signal",
            state=L.RAW_SIGNAL, classification=C.BRISEN_RAW,
            claim="Unconfirmed competitor move (amber).",
            source_type="open_web", source_refs=("w1",),
            raw_body="INTERNAL raw: scraped competitor press snippet.",
            title="Competitor raw signal",
        ),
        route_target=RT.MARKET_PROOF_COMPETITIVE_SET,
    ))
    # --- Public source (broadly safe) ----------------------------------------
    cands.append(ProjectionCandidate(
        item=_ev(
            "public-press-item",
            state=L.SHARED_VIEW, classification=C.PUBLIC_SOURCE,
            claim="Public hospitality-press item on AI in luxury operations.",
            allowed_orgs=frozenset({Org.NVIDIA, Org.MOHG, Org.VENUE_OWNER}),
            confidence=0.65, source_type="press", source_refs=("p1",),
            last_reviewed="2026-06-10",
        ),
        route_target=RT.MARKETING_PR,
    ))
    return cands


def _candidates() -> List[ProjectionCandidate]:
    """Hook point — Sprint-0 returns the seed. A later brief swaps this for the
    live projection store (``policy.projection.store.load_projection_items``)."""
    return _seed_candidates()


# --------------------------------------------------------------------------- #
# Auth — reuse the existing AI-Hotel read gate; injected by dashboard at include.
# --------------------------------------------------------------------------- #
# dashboard.py wires the real dependency in via router dependencies at include
# time; this placeholder keeps the module importable/testable standalone.
def _read_auth():  # pragma: no cover - overridden at include time
    return None


# --------------------------------------------------------------------------- #
# Endpoints — every external payload is built server-side via policy.projection.
# --------------------------------------------------------------------------- #
@router.get("/api/packet")
def get_packet(role: str = Query("brisen")) -> Mapping:
    """The role's view packet.

    - brisen_internal -> full internal-preview packet.
    - external roles  -> view_as(...) returns the byte-identical EXTERNAL packet a
      real partner gets: allowlist fields only, generic empty state, no raw rows,
      ids, counts, reasons, or source hints (AC2/AC3/T1/T2/T9).
    """
    audience = _resolve_audience(role)
    cands = _candidates()
    if audience == AudienceRole.BRISEN_INTERNAL:
        packet = build_internal_preview_packet(cands)
    else:
        # Server-backed view-as: the operator is Brisen; the packet is the partner's.
        packet = view_as(_OPERATOR, audience, cands)
    return packet.as_dict()


@router.get("/api/raw-signals")
def get_raw_signals(role: str = Query("brisen")) -> Mapping:
    """Raw Signal Inbox — INTERNAL ONLY (AC4/T1). Any external role gets nothing
    (not even counts): a flat 403-equivalent generic empty body."""
    audience = _resolve_audience(role)
    if audience != AudienceRole.BRISEN_INTERNAL:
        # No raw signal text, ids, counts, or section hints for an external role.
        return {"raw_signals": [], "internal_only": True}
    signals = [
        {
            "object_id": c.item.object_id,
            "section": (c.route_target.value if c.route_target else None),
            "claim": c.item.claim,
            "title": c.item.title,
            "raw_body": c.item.raw_body,
            "source_type": c.item.source_type,
            "freshness": c.item.freshness,
        }
        for c in _candidates()
        if c.item.lifecycle_state == LifecycleState.RAW_SIGNAL
    ]
    return {"raw_signals": signals, "internal_only": True}


@router.get("/api/item/{projection_item_id}/audit")
def get_item_audit(projection_item_id: str, role: str = Query("brisen")) -> Mapping:
    """Audit summary for a projected item.

    External roles get the audience-scoped SAFE summary only if the item is in
    THEIR own packet; another audience's item is absent (404), never leaked
    (T3 cross-role isolation)."""
    audience = _resolve_audience(role)
    cands = _candidates()
    if audience == AudienceRole.BRISEN_INTERNAL:
        for c in cands:
            if c.item.object_id == projection_item_id:
                return {
                    "object_id": c.item.object_id,
                    "lifecycle_state": c.item.lifecycle_state.value,
                    "owner": c.item.owner,
                    "revoked": c.revoked,
                    "stale": c.stale,
                    "source_refs": list(c.item.source_refs),
                }
        raise HTTPException(status_code=404, detail="not found")
    principal = _external_principal(audience)
    summary = external_item_audit(principal, projection_item_id, cands)
    if summary is None:
        raise HTTPException(status_code=404, detail="not found")
    return summary
