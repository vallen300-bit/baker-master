"""COCKPIT_DRAWER_COPY_BUTTON_FIX_1 — the drawer/panel Copy button must copy the
messages that are RENDERED, not the "(no unacknowledged messages)" placeholder.

Director live report: the cockpit card drawer rendered unacked messages, but the
Copy button copied the placeholder. Root cause: the renderer and the Copy button
read different sources. In the status-only hydration shape /api/agents returns
unacked_count > 0 with a lean/empty unacked_messages, while the authenticated
/api/messages payload carries the real rows; the renderer surfaced them (via the
"Last message" section / body-preview merge) but Copy read the empty status array.

The fix routes BOTH the renderer and Copy through one pure reconciler
(reconcileUnacked) + formatter (formatUnackedSummary) in glance_state.js, so Copy
copies EXACTLY the rendered rows and only emits the placeholder when the reconciled
list is genuinely empty. glance_state.js is browser JS with no JS runner wired in
this repo, so we exercise the pure, dual-exported functions through `node` and skip
(not fail) when node is absent — the same auto-skip discipline the live-PG tests use.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

GLANCE_JS = (
    Path(__file__).resolve().parents[1] / "scripts" / "cockpit_static" / "glance_state.js"
)


def _run_node(body: str):
    script = f"const g = require({json.dumps(str(GLANCE_JS))});\n{body}"
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=20, check=True,
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_status_only_hydration_shape_recovers_rendered_rows():
    """unacked_count>0 but unacked_messages empty → fall back to the in-memory
    /api/messages detail rows (the reported bug's exact shape)."""
    assert GLANCE_JS.exists(), GLANCE_JS
    rows = _run_node(
        "const row = {unacked_count: 2, unacked_messages: []};"
        "const details = ["
        "  {id: 11, topic: 'alpha', from_terminal: 'lead', acked: false, body_preview: 'hello alpha'},"
        "  {id: 12, topic: 'beta',  from_terminal: 'b1',   acked: false, body_preview: 'hello beta'},"
        "  {id: 9,  topic: 'old',   from_terminal: 'b3',   acked: true,  body_preview: 'already acked'}"
        "];"
        "process.stdout.write(JSON.stringify(g.reconcileUnacked(row, details)));"
    )
    # Only the two unacked details are recovered (the acked id 9 is excluded),
    # enriched with topic + from + body_preview.
    assert [r["id"] for r in rows] == [11, 12]
    assert rows[0]["from_terminal"] == "lead" and rows[0]["body_preview"] == "hello alpha"
    assert all(r["body_preview"] for r in rows)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_copy_payload_matches_rendered_rows_not_placeholder():
    """The status-only shape must copy the real rows (id + from + topic + preview),
    never the placeholder — the Director-reported failure."""
    payload = _run_node(
        "const row = {unacked_count: 1, unacked_messages: []};"
        "const details = [{id: 42, topic: 'cockpit-drawer-copy', from_terminal: 'lead',"
        "                  acked: false, body_preview: 'the real message body'}];"
        "const rows = g.reconcileUnacked(row, details);"
        "process.stdout.write(JSON.stringify(g.formatUnackedSummary('seat-x', rows)));"
    )
    assert "(no unacknowledged messages)" not in payload
    assert "#42" in payload
    assert "from lead" in payload
    assert "cockpit-drawer-copy" in payload
    assert "the real message body" in payload  # AC1: body preview included


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_normal_shape_enriches_lean_status_rows_with_body_preview():
    """When unacked_messages is populated (lean, no body), the reconciler enriches
    each row with the matching /api/messages body_preview so Copy carries it (AC1)."""
    rows = _run_node(
        "const row = {unacked_count: 1, unacked_messages: "
        "  [{id: 5, topic: 'x', from_terminal: 'lead'}]};"
        "const details = [{id: 5, acked: false, body_preview: 'body-of-5'}];"
        "process.stdout.write(JSON.stringify(g.reconcileUnacked(row, details)));"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == 5 and rows[0]["body_preview"] == "body-of-5"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_truly_empty_copies_placeholder():
    """AC2: the placeholder is copied ONLY when there are genuinely no unacked rows."""
    payload = _run_node(
        "const rows = g.reconcileUnacked({unacked_count: 0, unacked_messages: []}, []);"
        "process.stdout.write(JSON.stringify(["
        "  rows.length, g.formatUnackedSummary('seat-x', rows)]));"
    )
    assert payload[0] == 0
    assert "(no unacknowledged messages)" in payload[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bus_degraded_no_details_never_refetches():
    """AC4: with /api/messages unavailable (no in-memory detail rows) the reconciler
    reads only what is in hand — a lean status shape yields the placeholder, and a
    populated status shape still copies its rows. It never needs a refetch."""
    out = _run_node(
        # lean status + no details -> nothing to render -> placeholder (render==copy)
        "const lean = g.reconcileUnacked({unacked_count: 3, unacked_messages: []}, []);"
        # populated status + no details -> still copies the status rows (no body)
        "const full = g.reconcileUnacked({unacked_count: 1, unacked_messages: "
        "  [{id: 7, topic: 't', from_terminal: 'lead'}]}, []);"
        "process.stdout.write(JSON.stringify([lean.length, full.length, full[0].id]));"
    )
    assert out == [0, 1, 7]
