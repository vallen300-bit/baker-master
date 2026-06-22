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
from fastapi.responses import HTMLResponse

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
from policy.projection import admin_store
from policy.projection.models import (
    AUDIENCE_ORG,
    AUDIENCE_PRINCIPAL_ROLE,
    EXTERNAL_AUDIENCES,
    AudienceRole,
    ProjectionState,
)
from policy.projection.packets import (
    ProjectionCandidate,
    build_internal_preview_packet,
    external_item_audit,
    serve_external_packet,
    view_as,
)
from policy.projection.projector import build_projection_item
from policy.projection.store import ProjectionStoreUnavailableError
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


def _apply_overlay(
    cands: List[ProjectionCandidate], overlay: Mapping[str, "admin_store.AdminOverlayState"]
) -> List[ProjectionCandidate]:
    """Overlay the persisted admin state onto seed candidates (Step 5.1).

    A persisted record is AUTHORITATIVE for revoke/stale on its source item; items
    with no persisted record keep their seed defaults. Revoke is a HARD STOP and
    supersedes stale (a single terminal state) — the same chokepoint then drives every
    surface (packet / evidence / audit), so a revoked item is absent generically."""
    for c in cands:
        st = overlay.get(c.item.object_id)
        if st is None:
            continue
        if st.revoked:
            c.revoked = True
            c.revoked_by = st.revoked_by or c.revoked_by
            c.revoke_reason = st.revoke_reason or c.revoke_reason
            c.stale = False
        else:
            c.stale = st.stale
    return cands


def _candidates() -> List[ProjectionCandidate]:
    """Seed candidates with the persisted admin overlay applied (INTERNAL-tolerant).

    Step 5.1 wires the live projection-admin store: revoke/refresh decisions persisted
    by the admin endpoint are overlaid here so every consumer (packet / evidence /
    audit) sees the final admin state. On store outage the Brisen-internal view
    degrades to seed defaults (Brisen's own data) rather than going dark; external
    surfaces use ``_external_candidates`` which fails closed instead."""
    try:
        overlay = admin_store.load_admin_overlay()
    except ProjectionStoreUnavailableError:
        logger.warning("projection admin overlay unavailable — internal view uses seed defaults")
        overlay = {}
    return _apply_overlay(_seed_candidates(), overlay)


def _external_candidates() -> List[ProjectionCandidate]:
    """Seed + persisted overlay for an EXTERNAL surface (STRICT / fail-closed).

    Raises ``ProjectionStoreUnavailableError`` if the overlay can't be loaded; the
    caller returns a GENERIC unavailable packet — never a raw or last-known partner
    body (T11). This guarantees a revoked item can never reappear because the store
    had a transient error."""
    overlay = admin_store.load_admin_overlay()
    return _apply_overlay(_seed_candidates(), overlay)


# --------------------------------------------------------------------------- #
# Auth — reuse the existing AI-Hotel read gate; injected by dashboard at include.
# --------------------------------------------------------------------------- #
# dashboard.py wires the real dependency in via router dependencies at include
# time; this placeholder keeps the module importable/testable standalone.
def _read_auth():  # pragma: no cover - overridden at include time
    return None


# AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1: placeholder write-scope gate for the admin
# mutation route. dashboard.py binds the real `verify_ai_hotel_write_access` to this
# via `app.dependency_overrides` at include time (the module can't import dashboard —
# circular). Standalone (no override) it is a no-op so the module stays importable and
# direct unit calls to post_admin_action are unaffected; the HTTP write gate is proven
# via TestClient. The inner policy-layer human-admin check is unchanged.
def _write_auth():  # pragma: no cover - overridden at include time
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
    if audience == AudienceRole.BRISEN_INTERNAL:
        return build_internal_preview_packet(_candidates()).as_dict()
    # Server-backed view-as: the operator is Brisen; the packet is the partner's.
    try:
        cands = _external_candidates()
    except ProjectionStoreUnavailableError:
        # Fail closed: generic empty packet (NO raw / last-known fallback) so a revoked
        # item can never resurface on a store blip (T11).
        logger.warning("admin overlay unavailable — serving generic empty packet to %s", role)
        return view_as(_OPERATOR, audience, []).as_dict()
    return view_as(_OPERATOR, audience, cands).as_dict()


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
    if audience == AudienceRole.BRISEN_INTERNAL:
        for c in _candidates():
            if c.item.object_id == projection_item_id:
                return {
                    "object_id": c.item.object_id,
                    "lifecycle_state": c.item.lifecycle_state.value,
                    "owner": c.item.owner,
                    "revoked": c.revoked,
                    "revoked_by": c.revoked_by,
                    "revoke_reason": c.revoke_reason,
                    "stale": c.stale,
                    "source_refs": list(c.item.source_refs),
                }
        raise HTTPException(status_code=404, detail="not found")
    # External: audience-scoped safe summary, built from the persisted-overlay packet.
    # Fail closed on store outage -> absent (404), never a leaked existence hint (T11).
    try:
        cands = _external_candidates()
    except ProjectionStoreUnavailableError:
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


def _external_coverage() -> List[Mapping]:
    """Honest source-coverage map for an external role — only externally-available,
    non-never-external sources, with status only (no internal ids / gap reasons). Safe
    to serve even when item content is withheld (e.g. fail-closed search)."""
    return [
        {"domain": r.domain.value, "label": r.source_type,
         "status": r.collection_status.value}
        for r in _sources()
        if r.external_projection_available and not r.is_never_external
    ]


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
    """Serialize a SearchResult. body is already audience-scoped by policy.search.

    INTERNAL-ONLY fields (deputy-codex G2 #3879 + lead G4 #3892, T9 source-hint leak):
    route_target reveals the internal section taxonomy and route_reason reveals the
    internal routing rules ("rule N: ... -> <section>", "llm assist: ..."), and
    policy_reason_code is a denial/allow code. NONE of these may reach an external
    role — they are emitted only for internal Brisen."""
    out = {
        "result_ref": res.result_ref,
        "projected": res.projected,
        "body": res.body,
    }
    if internal:
        out["route_target"] = (getattr(res.routing, "route_target", None)
                               and res.routing.route_target.value)
        out["route_reason"] = getattr(res.routing, "route_reason", None)
        out["policy_reason_code"] = res.policy_reason_code
    return out


@router.get("/api/search")
def get_search(q: str = Query(...), role: str = Query("brisen")) -> Mapping:
    """Advanced Search (AC6/T8). Results are policy-gated by policy.search (external
    bodies are partner projections only). Coverage is honest: live domains vs
    gap/planned, never fabricated."""
    audience = _resolve_audience(role)
    internal = audience == AudienceRole.BRISEN_INTERNAL
    revoked_ids: set = set()
    if internal:
        principal, mode = _OPERATOR, SearchMode.INTERNAL_GLOBAL
    else:
        principal, mode = _external_principal(audience), SearchMode.PARTNER_SAFE
        # deputy-codex G2 #3970 (HIGH T2/T10/AC3): /api/search is a partner surface and
        # MUST honor the persisted revoke overlay. An external search result whose
        # underlying source-evidence id is revoked must be SUPPRESSED — otherwise a
        # source row tied to a revoked item still returns the revoked claim. Fail closed
        # on store outage: serve no external results (never leak a possibly-revoked row).
        try:
            overlay = admin_store.load_admin_overlay()
        except ProjectionStoreUnavailableError:
            logger.warning("admin overlay unavailable — empty external search for %s", role)
            return {"query": q, "result_count": 0, "results": [],
                    "zero_result_route": None, "coverage": _external_coverage()}
        revoked_ids = {sid for sid, st in overlay.items() if st.revoked}
    try:
        rs = policy_search(principal, q, mode, candidates=_seed_sources())
        results = []
        for r in rs.results:
            # External: drop any result whose object handle is a revoked source-evidence
            # id (selective suppression — visible neighbors still return). Internal keeps
            # everything (Brisen's own surface).
            if not internal and r.result_ref in revoked_ids:
                continue
            results.append(_serialize_result(r, internal=internal))
        # deputy-codex G2 #3879 (HIGH T2/T9): the zero-result ROUTE is an internal
        # routing/source-gap hint (e.g. "source_gap_unassigned_review"). It must NEVER
        # cross the boundary to an external role — external roles get a generic
        # no-results state only. Internal keeps the route for triage.
        zero_route = (rs.zero_result_route.value
                      if (internal and rs.zero_result_route) else None)
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
    # External: reuse the projection packet — already lifecycle/permission gated, and
    # built from the persisted overlay so revoked/stale items are absent. Fail closed
    # to an empty lane on store outage (never a raw / last-known fallback, T11).
    try:
        cands = _external_candidates()
    except ProjectionStoreUnavailableError:
        logger.warning("admin overlay unavailable — empty external evidence lane for %s", role)
        return {"evidence": [], "internal": False}
    packet = view_as(_OPERATOR, audience, cands)
    flat = []
    for sec, items in packet.as_dict()["sections"].items():
        if isinstance(items, list):
            flat.extend(items)
    return {"evidence": flat, "internal": False}


# --------------------------------------------------------------------------- #
# Projection admin (approve / revoke / refresh) — Brisen admin only (Step 5.1 LIVE).
# The whole router is read-gated; mutation additionally requires a HUMAN Brisen admin
# principal (server-set here; AI / external principals are rejected by
# policy.projection.admin — AC7/T7). revoke/refresh now run against the PERSISTED
# projection-admin store (no longer the in-memory seed), so the kill switch is durable
# across restart (AC1) and idempotent (AC8) via the deterministic opaque record id.
# --------------------------------------------------------------------------- #
@router.post("/api/admin/{action}", dependencies=[Depends(_write_auth)])
def post_admin_action(action: str, projection_item_id: str = Query(...),
                      reason: str = Query("")) -> Mapping:
    """approve / revoke / refresh on a projection item (by source evidence object id).

    Brisen human admin only. revoke persists a durable, audited REVOKED decision that
    removes the item from EVERY partner surface generically; refresh recomputes
    freshness from current evidence/policy and NEVER resurrects a revoked item (revoked
    is a hard stop — un-revoke is a separate out-of-scope action). On store outage the
    action is reported as NOT applied (503) — never silently dropped."""
    if action not in ("approve", "revoke", "refresh"):
        raise HTTPException(status_code=400, detail="unknown action")
    admin = Principal(org=Org.BRISEN, role="evidence_admin")
    target = next((c for c in _candidates() if c.item.object_id == projection_item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")

    if action == "approve":
        if target.revoked:
            # Revoke is a hard stop — approve must not silently un-hide a revoked item.
            raise HTTPException(
                status_code=409,
                detail="revoked is a hard stop; a separate Brisen-human un-revoke is "
                       "required (out of scope for Step 5.1)",
            )
        try:
            log = projection_admin.approve_projection(
                target.item, admin, rationale=reason or "approved via cockpit")
        except Exception as e:
            raise HTTPException(status_code=403, detail=f"admin action denied: {e}")
        return {"ok": True, "action": action,
                "event": getattr(log, "event_type", action),
                "projection_state": ProjectionState.PROJECTED_SHARED_VIEW.value}

    # --- revoke / refresh: build the matter-level (brisen_internal) admin record,
    # mutate it through policy.projection.admin, then persist row + audit. The
    # persisted overlay is then authoritative for every external surface. ---
    pi = build_projection_item(
        AudienceRole.BRISEN_INTERNAL, target.item,
        route_target=target.route_target,
        revoked=target.revoked, revoked_by=target.revoked_by,
        revoke_reason=target.revoke_reason, stale=target.stale,
        action_safe_text=target.action_safe_text,
    )
    if pi is None:  # internal READ denied this Brisen object -> cannot administer it
        raise HTTPException(status_code=404, detail="not found")
    prev_state = pi.projection_state.value

    try:
        if action == "revoke":
            log = projection_admin.revoke_projection(
                pi, admin,
                reason=f"{reason or 'revoked via cockpit'} "
                       f"(transition: {prev_state}->{ProjectionState.REVOKED.value})",
            )
        else:  # refresh — recompute; revoked stays REVOKED (refresh_projection only
               # marks stale, it never clears REVOKED, so a revoked item is preserved).
            log = projection_admin.refresh_projection(pi, admin, stale=target.stale)
        admin_store.record_admin_action(pi, log)
    except projection_admin.ProjectionAdminDenied as e:
        raise HTTPException(status_code=403, detail=f"admin action denied: {e}")
    except ProjectionStoreUnavailableError:
        raise HTTPException(
            status_code=503,
            detail=f"projection store unavailable; {action} NOT applied",
        )
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"admin action denied: {e}")

    return {"ok": True, "action": action,
            "projection_state": pi.projection_state.value,
            "event": getattr(log, "event_type", action),
            "revoked": pi.projection_state is ProjectionState.REVOKED}


# --------------------------------------------------------------------------- #
# Cockpit SPA (Pattern B — serious operational light mode). The page is a thin
# shell: ALL data is fetched from the /api endpoints above, which apply the policy
# boundary server-side. The browser never reconstructs an external view. Dynamic
# content is rendered via DOM API + textContent (never innerHTML) so values from
# the backend cannot be interpreted as markup (defense-in-depth, no XSS surface).
#
# The PAGE route itself is served by dashboard.py (where the AI-Hotel auth helpers
# live): an authenticated session/key gets _COCKPIT_HTML; an unauthenticated browser
# gets _COCKPIT_LOGIN_HTML (the PIN challenge, reusing /api/ai-hotel/pin-auth — A.1,
# lead #3878). The /api/* routes in THIS router stay hard-gated (401) by
# verify_ai_hotel_read_access. cockpit_page() is a convenience the page route calls.
# --------------------------------------------------------------------------- #
def cockpit_page() -> HTMLResponse:
    return HTMLResponse(_COCKPIT_HTML)


def cockpit_login_page(status_code: int = 401) -> HTMLResponse:
    return HTMLResponse(_COCKPIT_LOGIN_HTML, status_code=status_code)


_COCKPIT_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Hotel Lab — Cockpit</title>
<style>
  :root{
    --canvas:#F7F6F2; --sidebar:#EFEEE8; --panel:#FFFFFF; --panel-hover:#FAF9F5;
    --ink:#171717; --text-2:#54524C; --muted:#767168; --faint:#9B958B;
    --line:#DDD8CE; --line-2:#ECE8DE; --accent:#1D1D1D; --blue:#0969DA;
    --blue-soft:#E8F1FE; --amber:#B7791F; --amber-soft:#F8E9CA;
    --green:#4C8F2F; --green-soft:#E7F1E4; --red:#A4423F; --red-soft:#F4E5E3;
    --shadow:0 18px 42px rgba(30,24,12,.08),0 1px 0 rgba(255,255,255,.9) inset;
    --shadow-sm:0 10px 24px rgba(30,24,12,.06),0 1px 0 rgba(255,255,255,.9) inset;
  }
  *{box-sizing:border-box}
  html{background:var(--canvas)}
  body{
    margin:0;font:14px/1.48 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    color:var(--ink);background:var(--canvas);font-variant-numeric:tabular-nums;letter-spacing:0;
  }
  button,input{font:inherit;letter-spacing:0}
  button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid rgba(9,105,218,.22);outline-offset:2px}
  header{
    background:#fffdf9;border-bottom:1px solid var(--line);padding:22px 26px 18px;
  }
  .hero{display:grid;grid-template-columns:minmax(360px,1.45fr) minmax(280px,.75fr);gap:16px;max-width:1480px;margin:0 auto}
  .hero-main,.partner-gate,.searchbar,.stat,.panel,.item{background:var(--panel);border:1px solid var(--line);box-shadow:var(--shadow-sm)}
  .hero-main{border-radius:8px;padding:22px 24px}
  .eyebrow,.stat .k,nav .seclabel{color:var(--blue);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0}
  h1{font-size:30px;line-height:1.12;margin:4px 0 8px;font-weight:650;letter-spacing:0}
  .hero-copy{max-width:760px;color:var(--text-2);font-size:15px;margin:0}
  .milestone{
    display:inline-flex;align-items:center;gap:7px;margin-top:16px;font-size:12px;color:var(--text-2);
    border:1px solid var(--line);border-radius:999px;padding:5px 10px;background:var(--panel-hover);
  }
  .milestone:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft)}
  .partner-gate{border-radius:8px;padding:18px 20px}
  .partner-gate .label{font-size:12px;color:var(--muted);font-weight:600}
  .partner-gate .title{font-size:22px;line-height:1.14;font-weight:650;margin:6px 0;color:var(--ink)}
  .partner-gate p{margin:0;color:var(--text-2);font-size:13px}
  .roles{display:flex;gap:7px;flex-wrap:wrap;margin-top:18px}
  .roles button{
    min-height:36px;padding:7px 12px;border:1px solid var(--line);background:var(--panel);
    border-radius:999px;cursor:pointer;color:var(--ink);box-shadow:0 1px 0 rgba(255,255,255,.8) inset;
  }
  .roles button:hover{background:var(--panel-hover);border-color:#c9c1b4}
  .roles button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  .firstscreen{max-width:1480px;margin:14px auto 0;display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:10px}
  .stat{border-radius:8px;padding:12px 13px;min-height:82px}
  .stat .k{color:var(--muted);font-size:10px}
  .stat .v{font-size:14px;font-weight:650;line-height:1.28;margin-top:7px;color:var(--ink)}
  .searchbar{max-width:1480px;margin:14px auto 0;display:flex;gap:10px;border-radius:8px;padding:10px}
  .searchbar input{flex:1;min-width:0;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink)}
  .searchbar button{min-height:40px;padding:9px 16px;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:7px;cursor:pointer;font-weight:650}
  .searchbar button:hover{background:#000}
  .layout{display:flex;min-height:60vh;max-width:1480px;margin:0 auto}
  nav{width:250px;flex:0 0 250px;border-right:1px solid var(--line);padding:18px 12px;background:var(--sidebar)}
  nav a{display:block;padding:9px 12px;color:var(--ink);text-decoration:none;font-size:14px;cursor:pointer;border-radius:7px;border:1px solid transparent;margin:2px 0}
  nav a:hover{background:rgba(255,255,255,.55);border-color:var(--line)}
  nav a.active{font-weight:650;background:var(--panel);border-color:var(--line);box-shadow:var(--shadow-sm)}
  nav .seclabel{color:var(--muted);padding:16px 12px 6px}
  main{flex:1;padding:24px;min-width:0}
  .panel{border-radius:8px;padding:18px;margin-bottom:18px}
  .panel h2{font-size:13px;margin:0 0 13px;text-transform:uppercase;letter-spacing:0;color:var(--blue)}
  .item{border-radius:8px;padding:14px 15px;margin-bottom:10px}
  .item:hover{background:var(--panel-hover);border-color:#cfc6b9}
  .item .claim{font-weight:650;font-size:15px;line-height:1.35;color:var(--ink)}
  .item .meta{font-size:12px;color:var(--muted);margin-top:7px}
  .badge{display:inline-flex;align-items:center;min-height:21px;font-size:10px;text-transform:uppercase;letter-spacing:0;padding:2px 7px;border-radius:999px;margin-right:6px;font-weight:750}
  .b-raw{background:var(--amber-soft);color:var(--amber);border:1px solid rgba(183,121,31,.34)}
  .b-verified{background:var(--green-soft);color:var(--green);border:1px solid rgba(76,143,47,.3)}
  .b-gap{background:var(--red-soft);color:var(--red);border:1px solid rgba(164,66,63,.28)}
  .b-state{background:var(--blue-soft);color:var(--blue);border:1px solid rgba(9,105,218,.2)}
  .raw-card{border-left:4px solid var(--amber);background:#fffaf0}
  .verified-card{border-left:4px solid var(--green)}
  .btn{min-height:34px;padding:6px 11px;border:1px solid var(--line);background:var(--panel);border-radius:7px;cursor:pointer;margin:10px 6px 0 0;font-weight:600}
  .btn:hover{background:var(--panel-hover);border-color:#c9c1b4}
  .btn.live{border-color:rgba(76,143,47,.38);color:var(--green);background:var(--green-soft)}
  .btn[disabled]{opacity:.5;cursor:not-allowed}
  .reason{font-size:12px;color:var(--text-2);margin-top:10px;max-width:760px}
  .empty{color:var(--muted);font-size:13px;padding:10px 0}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0}
  .notice{background:var(--blue-soft);border:1px solid rgba(9,105,218,.18);border-radius:8px;padding:11px 13px;font-size:13px;color:#174B8B;margin-bottom:14px}
  pre{white-space:pre-wrap;font-size:12px;background:#fbfaf7;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto}
  @media(max-width:1040px){
    header{padding:18px 18px 14px}.hero{grid-template-columns:1fr}.firstscreen{grid-template-columns:repeat(3,minmax(140px,1fr))}
    .layout{display:block}nav{width:auto;display:flex;gap:6px;overflow-x:auto;border-right:none;border-bottom:1px solid var(--line);padding:12px}
    nav .seclabel{display:none}nav a{white-space:nowrap}main{padding:18px}
  }
  @media(max-width:680px){
    h1{font-size:26px}.hero-main,.partner-gate{padding:17px}.firstscreen{grid-template-columns:1fr 1fr}
    .searchbar{display:block}.searchbar button{width:100%;margin-top:8px}
  }
  @media(max-width:420px){.firstscreen{grid-template-columns:1fr}.roles button{width:100%;justify-content:center}}
</style></head>
<body>
<header>
  <section class="hero" aria-label="AI Hotel Lab status">
    <div class="hero-main">
      <div class="eyebrow">NVIDIA × Mandarin Oriental × Brisen</div>
      <h1>AI Hotel Lab</h1>
      <p class="hero-copy">Governed project room for the AI-hospitality lighthouse: partner-safe evidence, role-specific packets, source coverage, and Brisen-controlled activation.</p>
      <span class="milestone">Partner-live capable · activation held</span>
      <div class="roles" id="roles">
        <button data-role="brisen" class="active">Brisen (internal)</button>
        <button data-role="nvidia">View as NVIDIA</button>
        <button data-role="mohg">View as MOHG</button>
        <button data-role="venue">View as Venue Owner</button>
      </div>
    </div>
    <div class="partner-gate">
      <div class="label">Control state</div>
      <div class="title">Safe to demonstrate. Not opened externally.</div>
      <p>Technical gates are clear. Real partner access remains held until the first audience, access mode, and visible scope are ratified.</p>
    </div>
  </section>
  <div class="firstscreen" id="firstscreen"></div>
  <div class="searchbar">
    <input id="q" placeholder="Search governed evidence, source coverage, and partner-safe packet state"/>
    <button id="searchbtn">Search</button>
  </div>
</header>
<div class="layout">
  <nav id="nav">
    <div class="seclabel">Surfaces</div>
    <a data-view="overview" class="active">Overview</a>
    <a data-view="raw">Raw Signal Inbox</a>
    <a data-view="evidence">Verified Evidence</a>
    <a data-view="projection">Partner Projection</a>
    <a data-view="sources">Source Registry / Coverage</a>
    <a data-view="search">Advanced Search</a>
    <div class="seclabel">Execution</div>
    <a data-view="roadmap">Execution Roadmap</a>
  </nav>
  <main id="main"></main>
</div>
<script>
const KEY = new URLSearchParams(location.search).get('key');
let ROLE='brisen', VIEW='overview';
const isExternal=()=>ROLE!=='brisen';
// Safe DOM builder — values go in via textContent only; no innerHTML, no XSS surface.
function h(tag, attrs, kids){
  const e=document.createElement(tag);
  attrs=attrs||{};
  for(const k in attrs){
    if(k==='class') e.className=attrs[k];
    else if(k==='text') e.textContent=attrs[k];
    else if(k==='onclick') e.onclick=attrs[k];
    else if(k==='disabled'){ if(attrs[k]) e.setAttribute('disabled',''); }
    else if(attrs[k]!=null) e.setAttribute(k,attrs[k]);
  }
  (kids||[]).forEach(c=>{ if(c==null)return; e.appendChild(typeof c==='object'?c:document.createTextNode(String(c))); });
  return e;
}
function clear(n){ while(n.firstChild) n.removeChild(n.firstChild); }
function badge(cls,txt){ return h('span',{class:'badge '+cls,text:txt}); }
async function api(path){
  const hd={}; if(KEY) hd['X-Baker-Key']=KEY;
  const r=await fetch('/ai-hotel-lab/api/'+path+(path.includes('?')?'&':'?')+'role='+ROLE,{credentials:'same-origin',headers:hd});
  if(!r.ok) return null; return r.json();
}
function setRole(role){
  ROLE=role;
  document.querySelectorAll('#roles button').forEach(b=>b.classList.toggle('active',b.dataset.role===role));
  clear(document.getElementById('main')); clear(document.getElementById('firstscreen')); // AC3: clear prior-role state
  render();
}
function setView(v){ VIEW=v; document.querySelectorAll('#nav a').forEach(a=>a.classList.toggle('active',a.dataset.view===v)); render(); }
document.querySelectorAll('#roles button').forEach(b=>b.onclick=()=>setRole(b.dataset.role));
document.querySelectorAll('#nav a').forEach(a=>a.onclick=()=>setView(a.dataset.view));
document.getElementById('searchbtn').onclick=runSearch;

function stat(k,v){ return h('div',{class:'stat'},[h('div',{class:'k',text:k}),h('div',{class:'v',text:String(v)})]); }
async function renderFirstScreen(){
  const fs=document.getElementById('firstscreen'); clear(fs);
  const pkt=await api('packet'); if(!pkt){ fs.appendChild(stat('status','unavailable')); return; }
  const c=pkt.counts||{};
  [['Thesis','AI-hospitality lighthouse governed by partner-safe evidence'],
   ['Status','Sprint-0 live · gates cleared'],
   ['Next action','Controlled demo before external access'],
   ['Evidence freshness',pkt.last_generated_at?pkt.last_generated_at.slice(0,10):'—'],
   ['External sharing',isExternal()?'View-as preview · not partner-live':'Brisen control'],
   ['Visible packet',(c.visible||0)+' items · '+(c.action_linked||0)+' action-linked']
  ].forEach(s=>fs.appendChild(stat(s[0],s[1])));
}
function sectionItems(pkt){ const out=[]; for(const sec in (pkt.sections||{})){ const v=pkt.sections[sec]; if(Array.isArray(v)) v.forEach(i=>out.push({sec,i})); } return out; }
function panel(title, extra){ const p=h('div',{class:'panel'},[h('h2',{text:title})]); if(extra)p.appendChild(extra); return p; }
function notice(txt){ return h('div',{class:'notice',text:txt}); }

async function viewOverview(){
  const wrap=h('div'); const pkt=await api('packet'); if(!pkt){wrap.appendChild(h('div',{class:'empty',text:'No packet.'}));return wrap;}
  wrap.appendChild(notice(isExternal()
    ? 'Partner preview uses the exact server-built packet. No raw internal data reaches this view. Revoke is a durable, audited kill switch: a revoked item disappears from this view immediately.'
    : 'Brisen control view. Amber material is internal-only; verified evidence is promoted; partner packets are governed server-side.'));
  const p=panel('Evidence by section'); const items=sectionItems(pkt);
  if(!items.length) p.appendChild(h('div',{class:'empty',text:'No items available.'}));
  items.forEach(({sec,i})=>{
    const meta=h('div',{class:'meta'},[
      badge('b-state', i.dashboard_section||sec),
      badge('b-verified', i.evidence_status||i.projection_state||'verified'),
      ' confidence '+(i.evidence_confidence!=null?i.evidence_confidence:(i.confidence!=null?i.confidence:'—'))+' · '+(i.freshness||''),
      i.action_safe_text?' · action: '+i.action_safe_text:''
    ]);
    p.appendChild(h('div',{class:'item verified-card'},[h('div',{class:'claim',text:i.display_title||i.claim||i.display_summary||'—'}),meta]));
  });
  wrap.appendChild(p); return wrap;
}
async function viewRaw(){
  if(isExternal()) return panel('Raw Signal Inbox', h('div',{class:'empty',text:'Raw signals are internal-only and are not part of a partner view.'}));
  const d=await api('raw-signals'); const sig=(d&&d.raw_signals)||[];
  const p=panel('Raw Signal Inbox'); p.querySelector('h2').appendChild(badge('b-raw','internal only'));
  if(!sig.length) p.appendChild(h('div',{class:'empty',text:'No raw signals.'}));
  sig.forEach(s=>p.appendChild(h('div',{class:'item raw-card'},[
    h('div',{class:'claim',text:s.claim||s.title||'—'}),
    h('div',{class:'meta'},[badge('b-raw','raw · amber'),(s.section||'')+' · '+(s.source_type||'')+' · '+(s.freshness||'')]),
    h('div',{class:'meta',text:s.raw_body||''})
  ])));
  return p;
}
async function viewEvidence(){
  const d=await api('evidence'); const ev=(d&&d.evidence)||[]; const p=panel('Verified Evidence');
  if(!ev.length) p.appendChild(h('div',{class:'empty',text:'No verified evidence available.'}));
  ev.forEach(e=>p.appendChild(h('div',{class:'item verified-card'},[
    h('div',{class:'claim',text:e.display_title||e.claim||e.display_summary||'—'}),
    h('div',{class:'meta'},[badge('b-verified',e.lifecycle_state||e.evidence_status||'verified'),
      ' confidence '+(e.confidence!=null?e.confidence:(e.evidence_confidence!=null?e.evidence_confidence:'—'))+' · '+(e.last_verified_at||e.last_reviewed||'')])
  ])));
  return p;
}
async function viewProjection(){
  const wrap=h('div'); const pkt=await api('packet'); const items=pkt?sectionItems(pkt):[];
  const p=panel('Partner Projection');
  if(isExternal()) p.appendChild(notice('Brisen controls projection. Partners view; they do not approve or revoke.'));
  if(!items.length) p.appendChild(h('div',{class:'empty',text:'No projected items.'}));
  items.forEach(({i})=>{
    const card=h('div',{class:'item'},[
      h('div',{class:'claim',text:i.display_title||i.claim||'—'}),
      h('div',{class:'meta'},[badge('b-state',i.projection_state||'projected'),i.dashboard_section||''])
    ]);
    if(!isExternal()){
      const id=i.source_evidence_item_id||i.object_id||'';
      const ctl=h('div',{},[
        h('button',{class:'btn live',text:'Approve',onclick:()=>adminAct('approve',id)}),
        h('button',{class:'btn live',text:'Revoke',onclick:()=>adminAct('revoke',id)}),
        h('button',{class:'btn live',text:'Refresh',onclick:()=>adminAct('refresh',id)}),
        h('button',{class:'btn',text:'Audit',onclick:()=>showAudit(id)}),
        h('div',{class:'reason',text:'Brisen controls projection. Revoke is a durable, audited kill switch (item leaves every partner view); Refresh recomputes freshness. The server is the source of final state.'})
      ]);
      card.appendChild(ctl);
    }
    p.appendChild(card);
  });
  wrap.appendChild(p); wrap.appendChild(h('div',{id:'auditdrawer'})); return wrap;
}
async function viewSources(){
  const d=await api('sources'); const s=(d&&d.sources)||[];
  const tbl=h('table',{},[h('tr',{},[h('th',{text:'Domain'}),h('th',{text:'Source'}),h('th',{text:'Status'})])]);
  s.forEach(r=>{ const st=r.collection_status||r.availability||'';
    const cls=(st==='gap'||st==='not_available')?'b-gap':'b-verified';
    const stcell=h('td',{},[badge(cls,st)]); if(r.never_external) stcell.appendChild(badge('b-state','never-external'));
    tbl.appendChild(h('tr',{},[h('td',{text:r.domain}),h('td',{text:r.label}),stcell])); });
  return panel('Source Registry / Coverage', tbl);
}
async function viewRoadmap(){
  const d=await api('roadmap'); const r=(d&&d.roadmap)||[]; const p=panel('Execution Roadmap');
  if(!r.length) p.appendChild(h('div',{class:'empty',text:'No roadmap items in this view.'}));
  r.forEach(x=>p.appendChild(h('div',{class:'item'},[
    h('div',{class:'claim'},[badge('b-gap','gap'),(x.label||'')+' ('+(x.domain||'')+')']),
    h('div',{class:'meta',text:'owner '+(x.owner||'—')+' · '+(x.reason||'')}),
    h('div',{class:'meta',text:'next: '+(x.next_action||'')})
  ])));
  return p;
}
async function viewSearch(){
  const wrap=h('div'); wrap.appendChild(panel('Advanced Search', h('div',{class:'empty',text:'Use the search bar above. Results and honest source coverage (live vs gap) appear here.'})));
  wrap.appendChild(h('div',{id:'searchresults'})); return wrap;
}
async function runSearch(){
  const q=document.getElementById('q').value.trim(); if(!q) return; setView('search');
  const d=await api('search?q='+encodeURIComponent(q)); const box=document.getElementById('searchresults'); if(!box) return; clear(box); if(!d) return;
  const cov=h('table',{},[h('tr',{},[h('th',{text:'Domain'}),h('th',{text:'Status'})])]);
  (d.coverage||[]).forEach(c=>{ const cls=c.status==='gap'?'b-gap':'b-verified';
    cov.appendChild(h('tr',{},[h('td',{text:c.label||c.domain}),h('td',{},[badge(cls,c.status)])])); });
  box.appendChild(panel('Coverage (honest)',cov));
  const rp=panel('Results ('+d.result_count+')');
  if(!d.results.length) rp.appendChild(h('div',{class:'empty',text:'No results'+(d.zero_result_route?' — routed to '+d.zero_result_route:'')+'. Unwired connectors are shown as gaps above, never fabricated as results.'}));
  (d.results||[]).forEach(r=>rp.appendChild(h('div',{class:'item'},[
    h('div',{class:'claim',text:r.result_ref}),
    h('div',{class:'meta'},[badge(r.projected?'b-state':'b-verified',r.projected?'partner projection':'internal'),r.route_target||''])
  ])));
  box.appendChild(rp);
}
async function adminAct(action,id){
  const hd={'Content-Type':'application/json'}; if(KEY) hd['X-Baker-Key']=KEY;
  const r=await fetch('/ai-hotel-lab/api/admin/'+action+'?projection_item_id='+encodeURIComponent(id)+'&role='+ROLE,{method:'POST',credentials:'same-origin',headers:hd});
  alert(action+': '+(r.ok?'done':('blocked ('+r.status+')'))); if(r.ok) render();
}
async function showAudit(id){
  const d=await api('item/'+encodeURIComponent(id)+'/audit'); const box=document.getElementById('auditdrawer'); if(!box)return; clear(box);
  box.appendChild(d? panel('Audit · '+id, h('pre',{text:JSON.stringify(d,null,2)}))
                   : panel('Audit', h('div',{class:'empty',text:'Not available in this view.'})));
}
async function render(){
  await renderFirstScreen();
  const m=document.getElementById('main'); clear(m); m.appendChild(h('div',{class:'empty',text:'Loading…'}));
  const fn={overview:viewOverview,raw:viewRaw,evidence:viewEvidence,projection:viewProjection,sources:viewSources,roadmap:viewRoadmap,search:viewSearch}[VIEW]||viewOverview;
  const node=await fn(); clear(m); m.appendChild(node);
}
render();
</script>
</body></html>
"""


# PIN challenge served to an unauthenticated browser (A.1, lead #3878). Reuses the
# existing /api/ai-hotel/pin-auth endpoint; on success the (now path-widened)
# aih_session cookie is set and the page reloads into the cockpit. No cockpit data
# is present on this page — it is a pure auth gate. textContent only (no innerHTML).
_COCKPIT_LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Hotel Lab — Access</title>
<style>
  body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
       background:#f7f6f2;color:#1c2530;display:flex;min-height:100vh;align-items:center;justify-content:center}
  .box{background:#fffefb;border:1px solid #dcd9d0;border-radius:6px;padding:28px;width:320px}
  h1{font-size:17px;margin:0 0 4px} p{color:#5d6b7a;font-size:13px;margin:0 0 16px}
  input{width:100%;font:inherit;padding:10px;border:1px solid #dcd9d0;border-radius:4px;margin-bottom:10px}
  button{width:100%;font:inherit;padding:10px;border:1px solid #1a3a52;background:#1a3a52;color:#fff;border-radius:4px;cursor:pointer}
  .msg{font-size:12px;color:#9a3b3b;margin-top:10px;min-height:16px}
</style></head>
<body>
<div class="box">
  <h1>AI Hotel Lab</h1>
  <p>Internal cockpit — enter access code.</p>
  <input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="Access code" autofocus/>
  <button id="go">Enter</button>
  <div class="msg" id="msg"></div>
</div>
<script>
async function submit(){
  const pin=document.getElementById('pin').value.trim();
  const msg=document.getElementById('msg'); msg.textContent='';
  try{
    const r=await fetch('/api/ai-hotel/pin-auth',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});
    if(r.ok){ location.reload(); } else { msg.textContent = r.status===401?'Incorrect code.':'Access unavailable.'; }
  }catch(e){ msg.textContent='Network error.'; }
}
document.getElementById('go').onclick=submit;
document.getElementById('pin').addEventListener('keydown',e=>{ if(e.key==='Enter') submit(); });
</script>
</body></html>
"""
