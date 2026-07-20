"""COCKPIT_REVAMP_SPLIT_VIEW_SIDEBAR_1 — left-sidebar view filter + split-view shell.

Spec items 4 (true split view) + 5 (left sidebar navigation), @d5e25efa.

CI has no browser, so this locks the contract two ways:
  (1) Static inspection of the shipped static files (index.html / cockpit.js /
      cockpit.css / glance_state.js) — the structural pieces the DOM depends on.
  (2) Functional execution of the PURE `planView` view-filter through a `node -e`
      subprocess (skipped, not failed, when node is absent — the same auto-skip
      discipline the live-PG and glance-resolver tests use), so the vectors can
      never drift from the shipped logic.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "scripts" / "cockpit_static"
GLANCE = _STATIC / "glance_state.js"
JS = (_STATIC / "cockpit.js").read_text()
HTML = (_STATIC / "index.html").read_text()
CSS = (_STATIC / "cockpit.css").read_text()
GLANCE_SRC = GLANCE.read_text()
NODE = shutil.which("node")


# ── Layer 1 — static structure ──────────────────────────────────────────────
def test_pure_view_filter_exported():
    assert "function planView(" in GLANCE_SRC, "planView pure function missing"
    assert "ATTENTION_CLASSES" in GLANCE_SRC, "attention-class set missing"
    assert "window.planView = planView" in GLANCE_SRC, "planView browser-global export missing"
    assert "planView };" in GLANCE_SRC, "planView CommonJS export missing"


def test_split_view_shell_replaces_modal():
    # Three-column shell present; the #veil blur modal path is fully removed.
    assert 'id="appShell"' in HTML and "app-shell" in HTML, "app shell markup missing"
    assert 'id="sidebar"' in HTML, "sidebar container missing"
    assert 'class="term-pane"' in HTML, "terminal must be a pane, not a modal"
    assert 'id="veil"' not in HTML, "#veil modal markup must be gone"
    assert "veilEl" not in JS, "#veil references must be gone from cockpit.js"
    assert "getElementById(\"veil\")" not in JS
    assert re.search(r"^#veil\b", CSS, flags=re.M) is None, "dead #veil CSS remains"
    # Opening a seat toggles the pane column, not a blur overlay.
    assert 'appShellEl.classList.add("pane-open")' in JS
    assert ".app-shell.pane-open" in CSS


def test_sidebar_eight_entries_in_order():
    m = re.search(r"const NAV_ORDER = \[([^\]]+)\]", JS)
    assert m, "NAV_ORDER const missing"
    entries = [e.strip().strip('"') for e in m.group(1).split(",") if e.strip()]
    assert entries == ["ACTIVE", "ALL", "Pilots", "Control Tower", "Engineering",
                       "Support", "Legal/Finance", "Interns"], entries


def test_plate_to_nav_mapping_is_one_const_fail_soft():
    assert "const PLATE_TO_NAV = {" in JS, "single plate→nav mapping const missing"
    for plate in ("PILOTS & PILOT TEAMS", "Control Tower & VERIFICATION",
                  "ENGINEERING , TECHNICAL & STAFF MANAGEMENT",
                  "FLIGHTS SUPPORT & DOMAIN SPECIFIC",
                  "LEGAL ,FINANCIAL , PR, MARKETING & COMMUNICATIONS", "INTERNS"):
        assert plate in JS, f"plate label {plate!r} not mapped"
    # fail-soft: unknown plate falls back to its raw label.
    assert "PLATE_TO_NAV[plate.label] || plate.label" in JS


def test_view_persisted_only_cockpit_view_key():
    assert 'VIEW_KEY = "cockpit.view"' in JS, "persisted view key must be cockpit.view"
    assert "localStorage.setItem(VIEW_KEY" in JS and "localStorage.getItem(VIEW_KEY" in JS
    # No other new localStorage keys introduced (quality checkpoint 4).
    keys = set(re.findall(r'localStorage\.(?:get|set)Item\("([^"]+)"', JS))
    assert keys <= {"cockpit.notifyMuted"}, f"unexpected localStorage string keys: {keys}"


def test_render_routes_through_pure_planview():
    assert "window.planView(navGroups()" in JS, "render must use the pure planView"
    assert "function navGroups(" in JS and "function cardStateClass(" in JS
    assert "updateSidebar(plan.badges)" in JS, "sidebar badges must come from planView"


def test_narrow_sidebar_collapses_to_icons():
    assert ".nav-abbr" in CSS and ".nav-label" in CSS
    assert ":has(.sidebar:hover)" in CSS, "hover-expand must be CSS-only (:has)"
    # slug-only invariant preserved (COCKPIT_SLUG_ONLY_CARDS_1): no display_name.
    assert "display_name" not in JS


# ── Layer 2 — functional planView vectors via node ──────────────────────────
def _run_node(body: str):
    script = f"const g = require({json.dumps(str(GLANCE))});\n{body}"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         timeout=20, check=True)
    return json.loads(out.stdout)


_GROUPS = (
    '[{nav:"Pilots",label:"PILOTS",cards:['
    '{slug:"p1",stClass:"st-running"},{slug:"p2",stClass:"st-idle"},{slug:"p3",stClass:"st-unread"}]},'
    '{nav:"Engineering",label:"ENGINEERING",cards:['
    '{slug:"e1",stClass:"st-idle"},{slug:"e2",stClass:"st-idle"},{slug:"e3",stClass:"st-go"}]},'
    '{nav:"Interns",label:"INTERNS",cards:['
    '{slug:"i1",stClass:"st-idle"},{slug:"i2",stClass:"st-idle"}]}]'
)


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_active_view_partitions_nongrey_from_grey():
    r = _run_node(f'process.stdout.write(JSON.stringify(g.planView({_GROUPS}, "ACTIVE")));')
    pilots = r["groups"][0]
    assert [c["slug"] for c in pilots["activeCards"]] == ["p1", "p3"], "non-grey seats only"
    assert [c["slug"] for c in pilots["greyCards"]] == ["p2"] and pilots["greyCount"] == 1
    interns = r["groups"][2]
    assert interns["activeCards"] == [] and interns["greyCount"] == 2, "all-quiet group keeps its count"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_group_view_shows_only_that_group():
    r = _run_node(f'process.stdout.write(JSON.stringify(g.planView({_GROUPS}, "Pilots")));')
    assert [grp["nav"] for grp in r["groups"]] == ["Pilots"], "group view isolates one group"
    # In a group view every card shows (no grey collapse).
    assert [c["slug"] for c in r["groups"][0]["activeCards"]] == ["p1", "p2", "p3"]


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_badges_only_attention_and_not_current_group():
    # ALL view: every attention group badges (running-green NEVER badges).
    allv = _run_node(f'process.stdout.write(JSON.stringify(g.planView({_GROUPS}, "ALL").badges));')
    assert allv == {"Pilots": True, "Engineering": True}, allv
    # Viewing Pilots suppresses the Pilots badge but keeps Engineering's.
    piv = _run_node(f'process.stdout.write(JSON.stringify(g.planView({_GROUPS}, "Pilots").badges));')
    assert piv == {"Engineering": True}, piv


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_running_green_is_active_but_never_badges():
    groups = '[{nav:"Support",label:"S",cards:[{slug:"s1",stClass:"st-running"},{slug:"s2",stClass:"st-idle"}]}]'
    r = _run_node(f'process.stdout.write(JSON.stringify(g.planView({groups}, "ACTIVE")));')
    assert [c["slug"] for c in r["groups"][0]["activeCards"]] == ["s1"], "running is non-grey (ACTIVE)"
    assert r["badges"] == {}, "healthy running seat earns no red badge (quiet-when-healthy)"
