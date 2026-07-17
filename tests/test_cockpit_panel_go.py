"""Regression: the terminal-panel GO must gate on needs_go, not fire on any seat.

codex delta gate #12176 (LAB_COCKPIT_PAGE_1 PR #585): the card-face GO was
gated on needs_go but the panel GO (#term-go) was unconditional, so opening any
normal seat and clicking panel GO sent a bare Enter into its tmux. The fix routes
BOTH GO affordances through one pure predicate `goAffordanceVisible(row)` in
glance_state.js. This test locks that predicate.

glance_state.js is browser JS; there is no JS test runner wired into this repo,
so we exercise the pure, dual-exported predicate through `node`. If node is not
installed (e.g. a node-less CI image) the test skips rather than failing — the
same auto-skip discipline the live-PG tests use.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

GLANCE_JS = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cockpit_static"
    / "glance_state.js"
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_go_affordance_gates_strictly_on_needs_go():
    assert GLANCE_JS.exists(), GLANCE_JS
    script = (
        f"const g = require({json.dumps(str(GLANCE_JS))});"
        "const f = g.goAffordanceVisible;"
        "process.stdout.write(JSON.stringify(["
        "  f({needs_go: true}),"          # awaiting GO -> visible
        "  f({needs_go: false}),"         # up but not awaiting -> hidden
        "  f({needs_go: true, is_working: true}),"  # needs_go wins over working
        "  f({}),"                        # no needs_go field -> hidden
        "  f({needs_go: 'true'}),"        # truthy-but-not-true string -> hidden
        "  f(null),"                      # no live row (seat down/absent) -> hidden
        "  f(undefined)"                  # missing row -> hidden
        "]));"
    )
    out = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert json.loads(out.stdout) == [True, False, True, False, False, False, False]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_amber_state_is_unread_and_not_working():
    """D5 amber = unacked>0 AND not working AND not needs_go (== NEW)."""
    assert GLANCE_JS.exists(), GLANCE_JS
    script = (
        f"const g = require({json.dumps(str(GLANCE_JS))});"
        "const a = g.amberState;"
        "process.stdout.write(JSON.stringify(["
        "  a({unacked_count: 3, has_telemetry: true}),"                 # unread, idle -> amber
        "  a({unacked_count: 3, is_working: true, has_telemetry: true})," # working suppresses -> not amber
        "  a({unacked_count: 3, needs_go: true, has_telemetry: true})," # needs_go owns it -> not amber
        "  a({unacked_count: 0, has_telemetry: true}),"                # no unread -> not amber
        "  a(null),"                                                    # no row -> not amber
        "  a(undefined)"
        "]));"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=20, check=True,
    )
    assert json.loads(out.stdout) == [True, False, False, False, False, False]
