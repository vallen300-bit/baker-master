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
APP_BG = "#0c1018"        # recessed app/service/cowork card
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


# ---- composited semantic-overlay sweep (codex-arch #12272) -------------------
# The age text sits on a glance-tinted card (needs_go/NEW/working set a
# semi-transparent background that composites over the plate grade behind the
# card). The flat-fill checks above miss that; this sweeps age-role x overlay x
# every plate grade on the real composited background.

def _rgb(hexs):
    h = hexs.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(round(c) for c in rgb)


def _composite(base_hex, r, g, b, a):
    base = _rgb(base_hex)
    ov = (r, g, b)
    return _hex(tuple(base[i] * (1 - a) + ov[i] * a for i in range(3)))


def _grade_bgs():
    out = []
    for n in range(6):
        m = re.search(rf"\.plate\.grade-{n}\s*\{{[^}}]*background:\s*(#[0-9a-fA-F]{{6}})", CSS)
        assert m, f"grade-{n} background not found"
        out.append(m.group(1))
    return out


def _glance_tint(selector):
    m = re.search(re.escape(selector) + r"\s*\{[^}]*background:\s*rgba\(([^)]+)\)", CSS)
    assert m, f"no rgba background for {selector}"
    parts = [p.strip() for p in m.group(1).split(",")]
    r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
    return (r, g, b, float(parts[3]))


def _age_color(cls):
    # .card .age.hot / .age.warn / .card .age  (resolve var())
    sel = ".card .age.hot" if cls == "hot" else \
          ".card .age.warn" if cls == "warn" else ".card .age"
    return _rule_color(sel)


def test_age_text_passes_aa_composited_over_every_glance_tint_and_grade():
    grades = _grade_bgs()
    overlays = {
        "needs_go": _glance_tint(".card.glance-needs-go"),
        "NEW": _glance_tint(".card.glance-new"),
        "working": _glance_tint(".card.glance-working"),
    }
    failures = []
    for role in ("hot", "warn", "base"):
        fg = _age_color(role)
        # no-overlay case: age on the plain card fill
        if contrast(fg, CARD_BG) < AA:
            failures.append((role, "none", CARD_BG, round(contrast(fg, CARD_BG), 3)))
        for oname, (r, g, b, a) in overlays.items():
            for grade in grades:
                bg = _composite(grade, r, g, b, a)
                c = contrast(fg, bg)
                if c < AA:
                    failures.append((role, oname, grade, round(c, 3)))
    assert not failures, f"age text below {AA}:1 composited: {failures}"


def test_down_state_does_not_dim_text_below_aa():
    """Down cards must signal via chrome, not by dropping text opacity (which
    halved contrast to ~3.05:1). No text role may be opacity-dimmed."""
    for role in (".card.down .name", ".card.down .slug",
                 ".card.down .state", ".card.down .top"):
        assert role not in CSS, f"{role} re-introduces a text opacity dim"
