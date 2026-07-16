"""Regression: generate_cockpit_manifest.py --strict on an unresolved seat must
exit 1 with a FATAL message — NOT crash with ValueError (codex #12118 P1-3, where
the 4-tuple unresolved_seats row was unpacked as 3)."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_cockpit_manifest.py"


def _fixtures(tmp_path):
    # one eligible seat ('ghost') whose Terminal profile carries NO identity
    # marker -> unresolved. one clean seat ('b3') that resolves, so the run is
    # a realistic mixed case.
    reg = tmp_path / "registry.yml"
    reg.write_text(
        "agents:\n"
        "  - agent_id: AG-103\n    slug: b3\n    display_name: B3\n"
        "    status: active\n    runtime: terminal-claude\n"
        "  - agent_id: AG-900\n    slug: ghost\n    display_name: Ghost\n"
        "    status: active\n    runtime: terminal-claude\n"
    )
    plist = tmp_path / "Terminal.plist"
    plistlib.dump(
        {"Window Settings": {
            "B3": {"CommandString": "b3"},
            "Ghost": {"CommandString": "ghostalias"},
        }},
        plist.open("wb"),
    )
    return reg, plist


def _run(reg, plist, *args):
    env = dict(os.environ,
               BAKER_AGENT_REGISTRY=str(reg),
               COCKPIT_TERMINAL_PLIST=str(plist))
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env)


def test_strict_exits_1_not_crash_on_unresolved(tmp_path):
    reg, plist = _fixtures(tmp_path)
    r = _run(reg, plist, "--strict")
    # must be a clean fatal exit, not a Python traceback
    assert r.returncode == 1, r.stderr
    assert "FATAL" in r.stderr
    assert "ghost" in r.stderr
    assert "Traceback" not in r.stderr, r.stderr


def test_nonstrict_lists_unresolved_without_crash(tmp_path):
    reg, plist = _fixtures(tmp_path)
    r = _run(reg, plist)  # default mode: emit + report, exit 0
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr, r.stderr
