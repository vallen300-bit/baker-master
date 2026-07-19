"""COCKPIT_UI_POLISH_1 — deterministic WCAG AA contrast guard for cockpit.css.

Preserves the codex-arch #12246 contrast intent through the thin-row redesign
(Director #12800): every small-text role must clear AA (>=4.5:1) against the fill
it sits on. Rows sit on the page background (--bg) or its hover fill, tinted by
the glance overlays. No browser needed — pure string + math, CI-safe.
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent
       / "scripts" / "cockpit_static" / "cockpit.css").read_text()

# Fills a small-text role can sit on (darkest realistic case drives assertions).
PAGE_BG = "#0d1117"       # --bg: the row's own (transparent) background
ROW_HOVER = "#1a2130"     # .row:hover fill
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


def test_muted_and_text_pass_aa_on_row_fills(tokens):
    for bg in (PAGE_BG, ROW_HOVER):
        assert contrast(tokens["text"], bg) >= AA, ("text", bg)
        assert contrast(tokens["muted"], bg) >= AA, ("muted", bg)


def test_plate_count_passes_aa():
    count = _rule_color(".plate > h2 .count")
    assert contrast(count, PAGE_BG) >= AA, (count, PAGE_BG)


def test_row_kind_badge_passes_aa():
    """The service/headless kind badge (.r-kind) must clear AA on the page fill."""
    kind = _rule_color(".r-kind")
    assert contrast(kind, PAGE_BG) >= AA, (kind, PAGE_BG)


# ---- composited semantic-overlay sweep --------------------------------------
# The age text sits on a glance-tinted row (needs_go/amber set a semi-transparent
# background that composites over the page fill behind the row). The flat-fill
# checks above miss that; this sweeps age-role x overlay on the composited bg.

def _rgb(hexs):
    h = hexs.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(round(c) for c in rgb)


def _composite(base_hex, r, g, b, a):
    base = _rgb(base_hex)
    ov = (r, g, b)
    return _hex(tuple(base[i] * (1 - a) + ov[i] * a for i in range(3)))


def _glance_tint(selector):
    m = re.search(re.escape(selector) + r"\s*\{[^}]*background:\s*rgba\(([^)]+)\)", CSS)
    assert m, f"no rgba background for {selector}"
    parts = [p.strip() for p in m.group(1).split(",")]
    r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
    return (r, g, b, float(parts[3]))


def _age_color(cls):
    sel = ".age.hot" if cls == "hot" else ".age.warn" if cls == "warn" else ".age"
    return _rule_color(sel)


def test_age_text_passes_aa_composited_over_glance_tints():
    # COCKPIT_REVAMP_COLORS_1: the FINAL 6-state palette replaced glance-needs-go/
    # glance-amber. Sweep every state that sets a semi-transparent row tint so the
    # age text stays AA-legible composited over each one.
    overlays = {
        "go": _glance_tint(".row.st-go"),
        "unread": _glance_tint(".row.st-unread"),
        "unread_old": _glance_tint(".row.st-unread-old"),
        "offline": _glance_tint(".row.st-offline"),
    }
    failures = []
    for role in ("hot", "warn", "base"):
        fg = _age_color(role)
        # no-overlay case: age on the plain page fill and on hover.
        for bg in (PAGE_BG, ROW_HOVER):
            if contrast(fg, bg) < AA:
                failures.append((role, "none", bg, round(contrast(fg, bg), 3)))
        for oname, (r, g, b, a) in overlays.items():
            bg = _composite(PAGE_BG, r, g, b, a)
            c = contrast(fg, bg)
            if c < AA:
                failures.append((role, oname, bg, round(c, 3)))
    assert not failures, f"age text below {AA}:1 composited: {failures}"


def test_down_state_does_not_dim_text_below_aa():
    """Down rows must signal via the dot/chip, not by dropping text opacity
    (which would halve contrast). No row text role may be opacity-dimmed."""
    for role in (".row.down .r-name", ".row.down .r-slug", ".row.down .r-id"):
        assert role not in CSS, f"{role} re-introduces a text opacity dim"
