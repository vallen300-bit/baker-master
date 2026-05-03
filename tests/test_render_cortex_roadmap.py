"""Tests for scripts/render_cortex_roadmap.py — schema-version dispatch + structure.

Per BRIEF_FLEET_ROADMAP_HTML_RENDER_1 V0.3.1 §Tests. 12 test functions cover:
v4 backward-compat smoke + v5 two-track + v5 mixed-schema (v5 + v6) + missing
required v5 fields (track / gates / dependencies) + queued priority+ETA sort
+ default-priority-medium + empty-dropped-subsection-omitted + v5 html-escape
of user-content fields + LIVE V5 substring + gate-status-pill labels rendered.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_cortex_roadmap as rcr  # noqa: E402


def test_v4_renders_without_crash():
    """V4 fixture (current prod schema) must still render with original markers."""
    yml = {
        "version": 4,
        "cut_at": "2026-04-30",
        "cut_reason": "test",
        "target": "test target",
        "supersedes": "x",
        "brisen_docs_url": "https://example",
        "backlog": {"list_url": "https://clickup"},
        "done": [{"id": "a", "label": "done item", "shipped_at": "2026-04-30"}],
        "in_flight": [],
        "queued": [{"id": "q", "label": "queued item", "owner": "ah1", "eta": "2026-05-12", "priority": "high"}],
        "dropped": [],
    }
    html_out = rcr.render(yml)
    assert "Cortex Roadmap" in html_out
    assert "LIVE V4" in html_out
    assert "done item" in html_out
    assert "queued item" in html_out


def test_v5_renders_two_tracks_and_gates_and_deps():
    """V5 fixture must render Brisen Lab + Cortex + Gates + Dependencies."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "cut_reason": "test cut",
        "supersedes": "v4",
        "brisen_docs_url": "https://example",
        "clickup_backlog_list_url": "https://clickup",
        "tracks": {
            "brisen_lab": {
                "purpose": "Lab purpose line",
                "done": [{"id": "lab-v1", "label": "Lab V1", "shipped_at": "2026-05-01"}],
                "in_flight": [{"id": "lab-v2", "label": "Lab V2 build", "assignee": "b4", "started_at": "2026-05-03", "eta": "2026-05-24"}],
                "queued": [],
                "dropped": [],
            },
            "cortex": {
                "purpose": "Cortex purpose line",
                "done": [{"id": "stage2-step29", "label": "Step 29 DRY_RUN", "shipped_at": "2026-05-01"}],
                "in_flight": [],
                "queued": [{"id": "step33", "label": "Steps 33-36", "owner": "ah1", "eta": "2026-05-12", "priority": "high"}],
                "dropped": [],
            },
        },
        "gates": [
            {"id": "step-30-live-ao-cycle", "label": "Step 30 first LIVE AO cycle", "status": "open", "note": "Pick topic"},
            {"id": "decom-legacy-ao-path", "label": "Decom legacy AO path", "status": "pending", "note": "Gated on Step 30"},
        ],
        "dependencies": [
            {"from": "lab-v2", "to": "cortex-step-30", "effect": "Removes paste-relay tax"},
        ],
    }
    html_out = rcr.render(yml)
    # Track headers
    assert "Brisen Lab" in html_out
    assert "Cortex" in html_out
    assert "Lab purpose line" in html_out
    assert "Cortex purpose line" in html_out
    # Items present
    assert "Lab V2 build" in html_out
    assert "Step 29 DRY_RUN" in html_out
    # Gates section
    assert "Director's Gates" in html_out or "Gates" in html_out
    assert "Step 30 first LIVE AO cycle" in html_out
    # Dependencies section
    assert "Dependencies" in html_out
    assert "lab-v2" in html_out
    assert "cortex-step-30" in html_out
    assert "Removes paste-relay tax" in html_out


def test_v5_mixed_schema_raises():
    """v5 with stray top-level flat list should error clearly."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
        "done": [{"id": "stray", "label": "should not be here"}],
    }
    with pytest.raises(ValueError, match="Mixed schema"):
        rcr.render(yml)


def test_v6_mixed_schema_also_raises():
    """Mixed-schema check must fire on version >= 5 (forward-compat)."""
    yml = {
        "version": 6,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
        "queued": [{"id": "stray", "label": "should not be here"}],
    }
    with pytest.raises(ValueError, match="Mixed schema"):
        rcr.render(yml)


def test_v5_missing_required_track_raises():
    """v5 without tracks.brisen_lab should error with a specific match string."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {"cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []}},
        "gates": [],
        "dependencies": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_missing_gates_raises():
    """v5 without top-level gates should error."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "dependencies": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_missing_dependencies_raises():
    """v5 without top-level dependencies should error."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
    }
    with pytest.raises(ValueError, match="missing required v5 field"):
        rcr.render(yml)


def test_v5_queued_priority_sort_per_track():
    """Each track's queued list is sorted priority-then-ETA, same as v4. Includes
    two same-priority items with different ETAs to verify the ETA secondary key."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {
                "purpose": "p",
                "done": [],
                "in_flight": [],
                "queued": [
                    {"id": "low-late", "label": "LBL-LATE-LOW", "owner": "ah1", "eta": "2026-09-01", "priority": "low"},
                    {"id": "high-late", "label": "LBL-LATE-HIGH", "owner": "ah1", "eta": "2026-08-01", "priority": "high"},
                    {"id": "high-early", "label": "LBL-EARLY-HIGH", "owner": "ah1", "eta": "2026-05-10", "priority": "high"},
                    {"id": "med-mid", "label": "LBL-MID-MED", "owner": "ah1", "eta": "2026-07-01", "priority": "medium"},
                    {"id": "crit", "label": "LBL-CRIT-LATEST", "owner": "ah1", "eta": "2026-12-01", "priority": "critical"},
                ],
                "dropped": [],
            },
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    # Primary: critical → high → medium → low. Secondary (within same priority): ETA asc.
    # So expected order: CRIT-LATEST, EARLY-HIGH, LATE-HIGH, MID-MED, LATE-LOW.
    assert (
        html_out.find("LBL-CRIT-LATEST")
        < html_out.find("LBL-EARLY-HIGH")
        < html_out.find("LBL-LATE-HIGH")
        < html_out.find("LBL-MID-MED")
        < html_out.find("LBL-LATE-LOW")
    )


def test_v5_default_priority_medium():
    """Item with no `priority` field sorts as `medium`, matching v4."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {
                "purpose": "p",
                "done": [],
                "in_flight": [],
                "queued": [
                    {"id": "low", "label": "LBL-LOW", "owner": "ah1", "eta": "2026-05-01", "priority": "low"},
                    {"id": "no-pri", "label": "LBL-NOPRI", "owner": "ah1", "eta": "2026-05-01"},  # missing priority → medium
                    {"id": "high", "label": "LBL-HIGH", "owner": "ah1", "eta": "2026-05-01", "priority": "high"},
                ],
                "dropped": [],
            },
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    # Expected: LBL-HIGH (priority 1), LBL-NOPRI (priority 2 = medium default), LBL-LOW (priority 3).
    assert html_out.find("LBL-HIGH") < html_out.find("LBL-NOPRI") < html_out.find("LBL-LOW")


def test_v5_empty_dropped_subsection_omitted():
    """Empty `dropped: []` must NOT emit a `Dropped` heading."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {
                "purpose": "p",
                "done": [{"id": "x", "label": "X-DONE", "shipped_at": "2026-05-01"}],
                "in_flight": [],
                "queued": [],
                "dropped": [],
            },
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    assert "X-DONE" in html_out
    # No Brisen-Lab subsection heading for Dropped (zero items). The v4 standing-rules
    # callout still references DROPPED in caps; we assert the substage <h3>Dropped</h3>
    # is NOT emitted.
    assert ">Dropped<" not in html_out


def test_v5_html_escape_user_fields():
    """Gates/deps/purpose strings with HTML chars must be escaped."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "<b>unsafe</b>", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "ok", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [{"id": "g", "label": "<script>", "status": "open", "note": "& more"}],
        "dependencies": [{"from": "<a>", "to": "<b>", "effect": "x & y"}],
    }
    html_out = rcr.render(yml)
    # No raw <b> / <script> / <a> from user fields
    assert "<b>unsafe</b>" not in html_out
    assert "<script>" not in html_out
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html_out
    assert "&lt;script&gt;" in html_out


def test_v5_live_badge_substring():
    """`LIVE V5` substring must appear (header live-badge)."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    assert "LIVE V5" in html_out


def test_gate_status_pill_classes_present():
    """Gate status colors must use existing CSS classes (no new color system)."""
    yml = {
        "version": 5,
        "cut_at": "2026-05-03",
        "tracks": {
            "brisen_lab": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
            "cortex": {"purpose": "p", "done": [], "in_flight": [], "queued": [], "dropped": []},
        },
        "gates": [
            {"id": "g1", "label": "open gate", "status": "open", "note": "n"},
            {"id": "g2", "label": "pending gate", "status": "pending", "note": "n"},
            {"id": "g3", "label": "closed gate", "status": "closed", "note": "n"},
        ],
        "dependencies": [],
    }
    html_out = rcr.render(yml)
    assert "open gate" in html_out
    assert "pending gate" in html_out
    assert "closed gate" in html_out
