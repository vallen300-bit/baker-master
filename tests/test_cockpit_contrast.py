"""LAB_COCKPIT_REDESIGN_1 — deterministic WCAG AA contrast guard for cockpit.css.

codex-arch #12246 blocker 1: small text roles (down-state text, APP/SERVICE kind,
plate counts) rendered below 4.5:1. This test parses the committed cockpit.css,
resolves the color tokens, and asserts every small-text role clears AA (>=4.5:1)
against the fill it sits on. No browser needed — pure string + math, CI-safe.
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent
       / "scripts" / "cockpit_static" / "cockpit.css").read_text()

# Fills a small-text role can sit on (darkest case drives the assertion).
CARD_BG = "#1c2330"       # terminal card
APP_BG = "#12161f"        # recessed app/service/cowork card
DOWN_BG = "#171b24"       # down-state card fill
PLATE_DARKEST = "#0b0f16"  # grade-0, the darkest plate ladder step
AA = 4.5


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexs):
    h = hexs.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _root_var(name):
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert m, f"--{name} not found in :root"
    return m.group(1)


def _rule_color(selector):
    """Resolve the `color:` of a CSS rule, following one var(--x) indirection."""
    pat = re.escape(selector) + r"\s*\{[^}]*?color:\s*([^;]+);"
    m = re.search(pat, CSS)
    assert m, f"no color for {selector!r}"
    val = m.group(1).strip()
    mv = re.match(r"var\(--([a-z-]+)\)", val)
    return _root_var(mv.group(1)) if mv else val


@pytest.fixture(scope="module")
def tokens():
    return {"text": _root_var("text"), "muted": _root_var("muted")}


def test_muted_and_text_pass_aa_on_all_fills(tokens):
    for bg in (CARD_BG, APP_BG, DOWN_BG):
        assert contrast(tokens["text"], bg) >= AA, ("text", bg)
        assert contrast(tokens["muted"], bg) >= AA, ("muted", bg)


def test_plate_count_passes_aa_on_darkest_plate():
    count = _rule_color(".plate > h2 .count")
    assert contrast(count, PLATE_DARKEST) >= AA, (count, PLATE_DARKEST)


def test_app_kind_marker_passes_aa_on_recessed_fill():
    kind = _rule_color(".card.app .kind")
    assert contrast(kind, APP_BG) >= AA, (kind, APP_BG)


def test_down_state_does_not_dim_text_below_aa():
    """Down cards must signal via chrome, not by dropping text opacity (which
    halved contrast to ~3.05:1). No text role may be opacity-dimmed."""
    for role in (".card.down .name", ".card.down .slug",
                 ".card.down .state", ".card.down .top"):
        assert role not in CSS, f"{role} re-introduces a text opacity dim"
