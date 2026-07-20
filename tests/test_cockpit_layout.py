"""LAB_COCKPIT_REDESIGN_1 — invariants of the generated cockpit page layout.

These assert the committed artifact the cockpit page actually consumes
(scripts/cockpit_static/cockpit_layout.json), plus the generator's pure
row-band order helper. No live registry / contract / manifest needed for the
artifact assertions, so the test is deterministic and CI-safe.
"""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAYOUT = REPO / "scripts" / "cockpit_static" / "cockpit_layout.json"

# Plate labels + order come from the Director layout contract (D1).
EXPECTED_PLATE_ORDER = [
    "Control Tower & VERIFICATION",
    "ENGINEERING , TECHNICAL & STAFF MANAGEMENT",
    "PILOTS & PILOT TEAMS",
    "FLIGHTS SUPPORT & DOMAIN SPECIFIC",
    "LEGAL ,FINANCIAL , PR, MARKETING & COMMUNICATIONS",
    "INTERNS",
]


@pytest.fixture(scope="module")
def layout():
    return json.loads(LAYOUT.read_text())


def _find(layout, slug):
    for p in layout["plates"]:
        for c in p["cards"]:
            if c["slug"] == slug:
                return p["label"], c
    return None, None


def test_layout_present_and_shaped(layout):
    assert "plates" in layout and layout["plates"], "no plates in layout"
    for plate in layout["plates"]:
        assert plate["label"], "plate missing label"
        assert plate["cards"], f"empty plate {plate['label']}"
        for c in plate["cards"]:
            assert c["slug"], "card missing slug"
            assert c["display_name"], f"card {c['slug']} missing display_name"
            # AG pill dropped (D2) — no agent_id field is emitted.
            assert "agent_id" not in c, f"{c['slug']} still carries agent_id"
            assert isinstance(c["driveable"], bool)
            assert isinstance(c["status_only"], bool)
            # a card is exactly one of driveable / status-only
            assert c["driveable"] != c["status_only"], f"{c['slug']} ambiguous kind"
            # app_seat implies status-only (an app card is never driveable)
            if c.get("app_seat"):
                assert c["status_only"], f"{c['slug']} app_seat but driveable"


def test_plate_order_matches_contract(layout):
    labels = [p["label"] for p in layout["plates"]]
    assert labels == EXPECTED_PLATE_ORDER, labels
    assert "Unassigned" not in labels, "active seats missing from the contract"


def test_builders_b1_to_b4_adjacent_in_order(layout):
    plate, _ = _find(layout, "b1")
    eng = next((p for p in layout["plates"] if p["label"] == plate), None)
    assert eng, "no plate containing b1"
    slugs = [c["slug"] for c in eng["cards"]]
    idx = [slugs.index(b) for b in ("b1", "b2", "b3", "b4")]
    assert idx == sorted(idx), f"B1–B4 not in order: {slugs}"
    assert idx[-1] - idx[0] == 3, f"B1–B4 not adjacent: {slugs}"


def test_counts_consistent(layout):
    cards = [c for p in layout["plates"] for c in p["cards"]]
    slugs = [c["slug"] for c in cards]
    assert len(slugs) == len(set(slugs)), "duplicate card across plates"
    drive = sum(c["driveable"] for c in cards)
    status = sum(c["status_only"] for c in cards)
    meta = layout.get("meta", {}).get("counts", {})
    if meta:
        assert meta["driveable"] == drive
        assert meta["status_only"] == status
        assert meta.get("unassigned", 0) == 0
    # Current main keeps librarian in the cockpit while deep55 is parked.
    assert len(cards) == 42, f"expected 42 cards, got {len(cards)}"


def test_contract_display_names_applied(layout):
    """Director contract names (de-Desked, mock-approved) win over registry."""
    for slug, name in (("lead", "Lead"), ("aid", "AID T"),
                       ("clerk", "Clerk Qwen"), ("cowork-ao-desk", "Cowork AO")):
        _, c = _find(layout, slug)
        assert c and c["display_name"] == name, \
            f"{slug} name {c and c['display_name']!r} != {name!r}"


def test_codex_arch_app_seat_in_control_tower(layout):
    """Regression (lead #12205): codex-arch (app-codex) is a status-only app card;
    the contract places it in the Control Tower & VERIFICATION plate."""
    plate, c = _find(layout, "codex-arch")
    assert c, "codex-arch missing"
    assert c["app_seat"] is True and c["driveable"] is False
    assert plate == "Control Tower & VERIFICATION", plate


def test_scopeadd_driveable_seats_in_interns(layout):
    """Current contract keeps librarian, clerk, and clerk-haiku as driveable
    Terminal seats; deep55 is parked from the cockpit."""
    for slug in ("clerk", "clerk-haiku"):
        plate, c = _find(layout, slug)
        assert c, f"{slug} missing"
        assert c["driveable"] is True and c["status_only"] is False, f"{slug} not driveable"
        assert plate == "INTERNS", f"{slug} in {plate}, expected INTERNS"
    assert _find(layout, "deep55") == (None, None)
    plate, c = _find(layout, "librarian")
    assert c and c["driveable"] is True and c["status_only"] is False
    assert plate == "FLIGHTS SUPPORT & DOMAIN SPECIFIC"


def test_cortex_status_only_service_card(layout):
    """cortex (runtime service) → status-only card badged 'service'."""
    _, c = _find(layout, "cortex")
    assert c, "cortex missing"
    assert c["status_only"] is True and c["driveable"] is False
    assert c["app_seat"] is False and c["badge"] == "service" and c["kind"] == "SERVICE"


def test_every_card_has_kind_and_shape(layout):
    for p in layout["plates"]:
        for c in p["cards"]:
            assert c["kind"], f"{c['slug']} missing kind"
            assert "badge" in c, f"{c['slug']} missing badge key"
            if c["driveable"]:
                assert c["badge"] is None, f"{c['slug']} driveable but badged"


def _load_generator():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gcl", REPO / "scripts" / "generate_cockpit_layout.py")
    gcl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gcl)
    return gcl


def test_generator_orders_by_row_band():
    """_order_in_plate groups a visual row (y within ROW_BAND_PX) left→right by x,
    stacks rows top→bottom — the mock-v3 export rule."""
    gcl = _load_generator()
    cards = [
        {"slug": "d", "x": 260, "y": 77},   # second row (cowork)
        {"slug": "a", "x": 11, "y": 2},     # first row
        {"slug": "c", "x": 387, "y": 0},    # first row
        {"slug": "b", "x": 137, "y": 0},    # first row
        {"slug": "e", "x": 138, "y": 76},   # second row
    ]
    ordered = [c["slug"] for c in gcl._order_in_plate(cards)]
    assert ordered == ["a", "b", "c", "e", "d"], ordered
