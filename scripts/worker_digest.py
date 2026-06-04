#!/usr/bin/env python3
"""Daily digest — Slack summary of B-code self-wake activity in last 24h.

Triggered by launchd at 09:00 UTC daily via com.baker.worker-digest.plist.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Calls GET /api/worker/digest?since=<iso> on baker-master, formats one
Slack message with per-worker line + total cost, posts to SLACK_WEBHOOK_URL.

Required env:
    BAKER_MASTER_URL    — default https://baker-master.onrender.com
    BAKER_API_KEY       — for /api/worker/digest auth
    SLACK_WEBHOOK_URL   — destination

Exit codes: always 0 (launchd treats non-zero as crash).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta


def _post_slack(webhook: str, text: str) -> None:
    if not webhook:
        sys.stderr.write("digest: SLACK_WEBHOOK_URL unset; skipping post\n")
        return
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                webhook,
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=10,
        )
    except Exception as e:
        sys.stderr.write(f"digest: Slack post failed: {e!r}\n")


def _fetch_digest(master_url: str, baker_key: str, since_iso: str) -> dict | None:
    qs = urllib.parse.urlencode({"since": since_iso})
    url = f"{master_url}/api/worker/digest?{qs}"
    req = urllib.request.Request(url, headers={"X-Baker-Key": baker_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        sys.stderr.write(f"digest: fetch failed: {e!r}\n")
        return None


def _format(data: dict, since_iso: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f":robot_face: *Worker digest — last 24h* ({now})", ""]
    any_activity = False
    for slug in ("b1", "b2", "b3", "b4"):
        s = data.get(slug)
        if not s:
            lines.append(f"• *worker-{slug}*: idle")
            continue
        any_activity = True
        wake_count = int(s.get("wake_count", 0))
        tokens = int(s.get("total_tokens", 0))
        fail_count = int(s.get("fail_count", 0))
        breaker = " :rotating_light: BREAKER" if s.get("breaker_tripped") else ""
        lines.append(
            f"• *worker-{slug}*: {wake_count} wakes · ~{tokens:,} tokens "
            f"· {fail_count} fails{breaker}"
        )
    lines.append("")
    lines.append(f"Total cost est: ~€{float(data.get('total_cost_eur', 0) or 0):.2f}")
    if not any_activity:
        lines.append("(All four workers idle — no bus traffic in the window.)")
    lines.append(f"Window since: {since_iso}")
    return "\n".join(lines)


def main() -> None:
    master_url = os.environ.get("BAKER_MASTER_URL", "https://baker-master.onrender.com").rstrip("/")
    baker_key = os.environ.get("BAKER_API_KEY", "")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not baker_key:
        sys.stderr.write("digest: BAKER_API_KEY required\n")
        sys.exit(0)

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    data = _fetch_digest(master_url, baker_key, since)
    if data is None:
        _post_slack(
            slack_webhook,
            f":warning: Worker digest fetch failed at {datetime.now(timezone.utc).isoformat()}; "
            f"check baker-master /api/worker/digest.",
        )
        sys.exit(0)
    _post_slack(slack_webhook, _format(data, since))
    sys.exit(0)


if __name__ == "__main__":
    main()
