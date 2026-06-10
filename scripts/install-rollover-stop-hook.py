#!/usr/bin/env python3
"""Install the worker rollover Stop hook into a Claude settings.json file.

Idempotent. The hook uses per-picker config from ``rollover_window_tokens``;
pass ``--window-tokens`` for the engine window of that picker.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HOOK = {
    "type": "command",
    "command": ".claude/hooks/context-threshold-check.sh",
    "timeout": 10,
}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _ensure_stop_hook(settings: dict) -> bool:
    hooks_root = settings.setdefault("hooks", {})
    stop_entries = hooks_root.setdefault("Stop", [])
    for entry in stop_entries:
        for hook in entry.get("hooks") or []:
            if hook.get("command") == HOOK["command"]:
                if hook != HOOK:
                    hook.clear()
                    hook.update(HOOK)
                    return True
                return False
    stop_entries.append({"hooks": [dict(HOOK)]})
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
    changed = _ensure_stop_hook(settings)
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
