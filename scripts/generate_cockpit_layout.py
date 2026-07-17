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

  1. Director layout contract — ``director_layout_contract.json`` — the
     authoritative grouping source (LAB_COCKPIT_REDESIGN_1 D1, REPLACES the
     Control-Room mirror). It supplies the plate labels, plate order, per-plate
     card membership, the Director's display_name per card, and the x/y that
     drive in-plate order (row-band y±40 then x — same rule as the mock export).
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
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY = Path(os.environ.get(
    "BAKER_AGENT_REGISTRY",
    os.path.expanduser("~/baker-vault/_ops/registries/agent_registry.yml"),
))
CONTRACT_IN = Path(os.environ.get(
    "COCKPIT_LAYOUT_CONTRACT",
    SCRIPT_DIR / "cockpit_static" / "director_layout_contract.json"))
MANIFEST_IN = Path(os.environ.get(
    "COCKPIT_MANIFEST_IN", SCRIPT_DIR / "cockpit_launch_manifest.json"))
# In-plate order: cards on the same visual row (y within this band) read
# left-to-right by x; rows stack top-to-bottom. Mirrors the mock-v3 export sort.
ROW_BAND_PX = 40
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


def _load_contract() -> list:
    """Load the Director layout contract: [(label, [card, ...]), ...].

    Each card is the raw contract dict (slug, display_name, app, x, y). This is
    the Director's FINAL grouping + in-plate positions (mock-v3 export) and
    REPLACES the Control-Room mirror as the grouping source (LAB_COCKPIT_REDESIGN_1
    D1). Fail loud if the file is missing or malformed."""
    try:
        data = json.loads(CONTRACT_IN.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FATAL: cannot read layout contract {CONTRACT_IN}: {exc}")
    plates = data.get("plates")
    if not isinstance(plates, list) or not plates:
        raise SystemExit(f"FATAL: layout contract has no plates: {CONTRACT_IN}")
    out = []
    for p in plates:
        label = p.get("label")
        cards = p.get("cards") or []
        if not label:
            raise SystemExit(f"FATAL: contract plate missing label: {p}")
        out.append((label, list(cards)))
    return out


def _order_in_plate(cards: list) -> list:
    """Row-band sort (mock export rule): group cards whose y is within
    ROW_BAND_PX of a row's anchor, order rows top→bottom, within a row left→right
    by x. Keeps B1–B4 (one row) left-to-right and cowork rows below terminals."""
    bands: list[dict] = []
    for c in sorted(cards, key=lambda c: (c.get("y", 0), c.get("x", 0))):
        y = c.get("y", 0)
        band = next((b for b in bands if abs(y - b["y0"]) <= ROW_BAND_PX), None)
        if band is None:
            bands.append({"y0": y, "items": [c]})
        else:
            band["items"].append(c)
    ordered = []
    for b in sorted(bands, key=lambda b: b["y0"]):
        ordered.extend(sorted(b["items"], key=lambda c: c.get("x", 0)))
    return ordered


def build() -> dict:
    registry = _load_registry()
    ports = _load_manifest_ports()
    contract = _load_contract()

    driveable = set(ports)                       # in the tmux launch manifest
    # Every active seat gets a card (lead #12208). A driveable card is a tmux
    # seat; every other active seat is status-only. Membership + grouping now
    # come from the Director contract; the registry still gates which slugs are
    # live (active) and supplies runtime/driveable/ports.
    active = {s for s, a in registry.items()
              if str(a.get("status")) == "active"}
    app_seats = {s for s, a in registry.items()
                 if str(a.get("runtime", "")).startswith("app-")}

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

    def _notify_eligible(slug: str) -> bool:
        """LAB_COCKPIT_NOTIFY_SLICE_1 — should the cockpit controller fire a macOS
        banner when a bus dispatch lands unread on this seat?

        True iff the seat is app-resident (runtime ``app-*``) AND Wake.app does not
        already banner it. Wake.app (BUS_AUTOWAKE_APP_RESIDENT_NOTIFY_1) banners
        wake-registered app-claude seats — i.e. app-claude whose ``wakeable`` is not
        the explicit ``false`` override. So the residue the controller must cover is
        app-codex seats (codex-arch) + app-claude seats with ``wakeable: false``
        (the cowork desks). Terminal-* seats are self-awake / driven and are never
        notified (matches the AC: b1 → no banner). Classifier lead-approved
        2026-07-17 (bus #12332)."""
        a = registry.get(slug, {})
        runtime = str(a.get("runtime", ""))
        if not runtime.startswith("app-"):
            return False
        wake_registered = runtime == "app-claude" and a.get("wakeable") is not False
        return not wake_registered

    def card_for(slug: str, contract_name: str | None = None) -> dict:
        a = registry.get(slug, {})
        runtime = str(a.get("runtime", ""))
        kind, badge = _kind_and_badge(slug, runtime)
        # Director contract naming (de-Desked, mock-approved) wins where present;
        # registry display_name is the fallback (D1/D2 reconciliation).
        display = contract_name or a.get("display_name", slug)
        return {
            "slug": slug,
            "alias": (a.get("aliases") or [slug])[0] if isinstance(a.get("aliases"), list) else slug,
            "display_name": display,
            "driveable": slug in driveable,
            "app_seat": slug in app_seats,
            "status_only": slug not in driveable,
            "kind": kind,
            "badge": badge,
            "port": ports.get(slug),
            "notify_eligible": _notify_eligible(slug),
        }

    # Build plates in contract order; in-plate order = row-band(y±40) then x.
    # Fail loud on drift: a contract card whose slug is not an active registry
    # seat, or a duplicate slug, is reported; an active seat the contract omits
    # lands in a trailing "Unassigned" plate — never silently dropped (D1).
    plates: list[dict] = []
    placed: set[str] = set()
    unknown: list[tuple] = []      # (slug, plate) — contract refs a non-active seat
    duplicates: list[str] = []     # slug listed in >1 contract card
    for label, cards in contract:
        built = []
        for c in _order_in_plate(cards):
            slug = c.get("slug")
            if not slug:
                continue
            if slug in placed:
                duplicates.append(slug); continue
            if slug not in active:
                unknown.append((slug, label)); continue
            built.append(card_for(slug, c.get("display_name")))
            placed.add(slug)
        if built:
            plates.append({"label": label, "cards": built})

    unassigned = sorted(active - placed)
    if unassigned:
        plates.append({"label": "Unassigned",
                       "cards": [card_for(s) for s in unassigned]})

    drift = bool(unassigned or unknown or duplicates)
    return {
        "plates": plates,
        "counts": {
            "cards": len(placed) + len(unassigned),
            "driveable": len(driveable & placed),
            "status_only": len(placed - driveable) + len(unassigned),
            "app_seat": len(app_seats & placed),
            "unassigned": len(unassigned),
        },
        "unassigned": unassigned,
        "unknown": unknown,
        "duplicates": duplicates,
        "drift": drift,
    }


def render(result: dict) -> str:
    header = {
        "_generated": "DO NOT EDIT BY HAND — regenerate with "
                      "scripts/generate_cockpit_layout.py --write",
        "_sources": {
            "registry": str(REGISTRY),
            "registry_sha256": _sha256(REGISTRY),
            "layout_contract": str(CONTRACT_IN),
            "layout_contract_sha256": _sha256(CONTRACT_IN),
            "manifest": str(MANIFEST_IN),
        },
        "_grouping": "plates + order + in-plate position from the Director layout "
                     "contract (LAB_COCKPIT_REDESIGN_1 D1); membership gated by "
                     "registry active status + manifest driveable/ports",
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
          f"{c['status_only']}, unassigned {c['unassigned']})", file=sys.stderr)

    # Fail loud on any contract/registry drift (D1): active seat the contract
    # omits, contract card referencing a non-active seat, or a duplicate slug.
    if result["unassigned"]:
        print(f"DRIFT: active seats not in contract (Unassigned plate): "
              f"{', '.join(result['unassigned'])}", file=sys.stderr)
    if result["unknown"]:
        print(f"DRIFT: contract cards not active in registry: "
              f"{', '.join(f'{s} @{p}' for s, p in result['unknown'])}", file=sys.stderr)
    if result["duplicates"]:
        print(f"DRIFT: duplicate slugs in contract: "
              f"{', '.join(result['duplicates'])}", file=sys.stderr)
    if args.strict and result["drift"]:
        print("FATAL (--strict): contract/registry drift — see DRIFT lines above.",
              file=sys.stderr)
        sys.exit(1)

    if args.write:
        _atomic_write(LAYOUT_OUT, layout)
        print(f"wrote {LAYOUT_OUT}")
    else:
        print(layout)


if __name__ == "__main__":
    main()
