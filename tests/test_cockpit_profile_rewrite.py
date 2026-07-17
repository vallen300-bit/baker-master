"""Round-trip tests for scripts/cockpit_profile_rewrite.py (FLEET_TMUX_LAUNCH_1
Phase-2, scope §6.1 / §12). No live Terminal.app dependency — everything runs
against a throwaway plist + manifest in tmp_path, with --allow-running to bypass
the Lesson-76 running-Terminal guard.
"""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cockpit_profile_rewrite.py"

# eligible seats (profile display name -> (slug, alias)); mirrors the real manifest shape
SEATS = {
    "B3": ("b3", "b3"),
    "Brisen Desk": ("brisen-desk", "brisendesk"),
    "AO Desk": ("ao-desk", "aodesk"),
}


def _wrapper(slug, alias):
    return f"tmux new-session -A -s {slug} \"/bin/zsh -lic '{alias}'\""


def _write_plist(path, extra=None):
    win = {name: {"CommandString": alias, "ProfileCurrentVersion": "2.09"}
           for name, (_slug, alias) in SEATS.items()}
    # a non-eligible profile the rewrite must never touch
    win["Basic"] = {"CommandString": "", "ProfileCurrentVersion": "2.09"}
    if extra:
        win.update(extra)
    root = {"Window Settings": win, "Default Window Settings": "Basic"}
    path.write_bytes(plistlib.dumps(root, fmt=plistlib.FMT_BINARY))


def _write_manifest(path):
    entries = [{"slug": slug, "alias": alias, "profile": name,
                "launch": f"/bin/zsh -lic '{alias}'", "port": 7600 + i, "eligible": True}
               for i, (name, (slug, alias)) in enumerate(SEATS.items())]
    path.write_text(json.dumps({"meta": {"eligible_count": len(entries),
                                         "resolved_count": len(entries)},
                                "entries": entries}))


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def _load_win(plist):
    return plistlib.loads(plist.read_bytes())["Window Settings"]


@pytest.fixture
def env(tmp_path):
    plist = tmp_path / "com.apple.Terminal.plist"
    manifest = tmp_path / "manifest.json"
    backup = tmp_path / "profile_backup.json"
    _write_plist(plist)
    _write_manifest(manifest)
    return plist, manifest, backup


def test_rewrite_sets_wrapper_and_snapshots_originals(env):
    plist, manifest, backup = env
    r = _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
             "--backup", str(backup), "--allow-running")
    assert r.returncode == 0, r.stderr
    win = _load_win(plist)
    for name, (slug, alias) in SEATS.items():
        assert win[name]["CommandString"] == _wrapper(slug, alias)
    # non-eligible profile untouched
    assert win["Basic"]["CommandString"] == ""
    # backup captured the true originals (bare aliases)
    snap = json.loads(backup.read_text())
    for name, (_slug, alias) in SEATS.items():
        assert snap[name] == alias
    assert "Basic" not in snap


def test_restore_all_reverts_exactly(env):
    plist, manifest, backup = env
    _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
         "--backup", str(backup), "--allow-running")
    r = _run("restore-all", "--plist", str(plist), "--backup", str(backup), "--allow-running")
    assert r.returncode == 0, r.stderr
    win = _load_win(plist)
    for name, (_slug, alias) in SEATS.items():
        assert win[name]["CommandString"] == alias


def test_restore_single_profile(env):
    plist, manifest, backup = env
    _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
         "--backup", str(backup), "--allow-running")
    r = _run("restore", "--plist", str(plist), "--backup", str(backup),
             "--profile", "AO Desk", "--allow-running")
    assert r.returncode == 0, r.stderr
    win = _load_win(plist)
    assert win["AO Desk"]["CommandString"] == "aodesk"            # reverted
    assert win["B3"]["CommandString"] == _wrapper("b3", "b3")     # still migrated


def test_plan_only_writes_nothing(env):
    plist, manifest, backup = env
    before = plist.read_bytes()
    r = _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
             "--backup", str(backup), "--plan-only")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["wrote"] is False
    assert out["count_planned"] == len(SEATS)
    assert plist.read_bytes() == before          # plist untouched
    assert not backup.exists()                    # no backup written


def test_idempotent_rerun_reports_already(env):
    plist, manifest, backup = env
    _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
         "--backup", str(backup), "--allow-running")
    # rerun with --force (backup exists) — every seat already at wrapper
    r = _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
             "--backup", str(backup), "--allow-running", "--force")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["count_already"] == len(SEATS)
    assert out["count_rewritten"] == 0


def test_drift_fails_loud_and_writes_nothing(env, tmp_path):
    plist, manifest, backup = env
    # corrupt one eligible profile to an unexpected value
    root = plistlib.loads(plist.read_bytes())
    root["Window Settings"]["AO Desk"]["CommandString"] = "something-unexpected"
    plist.write_bytes(plistlib.dumps(root, fmt=plistlib.FMT_BINARY))
    before = plist.read_bytes()
    r = _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
             "--backup", str(backup), "--allow-running")
    assert r.returncode == 4, (r.returncode, r.stderr)
    assert plist.read_bytes() == before          # nothing written on drift
    assert not backup.exists()


def test_rerun_after_partial_rollback_merge_preserves(env):
    """A pre-existing backup must NOT block a rerun (codex finding 7): rewrite
    merge-preserves the original snapshot and never recaptures a wrapped value."""
    plist, manifest, backup = env
    # first cutover
    _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
         "--backup", str(backup), "--allow-running")
    # simulate a partial rollback: one seat reverted to its alias, backup left in place
    root = plistlib.loads(plist.read_bytes())
    root["Window Settings"]["AO Desk"]["CommandString"] = "aodesk"
    plist.write_bytes(plistlib.dumps(root, fmt=plistlib.FMT_BINARY))
    # rerun must succeed (no exit 3) and re-wrap the reverted seat
    r = _run("rewrite", "--manifest", str(manifest), "--plist", str(plist),
             "--backup", str(backup), "--allow-running")
    assert r.returncode == 0, r.stderr
    win = _load_win(plist)
    assert win["AO Desk"]["CommandString"] == _wrapper("ao-desk", "aodesk")
    # the backup still holds the TRUE original alias, not a wrapped value
    snap = json.loads(backup.read_text())
    assert snap["AO Desk"] == "aodesk"
