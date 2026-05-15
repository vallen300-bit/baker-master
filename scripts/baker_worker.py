#!/usr/bin/env python3
"""Self-wake worker for B-codes — Stage 3 Phase 1.

Invoked by launchd every 120s per B-code. One python process per wake cycle.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Required env (set in launchd plist):
    BAKER_WORKER_SLUG        — b1 / b2 / b3 / b4
    BAKER_WORKER_ENABLED     — "true" to run; anything else -> exit 0
    BAKER_WORKER_STATE_DIR   — abs path to worker state dir
    BAKER_WORKER_PICKER_DIR  — abs path to ~/bm-b{N}
    BRISEN_LAB_DAEMON_URL    — default https://brisen-lab.onrender.com
    BAKER_MASTER_URL         — default https://baker-master.onrender.com
    BAKER_KEY                — for /api/worker/wake auth (X-Baker-Key header)
    SLACK_WEBHOOK_URL        — for breaker + cost-cap-first-hit pushes
    PATH                     — must include /opt/homebrew/bin (for `claude`)

Exit codes: always 0 (launchd treats non-zero as crash; worker logs failures
internally + via Slack/breaker).

Token accounting: worker invokes `claude --print --output-format=json`. Final
stdout is a JSON dict with `modelUsage[<model>].inputTokens / outputTokens /
cacheReadInputTokens / cacheCreationInputTokens` (probe 2026-05-15). Token
total = sum of those four across all model keys. Falls back to `usage` keys
(input_tokens, output_tokens, cache_*) for older claude versions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# -- Constants ---------------------------------------------------------------

CLAUDE_BIN = "/opt/homebrew/bin/claude"
CLAUDE_TIMEOUT_S = 600
POLL_TIMEOUT_S = 8
AUDIT_TIMEOUT_S = 10
ACK_TIMEOUT_S = 5
RATE_CAP_PER_HOUR = 4
COST_CAP_TOKENS_PER_DAY = 100_000
BREAKER_FAILS = 3
PROCESSED_FIFO_SIZE = 200
LOCK_STALE_S = 900  # 15 min — older lock treated as orphan

# Fallback token count when --output-format=json doesn't surface usage.
# 1000 tokens/wake keeps cost cap at ~100 wakes/day (well above 4/hr rate cap).
FALLBACK_TOKENS_PER_WAKE = 1000

# Tokens-to-EUR rough conversion. Refined after first 7d burn-in vs Anthropic
# invoice. Worker-side cost cap is enforced in tokens (deterministic) — this
# value only affects the cost_eur_est field stored to baker_actions.
EUR_PER_TOKEN = 0.0001


# -- Setup -------------------------------------------------------------------

def _env_or_die(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.stderr.write(f"missing required env: {name}\n")
        sys.exit(0)
    return v


def _slack(text: str, webhook: str) -> None:
    """Best-effort Slack push; swallow failures."""
    if not webhook:
        return
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# -- State -------------------------------------------------------------------

def _default_state() -> dict:
    return {
        "cursor": "1970-01-01T00:00:00Z",
        "processed_ids": [],
        "tokens_today": 0,
        "tokens_today_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "recent_wakes_60min": [],
        "consecutive_fails": 0,
        "breaker": {"tripped": False, "trip_ts": None, "reason": None},
        "cost_cap_hit_today": False,
    }


def _load_state(state_file: Path) -> dict:
    default = _default_state()
    if not state_file.exists():
        return default
    try:
        on_disk = json.loads(state_file.read_text())
        if not isinstance(on_disk, dict):
            return default
        merged = {**default, **on_disk}
        # Force-type-coerce critical fields (state file corruption tolerance)
        merged["recent_wakes_60min"] = [
            float(x) for x in merged.get("recent_wakes_60min", []) if isinstance(x, (int, float))
        ]
        merged["processed_ids"] = [
            int(x) for x in merged.get("processed_ids", []) if isinstance(x, int)
        ]
        merged["tokens_today"] = int(merged.get("tokens_today", 0) or 0)
        return merged
    except Exception:
        return default


def _save_state(state_file: Path, s: dict) -> None:
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, sort_keys=True))
    tmp.replace(state_file)


# -- Lock --------------------------------------------------------------------

def _lock_alive(lock_file: Path) -> bool:
    """True if a prior wake or interactive picker holds the lock.

    Lock is stale-collected when:
      - file unreadable / malformed JSON
      - start_ts age > LOCK_STALE_S
      - pid does not exist (os.kill signal 0 raises ProcessLookupError)
    """
    if not lock_file.exists():
        return False
    try:
        lock = json.loads(lock_file.read_text())
        pid = int(lock["pid"])
        start_ts = float(lock["start_ts"])
        if (time.time() - start_ts) > LOCK_STALE_S:
            lock_file.unlink(missing_ok=True)
            return False
        os.kill(pid, 0)  # signal 0 = liveness check (no signal sent)
        return True
    except (ProcessLookupError, OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        lock_file.unlink(missing_ok=True)
        return False


def _write_lock(lock_file: Path, source: str = "self_wake_worker") -> None:
    lock_file.write_text(json.dumps({
        "pid": os.getpid(),
        "start_ts": time.time(),
        "source": source,
    }))


def _delete_lock(lock_file: Path) -> None:
    lock_file.unlink(missing_ok=True)


# -- Terminal key ------------------------------------------------------------

def _read_key(key_file: Path, slack_webhook: str, slug: str) -> str:
    if not key_file.exists():
        _slack(f":rotating_light: worker-{slug} terminal-key missing at {key_file}", slack_webhook)
        sys.exit(0)
    key = key_file.read_text().strip()
    if not key:
        _slack(f":rotating_light: worker-{slug} terminal-key empty at {key_file}", slack_webhook)
        sys.exit(0)
    return key


# -- Bus I/O -----------------------------------------------------------------

def _poll_bus(lab_url: str, slug: str, cursor: str, key: str) -> list[dict]:
    """GET /msg/<slug>?since=<cursor>. Tolerates 5xx + network as no-op (no breaker hit)."""
    url = f"{lab_url}/msg/{slug}?since={urllib_quote(cursor)}"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=POLL_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            return []
        # 4xx is a breaker-tick signal (raised to caller)
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("messages") or data.get("rows") or []
    else:
        rows = []
    return [m for m in rows if isinstance(m, dict) and "id" in m]


def _ack_message(lab_url: str, msg_id: int, key: str) -> bool:
    url = f"{lab_url}/msg/{msg_id}/ack"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=ACK_TIMEOUT_S)
        return True
    except Exception:
        return False


def urllib_quote(s: str) -> str:
    """Minimal URL-quote for cursor timestamps; stdlib import lifted to local fn."""
    from urllib.parse import quote
    return quote(str(s), safe="")


# -- Claude invocation -------------------------------------------------------

def _invoke_claude(picker_dir: Path) -> tuple[int, str, str, float]:
    """Run claude --print --output-format=json non-interactively.

    Returns (exit_code, stdout, stderr, duration_s).
    """
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [
                CLAUDE_BIN, "--print", "--output-format=json",
                "Wake. New bus messages. Read your CLAUDE.md, drain inbox, act per orientation.",
            ],
            cwd=str(picker_dir),
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_S,
        )
        return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + "\n[timeout]", time.monotonic() - start
    except FileNotFoundError:
        return 127, "", f"claude binary not found at {CLAUDE_BIN}", time.monotonic() - start


def _parse_tokens(stdout: str) -> int:
    """Parse token count from `claude --print --output-format=json` stdout.

    Probe (2026-05-15): top-level JSON dict carries `usage` + `modelUsage` keys.
    `modelUsage[<model>]` has camelCase keys (inputTokens, outputTokens,
    cacheReadInputTokens, cacheCreationInputTokens). `usage` has snake_case
    versions that go to zero on budget-cap errors. Preferred path = modelUsage.

    Fallback: FALLBACK_TOKENS_PER_WAKE constant when no JSON / no usage data
    (rate + wake-count caps still bound damage).
    """
    if not stdout:
        return FALLBACK_TOKENS_PER_WAKE
    try:
        doc = json.loads(stdout.strip().splitlines()[-1])
    except Exception:
        try:
            doc = json.loads(stdout)
        except Exception:
            return FALLBACK_TOKENS_PER_WAKE
    if not isinstance(doc, dict):
        return FALLBACK_TOKENS_PER_WAKE

    total = 0
    model_usage = doc.get("modelUsage") or {}
    if isinstance(model_usage, dict):
        for _, mu in model_usage.items():
            if not isinstance(mu, dict):
                continue
            for k in ("inputTokens", "outputTokens",
                      "cacheReadInputTokens", "cacheCreationInputTokens"):
                v = mu.get(k)
                if isinstance(v, (int, float)):
                    total += int(v)
    if total > 0:
        return total

    usage = doc.get("usage") or {}
    if isinstance(usage, dict):
        for k in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens"):
            v = usage.get(k)
            if isinstance(v, (int, float)):
                total += int(v)
    return total if total > 0 else FALLBACK_TOKENS_PER_WAKE


# -- Audit -------------------------------------------------------------------

def _audit_log(master_url: str, baker_key: str, payload: dict) -> None:
    """POST audit row to baker-master /api/worker/wake. Swallow failures."""
    if not baker_key:
        return
    url = f"{master_url}/api/worker/wake"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-Baker-Key": baker_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=AUDIT_TIMEOUT_S)
    except Exception as e:
        sys.stderr.write(f"audit POST failed: {e}\n")


# -- Time-window helpers -----------------------------------------------------

def _prune_old_wakes(wakes: list[float], window_s: int = 3600) -> list[float]:
    cutoff = time.time() - window_s
    return [w for w in wakes if w > cutoff]


def _maybe_reset_daily_cost(state: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("tokens_today_date") != today:
        state["tokens_today"] = 0
        state["tokens_today_date"] = today
        state["cost_cap_hit_today"] = False


# -- Main --------------------------------------------------------------------

def main() -> None:
    # Kill switch — exit silently if not enabled
    if os.environ.get("BAKER_WORKER_ENABLED", "").lower() != "true":
        sys.exit(0)

    slug = _env_or_die("BAKER_WORKER_SLUG")
    state_dir = Path(_env_or_die("BAKER_WORKER_STATE_DIR"))
    picker_dir = Path(_env_or_die("BAKER_WORKER_PICKER_DIR"))
    lab_url = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com").rstrip("/")
    master_url = os.environ.get("BAKER_MASTER_URL", "https://baker-master.onrender.com").rstrip("/")
    baker_key = os.environ.get("BAKER_KEY", "").strip()
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    state_file = state_dir / "state.json"
    key_file = state_dir / "key"
    lock_file = state_dir / "wake.lock"

    # Lock — skip if a prior wake or interactive picker holds it
    if _lock_alive(lock_file):
        sys.exit(0)

    state = _load_state(state_file)

    # Breaker check
    if state["breaker"].get("tripped"):
        sys.exit(0)

    # Rate cap — prune old, count window
    state["recent_wakes_60min"] = _prune_old_wakes(state["recent_wakes_60min"])
    if len(state["recent_wakes_60min"]) >= RATE_CAP_PER_HOUR:
        _save_state(state_file, state)
        sys.exit(0)

    # Cost cap (daily reset first)
    _maybe_reset_daily_cost(state)
    if state["tokens_today"] >= COST_CAP_TOKENS_PER_DAY:
        if not state.get("cost_cap_hit_today"):
            _slack(
                f":money_with_wings: worker-{slug} hit daily token cap "
                f"({COST_CAP_TOKENS_PER_DAY}); sleeping until 00:00 UTC",
                slack_webhook,
            )
            state["cost_cap_hit_today"] = True
            _save_state(state_file, state)
        sys.exit(0)

    key = _read_key(key_file, slack_webhook, slug)

    # Poll — tolerate 4xx by ticking the breaker, 5xx silently
    try:
        msgs = _poll_bus(lab_url, slug, state["cursor"], key)
    except urllib.error.HTTPError as e:
        state["consecutive_fails"] += 1
        if state["consecutive_fails"] >= BREAKER_FAILS:
            state["breaker"] = {
                "tripped": True,
                "trip_ts": datetime.now(timezone.utc).isoformat(),
                "reason": f"poll HTTP {e.code} after {BREAKER_FAILS} fails",
            }
            _slack(
                f":rotating_light: worker-{slug} circuit breaker TRIPPED — {state['breaker']['reason']}. "
                "Manual re-enable required.",
                slack_webhook,
            )
        _save_state(state_file, state)
        sys.exit(0)

    new_msgs = [m for m in msgs if m["id"] not in state["processed_ids"]]
    if not new_msgs:
        # Successful empty poll resets the consecutive-fail counter
        state["consecutive_fails"] = 0
        _save_state(state_file, state)
        sys.exit(0)

    # Got work — write lock, invoke claude
    _write_lock(lock_file)
    try:
        wake_ts = datetime.now(timezone.utc).isoformat()
        exit_code, stdout, stderr, duration = _invoke_claude(picker_dir)
        tokens = _parse_tokens(stdout)

        # Ack each drained message (best-effort; per-msg failure isolated)
        for m in new_msgs:
            _ack_message(lab_url, int(m["id"]), key)

        # State updates
        state["recent_wakes_60min"].append(time.time())
        state["tokens_today"] += tokens
        try:
            latest_cursor = max(
                str(m.get("created_at") or "") for m in new_msgs
            )
            if latest_cursor:
                state["cursor"] = latest_cursor
        except Exception:
            pass
        new_ids = [int(m["id"]) for m in new_msgs if isinstance(m.get("id"), int)]
        state["processed_ids"] = (state["processed_ids"] + new_ids)[-PROCESSED_FIFO_SIZE:]

        # Breaker logic — increment on failure, reset on success
        if exit_code != 0:
            state["consecutive_fails"] += 1
            if state["consecutive_fails"] >= BREAKER_FAILS:
                state["breaker"] = {
                    "tripped": True,
                    "trip_ts": wake_ts,
                    "reason": f"claude exit {exit_code} after {BREAKER_FAILS} consecutive fails",
                }
                _slack(
                    f":rotating_light: worker-{slug} circuit breaker TRIPPED — "
                    f"{state['breaker']['reason']}. Manual re-enable required.",
                    slack_webhook,
                )
        else:
            state["consecutive_fails"] = 0

        # Audit log
        _audit_log(master_url, baker_key, {
            "worker_slug": slug,
            "wake_ts": wake_ts,
            "messages_drained": len(new_msgs),
            "message_ids": new_ids,
            "claude_exit_code": exit_code,
            "claude_stdout_tokens": tokens,
            "claude_stderr_truncated": (stderr or "")[-2000:],
            "duration_seconds": round(duration, 3),
            "cost_eur_est": round(tokens * EUR_PER_TOKEN, 4),
        })

        _save_state(state_file, state)
    finally:
        _delete_lock(lock_file)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"worker crash: {e}\n")
        sys.exit(0)
