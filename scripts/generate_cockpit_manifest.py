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
MANIFEST_OUT = Path(os.environ.get("COCKPIT_MANIFEST_OUT", SCRIPT_DIR / "cockpit_launch_manifest.json"))
RECON_OUT = Path(os.environ.get("COCKPIT_RECON_OUT", SCRIPT_DIR / "cockpit_manifest_reconciliation.md"))
PORT_BASE = 7600


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp + os.replace so a run never leaves a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


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


# A profile CommandString is normally the bare launch alias, but after the
# Phase-2 cutover it is the tmux wrapper `tmux new-session -A -s <slug>
# "/bin/zsh -lic '<alias>'"`. Unwrap it back to the alias so the generator
# resolves IDENTICALLY pre- and post-cutover (codex 019f714a finding 7 — otherwise
# a post-cutover regeneration resolves 0/N and --strict fails the whole fleet).
_WRAPPER_RE = re.compile(r"""^tmux\s+new-session\s+-A\s+-s\s+\S+\s+"/bin/zsh\s+-lic\s+'([^']+)'"\s*$""")


def _unwrap_commandstring(cmd: str) -> str:
    m = _WRAPPER_RE.match(cmd)
    return m.group(1) if m else cmd


def _load_profiles():
    """profile display-name -> launch alias (CommandString, unwrapped if post-cutover)."""
    import plistlib
    d = plistlib.loads(TERMINAL_PLIST.read_bytes())
    out = {}
    for name, cfg in (d.get("Window Settings") or {}).items():
        cmd = cfg.get("CommandString")
        if cmd:
            out[name] = _unwrap_commandstring(cmd.strip())
    return out


def _zsh(cmd: str) -> str:
    """Run a login+interactive zsh so alias functions are defined."""
    r = subprocess.run(
        ["/bin/zsh", "-lic", cmd],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout


def _function_body(alias: str, _hopped: bool = False):
    """Return (body, hop) for the alias, following AT MOST ONE wrapper hop
    (scope v1.3.2 §6b, ruling #12093). hop is the wrapper alias followed, or None."""
    body = _zsh(f"functions {alias} 2>/dev/null")
    if f"{alias} ()" not in body and f"{alias}()" not in body:
        return None, None
    # pure wrapper: body is just `other "$@"` -> follow EXACTLY ONE hop
    m = re.search(rf"{re.escape(alias)}\s*\(\)\s*\{{\s*([a-zA-Z0-9_-]+)\s+\"\$@\"\s*\}}", body)
    if m and not _hopped:
        inner, _ = _function_body(m.group(1), _hopped=True)
        if inner:
            return inner, m.group(1)
    return body, None


def _alias_type_ok(alias: str) -> bool:
    """scope §6b gen-time probe: the alias must resolve as a function."""
    out = _zsh(f"type {alias} 2>/dev/null")
    return alias in out and ("function" in out or "shell function" in out)


# ruling #12093 delta (1): ONLY literal identity markers. NO picker-dir/cd fallback
# (cwd parsing stays forbidden). Both markers are collected, then reconciled.
_MARKER_VARS = ("BAKER_ROLE", "FORGE_TERMINAL")


def _extract_markers(body: str):
    """All literal identity markers in the body: list of (var, raw_value)."""
    found = []
    for var in _MARKER_VARS:
        m = re.search(rf"\b{var}=([A-Za-z0-9_-]+)", body)
        if m:
            found.append((var, m.group(1)))
    return found


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
    # Per-profile resolution with full provenance (ruling #12093 delta 3).
    # Reconcile-to-exactly-one (delta 2): the DISTINCT set of registry slugs the
    # profile's markers resolve to must have size exactly 1 — zero or >1 (conflict)
    # => unresolved, fail loud. No first-match-wins.
    provenance = []          # per-profile rows for the reconciliation artifact
    slug_to_profiles = {}    # slug -> [profile_name, ...] (seat-level reconcile)
    for pname, alias in sorted(profiles.items()):
        row = {"profile": pname, "alias": alias, "hop": None,
               "markers": [], "matched": None, "verdict": None}
        if not _alias_type_ok(alias):
            row["verdict"] = "unresolved: alias not a zsh function (type probe failed)"
            provenance.append(row); continue
        body, hop = _function_body(alias)
        row["hop"] = hop
        if not body:
            row["verdict"] = "unresolved: no function body"
            provenance.append(row); continue
        markers = _extract_markers(body)
        row["markers"] = [f"{v}={val}" for v, val in markers]
        if not markers:
            row["verdict"] = "unresolved: zero identity markers (BAKER_ROLE/FORGE_TERMINAL)"
            provenance.append(row); continue
        resolved = {}   # slug -> [marker str] that mapped to it
        for v, val in markers:
            s = slug_by_norm.get(_norm(val))
            if s:
                resolved.setdefault(s, []).append(f"{v}={val}")
        distinct = set(resolved)
        if len(distinct) == 0:
            row["verdict"] = f"unresolved: no marker maps to a registry slug ({row['markers']})"
        elif len(distinct) > 1:
            row["verdict"] = f"unresolved: CONFLICT — markers point at {sorted(distinct)}"
        else:
            slug = distinct.pop()
            row["matched"] = slug
            row["verdict"] = "resolved"
            slug_to_profiles.setdefault(slug, []).append(pname)
        provenance.append(row)

    profile_by_slug = {r["matched"]: r for r in provenance if r["verdict"] == "resolved"}

    entries = []
    unresolved_seats = []
    for a in eligible:
        slug = a["slug"]
        hits = slug_to_profiles.get(slug, [])
        if len(hits) == 0:
            unresolved_seats.append((slug, a.get("display_name", ""), a.get("runtime"),
                                     "no profile resolved to this slug"))
            continue
        if len(hits) > 1:   # seat-level conflict: >1 profile claims this seat
            unresolved_seats.append((slug, a.get("display_name", ""), a.get("runtime"),
                                     f"CONFLICT — {len(hits)} profiles resolve here: {hits}"))
            continue
        r = profile_by_slug[slug]
        entries.append({
            "slug": slug,
            "alias": r["alias"],
            "launch": f"/bin/zsh -lic '{r['alias']}'",
            "port": PORT_BASE + idx_by_slug[slug],
            "eligible": True,
            "profile": r["profile"],
        })
    entries.sort(key=lambda e: e["port"])
    return {
        "entries": entries,
        "eligible_count": len(eligible),
        "resolved_count": len(entries),
        "unresolved_seats": unresolved_seats,
        "provenance": provenance,
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
        "# Cockpit manifest reconciliation (FLEET_TMUX_LAUNCH_1, join v1.3.2 / #12093)",
        "",
        "> GENERATED artifact — do not hand-edit. Reconcile-to-exactly-one: a profile",
        "> resolves iff its literal BAKER_ROLE/FORGE_TERMINAL markers (≤1 wrapper hop,",
        "> NO cwd parsing) map to exactly one registry slug. Zero/conflict/multiple =",
        "> unresolved -> fix that seat's zsh function markers at source, never a table.",
        "",
        f"- Eligible seats (active + runtime terminal-*): **{result['eligible_count']}**",
        f"- Resolved into manifest: **{result['resolved_count']}**",
        f"- Unresolved eligible seats: **{len(result['unresolved_seats'])}**",
        "",
        "## Resolved seats",
        "",
        "| port | slug | alias | Terminal profile |",
        "|---|---|---|---|",
    ]
    for e in result["entries"]:
        lines.append(f"| {e['port']} | {e['slug']} | `{e['alias']}` | {e['profile']} |")
    lines += ["", "## Unresolved eligible seats (fix the zsh function markers)", ""]
    if result["unresolved_seats"]:
        lines += ["| slug | display | runtime | why |", "|---|---|---|---|"]
        for slug, disp, rt, why in result["unresolved_seats"]:
            lines.append(f"| {slug} | {disp} | {rt} | {why} |")
    else:
        lines.append("_none — all eligible seats resolved deterministically._")
    lines += ["", "## Per-profile provenance (reviewer line-read — #12093 delta 3)", "",
              "| profile | alias | wrapper hop | markers found | matched slug | verdict |",
              "|---|---|---|---|---|---|"]
    for r in result["provenance"]:
        mk = ", ".join(r["markers"]) or "—"
        lines.append(
            f"| {r['profile']} | `{r['alias']}` | {r['hop'] or '—'} | {mk} | "
            f"{r['matched'] or '—'} | {r['verdict']} |"
        )
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

    print(
        f"resolved {result['resolved_count']}/{result['eligible_count']} eligible seats"
        f" ({len(result['unresolved_seats'])} unresolved)",
        file=sys.stderr,
    )

    # P1-B (codex #12130): validate strict BEFORE writing anything — never leave
    # partial artifacts or overwrite the source manifest on a failed strict run
    # (no-partial-manifest contract, scope §6b). Fail loud first, write after.
    if args.strict and result["unresolved_seats"]:
        # unresolved_seats rows are 4-tuples (slug, display, runtime, why)
        names = ", ".join(row[0] for row in result["unresolved_seats"])
        print(f"FATAL (--strict): unresolved eligible seats: {names}", file=sys.stderr)
        sys.exit(1)

    if args.write:
        _atomic_write(MANIFEST_OUT, manifest)
        _atomic_write(RECON_OUT, recon)
        print(f"wrote {MANIFEST_OUT}")
        print(f"wrote {RECON_OUT}")
    else:
        print(manifest)


if __name__ == "__main__":
    main()
