"""Unit tests for the Publisher render engine (PUBLISHER_AGENT_INSTALL_1 Part 3).

Covers:
  * AC2 — each of the 5 deterministic gates demonstrably FAILs a seeded violation
    (and PASSes a clean render).
  * AC7 — per-render context isolation: a matter-A fact never leaks into a
    matter-B render in the same drain run; the engine is stateless (same input →
    identical output; interleaved renders independent).
  * AC1 (mechanism) — fact-faithful re-render: every figure / section / receipt a
    packet declares round-trips byte-normalized through the render. Also grounded
    on the real on-disk v1 fixture (its receipts all survive the render).

Pure, no network, no DB, no model call — the engine is deterministic code.
"""
from __future__ import annotations

import json
import os

import pytest

from orchestrator.publisher_render import (
    Figure,
    PublisherFacts,
    RenderDoc,
    Receipt,
    build_render_doc,
    extract_figures,
    extract_page_version,
    extract_receipts,
    extract_sections,
    facts_from_ticket,
    gate_as_of,
    gate_honesty,
    gate_lexical,
    gate_staleness,
    gate_version_stamp,
    render_html,
    render_ticket,
    resolve_content_contract,
)

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..",
    "brisen-lab",  # not used; real path below via baker-vault
)

# The real on-disk v1 packet (build-infra fixture). Resolved relative to the
# baker-vault checkout that sits beside this repo clone.
_VAULT_FIXTURE = os.path.expanduser(
    "~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/"
    "BB-AUK-001/data-fixture.json"
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _clean_ticket(**over) -> dict:
    """A packet that PASSes every gate — the round-trip / control baseline."""
    tk = {
        "contract": "FLIGHT_DASHBOARD_PACKET v2",
        "project_code": "BB-AUK-001",
        "flight_name": "Aukera financing",
        "matter_slug": "aukera",
        "desk_owner": "baden-baden-desk",
        "business_outcome": "Advance or close the Aukera financing with visible proof.",
        "snapshot_mode": "read_only",
        "page_version": 15,
        "last_refreshed_at": "2026-07-08",
        "machine_counts_source": "ledger_query",
        "figures": [
            {"value": "12.31M", "label": "Facility EUR",
             "source_family": "loan agreement", "source_version": "v26", "as_of": "2026-07-02"},
            {"value": "547K", "label": "Self-fund per month",
             "source_family": "cash-flow email", "source_version": "1", "as_of": "2026-06-17"},
        ],
        "receipts": [
            {"ref": "#5572", "detail": "loan draft v26 sweep"},
            {"ref": "[BB-AUK-001]", "detail": "matter tag"},
        ],
        "version_history": [13, 14, 15],
    }
    tk.update(over)
    return tk


def _clean_doc(**over) -> RenderDoc:
    """A gate context that PASSes every gate; override one field to seed one
    violation (AC2)."""
    facts = facts_from_ticket(_clean_ticket())
    contract = resolve_content_contract(_clean_ticket())
    html_text = render_html(facts, contract)
    base = build_render_doc(facts, contract, html_text)
    fields = {
        "html": base.html, "figures": base.figures, "business_text": base.business_text,
        "sections": base.sections, "receipts": base.receipts,
        "page_version": base.page_version, "prior_version": base.prior_version,
        "register": base.register, "machine_counts_source": base.machine_counts_source,
        "snapshot_mode": base.snapshot_mode, "lexical_english_only": base.lexical_english_only,
    }
    fields.update(over)
    return RenderDoc(**fields)


# ── AC2: clean render passes all 5 gates ─────────────────────────────────────
def test_clean_render_passes_every_gate():
    r = render_ticket(_clean_ticket())
    assert r["status"] == "rendered", r["gates"]
    assert all(g["verdict"] == "PASS" for g in r["gates"]), r["gates"]
    assert {g["gate"] for g in r["gates"]} == {
        "version-stamp", "lexical", "as-of", "staleness", "honesty"
    }


# ── AC2: version-stamp gate ──────────────────────────────────────────────────
def test_gate_version_stamp_fails_when_missing():
    assert gate_version_stamp(_clean_doc(page_version=None))["verdict"] == "FAIL"


def test_gate_version_stamp_fails_when_not_incremented():
    v = gate_version_stamp(_clean_doc(page_version=14, prior_version=14))
    assert v["verdict"] == "FAIL"
    assert "increment" in v["detail"]


def test_gate_version_stamp_passes_on_increment():
    assert gate_version_stamp(_clean_doc(page_version=15, prior_version=14))["verdict"] == "PASS"


# ── AC2: lexical gate (10a diacritic, 10a term, 10b abbrev, 10c wall) ────────
def test_gate_lexical_fails_on_german_diacritic():
    v = gate_lexical(_clean_doc(business_text="The Annaberg facility uses Gebuehren über time."))
    assert v["verdict"] == "FAIL"
    assert "10a" in v["detail"]


def test_gate_lexical_fails_on_german_term():
    v = gate_lexical(_clean_doc(business_text="See the Darlehensvertrag for the facility amount."))
    assert v["verdict"] == "FAIL" and "Darlehensvertrag" in v["detail"]


def test_gate_lexical_fails_on_banned_abbreviation():
    v = gate_lexical(_clean_doc(business_text="The LTV is comfortably inside the cap."))
    assert v["verdict"] == "FAIL" and "LTV" in v["detail"]


def test_gate_lexical_fails_on_wall_of_text():
    wall = (
        '<section id="v1"><div class="card"><span>This is one. This is two. '
        "This is three. This is four.</span></div></section>"
    )
    v = gate_lexical(_clean_doc(html=wall, business_text="This is one. This is two. This is three. This is four."))
    assert v["verdict"] == "FAIL" and "10c" in v["detail"]


def test_gate_lexical_exempts_engine_lab_from_wall_of_text():
    # An engineer-facing build log in the Engine-Lab section is exempt (rule 10c).
    wall = (
        '<section id="v9"><div class="card"><span>Build one. Build two. '
        "Build three. Build four.</span></div></section>"
    )
    v = gate_lexical(_clean_doc(html=wall, business_text=""))
    assert v["verdict"] == "PASS"


# ── AC2: as-of gate ──────────────────────────────────────────────────────────
def test_gate_as_of_fails_on_missing_anchor():
    figs = (Figure(value="12.31M", label="Facility", source_version="v26", as_of=""),)
    v = gate_as_of(_clean_doc(figures=figs))
    assert v["verdict"] == "FAIL" and "as-of" in v["detail"]


def test_gate_as_of_passes_when_all_anchored():
    figs = (Figure(value="12.31M", label="Facility", as_of="2026-07-02"),)
    assert gate_as_of(_clean_doc(figures=figs))["verdict"] == "PASS"


# ── AC2: staleness gate (9c vs living-documents register) ────────────────────
def test_gate_staleness_fails_on_stale_cited_version():
    register = {"loan agreement": {"version": "v26", "as_of": "2026-07-02"}}
    figs = (Figure(value="15.0M", label="Facility", source_family="loan agreement",
                   source_version="v17", as_of="2026-06-20"),)
    v = gate_staleness(_clean_doc(figures=figs, register=register))
    assert v["verdict"] == "FAIL" and "STALE" in v["detail"]


def test_gate_staleness_passes_when_current():
    register = {"loan agreement": {"version": "v26", "as_of": "2026-07-02"}}
    figs = (Figure(value="12.31M", label="Facility", source_family="loan agreement",
                   source_version="v26", as_of="2026-07-02"),)
    assert gate_staleness(_clean_doc(figures=figs, register=register))["verdict"] == "PASS"


# ── AC2: honesty gate (11a fake-live control, section-4 ledger counts) ───────
def test_gate_honesty_fails_on_fake_live_control():
    html_text = '<div class="card"><span class="gocue">\U0001f7e2 GO? approve now</span></div>'
    v = gate_honesty(_clean_doc(html=html_text, snapshot_mode="read_only"))
    assert v["verdict"] == "FAIL" and "11a" in v["detail"]


def test_gate_honesty_passes_when_cue_is_disabled():
    html_text = '<span class="gocue" aria-disabled="true">\U0001f7e2 GO? approve · planned</span>'
    assert gate_honesty(_clean_doc(html=html_text, snapshot_mode="read_only"))["verdict"] == "PASS"


def test_gate_honesty_fails_on_pasted_machine_counts():
    v = gate_honesty(_clean_doc(machine_counts_source="pasted_snapshot"))
    assert v["verdict"] == "FAIL" and "section-4" in v["detail"]


# ── AC1 (mechanism): fact-set round-trip is byte-normalized ──────────────────
def test_ac1_figures_round_trip():
    facts = facts_from_ticket(_clean_ticket())
    contract = resolve_content_contract(_clean_ticket())
    html_text = render_html(facts, contract)
    assert extract_figures(html_text) == [f.value for f in facts.figures]


def test_ac1_sections_round_trip():
    facts = facts_from_ticket(_clean_ticket())
    contract = resolve_content_contract(_clean_ticket())
    html_text = render_html(facts, contract)
    assert extract_sections(html_text) == [sid for sid, _ in contract["sections"]]


def test_ac1_receipts_round_trip():
    facts = facts_from_ticket(_clean_ticket())
    contract = resolve_content_contract(_clean_ticket())
    html_text = render_html(facts, contract)
    assert extract_receipts(html_text) == [r.ref for r in facts.receipts]


def test_ac1_page_version_is_max_not_first():
    # The build-log lists every historical Page vN; the current version must be
    # the authoritative stamp (max), never a first-match.
    facts = facts_from_ticket(_clean_ticket(page_version=15, version_history=[13, 14, 15]))
    contract = resolve_content_contract(_clean_ticket())
    html_text = render_html(facts, contract)
    assert extract_page_version(html_text) == 15


@pytest.mark.skipif(not os.path.exists(_VAULT_FIXTURE), reason="baker-vault checkout not beside repo")
def test_ac1_grounded_on_real_v1_fixture_receipts_survive():
    # Non-tautological grounding: every receipt derived from the REAL on-disk v1
    # packet survives byte-normalized into the render (the engine drops nothing).
    ticket = json.load(open(_VAULT_FIXTURE))
    ticket["page_version"] = 15
    facts = facts_from_ticket(ticket)
    r = render_ticket(ticket)
    rendered = set(extract_receipts(r["html"]))
    for rcpt in facts.receipts:
        assert rcpt.ref in rendered, f"receipt dropped from render: {rcpt.ref}"


# ── AC7: per-render context isolation (spec v1.1(b)) ─────────────────────────
def _matter_ticket(slug: str, secret_figure: str) -> dict:
    return _clean_ticket(
        project_code=f"{slug.upper()}-001",
        flight_name=f"{slug} flight",
        matter_slug=slug,
        business_outcome=f"Advance the {slug} matter.",
        figures=[{"value": secret_figure, "label": f"{slug} figure",
                  "source_family": "doc", "source_version": "v1", "as_of": "2026-07-08"}],
        receipts=[{"ref": f"#{slug}-9999", "detail": f"{slug} receipt"}],
    )


def test_ac7_no_cross_contamination_between_matters():
    a = _matter_ticket("alpha", "111.1M")
    b = _matter_ticket("bravo", "222.2M")
    ra = render_ticket(a)
    rb = render_ticket(b)
    # matter-A's unique figure + receipt must NOT appear in matter-B's render.
    assert "111.1M" not in rb["html"]
    assert "#alpha-9999" not in rb["html"]
    assert "alpha" not in rb["html"]
    # and vice-versa, in the same drain run.
    assert "222.2M" not in ra["html"]
    assert "bravo" not in ra["html"]


def test_ac7_engine_is_stateless_same_input_same_output():
    a = _matter_ticket("alpha", "111.1M")
    # interleave a different matter between two identical renders.
    first = render_ticket(a)["html"]
    render_ticket(_matter_ticket("bravo", "222.2M"))
    second = render_ticket(a)["html"]
    assert first == second


# ── contract resolution (spec v1.1(a): flight's OWN contract, no universal schema)
def test_v1_1a_flight_can_extend_section_set():
    contract = resolve_content_contract(_clean_ticket(content_contract={
        "id": "BB-AUK-001 own contract",
        "sections": [{"id": "v0", "label": "Overview"}, {"id": "v11", "label": "Balgerstrasse"}],
    }))
    ids = [sid for sid, _ in contract["sections"]]
    assert ids == ["v0", "v11"]
    assert contract["id"] == "BB-AUK-001 own contract"


def test_v1_1a_default_contract_when_none_supplied():
    contract = resolve_content_contract(_clean_ticket())
    assert "base" in contract["id"]
    assert ("v0", "Overview") in contract["sections"]


# ── bounce path (FORM-only lane: malformed packet goes back to the desk) ─────
def test_malformed_packet_bounces():
    r = render_ticket({"flight_name": "no code"})
    assert r["status"] == "bounce"
    assert "project_code" in r["bounce_reason"]
    assert r["cost"]["usd"] == 0.0
