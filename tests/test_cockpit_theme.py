"""LAB_UNIFY_THEME_COCKPIT_EXTENSION_1 — cockpit follows the /v2 light theme +
the duplicate top-right #conn health line is removed (folded into #sync-note).

DB-free file-content contracts (no browser needed; the live re-theme + offline
signal are browser-verified per the brief). Dark stays the default; light is
opt-in via the shared `labTheme` localStorage key + a pre-paint bootstrap.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "scripts" / "cockpit_static"
CSS = (BASE / "cockpit.css").read_text()
HTML = (BASE / "index.html").read_text()
JS = (BASE / "cockpit.js").read_text()

BOOTSTRAP_MARKER = 'localStorage.getItem("labTheme")'
LIGHT_MARKER = 'html[data-theme="light"]'


def test_css_defines_light_palette():
    assert LIGHT_MARKER in CSS, "cockpit.css missing html[data-theme=light] override"
    # The light block redefines the core tokens (1:1 with :root).
    for tok in ("--bg:", "--panel:", "--text:", "--border:", "--st-green:", "--danger:"):
        assert CSS.count(tok) >= 2, f"light override must redefine {tok}"
    # The legacy in-page tab bar is gone; theme tokens still cover the shell.
    assert "--header-bg" not in CSS
    assert "cockpit-header" not in CSS and "cockpit-header" not in HTML


def test_html_bootstrap_before_paint_and_cache_busted():
    assert BOOTSTRAP_MARKER in HTML, "pre-paint theme bootstrap missing from cockpit"
    assert HTML.index(BOOTSTRAP_MARKER) < HTML.index("cockpit.css?v="), (
        "theme bootstrap must run before the stylesheet"
    )
    assert "cockpit.css?v=9" in HTML, "cockpit.css cache-bust not bumped"
    assert "cockpit.js?v=9" in HTML, "cockpit.js cache-bust not bumped"


def test_js_live_follows_theme():
    assert 'addEventListener("storage"' in JS, "cockpit must live-follow the shell theme"
    assert "labTheme" in JS
    assert 'data-theme' in JS


def test_conn_removed_and_health_migrated_to_sync_note():
    # The duplicate top-right #conn element + its render path are gone.
    assert 'id="conn"' not in HTML, "top-right #conn element must be removed"
    assert 'getElementById("conn")' not in JS, "#conn render path must be removed"
    assert "connEl" not in JS, "no dangling connEl reference"
    # The single health line now renders into #sync-note, and keeps the red
    # feed-dead state (offline signal must survive the #conn removal).
    assert "summary-status feed-dead" in JS, "feed-offline state must migrate to sync-note"
    assert ".summary-status.feed-dead" in CSS, "feed-dead red state missing from CSS"
    assert '" with terminal / " + health.total + " seats"' in JS, "live count must survive"


def test_light_mode_error_toast_is_legible():
    # #toast.err hardcodes a pale red (readable on the dark toast, unreadable on
    # the white light-mode panel) — light mode must override it to a dark red.
    assert 'html[data-theme="light"] #toast.err' in CSS, (
        "error toast needs a light-mode color override for contrast"
    )


def test_dark_is_default_no_forced_attr():
    assert '<html lang="en" data-theme' not in HTML
    assert "<html data-theme" not in HTML
