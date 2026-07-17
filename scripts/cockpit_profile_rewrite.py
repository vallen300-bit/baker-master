#!/usr/bin/env python3
"""cockpit_profile_rewrite.py — Terminal-profile CommandString rewrite for the
Phase-2 coordinated cutover (FLEET_TMUX_LAUNCH_1 §6a, scope SCOPE_LAB_TERMINAL_COCKPIT_1
§6.1 / §12). Invoked by cockpit_migrate.sh cutover().

Rewrites each eligible seat's Terminal profile so opening it attaches to (or
creates) that seat's tmux session instead of launching the alias directly:

    CommandString: <alias>  ->  tmux new-session -A -s <slug> "/bin/zsh -lic '<alias>'"

which is exactly the launch form the scope mandates (§6.1). `-A` = attach-if-exists,
so a double-open is safe.

Lesson 76 (HARD, do not weaken): Terminal.app persists its in-memory Window
Settings cache back to the plist on quit. Editing the plist while Terminal is
RUNNING is clobbered on the next quit. This helper therefore REFUSES to run while
Terminal.app is up unless --allow-running is passed (tests / dry-run only). The
cutover orchestrator quits Terminal first, then calls rewrite.

Subcommands (all writes atomic — temp + os.replace):
  rewrite      --manifest F --plist F --backup F   rewrite every eligible profile; snapshot originals to backup first
  restore      --plist F --backup F --profile NAME restore one profile's original CommandString
  restore-all  --plist F --backup F                restore every backed-up profile

The backup is JSON: {"<profile display name>": "<original CommandString>"}.
It is the per-seat rollback source of truth (§12). rewrite refuses to overwrite
an existing backup (that would capture an already-rewritten value as if it were
the original) unless --force.

Exit codes: 0 ok; 2 usage; 3 precondition (Terminal running / plist missing);
4 drift (a profile is not in its expected pre-cutover state) — fail loud, nothing
written.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path


def _die(code: int, msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(code)


def _terminal_running() -> bool:
    """True if Terminal.app has a live process (pgrep -x, exact match)."""
    try:
        r = subprocess.run(["pgrep", "-x", "Terminal"], capture_output=True, text=True)
        return r.returncode == 0 and r.stdout.strip() != ""
    except OSError:
        # pgrep absent is unexpected on macOS; treat as "cannot prove down" -> unsafe.
        return True


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _load_plist(plist: Path) -> dict:
    if not plist.is_file():
        _die(3, f"Terminal plist not found: {plist}")
    try:
        return plistlib.loads(plist.read_bytes())
    except Exception as e:  # noqa: BLE001 — surface any parse failure loudly
        _die(3, f"could not parse plist {plist}: {e}")


def _wrapper(slug: str, alias: str) -> str:
    """The tmux launch wrapper (scope §6.1). Nested quoting: outer double-quotes
    around the login-shell invocation, single quotes around the alias."""
    return f"tmux new-session -A -s {slug} \"/bin/zsh -lic '{alias}'\""


def _manifest_entries(manifest: Path) -> list[dict]:
    if not manifest.is_file():
        _die(3, f"manifest not found: {manifest}")
    data = json.loads(manifest.read_text())
    entries = data.get("entries", [])
    if not entries:
        _die(3, f"manifest has no entries: {manifest}")
    return entries


def cmd_rewrite(args) -> None:
    plist = Path(args.plist)
    manifest = Path(args.manifest)
    backup = Path(args.backup)

    if not args.plan_only:
        if _terminal_running() and not args.allow_running:
            _die(3, "Terminal.app is running — refusing to rewrite (Lesson 76: the "
                    "edit would be clobbered on Terminal's next quit). Quit Terminal "
                    "first, or pass --allow-running for tests/dry-run.")
        # A pre-existing backup is NOT fatal: rewrite merge-preserves it (setdefault
        # below), and the drift guard guarantees a wrapped value is never captured as
        # an "original". This keeps the cutover rerunnable after a partial rollback
        # left the backup in place (codex 267d4477 finding 7). --force is accepted
        # for back-compat but no longer required.
        if backup.exists():
            print(f"note: backup exists at {backup} — merge-preserving originals "
                  "(a rewritten value is never recaptured; drift guard enforces this).",
                  file=sys.stderr)

    entries = _manifest_entries(manifest)
    root = _load_plist(plist)
    win = root.get("Window Settings") or {}

    # Drift guard (fail loud, write NOTHING): every eligible profile must currently
    # be in a known pre-cutover state — either the bare alias (not yet migrated) or
    # already the exact wrapper (idempotent rerun). Any other value is unexpected.
    planned = []   # (profile, slug, alias, current, new)
    already = []   # profiles already at the wrapper (skip)
    for e in entries:
        profile, slug, alias = e.get("profile"), e.get("slug"), e.get("alias")
        if not (profile and slug and alias):
            _die(4, f"manifest entry missing profile/slug/alias: {e}")
        # Quoting guard (codex 019f715a finding 5): the wrapper single-quotes the
        # alias and space-delimits the slug — an alias with a quote or a slug with
        # whitespace/quote would build a broken CommandString. Fail loud rather than
        # emit an unparseable wrapper. (No current seat trips this.)
        if "'" in alias or '"' in alias:
            _die(4, f"alias '{alias}' (seat {slug}) contains a quote — unsupported "
                    "(the tmux wrapper single-quotes the alias).")
        if '"' in slug or "'" in slug or any(c.isspace() for c in slug):
            _die(4, f"slug '{slug}' contains whitespace or a quote — unsupported "
                    "(the tmux wrapper space-delimits the session name).")
        if profile not in win:
            _die(4, f"profile '{profile}' (seat {slug}) not present in {plist} "
                    "Window Settings — cannot rewrite a profile that isn't there.")
        current = (win[profile].get("CommandString") or "").strip()
        new = _wrapper(slug, alias)
        if current == new:
            already.append(profile)
            continue
        if current != alias:
            _die(4, f"drift: profile '{profile}' (seat {slug}) CommandString is "
                    f"'{current}', expected the bare alias '{alias}' or the wrapper. "
                    "Refusing to rewrite an unexpected value — fix the seat first.")
        planned.append((profile, slug, alias, current, new))

    # Load any existing backup up front — the recoverability check below applies to
    # BOTH plan-only and the real run (codex 019f715a finding 4: a green dry-run must
    # not hide a rewrite that would _die).
    existing: dict[str, str] = {}
    if backup.exists():
        try:
            existing = json.loads(backup.read_text())
        except Exception:  # noqa: BLE001
            existing = {}
    # Every ALREADY-wrapped profile must have a recoverable original in the backup,
    # else it can never be rolled back (mixed wrapped/bare + no backup). Fail loud —
    # in plan-only too — before anything is written.
    missing = [p for p in already if p not in existing]
    if missing:
        _die(4, f"profiles already at the wrapper with NO backup entry: {missing}. "
                "Their original CommandString is unrecoverable — refusing rather than "
                f"proceeding with an incomplete rollback source. Restore from "
                f"{backup}.plist.bak or repair the backup first.")

    if args.plan_only:
        summary = {
            "plan": [{"profile": p, "seat": s, "from": c, "to": nw}
                     for p, s, _a, c, nw in planned],
            "already": already,
            "count_planned": len(planned),
            "count_already": len(already),
            "wrote": False,
        }
        print(f"[plan-only] {len(planned)} profile(s) would be rewritten, "
              f"{len(already)} already at wrapper; NOTHING written.", file=sys.stderr)
        print(json.dumps(summary, indent=2))
        return

    # Snapshot originals = existing backup + the bare-alias originals of what we will
    # change (merge-preserve: never lose a true original across reruns).
    snapshot = dict(existing)
    for profile, slug, alias, current, new in planned:
        snapshot.setdefault(profile, current)   # current == bare alias here
    # Never write a degenerate/empty rollback source: nothing to preserve AND no
    # prior backup means a later failed seat would have no original to restore.
    if not snapshot:
        _die(4, "refusing to write an empty backup: every eligible profile is "
                "already at the wrapper and no prior backup exists, so no original "
                "CommandString can be recovered. If this is a re-run, restore from "
                f"{backup}.plist.bak or regenerate originals before proceeding.")
    _atomic_write_text(backup, json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

    # Apply the rewrite.
    for profile, slug, alias, current, new in planned:
        win[profile]["CommandString"] = new
        # Belt-and-suspenders: make sure the profile actually runs the command.
        win[profile]["RunCommandAsShell"] = win[profile].get("RunCommandAsShell", False)
    root["Window Settings"] = win
    _atomic_write_bytes(plist, plistlib.dumps(root, fmt=plistlib.FMT_BINARY))

    summary = {
        "rewritten": [p for p, *_ in planned],
        "already": already,
        "backup": str(backup),
        "count_rewritten": len(planned),
        "count_already": len(already),
    }
    print(f"rewrote {len(planned)} profile(s), {len(already)} already at wrapper; "
          f"backup -> {backup}", file=sys.stderr)
    print(json.dumps(summary))


def _restore_one(win: dict, backup_map: dict, profile: str) -> bool:
    if profile not in backup_map:
        print(f"  no backup entry for '{profile}' — skipped", file=sys.stderr)
        return False
    if profile not in win:
        print(f"  profile '{profile}' absent from plist — skipped", file=sys.stderr)
        return False
    win[profile]["CommandString"] = backup_map[profile]
    print(f"  restored '{profile}' -> '{backup_map[profile]}'", file=sys.stderr)
    return True


def cmd_restore(args) -> None:
    plist = Path(args.plist)
    backup = Path(args.backup)
    if _terminal_running() and not args.allow_running:
        _die(3, "Terminal.app is running — a profile restore written now is "
                "clobbered on Terminal's next quit (Lesson 76). The restored value "
                "lands at the next coordinated Terminal restart. Pass --allow-running "
                "to write anyway (tests), or quit Terminal for a durable restore.")
    if not backup.is_file():
        _die(3, f"backup not found: {backup}")
    backup_map = json.loads(backup.read_text())
    # A restore that CANNOT happen is a loud failure, not a silent RC=0 no-op
    # (codex 019f713a finding 3a): a failed seat with no original to restore must
    # surface so the caller can flag it, never report a phantom success.
    if args.profile not in backup_map:
        _die(4, f"no backup entry for profile '{args.profile}' in {backup} — cannot "
                "restore its original CommandString (the seat has no recoverable "
                "original). Surfacing loudly rather than reporting a phantom restore.")
    root = _load_plist(plist)
    win = root.get("Window Settings") or {}
    changed = _restore_one(win, backup_map, args.profile)
    if not changed:
        _die(4, f"profile '{args.profile}' present in backup but not writable into "
                f"{plist} (absent from Window Settings) — restore did not apply.")
    root["Window Settings"] = win
    _atomic_write_bytes(plist, plistlib.dumps(root, fmt=plistlib.FMT_BINARY))
    print(json.dumps({"restored": [args.profile]}))


def cmd_restore_all(args) -> None:
    plist = Path(args.plist)
    backup = Path(args.backup)
    if _terminal_running() and not args.allow_running:
        _die(3, "Terminal.app is running — restore written now is clobbered on "
                "Terminal's next quit (Lesson 76). Quit Terminal for a durable "
                "restore, or pass --allow-running for tests.")
    if not backup.is_file():
        _die(3, f"backup not found: {backup}")
    backup_map = json.loads(backup.read_text())
    root = _load_plist(plist)
    win = root.get("Window Settings") or {}
    restored, skipped = [], []
    for p in backup_map:
        (restored if _restore_one(win, backup_map, p) else skipped).append(p)
    root["Window Settings"] = win
    _atomic_write_bytes(plist, plistlib.dumps(root, fmt=plistlib.FMT_BINARY))
    print(f"restored {len(restored)} profile(s) from {backup}"
          f"{f'; {len(skipped)} not applied' if skipped else ''}", file=sys.stderr)
    print(json.dumps({"restored": restored, "skipped": skipped}))
    # A backed-up profile that could not be applied (renamed/removed from the plist)
    # is a LOUD failure so callers (emergency_recover) trigger the whole-plist
    # fallback instead of reporting a phantom-complete recovery (codex 019f714a
    # finding 5).
    if skipped:
        sys.exit(4)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cockpit Phase-2 Terminal-profile rewrite/restore")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rewrite", help="rewrite all eligible profiles to the tmux wrapper")
    r.add_argument("--manifest", required=True)
    r.add_argument("--plist", required=True)
    r.add_argument("--backup", required=True)
    r.add_argument("--force", action="store_true", help="overwrite an existing backup")
    r.add_argument("--allow-running", action="store_true", help="skip the Terminal-running guard (tests only)")
    r.add_argument("--plan-only", action="store_true", help="print the planned rewrite as JSON; write nothing (dry-run)")
    r.set_defaults(func=cmd_rewrite)

    s = sub.add_parser("restore", help="restore one profile's original CommandString")
    s.add_argument("--plist", required=True)
    s.add_argument("--backup", required=True)
    s.add_argument("--profile", required=True)
    s.add_argument("--allow-running", action="store_true")
    s.set_defaults(func=cmd_restore)

    a = sub.add_parser("restore-all", help="restore every backed-up profile")
    a.add_argument("--plist", required=True)
    a.add_argument("--backup", required=True)
    a.add_argument("--allow-running", action="store_true")
    a.set_defaults(func=cmd_restore_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
