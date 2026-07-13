#!/usr/bin/env python3
"""Fleet-wide rollover Stop-hook wiring + fail-loud coverage audit.

CASE_ONE_P0_CONTEXT_METERING_1 (P0.2). The 70/85 context-threshold Stop hook must
be a STRUCTURAL part of every seat, not an opt-in, so no seat runs unmetered. This
generalizes the per-seat installer (scripts/install-rollover-stop-hook.py) across
the whole fleet, enumerated from the ONE source of truth
(orchestrator/agent_identity_data.SNAPSHOT_TERMINALS, generated from the agent
registry).

Two subcommands:
  audit    — report, per picker, whether the Stop hook is registered. FAIL-LOUD:
             exits non-zero and NAMES every unwired / unreachable picker. Never
             silently skips a seat (brief verification #3).
  install  — idempotently register the hook in every reachable picker's
             settings.json via the per-seat installer. Unreachable pickers are
             REPORTED, not skipped.

A picker DIRECTORY is the wiring unit (many seats share one picker path — e.g. the
vault desks all resolve to ~/baker-vault — and the hook is per-picker, not
per-session), so we dedupe on path while still naming every seat that rides it.
"""
from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.agent_identity_data import SNAPSHOT_TERMINALS  # noqa: E402

HOOK_COMMAND = ".claude/hooks/context-threshold-check.sh"  # P0 (kept for back-compat)
PER_SEAT_INSTALLER = REPO_ROOT / "scripts" / "install-rollover-stop-hook.py"

# CASE_ONE_E23: the audit now covers the full hook set the per-seat installer
# wires — the P0 context band PLUS the close-pin gate (Stop + SessionEnd) and the
# session-open orientation hook. Kept in lockstep with install-rollover-stop-hook's
# REQUIRED_HOOKS so a picker is WIRED only when EVERY (event, command) is present.
REQUIRED_HOOKS = [
    ("Stop", ".claude/hooks/context-threshold-check.sh"),
    ("Stop", ".claude/hooks/close-pin-check.sh"),
    ("SessionEnd", ".claude/hooks/close-pin-check.sh"),
    ("SessionStart", ".claude/hooks/session-open-orientation.sh"),
]


def picker_map() -> dict:
    """{picker_path: [slugs riding it]} from SNAPSHOT_TERMINALS. Each entry is
    'slug:path1[,path2]'; the FIRST path is the seat's primary picker (a second,
    for b-codes, is the brisen-lab clone — not a Claude picker, so ignored)."""
    pickers: dict[str, list] = {}
    for entry in SNAPSHOT_TERMINALS:
        slug, _, paths = entry.partition(":")
        if not paths:
            continue
        primary = paths.split(",")[0].strip()
        if primary:
            pickers.setdefault(primary, []).append(slug)
    return pickers


def _event_has_command(settings: dict, event: str, command: str) -> bool:
    for entry in settings.get("hooks", {}).get(event, []) or []:
        for hook in entry.get("hooks") or []:
            if hook.get("command") == command:
                return True
    return False


def _hook_registered(settings: dict) -> bool:
    """WIRED requires EVERY required (event, command) present — the P0 band hook
    plus the two E23 hooks. A picker with only some of them is not fully wired."""
    return all(_event_has_command(settings, ev, cmd) for ev, cmd in REQUIRED_HOOKS)


# Each registered command must point at a script that actually EXISTS in the
# picker, else it no-ops silently (the false-green case, lead #9975). We require
# every hook script plus the shared modules both hook families import.
REQUIRED_HOOK_FILES = (
    ".claude/hooks/context-threshold-check.sh",
    ".claude/hooks/context_meter.py",
    ".claude/hooks/close-pin-check.sh",
    ".claude/hooks/session-open-orientation.sh",
    ".claude/hooks/live_state_predicate.py",
)


def _file_runnable(path: Path) -> bool:
    """A hook file is 'present' only if it can actually RUN when the harness invokes
    it — not merely if it exists (codex #10226 blocker 2: a hook that lost its exec
    bit false-greened). Shell hooks need the user exec bit AND must parse (`bash
    -n`); Python modules must compile (`py_compile`)."""
    if not path.exists():
        return False
    if path.suffix == ".sh":
        try:
            if not (path.stat().st_mode & stat.S_IXUSR):
                return False
            return subprocess.run(["bash", "-n", str(path)],
                                  capture_output=True, timeout=15).returncode == 0
        except Exception:
            return False
    if path.suffix == ".py":
        try:
            return subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                                  capture_output=True, timeout=15).returncode == 0
        except Exception:
            return False
    return path.exists()


def _script_present(root: Path) -> bool:
    return all(_file_runnable(root / rel) for rel in REQUIRED_HOOK_FILES)


def _classify(picker_path: str) -> str:
    """WIRED / MISSING_SCRIPT / MISSING_HOOK / NO_SETTINGS / PATH_ABSENT for one
    picker dir. WIRED requires the Stop hook REGISTERED in settings.local.json (or
    settings.json) AND the hook script files actually PRESENT — registration alone
    is false-green: the command points at a script that no-ops when absent
    (settings-registered-but-script-absent case, lead #9975)."""
    root = Path(picker_path)
    if not root.exists():
        return "PATH_ABSENT"
    claude = root / ".claude"
    found_settings = False
    registered = False
    for name in ("settings.local.json", "settings.json"):
        p = claude / name
        if not p.exists():
            continue
        found_settings = True
        try:
            if _hook_registered(json.loads(p.read_text())):
                registered = True
                break
        except (OSError, json.JSONDecodeError):
            continue
    if registered:
        return "WIRED" if _script_present(root) else "MISSING_SCRIPT"
    return "MISSING_HOOK" if found_settings else "NO_SETTINGS"


def cmd_audit(_args) -> int:
    pickers = picker_map()
    rows = []
    unwired = []
    for path in sorted(pickers):
        status = _classify(path)
        rows.append((status, path, pickers[path]))
        if status != "WIRED":
            unwired.append((status, path, pickers[path]))
    print(f"rollover coverage: {len(pickers)} pickers across "
          f"{sum(len(s) for s in pickers.values())} seats\n")
    for status, path, slugs in rows:
        print(f"  [{status:12}] {path}  ({', '.join(sorted(slugs))})")
    if unwired:
        # FAIL-LOUD: name every gap; never a silent pass.
        print(f"\nFAIL: {len(unwired)} picker(s) NOT fully wired for rollover + "
              f"session-state hooks (context band / close-pin / orientation):")
        for status, path, slugs in unwired:
            print(f"  - {status}: {path}  seats={sorted(slugs)}")
        return 1
    print("\nPASS: every enumerated picker has all rollover + session-state hooks "
          "(context band, close-pin Stop+SessionEnd, session-open orientation).")
    return 0


def cmd_install(args) -> int:
    pickers = picker_map()
    absent, installed, failed = [], [], []
    for path in sorted(pickers):
        root = Path(path)
        if not root.exists():
            absent.append((path, pickers[path]))
            continue
        settings_path = root / ".claude" / "settings.json"
        cmd = [sys.executable, str(PER_SEAT_INSTALLER), "--settings", str(settings_path)]
        if args.window_tokens is not None:
            cmd += ["--window-tokens", str(args.window_tokens)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as exc:  # noqa: BLE001
            failed.append((path, str(exc)))
            continue
        if out.returncode == 0:
            installed.append((path, out.stdout.strip()))
        else:
            failed.append((path, (out.stderr or out.stdout).strip()))
    for path, note in installed:
        print(f"  [ok]      {path}: {note}")
    # FAIL-LOUD on unreachable / errored pickers — report, never silently skip.
    for path, slugs in absent:
        print(f"  [ABSENT]  {path}: seats={sorted(slugs)} — cannot wire "
              f"(picker dir missing / host offline)")
    for path, err in failed:
        print(f"  [FAIL]    {path}: {err}")
    if absent or failed:
        print(f"\nINCOMPLETE: {len(absent)} absent, {len(failed)} failed — "
              f"run again once those hosts/pickers are reachable.")
        return 1
    print(f"\nDONE: hook wired in all {len(installed)} reachable pickers.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="fail-loud coverage report (no writes)")
    ins = sub.add_parser("install", help="idempotently wire the hook fleet-wide")
    ins.add_argument("--window-tokens", type=int, default=None,
                     help="per-picker context window token count")
    args = ap.parse_args()
    raise SystemExit(cmd_audit(args) if args.cmd == "audit" else cmd_install(args))


if __name__ == "__main__":
    main()
