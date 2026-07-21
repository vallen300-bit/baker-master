"""COCKPIT_OPEN_NUDGE_SPLIT_1 — opening a terminal is inspection, not a wake."""
import re
from pathlib import Path


JS = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cockpit_static"
    / "cockpit.js"
).read_text()


def _open_term_body() -> str:
    match = re.search(
        r"  function openTerm\(slug, name\) \{(?P<body>.*?)\n  \}\n\n  function closeTerm",
        JS,
        flags=re.S,
    )
    assert match, "openTerm() body not found"
    return match.group("body")


def test_opening_terminal_does_not_auto_nudge():
    body = _open_term_body()
    assert "nudgeSeat(" not in body
    assert "/api/sessions/" not in body


def test_drawer_nudge_button_remains_the_explicit_wake_path():
    assert (
        'if (termNudge) termNudge.addEventListener("click", () => '
        "{ if (openSlug) nudgeSeat(openSlug, openName); });"
    ) in JS
