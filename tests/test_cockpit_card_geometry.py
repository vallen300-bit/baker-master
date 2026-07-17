"""LAB_COCKPIT_REDESIGN_1 — card-geometry guard (codex-arch #12246/#12262).

Two rendered regressions this locks, without a browser (CI has none — the repo
tests JS via `node` for pure logic only, and node has no layout engine):

  #12246 blocker 2 — cards must be a UNIFORM fixed height (min-height let
  content-heavy terminal cards outgrow status-only cards).
  #12262 — a fixed height too short for the crowded driveable state (kind + name
  + slug + state + unread + GO = 6 rows) flex-shrank .name to 0px. Fix = every
  card child `flex-shrink:0` + the fixed height sized to the crowded state.

The faithful rendered check ("name/slug/unread/GO keep non-zero bounds in the
crowded fixture") was verified in-browser on the scratch port: natural crowded
height 134px, name 19px, slug 11px, unread 14px, GO 21px, 0 clipped. This test
is the CI-enforceable proxy: it parses cockpit.css and asserts the invariants
that make that render impossible to regress.
"""
import re
from pathlib import Path

import pytest

_RAW = (Path(__file__).resolve().parent.parent
        / "scripts" / "cockpit_static" / "cockpit.css").read_text()
# Strip /* comments */ so prose mentioning a property never trips a substring check.
CSS = re.sub(r"/\*.*?\*/", "", _RAW, flags=re.S)

# Measured natural height of the 6-row crowded driveable card (2026-07-17,
# scratch-port render). The fixed card height must be >= this so overflow:hidden
# never clips and no row is forced to shrink.
CROWDED_NATURAL_PX = 134


def _card_block():
    m = re.search(r"\.card\s*\{([^}]*)\}", CSS)
    assert m, ".card rule not found"
    return m.group(1)


def test_card_uses_fixed_height_not_min_height():
    """Uniformity (#12246 b2): a single fixed height, no min-height floor."""
    block = _card_block()
    assert re.search(r"(?<!min-)height:\s*\d+px", block), "no fixed height on .card"
    assert "min-height" not in block, "min-height re-introduced — breaks uniformity"


def test_fixed_height_covers_the_crowded_state():
    """#12262: the fixed height must fit the 6-row GO+unread state (>=134px)."""
    block = _card_block()
    m = re.search(r"(?<!min-)height:\s*(\d+)px", block)
    assert m, "no fixed height on .card"
    h = int(m.group(1))
    assert h >= CROWDED_NATURAL_PX, (
        f".card height {h}px < crowded-state {CROWDED_NATURAL_PX}px — .name will clip/collapse")


def test_card_children_do_not_flex_shrink():
    """#12262 mechanism: a fixed-height flex column must not shrink any row to 0."""
    assert re.search(r"\.card\s*>\s*\*\s*\{[^}]*flex-shrink:\s*0", CSS), \
        "missing `.card > * { flex-shrink: 0 }` — crowded .name can collapse to 0px"


def test_card_clips_overflow_for_uniformity():
    """overflow:hidden + a height that fits the crowded state = uniform, no clip."""
    assert "overflow: hidden" in _card_block(), "overflow guard missing on .card"
