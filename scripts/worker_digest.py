#!/usr/bin/env python3
"""Daily digest — posts Slack summary of B-code worker activity over last 24h.

Triggered by launchd at 09:00 UTC daily via com.baker.worker-digest.plist.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Required env:
    BAKER_MASTER_URL    — baker-master base URL
    BAKER_KEY           — X-Baker-Key for /api/worker/digest auth
    SLACK_WEBHOOK_URL   — Director Slack webhook for summary post

Exit codes: always 0 (launchd hygiene).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta


def _slack(text: str, webhook: str) -> None:
    if not webhook:
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
        sys.stderr.write(f"slack POST failed: {e}\n")


def _fetch_digest(master_url: str, baker_key: str, since_iso: str) -> dict:
    from urllib.parse import quote
    url = f"{master_url}/api/worker/digest?since={quote(since_iso)}"
    req = urllib.request.Request(url, headers={"X-Baker-Key": baker_key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    master_url = os.environ.get("BAKER_MASTER_URL", "https://baker-master.onrender.com").rstrip("/")
    baker_key = os.environ.get("BAKER_KEY", "").strip()
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    if not baker_key:
        sys.stderr.write("BAKER_KEY not set; digest skipped\n")
        sys.exit(0)

    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat()

    try:
        data = _fetch_digest(master_url, baker_key, since)
    except Exception as e:
        _slack(f":warning: worker-digest fetch failed: {e}", slack_webhook)
        sys.exit(0)

    lines = [
        f":robot_face: *Worker digest — last 24h* ({now.strftime('%Y-%m-%d %H:%M UTC')})",
        "",
    ]
    any_activity = False
    for slug in ("b1", "b2", "b3", "b4"):
        s = data.get(slug) if isinstance(data, dict) else None
        if not isinstance(s, dict):
            lines.append(f"• *worker-{slug}*: 0 wakes")
            continue
        any_activity = True
        wake_count = int(s.get("wake_count", 0) or 0)
        tokens = int(s.get("total_tokens", 0) or 0)
        fail_count = int(s.get("fail_count", 0) or 0)
        breaker = " :rotating_light: BREAKER TRIPPED" if s.get("breaker_tripped") else ""
        lines.append(
            f"• *worker-{slug}*: {wake_count} wakes · ~{tokens:,} tokens · {fail_count} fails{breaker}"
        )

    total_cost = float(data.get("total_cost_eur", 0) or 0) if isinstance(data, dict) else 0.0
    lines.append("")
    lines.append(f"Total cost est: ~€{total_cost:.2f}")
    if not any_activity:
        lines.append("(no recorded wakes in window)")

    _slack("\n".join(lines), slack_webhook)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"digest crash: {e}\n")
        sys.exit(0)
