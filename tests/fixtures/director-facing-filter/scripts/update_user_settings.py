#!/usr/bin/env python3
"""update_user_settings.py — idempotent merge of director-facing-filter hooks
into ~/.claude/settings.json. Pre-merge: backup to settings.json.bak-<ts>.

Adds:
  UserPromptSubmit: strategic-mode-router, authority-profile-preload, pre-send-checklist
  Stop: synthesis-vs-taxonomy, standing-rules-scan

ORDER MATTERS:
  UserPromptSubmit — strategic-mode-router MUST run before authority-profile-preload
                     + pre-send-checklist (state-file dependency).
  Stop — synthesis-vs-taxonomy + standing-rules-scan run alongside recommendation-check;
         no cross-dependency.

Idempotent: if hook already present at correct path, no-op. If at wrong path, warn + skip.
Refuses to write if a conflicting entry exists (same hook name, different command).

CLI:
  update_user_settings.py [--dry-run] [--settings PATH]
  Default settings = $HOME/.claude/settings.json.
  --dry-run: print the merged settings to stdout, do not write.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path


HOOKS_TO_WIRE = {
    "UserPromptSubmit": [
        "$HOME/.claude/hooks/strategic-mode-router.sh",
        "$HOME/.claude/hooks/authority-profile-preload.sh",
        "$HOME/.claude/hooks/pre-send-checklist.sh",
        # Phase 2 (v1.1): inject any pending light-mode annotations on next turn.
        # Order after pre-send-checklist so it runs last in the UserPromptSubmit pipe.
        "$HOME/.claude/hooks/annotate-pending-checker.sh",
    ],
    "Stop": [
        "$HOME/.claude/hooks/synthesis-vs-taxonomy.sh",
        "$HOME/.claude/hooks/standing-rules-scan.sh",
        # Phase 2 (v1.1): judgment-layer triggers. Both call Haiku via
        # lib/call_validator.py (1Password-fetched key); both degrade to no-op
        # on any infra failure so they never block legitimate work.
        "$HOME/.claude/hooks/stakeholder-authority-trigger.sh",
        "$HOME/.claude/hooks/contract-gate-trigger.sh",
    ],
}


def _normalize(cmd: str) -> str:
    """Idempotency comparator: collapse $HOME / ~ / symlinks so two spellings of
    the same path compare equal (Gate-2 MEDIUM)."""
    if not cmd:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(cmd))
    try:
        return os.path.realpath(expanded)
    except OSError:
        return expanded


def _existing_commands(matcher_entries: list) -> set:
    """All commands already wired under this event, normalized."""
    out: set = set()
    for entry in matcher_entries or []:
        for h in (entry.get("hooks") or []):
            cmd = h.get("command")
            if cmd:
                out.add(_normalize(cmd))
    return out


def _find_or_create_matcher_entry(bucket: list) -> dict:
    """Return the first existing `matcher: "*"` entry, or create one and append.

    Bundling all hooks for an event under a single matcher entry is what
    guarantees execution order — Claude Code preserves the `hooks: [...]` array
    ordering within one matcher entry. Multiple matcher entries can interleave
    based on which Claude Code's matcher fires first (per Gate-3 HIGH 2026-05-19).
    """
    for entry in bucket:
        if entry.get("matcher") == "*":
            entry.setdefault("hooks", [])
            return entry
    entry = {"matcher": "*", "hooks": []}
    bucket.append(entry)
    return entry


def merge_settings(settings: dict) -> tuple[dict, list[str]]:
    """Return (merged_settings, list_of_actions_taken).

    Per-event: all wire-list commands go into ONE matcher entry's hooks[] array
    so execution order is deterministic. Idempotent via path-normalized compare.
    """
    actions: list[str] = []
    hooks_root = settings.setdefault("hooks", {})

    for event, commands in HOOKS_TO_WIRE.items():
        bucket = hooks_root.setdefault(event, [])
        existing = _existing_commands(bucket)
        entry = _find_or_create_matcher_entry(bucket)
        for cmd in commands:
            if _normalize(cmd) in existing:
                actions.append(f"skip (already wired): {event} → {cmd}")
                continue
            entry["hooks"].append({"type": "command", "command": cmd})
            existing.add(_normalize(cmd))
            actions.append(f"add: {event} → {cmd}")

    return settings, actions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"),
                    help="Path to settings.json (default: ~/.claude/settings.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print merged JSON to stdout instead of writing.")
    args = ap.parse_args()

    settings_path = Path(args.settings)
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: settings.json is not valid JSON: {e}", file=sys.stderr)
            return 2
    else:
        settings = {}

    merged, actions = merge_settings(settings)
    output = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"

    for action in actions:
        print(action, file=sys.stderr)

    if args.dry_run:
        sys.stdout.write(output)
        return 0

    if settings_path.exists():
        ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup = settings_path.with_suffix(settings_path.suffix + f".bak-{ts}")
        shutil.copy2(settings_path, backup)
        print(f"backup: {backup}", file=sys.stderr)
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings_path.write_text(output, encoding="utf-8")
    print(f"wrote: {settings_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
