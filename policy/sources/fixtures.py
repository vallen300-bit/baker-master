"""SAMPLE source-registry rows for the AI Hotel Lab (demo + tests only).

NOT real data and NOT a seed migration — representative fixtures covering all 8
domains plus explicit gap rows, used by the source-map sample (done rubric #5) and
the test gate. Every row validates against ``registry.validate_record``.

``source_id`` values are opaque, deterministic hashes (AC9: non-enumerable, no
sequential ids, no path/url/message-id leakage).
"""

from __future__ import annotations

import hashlib
from typing import List

from policy.models import Classification, LifecycleState, Org, Sensitivity
from policy.sources.models import (
    CollectionStatus,
    ProvenanceClass,
    SourceDomain,
    SourceObjectType,
    SourceRecord,
)


def opaque_id(label: str) -> str:
    """Deterministic, opaque, non-enumerable source id (AC9)."""

    return "src_" + hashlib.sha256(("ai-hotel-source::" + label).encode()).hexdigest()[:16]


def sample_records() -> List[SourceRecord]:
    """≥1 wired row per 8 domains + 3 explicit gap rows (done rubric #2)."""

    rows: List[SourceRecord] = [
        # 1. Baker internal memory — internal only, never partner-facing.
        SourceRecord(
            source_id=opaque_id("baker-memory-decisions"),
            domain=SourceDomain.BAKER_INTERNAL_MEMORY,
            source_type="baker_decisions_log",
            object_type=SourceObjectType.NOTE,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_CONFIDENTIAL,
            lifecycle_state=LifecycleState.VERIFIED_EVIDENCE,
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.WIRED,
            raw_body_available_internal=True,
            external_projection_available=False,
            redaction_reason="internal Brisen reasoning — not partner-facing",
            provenance_refs=("baker:decisions:1042",),
            policy_object_id="src-baker-memory-1",
            name="Lab go/no-go decision log",
            freshness="2026-06-21",
        ),
        # 2. Vault / project rooms — curated NVIDIA-safe material, shared.
        SourceRecord(
            source_id=opaque_id("vault-nvidia-curated"),
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
            provenance_refs=("vault:ai-hotel/nvidia/brief.md", "vault:ai-hotel/lighthouse.md"),
            policy_object_id="src-vault-nvidia-1",
            name="NVIDIA lighthouse readiness brief",
            claim="The Lab can host an NVIDIA AI-hospitality lighthouse pilot in Q4.",
            confidence=0.9,
            freshness="2026-06-20",
        ),
        # 3. Dropbox / project files — internal site design, not partner-facing.
        SourceRecord(
            source_id=opaque_id("dropbox-site-design"),
            domain=SourceDomain.DROPBOX_PROJECT_FILES,
            source_type="dropbox_design_folder",
            object_type=SourceObjectType.DOCUMENT,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_CONFIDENTIAL,
            lifecycle_state=LifecycleState.RESEARCH_ARTIFACT,
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.PARTIAL,
            raw_body_available_internal=True,
            external_projection_available=False,
            redaction_reason="internal design WIP — not cleared for any partner",
            provenance_refs=("dropbox:/AI Hotel/Design/",),
            policy_object_id="src-dropbox-design-1",
            name="Santa Clara site design WIP",
            freshness="2026-06-18",
        ),
        # 4. Email / WA / Slack — raw correspondence, NEVER external (hard-deny).
        SourceRecord(
            source_id=opaque_id("comms-partner-email"),
            domain=SourceDomain.COMMS_EMAIL_WA_SLACK,
            source_type="email_thread",
            object_type=SourceObjectType.PARTNER_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_RAW,
            lifecycle_state=LifecycleState.RAW_SIGNAL,
            sensitivity=Sensitivity.EMAIL_WA_RAW,  # never-external hard-deny dimension
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.WIRED,
            raw_body_available_internal=True,
            external_projection_available=False,
            redaction_reason="raw correspondence — never external (AC5)",
            provenance_refs=("gmail:thread:abc123",),
            policy_object_id="src-comms-email-1",
            name="Brisen↔NVIDIA email thread",
            freshness="2026-06-21",
        ),
        # 5. Field evidence — site photos, venue-owner-safe, shared.
        SourceRecord(
            source_id=opaque_id("field-site-photos"),
            domain=SourceDomain.FIELD_EVIDENCE,
            source_type="site_photo_capture",
            object_type=SourceObjectType.SITE_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.PARTNER_SAFE_VENUE_OWNER,
            lifecycle_state=LifecycleState.SHARED_VIEW,
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.WIRED,
            allowed_orgs=frozenset({Org.VENUE_OWNER}),
            raw_body_available_internal=True,
            external_projection_available=True,
            provenance_refs=("field:capture:551", "field:capture:552"),
            policy_object_id="src-field-photos-1",
            name="Venue condition survey photos",
            claim="The venue's east hall meets the pilot floor-load spec.",
            confidence=0.8,
            freshness="2026-06-19",
        ),
        # 6. Open web — hospitality/AI press, public, broadly partner-visible.
        SourceRecord(
            source_id=opaque_id("openweb-hospitality-press"),
            domain=SourceDomain.OPEN_WEB,
            source_type="press_rss",
            object_type=SourceObjectType.COMPETITOR_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.PUBLIC_SOURCE,
            lifecycle_state=LifecycleState.SHARED_VIEW,
            provenance_class=ProvenanceClass.PUBLIC,
            collection_status=CollectionStatus.WIRED,
            allowed_orgs=frozenset({Org.NVIDIA, Org.MOHG, Org.VENUE_OWNER}),
            raw_body_available_internal=False,
            external_projection_available=True,
            provenance_refs=("rss:hospitality-ai",),
            policy_object_id="src-openweb-press-1",
            name="AI-hospitality market press",
            claim="Branded AI-hospitality pilots are accelerating in 2026.",
            confidence=0.7,
            freshness="2026-06-21",
        ),
        # 7. Santa Clara / site-search public data — zoning, public.
        SourceRecord(
            source_id=opaque_id("sitepublic-zoning"),
            domain=SourceDomain.SITE_SEARCH_PUBLIC,
            source_type="city_planning_portal",
            object_type=SourceObjectType.SITE_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.PUBLIC_SOURCE,
            lifecycle_state=LifecycleState.SHARED_VIEW,
            provenance_class=ProvenanceClass.PUBLIC,
            collection_status=CollectionStatus.WIRED,
            allowed_orgs=frozenset({Org.NVIDIA, Org.VENUE_OWNER}),
            raw_body_available_internal=False,
            external_projection_available=True,
            provenance_refs=("santaclara:planning:APN-104-22",),
            policy_object_id="src-site-zoning-1",
            name="Santa Clara zoning record",
            claim="The parcel is zoned for hospitality with a conditional-use path.",
            confidence=0.6,
            freshness="2026-06-15",
        ),
        # 8. Market / capital / residence — bank financing, capital-sensitive, never external.
        SourceRecord(
            source_id=opaque_id("market-financing-signal"),
            domain=SourceDomain.MARKET_CAPITAL_RESIDENCE,
            source_type="bank_financing_note",
            object_type=SourceObjectType.FINANCING_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_CONFIDENTIAL,
            lifecycle_state=LifecycleState.VERIFIED_EVIDENCE,
            sensitivity=Sensitivity.FINANCIAL,  # capital-sensitive never-external
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.WIRED,
            raw_body_available_internal=True,
            external_projection_available=False,
            redaction_reason="capital-sensitive financing terms — never external (AC5)",
            provenance_refs=("bank:term-sheet:v3",),
            policy_object_id="src-market-financing-1",
            name="Construction financing term signal",
            freshness="2026-06-17",
        ),
        # --- 3 explicit GAP rows (AC8) — no payload, owner/reason/next_action ---
        SourceRecord(
            source_id=opaque_id("gap-slack"),
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
            gap_reason="Slack is not yet wired into Lab ingestion",
            gap_next_action="wire Slack export after Step 3 search lands",
        ),
        SourceRecord(
            source_id=opaque_id("gap-partner-dataroom"),
            domain=SourceDomain.VAULT_PROJECT_ROOMS,
            source_type="partner_data_room",
            object_type=SourceObjectType.PARTNER_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_CONFIDENTIAL,
            lifecycle_state=LifecycleState.RAW_SIGNAL,
            provenance_class=ProvenanceClass.PARTNER_PROVIDED,
            collection_status=CollectionStatus.GAP,
            raw_body_available_internal=False,
            external_projection_available=False,
            freshness="2026-06-21",
            gap_owner="origination-desk",
            gap_reason="NVIDIA/MOHG shared data room not yet provisioned",
            gap_next_action="request data-room access in partnership MoU",
        ),
        SourceRecord(
            source_id=opaque_id("gap-residence-crm"),
            domain=SourceDomain.MARKET_CAPITAL_RESIDENCE,
            source_type="residence_buyer_crm",
            object_type=SourceObjectType.RESIDENCE_SIGNAL,
            owner_org=Org.BRISEN,
            classification=Classification.BRISEN_CONFIDENTIAL,
            lifecycle_state=LifecycleState.RAW_SIGNAL,
            provenance_class=ProvenanceClass.FIRST_PARTY,
            collection_status=CollectionStatus.GAP,
            raw_body_available_internal=False,
            external_projection_available=False,
            freshness="2026-06-21",
            gap_owner="sales-desk",
            gap_reason="branded-residence buyer CRM not yet stood up",
            gap_next_action="defer until residence sales workstream opens",
        ),
    ]
    return rows
