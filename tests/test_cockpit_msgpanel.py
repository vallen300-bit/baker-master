"""COCKPIT_UI_POLISH_1 D9 — App-resident bus-message panel guard.

CI has no browser, so this parses cockpit.js/index.html/css and locks the D9
wiring that makes the panel + flash + zero-dead-clicks impossible to regress. The
rendered behaviour itself was verified live (Chrome) at build time.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "scripts" / "cockpit_static"
JS = (_ROOT / "cockpit.js").read_text()
GLANCE = (_ROOT / "glance_state.js").read_text()
HTML = (_ROOT / "index.html").read_text()
CSS = re.sub(r"/\*.*?\*/", "", (_ROOT / "cockpit.css").read_text(), flags=re.S)


def test_panel_markup_present():
    assert 'id="msgpanel"' in HTML and 'id="msg-body"' in HTML
    assert 'id="msg-copy"' in HTML and 'id="msg-x"' in HTML


def test_panel_binds_same_three_sections():
    # Same section shape as the Lab "Production & Lab" component.
    assert "Unacknowledged (" in JS
    assert "Last message" in JS
    assert "Acknowledged" in JS
    # Bound to the same per-agent bus fields surfaced by the controller.
    # COCKPIT_DRAWER_COPY_BUTTON_FIX_1: the unacked binding now flows through the
    # shared reconcileUnacked() (glance_state.js) so the panel render and the Copy
    # buttons draw one source; last_message/acked_count stay bound in cockpit.js.
    assert "renderedUnackedRows" in JS and "reconcileUnacked" in JS
    assert "unacked_messages" in GLANCE, "reconciler must bind the unacked_messages field"
    assert "last_message" in JS and "acked_count" in JS


def test_app_cards_open_panel_zero_dead_clicks():
    # Driveable -> terminal; status_only -> bus panel. Every card wires a click.
    assert "openMsgPanel(meta.slug, name)" in JS, "App cards must open the bus panel"
    assert "openTerm(meta.slug, name)" in JS, "tmux cards must still open the terminal"
    assert 'c.addEventListener("click", open)' in JS, "every card must be clickable"


def test_flash_on_new_message():
    assert "computeFlash" in JS, "flash-on-new-message tracker missing"
    assert "flashSlugs" in JS
    assert ".row.flash" in CSS and "row-flash" in CSS, "flash animation missing"


def test_panel_refreshes_live_and_closes():
    assert "if (openMsgSlug) renderMsgSummary(openMsgSlug)" in JS, "panel must live-refresh on poll"
    assert "closeMsgPanel" in JS


def test_panel_lazily_merges_authenticated_body_previews():
    assert "/api/messages/" in JS
    assert "mergeMessageDetails" in JS
    assert "messageDetailFor" in JS
    assert "detail.body_preview" in JS
    assert "text: detail.body_preview" in JS
    assert ".hpreview" in CSS


def test_summary_counts_only_driveable_terminal_attention():
    # Realigned to the ratified COCKPIT_REVAMP merge (b7007c84): the oversized digit
    # block (with its needs_go/ttyd-down "Attention" count) was removed (spec item 6),
    # and "driveable" was relabeled "with terminal" in the one green header line. The
    # surviving intent — the header counts driveable terminals from the layout — is
    # kept. (Merge-integration fix: the pre-merge assertions referenced removed code.)
    assert "const driveable = layout" in JS
    assert "card.driveable).length" in JS
    assert '" with terminal / " + total + " seats"' in JS
