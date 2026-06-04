#!/usr/bin/env python3
"""Self-wake worker for B-codes — Stage 3 Phase 1.

Invoked by launchd every 120s per B-code. One python process per wake cycle.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Per-cycle flow:
    1. Kill switch (BAKER_WORKER_ENABLED) — exit 0 if not 'true'.
    2. wake.lock check — exit 0 if a prior wake / interactive picker holds it.
    3. Breaker check — exit 0 if state.breaker.tripped (manual reset).
    4. Rate cap (4 wakes / 60min) — exit 0 if hit.
    5. Daily token cap (100K / day, reset 00:00 UTC) — exit 0 + Slack push first hit.
    6. Poll bus GET /msg/<slug>?since=<cursor> with X-Terminal-Key. 5xx tolerated.
    7. Filter against state.processed_ids (FIFO last 200).
    8. New msgs → claim wake.lock → invoke `claude --print --output-format=json`
       in cwd=picker-dir → parse usage from final JSON line → ack each msg →
       update cursor + processed_ids → audit POST /api/worker/wake → drop lock.
    9. claude exit != 0 OR HTTP 4xx → consecutive_fails++; >=3 → breaker trip + Slack.
    10. Success → consecutive_fails reset.

Required env (set in launchd plist):
    BAKER_WORKER_SLUG        — b1 / b2 / b3 / b4
    BAKER_WORKER_ENABLED     — "true" to run; anything else → exit 0
    BAKER_WORKER_STATE_DIR   — abs path to worker state dir
    BAKER_WORKER_PICKER_DIR  — abs path to ~/bm-b{N}
    BRISEN_LAB_DAEMON_URL    — default https://brisen-lab.onrender.com
    BAKER_MASTER_URL         — default https://baker-master.onrender.com
    BAKER_API_KEY            — for /api/worker/wake auth (matches dashboard env name)
    SLACK_WEBHOOK_URL        — for breaker + cost-cap-first-hit pushes (optional)
    PATH                     — must include /opt/homebrew/bin (claude + op)

Exit codes: ALWAYS 0. launchd treats non-zero as crash + spawns faster.
Worker logs failures locally + via Slack/breaker.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
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
# Orphan-lock reclaim window — applies ONLY when the recorded PID is dead.
# A live PID keeps the lock alive regardless of age so long interactive
# picker sessions (>15min builds) don't get racing wakes. 4h covers any
# realistic Director session; orphan from a worker crash is reclaimed
# next cycle once the writer's PID is gone.
LOCK_STALE_S = 14400
EUR_PER_TOKEN_FALLBACK = 0.0001   # used only when JSON probe omits total_cost_usd
USD_TO_EUR_FALLBACK = 0.92        # rough; refined after first 7d burn-in


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slack(webhook: str, text: str) -> None:
    """Best-effort Slack push; swallow failures (worker keeps running)."""
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


def _load_state(state_file: Path, slack_webhook: str, slug: str) -> dict:
    default = _default_state()
    if not state_file.exists():
        return default
    try:
        loaded = json.loads(state_file.read_text())
        return {**default, **loaded}
    except Exception as e:
        _slack(slack_webhook, f":warning: worker-{slug} state.json unreadable ({e}); reset to defaults")
        return default


def _save_state(state_file: Path, state: dict) -> None:
    """Atomic write via tmp + replace — never leave a half-written state.json."""
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(state_file)


def _read_key(key_file: Path, slack_webhook: str, slug: str) -> str | None:
    if not key_file.exists():
        _slack(slack_webhook, f":rotating_light: worker-{slug} terminal-key file missing at {key_file}")
        return None
    try:
        return key_file.read_text().strip()
    except Exception as e:
        _slack(slack_webhook, f":rotating_light: worker-{slug} terminal-key unreadable ({e})")
        return None


def _lock_alive(lock_file: Path) -> bool:
    """True iff the lock writer is still alive.

    PID check is authoritative: a live PID means the lock is real, regardless
    of age (long interactive picker sessions are common). The stale window
    only matters as an orphan-reclaim fallback for locks whose writer PID is
    gone. Corrupted / unreadable locks are reclaimed immediately.
    """
    if not lock_file.exists():
        return False
    try:
        lock = json.loads(lock_file.read_text())
        pid = int(lock["pid"])
        age = time.time() - float(lock["start_ts"])
    except (KeyError, ValueError, json.JSONDecodeError, OSError):
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass
        return False

    try:
        os.kill(pid, 0)   # signal 0 = liveness probe
        return True       # writer still alive → lock holds
    except ProcessLookupError:
        # Writer gone. Reclaim only if the lock is also old enough to look
        # like an orphan (avoids a SessionEnd race where the picker just
        # exited but the worker's next cycle hasn't seen it yet).
        if age > LOCK_STALE_S:
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
            return False
        return True   # recent + writer just exited → conservative hold
    except PermissionError:
        # Different uid owns the PID — treat as alive (don't reclaim what
        # we can't probe).
        return True


def _write_lock(lock_file: Path) -> None:
    payload = {"pid": os.getpid(), "start_ts": time.time(), "source": "baker_worker"}
    lock_file.write_text(json.dumps(payload))


def _delete_lock(lock_file: Path) -> None:
    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass


def _poll_bus(base: str, slug: str, cursor: str, key: str) -> tuple[list[dict], int | None]:
    """Returns (messages, http_status_or_none).

    HTTP 5xx → ([], status). 4xx → ([], status). 200 → (rows, 200).
    Network exception → ([], None) — tolerated, no breaker tick.
    """
    qs = urllib.parse.urlencode({"since": cursor, "limit": 50})
    url = f"{base}/msg/{slug}?{qs}"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=POLL_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("messages") or data.get("rows") or []
            else:
                rows = []
            return rows, resp.status
    except urllib.error.HTTPError as e:
        return [], e.code
    except urllib.error.URLError:
        return [], None
    except Exception:
        return [], None


def _ack_message(base: str, msg_id: int, key: str) -> bool:
    url = f"{base}/msg/{msg_id}/ack"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=ACK_TIMEOUT_S)
        return True
    except Exception:
        return False


def _invoke_claude(picker_dir: Path) -> tuple[int, str, str, float]:
    """Run claude --print --output-format=json non-interactively.

    Returns (exit_code, stdout, stderr, duration_s). Stdout's last line is a
    JSON usage record (parsed by _parse_usage). Timeout treated as exit 124
    (matches GNU `timeout`). Any other exception → (1, "", str(e), duration).
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
    except Exception as e:
        return 1, "", f"claude invocation failed: {e!r}", time.monotonic() - start


def _parse_usage(stdout: str) -> tuple[int, float | None]:
    """Parse claude --print --output-format=json final-line JSON for tokens + cost.

    Returns (total_tokens, cost_usd_or_None). Falls back to (0, None) on any
    parse failure — caller then estimates EUR via EUR_PER_TOKEN_FALLBACK
    constant. Token total includes input + output + cache_creation +
    cache_read so the 100K/day cap reflects full work done, not just billable
    surface. (Cache creation dominates --print invocations because each wake
    is a fresh session; this keeps the cap honest.)

    Probe outcome (2026-05-15 against claude 2.1.111):
        {"type":"result", ..., "usage":{"input_tokens":6,
         "cache_creation_input_tokens":42508, "cache_read_input_tokens":0,
         "output_tokens":13, ...}, "total_cost_usd":0.26603, ...}
    """
    if not stdout:
        return 0, None
    # Grab the last non-empty line and try to parse as JSON. claude --print
    # --output-format=json emits a single JSON object on one line; use
    # last-line semantics so any pre-roll noise (rare) is ignored.
    last_line = ""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line:
            last_line = line
            break
    if not last_line:
        return 0, None
    try:
        obj = json.loads(last_line)
    except Exception:
        return 0, None
    usage = obj.get("usage") if isinstance(obj, dict) else None
    if not isinstance(usage, dict):
        return 0, None
    total = 0
    for key in ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = usage.get(key)
        if isinstance(val, int):
            total += val
    cost_usd = obj.get("total_cost_usd") if isinstance(obj.get("total_cost_usd"), (int, float)) else None
    return total, cost_usd


def _audit_log(master_url: str, baker_key: str, payload: dict) -> bool:
    """POST audit to baker-master /api/worker/wake. Returns True on 200.

    Failure swallowed (already locally logged via launchd stdout/err →
    ~/Library/Logs/), but flagged via return value so caller can decide
    whether to count it toward consecutive_fails (HTTP 4xx counts; 5xx
    + network blip don't, matching the bus-poll tolerance pattern).
    """
    if not baker_key:
        sys.stderr.write("audit POST skipped: no BAKER_API_KEY\n")
        return False
    url = f"{master_url}/api/worker/wake"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"X-Baker-Key": baker_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=AUDIT_TIMEOUT_S)
        return True
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"audit POST {e.code}: {e.reason}\n")
        return False
    except Exception as e:
        sys.stderr.write(f"audit POST failed: {e!r}\n")
        return False


def _prune_old_wakes(wakes: list[float], window_s: int = 3600) -> list[float]:
    cutoff = time.time() - window_s
    return [w for w in wakes if w > cutoff]


def _maybe_reset_daily_cost(state: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state["tokens_today_date"] != today:
        state["tokens_today"] = 0
        state["tokens_today_date"] = today
        state["cost_cap_hit_today"] = False


def _est_cost_eur(tokens: int, cost_usd: float | None) -> float:
    if cost_usd is not None:
        return round(float(cost_usd) * USD_TO_EUR_FALLBACK, 4)
    return round(tokens * EUR_PER_TOKEN_FALLBACK, 4)


def _run_cycle() -> int:
    """One worker cycle. Returns exit status (always 0 to launchd; internal).

    Split out from main() so unit tests can drive it without touching
    sys.exit / process state. Returns:
        0 — normal exit (no-op or successful wake)
        1 — anomalous (kept for tests; main() always rewrites to 0)
    """
    slug = os.environ.get("BAKER_WORKER_SLUG", "").strip().lower()
    if slug not in ("b1", "b2", "b3", "b4"):
        sys.stderr.write(f"worker: invalid BAKER_WORKER_SLUG={slug!r}\n")
        return 1

    if os.environ.get("BAKER_WORKER_ENABLED", "").strip().lower() != "true":
        return 0   # kill switch — silent exit

    state_dir_raw = os.environ.get("BAKER_WORKER_STATE_DIR", "")
    picker_dir_raw = os.environ.get("BAKER_WORKER_PICKER_DIR", "")
    if not state_dir_raw or not picker_dir_raw:
        sys.stderr.write("worker: BAKER_WORKER_STATE_DIR / BAKER_WORKER_PICKER_DIR required\n")
        return 1
    state_dir = Path(state_dir_raw)
    picker_dir = Path(picker_dir_raw)
    if not picker_dir.exists():
        sys.stderr.write(f"worker: picker dir missing: {picker_dir}\n")
        return 1
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / "state.json"
    key_file = state_dir / "key"
    lock_file = state_dir / "wake.lock"

    lab_url = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com").rstrip("/")
    master_url = os.environ.get("BAKER_MASTER_URL", "https://baker-master.onrender.com").rstrip("/")
    baker_key = os.environ.get("BAKER_API_KEY", "")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "")

    # Concurrent-picker collision: skip if a prior wake or interactive
    # claude session in this picker still holds the lock.
    if _lock_alive(lock_file):
        return 0

    state = _load_state(state_file, slack_webhook, slug)

    # Breaker — manual re-enable required (state.breaker.tripped=false).
    if state["breaker"]["tripped"]:
        return 0

    # Rate cap.
    state["recent_wakes_60min"] = _prune_old_wakes(state["recent_wakes_60min"])
    if len(state["recent_wakes_60min"]) >= RATE_CAP_PER_HOUR:
        _save_state(state_file, state)
        return 0

    # Cost cap (daily reset first).
    _maybe_reset_daily_cost(state)
    if state["tokens_today"] >= COST_CAP_TOKENS_PER_DAY:
        if not state["cost_cap_hit_today"]:
            _slack(
                slack_webhook,
                f":money_with_wings: worker-{slug} hit daily token cap "
                f"({COST_CAP_TOKENS_PER_DAY}); sleeping until 00:00 UTC",
            )
            state["cost_cap_hit_today"] = True
            _save_state(state_file, state)
        return 0

    key = _read_key(key_file, slack_webhook, slug)
    if not key:
        return 1   # missing key already Slack'd in _read_key

    msgs, _http = _poll_bus(lab_url, slug, state["cursor"], key)
    new_msgs = [m for m in msgs if isinstance(m, dict) and m.get("id") not in state["processed_ids"]]
    if not new_msgs:
        _save_state(state_file, state)
        return 0

    # Got work — claim lock then invoke claude.
    _write_lock(lock_file)
    try:
        wake_ts = _now_iso()
        exit_code, stdout, stderr, duration = _invoke_claude(picker_dir)
        tokens, cost_usd = _parse_usage(stdout)
        cost_eur_est = _est_cost_eur(tokens, cost_usd)

        # Ack each drained message (NM3: idempotent — daemon-side dedupe
        # tolerates the user-prompt drain hook inside the claude session
        # also acking the same id).
        for m in new_msgs:
            mid = m.get("id")
            if isinstance(mid, int):
                _ack_message(lab_url, mid, key)

        # State updates.
        state["recent_wakes_60min"].append(time.time())
        state["tokens_today"] += tokens
        latest_created = max(
            (str(m.get("created_at") or "") for m in new_msgs),
            default=state["cursor"],
        )
        if latest_created > state["cursor"]:
            state["cursor"] = latest_created
        new_ids = [m["id"] for m in new_msgs if isinstance(m.get("id"), int)]
        state["processed_ids"] = (state["processed_ids"] + new_ids)[-PROCESSED_FIFO_SIZE:]

        # Audit POST — failure tolerated but flagged.
        audit_ok = _audit_log(master_url, baker_key, {
            "worker_slug": slug,
            "wake_ts": wake_ts,
            "messages_drained": len(new_msgs),
            "message_ids": new_ids,
            "claude_exit_code": exit_code,
            "claude_stdout_tokens": tokens,
            "claude_stderr_truncated": (stderr or "")[-2000:],
            "duration_seconds": round(duration, 3),
            "cost_eur_est": cost_eur_est,
        })

        # Breaker: claude failure OR audit-log explicit failure.
        if exit_code != 0:
            state["consecutive_fails"] += 1
            if state["consecutive_fails"] >= BREAKER_FAILS:
                state["breaker"] = {
                    "tripped": True,
                    "trip_ts": wake_ts,
                    "reason": (
                        f"claude exit {exit_code} after "
                        f"{BREAKER_FAILS} consecutive fails; manual reset required"
                    ),
                }
                _slack(
                    slack_webhook,
                    f":rotating_light: worker-{slug} circuit breaker TRIPPED — "
                    f"{state['breaker']['reason']}",
                )
        else:
            state["consecutive_fails"] = 0

        # Audit failure logged to stderr (launchd) but not breaker-counted —
        # post-hoc audit drop is recoverable; we don't want a flapping
        # baker-master deploy to disable the worker pool.
        if not audit_ok:
            sys.stderr.write(f"worker-{slug}: audit POST failed (kept running)\n")

        _save_state(state_file, state)
        return 0
    finally:
        _delete_lock(lock_file)


def main() -> None:
    try:
        _run_cycle()
    except SystemExit:
        raise
    except Exception as e:
        # Last-resort guard: never propagate to launchd as crash.
        sys.stderr.write(f"worker crash: {e!r}\n")
    # Always exit 0 so launchd doesn't accelerate respawn.
    sys.exit(0)


if __name__ == "__main__":
    main()
