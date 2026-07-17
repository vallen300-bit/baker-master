#!/usr/bin/env python3
"""Generate the Cockpit *page layout* (LAB_COCKPIT_PAGE_1, scope §5.1 / §6.4).

The cockpit page renders a plate-grouped card grid. Two things are needed that
the controller's live ``GET /api/agents`` does NOT carry: the plate grouping and
the app-claude (status-only) marking. Per scope §5.1 the grouping must *mirror
the live Lab Control Room* and be *verified against it at build* — and per §6.4
it is a *generated* artifact (same generator family as
``agent_identity_generated.sh``), never a list hand-kept inside the page JS.

This generator derives the layout from three live sources — fail-loud, no
hand-kept slug list:

  1. Live Lab Control Room grouping — ``CONTROL_GROUPS`` in
     ``brisen-lab/static/app.js`` — the authoritative mirror target (§5.1). It
     supplies the plate labels, plate order, and per-plate slug order (which
     keeps B1–B4 adjacent, §5.1). It is a frozen JSON-compatible literal.
  2. Agent registry (``agent_registry.yml``) — display_name, agent_id (AG-###),
     runtime, status. EVERY ``status: active`` seat gets a card (lead #12208
     ruling). A driveable card is a tmux seat (in the manifest); every other
     active seat is *status-only* (no ttyd, no iframe) and is badged by its
     runtime family — ``app-*`` → "APP", ``service`` → "SERVICE",
     ``headless*`` → "HEADLESS". The registry has NO class/group field, which
     is exactly why the grouping is sourced from the Control Room, not the
     registry (§5.1 wording is aspirational; flagged to lead 2026-07-17 #12159).
  3. The cockpit launch manifest (``cockpit_launch_manifest.json``) — the set of
     tmux-driveable seats and their ports. A card is *driveable* iff it is in
     the manifest; otherwise it is status-only.

Card set = every status:active registry seat (driveable if in the manifest,
else status-only). Every card is placed in its Control Room plate; a card whose slug is not directly in
CONTROL_GROUPS is placed by its base slug (``cowork-researcher`` -> the plate of
``researcher``); anything still unplaced lands in a trailing "Other" plate and
is reported (never silently dropped).

Regenerate with:  python3 scripts/generate_cockpit_layout.py --write
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY = Path(os.environ.get(
    "BAKER_AGENT_REGISTRY",
    os.path.expanduser("~/baker-vault/_ops/registries/agent_registry.yml"),
))
CONTROL_SRC = Path(os.environ.get(
    "COCKPIT_CONTROL_GROUPS_SRC",
    os.path.expanduser("~/bm-b1/brisen-lab/static/app.js"),
))
MANIFEST_IN = Path(os.environ.get(
    "COCKPIT_MANIFEST_IN", SCRIPT_DIR / "cockpit_launch_manifest.json"))
LAYOUT_OUT = Path(os.environ.get(
    "COCKPIT_LAYOUT_OUT", SCRIPT_DIR / "cockpit_static" / "cockpit_layout.json"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def _load_registry() -> dict:
    import yaml  # local import: only the generator needs pyyaml
    data = yaml.safe_load(REGISTRY.read_text())
    agents = data.get("agents") if isinstance(data, dict) else data
    if isinstance(agents, dict):
        agents = list(agents.values())
    return {a["slug"]: a for a in agents}


def _load_manifest_ports() -> dict:
    data = json.loads(MANIFEST_IN.read_text())
    return {e["slug"]: e["port"] for e in data.get("entries", [])}


def _parse_control_groups() -> list:
    """Extract CONTROL_GROUPS from the live Lab app.js.

    The literal is ``Object.freeze([ ["Label", ["slug", ...]], ... ])`` — pure
    double-quoted JSON once the freeze wrapper and any trailing commas are
    stripped. Fail loud if it can't be found or parsed (the whole point is
    build-time verification against the live Control Room)."""
    text = CONTROL_SRC.read_text()
    m = re.search(r"CONTROL_GROUPS\s*=\s*Object\.freeze\(\s*(\[[\s\S]*?\])\s*\)\s*;",
                  text)
    if not m:
        raise SystemExit(
            f"FATAL: CONTROL_GROUPS not found in {CONTROL_SRC} — cannot mirror "
            "the live Control Room (scope §5.1).")
    body = re.sub(r",(\s*[\]}])", r"\1", m.group(1))  # strip trailing commas
    try:
        arr = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FATAL: CONTROL_GROUPS not JSON-parseable: {exc}")
    return [(label, list(slugs)) for label, slugs in arr]


def build() -> dict:
    registry = _load_registry()
    ports = _load_manifest_ports()
    control = _parse_control_groups()

    driveable = set(ports)                       # in the tmux launch manifest
    # Every active seat gets a card (lead #12208). A driveable card is a tmux
    # seat; every other active seat is status-only. Matching only "app-claude"
    # once silently dropped app-codex (codex-arch, #12205) and non-app actives
    # like cortex (service); membership is now the whole active set.
    active = {s for s, a in registry.items()
              if str(a.get("status")) == "active"}
    app_seats = {s for s, a in registry.items()
                 if str(a.get("runtime", "")).startswith("app-")}
    card_slugs = active | driveable              # driveable ⊆ active in practice

    # slug -> plate label, from the Control Room curation (mirror target).
    plate_of: dict[str, str] = {}
    plate_order: list[str] = []
    for label, slugs in control:
        if label not in plate_order:
            plate_order.append(label)
        for s in slugs:
            plate_of.setdefault(s, label)

    def resolve_plate(slug: str) -> str | None:
        if slug in plate_of:
            return plate_of[slug]
        if slug.startswith("cowork-"):            # app sibling -> base plate
            base = slug[len("cowork-"):]
            if base in plate_of:
                return plate_of[base]
        return None

    def _kind_and_badge(slug: str, runtime: str):
        """Pill label + status-only badge for a card.

        driveable → ("TERMINAL", None); app-* → ("APP", None); every other
        status-only runtime family carries a badge so a service/headless seat
        reads distinctly from an app seat (lead #12208)."""
        if slug in driveable:
            return "TERMINAL", None
        if runtime.startswith("app-"):
            return "APP", None
        if runtime.startswith("headless"):
            return "HEADLESS", "headless"
        if runtime == "service":
            return "SERVICE", "service"
        cat = (runtime.split("-")[0] or "seat")
        return cat.upper(), cat

    def card_for(slug: str) -> dict:
        a = registry.get(slug, {})
        runtime = str(a.get("runtime", ""))
        kind, badge = _kind_and_badge(slug, runtime)
        return {
            "slug": slug,
            "alias": (a.get("aliases") or [slug])[0] if isinstance(a.get("aliases"), list) else slug,
            "agent_id": a.get("agent_id", ""),
            "display_name": a.get("display_name", slug),
            "driveable": slug in driveable,
            "app_seat": slug in app_seats,
            "status_only": slug not in driveable,
            "kind": kind,
            "badge": badge,
            "port": ports.get(slug),
        }

    # Build plates in Control Room order; within a plate keep Control Room slug
    # order (B1–B4 adjacency preserved), appending any base-slug-resolved extras.
    plates: list[dict] = []
    placed: set[str] = set()
    for label, slugs in control:
        cards = []
        for s in slugs:
            if s in card_slugs and s not in placed:
                cards.append(card_for(s)); placed.add(s)
        # app-claude siblings resolved to this plate but not listed here
        for s in sorted(card_slugs - placed):
            if resolve_plate(s) == label:
                cards.append(card_for(s)); placed.add(s)
        if cards:
            # de-dup label (Control Room lists each once, but be defensive)
            existing = next((p for p in plates if p["label"] == label), None)
            if existing:
                existing["cards"].extend(cards)
            else:
                plates.append({"label": label, "cards": cards})

    unplaced = sorted(card_slugs - placed)
    if unplaced:
        plates.append({"label": "Other",
                       "cards": [card_for(s) for s in unplaced]})

    return {
        "plates": plates,
        "counts": {
            "cards": len(card_slugs),
            "driveable": len(driveable & card_slugs),
            "status_only": len(card_slugs - driveable),
            "app_seat": len(app_seats & card_slugs),
            "unplaced": len(unplaced),
        },
        "unplaced": unplaced,
    }


def render(result: dict) -> str:
    header = {
        "_generated": "DO NOT EDIT BY HAND — regenerate with "
                      "scripts/generate_cockpit_layout.py --write",
        "_sources": {
            "registry": str(REGISTRY),
            "registry_sha256": _sha256(REGISTRY),
            "control_groups_source": str(CONTROL_SRC),
            "control_groups_sha256": _sha256(CONTROL_SRC),
            "manifest": str(MANIFEST_IN),
        },
        "_mirror": "plates + order mirror live Lab CONTROL_GROUPS (scope §5.1); "
                   "membership reconciled with registry runtime + launch manifest",
        "counts": result["counts"],
    }
    return json.dumps(
        {"meta": header,
         "plates": result["plates"]}, indent=2) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write layout to scripts/cockpit_static/cockpit_layout.json")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any card is unplaced (Other plate)")
    args = ap.parse_args()

    result = build()
    layout = render(result)
    c = result["counts"]
    print(f"cards {c['cards']} (driveable {c['driveable']}, status-only "
          f"{c['status_only']}, unplaced {c['unplaced']})", file=sys.stderr)

    if args.strict and result["unplaced"]:
        print(f"FATAL (--strict): unplaced cards: {', '.join(result['unplaced'])}",
              file=sys.stderr)
        sys.exit(1)

    if args.write:
        _atomic_write(LAYOUT_OUT, layout)
        print(f"wrote {LAYOUT_OUT}")
    else:
        print(layout)


if __name__ == "__main__":
    main()
