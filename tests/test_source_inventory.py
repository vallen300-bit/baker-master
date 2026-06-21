"""AC1–AC10 + T1–T10 gate for the AI Hotel Lab source registry (Step 2).

Test names map 1:1 to the brief so the ship report can cite a test per AC and per
threat. Every test runs with NO database — the fail-closed store path (T10) uses a
raising conn factory, and the live-policy integration spy patches
``policy.engine.partner_projection``.

The load-bearing invariant: **no source can become externally visible through
registry metadata alone — the Step-1 policy engine + projection remain the final
control.**
"""

from __future__ import annotations

import pytest

from policy import engine
from policy.models import (
    Classification,
    LifecycleState,
    Org,
    Principal,
    Sensitivity,
)
from policy.sources import fixtures, registry, sourcemap, store
from policy.sources.models import (
    CollectionStatus,
    ProvenanceClass,
    SourceDomain,
    SourceObjectType,
    SourceRecord,
)

BRISEN_DIRECTOR = Principal(Org.BRISEN, "director")
BRISEN_AI = Principal(Org.BRISEN, "internal_team", is_ai=True)
NVIDIA = Principal(Org.NVIDIA, "ai_hospitality_lighthouse_lead")
MOHG = Principal(Org.MOHG, "ops_standards_lead")
VENUE = Principal(Org.VENUE_OWNER, "site_diligence_lead")
EXTERNALS = [NVIDIA, MOHG, VENUE]


def _valid_wired(**kw) -> SourceRecord:
    """A valid, partner-visible-to-NVIDIA wired record; override via kw."""

    base = dict(
        source_id=fixtures.opaque_id("test-wired"),
        domain=SourceDomain.VAULT_PROJECT_ROOMS,
        source_type="curated_partner_brief",
        object_type=SourceObjectType.PARTNER_SIGNAL,
        owner_org=Org.BRISEN,
        classification=Classification.PARTNER_SAFE_NVIDIA,
        lifecycle_state=LifecycleState.SHARED_VIEW,
        provenance_class=ProvenanceClass.DERIVED,
        collection_status=CollectionStatus.WIRED,
        allowed_orgs=frozenset({Org.NVIDIA}),
        raw_body_available_internal=True,
        external_projection_available=True,
        provenance_refs=("vault:secret/path.md",),
        policy_object_id="po-test-1",
        name="SECRET internal name",
        claim="The Lab can host the pilot.",
        confidence=0.9,
        freshness="2026-06-21",
    )
    base.update(kw)
    return SourceRecord(**base)


# =========================================================================== #
# AC1 — registry schema mandatory + machine-readable; missing fields fail closed
# =========================================================================== #
def test_ac1_valid_record_passes_validation():
    registry.validate_record(_valid_wired())  # no raise


@pytest.mark.parametrize("field", [
    "source_id", "source_type", "freshness", "policy_object_id",
])
def test_ac1_missing_required_field_fails_closed(field):
    rec = _valid_wired(**{field: None})
    with pytest.raises(registry.RegistryInvalidError):
        registry.validate_record(rec)


def test_ac1_save_validates_before_persist():
    rec = _valid_wired(policy_object_id=None)  # invalid non-gap
    with pytest.raises(registry.RegistryInvalidError):
        store.save_source(rec, conn_factory=lambda: (_ for _ in ()).throw(AssertionError("must not reach DB")))


# =========================================================================== #
# AC2 — exactly the 8 domains; no misc; gaps explicit
# =========================================================================== #
def test_ac2_exactly_eight_domains():
    assert len(list(SourceDomain)) == 8
    assert "misc" not in {d.value for d in SourceDomain}


def test_ac2_fixtures_cover_all_eight_domains():
    recs = fixtures.sample_records()
    assert {r.domain for r in recs} == set(SourceDomain)


def test_ac2_at_least_three_gap_rows():
    gaps = [r for r in fixtures.sample_records() if r.is_gap]
    assert len(gaps) >= 3


# =========================================================================== #
# AC3 — classification is NOT a grant
# =========================================================================== #
def test_ac3_misregistered_partner_safe_still_denied_without_grant():
    # mis-registered partner_safe_nvidia but NO allowed_orgs grant → engine hides it.
    rec = _valid_wired(allowed_orgs=frozenset())
    assert registry.external_projection_for(NVIDIA, rec) is None


def test_f1_external_projection_fails_closed_on_missing_policy_object_id():
    # deputy-codex F1: a non-gap record missing policy_object_id must NOT project —
    # no fallback to source_id, no leaked identifier. Fail closed (raise), no payload.
    rec = _valid_wired(policy_object_id=None)
    with pytest.raises(registry.RegistryInvalidError):
        registry.external_projection_for(NVIDIA, rec)


def test_f1_query_external_fails_closed_on_invalid_record(monkeypatch):
    good = _valid_wired()
    bad = _valid_wired(source_id=fixtures.opaque_id("bad"), policy_object_id=None)
    monkeypatch.setattr(store, "load_sources", lambda **k: [good, bad])
    with pytest.raises(registry.RegistryInvalidError):
        store.query_external_visible_sources(NVIDIA)


def test_f1_record_to_evidence_item_requires_policy_object_id():
    rec = _valid_wired(policy_object_id=None)
    with pytest.raises(registry.RegistryInvalidError):
        registry.record_to_evidence_item(rec)


# =========================================================================== #
# AC4 / T3 — uses the LIVE Step-1 policy engine; no duplicate allow path
# =========================================================================== #
def test_ac4_uses_live_policy_engine_spy(monkeypatch):
    calls = {"n": 0}
    real = engine.partner_projection

    def spy(principal, item, **kw):
        calls["n"] += 1
        return real(principal, item, **kw)

    monkeypatch.setattr(engine, "partner_projection", spy)
    rec = _valid_wired()
    registry.external_projection_for(NVIDIA, rec)
    assert calls["n"] == 1  # the registry delegated to the engine


def test_t3_removing_engine_call_would_change_result(monkeypatch):
    # If the registry had its own allow path, patching the engine to always deny
    # would NOT hide the row. Because it delegates, denial propagates.
    monkeypatch.setattr(
        engine, "partner_projection",
        lambda *a, **k: (_ for _ in ()).throw(engine.ProjectionDenied("forced")),
    )
    rec = _valid_wired()
    assert registry.external_projection_for(NVIDIA, rec) is None


# =========================================================================== #
# AC5 / T4 — never-external survives even if mis-classified partner-safe
# =========================================================================== #
@pytest.mark.parametrize("principal", EXTERNALS)
def test_ac5_never_external_hard_deny(principal):
    rec = _valid_wired(
        classification=Classification.PARTNER_SAFE_NVIDIA,
        allowed_orgs=frozenset({principal.org}),
        sensitivity=Sensitivity.FINANCIAL,  # never-external dimension set
    )
    assert registry.external_projection_for(principal, rec) is None


# =========================================================================== #
# AC6 / T2 — raw-body flag is non-leaking
# =========================================================================== #
def test_ac6_projection_has_no_raw_body_title_or_identifiers():
    rec = _valid_wired(raw_body_available_internal=True)
    proj = registry.external_projection_for(NVIDIA, rec)
    assert proj is not None
    blob = " ".join(str(v) for v in proj.values())
    assert "raw_body" not in proj and "title" not in proj
    assert "SECRET internal name" not in blob       # internal name never leaks
    assert "vault:secret/path.md" not in blob       # provenance ref never leaks
    assert "source_refs" not in proj


# =========================================================================== #
# AC7 — hidden rows must carry a redaction_reason
# =========================================================================== #
def test_ac7_hidden_row_without_reason_fails_closed():
    rec = _valid_wired(external_projection_available=False, redaction_reason=None)
    with pytest.raises(registry.RegistryInvalidError):
        registry.validate_record(rec)


def test_ac7_hidden_row_with_reason_ok():
    rec = _valid_wired(external_projection_available=False,
                       redaction_reason="internal only")
    registry.validate_record(rec)  # no raise


# =========================================================================== #
# AC8 / T7 — gap sources first-class, never a silent blank
# =========================================================================== #
def _gap(**kw) -> SourceRecord:
    base = dict(
        source_id=fixtures.opaque_id("test-gap"),
        domain=SourceDomain.COMMS_EMAIL_WA_SLACK,
        source_type="slack_workspace",
        object_type=SourceObjectType.PARTNER_SIGNAL,
        owner_org=Org.BRISEN,
        classification=Classification.BRISEN_CONFIDENTIAL,
        lifecycle_state=LifecycleState.RAW_SIGNAL,
        provenance_class=ProvenanceClass.FIRST_PARTY,
        collection_status=CollectionStatus.GAP,
        raw_body_available_internal=False,
        external_projection_available=False,
        freshness="2026-06-21",
        gap_owner="AID-T",
        gap_reason="not wired",
        gap_next_action="wire later",
    )
    base.update(kw)
    return SourceRecord(**base)


def test_ac8_gap_row_requires_owner_reason_next():
    with pytest.raises(registry.RegistryInvalidError):
        registry.validate_record(_gap(gap_next_action=None))


def test_ac8_gap_row_never_externally_visible():
    assert registry.external_projection_for(NVIDIA, _gap()) is None


def test_ac8_gap_cannot_be_marked_external():
    with pytest.raises(registry.RegistryInvalidError):
        registry.validate_record(_gap(external_projection_available=True))


# =========================================================================== #
# AC9 / T9 — provenance audience-scoped; source_id opaque; no identifier leakage
# =========================================================================== #
def test_ac9_external_has_provenance_class_not_raw_refs():
    proj = registry.external_projection_for(NVIDIA, _valid_wired())
    assert proj["provenance_class"] == ProvenanceClass.DERIVED.value
    assert "provenance_refs" not in proj
    assert "source_count" in proj


def test_ac9_source_id_opaque_and_non_enumerable():
    a = fixtures.opaque_id("alpha")
    b = fixtures.opaque_id("beta")
    assert a.startswith("src_") and b.startswith("src_")
    assert a != b
    # not sequential / not a path / not a url
    for sid in (a, b):
        assert "/" not in sid and ":" not in sid
        assert not sid.replace("src_", "").isdigit()


def test_t9_no_identifier_leakage_in_source_map():
    recs = fixtures.sample_records()
    text = sourcemap.generate_source_map(recs, NVIDIA)
    for ref in ("gmail:thread", "dropbox:/", "bank:term-sheet", "vault:ai-hotel"):
        assert ref not in text


# =========================================================================== #
# AC10 — registry changes auditable; human ratifies external exposure
# =========================================================================== #
def test_ac10_ai_cannot_make_source_externally_visible():
    rec = _valid_wired(external_projection_available=False,
                       redaction_reason="pending review")
    with pytest.raises(registry.RegistryBypassError):
        registry.apply_registry_change(
            rec, "external_projection_available", True, BRISEN_AI,
            rationale="model thinks it's safe", decision_source="auto",
        )


def test_ac10_human_can_ratify_external_exposure():
    rec = _valid_wired(external_projection_available=False,
                       redaction_reason="pending review")
    change = registry.apply_registry_change(
        rec, "external_projection_available", True, BRISEN_DIRECTOR,
        rationale="director approved", decision_source="director_review",
    )
    assert rec.external_projection_available is True
    assert change.increases_external_exposure is True
    assert change.actor_role == "director"


def test_ac10_propose_does_not_mutate():
    rec = _valid_wired()
    before = rec.classification
    change = registry.propose_registry_change(
        rec, "classification", Classification.EXPORTABLE, BRISEN_AI,
        rationale="x", decision_source="auto",
    )
    assert rec.classification is before        # unchanged
    assert change.actor_is_ai is True


def test_ac10_ai_can_change_internal_metadata():
    rec = _valid_wired()
    registry.apply_registry_change(
        rec, "freshness", "2026-06-22", BRISEN_AI,
        rationale="re-checked", decision_source="auto",
    )
    assert rec.freshness == "2026-06-22"


# =========================================================================== #
# T5 — cross-partner bleed (NVIDIA ↔ MOHG)
# =========================================================================== #
def test_t5_cross_partner_bleed_blocked():
    rec = _valid_wired(
        classification=Classification.PARTNER_SAFE_MOHG,
        allowed_orgs=frozenset({Org.MOHG}),
    )
    assert registry.external_projection_for(NVIDIA, rec) is None
    assert registry.external_projection_for(MOHG, rec) is not None


# =========================================================================== #
# T6 — no search / no snippets / no summaries leak through the map or projection
# =========================================================================== #
def test_t6_no_snippet_or_body_keys_in_projection():
    proj = registry.external_projection_for(NVIDIA, _valid_wired())
    for forbidden in ("snippet", "summary", "body", "raw_body", "content"):
        assert forbidden not in proj


# =========================================================================== #
# T8 — public-source fallacy: public ≠ grant
# =========================================================================== #
def test_t8_public_source_still_needs_grant():
    rec = _valid_wired(
        classification=Classification.PUBLIC_SOURCE,
        provenance_class=ProvenanceClass.PUBLIC,
        allowed_orgs=frozenset(),  # public, but no explicit grant
        raw_body_available_internal=False,
    )
    assert registry.external_projection_for(NVIDIA, rec) is None


# =========================================================================== #
# T10 — tamper / audit gap: fail closed; changes recorded
# =========================================================================== #
def test_t10_query_external_fails_closed_on_store_error():
    def raising():
        raise RuntimeError("registry DB down")

    with pytest.raises(store.SourceRegistryUnavailableError):
        store.query_external_visible_sources(NVIDIA, conn_factory=raising)


def test_t10_apply_change_records_audit_via_recorder():
    rec = _valid_wired()
    recorded = []
    registry.apply_registry_change(
        rec, "freshness", "2026-06-22", BRISEN_DIRECTOR,
        rationale="r", decision_source="d", recorder=recorded.append,
    )
    assert len(recorded) == 1
    assert recorded[0].field == "freshness"
    assert recorded[0].prior_value and recorded[0].new_value == "2026-06-22"


# =========================================================================== #
# Integration — query_external_visible_sources + source-map sample
# =========================================================================== #
def test_query_external_visible_sources_returns_only_projections(monkeypatch):
    monkeypatch.setattr(store, "load_sources", lambda **k: fixtures.sample_records())
    out = store.query_external_visible_sources(NVIDIA)
    # NVIDIA sees only its granted partner-safe + broadly-granted public rows;
    # never the internal/raw/financial/gap rows.
    assert out  # non-empty
    for proj in out:
        assert "raw_body" not in proj and "title" not in proj
        assert "provenance_refs" not in proj
    blob = " ".join(str(v) for p in out for v in p.values())
    assert "gmail:thread" not in blob and "bank:term-sheet" not in blob


def test_sourcemap_sample_has_all_domains_and_gaps():
    text = sourcemap.generate_source_map(fixtures.sample_records(), NVIDIA)
    # all 8 domain headers present (no silent omission, T7)
    for n in range(1, 9):
        assert f"## {n}." in text
    assert "⛔ GAP" in text          # gaps explicit
    assert "🔒 hidden" in text       # redacted rows explicit
