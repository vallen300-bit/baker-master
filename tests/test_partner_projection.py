"""codex-arch AC1-7 + 10 threat cases + deputy-codex #3738 AC/T gate for the AI Hotel
Lab partner-safe projection surface (Step 4).

Test names map 1:1 to the brief done rubric so the ship report can cite a test per AC /
threat / rubric item. Every test runs with NO database: store fail-closed paths use a
raising conn factory; the live-policy integration is exercised via spies on
``policy.engine.partner_projection`` / ``policy.engine.evaluate``.

Load-bearing invariant: **no external audience can see another audience's items or any
raw internal field; projection exists only through the Step-1 engine + the
human-approved lifecycle; revoke/stale are honored.**
"""

from __future__ import annotations

import pytest

from policy import engine, lifecycle
from policy.models import (
    Classification,
    EvidenceItem,
    LifecycleState,
    ObjectType,
    Org,
    Principal,
    Sensitivity,
)
from policy.projection import admin, packets, projector, store
from policy.projection.models import (
    EXTERNAL_ITEM_ALLOWLIST,
    FORBIDDEN_EXTERNAL_SUBSTRINGS,
    AudienceRole,
    ProjectionState,
)
from policy.projection.packets import ProjectionCandidate, SpoofDenied
from policy.search.routing import RouteTarget

# --- the 6 principals (deputy-codex fixture requirement) ---
BR_INTERNAL = Principal(Org.BRISEN, "internal_team")
BR_ADMIN = Principal(Org.BRISEN, "evidence_admin")
BR_AI = Principal(Org.BRISEN, "internal_team", is_ai=True)
NVIDIA = Principal(Org.NVIDIA, "ai_hospitality_lighthouse_lead")
MOHG = Principal(Org.MOHG, "ops_standards_lead")
VENUE = Principal(Org.VENUE_OWNER, "site_diligence_lead")
SPOOF = Principal(Org.NVIDIA, "ai_hospitality_lighthouse_lead")  # tampers to claim others
EXTERNALS = [NVIDIA, MOHG, VENUE]


def _ev(object_id, classification, orgs, *, lifecycle_state=LifecycleState.SHARED_VIEW,
        sensitivity=None, confidence=0.9, claim="verified claim", action=False):
    return EvidenceItem(
        object_id=object_id,
        object_type=ObjectType.ACTION if action else ObjectType.CLAIM,
        classification=classification,
        lifecycle_state=lifecycle_state,
        owner_org=Org.BRISEN,
        owner="brisen-evidence-team",
        sensitivity=sensitivity,
        allowed_orgs=frozenset(orgs),
        confidence=confidence,
        source_refs=("vault:secret/path.md", "gmail:thread:abc"),
        source_type="curated_partner_brief",
        claim=claim,
        freshness="2026-06-22",
        last_reviewed="2026-06-22",
        raw_body="SECRET RAW BODY",
        title="SECRET INTERNAL TITLE",
    )


def _nv_item(**kw):
    return _ev("po-nvidia-1", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA], **kw)


def _mo_item(**kw):
    return _ev("po-mohg-1", Classification.PARTNER_SAFE_MOHG, [Org.MOHG], **kw)


def _venue_item(**kw):
    return _ev("po-venue-1", Classification.PARTNER_SAFE_VENUE_OWNER, [Org.VENUE_OWNER], **kw)


def _mixed_candidates():
    """One item per external audience + never_external + verified-candidate."""
    return [
        ProjectionCandidate(_nv_item(), RouteTarget.NVIDIA_LIGHTHOUSE),
        ProjectionCandidate(_mo_item(), RouteTarget.MANDARIN_ORIENTAL_OPERATOR_LOGIC),
        ProjectionCandidate(_venue_item(), RouteTarget.SANTA_CLARA_SITE_THESIS),
        ProjectionCandidate(
            _ev("po-never-1", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
                sensitivity=Sensitivity.FINANCIAL),
            RouteTarget.BUSINESS_CASE_FINANCING),
        ProjectionCandidate(
            _ev("po-cand-1", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
                lifecycle_state=LifecycleState.VERIFIED_EVIDENCE),
            RouteTarget.NVIDIA_LIGHTHOUSE),
    ]


# =========================================================================== #
# codex-arch AC1 — role-specific partner-safe packets for nvidia/mohg/venue
# =========================================================================== #
def test_ac1_role_specific_packets():
    cands = _mixed_candidates()
    nv = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    mo = packets.build_external_packet(AudienceRole.MOHG_OPS_STANDARDS, cands, generated_at="T0")
    ve = packets.build_external_packet(AudienceRole.VENUE_OWNER_SITE_DILIGENCE, cands, generated_at="T0")
    assert nv.visible_count == 1 and mo.visible_count == 1 and ve.visible_count == 1


# =========================================================================== #
# AC2 / rubric2 — derived-only: every external display field from partner_projection
# =========================================================================== #
def test_rubric2_external_fields_from_partner_projection(monkeypatch):
    calls = {"n": 0}
    real = engine.partner_projection

    def spy(principal, item, **kw):
        calls["n"] += 1
        return real(principal, item, **kw)

    monkeypatch.setattr(engine, "partner_projection", spy)
    packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                  [ProjectionCandidate(_nv_item())], generated_at="T0")
    assert calls["n"] >= 1


def test_rubric2_removing_projection_yields_no_external_body(monkeypatch):
    monkeypatch.setattr(
        engine, "partner_projection",
        lambda *a, **k: (_ for _ in ()).throw(engine.ProjectionDenied("forced")),
    )
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                        [ProjectionCandidate(_nv_item())], generated_at="T0")
    assert pkt.visible_count == 0  # no engine body => nothing visible


def test_ac2_no_raw_text_leaks():
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                        _mixed_candidates(), generated_at="T0")
    blob = str(pkt.as_dict())
    assert "SECRET RAW BODY" not in blob and "SECRET INTERNAL TITLE" not in blob
    assert "vault:secret/path.md" not in blob and "gmail:thread:abc" not in blob


# =========================================================================== #
# AC3 — item includes confidence, visibility_reason, redaction, safe provenance
# =========================================================================== #
def test_ac2_missing_confidence_fails_closed():
    # deputy-codex AC2 / T4: a shared_view item granted to NVIDIA but missing
    # confidence metadata is denied by the engine -> blocked, no external body.
    cand = ProjectionCandidate(_nv_item(confidence=None))
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert pkt.visible_count == 0
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, cand.item)
    assert pi.projection_state is ProjectionState.BLOCKED_BY_POLICY


def test_ac3_item_has_confidence_visibility_provenance():
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                        [ProjectionCandidate(_nv_item())], generated_at="T0")
    item = next(i for sec in pkt.sections.values() if isinstance(sec, list) for i in sec)
    assert item["evidence_confidence"] == 0.9
    assert item["visibility_reason"]
    assert item["redaction_applied"] is True
    assert item["citation_or_provenance_safe"] == "2 source(s)"  # count, not refs


# =========================================================================== #
# AC4 / rubric4 — Brisen internal can preview each partner view (view-as)
# =========================================================================== #
def test_ac4_view_as_each_partner():
    cands = _mixed_candidates()
    for role in (AudienceRole.NVIDIA_LIGHTHOUSE, AudienceRole.MOHG_OPS_STANDARDS,
                 AudienceRole.VENUE_OWNER_SITE_DILIGENCE):
        pkt = packets.view_as(BR_ADMIN, role, cands, generated_at="T0")
        assert pkt.audience_role is role


def test_ac4_external_cannot_view_as():
    with pytest.raises(SpoofDenied):
        packets.view_as(NVIDIA, AudienceRole.MOHG_OPS_STANDARDS, _mixed_candidates())


# =========================================================================== #
# AC5 — evidence-admin approve / revoke / refresh, each audited; human-only
# =========================================================================== #
def test_ac5_admin_approve_via_lifecycle_gate():
    item = _ev("po-approve-1", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
               lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    rec = admin.approve_projection(item, BR_ADMIN, rationale="ready", confidence=0.9)
    assert rec.allow and item.lifecycle_state is LifecycleState.SHARED_VIEW


def test_ac5_admin_actions_reject_non_human_admin():
    item = _ev("po-approve-2", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
               lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    for bad in (BR_AI, NVIDIA, BR_INTERNAL):  # AI, external, non-admin internal
        with pytest.raises(admin.ProjectionAdminDenied):
            admin.approve_projection(item, bad, rationale="x", confidence=0.9)
    assert item.lifecycle_state is LifecycleState.VERIFIED_EVIDENCE  # unchanged


def test_ac5_revoke_audited_and_removes_from_external():
    cand = ProjectionCandidate(_nv_item())
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, cand.item)
    assert pi.is_externally_visible
    rec = admin.revoke_projection(pi, BR_ADMIN, reason="superseded")
    assert rec.allow and pi.projection_state is ProjectionState.REVOKED
    assert not pi.is_externally_visible  # gone from external view


# =========================================================================== #
# rubric3 — cross-role isolation (absent, not hidden) across packet/counts/audit
# =========================================================================== #
def test_rubric3_cross_role_isolation_packet_and_counts():
    cands = _mixed_candidates()
    nv = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    blob = str(nv.as_dict())
    assert "po-mohg-1" not in blob and "po-venue-1" not in blob  # absent, not hidden
    # NVIDIA counts reflect ONLY NVIDIA-intended items (1 visible + never + candidate)
    assert nv.visible_count == 1


def test_rubric3_cross_role_isolation_item_audit():
    cands = _mixed_candidates()
    # NVIDIA's own visible item id
    nv = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    nv_id = next(i["projection_item_id"] for sec in nv.sections.values()
                 if isinstance(sec, list) for i in sec)
    # MOHG's item id (computed for MOHG audience)
    mo_id = projector._opaque_item_id("po-mohg-1", AudienceRole.MOHG_OPS_STANDARDS)
    assert packets.external_item_audit(NVIDIA, nv_id, cands) is not None     # own item OK
    assert packets.external_item_audit(NVIDIA, mo_id, cands) is None         # other audience absent


# =========================================================================== #
# rubric4 — direct-API bypass: crafted role/item_id/source_id fails closed
# =========================================================================== #
def test_rubric4_direct_api_bypass_crafted_role():
    with pytest.raises(SpoofDenied):
        packets.serve_external_packet(NVIDIA, AudienceRole.MOHG_OPS_STANDARDS,
                                      _mixed_candidates(), generated_at="T0")


def test_rubric4_crafted_candidates_other_audience_absent():
    # Even if the candidate list contains MOHG/venue items, NVIDIA's packet excludes them.
    pkt = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                        _mixed_candidates(), generated_at="T0")
    blob = str(pkt.as_dict())
    assert "po-mohg-1" not in blob and "po-venue-1" not in blob


# =========================================================================== #
# rubric5 / T3 — no second engine: every external item via evaluate+partner_projection
# =========================================================================== #
def test_rubric5_external_routes_through_engine(monkeypatch):
    seen = {"proj": 0}
    real = engine.partner_projection

    def spy(p, i, **kw):
        seen["proj"] += 1
        return real(p, i, **kw)

    monkeypatch.setattr(engine, "partner_projection", spy)
    packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                  [ProjectionCandidate(_nv_item())], generated_at="T0")
    assert seen["proj"] >= 1


# =========================================================================== #
# rubric6 — raw_signal / research_artifact never project externally
# =========================================================================== #
@pytest.mark.parametrize("state", [LifecycleState.RAW_SIGNAL, LifecycleState.RESEARCH_ARTIFACT])
def test_rubric6_raw_and_research_never_project(state):
    cand = ProjectionCandidate(_nv_item(lifecycle_state=state))
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert pkt.visible_count == 0
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, cand.item)
    assert pi.projection_state is ProjectionState.NOT_PROJECTABLE


# =========================================================================== #
# rubric7 — never_external verified item -> blocked_by_policy, no payload
# =========================================================================== #
def test_rubric7_never_external_blocked():
    cand = ProjectionCandidate(
        _ev("po-ne", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
            sensitivity=Sensitivity.LEGAL))
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, cand.item)
    assert pi.projection_state is ProjectionState.BLOCKED_BY_POLICY
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert pkt.visible_count == 0
    assert "SECRET" not in str(pkt.as_dict())


# =========================================================================== #
# rubric8 — revoke gone from external (audit retained); stale -> stale_projection
# =========================================================================== #
def test_rubric8_revoke_and_stale():
    cand = ProjectionCandidate(_nv_item(), revoked=True)
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert pkt.visible_count == 0  # revoked gone from external view
    audits = []
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, _nv_item())
    admin.revoke_projection(pi, BR_ADMIN, reason="r", audit_recorder=audits.append)
    assert audits and audits[0].event_type == "revoke"  # audit retained
    # stale: removed from external view; F1 -> NO external stale count is exposed
    stale_pkt = packets.build_external_packet(
        AudienceRole.NVIDIA_LIGHTHOUSE, [ProjectionCandidate(_nv_item(), stale=True)],
        generated_at="T0")
    assert stale_pkt.visible_count == 0 and stale_pkt.stale_count == 0
    # the stale state is still computable internally/admin-side
    pi_stale = projector.build_projection_item(
        AudienceRole.NVIDIA_LIGHTHOUSE, _nv_item(), stale=True)
    assert pi_stale.projection_state is ProjectionState.STALE_PROJECTION


# =========================================================================== #
# rubric9 — view-as byte-identical to the real external packet
# =========================================================================== #
def test_rubric9_view_as_byte_identical():
    cands = _mixed_candidates()
    real = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    va = packets.view_as(BR_ADMIN, AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    assert va.as_dict() == real.as_dict()


# =========================================================================== #
# rubric10 — explicit empty state, never blank
# =========================================================================== #
def test_rubric10_empty_state_is_generic_external():
    # deputy-codex F1 (#3762): the EXTERNAL empty state is GENERIC — never blank, but
    # it must NOT reveal that hidden/blocked material exists or why.
    cand = ProjectionCandidate(
        _ev("po-ne2", Classification.PARTNER_SAFE_NVIDIA, [Org.NVIDIA],
            sensitivity=Sensitivity.FINANCIAL))
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert "_empty_state" in pkt.sections                       # never blank
    assert pkt.sections["_empty_state"] == "no_items_available" # generic, no reason
    assert "blocked_by_policy" not in str(pkt.as_dict())


# =========================================================================== #
# deputy-codex F1 (#3762) — external packets reveal ZERO hidden counts/reasons
# =========================================================================== #
def test_f1_external_no_hidden_counts_or_reason():
    # a never_external item + a not-yet-verified candidate for NVIDIA: both hidden.
    cands = [
        ProjectionCandidate(_ev("po-ne-f1", Classification.PARTNER_SAFE_NVIDIA,
                                [Org.NVIDIA], sensitivity=Sensitivity.FINANCIAL)),
        ProjectionCandidate(_ev("po-cand-f1", Classification.PARTNER_SAFE_NVIDIA,
                                [Org.NVIDIA], lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)),
    ]
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    assert pkt.visible_count == 0
    assert pkt.blocked_count == 0 and pkt.stale_count == 0        # no hidden counts
    d = pkt.as_dict()
    assert d["counts"]["blocked"] == 0 and d["counts"]["stale"] == 0
    blob = str(d)
    for leak in ("blocked_by_policy", "blocked_by_missing_confirmation",
                 "stale_projection", "po-ne-f1", "po-cand-f1"):
        assert leak not in blob
    # the detailed reason is still computable internally/admin-side (audience split)
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, cands[0].item)
    assert pi.projection_state is ProjectionState.BLOCKED_BY_POLICY


# =========================================================================== #
# rubric11 / deputy-codex AC4 — external field allowlist
# =========================================================================== #
def test_rubric11_field_allowlist():
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE,
                                        [ProjectionCandidate(_nv_item())], generated_at="T0")
    item = next(i for sec in pkt.sections.values() if isinstance(sec, list) for i in sec)
    assert set(item.keys()) <= set(EXTERNAL_ITEM_ALLOWLIST)
    blob = str(pkt.as_dict())
    for forbidden in FORBIDDEN_EXTERNAL_SUBSTRINGS:
        assert forbidden not in blob


# =========================================================================== #
# rubric12 / deputy-codex T8/AC9 — action-link no internal URLs + non-mutating
# =========================================================================== #
def test_rubric12_action_link_no_urls():
    cand = ProjectionCandidate(
        _nv_item(lifecycle_state=LifecycleState.ACTION_LINKED, action=True),
        action_safe_text="Review the pilot floor-load spec")
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    blob = str(pkt.as_dict())
    for url in ("clickup.com", "github.com", "dropbox.com", "http://", "https://"):
        assert url not in blob
    assert pkt.action_linked_count == 1


def test_rubric12_view_is_non_mutating():
    cand = ProjectionCandidate(_nv_item())
    before = (cand.item.lifecycle_state, cand.item.classification, cand.item.allowed_orgs)
    packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, [cand], generated_at="T0")
    assert (cand.item.lifecycle_state, cand.item.classification, cand.item.allowed_orgs) == before


# =========================================================================== #
# rubric13 / deputy-codex T9/AC10 — serializer boundary (internal vs external)
# =========================================================================== #
def test_rubric13_serializer_boundary():
    cands = [ProjectionCandidate(_nv_item())]
    ext = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    intern = packets.build_internal_preview_packet(cands, generated_at="T0")
    ext_item = next(i for sec in ext.sections.values() if isinstance(sec, list) for i in sec)
    int_item = next(i for sec in intern.sections.values() if isinstance(sec, list) for i in sec)
    # internal serializer carries the raw source id + owner; external NEVER does
    assert "source_evidence_item_id" in int_item and "owner" in int_item
    assert "source_evidence_item_id" not in ext_item and "owner" not in ext_item
    assert "po-nvidia-1" not in str(ext.as_dict())  # internal id absent externally


# =========================================================================== #
# rubric14 / deputy-codex T10 — simulated-user spoof denied server-side
# =========================================================================== #
def test_rubric14_spoof_org_role_denied():
    # NVIDIA principal tries to be served MOHG or venue
    for target in (AudienceRole.MOHG_OPS_STANDARDS, AudienceRole.VENUE_OWNER_SITE_DILIGENCE):
        with pytest.raises(SpoofDenied):
            packets.serve_external_packet(SPOOF, target, _mixed_candidates(), generated_at="T0")
    # an unknown-org principal cannot resolve to any external audience
    rogue = Principal(Org.BRISEN, "internal_team")  # not an external audience
    with pytest.raises(SpoofDenied):
        packets.serve_external_packet(rogue, AudienceRole.NVIDIA_LIGHTHOUSE,
                                      _mixed_candidates(), generated_at="T0")


# =========================================================================== #
# rubric15 / deputy-codex T11 — cache revalidated at response time
# =========================================================================== #
def test_rubric15_cache_revalidated_on_change():
    item = _nv_item()
    cand = ProjectionCandidate(item)
    cache: dict = {}
    p1 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p1.visible_count == 1
    # demote the underlying evidence AFTER caching
    item.classification = Classification.BRISEN_CONFIDENTIAL
    p2 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p2.visible_count == 0  # stale cache NOT served — revalidated + rebuilt


def test_rubric15_cache_served_when_unchanged():
    cand = ProjectionCandidate(_nv_item())
    cache: dict = {}
    p1 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    p2 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T1", cache=cache)
    assert p1 is p2  # unchanged underlying -> cached packet reused (revalidation passed)


# =========================================================================== #
# deputy-codex F2 (#3762) — cache fingerprint covers EVERY externally-serialized field
# =========================================================================== #
def test_f2_cache_invalidated_on_claim_change():
    item = _nv_item(claim="OLD claim text")
    cand = ProjectionCandidate(item)
    cache: dict = {}
    p1 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert "OLD claim text" in str(p1.as_dict())
    item.claim = "NEW claim text"   # same lifecycle/classification/grants
    p2 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p1 is not p2
    blob = str(p2.as_dict())
    assert "NEW claim text" in blob and "OLD claim text" not in blob


def test_f2_cache_invalidated_on_source_refs_change():
    item = _nv_item()  # 2 source_refs -> "2 source(s)"
    cand = ProjectionCandidate(item)
    cache: dict = {}
    p1 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert "2 source(s)" in str(p1.as_dict())
    item.source_refs = item.source_refs + ("vault:extra", "vault:extra2")  # now 4
    p2 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p1 is not p2 and "4 source(s)" in str(p2.as_dict())


def test_f2_cache_invalidated_on_action_text_and_route():
    item = _nv_item(lifecycle_state=LifecycleState.ACTION_LINKED, action=True)
    cand = ProjectionCandidate(item, route_target=RouteTarget.NVIDIA_LIGHTHOUSE,
                               action_safe_text="action A")
    cache: dict = {}
    p1 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert "action A" in str(p1.as_dict())
    cand.action_safe_text = "action B"
    p2 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p1 is not p2 and "action B" in str(p2.as_dict())
    cand.route_target = RouteTarget.EXECUTIVE_SUMMARY
    p3 = packets.serve_external_packet(NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE,
                                       [cand], generated_at="T0", cache=cache)
    assert p3 is not p2
    assert RouteTarget.EXECUTIVE_SUMMARY.value in str(p3.as_dict())


# =========================================================================== #
# deputy-codex AC11 / T12 — projection audit audience-split (external safe-only)
# =========================================================================== #
def test_ac11_external_audit_safe_only():
    cands = [ProjectionCandidate(_nv_item())]
    pkt = packets.build_external_packet(AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    pid = next(i["projection_item_id"] for sec in pkt.sections.values()
               if isinstance(sec, list) for i in sec)
    audit = packets.external_item_audit(NVIDIA, pid, cands)
    assert audit is not None
    allowed = {"projection_item_id", "audience_role", "projection_state",
               "evidence_status", "last_verified_at", "visibility_reason"}
    assert set(audit.keys()) <= allowed
    blob = str(audit)
    for forbidden in ("source_evidence_item_id", "owner", "audit_trace_id",
                      "po-nvidia-1", "reason_code", "SECRET"):
        assert forbidden not in blob


# =========================================================================== #
# deputy-codex AC12 — failure + scale controls (bounded read, fail closed)
# =========================================================================== #
def _raising():
    raise RuntimeError("projection DB down")


def test_store_save_item_fails_closed():
    pi = projector.build_projection_item(AudienceRole.NVIDIA_LIGHTHOUSE, _nv_item())
    with pytest.raises(store.ProjectionStoreUnavailableError):
        store.save_projection_item(pi, conn_factory=_raising)


def test_store_load_items_fails_closed():
    with pytest.raises(store.ProjectionStoreUnavailableError):
        store.load_projection_items("nvidia_lighthouse", conn_factory=_raising)


def test_ac12_load_projection_items_bounded():
    captured = {}

    class _Cur:
        description = [("projection_item_id",)]
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            captured["sql"], captured["params"] = sql, params
        def fetchall(self): return []

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()

    rows = store.load_projection_items("nvidia_lighthouse", limit=10**9,
                                       conn_factory=lambda: _Conn())
    assert rows == []
    assert "LIMIT" in captured["sql"]                 # bounded SQL
    assert captured["params"][1] == 500               # clamped to the hard ceiling


# =========================================================================== #
# Fixture coverage — all 6 principals exercised in one set; never_external present
# =========================================================================== #
def test_all_six_principals_same_fixture_set():
    cands = _mixed_candidates()
    # internal preview sees items; each external sees only its own; admin can view-as
    intern = packets.build_internal_preview_packet(cands, generated_at="T0")
    assert intern.visible_count >= 1
    seen = {}
    for p, role in ((NVIDIA, AudienceRole.NVIDIA_LIGHTHOUSE),
                    (MOHG, AudienceRole.MOHG_OPS_STANDARDS),
                    (VENUE, AudienceRole.VENUE_OWNER_SITE_DILIGENCE)):
        pkt = packets.serve_external_packet(p, role, cands, generated_at="T0")
        seen[role] = pkt.visible_count
        assert pkt.is_external
    assert all(v == 1 for v in seen.values())
    # admin view-as parity for one role; spoof principal denied
    packets.view_as(BR_ADMIN, AudienceRole.NVIDIA_LIGHTHOUSE, cands, generated_at="T0")
    with pytest.raises(SpoofDenied):
        packets.serve_external_packet(SPOOF, AudienceRole.MOHG_OPS_STANDARDS, cands)
    # never_external row present in the fixture set
    assert any(c.item.sensitivity is not None for c in cands)
