"""CASE_ONE_P0_CONTEXT_METERING_1 (P0.2) — fleet wiring + fail-loud audit tests.

Classification runs against tmp fixture picker dirs (never touches real seats).
"""
from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rollover_fleet", REPO_ROOT / "scripts" / "rollover_fleet.py")
rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf)

# WIRED now requires EVERY hook the installer registers (E23 extended the set):
# context band + close-pin (Stop+SessionEnd) + orientation (SessionStart).
def _wired_hooks() -> dict:
    hooks: dict = {}
    for event, command in rf.REQUIRED_HOOKS:
        hooks.setdefault(event, [{"hooks": []}])[0]["hooks"].append(
            {"type": "command", "command": command, "timeout": 10})
    return {"hooks": hooks}


WIRED_SETTINGS = _wired_hooks()


def _make_picker(root: Path, settings: dict | None, *, name="settings.json",
                 with_script: bool = True):
    claude = root / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (claude / name).write_text(json.dumps(settings))
    if with_script:
        # Every hook script + shared module the registrations point at, written so it
        # is actually RUNNABLE (exec bit + parses / compiles) — WIRED is false-green
        # otherwise (a hook that only exists but can't run no-ops silently).
        hooks = claude / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        for rel in rf.REQUIRED_HOOK_FILES:
            f = claude.parent / rel
            if f.suffix == ".sh":
                f.write_text("#!/usr/bin/env bash\nexit 0\n")
                f.chmod(f.stat().st_mode | stat.S_IXUSR)
            else:  # .py
                f.write_text("# stub\n")
    return root


def test_picker_map_dedupes_shared_paths_and_names_all_seats():
    pickers = rf.picker_map()
    # Many vault desks share ~/baker-vault — one picker path, several seats.
    vault = "/Users/dimitry/baker-vault"
    assert vault in pickers
    assert len(pickers[vault]) > 1, "shared picker must list every seat riding it"
    # b3's primary picker is bm-b3 (the brisen-lab second path is dropped).
    assert "b3" in pickers.get("/Users/dimitry/bm-b3", [])


def test_classify_wired(tmp_path):
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS)
    assert rf._classify(str(p)) == "WIRED"


def test_classify_wired_via_settings_local(tmp_path):
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS, name="settings.local.json")
    assert rf._classify(str(p)) == "WIRED"


def test_classify_missing_script_when_registered_but_no_hook_files(tmp_path):
    # The false-green case (lead #9975): settings register the hook, but the
    # script files are absent -> the command no-ops -> NOT wired.
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS, with_script=False)
    assert rf._classify(str(p)) == "MISSING_SCRIPT"


def test_classify_missing_script_when_only_one_hook_file(tmp_path):
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS, with_script=False)
    (p / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    # Only the runner, not the shared context_meter.py -> still MISSING_SCRIPT.
    (p / ".claude" / "hooks" / "context-threshold-check.sh").write_text("#!/bin/bash\n")
    assert rf._classify(str(p)) == "MISSING_SCRIPT"


def test_classify_missing_script_when_hook_not_executable(tmp_path):
    # codex #10226 blocker 2: a registered hook that exists but LOST its exec bit
    # must NOT false-green as WIRED — the harness can't run it.
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS, with_script=True)
    hook = p / ".claude" / "hooks" / "close-pin-check.sh"
    hook.chmod(hook.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    assert rf._classify(str(p)) == "MISSING_SCRIPT"


def test_classify_missing_script_when_shell_hook_syntax_broken(tmp_path):
    # A hook that exists + is executable but does not parse (`bash -n`) is not
    # runnable either -> MISSING_SCRIPT, not WIRED.
    p = _make_picker(tmp_path / "seat", WIRED_SETTINGS, with_script=True)
    hook = p / ".claude" / "hooks" / "session-open-orientation.sh"
    hook.write_text("#!/usr/bin/env bash\nif [ ; then\n")  # broken syntax
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    assert rf._classify(str(p)) == "MISSING_SCRIPT"


def test_classify_missing_hook(tmp_path):
    p = _make_picker(tmp_path / "seat", {"hooks": {"Stop": []}})
    assert rf._classify(str(p)) == "MISSING_HOOK"


def test_classify_no_settings(tmp_path):
    p = _make_picker(tmp_path / "seat", None)  # .claude exists, no json
    assert rf._classify(str(p)) == "NO_SETTINGS"


def test_classify_path_absent(tmp_path):
    assert rf._classify(str(tmp_path / "does-not-exist")) == "PATH_ABSENT"


def test_audit_returns_nonzero_when_any_unwired(monkeypatch, tmp_path, capsys):
    wired = _make_picker(tmp_path / "a", WIRED_SETTINGS)
    unwired = _make_picker(tmp_path / "b", {"hooks": {}})
    monkeypatch.setattr(rf, "picker_map",
                        lambda: {str(wired): ["s1"], str(unwired): ["s2"]})
    rc = rf.cmd_audit(None)
    out = capsys.readouterr().out
    assert rc == 1, "fail-loud: any unwired picker -> nonzero exit"
    assert "FAIL" in out and str(unwired) in out


def test_audit_passes_when_all_wired(monkeypatch, tmp_path, capsys):
    a = _make_picker(tmp_path / "a", WIRED_SETTINGS)
    b = _make_picker(tmp_path / "b", WIRED_SETTINGS)
    monkeypatch.setattr(rf, "picker_map",
                        lambda: {str(a): ["s1"], str(b): ["s2"]})
    rc = rf.cmd_audit(None)
    assert rc == 0
    assert "PASS" in capsys.readouterr().out
