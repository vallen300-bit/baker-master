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
    if internal:
        principal, mode = _OPERATOR, SearchMode.INTERNAL_GLOBAL
    else:
        principal, mode = _external_principal(audience), SearchMode.PARTNER_SAFE
    try:
        rs = policy_search(principal, q, mode, candidates=_seed_sources())
        results = [_serialize_result(r, internal=internal) for r in rs.results]
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
        # revoke / refresh operate on PERSISTED ProjectionItems (Step 5.1, a separate
        # follow-on after merge — codex-arch #3873). Sprint-0 has no persisted store,
        # so the UI renders these controls DISABLED/read-only with this exact reason
        # string; the endpoint returns it explicitly rather than a bare 501.
        raise HTTPException(
            status_code=501,
            detail="Step 5.1 pending persisted projection-admin store",
        )
    try:
        log = projection_admin.approve_projection(
            target.item, admin, rationale=reason or "approved via cockpit")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"admin action denied: {e}")
    return {"ok": True, "action": action, "event": getattr(log, "event_type", action)}


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
    --paper:#f7f6f2; --ink:#1c2530; --muted:#5d6b7a; --line:#dcd9d0; --card:#fffefb;
    --navy:#1a3a52; --navy-soft:#e7edf2; --amber:#b3760a; --amber-bg:#fdf3e0;
    --verified:#1f6b46; --verified-bg:#e8f3ec; --gap:#9a3b3b; --gap-bg:#f7eaea;
  }
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper)}
  header{background:var(--card);border-bottom:1px solid var(--line);padding:14px 20px;position:sticky;top:0;z-index:10}
  .titlerow{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  h1{font-size:18px;margin:0;letter-spacing:.3px}
  .milestone{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:3px;padding:2px 7px;text-transform:uppercase;letter-spacing:.5px}
  .roles{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
  .roles button{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--line);background:var(--paper);border-radius:4px;cursor:pointer;color:var(--ink)}
  .roles button.active{background:var(--navy);color:#fff;border-color:var(--navy)}
  .firstscreen{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
  .stat{background:var(--paper);border:1px solid var(--line);border-radius:4px;padding:8px 10px}
  .stat .k{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}
  .stat .v{font-size:14px;font-weight:600;margin-top:2px}
  .searchbar{display:flex;gap:8px;margin-top:12px}
  .searchbar input{flex:1;font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:4px;background:#fff}
  .searchbar button{font:inherit;padding:8px 14px;border:1px solid var(--navy);background:var(--navy);color:#fff;border-radius:4px;cursor:pointer}
  .layout{display:flex;min-height:60vh}
  nav{width:230px;flex:0 0 230px;border-right:1px solid var(--line);padding:16px 0;background:var(--card)}
  nav a{display:block;padding:8px 20px;color:var(--ink);text-decoration:none;font-size:14px;cursor:pointer;border-left:3px solid transparent}
  nav a:hover{background:var(--navy-soft)} nav a.active{border-left-color:var(--navy);font-weight:600;background:var(--navy-soft)}
  nav .seclabel{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);padding:14px 20px 4px}
  main{flex:1;padding:20px;min-width:0}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:16px;margin-bottom:18px}
  .panel h2{font-size:14px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.5px;color:var(--navy)}
  .item{border:1px solid var(--line);border-radius:4px;padding:10px 12px;margin-bottom:8px;background:#fff}
  .item .claim{font-weight:600} .item .meta{font-size:12px;color:var(--muted);margin-top:4px}
  .badge{display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:2px 7px;border-radius:3px;margin-right:6px;font-weight:700}
  .b-raw{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber)}
  .b-verified{background:var(--verified-bg);color:var(--verified);border:1px solid var(--verified)}
  .b-gap{background:var(--gap-bg);color:var(--gap);border:1px solid var(--gap)}
  .b-state{background:var(--navy-soft);color:var(--navy);border:1px solid #b9c8d4}
  .raw-card{border-left:4px solid var(--amber);background:var(--amber-bg)}
  .verified-card{border-left:4px solid var(--verified)}
  .btn{font:inherit;font-size:12px;padding:5px 10px;border:1px solid var(--line);background:var(--paper);border-radius:4px;cursor:pointer;margin-right:6px}
  .btn.live{border-color:var(--verified);color:var(--verified)}
  .btn[disabled]{opacity:.5;cursor:not-allowed}
  .reason{font-size:11px;color:var(--muted);font-style:italic;margin-top:4px}
  .empty{color:var(--muted);font-size:13px;padding:8px 0}
  table{width:100%;border-collapse:collapse;font-size:13px} th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  .notice{background:var(--navy-soft);border:1px solid #b9c8d4;border-radius:4px;padding:8px 12px;font-size:12px;color:var(--navy);margin-bottom:14px}
  pre{white-space:pre-wrap;font-size:12px}
  @media(max-width:760px){.layout{flex-direction:column}nav{width:auto;flex:none;border-right:none;border-bottom:1px solid var(--line);display:flex;overflow-x:auto}nav .seclabel{display:none}nav a{white-space:nowrap;border-left:none;border-bottom:3px solid transparent}}
</style></head>
<body>
<header>
  <div class="titlerow">
    <h1>AI Hotel Lab</h1>
    <span class="milestone">Internal cockpit · view-as milestone</span>
    <div class="roles" id="roles">
      <button data-role="brisen" class="active">Brisen (internal)</button>
      <button data-role="nvidia">View as NVIDIA</button>
      <button data-role="mohg">View as MOHG</button>
      <button data-role="venue">View as Venue Owner</button>
    </div>
  </div>
  <div class="firstscreen" id="firstscreen"></div>
  <div class="searchbar">
    <input id="q" placeholder="Advanced search — internal Baker/vault/field; web & authorities shown as gaps until wired"/>
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
  [['Stage','Sprint-0 · Step 5 (cockpit)'],['Viewing as',pkt.audience_label],
   ['Visible evidence',(c.visible||0)+' items'],['Action-linked',(c.action_linked||0)],
   ['Evidence freshness',pkt.last_generated_at?pkt.last_generated_at.slice(0,10):'—'],
   ['External sharing',isExternal()?'view-as preview (not partner-live)':'Brisen control']
  ].forEach(s=>fs.appendChild(stat(s[0],s[1])));
}
function sectionItems(pkt){ const out=[]; for(const sec in (pkt.sections||{})){ const v=pkt.sections[sec]; if(Array.isArray(v)) v.forEach(i=>out.push({sec,i})); } return out; }
function panel(title, extra){ const p=h('div',{class:'panel'},[h('h2',{text:title})]); if(extra)p.appendChild(extra); return p; }
function notice(txt){ return h('div',{class:'notice',text:txt}); }

async function viewOverview(){
  const wrap=h('div'); const pkt=await api('packet'); if(!pkt){wrap.appendChild(h('div',{class:'empty',text:'No packet.'}));return wrap;}
  wrap.appendChild(notice(isExternal()
    ? 'Partner view-as preview. This is the exact server-built partner packet — no raw internal data reaches this view. Partner-live access opens after revoke is wired (Step 5.1).'
    : 'Brisen internal command view. Raw signals are amber and internal-only; verified evidence is promoted; partner projections are governed server-side.'));
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
        h('button',{class:'btn',text:'Revoke',disabled:true,title:'Step 5.1 pending persisted projection-admin store'}),
        h('button',{class:'btn',text:'Refresh',disabled:true,title:'Step 5.1 pending persisted projection-admin store'}),
        h('button',{class:'btn',text:'Audit',onclick:()=>showAudit(id)}),
        h('div',{class:'reason',text:'Revoke / Refresh: Step 5.1 pending persisted projection-admin store.'})
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
