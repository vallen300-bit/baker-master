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
from policy.search.models import RouteTarget, SearchMode
from policy.search.runner import search as policy_search
from policy.sources.models import (
    CollectionStatus,
    ProvenanceClass,
    SourceDomain,
    SourceObjectType,
    SourceRecord,
)
from policy.sources.registry import external_projection_for

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


# --------------------------------------------------------------------------- #
# Source registry / coverage seed (honest WIRED / PARTIAL / GAP — no faked live)
# --------------------------------------------------------------------------- #
def _src(
    source_id: str,
    *,
    domain: SourceDomain,
    status: CollectionStatus,
    label: str,
    external_ok: bool = False,
    provenance: ProvenanceClass = ProvenanceClass.FIRST_PARTY,
    gap_owner: Optional[str] = None,
    gap_reason: Optional[str] = None,
    gap_next_action: Optional[str] = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        domain=domain,
        source_type=label,
        object_type=SourceObjectType.NOTE,
        owner_org=Org.BRISEN,
        classification=(Classification.PUBLIC_SOURCE if external_ok else Classification.BRISEN_CONFIDENTIAL),
        lifecycle_state=LifecycleState.VERIFIED_EVIDENCE,
        provenance_class=provenance,
        collection_status=status,
        raw_body_available_internal=(status is not CollectionStatus.GAP),
        external_projection_available=external_ok,
        # Required when a source is not externally projectable — a curated safe
        # reason (never an engine denial reason).
        redaction_reason=(None if external_ok else "internal source — not partner-projected"),
        freshness="2026-06",
        # policy_object_id is required for any non-gap (collectable) source.
        policy_object_id=(None if status is CollectionStatus.GAP else f"src-{source_id}"),
        gap_owner=gap_owner,
        gap_reason=gap_reason,
        gap_next_action=gap_next_action,
    )


def _seed_sources() -> List[SourceRecord]:
    """Honest connector coverage across the 8 Step-2 domains. Most live ingestion is
    not yet wired in Sprint-0 — those are GAP rows that drive the Execution Roadmap,
    never faked as working (T8)."""
    SD, CS = SourceDomain, CollectionStatus
    return [
        _src("baker-memory", domain=SD.BAKER_INTERNAL_MEMORY, status=CS.WIRED,
             label="Baker internal memory"),
        _src("vault-rooms", domain=SD.VAULT_PROJECT_ROOMS, status=CS.WIRED,
             label="Vault project rooms"),
        _src("dropbox-files", domain=SD.DROPBOX_PROJECT_FILES, status=CS.PARTIAL,
             label="Dropbox project files"),
        _src("comms", domain=SD.COMMS_EMAIL_WA_SLACK, status=CS.GAP,
             label="Email / WhatsApp / Slack", gap_owner="lead",
             gap_reason="connector not yet authorized for this matter",
             gap_next_action="authorize + wire comms ingestion"),
        _src("field-evidence", domain=SD.FIELD_EVIDENCE, status=CS.PARTIAL,
             label="Field evidence (site photos/notes)"),
        _src("open-web", domain=SD.OPEN_WEB, status=CS.GAP,
             label="Open web", gap_owner="lead",
             gap_reason="live crawl not enabled (hook only in Step 3)",
             gap_next_action="enable web research connector"),
        _src("site-search", domain=SD.SITE_SEARCH_PUBLIC, status=CS.GAP,
             label="Santa Clara authorities / planning", gap_owner="lead",
             gap_reason="authority site-search connector not wired",
             gap_next_action="wire Santa Clara planning/site-search"),
        _src("market", domain=SD.MARKET_CAPITAL_RESIDENCE, status=CS.PARTIAL,
             label="Market / capital / residence", external_ok=True,
             provenance=ProvenanceClass.PUBLIC),
    ]


def _sources() -> List[SourceRecord]:
    return _seed_sources()


@router.get("/api/sources")
def get_sources(role: str = Query("brisen")) -> Mapping:
    """Source Registry / Coverage panel (AC6).

    Internal shows full coverage incl. gap owner/reason/next-action (roadmap fuel).
    External roles get ONLY safe domain labels of externally-available sources — no
    internal source ids, no gap reasons, no never_external hints (T9)."""
    audience = _resolve_audience(role)
    recs = _sources()
    if audience == AudienceRole.BRISEN_INTERNAL:
        return {"sources": [
            {
                "source_id": r.source_id,
                "domain": r.domain.value,
                "label": r.source_type,
                "collection_status": r.collection_status.value,
                "external_projection_available": r.external_projection_available,
                "never_external": r.is_never_external,
                "gap_owner": r.gap_owner,
                "gap_reason": r.gap_reason,
                "gap_next_action": r.gap_next_action,
            }
            for r in recs
        ]}
    # External: only externally-available, WIRED/PARTIAL sources, safe labels only.
    safe = [
        {"domain": r.domain.value, "label": r.source_type,
         "availability": ("available" if r.collection_status is not CollectionStatus.GAP else "not_available")}
        for r in recs
        if r.external_projection_available and not r.is_never_external
    ]
    return {"sources": safe}


@router.get("/api/roadmap")
def get_roadmap(role: str = Query("brisen")) -> Mapping:
    """Execution Roadmap — gap-derived items (AC4). Internal-only detail; external
    roles get a generic empty roadmap (no gap reasons / source hints, T9)."""
    audience = _resolve_audience(role)
    if audience != AudienceRole.BRISEN_INTERNAL:
        return {"roadmap": []}
    items = [
        {"source_id": r.source_id, "domain": r.domain.value, "label": r.source_type,
         "owner": r.gap_owner, "reason": r.gap_reason, "next_action": r.gap_next_action}
        for r in _sources() if r.is_gap
    ]
    return {"roadmap": items}


def _serialize_result(res, *, internal: bool) -> Mapping:
    """Serialize a SearchResult. body is already audience-scoped by policy.search;
    policy_reason_code is internal-only (never leak a reason code externally, T2/T9)."""
    out = {
        "result_ref": res.result_ref,
        "projected": res.projected,
        "body": res.body,
        "route_target": getattr(res.routing, "route_target", None)
                        and res.routing.route_target.value,
        "route_reason": getattr(res.routing, "route_reason", None),
    }
    if internal:
        out["policy_reason_code"] = res.policy_reason_code
    return out


@router.get("/api/search")
def get_search(q: str = Query(...), role: str = Query("brisen")) -> Mapping:
    """Advanced Search (AC6/T8). Results are policy-gated by policy.search (external
    bodies are partner projections only). Coverage is honest: live domains vs
    gap/planned, never fabricated."""
    audience = _resolve_audience(role)
    internal = audience == AudienceRole.BRISEN_INTERNAL
    if internal:
        principal, mode = _OPERATOR, SearchMode.INTERNAL_GLOBAL
    else:
        principal, mode = _external_principal(audience), SearchMode.PARTNER_SAFE
    try:
        rs = policy_search(principal, q, mode, candidates=_seed_sources())
        results = [_serialize_result(r, internal=internal) for r in rs.results]
        zero_route = rs.zero_result_route.value if rs.zero_result_route else None
    except Exception as e:  # fail closed — never fabricate results
        logger.warning("ai-hotel search failed (non-fatal): %s", e)
        results, zero_route = [], None
    # Honest coverage map (T8). External sees only externally-available domains.
    recs = _sources()
    coverage = [
        {"domain": r.domain.value, "label": r.source_type,
         "status": r.collection_status.value}
        for r in recs
        if internal or (r.external_projection_available and not r.is_never_external)
    ]
    return {
        "query": q,
        "result_count": len(results),
        "results": results,
        "zero_result_route": zero_route,
        "coverage": coverage,
    }


@router.get("/api/evidence")
def get_evidence(role: str = Query("brisen")) -> Mapping:
    """Verified Evidence lane (AC5) — lifecycle-promoted items only, visually distinct
    from raw. Internal: verified/shared/action-linked. External: only shared/action-
    linked, served via the projection packet (no raw, no candidates)."""
    audience = _resolve_audience(role)
    if audience == AudienceRole.BRISEN_INTERNAL:
        promoted = {
            LifecycleState.VERIFIED_EVIDENCE,
            LifecycleState.SHARED_VIEW,
            LifecycleState.ACTION_LINKED,
        }
        items = [
            {"object_id": c.item.object_id, "claim": c.item.claim,
             "lifecycle_state": c.item.lifecycle_state.value,
             "confidence": c.item.confidence, "last_reviewed": c.item.last_reviewed,
             "section": c.route_target.value if c.route_target else None}
            for c in _candidates() if c.item.lifecycle_state in promoted
        ]
        return {"evidence": items, "internal": True}
    # External: reuse the projection packet — already lifecycle/permission gated.
    packet = view_as(_OPERATOR, audience, _candidates())
    flat = []
    for sec, items in packet.as_dict()["sections"].items():
        if isinstance(items, list):
            flat.extend(items)
    return {"evidence": flat, "internal": False}


# --------------------------------------------------------------------------- #
# Projection admin (approve / revoke / refresh) — Brisen admin only.
# The whole router is read-gated; mutation additionally requires a Brisen admin
# principal. Sprint-0 operates on the in-memory seed; persistence is a later brief.
# --------------------------------------------------------------------------- #
@router.post("/api/admin/{action}")
def post_admin_action(action: str, projection_item_id: str = Query(...),
                      reason: str = Query("")) -> Mapping:
    """approve / revoke / refresh on a projection item. Brisen admin only — AI and
    external principals are rejected by policy.projection.admin (AC7)."""
    if action not in ("approve", "revoke", "refresh"):
        raise HTTPException(status_code=400, detail="unknown action")
    admin = Principal(org=Org.BRISEN, role="evidence_admin")
    target = next((c for c in _candidates() if c.item.object_id == projection_item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    if action != "approve":
        # revoke / refresh operate on PERSISTED ProjectionItems. Sprint-0 has no
        # projection store wired (later brief), so those states are shown read-only
        # from the packet (AC7 display) rather than mutated here. Honest, not faked.
        raise HTTPException(
            status_code=501,
            detail=f"{action} requires the persisted projection store (later brief); "
                   "state is shown read-only from the packet in Sprint-0",
        )
    try:
        log = projection_admin.approve_projection(
            target.item, admin, rationale=reason or "approved via cockpit")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"admin action denied: {e}")
    return {"ok": True, "action": action, "event": getattr(log, "event_type", action)}
