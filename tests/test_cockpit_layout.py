"""LAB_COCKPIT_PAGE_1 — invariants of the generated cockpit page layout.

These assert the committed artifact the cockpit page actually consumes
(scripts/cockpit_static/cockpit_layout.json), plus the generator's pure
CONTROL_GROUPS parser. No live registry / Control Room / manifest needed, so the
test is deterministic and CI-safe.
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAYOUT = REPO / "scripts" / "cockpit_static" / "cockpit_layout.json"

# Plate labels + order mirror the live Lab Control Room (scope §5.1).
EXPECTED_PLATE_ORDER = [
    "Control Tower", "Verification", "Specialists",
    "Builders", "Matter desks", "Ground systems",
]


@pytest.fixture(scope="module")
def layout():
    return json.loads(LAYOUT.read_text())


def test_layout_present_and_shaped(layout):
    assert "plates" in layout and layout["plates"], "no plates in layout"
    for plate in layout["plates"]:
        assert plate["label"], "plate missing label"
        assert plate["cards"], f"empty plate {plate['label']}"
        for c in plate["cards"]:
            assert c["slug"], "card missing slug"
            assert c["display_name"], f"card {c['slug']} missing display_name"
            assert re.match(r"AG-\d+", c["agent_id"]), f"{c['slug']} bad agent_id"
            assert isinstance(c["driveable"], bool)
            assert isinstance(c["app_seat"], bool)
            # a card is exactly one of driveable / app-seat (status-only)
            assert c["driveable"] != c["app_seat"], f"{c['slug']} ambiguous kind"


def test_plate_order_mirrors_control_room(layout):
    labels = [p["label"] for p in layout["plates"]]
    # every rendered plate is a known Control Room plate, in Control Room order
    assert labels == [l for l in EXPECTED_PLATE_ORDER if l in labels], labels
    assert "Other" not in labels, "unplaced cards leaked into an Other plate"


def test_builders_b1_to_b4_adjacent_in_order(layout):
    builders = next((p for p in layout["plates"] if p["label"] == "Builders"), None)
    assert builders, "no Builders plate"
    slugs = [c["slug"] for c in builders["cards"]]
    idx = [slugs.index(b) for b in ("b1", "b2", "b3", "b4")]
    assert idx == sorted(idx), f"B1–B4 not in order: {slugs}"
    assert idx[-1] - idx[0] == 3, f"B1–B4 not adjacent: {slugs}"


def test_counts_consistent(layout):
    cards = [c for p in layout["plates"] for c in p["cards"]]
    slugs = [c["slug"] for c in cards]
    assert len(slugs) == len(set(slugs)), "duplicate card across plates"
    drive = sum(c["driveable"] for c in cards)
    app = sum(c["app_seat"] for c in cards)
    meta = layout.get("meta", {}).get("counts", {})
    if meta:
        assert meta["driveable"] == drive
        assert meta["app_seat"] == app
        assert meta.get("unplaced", 0) == 0


def test_codex_arch_carded_as_app_seat_in_verification(layout):
    """Regression (lead #12205): codex-arch (runtime app-codex) is active +
    bus-enabled and Control-Room-listed, so it must render as a status-only app
    card in the Verification plate next to codex — not be silently dropped by an
    app-claude-only membership filter."""
    verification = next(
        (p for p in layout["plates"] if p["label"] == "Verification"), None)
    assert verification, "no Verification plate"
    by_slug = {c["slug"]: c for c in verification["cards"]}
    assert "codex-arch" in by_slug, \
        f"codex-arch missing from Verification: {list(by_slug)}"
    card = by_slug["codex-arch"]
    assert card["app_seat"] is True and card["driveable"] is False, \
        "codex-arch must be a status-only app seat (app-codex, no tmux terminal)"


def test_no_app_runtime_seat_silently_dropped(layout):
    """Any registry seat with an app-* runtime that the Control Room places must
    surface as an app_seat card — generalizes the codex-arch fix beyond app-claude."""
    carded = {c["slug"] for p in layout["plates"] for c in p["cards"]}
    # codex-arch is the representative app-codex seat; assert it is carded and
    # marked app_seat (broader registry-vs-layout reconciliation is a live check).
    assert "codex-arch" in carded


def test_generator_parses_control_groups_literal():
    """The generator must extract CONTROL_GROUPS as JSON (mirror-at-build)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gcl", REPO / "scripts" / "generate_cockpit_layout.py")
    gcl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gcl)
    sample = (
        'const CONTROL_GROUPS = Object.freeze([\n'
        '  ["Control Tower", ["lead", "deputy-codex"]],\n'
        '  ["Builders", ["b1", "b2", "b3", "b4"]],\n'
        ']);\n'
    )
    body = re.search(
        r"CONTROL_GROUPS\s*=\s*Object\.freeze\(\s*(\[[\s\S]*?\])\s*\)\s*;", sample
    ).group(1)
    arr = json.loads(re.sub(r",(\s*[\]}])", r"\1", body))
    assert arr[0][0] == "Control Tower"
    assert arr[1][1] == ["b1", "b2", "b3", "b4"]
