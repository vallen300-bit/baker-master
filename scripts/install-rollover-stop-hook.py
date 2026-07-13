#!/usr/bin/env python3
"""Install the fleet rollover + session-state hooks into a Claude settings.json.

Idempotent. Registers every hook in ``REQUIRED_HOOKS`` under its event, and sets
``rollover_window_tokens`` when ``--window-tokens`` is given.

CASE_ONE_P0 wired the context-threshold Stop hook here. CASE_ONE_E23 extends the
SAME installer (no second wiring mechanism, per brief) to also register the
close-pin gate (Stop + SessionEnd) and the session-open orientation hook
(SessionStart). One installer registers them all so a picker is either fully wired
or fail-loud in the audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# (event, command) pairs. All share the same command-hook shape (timeout 10). The
# close-pin gate is wired on BOTH Stop (can block/warn) and SessionEnd (persist at
# real close) — one script, event-aware inside.
REQUIRED_HOOKS: list = [
    ("Stop", ".claude/hooks/context-threshold-check.sh"),           # P0 context band
    ("Stop", ".claude/hooks/close-pin-check.sh"),                   # E23.1 warn/block
    ("SessionEnd", ".claude/hooks/close-pin-check.sh"),             # E23.1 persist
    ("SessionStart", ".claude/hooks/session-open-orientation.sh"),  # E23.2 orient
]


def _hook_dict(command: str) -> dict:
    return {"type": "command", "command": command, "timeout": 10}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _ensure_hook(settings: dict, event: str, command: str) -> bool:
    """Register (event, command) idempotently. Returns True if it changed the doc."""
    hooks_root = settings.setdefault("hooks", {})
    entries = hooks_root.setdefault(event, [])
    want = _hook_dict(command)
    for entry in entries:
        for hook in entry.get("hooks") or []:
            if hook.get("command") == command:
                if hook != want:
                    hook.clear()
                    hook.update(want)
                    return True
                return False
    entries.append({"hooks": [dict(want)]})
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--settings",
        default=".claude/settings.json",
        help="settings.json path (default: .claude/settings.json)",
    )
    ap.add_argument(
        "--window-tokens",
        type=int,
        default=None,
        help="per-picker context window token count",
    )
    args = ap.parse_args()

    path = Path(args.settings)
    settings = _load(path)
    changed = False
    for event, command in REQUIRED_HOOKS:
        if _ensure_hook(settings, event, command):
            changed = True
    if args.window_tokens is not None:
        if args.window_tokens <= 0:
            raise SystemExit("--window-tokens must be positive")
        if settings.get("rollover_window_tokens") != args.window_tokens:
            settings["rollover_window_tokens"] = args.window_tokens
            changed = True

    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"updated {path}")
    else:
        print(f"already installed in {path}")


if __name__ == "__main__":
    main()
