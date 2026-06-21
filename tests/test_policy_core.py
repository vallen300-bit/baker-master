"""AC1–AC10 + T1–T10 gate for the AI Hotel Lab policy/evidence core.

Test naming maps 1:1 to the dispatch brief so the ship report can cite a test per
AC and per threat:

  AC -> test_acN_*        Threat -> test_tN_*

The engine + lifecycle are pure, so this whole file runs with NO database. The
fail-closed store path (T10) is exercised with a fake connection factory that
raises — no live PG required.
"""

from __future__ import annotations

import pytest

from policy import engine, lifecycle, store
from policy.audit import ListAuditSink
from policy.models import (
    Action,
    Classification,
    EvidenceItem,
    LifecycleState,
    ObjectType,
    Org,
    PolicyDecision,
    Principal,
    Reason,
    Sensitivity,
)

# --------------------------------------------------------------------------- #
# Fixtures / factories
# --------------------------------------------------------------------------- #
BRISEN_DIRECTOR = Principal(Org.BRISEN, "director")
BRISEN_TEAM = Principal(Org.BRISEN, "internal_team")
BRISEN_ADMIN = Principal(Org.BRISEN, "evidence_admin")
BRISEN_AI = Principal(Org.BRISEN, "internal_team", is_ai=True)
NVIDIA = Principal(Org.NVIDIA, "ai_hospitality_lighthouse_lead")
MOHG = Principal(Org.MOHG, "ops_standards_lead")
VENUE = Principal(Org.VENUE_OWNER, "site_diligence_lead")

EXTERNALS = [NVIDIA, MOHG, VENUE]


def make_item(**kw) -> EvidenceItem:
    base = dict(
        object_id="claim-1",
        object_type=ObjectType.CLAIM,
        classification=Classification.BRISEN_RAW,
        lifecycle_state=LifecycleState.RAW_SIGNAL,
        owner_org=Org.BRISEN,
        owner="brisen-evidence-team",
        sensitivity=None,
        allowed_orgs=frozenset(),
        allowed_roles=frozenset(),
        confidence=None,
        source_refs=("src-1",),
        source_type="meeting_note",
        claim="The venue can host 400 attendees.",
        freshness="2026-06-21",
        last_reviewed="2026-06-21",
        raw_body="RAW INTERNAL BODY — must never leak",
        title="Internal title — must never leak",
    )
    base.update(kw)
    return EvidenceItem(**base)


def partner_safe_for(org: Org) -> Classification:
    return {
        Org.NVIDIA: Classification.PARTNER_SAFE_NVIDIA,
        Org.MOHG: Classification.PARTNER_SAFE_MOHG,
        Org.VENUE_OWNER: Classification.PARTNER_SAFE_VENUE_OWNER,
    }[org]


def shared_partner_item(principal: Principal, **kw) -> EvidenceItem:
    """A fully partner-readable item for ``principal`` (shared_view, matching
    classification, explicit grant, non-null confidence)."""

    defaults = dict(
        classification=partner_safe_for(principal.org),
        lifecycle_state=LifecycleState.SHARED_VIEW,
        allowed_orgs=frozenset({principal.org}),
        confidence=0.9,
    )
    defaults.update(kw)
    return make_item(**defaults)


# =========================================================================== #
# AC1 — object-level decision returns allow/deny + reason_code + evaluated inputs
# =========================================================================== #
def test_ac1_decision_shape_and_evaluated_inputs():
    item = make_item()
    d = engine.evaluate(BRISEN_DIRECTOR, item, Action.READ)
    assert isinstance(d, PolicyDecision)
    assert isinstance(d.reason_code, Reason)
    for key in ("principal_org", "role", "object_type", "object_id", "action",
                "lifecycle_state", "classification"):
        assert key in d.evaluated
    assert d.evaluated["action"] == "read"
    assert d.evaluated["classification"] == "brisen_raw"


def test_ac1_actions_cover_required_set():
    required = {"read", "search", "export", "promote", "demote", "annotate",
                "assign_action", "view_audit"}
    assert required.issubset({a.value for a in Action})


# =========================================================================== #
# AC2 — default-deny external, same server-side policy function for every surface
# =========================================================================== #
def test_ac2_default_deny_external_no_grant():
    # partner_safe_nvidia + shared_view but NO allowed_orgs grant → still deny.
    item = make_item(
        classification=Classification.PARTNER_SAFE_NVIDIA,
        lifecycle_state=LifecycleState.SHARED_VIEW,
        confidence=0.9,
        allowed_orgs=frozenset(),
    )
    d = engine.evaluate(NVIDIA, item, Action.READ)
    assert not d.allow
    assert d.reason_code is Reason.DENY_NOT_IN_ALLOWED_ORGS


def _fake_factory(items):
    """Build a conn_factory returning the given items as DB rows."""

    def to_row(it: EvidenceItem) -> dict:
        return {
            "id": 1,
            "object_id": it.object_id,
            "object_type": it.object_type.value,
            "classification": it.classification.value,
            "lifecycle_state": it.lifecycle_state.value,
            "sensitivity": it.sensitivity.value if it.sensitivity else None,
            "owner_org": it.owner_org.value,
            "owner": it.owner,
            "allowed_orgs": sorted(o.value for o in it.allowed_orgs),
            "allowed_roles": sorted(it.allowed_roles),
            "confidence": it.confidence,
            "source_refs": list(it.source_refs),
            "source_type": it.source_type,
            "claim": it.claim,
            "freshness": it.freshness,
            "last_reviewed": it.last_reviewed,
            "raw_body": it.raw_body,
            "title": it.title,
        }

    rows = [to_row(it) for it in items]
    cols = list(rows[0].keys()) if rows else []
    tuples = [tuple(r[c] for c in cols) for r in rows]

    class _Cur:
        description = [(c,) for c in cols]

        def execute(self, sql, params=None):
            return None

        def fetchall(self):
            return tuples

        def fetchone(self):
            return tuples[0] if tuples else None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def factory():
        return _Conn()

    return factory


def test_ac2_query_visible_items_filters_server_side():
    raw = make_item(object_id="raw-1", classification=Classification.BRISEN_RAW)
    shared = shared_partner_item(NVIDIA, object_id="shared-1")
    factory = _fake_factory([raw, shared])
    visible = store.query_visible_items(NVIDIA, Action.READ, conn_factory=factory)
    # external caller receives projections (dicts), never raw items (F1).
    ids = {p["object_id"] for p in visible}
    assert ids == {"shared-1"}  # raw never reaches the partner


def test_f1_external_query_never_returns_raw_item_default_path():
    # deputy-codex F1: a partner read via the DEFAULT path (project=False) must
    # still get a redacted projection — never an EvidenceItem with raw_body/title.
    shared = shared_partner_item(NVIDIA, object_id="shared-1")
    factory = _fake_factory([shared])
    visible = store.query_visible_items(NVIDIA, Action.READ, conn_factory=factory)
    assert len(visible) == 1
    proj = visible[0]
    assert not isinstance(proj, EvidenceItem)
    assert "raw_body" not in proj and "title" not in proj
    assert "source_refs" not in proj
    assert "must never leak" not in " ".join(str(v) for v in proj.values())


def test_f1_internal_default_path_returns_full_item():
    # internal callers still get full items by default (no behaviour change).
    item = make_item(object_id="raw-1", classification=Classification.BRISEN_RAW)
    factory = _fake_factory([item])
    visible = store.query_visible_items(BRISEN_DIRECTOR, Action.READ, conn_factory=factory)
    assert isinstance(visible[0], EvidenceItem)


# =========================================================================== #
# AC3 — all 7 classifications first-class
# =========================================================================== #
@pytest.mark.parametrize("cls", list(Classification))
def test_ac3_seven_classifications_recognized(cls):
    assert isinstance(cls, Classification)
    item = make_item(classification=cls)
    d = engine.evaluate(BRISEN_DIRECTOR, item, Action.READ)  # never crashes
    assert isinstance(d, PolicyDecision)


def test_ac3_exact_seven_classifications():
    assert {c.value for c in Classification} == {
        "brisen_raw", "brisen_confidential", "partner_safe_nvidia",
        "partner_safe_mohg", "partner_safe_venue_owner", "public_source", "exportable",
    }


# =========================================================================== #
# AC4 — never-external classes are HARD-DENY (beats any allow)
# =========================================================================== #
@pytest.mark.parametrize("principal", EXTERNALS)
@pytest.mark.parametrize("sensitivity", list(Sensitivity))
@pytest.mark.parametrize("action", [Action.READ, Action.SEARCH, Action.EXPORT])
def test_ac4_never_external_hard_deny_beats_allow(principal, sensitivity, action):
    # Item is otherwise fully shareable to this partner — only the never-external
    # sensitivity should block it. Proves hard-deny beats allow.
    item = shared_partner_item(
        principal,
        classification=Classification.EXPORTABLE if action is Action.EXPORT
        else partner_safe_for(principal.org),
        sensitivity=sensitivity,
    )
    d = engine.evaluate(principal, item, action)
    assert not d.allow
    assert d.reason_code is Reason.HARD_DENY_NEVER_EXTERNAL


def test_ac4_internal_can_still_read_never_external():
    item = make_item(
        classification=Classification.BRISEN_CONFIDENTIAL,
        sensitivity=Sensitivity.LEGAL,
    )
    assert engine.evaluate(BRISEN_DIRECTOR, item, Action.READ).allow


# =========================================================================== #
# AC5 — lifecycle state machine
# =========================================================================== #
def test_ac5_forward_by_one_allowed():
    item = make_item(lifecycle_state=LifecycleState.RAW_SIGNAL)
    rec = lifecycle.transition(item, LifecycleState.RESEARCH_ARTIFACT, BRISEN_TEAM,
                               source_refs=("s1",))
    assert item.lifecycle_state is LifecycleState.RESEARCH_ARTIFACT
    assert rec.prior_state == "raw_signal" and rec.new_state == "research_artifact"
    assert rec.actor_role == "internal_team" and rec.timestamp


def test_ac5_skip_denied():
    item = make_item(lifecycle_state=LifecycleState.RAW_SIGNAL)
    with pytest.raises(lifecycle.TransitionDenied) as ei:
        lifecycle.transition(item, LifecycleState.VERIFIED_EVIDENCE, BRISEN_TEAM)
    assert ei.value.reason_code == "invalid_transition"
    assert item.lifecycle_state is LifecycleState.RAW_SIGNAL  # unchanged


def test_ac5_backward_denied_without_override():
    item = make_item(lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    with pytest.raises(lifecycle.TransitionDenied):
        lifecycle.transition(item, LifecycleState.RESEARCH_ARTIFACT, BRISEN_ADMIN)


def test_ac5_backward_allowed_with_admin_override():
    item = make_item(lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    rec = lifecycle.transition(item, LifecycleState.RESEARCH_ARTIFACT, BRISEN_ADMIN,
                               override_reason="re-review: source retracted")
    assert item.lifecycle_state is LifecycleState.RESEARCH_ARTIFACT
    assert rec.override_reason == "re-review: source retracted"


def test_ac5_override_requires_admin():
    item = make_item(lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    with pytest.raises(lifecycle.TransitionDenied) as ei:
        lifecycle.transition(item, LifecycleState.RESEARCH_ARTIFACT, BRISEN_TEAM,
                             override_reason="trying to skip back")
    assert ei.value.reason_code == "override_requires_admin"


def test_ac5_transition_records_all_fields():
    item = make_item(lifecycle_state=LifecycleState.RAW_SIGNAL)
    rec = lifecycle.transition(item, LifecycleState.RESEARCH_ARTIFACT, BRISEN_TEAM,
                               source_refs=("s1", "s2"), confidence=0.5,
                               last_reviewed="2026-06-21")
    for fld in ("actor_org", "actor_role", "timestamp", "source_refs",
                "confidence", "last_reviewed", "prior_state", "new_state"):
        assert getattr(rec, fld) is not None


# =========================================================================== #
# AC6 — human ratifies partner-safe promotion; AI may propose, cannot finalize
# =========================================================================== #
def _verified(**kw) -> EvidenceItem:
    defaults = dict(
        lifecycle_state=LifecycleState.VERIFIED_EVIDENCE,
        classification=Classification.PARTNER_SAFE_NVIDIA,
        allowed_orgs=frozenset({Org.NVIDIA}),
        confidence=0.8,
    )
    defaults.update(kw)
    return make_item(**defaults)


def test_ac6_ai_cannot_finalize_promotion_via_transition():
    item = _verified()
    with pytest.raises(lifecycle.TransitionDenied) as ei:
        lifecycle.transition(item, LifecycleState.SHARED_VIEW, BRISEN_AI, confidence=0.8)
    assert ei.value.reason_code == Reason.DENY_PROMOTE_AI_CANNOT_FINALIZE.value
    assert item.lifecycle_state is LifecycleState.VERIFIED_EVIDENCE


def test_ac6_non_admin_human_cannot_finalize():
    item = _verified()
    with pytest.raises(lifecycle.TransitionDenied) as ei:
        lifecycle.transition(item, LifecycleState.SHARED_VIEW, BRISEN_TEAM, confidence=0.8)
    assert ei.value.reason_code == Reason.DENY_PROMOTE_REQUIRES_HUMAN_ADMIN.value


def test_ac6_human_admin_can_finalize():
    item = _verified()
    lifecycle.transition(item, LifecycleState.SHARED_VIEW, BRISEN_DIRECTOR, confidence=0.8)
    assert item.lifecycle_state is LifecycleState.SHARED_VIEW


def test_ac6_ai_may_propose_without_state_change():
    item = _verified()
    proposal = lifecycle.propose_promotion(item, BRISEN_AI, rationale="model says verified",
                                           source_evidence=("s1",))
    assert proposal.proposer_is_ai is True
    assert item.lifecycle_state is LifecycleState.VERIFIED_EVIDENCE  # unchanged


def test_ac6_external_cannot_propose():
    item = _verified()
    with pytest.raises(lifecycle.PromotionDenied):
        lifecycle.propose_promotion(item, NVIDIA, rationale="please share")


def test_ac6_approve_records_proposer_approver_rationale_source():
    item = _verified()
    proposal = lifecycle.propose_promotion(item, BRISEN_AI, rationale="verified by 2 sources",
                                           source_evidence=("s1", "s2"))
    rec = lifecycle.approve_promotion(item, BRISEN_DIRECTOR, proposal, confidence=0.8)
    assert rec.proposer_role == "internal_team"
    assert rec.approver_role == "director"
    assert rec.approval_timestamp
    assert rec.rationale == "verified by 2 sources"
    assert rec.source_evidence == ("s1", "s2")
    assert item.lifecycle_state is LifecycleState.SHARED_VIEW


def test_ac6_save_item_cannot_bypass_promotion_gate():
    # deputy-codex coverage note: a writer hand-building a shared_view item and
    # persisting it directly must be refused — promotion goes through lifecycle.
    item = shared_partner_item(NVIDIA)
    with pytest.raises(store.PromotionBypassError):
        store.save_item(item, conn_factory=_fake_factory([item]))


def test_ac6_save_item_via_lifecycle_allows_partner_visible():
    # the post-promotion persistence step is allowed with the explicit flag.
    item = shared_partner_item(NVIDIA)
    store.save_item(item, via_lifecycle=True, conn_factory=_fake_factory([item]))


def test_ac6_save_item_internal_state_allowed_by_default():
    # non-partner-visible states persist freely (no flag needed).
    item = make_item(lifecycle_state=LifecycleState.VERIFIED_EVIDENCE)
    store.save_item(item, conn_factory=_fake_factory([item]))


# =========================================================================== #
# AC7 — partner-safe projection is a DERIVED view, no raw leakage; audit redacted
# =========================================================================== #
def test_ac7_projection_excludes_internal_fields():
    item = shared_partner_item(NVIDIA)
    proj = engine.partner_projection(NVIDIA, item)
    assert "raw_body" not in proj
    assert "title" not in proj
    assert "allowed_orgs" not in proj
    assert proj["claim"] == item.claim
    assert proj["confidence"] == item.confidence
    assert "source_refs" not in proj  # raw refs never leak (T2/T5)
    # the secret body text appears nowhere in the projection values
    assert "must never leak" not in " ".join(str(v) for v in proj.values())


def test_f2_projection_carries_source_count():
    # deputy-codex F2: partner-visible evidence must carry a source COUNT
    # (non-sensitive), not the raw refs.
    item = shared_partner_item(NVIDIA, source_refs=("s1", "s2", "s3"))
    proj = engine.partner_projection(NVIDIA, item)
    assert proj["source_count"] == 3
    assert "source_refs" not in proj


def test_ac7_projection_denied_fails_closed():
    item = make_item(classification=Classification.BRISEN_RAW)
    with pytest.raises(engine.ProjectionDenied):
        engine.partner_projection(NVIDIA, item)


def test_ac7_redact_audit_for_partner_keeps_only_safe_fields():
    raw_audit = {
        "claim": "c", "source_type": "meeting", "freshness": "2026-06-21",
        "confidence": 0.9, "owner": "team", "raw_body": "SECRET",
        "audit_note": "internal", "allowed_orgs": ["nvidia"],
    }
    red = engine.redact_audit_for_partner(raw_audit)
    assert set(red.keys()) == {"claim", "source_type", "freshness", "confidence", "owner"}
    assert "raw_body" not in red and "audit_note" not in red


# =========================================================================== #
# AC8 — evidence confidence is the first-dashboard primitive
# =========================================================================== #
def test_ac8_partner_safe_requires_non_null_confidence():
    item = shared_partner_item(NVIDIA, confidence=None)
    d = engine.evaluate(NVIDIA, item, Action.READ)
    assert not d.allow
    assert d.reason_code is Reason.DENY_PARTNER_SAFE_MISSING_CONFIDENCE


def test_ac8_raw_signal_may_have_null_confidence_internally():
    item = make_item(lifecycle_state=LifecycleState.RAW_SIGNAL, confidence=None)
    assert engine.evaluate(BRISEN_TEAM, item, Action.READ).allow


def test_ac8_promote_to_shared_view_requires_confidence():
    item = _verified(confidence=None)
    with pytest.raises(lifecycle.TransitionDenied) as ei:
        lifecycle.transition(item, LifecycleState.SHARED_VIEW, BRISEN_DIRECTOR)
    assert ei.value.reason_code == "shared_view_requires_confidence"


# =========================================================================== #
# AC9 — logging + fail-loud; every event audited
# =========================================================================== #
def test_ac9_every_decision_writes_audit():
    sink = ListAuditSink()
    item = make_item()
    engine.evaluate(NVIDIA, item, Action.READ, sink=sink)
    assert len(sink.events) == 1
    assert sink.events[0].event_type == "decision"
    assert sink.events[0].allow is False


def test_ac9_transition_and_promotion_audited():
    sink = ListAuditSink()
    item = _verified()
    proposal = lifecycle.propose_promotion(item, BRISEN_AI, rationale="x", sink=sink)
    lifecycle.approve_promotion(item, BRISEN_DIRECTOR, proposal, confidence=0.8, sink=sink)
    kinds = [e.event_type for e in sink.events]
    assert "promotion" in kinds and "transition" in kinds


# =========================================================================== #
# AC10 — allow/deny matrix + regression + negative test
# =========================================================================== #
# (principal, item-kwargs, action, expect_allow)
_MATRIX = [
    # internal can read raw
    (BRISEN_DIRECTOR, dict(classification=Classification.BRISEN_RAW), Action.READ, True),
    # internal can read confidential
    (BRISEN_TEAM, dict(classification=Classification.BRISEN_CONFIDENTIAL), Action.READ, True),
    # external cannot read raw
    (NVIDIA, dict(classification=Classification.BRISEN_RAW,
                  lifecycle_state=LifecycleState.SHARED_VIEW, confidence=0.5,
                  allowed_orgs=frozenset({Org.NVIDIA})), Action.READ, False),
    # external CAN read its own partner_safe (fully granted)
    (NVIDIA, dict(classification=Classification.PARTNER_SAFE_NVIDIA,
                  lifecycle_state=LifecycleState.SHARED_VIEW, confidence=0.9,
                  allowed_orgs=frozenset({Org.NVIDIA})), Action.READ, True),
    # external cannot read other partner's safe (cross-partner)
    (NVIDIA, dict(classification=Classification.PARTNER_SAFE_MOHG,
                  lifecycle_state=LifecycleState.SHARED_VIEW, confidence=0.9,
                  allowed_orgs=frozenset({Org.NVIDIA})), Action.READ, False),
    # external cannot promote
    (NVIDIA, dict(classification=Classification.PARTNER_SAFE_NVIDIA,
                  lifecycle_state=LifecycleState.VERIFIED_EVIDENCE, confidence=0.9,
                  allowed_orgs=frozenset({Org.NVIDIA})), Action.PROMOTE, False),
    # internal_team (non-admin) cannot promote
    (BRISEN_TEAM, dict(), Action.PROMOTE, False),
    # admin can promote
    (BRISEN_ADMIN, dict(), Action.PROMOTE, True),
    # export only exportable
    (BRISEN_DIRECTOR, dict(classification=Classification.EXPORTABLE), Action.EXPORT, True),
    (BRISEN_DIRECTOR, dict(classification=Classification.BRISEN_RAW), Action.EXPORT, False),
]


@pytest.mark.parametrize("principal,kw,action,expect", _MATRIX)
def test_ac10_allow_deny_matrix(principal, kw, action, expect):
    item = make_item(**kw)
    assert engine.evaluate(principal, item, action).allow is expect


@pytest.mark.parametrize("principal", EXTERNALS)
def test_ac10_external_search_cannot_return_never_external(principal):
    item = make_item(classification=Classification.BRISEN_RAW,
                     lifecycle_state=LifecycleState.SHARED_VIEW, confidence=0.5,
                     allowed_orgs=frozenset({principal.org}))
    assert not engine.evaluate(principal, item, Action.SEARCH).allow


def test_ac10_export_cannot_include_brisen_confidential():
    item = make_item(classification=Classification.BRISEN_CONFIDENTIAL)
    assert not engine.evaluate(BRISEN_DIRECTOR, item, Action.EXPORT).allow


def test_ac10_malicious_param_cannot_widen_access():
    item = make_item()
    # bogus, non-enum action / classification must be denied, never allowed.
    assert not engine.evaluate(BRISEN_DIRECTOR, item, "read; drop table").allow
    bad = make_item()
    object.__setattr__(bad, "classification", "totally_made_up")
    assert not engine.evaluate(NVIDIA, bad, Action.READ).allow


# =========================================================================== #
# Threat model — T1..T10: control + a test that fails if the control is removed
# =========================================================================== #
def test_t1_confused_deputy_engine_is_server_side():
    # A partner asking to READ a non-shared item is denied by the engine itself,
    # not by any client filter.
    item = make_item(classification=Classification.PARTNER_SAFE_NVIDIA,
                     lifecycle_state=LifecycleState.VERIFIED_EVIDENCE, confidence=0.9,
                     allowed_orgs=frozenset({Org.NVIDIA}))
    d = engine.evaluate(NVIDIA, item, Action.READ)
    assert d.reason_code is Reason.DENY_NOT_SHARED_VIEW


def test_t2_search_leakage_blocked():
    item = make_item(classification=Classification.BRISEN_CONFIDENTIAL,
                     lifecycle_state=LifecycleState.SHARED_VIEW, confidence=0.9,
                     allowed_orgs=frozenset({Org.NVIDIA}))
    assert not engine.evaluate(NVIDIA, item, Action.SEARCH).allow


def test_t3_misclassification_blocked_by_sensitivity():
    # An item MISTAGGED partner_safe_nvidia but actually financial → hard deny.
    item = shared_partner_item(NVIDIA, sensitivity=Sensitivity.FINANCIAL)
    d = engine.evaluate(NVIDIA, item, Action.READ)
    assert d.reason_code is Reason.HARD_DENY_NEVER_EXTERNAL


def test_t4_ai_over_promotion_blocked():
    item = _verified()
    with pytest.raises(lifecycle.TransitionDenied):
        lifecycle.transition(item, LifecycleState.SHARED_VIEW, BRISEN_AI, confidence=0.8)


def test_t5_audit_leakage_redacted():
    red = engine.redact_audit_for_partner({"claim": "c", "raw_body": "SECRET",
                                           "source_type": "x", "freshness": "f",
                                           "confidence": 0.5, "owner": "o"})
    assert "SECRET" not in " ".join(str(v) for v in red.values())


def test_t6_cross_partner_bleed_blocked():
    item = shared_partner_item(MOHG)  # partner_safe_mohg, granted to MOHG
    d = engine.evaluate(NVIDIA, item, Action.READ)
    assert d.reason_code is Reason.DENY_CLASSIFICATION_ORG_MISMATCH


def test_t7_stale_evidence_blocked_by_confidence():
    item = shared_partner_item(NVIDIA, confidence=None)
    assert not engine.evaluate(NVIDIA, item, Action.READ).allow


def test_t8_export_widening_blocked():
    for cls in (Classification.BRISEN_RAW, Classification.BRISEN_CONFIDENTIAL,
                Classification.PARTNER_SAFE_NVIDIA):
        item = make_item(classification=cls)
        assert not engine.evaluate(BRISEN_DIRECTOR, item, Action.EXPORT).allow


@pytest.mark.parametrize("action", [Action.PROMOTE, Action.DEMOTE, Action.ANNOTATE,
                                    Action.ASSIGN_ACTION])
def test_t9_privilege_creep_external_blocked(action):
    item = shared_partner_item(NVIDIA)
    assert not engine.evaluate(NVIDIA, item, action).allow


def test_t10_fallback_open_store_unavailable_fails_closed():
    def raising_factory():
        raise RuntimeError("policy DB unreachable")

    with pytest.raises(store.PolicyUnavailableError):
        store.query_visible_items(NVIDIA, Action.READ, conn_factory=raising_factory)


def test_t10_engine_internal_error_denies(monkeypatch):
    item = make_item()
    monkeypatch.setattr(engine, "_decide",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    d = engine.evaluate(BRISEN_DIRECTOR, item, Action.READ)
    assert d.allow is False  # fail closed, no object payload
