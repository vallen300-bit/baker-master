"""COCKPIT_SLUG_ONLY_CARDS_1 — the cockpit cards render the SLUG, never the display
name (Director: "the name is for me, not for agents").

CI has no browser, so this parses cockpit.js/cockpit.css and locks the slug-only
identity wiring: the slug renders in the name's type slot (.r-name), the separate
small .r-slug line is gone, and no display_name string reaches any rendered surface
(card face, drawer header, panel title, control tooltips). Ruling #13307 geometry is
untouched — this amends the identity text only. Rendered behaviour verified live at
build time.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "scripts" / "cockpit_static"
JS = (_ROOT / "cockpit.js").read_text()
CSS_RAW = (_ROOT / "cockpit.css").read_text()
CSS = re.sub(r"/\*.*?\*/", "", CSS_RAW, flags=re.S)  # strip comments before selector checks


def test_card_renders_slug_in_the_name_slot():
    # The slug is rendered in the .r-name element (name's 13px/500 + per-state color).
    assert 'class: "r-name", text: meta.slug' in JS


def test_no_separate_slug_line_rendered():
    # The old muted-monospace .r-slug line is dropped so the slug shows exactly once.
    assert 'class: "r-slug"' not in JS, "the duplicate .r-slug span must be removed"
    assert re.search(r"^\.r-slug\b", CSS, flags=re.M) is None, "dead .r-slug CSS rule remains"


def test_no_display_name_reaches_a_rendered_surface():
    # No card face, title, header, or tooltip may render the display name.
    assert "display_name" not in JS, "cockpit cards must never render display_name"


def test_panel_title_and_identity_are_slug_only():
    # Card-open identity is the slug; the panel title is slug-only (no "[slug]" dup).
    assert "const name = meta.slug;" in JS
    assert 'slug + " messages"' in JS
    assert '"] messages"' not in JS, "old 'name [slug] messages' title must be gone"
