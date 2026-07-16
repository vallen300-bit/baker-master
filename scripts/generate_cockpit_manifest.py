#!/usr/bin/env python3
"""Generate the Cockpit launch manifest (FLEET_TMUX_LAUNCH_1, scope §6b v1.3).

The manifest is the ONLY thing fleet_terminals.sh and the ttyd plist installer
consume. It is DERIVED at generation time from three live sources — never a
hand-kept list (HAGENAUER trap) and never a registry schema change:

  1. agent registry  -> eligibility (status active AND runtime prefix terminal-)
                        + registry index (port = 7600 + index).
  2. Terminal.app     -> per-profile CommandString == the launch alias.
     profiles
  3. the alias's own  -> role marker, extracted per lead ruling #12080 (join D):
     zsh function        BAKER_ROLE / FORGE_TERMINAL assignment, or the picker
     body                directory the function cd's into. One level of alias
                         indirection (`foo () { bar "$@" }`) is followed.

Join D fail-loud (scope §6b): an eligible profile whose function body yields no
resolvable registry slug is a REAL DEFECT in that seat's zsh function — the fix
is correcting the function, never adding a table entry here. --strict makes that
fatal (binds the Phase-2 cutover gate); default mode emits the manifest for the
resolvable seats plus a reconciliation report naming the rest (unblocks the
Phase-1 pilot per the #12080 gate split).

Launch form everywhere (scope §6b): /bin/zsh -lic '<alias>'.

Regenerate with:  python3 scripts/generate_cockpit_manifest.py --write
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REGISTRY = Path(os.environ.get(
    "BAKER_AGENT_REGISTRY",
    os.path.expanduser("~/baker-vault/_ops/registries/agent_registry.yml"),
))
TERMINAL_PLIST = Path(os.environ.get(
    "COCKPIT_TERMINAL_PLIST",
    os.path.expanduser("~/Library/Preferences/com.apple.Terminal.plist"),
))
SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_OUT = SCRIPT_DIR / "cockpit_launch_manifest.json"
RECON_OUT = SCRIPT_DIR / "cockpit_manifest_reconciliation.md"
PORT_BASE = 7600


def _load_registry():
    import yaml  # local import: only the generator needs pyyaml
    data = yaml.safe_load(REGISTRY.read_text())
    agents = data.get("agents") if isinstance(data, dict) else data
    if isinstance(agents, dict):
        agents = list(agents.values())
    return agents


def _norm(s: str) -> str:
    """Case/sep-insensitive key: 'AI_DENNIS' == 'ai-dennis', 'B3' == 'b3'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _load_profiles():
    """profile display-name -> launch alias (CommandString)."""
    import plistlib
    d = plistlib.loads(TERMINAL_PLIST.read_bytes())
    out = {}
    for name, cfg in (d.get("Window Settings") or {}).items():
        cmd = cfg.get("CommandString")
        if cmd:
            out[name] = cmd.strip()
    return out


def _zsh(cmd: str) -> str:
    """Run a login+interactive zsh so alias functions are defined."""
    r = subprocess.run(
        ["/bin/zsh", "-lic", cmd],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout


def _function_body(alias: str, _depth: int = 0) -> str | None:
    """Return the alias's zsh function body, following one indirection level."""
    if _depth > 3:
        return None
    body = _zsh(f"functions {alias} 2>/dev/null")
    if f"{alias} ()" not in body and f"{alias}()" not in body:
        return None
    # indirection: body is just `other "$@"` -> follow it
    m = re.search(rf"{re.escape(alias)}\s*\(\)\s*\{{\s*([a-zA-Z0-9_-]+)\s+\"\$@\"\s*\}}", body)
    if m:
        inner = _function_body(m.group(1), _depth + 1)
        if inner:
            return inner
    return body


def _alias_type_ok(alias: str) -> bool:
    """scope §6b gen-time probe: the alias must resolve as a function."""
    out = _zsh(f"type {alias} 2>/dev/null")
    return alias in out and ("function" in out or "shell function" in out)


def _extract_role_marker(body: str) -> str | None:
    """Pull the role slug from a function body via the join-D markers."""
    for var in ("BAKER_ROLE", "FORGE_TERMINAL"):
        m = re.search(rf"\b{var}=([A-Za-z0-9_-]+)", body)
        if m:
            return m.group(1)
    # picker directory the function cd's into: cd ~/bm-<x> or cd "$HOME/.../bm-<x>"
    m = re.search(r"cd\s+[\"']?\S*?bm-([A-Za-z0-9_-]+?)(?:-t)?[\"'/\s]", body)
    if m:
        return m.group(1)
    return None


def build():
    agents = _load_registry()
    # registry index -> port (stable across eligibility filtering)
    idx_by_slug = {a["slug"]: i for i, a in enumerate(agents)}
    slug_by_norm = {}
    for a in agents:
        slug_by_norm[_norm(a["slug"])] = a["slug"]
        if a.get("display_name"):
            slug_by_norm.setdefault(_norm(a["display_name"]), a["slug"])

    eligible = [
        a for a in agents
        if str(a.get("status")) == "active"
        and str(a.get("runtime", "")).startswith("terminal-")
    ]

    profiles = _load_profiles()
    # resolve each Terminal profile -> registry slug via its function body
    profile_slug = {}       # slug -> (profile_name, alias)
    unresolved_profiles = []  # (profile_name, alias, reason)
    for pname, alias in profiles.items():
        if not _alias_type_ok(alias):
            unresolved_profiles.append((pname, alias, "alias does not resolve as a zsh function (type probe failed)"))
            continue
        body = _function_body(alias)
        if not body:
            unresolved_profiles.append((pname, alias, "no function body found"))
            continue
        marker = _extract_role_marker(body)
        if not marker:
            unresolved_profiles.append((pname, alias, "function body carries no BAKER_ROLE/FORGE_TERMINAL/picker-dir marker"))
            continue
        slug = slug_by_norm.get(_norm(marker))
        if not slug:
            unresolved_profiles.append((pname, alias, f"marker '{marker}' does not map to any registry slug"))
            continue
        # first profile wins; a second one mapping to the same slug is a dup
        if slug not in profile_slug:
            profile_slug[slug] = (pname, alias)

    entries = []
    unresolved_seats = []
    for a in eligible:
        slug = a["slug"]
        hit = profile_slug.get(slug)
        if not hit:
            unresolved_seats.append((slug, a.get("display_name", ""), a.get("runtime")))
            continue
        pname, alias = hit
        entries.append({
            "slug": slug,
            "alias": alias,
            "launch": f"/bin/zsh -lic '{alias}'",
            "port": PORT_BASE + idx_by_slug[slug],
            "eligible": True,
            "profile": pname,
        })
    entries.sort(key=lambda e: e["port"])
    return {
        "entries": entries,
        "eligible_count": len(eligible),
        "resolved_count": len(entries),
        "unresolved_seats": unresolved_seats,
        "unresolved_profiles": unresolved_profiles,
    }


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def render_manifest(result) -> str:
    header = {
        "_generated": "DO NOT EDIT BY HAND — regenerate with scripts/generate_cockpit_manifest.py --write",
        "_sources": {
            "registry": str(REGISTRY),
            "registry_sha256": _sha256(REGISTRY),
            "terminal_plist": str(TERMINAL_PLIST),
        },
        "_join": "D (alias-function role-marker derivation, lead ruling #12080)",
        "_launch_form": "/bin/zsh -lic '<alias>'",
        "port_base": PORT_BASE,
        "eligible_count": result["eligible_count"],
        "resolved_count": result["resolved_count"],
    }
    return json.dumps({"meta": header, "entries": result["entries"]}, indent=2) + "\n"


def render_reconciliation(result) -> str:
    lines = [
        "# Cockpit manifest reconciliation (FLEET_TMUX_LAUNCH_1, join D / #12080)",
        "",
        "> GENERATED artifact — do not hand-edit. Fixing an unresolved seat means",
        "> correcting that seat's zsh function (real source), never a table here.",
        "",
        f"- Eligible seats (active + runtime terminal-*): **{result['eligible_count']}**",
        f"- Resolved into manifest: **{result['resolved_count']}**",
        f"- Unresolved eligible seats: **{len(result['unresolved_seats'])}**",
        "",
        "## Resolved",
        "",
        "| port | slug | alias | Terminal profile |",
        "|---|---|---|---|",
    ]
    for e in result["entries"]:
        lines.append(f"| {e['port']} | {e['slug']} | `{e['alias']}` | {e['profile']} |")
    lines += ["", "## Unresolved eligible seats (fix the zsh function)", ""]
    if result["unresolved_seats"]:
        lines += ["| slug | display | runtime | why |", "|---|---|---|---|"]
        for slug, disp, rt in result["unresolved_seats"]:
            lines.append(f"| {slug} | {disp} | {rt} | no Terminal profile function body resolved to this slug |")
    else:
        lines.append("_none — all eligible seats resolved._")
    lines += ["", "## Unresolved Terminal profiles (informational)", ""]
    if result["unresolved_profiles"]:
        lines += ["| profile | alias | reason |", "|---|---|---|"]
        for pname, alias, why in result["unresolved_profiles"]:
            lines.append(f"| {pname} | `{alias}` | {why} |")
    else:
        lines.append("_none._")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write manifest + reconciliation to scripts/")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if any eligible seat is unresolved (Phase-2 gate)")
    args = ap.parse_args()

    result = build()
    manifest = render_manifest(result)
    recon = render_reconciliation(result)

    if args.write:
        MANIFEST_OUT.write_text(manifest)
        RECON_OUT.write_text(recon)
        print(f"wrote {MANIFEST_OUT}")
        print(f"wrote {RECON_OUT}")
    else:
        print(manifest)

    print(
        f"resolved {result['resolved_count']}/{result['eligible_count']} eligible seats"
        f" ({len(result['unresolved_seats'])} unresolved)",
        file=sys.stderr,
    )
    if args.strict and result["unresolved_seats"]:
        names = ", ".join(s for s, _, _ in result["unresolved_seats"])
        print(f"FATAL (--strict): unresolved eligible seats: {names}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
