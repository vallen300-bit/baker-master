"""COCKPIT_UI_POLISH_1 — thin-row geometry guard (Director #12800).

Supersedes the fixed-height CARD contract (LAB_COCKPIT_REDESIGN_1 #12246/#12262/
#12264): the Director replaced the landscape cards with thin Lab-list rows so the
whole fleet fits one screen. This locks the row invariants that make D1/D2/D3
impossible to regress, parsed from cockpit.css/js (CI has no browser).

  D1 — one thin row per seat, a fixed 5-column grid so columns align table-style.
  D2 — the context meter renders on EVERY row (em-dash placeholder when null).
  D3 — the state control renders on EVERY row (refresh / GO / status chip).
"""
import re
from pathlib import Path

_RAW = (Path(__file__).resolve().parent.parent
        / "scripts" / "cockpit_static" / "cockpit.css").read_text()
# Strip /* comments */ so prose mentioning a property never trips a substring check.
CSS = re.sub(r"/\*.*?\*/", "", _RAW, flags=re.S)

JS = (Path(__file__).resolve().parent.parent
      / "scripts" / "cockpit_static" / "cockpit.js").read_text()
HTML = (Path(__file__).resolve().parent.parent
        / "scripts" / "cockpit_static" / "index.html").read_text()


def _row_block():
    m = re.search(r"\.row\s*\{([^}]*)\}", CSS)
    assert m, ".row rule not found"
    return m.group(1)


def test_row_is_a_fixed_column_grid():
    """D1: rows use a CSS grid with a fixed column template so every row's
    columns align across all plates (uniform Lab-list density)."""
    block = _row_block()
    assert "display: grid" in block, ".row must be a CSS grid"
    m = re.search(r"grid-template-columns:\s*([^;]+);", block)
    assert m, ".row has no grid-template-columns"
    assert m.group(1).strip() == "var(--row-columns)"
    root = re.search(r"--row-columns:\s*([^;]+);", CSS)
    assert root, "--row-columns custom property missing"
    # 5 columns: dot · identity · ctx · unread · control.
    cols = root.group(1).split()
    assert len(cols) >= 5, f".row grid needs >=5 columns, got {root.group(1)!r}"


def test_rows_are_thin_not_fixed_card_height():
    """The old uniform 102px card height is gone; desktop rows are compact so the
    whole fleet fits one 1440x900 screen."""
    block = _row_block()
    m = re.search(r"min-height:\s*(\d+)px", block)
    assert m, ".row needs a compact min-height"
    assert int(m.group(1)) <= 30, "row min-height too tall for a one-screen fleet"
    assert "height: 102px" not in CSS, "old fixed card height still present"


def test_ctx_meter_rendered_on_every_row():
    """D2: card() appends ctxCell unconditionally, and ctxCell returns a node in
    BOTH branches — a bar when numeric, an em-dash placeholder when null."""
    assert "ctxCell(meta, row)" in JS, "card() no longer appends ctxCell for every row"
    assert "function ctxCell" in JS, "ctxCell helper missing"
    # Null branch renders the em-dash placeholder; never null, never hidden.
    assert 'class: "r-ctx r-ctx-null"' in JS, "ctxCell null branch must render an em-dash placeholder"
    assert ".r-ctx-null" in CSS, ".r-ctx-null placeholder style missing"


def test_stale_context_meter_is_dimmed_and_shows_age():
    """D2: stale last-known context leads with age and uses a distinct treatment."""
    assert "ctx-stale" in JS, "stale context class missing from ctxCell"
    assert "context_age_sec" in JS, "stale context age is not rendered"
    assert ".r-ctx.ctx-stale" in CSS, "stale context style missing"
    assert 'age + " old · "' in JS, "stale label must lead with age"
    assert 'text: "?"' in JS, "long-stale context must replace the fill with ?"
    assert ".r-ctx.ctx-stale-long" in CSS, "long-stale context treatment missing"
    assert "#d2d9e1" in CSS, "dark stale label color missing"
    assert 'html[data-theme="light"] .r-ctx.ctx-stale .ctxlbl' in CSS, \
        "light stale label override missing"


def test_inbox_card_shows_age_without_count_pill():
    """Director ruling: the card face shows oldest-message age only; counts stay
    available to the behavior logic and drawer/panel surfaces."""
    assert 'class: "r-unread"' in JS
    assert "formatUnreadAge(row.oldest_unacked_age_sec || 0)" in JS
    assert 'class: "unread"' not in JS
    assert ".unread" not in CSS
    assert "row.unacked_count > 0" in JS
    assert "flashSlugs" in JS
    assert "nudgeSeat" in JS
    assert 'class: "r-unread r-unread-empty"' in JS


def test_mobile_context_meter_keeps_a_visible_bar():
    """The 320px layout must reserve room for both the stale-age label and bar."""
    m = re.search(r"@media \(max-width:\s*640px\)\s*\{(.*?)\n\}", CSS, re.S)
    assert m, "no phone media query"
    block = m.group(1)
    assert "auto 90px" in block, "mobile context cell must reserve a 90px column"
    assert "flex: 0 0 24px" in block, "mobile context bar must keep a fixed width"


def test_state_control_rendered_on_every_row():
    """D3: card() appends stateControl unconditionally, which returns an action
    group or status chip so the control column is never absent."""
    assert "stateControl(meta, row, up)" in JS, "card() no longer appends stateControl for every row"
    assert "function stateControl" in JS, "stateControl helper missing"
    assert "refreshContextButton(meta)" in JS, "context refresh action missing"
    assert 'class: "chip"' in JS, "stateControl must always fall through to a status chip"
    assert ".rbtn" in CSS and ".chip" in CSS, "row control styles (.rbtn/.chip) missing"


def test_header_and_rows_share_column_template_and_order():
    """Director pass: header and rows use one desktop template, with context
    before inbox and matching horizontal padding."""
    assert CSS.count("--row-columns:") == 1
    assert re.search(
        r"<span></span><span>Agent / identity</span><span>Context window</span>"
        r"<span>Inbox</span><span>Session</span>",
        HTML,
    )
    assert re.search(r"\.fleet-columns\s*\{[^}]*padding:\s*0 12px;", CSS, re.S)
    assert re.search(r"\.row\s*\{[^}]*padding:\s*4px 12px;", CSS, re.S)


def test_start_button_removed_but_endpoint_and_down_guard_remain():
    """Start remains a backend capability, but the Director-facing card no
    longer offers it."""
    assert 'class: "rbtn start"' not in JS
    assert '"/api/sessions/" + slug + "/start"' in JS
    assert "function doStart" in JS
    assert "start it in the terminal" in JS


def test_context_refresh_is_click_armed_and_driveable_only():
    """The /clear action is a two-step click on up driveable rows, with no
    action rendered for down or status-only rows."""
    assert 'class: "rbtn refresh-context"' in JS
    assert 'title: "Refresh context (/clear)"' in JS
    assert "CONTEXT_REFRESH_ARM_MS = 3000" in JS
    assert "refreshContext(meta.slug, ev.currentTarget)" in JS
    assert '"/api/sessions/" + slug + "/refresh_context"' in JS
    assert "if (meta.status_only || !up)" in JS
    assert ".control-actions" in CSS


def test_subtitle_slot_is_reserved_but_empty():
    assert "Every terminal, app seat, desk, and service in one scan surface." not in HTML
    assert "reserved: future header line, same font slot" in HTML


def test_phone_rows_stay_tappable():
    """Phone (Director uses iPhone Safari): rows stay >=44px tappable via a media
    query, even though desktop rows are compact."""
    m = re.search(r"@media \(max-width:\s*640px\)\s*\{(.*?)\n\}", CSS, re.S)
    assert m, "no phone media query"
    assert re.search(r"\.row\s*\{[^}]*min-height:\s*44px", m.group(1)), \
        "phone rows must be >=44px tappable"


# ---- COCKPIT_LAYOUT_REARRANGE_1 mock-v3 fidelity guards ---------------------

def test_context_fill_is_severity_gradient():
    """Mock v3 legend: the context line 'fills as context grows' green->amber->red.
    The fill must be a horizontal gradient, not a flat single-hue bar."""
    m = re.search(r"\.r-ctx\s+\.ctxfill\s*\{([^}]*)\}", CSS)
    assert m, ".r-ctx .ctxfill rule not found"
    body = m.group(1)
    assert "linear-gradient" in body, "context fill must be a green->amber->red gradient"
    # green low, red high — the two ends of the severity ramp must be present.
    assert "#3fb950" in body and "#f85149" in body, \
        "context gradient must run from green (#3fb950) to red (#f85149)"


def test_context_gradient_is_anchored_to_value_not_width():
    """SEVERITY-BY-VALUE (lead ruling #12977): the gradient must be anchored to the
    full track so its colour reads the true context_pct, NOT stretched across the
    fill's own width (which paints a red tip on a low-context row — misleading
    telemetry). The fill scales the gradient box to one full track via
    --ctx-track-scale and paints it once from the left."""
    m = re.search(r"\.r-ctx\s+\.ctxfill\s*\{([^}]*)\}", CSS)
    assert m, ".r-ctx .ctxfill rule not found"
    body = m.group(1)
    # Gradient box scaled to a full track (not the default 100% = fill's own width).
    assert "--ctx-track-scale" in body and "background-size" in body, \
        "ctxfill must scale the gradient to the full track via --ctx-track-scale"
    # Painted once, from the left, so the reveal window == 0..pct of the true ramp.
    assert "no-repeat" in body, "ctxfill gradient must not tile (background-repeat: no-repeat)"
    assert re.search(r"background-position:\s*left", body), \
        "ctxfill gradient must anchor at the track's left edge"
    # JS must supply the per-row scale = (10000/pct)% so colour == severity(pct).
    assert "--ctx-track-scale" in JS and "10000" in JS, \
        "cockpit.js must set --ctx-track-scale = (10000/pct)% on each ctxfill"


def test_app_rows_are_recessed():
    """Mock v3: App/Cowork (status-only) seats sit recessed with an inner shadow
    (".card.app" inset treatment) so they read distinct from driveable rows."""
    m = re.search(r"\.row\.app\s*\{([^}]*)\}", CSS)
    assert m, ".row.app rule not found"
    body = m.group(1)
    assert re.search(r"box-shadow:\s*inset", body), \
        ".row.app must carry an inset (recessed) box-shadow"
