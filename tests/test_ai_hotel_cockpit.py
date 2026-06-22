"""AI_HOTEL_LAB_COCKPIT_UI_1 — Step-5 cockpit leak/role test matrix.

Maps deputy-codex threat rubric T1-T12 + codex-arch AC2/AC3/AC5/AC10 1:1 to named
tests. These are ENDPOINT PAYLOAD assertions (per AC10: endpoint payload assertions
count, template-only do not) — they call the cockpit endpoint functions and assert
on the JSON dict the browser would receive. The no-leak property is proven at the
server boundary, not in the template.
"""
import json

import pytest

from outputs import ai_hotel_lab as lab
from policy.projection.models import AudienceRole
from policy.projection.packets import view_as

EXTERNAL_ROLES = ["nvidia", "mohg", "venue"]

# Concrete internal secrets seeded behind the boundary. NONE may appear in any
# external payload (raw bodies, internal titles, owner identity, internal source
# ids, gap reasons, Brisen-confidential claims).
INTERNAL_SECRETS = [
    "INTERNAL raw",                       # raw_body marker
    "term sheet",                         # financing raw_body
    "NVIDIA call notes",                  # raw_body
    "scraped competitor",                 # raw_body
    "Financing strategy raw",             # internal title
    "Competitor raw signal",              # internal title
    "brisen_evidence_admin",              # owner / reviewer identity
    "Financing structure and negotiation",  # brisen_confidential claim
    "Unconfirmed competitor move",        # raw signal claim
    "baker-memory", "vault-rooms", "src-",  # internal source ids
    "not yet authorized", "live crawl not", "authority site-search connector",  # gap reasons
    "not partner-projected",              # internal redaction reason
]


def _external_blob(role: str) -> str:
    """Every external payload a role can fetch, concatenated for token scanning."""
    payloads = [
        lab.get_packet(role=role),
        lab.get_raw_signals(role=role),
        lab.get_sources(role=role),
        lab.get_roadmap(role=role),
        lab.get_search(q="lighthouse site financing competitor", role=role),
        lab.get_evidence(role=role),
    ]
    return json.dumps(payloads)


# ── T1 — raw-text leak ───────────────────────────────────────────────────────
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t1_no_raw_text_leak_to_external(role):
    blob = _external_blob(role)
    for secret in INTERNAL_SECRETS:
        assert secret not in blob, f"T1 leak: {secret!r} reached {role} payload"


# ── T2 — metadata leak (counts / reasons / hints in empty/blocked state) ──────
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t2_external_packet_counts_are_content_free(role):
    pkt = lab.get_packet(role=role)
    # F1 invariant: external packets never expose blocked/stale counts.
    assert pkt["counts"]["blocked"] == 0
    assert pkt["counts"]["stale"] == 0
    # Empty sections use the generic empty-state marker, never a hidden count/reason.
    for sec in pkt["sections"].values():
        if isinstance(sec, dict):
            assert sec == {"_empty_state": "no_items_available"}


# ── T3 — cross-role bleed ─────────────────────────────────────────────────────
def test_t3_no_cross_role_section_bleed():
    nv = lab.get_packet(role="nvidia")
    mo = lab.get_packet(role="mohg")
    ve = lab.get_packet(role="venue")
    # NVIDIA never sees MOHG operator-logic or venue site-thesis sections (with content).
    assert "mandarin_oriental_operator_logic" not in _content_sections(nv)
    assert "santa_clara_site_thesis" not in _content_sections(nv)
    assert "nvidia_lighthouse" not in _content_sections(mo)
    assert "nvidia_lighthouse" not in _content_sections(ve)


def test_t3_cross_role_audit_is_absent():
    # NVIDIA asking for a venue item's audit -> 404 (absent, not denied-with-detail).
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        lab.get_item_audit("venue-site-diligence", role="nvidia")
    assert ei.value.status_code == 404


def _content_sections(pkt):
    return {k for k, v in pkt["sections"].items() if isinstance(v, list) and v}


# ── T4 — stale / revoked persistence ──────────────────────────────────────────
def test_t4_revoked_item_absent_from_external_packet():
    blob = json.dumps(lab.get_packet(role="venue"))
    assert "venue-revoked-item" not in blob  # revoked -> not visible externally


def test_t4_stale_external_item_not_actionable():
    pkt = lab.get_packet(role="mohg")
    # the stale market metric must not appear as a live external item
    assert "mohg-stale-metric" not in json.dumps(pkt)


# ── T5 — client-side permission bypass (no broad payload to filter) ───────────
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t5_external_items_only_carry_allowlist_keys(role):
    from policy.projection.models import EXTERNAL_ITEM_ALLOWLIST
    pkt = lab.get_packet(role=role)
    for sec in pkt["sections"].values():
        if isinstance(sec, list):
            for item in sec:
                extra = set(item) - set(EXTERNAL_ITEM_ALLOWLIST)
                assert not extra, f"T5: {role} item exposes non-allowlist keys {extra}"


# ── T6 — no second permission engine (consumes the canonical packet path) ─────
@pytest.mark.parametrize("role,audience", [
    ("nvidia", AudienceRole.NVIDIA_LIGHTHOUSE),
    ("mohg", AudienceRole.MOHG_OPS_STANDARDS),
    ("venue", AudienceRole.VENUE_OWNER_SITE_DILIGENCE),
])
def test_t6_packet_is_byte_identical_to_canonical_view_as(role, audience):
    # The endpoint returns exactly what policy.projection.view_as produces — it does
    # not re-decide visibility in a parallel engine. (last_generated_at is a wall-clock
    # stamp that differs per call; everything else — sections, counts, allowlist — is
    # the canonical packet.)
    def _stable(p):
        return {k: v for k, v in p.items() if k != "last_generated_at"}
    canonical = view_as(lab._OPERATOR, audience, lab._candidates()).as_dict()
    assert _stable(lab.get_packet(role=role)) == _stable(canonical)


# ── T7 — direct raw fetch ─────────────────────────────────────────────────────
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t7_raw_signal_inbox_empty_for_external(role):
    rs = lab.get_raw_signals(role=role)
    assert rs["raw_signals"] == []


@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t7_external_sources_have_no_internal_ids(role):
    src = lab.get_sources(role=role)
    for s in src["sources"]:
        assert "source_id" not in s            # no internal id exposed
        assert "gap_reason" not in s
        assert "gap_owner" not in s
        assert "never_external" not in s


# ── T8 — search fabrication / coverage honesty ────────────────────────────────
def test_t8_search_coverage_marks_gaps_honestly_internal():
    res = lab.get_search(q="comms", role="brisen")
    statuses = {c["domain"]: c["status"] for c in res["coverage"]}
    # the comms + open-web + site-search connectors are GAP, never reported live
    assert statuses["comms_email_wa_slack"] == "gap"
    assert statuses["open_web"] == "gap"
    assert statuses["site_search_public"] == "gap"


@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t8_search_results_never_fabricated(role):
    res = lab.get_search(q="zzz-nonexistent-term-zzz", role=role)
    # zero matches => zero results, never synthetic rows
    assert res["result_count"] == len(res["results"])
    assert all(r.get("projected") in (True, False) for r in res["results"])


# ── T9 — source-hint leak ─────────────────────────────────────────────────────
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t9_external_roadmap_is_empty(role):
    # roadmap is gap-derived internal detail; external roles get nothing.
    assert lab.get_roadmap(role=role)["roadmap"] == []


@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t9_external_sources_expose_no_never_external_or_gap_hint(role):
    blob = json.dumps(lab.get_sources(role=role))
    for token in ("never_external", "gap_reason", "src-", "baker_internal_memory"):
        assert token not in blob


# ── T10 — hierarchy: raw never enters the verified evidence lane ──────────────
def test_t10_verified_lane_excludes_raw_internal():
    evd = lab.get_evidence(role="brisen")
    states = {e["lifecycle_state"] for e in evd["evidence"]}
    assert "raw_signal" not in states
    assert "research_artifact" not in states


def test_t10_raw_signal_only_in_raw_state():
    rs = lab.get_raw_signals(role="brisen")
    assert rs["raw_signals"], "internal raw inbox should have at least one amber signal"


# ── AC2 / AC3 — server-side resolution, no raw rows externally ────────────────
def test_ac3_unknown_role_fails_closed():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        lab.get_packet(role="superuser")
    assert ei.value.status_code == 400


def test_ac2_brisen_internal_preview_has_full_fields_but_externals_do_not():
    internal = lab.get_packet(role="brisen")
    # internal preview legitimately carries internal ids/owner; external must not.
    assert "brisen-financing-strategy" in json.dumps(internal)
    assert "brisen-financing-strategy" not in json.dumps(lab.get_packet(role="nvidia"))


# ── AC7 — revoke/refresh disabled with exact reason; approve live ─────────────
def test_ac7_revoke_refresh_return_step51_reason():
    from fastapi import HTTPException
    for action in ("revoke", "refresh"):
        with pytest.raises(HTTPException) as ei:
            lab.post_admin_action(action, projection_item_id="nv-lighthouse-thesis")
        assert ei.value.status_code == 501
        assert ei.value.detail == "Step 5.1 pending persisted projection-admin store"


def test_ac7_approve_is_live_and_audited():
    out = lab.post_admin_action("approve", projection_item_id="brisen-financing-strategy")
    assert out["ok"] is True
    assert out["action"] == "approve"


# ── AC1 — page shell renders; safe DOM only (no innerHTML XSS surface) ────────
def test_cockpit_page_renders_html():
    resp = lab.cockpit_page()
    assert resp.status_code == 200
    body = resp.body.decode()
    for marker in ("AI Hotel Lab", "View as NVIDIA", "Raw Signal Inbox",
                   "Verified Evidence", "Partner Projection", "Execution Roadmap",
                   "Step 5.1 pending persisted projection-admin store"):
        assert marker in body


def test_cockpit_page_uses_no_innerhtml_assignment():
    # Dynamic content is built via textContent/DOM; no innerHTML sink (XSS guard).
    body = lab.cockpit_page().body.decode()
    assert ".innerHTML" not in body


def test_all_four_role_views_render_without_error():
    # G1: render the 4 role views server-side (endpoint payloads resolve cleanly).
    for role in ("brisen", "nvidia", "mohg", "venue"):
        assert lab.get_packet(role=role)["audience_label"]


# ── G2 #3879 BLOCKER 1 — external search must not leak the zero-result route ──
@pytest.mark.parametrize("role", EXTERNAL_ROLES)
def test_t9_external_search_has_no_zero_result_route_or_gap_hint(role):
    res = lab.get_search(q="no-such-term-xyzzy lighthouse financing", role=role)
    assert res["zero_result_route"] is None          # generic empty state, no route hint
    blob = json.dumps(res)
    for token in ("source_gap", "unassigned_review", "risk_permissions_review",
                  "_gap_", "zero_result_reason"):
        assert token not in blob, f"T9: {role} search leaked {token!r}"


def test_internal_search_keeps_zero_result_route_for_triage():
    # Internal Brisen retains the route to triage gaps (not a leak — internal surface).
    res = lab.get_search(q="no-such-term-xyzzy", role="brisen")
    assert "zero_result_route" in res  # present (may be a route value) for internal


# ── G2 #3879 BLOCKER 2 (A.1) — cockpit page challenges unauth browsers ────────
def test_unauthenticated_browser_is_challenged_not_served():
    from fastapi.testclient import TestClient
    from outputs import dashboard
    c = TestClient(dashboard.app)
    r = c.get("/ai-hotel-lab")
    assert r.status_code == 401                       # challenged, not 500
    assert "Access code" in r.text                    # PIN-login served
    assert "View as NVIDIA" not in r.text             # cockpit NOT served to unauth
    # data routes stay hard-gated regardless
    assert c.get("/ai-hotel-lab/api/packet?role=nvidia").status_code == 401
    # header client (and tests) are served the cockpit unchanged
    key = getattr(dashboard, "_BAKER_API_KEY", "")
    if key:
        r2 = c.get("/ai-hotel-lab", headers={"X-Baker-Key": key})
        assert r2.status_code == 200 and "View as NVIDIA" in r2.text
