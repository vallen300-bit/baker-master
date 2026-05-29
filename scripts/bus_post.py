#!/usr/bin/env python3
"""bus_post.py — AI Head outbound auto-post (richer payload variant).

Usage:
    bus_post.py --to lead --body "..." [--topic ...] [--parent-id N] [--kind dispatch] [--tier B]
    bus_post.py --to lead,deputy --body "..."  # multiple recipients
    BAKER_ROLE=aid bus_post.py --to lead --body "..."  # AID-Terminal sender

Companion to scripts/bus_post.sh. Use the .sh for one-liner dispatches; the
.py when you need parent_id chains, multi-recipient broadcasts, or multiline
bodies that shell-quote awkwardly.

Director ratified 2026-05-06 OPTION A + policy (ii): op-fetch sender key on demand.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DAEMON_URL = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com")

VALID_SLUGS = {
    "director", "cowork-ah1", "lead", "deputy", "architect",
    "b1", "b2", "b3", "b4", "b5",
    "cortex", "daemon", "aid", "codex",
}

ROLE_TO_SLUG = {
    "AH1": "lead", "aihead1": "lead", "lead": "lead", "LEAD": "lead",
    "AH2": "deputy", "aihead2": "deputy", "deputy": "deputy", "DEPUTY": "deputy",
    "B1": "b1", "b1": "b1",
    "B2": "b2", "b2": "b2",
    "B3": "b3", "b3": "b3",
    "B4": "b4", "b4": "b4",
    "B5": "b5", "b5": "b5",
    "architect": "architect", "ARCHITECT": "architect",
    "cortex": "cortex", "CORTEX": "cortex",
    "aid": "aid", "AID": "aid",
    "codex": "codex", "CODEX": "codex",
}


def _resolve_sender() -> str:
    role = os.environ.get("BAKER_ROLE", "")
    if role not in ROLE_TO_SLUG:
        sys.exit(
            f"ERROR: BAKER_ROLE not set or unrecognized: {role!r}. "
            f"Valid: AH1, AH2, B1-B5, architect, cortex, aid, codex"
        )
    return ROLE_TO_SLUG[role]


def _fetch_key(sender: str) -> str:
    ref = f"op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_{sender}/credential"
    try:
        out = subprocess.run(
            ["op", "read", ref],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        sys.exit(f"ERROR: 1Password CLI fetch failed: {e}")
    if out.returncode != 0:
        sys.exit(
            f"ERROR: 1Password fetch returned non-zero for {sender}: "
            f"{out.stderr.strip()}"
        )
    key = out.stdout.strip()
    if not key:
        sys.exit(f"ERROR: 1Password returned empty key for {sender}")
    return key


def _post(recipient: str, payload: dict, key: str) -> dict:
    url = f"{DAEMON_URL}/msg/{recipient}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-Terminal-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: POST {url} returned HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: POST {url} failed: {e.reason}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", required=True, help="comma-separated recipient slug(s)")
    ap.add_argument("--body", required=True, help="message body")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--parent-id", type=int, default=None)
    ap.add_argument("--thread-id", default=None)
    ap.add_argument(
        "--kind", default="dispatch",
        choices=["dispatch", "ack", "broadcast", "ratify_required", "ratify_decision"],
    )
    ap.add_argument("--tier", default="B", choices=["B", "A", "director_only"])
    args = ap.parse_args()

    recipients = [r.strip() for r in args.to.split(",") if r.strip()]
    # F2-FU-1: director-recipient is daemon-gated (BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED).
    # Single control point — script passes through; daemon enforces.
    bad = [r for r in recipients if r not in VALID_SLUGS]
    if bad:
        sys.exit(f"ERROR: unknown slug(s): {bad}. Valid: {sorted(VALID_SLUGS)}")

    sender = _resolve_sender()
    key = _fetch_key(sender)

    payload: dict = {
        "kind": args.kind,
        "body": args.body,
        "to": recipients,
        "tier_required": args.tier,
    }
    if args.topic is not None:
        payload["topic"] = args.topic
    if args.parent_id is not None:
        payload["parent_id"] = args.parent_id
    if args.thread_id is not None:
        payload["thread_id"] = args.thread_id

    # POST to first recipient with full to=[list] in body. Daemon's
    # POST /msg/{terminal} is single-pathed but accepts multi-recipient body.
    result = _post(recipients[0], payload, key)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
