# BRIEF: WORKER_SELFWAKE_PHASE_1 — Self-wake worker for B1-B4

## Context

Director ratified 2026-05-14 Stage 3 Phase 1: per-B-code launchd worker that polls the brisen-lab bus and fires `claude --print` non-interactively in the B-code picker dir on new messages — removes Director-as-wake-signal for 60-70% of dispatches. Source spec: `~/baker-vault/_ops/ideas/2026-05-14-stage-3-worker-self-wake-design.md` (anchor `5c55767`). Predecessor: 2026-05-06 Stage 2 (App auto-reads inbox on Director prompt; same ratification thread pre-locked safety rails).

Director ratifications 2026-05-14: Phase 1 (B-codes only); wake cadence 2 min; daily digest @ 09:00 UTC + immediate push on Tier B / failure; no veto window on Tier A.

## Estimated time: ~2 days (1d build + 1d test + plist install)
## Complexity: Medium
## Prerequisites:
- 1P entries `BRISEN_LAB_TERMINAL_KEY_b{1,2,3,4}` exist (used by `bus_post.sh` today — confirmed)
- `claude` CLI at `/opt/homebrew/bin/claude` (confirmed)
- Bus daemon at `https://brisen-lab.onrender.com` reachable (confirmed; same daemon as `bus_post.sh`)
- Slack push helper available (mirror existing `actions_log.md` Slack push pattern)
- `baker_actions` extended with `tier`, `cost_eur`, `action_class`, `committer_agent`, `committed_at`, `self_cost_eur` columns (`migrations/20260510_baker_actions_tier_b_runtime.sql`, applied)

---

## Architecture

**One worker per B-code (4 total).** Each is a Python script + launchd plist. They share a library (`scripts/baker_worker.py`) for poll/cap/invoke/audit logic.

```
~/Library/Application Support/baker/
├── worker-b1/
│   ├── state.json          # cursor + cost counter + rate counter + breaker state
│   ├── key                 # terminal-key b1 (mode 0600)
│   └── wake.lock           # PID + start_ts; auto-cleaned post-exit
├── worker-b2/  (same structure)
├── worker-b3/  (same structure)
└── worker-b4/  (same structure)

~/Library/LaunchAgents/
├── com.baker.worker-b1.plist  # StartInterval=120
├── com.baker.worker-b2.plist
├── com.baker.worker-b3.plist
└── com.baker.worker-b4.plist
```

**Per-cycle flow** (every 120s per plist `StartInterval`):

1. **Kill switch check** — if `BAKER_WORKER_B{N}_ENABLED=false` in plist env, exit 0 immediately.
2. **Lock check** — if `wake.lock` exists with a live PID, exit 0 (prior wake still running, or Director has picker open with worker-injected marker; see §Concurrent-picker collision).
3. **Breaker check** — if `state.breaker.tripped=true`, exit 0 (manual re-enable required).
4. **Rate cap check** — if `len(state.recent_wakes_60min) >= 4`, exit 0 + log debug.
5. **Cost cap check** — if `state.tokens_today >= 100_000`, exit 0 + Slack push if first hit today.
6. **Poll bus** — `GET https://brisen-lab.onrender.com/msg/b{N}?since={state.cursor}` with `X-Terminal-Key`. Timeout 8s. 5xx → exit 0 (no breaker hit; daemon flap tolerated).
7. **Filter** — drop any message whose `id` is in `state.processed_ids` (idempotency tail; last 200 retained).
8. **If new messages exist:**
   a. Write `wake.lock` with current PID + `start_ts`.
   b. Invoke `/opt/homebrew/bin/claude --print "Wake. New bus messages. Read your CLAUDE.md, drain inbox, act."` with cwd=`~/bm-b{N}`, timeout 600s.
   c. Capture stdout/stderr + token count (parse `claude` final usage line; see §Token accounting).
   d. POST `https://brisen-lab.onrender.com/msg/{id}/ack` for each drained message.
   e. Update `state.cursor` to max(created_at) of drained messages.
   f. Append `id`s to `state.processed_ids` (FIFO, keep last 200).
   g. Audit log: `POST https://baker-master.onrender.com/api/worker/wake` with payload (see §Audit endpoint).
   h. Delete `wake.lock`.
9. **Breaker tick** — if `claude` exit ≠ 0 OR HTTP 4xx from bus/baker-master, increment `state.consecutive_fails`. If `>=3` → `state.breaker.tripped=true` + Slack push.
10. **Reset breaker on success** — `state.consecutive_fails = 0`.

**Daily digest** (separate launchd job, 09:00 UTC):
- `com.baker.worker-digest.plist` — runs `scripts/worker_digest.py` once/day
- Reads `baker_actions` WHERE `committer_agent` LIKE `worker-b%` AND `committed_at > NOW() - INTERVAL '24h'`
- Posts single Slack message: wake count per worker + total tokens + any breaker trips

---

## Fix/Feature 1: Migration — worker_processed + action class

### Problem
Need idempotency table + register `worker.wake.b_code` action class in `tier_b_action_classes`.

### Implementation

Create `migrations/20260515_worker_self_wake.sql`:

```sql
-- 20260515_worker_self_wake.sql
-- Stage 3 Phase 1: self-wake worker for B1-B4.
-- BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

BEGIN;

-- 1. Register the worker.wake.b_code action class.
INSERT INTO tier_b_action_classes (class_name, eur_cost, description) VALUES
    ('worker.wake.b_code', 0.10, 'B-code self-wake invocation (claude --print non-interactive). Cost approximation: ~€0.05-0.30/wake; midpoint logged. Daily cap 100K tokens enforced worker-side.')
ON CONFLICT (class_name) DO NOTHING;

COMMIT;
```

**Why no `worker_processed` DDL table:** idempotency state lives in per-worker `state.json` (last 200 IDs FIFO). DB-side dedupe is unnecessary — bus daemon already enforces unique message_ids, and 200-entry FIFO covers >>1 day of message volume at observed dispatch rate.

### Verification
```sql
SELECT class_name, eur_cost FROM tier_b_action_classes WHERE class_name = 'worker.wake.b_code';
-- Expected: 1 row, eur_cost=0.10
```

---

## Fix/Feature 2: Audit endpoint — POST /api/worker/wake

### Problem
Workers run on Director's Mac (no direct DB write). Must log each wake to `baker_actions` via baker-master HTTP API.

### Current State
`outputs/dashboard.py` already has `X-Baker-Key`-authenticated endpoints. Existing pattern: `POST /api/cortex/run` (line ~10540 references baker_actions). Worker mirrors this.

### Implementation

Add to `outputs/dashboard.py` (search for an existing `@app.post("/api/cortex/` block and add the new endpoint adjacent — keep neighboring routes grouped):

```python
@app.post("/api/worker/wake")
async def worker_wake_log(request: Request):
    """Audit log endpoint for self-wake worker (B-code Phase 1).

    Body (JSON):
        worker_slug: "b1" | "b2" | "b3" | "b4"
        wake_ts: ISO timestamp
        messages_drained: int
        message_ids: list[int]
        claude_exit_code: int
        claude_stdout_tokens: int (best-effort parse)
        claude_stderr_truncated: str (max 2000 chars)
        duration_seconds: float
        cost_eur_est: float
    """
    key = request.headers.get("X-Baker-Key")
    if key != os.environ.get("BAKER_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    required = {"worker_slug", "wake_ts", "messages_drained", "claude_exit_code",
                "claude_stdout_tokens", "duration_seconds", "cost_eur_est"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")

    if body["worker_slug"] not in {"b1", "b2", "b3", "b4"}:
        raise HTTPException(status_code=400, detail="Invalid worker_slug")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, action_payload, tier, cost_eur, action_class,
                     committer_agent, committed_at, self_cost_eur)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    "worker_wake",
                    json.dumps(body),
                    "B",
                    body["cost_eur_est"],
                    "worker.wake.b_code",
                    f"worker-{body['worker_slug']}",
                    body["wake_ts"],
                    body["cost_eur_est"],
                ),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
            return {"ok": True, "id": new_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Audit log write failed: {e}")
    finally:
        conn.close()
```

**Verify before writing:**
- Run `grep -n "@app.post(\"/api/cortex/run\"" outputs/dashboard.py` — confirms route prefix pattern + neighboring code style. Match the surrounding `get_db_connection()` / commit / rollback pattern verbatim.
- Run `grep -n "def get_db_connection" outputs/dashboard.py` — confirm function name (may be `_get_db_conn` or similar; brief author used `get_db_connection` as canonical; if rename needed, use actual name).

### Test
`tests/test_worker_wake_audit.py`:
- POST without auth → 401
- POST with auth + valid payload → 200, row in baker_actions with `committer_agent='worker-b1'`, `tier='B'`, `action_class='worker.wake.b_code'`
- POST with missing field → 400
- POST with invalid worker_slug → 400

---

## Fix/Feature 3: Worker library — scripts/baker_worker.py

### Implementation

Create `scripts/baker_worker.py`:

```python
#!/usr/bin/env python3
"""Self-wake worker for B-codes — Stage 3 Phase 1.

Invoked by launchd every 120s per B-code. One python process per wake cycle.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.

Required env (set in launchd plist):
    BAKER_WORKER_SLUG        — b1 / b2 / b3 / b4
    BAKER_WORKER_ENABLED     — "true" to run; anything else → exit 0
    BAKER_WORKER_STATE_DIR   — abs path to worker state dir
    BAKER_WORKER_PICKER_DIR  — abs path to ~/bm-b{N}
    BRISEN_LAB_DAEMON_URL    — default https://brisen-lab.onrender.com
    BAKER_MASTER_URL         — default https://baker-master.onrender.com
    BAKER_KEY                — for /api/worker/wake auth
    SLACK_WEBHOOK_URL        — for breaker + cost-cap-first-hit pushes
    PATH                     — must include /opt/homebrew/bin (for `claude` + `op`)

Exit codes: always 0 (launchd treats non-zero as crash; worker logs failures
internally + via Slack/breaker).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
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
LOCK_STALE_S = 900   # if lock older than 15min, treat as orphan (prior crash)

# -- Setup -------------------------------------------------------------------

SLUG = os.environ["BAKER_WORKER_SLUG"]
STATE_DIR = Path(os.environ["BAKER_WORKER_STATE_DIR"])
PICKER_DIR = Path(os.environ["BAKER_WORKER_PICKER_DIR"])
LAB_URL = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com")
MASTER_URL = os.environ.get("BAKER_MASTER_URL", "https://baker-master.onrender.com")
BAKER_KEY = os.environ.get("BAKER_KEY", "")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
STATE_FILE = STATE_DIR / "state.json"
KEY_FILE = STATE_DIR / "key"
LOCK_FILE = STATE_DIR / "wake.lock"


def _slack(text: str) -> None:
    """Best-effort Slack push; swallow failures (worker keeps running)."""
    if not SLACK_WEBHOOK:
        return
    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _load_state() -> dict:
    default = {
        "cursor": "1970-01-01T00:00:00Z",
        "processed_ids": [],
        "tokens_today": 0,
        "tokens_today_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "recent_wakes_60min": [],
        "consecutive_fails": 0,
        "breaker": {"tripped": False, "trip_ts": None, "reason": None},
        "cost_cap_hit_today": False,
    }
    if not STATE_FILE.exists():
        return default
    try:
        return {**default, **json.loads(STATE_FILE.read_text())}
    except Exception as e:
        _slack(f":warning: worker-{SLUG} state.json unreadable ({e}); using defaults")
        return default


def _save_state(s: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(STATE_FILE)


def _read_key() -> str:
    if not KEY_FILE.exists():
        _slack(f":rotating_light: worker-{SLUG} terminal-key file missing at {KEY_FILE}")
        sys.exit(0)
    return KEY_FILE.read_text().strip()


def _lock_alive() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        lock = json.loads(LOCK_FILE.read_text())
        pid = lock["pid"]
        age = time.time() - lock["start_ts"]
        if age > LOCK_STALE_S:
            LOCK_FILE.unlink(missing_ok=True)
            return False
        os.kill(pid, 0)   # signal 0 = check exists
        return True
    except (ProcessLookupError, OSError, KeyError, ValueError):
        LOCK_FILE.unlink(missing_ok=True)
        return False


def _write_lock() -> None:
    LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "start_ts": time.time()}))


def _delete_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def _poll_bus(cursor: str, key: str) -> list[dict]:
    url = f"{LAB_URL}/msg/{SLUG}?since={cursor}"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=POLL_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Expected shape: {"messages": [{"id": int, "body": str, "created_at": iso, ...}, ...]}
            return data.get("messages", [])
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            return []   # daemon flap; tolerate without breaker tick
        raise
    except urllib.error.URLError:
        return []   # network blip; tolerate


def _ack_message(msg_id: int, key: str) -> bool:
    url = f"{LAB_URL}/msg/{msg_id}/ack"
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=ACK_TIMEOUT_S)
        return True
    except Exception:
        return False


def _invoke_claude() -> tuple[int, str, str, float]:
    """Run claude --print non-interactively. Returns (exit, stdout, stderr, duration_s).

    Output is stdout-captured; final usage line carries token count (parsed downstream).
    """
    start = time.monotonic()
    proc = subprocess.run(
        [
            CLAUDE_BIN, "--print",
            "Wake. New bus messages. Read your CLAUDE.md, drain inbox, act per orientation.",
        ],
        cwd=str(PICKER_DIR),
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_S,
    )
    return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start


def _parse_tokens(stdout: str) -> int:
    """Best-effort parse of token count from claude --print output.

    Probe during build: claude --print emits a usage summary in stdout in some
    versions, JSONL when --output-format=json is passed. If no usage emitted,
    return 0 — cost cap will then never trip from this wake (acceptable;
    rate cap + per-day wake count still bound damage).

    PROBE TASK FOR B-CODE: run `claude --print "hi"` from CLI; check stdout for
    a tokens/usage line; if absent, try `claude --print --output-format=json`;
    pick whichever surface is parseable + add a regex / json key extractor here.
    Token count is BEST-EFFORT — worker must still run if parse fails.
    """
    # Placeholder — replace with verified pattern. Default 1000 tokens per wake
    # so the daily cap rolls in around 100 wakes (~ rate-cap ceiling × 25h).
    return 1000


def _audit_log(payload: dict) -> None:
    """POST audit to baker-master /api/worker/wake. Swallow failures (already
    locally logged via launchd stdout/err → ~/Library/Logs/)."""
    if not BAKER_KEY:
        return
    url = f"{MASTER_URL}/api/worker/wake"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-Baker-Key": BAKER_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=AUDIT_TIMEOUT_S)
    except Exception as e:
        sys.stderr.write(f"audit POST failed: {e}\n")


def _prune_old_wakes(wakes: list[float], window_s: int = 3600) -> list[float]:
    cutoff = time.time() - window_s
    return [w for w in wakes if w > cutoff]


def _maybe_reset_daily_cost(state: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state["tokens_today_date"] != today:
        state["tokens_today"] = 0
        state["tokens_today_date"] = today
        state["cost_cap_hit_today"] = False


def main() -> None:
    # Kill switch
    if os.environ.get("BAKER_WORKER_ENABLED", "").lower() != "true":
        sys.exit(0)

    # Concurrent-picker collision: skip if a prior wake or interactive Claude
    # session in this picker still holds the lock.
    if _lock_alive():
        sys.exit(0)

    state = _load_state()

    # Breaker check
    if state["breaker"]["tripped"]:
        sys.exit(0)

    # Rate cap
    state["recent_wakes_60min"] = _prune_old_wakes(state["recent_wakes_60min"])
    if len(state["recent_wakes_60min"]) >= RATE_CAP_PER_HOUR:
        _save_state(state)
        sys.exit(0)

    # Cost cap (daily reset first)
    _maybe_reset_daily_cost(state)
    if state["tokens_today"] >= COST_CAP_TOKENS_PER_DAY:
        if not state["cost_cap_hit_today"]:
            _slack(f":money_with_wings: worker-{SLUG} hit daily token cap ({COST_CAP_TOKENS_PER_DAY}); sleeping until 00:00 UTC")
            state["cost_cap_hit_today"] = True
            _save_state(state)
        sys.exit(0)

    key = _read_key()

    # Poll
    msgs = _poll_bus(state["cursor"], key)
    new_msgs = [m for m in msgs if m["id"] not in state["processed_ids"]]
    if not new_msgs:
        _save_state(state)
        sys.exit(0)

    # Got work — claim lock
    _write_lock()
    try:
        wake_ts = datetime.now(timezone.utc).isoformat()
        exit_code, stdout, stderr, duration = _invoke_claude()
        tokens = _parse_tokens(stdout)

        # Ack drained
        for m in new_msgs:
            _ack_message(m["id"], key)

        # State updates
        state["recent_wakes_60min"].append(time.time())
        state["tokens_today"] += tokens
        latest_cursor = max(m["created_at"] for m in new_msgs)
        state["cursor"] = latest_cursor
        state["processed_ids"] = (state["processed_ids"] + [m["id"] for m in new_msgs])[-PROCESSED_FIFO_SIZE:]

        # Breaker
        if exit_code != 0:
            state["consecutive_fails"] += 1
            if state["consecutive_fails"] >= BREAKER_FAILS:
                state["breaker"] = {
                    "tripped": True,
                    "trip_ts": wake_ts,
                    "reason": f"claude exit {exit_code} after {BREAKER_FAILS} consecutive fails",
                }
                _slack(f":rotating_light: worker-{SLUG} circuit breaker TRIPPED — {state['breaker']['reason']}. Manual re-enable required.")
        else:
            state["consecutive_fails"] = 0

        # Audit
        _audit_log({
            "worker_slug": SLUG,
            "wake_ts": wake_ts,
            "messages_drained": len(new_msgs),
            "message_ids": [m["id"] for m in new_msgs],
            "claude_exit_code": exit_code,
            "claude_stdout_tokens": tokens,
            "claude_stderr_truncated": stderr[-2000:] if stderr else "",
            "duration_seconds": duration,
            "cost_eur_est": round(tokens * 0.0001, 4),   # rough €/token; refined after first 7d data
        })

        _save_state(state)
    finally:
        _delete_lock()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"worker crash: {e}\n")
        # Don't propagate; launchd would mark as crashed + spawn faster
        sys.exit(0)
```

### Test
`tests/test_baker_worker.py` — mock urllib + subprocess; verify:
- Kill switch off → exits 0 immediately, no calls
- Lock alive → exits 0
- Breaker tripped → exits 0
- Rate cap reached → exits 0
- Cost cap reached → exits 0 + one Slack push (then no more until next day)
- No new messages → exits 0, state.cursor unchanged
- New messages → invokes claude, acks each, updates state, audits
- Claude exit ≠ 0 → consecutive_fails increments; 3rd fail trips breaker

---

## Fix/Feature 4: launchd plists

### Implementation

Create `scripts/templates/com.baker.worker-bN.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.baker.worker-bN</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/dimitry/Desktop/baker-code/scripts/baker_worker.py</string>
  </array>
  <key>StartInterval</key>
  <integer>120</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/dimitry/Library/Logs/baker-worker-bN.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/dimitry/Library/Logs/baker-worker-bN.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>BAKER_WORKER_SLUG</key>
    <string>bN</string>
    <key>BAKER_WORKER_ENABLED</key>
    <string>true</string>
    <key>BAKER_WORKER_STATE_DIR</key>
    <string>/Users/dimitry/Library/Application Support/baker/worker-bN</string>
    <key>BAKER_WORKER_PICKER_DIR</key>
    <string>/Users/dimitry/bm-bN</string>
    <key>BRISEN_LAB_DAEMON_URL</key>
    <string>https://brisen-lab.onrender.com</string>
    <key>BAKER_MASTER_URL</key>
    <string>https://baker-master.onrender.com</string>
    <key>BAKER_KEY</key>
    <string>FILLED_BY_INSTALLER</string>
    <key>SLACK_WEBHOOK_URL</key>
    <string>FILLED_BY_INSTALLER</string>
  </dict>
</dict>
</plist>
```

Create `scripts/install_workers.sh`:

```bash
#!/usr/bin/env bash
# install_workers.sh — Stage 3 Phase 1 idempotent installer.
# Creates state dirs, copies terminal-keys from 1P, renders plists, loads via launchctl.
#
# Usage:
#   BAKER_KEY=$(op read ...) SLACK_WEBHOOK_URL=$(op read ...) ./scripts/install_workers.sh
# Optional:
#   WORKERS="b1 b2"  (default: all four)
#
# Idempotent: safe to re-run. Unloads + reloads plist on rerun.

set -euo pipefail

WORKERS="${WORKERS:-b1 b2 b3 b4}"
TEMPLATE=scripts/templates/com.baker.worker-bN.plist.template

if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: missing $TEMPLATE" >&2
    exit 1
fi
if [ -z "${BAKER_KEY:-}" ] || [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
    echo "ERROR: BAKER_KEY and SLACK_WEBHOOK_URL must be set in env" >&2
    exit 1
fi

for N in $WORKERS; do
    STATE_DIR="$HOME/Library/Application Support/baker/worker-$N"
    PLIST="$HOME/Library/LaunchAgents/com.baker.worker-$N.plist"
    LOG_DIR="$HOME/Library/Logs"

    mkdir -p "$STATE_DIR" "$LOG_DIR"

    # Fetch + write terminal key (mode 0600)
    KEY=$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_$N/credential")
    if [ -z "$KEY" ]; then
        echo "ERROR: empty terminal-key for $N" >&2
        exit 1
    fi
    umask 077
    echo "$KEY" > "$STATE_DIR/key"

    # Render plist (template literal substitution; bN → b<N>)
    sed -e "s|bN|$N|g" \
        -e "s|<string>FILLED_BY_INSTALLER</string>|<string>__PLACEHOLDER__</string>|" \
        "$TEMPLATE" > "$PLIST.tmp"
    # Inject BAKER_KEY + SLACK_WEBHOOK_URL via python (safer than sed with special chars)
    python3 - "$PLIST.tmp" "$BAKER_KEY" "$SLACK_WEBHOOK_URL" <<'PY'
import re, sys
plist_path, baker_key, slack_url = sys.argv[1:4]
text = open(plist_path).read()
# Replace the two placeholders in order: first = BAKER_KEY, second = SLACK
parts = text.split("<string>__PLACEHOLDER__</string>", 2)
if len(parts) != 3:
    sys.exit(f"ERROR: expected 2 placeholders, got {len(parts)-1}")
out = parts[0] + f"<string>{baker_key}</string>" + parts[1] + f"<string>{slack_url}</string>" + parts[2]
open(plist_path, "w").write(out)
PY
    mv "$PLIST.tmp" "$PLIST"
    chmod 600 "$PLIST"

    # Unload (ignore errors if not yet loaded) + load
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"

    echo "Installed worker-$N (state: $STATE_DIR, plist: $PLIST)"
done

echo
echo "Workers loaded. Verify:"
echo "  launchctl list | grep com.baker.worker"
echo "  tail -f ~/Library/Logs/baker-worker-b1.log"
echo
echo "To disable a worker: set BAKER_WORKER_ENABLED=false in its plist + reload."
echo "To kill ALL workers: BAKER_WORKER_ENABLED=false on every plist + launchctl unload each."
```

### Verification
```bash
launchctl list | grep com.baker.worker
# Expected: 4 entries (com.baker.worker-b1 through b4) with PID column = "-" between cycles (sleeping)

# Test wake (manual trigger):
launchctl kickstart -k gui/$(id -u)/com.baker.worker-b1
sleep 5
tail -20 ~/Library/Logs/baker-worker-b1.log
tail -20 ~/Library/Logs/baker-worker-b1.err.log
# Expected: no error; if no bus messages → silent exit
```

---

## Fix/Feature 5: Daily digest

### Implementation

Create `scripts/worker_digest.py`:

```python
#!/usr/bin/env python3
"""Daily digest — posts Slack summary of worker activity over last 24h.

Triggered by launchd at 09:00 UTC daily via com.baker.worker-digest.plist.
BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

MASTER_URL = os.environ["BAKER_MASTER_URL"]
BAKER_KEY = os.environ["BAKER_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]


def main() -> None:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    req = urllib.request.Request(
        f"{MASTER_URL}/api/worker/digest?since={since}",
        headers={"X-Baker-Key": BAKER_KEY},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    lines = [
        f":robot_face: *Worker digest — last 24h* ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})",
        "",
    ]
    for slug in ["b1", "b2", "b3", "b4"]:
        s = data.get(slug, {})
        wake_count = s.get("wake_count", 0)
        tokens = s.get("total_tokens", 0)
        fail_count = s.get("fail_count", 0)
        breaker = " :rotating_light: BREAKER TRIPPED" if s.get("breaker_tripped") else ""
        lines.append(f"• *worker-{slug}*: {wake_count} wakes · ~{tokens:,} tokens · {fail_count} fails{breaker}")

    lines.append("")
    lines.append(f"Total cost est: ~€{data.get('total_cost_eur', 0):.2f}")

    urllib.request.urlopen(
        urllib.request.Request(
            SLACK_WEBHOOK,
            data=json.dumps({"text": "\n".join(lines)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        timeout=10,
    )


if __name__ == "__main__":
    main()
```

Add `GET /api/worker/digest?since=ISO` to `outputs/dashboard.py` (same neighborhood as `/api/worker/wake`):

```python
@app.get("/api/worker/digest")
async def worker_digest(since: str, request: Request):
    key = request.headers.get("X-Baker-Key")
    if key != os.environ.get("BAKER_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT committer_agent, COUNT(*) AS wakes,
                       SUM((action_payload->>'claude_stdout_tokens')::int) AS total_tokens,
                       SUM(CASE WHEN (action_payload->>'claude_exit_code')::int != 0 THEN 1 ELSE 0 END) AS fails,
                       SUM(cost_eur) AS total_cost_eur
                FROM baker_actions
                WHERE action_class = 'worker.wake.b_code'
                  AND committed_at > %s::timestamptz
                GROUP BY committer_agent
                LIMIT 100
                """,
                (since,),
            )
            rows = cur.fetchall()
        out = {"total_cost_eur": 0.0}
        for committer, wakes, tokens, fails, cost in rows:
            slug = committer.replace("worker-", "")
            out[slug] = {
                "wake_count": wakes,
                "total_tokens": int(tokens or 0),
                "fail_count": int(fails or 0),
                "breaker_tripped": False,   # state.json is local; Phase 1 trusts breaker pushes Slack directly
            }
            out["total_cost_eur"] += float(cost or 0)
        return out
    finally:
        conn.close()
```

Create `scripts/templates/com.baker.worker-digest.plist.template` — same shape as worker-bN but with `<key>StartCalendarInterval</key>` instead of `StartInterval`:

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key><integer>9</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

---

## Files Modified

- `migrations/20260515_worker_self_wake.sql` — NEW: register `worker.wake.b_code` action class
- `outputs/dashboard.py` — NEW endpoints: `POST /api/worker/wake` + `GET /api/worker/digest`
- `scripts/baker_worker.py` — NEW: per-cycle worker logic
- `scripts/worker_digest.py` — NEW: daily Slack summary
- `scripts/install_workers.sh` — NEW: idempotent installer
- `scripts/templates/com.baker.worker-bN.plist.template` — NEW
- `scripts/templates/com.baker.worker-digest.plist.template` — NEW
- `tests/test_worker_wake_audit.py` — NEW: 4 tests for /api/worker/wake
- `tests/test_baker_worker.py` — NEW: 8 tests for worker library

## Do NOT Touch

- `scripts/bus_post.sh` / `scripts/bus_post.py` — outbound; unrelated
- `~/bm-b{N}/CLAUDE.md` or `~/bm-b{N}/.claude/role-context/b{N}.md` — orientation unchanged; worker triggers existing flow
- `~/bm-b{N}/.claude/hooks/user-prompt-submit-confirm.py` — inbound drain already works end-to-end (auth + drain + ack); worker invokes claude which fires this hook
- Existing `baker_actions` columns — additive use only via existing schema
- `~/Library/LaunchAgents/com.baker.chrome-debug.plist` / `com.baker.forge-snapshot-push.plist.bak` — unrelated workers
- `scripts/check_singletons.sh` — no SentinelRetriever / SentinelStoreBack touched

## Quality Checkpoints

1. Migration `20260515_worker_self_wake.sql` applies clean on staging Neon branch: `SELECT class_name FROM tier_b_action_classes WHERE class_name='worker.wake.b_code'` returns 1 row.
2. `pytest tests/test_worker_wake_audit.py tests/test_baker_worker.py -v` — literal green output captured in ship report (NO "pass by inspection" per Lesson #8).
3. Install on one B-code first (b1): `WORKERS=b1 ./scripts/install_workers.sh` → `launchctl list | grep com.baker.worker-b1` shows entry → manual kick: `launchctl kickstart -k gui/$(id -u)/com.baker.worker-b1` → `tail ~/Library/Logs/baker-worker-b1.log` shows clean exit (no bus messages → silent).
4. Probe wake: post a test bus message to b1, wait ≤120s, verify worker fires, claude session ran in ~/bm-b1, message acked, `baker_actions` has new row with `action_class='worker.wake.b_code'`.
5. Probe breaker: with worker disabled, post 3 bogus messages that cause claude to exit 1 (e.g., invalid prompt that would surface immediate error) → breaker trips on 3rd → Slack push lands → worker idle until manual reset.
6. Probe cost cap: pre-seed `state.json` with `tokens_today: 99999` → next wake hits cap → Slack push → no claude invocation.
7. Probe rate cap: pre-seed `state.json` with 4 recent_wakes_60min → next wake skipped silently.
8. Probe concurrent picker: open ~/bm-b1 picker session (interactive claude); during it, kick worker manually; verify worker sees `wake.lock` from claude session and skips (need claude session to write lock — see §Concurrent-picker collision).
9. After Phase-1 install on all 4, monitor `baker_actions` 24h: `SELECT committer_agent, COUNT(*), SUM(cost_eur) FROM baker_actions WHERE action_class='worker.wake.b_code' AND committed_at > NOW() - INTERVAL '24h' GROUP BY 1`. Expected: ≤30 wakes total, <€5 cost.
10. After 7 days: review digest pattern. If any unexpected spikes → kill switch + postmortem.

## Verification SQL

```sql
-- Action class registered
SELECT class_name, eur_cost, description FROM tier_b_action_classes WHERE class_name = 'worker.wake.b_code';

-- Wake activity last 24h (use after install)
SELECT committer_agent, COUNT(*) AS wakes,
       SUM((action_payload->>'claude_stdout_tokens')::int) AS tokens,
       SUM(cost_eur) AS cost_eur,
       SUM(CASE WHEN (action_payload->>'claude_exit_code')::int != 0 THEN 1 ELSE 0 END) AS fails
FROM baker_actions
WHERE action_class = 'worker.wake.b_code'
  AND committed_at > NOW() - INTERVAL '24 hours'
GROUP BY committer_agent
ORDER BY committer_agent
LIMIT 10;

-- Recent wake payloads (debugging)
SELECT id, committer_agent, committed_at, action_payload
FROM baker_actions
WHERE action_class = 'worker.wake.b_code'
ORDER BY committed_at DESC
LIMIT 20;
```

---

## §Concurrent-picker collision (design note for B-code)

The risk: Director opens `~/bm-b{N}` picker (interactive Claude session) while the launchd worker fires. Two claude processes running in same dir → git/state collisions.

**Mitigation:** worker uses `wake.lock` PID file. Interactive picker sessions must ALSO write this lock so worker skips. Options:

1. **Add to existing SessionStart hook** in `~/bm-b{N}/.claude/hooks/session-start-role.sh` — on session open, write `~/Library/Application Support/baker/worker-b{N}/wake.lock` with current PID; on session close (via SessionEnd hook), delete it.
2. **Use a separate trampoline** — picker auto-launches a tiny PID-tracker on session start.

**Recommended:** option 1. Cleanest. B-code MUST add this to the SessionStart hook as part of this brief. Reference snippet:

```bash
# In session-start-role.sh, after role detection succeeds:
if [ -n "$ROLE_LC" ] && [[ "$ROLE_LC" =~ ^b[1-5]$ ]]; then
    LOCK_DIR="$HOME/Library/Application Support/baker/worker-$ROLE_LC"
    if [ -d "$LOCK_DIR" ]; then
        python3 -c "import json, os, time; open('$LOCK_DIR/wake.lock','w').write(json.dumps({'pid': os.getppid(), 'start_ts': time.time(), 'source': 'interactive-picker'}))" 2>/dev/null || true
    fi
fi
```

And SessionEnd companion in `aihead1-session-end.sh` (or its B-code equivalent — verify naming; brief author noted `aihead1-session-end.sh` symlinked into bm-b1, may need rename).

**Open Q for B-code:** confirm the b1-b4 session-end hook naming/wiring is consistent with bm-aihead1. If not, generalize.

---

## §Token accounting probe (REQUIRED BEFORE SHIP)

`_parse_tokens()` is a placeholder. B-code MUST probe `claude --print` output formats and pick one that emits parseable token counts:

```bash
# Probe 1: default text output
claude --print "What is 2+2?" 2>&1 | tail -20
# Look for "tokens", "usage", "tokens used", etc.

# Probe 2: JSON output
claude --print --output-format=json "What is 2+2?" 2>&1 | tail -20
# Look for usage / input_tokens / output_tokens keys

# Probe 3: stderr separately
claude --print "What is 2+2?" 2>/tmp/stderr.txt >/tmp/stdout.txt
cat /tmp/stderr.txt
```

Once a parseable surface is found, replace `_parse_tokens()` with the verified extractor. Record format + version in commit message. If genuinely no usage emitted in any mode → leave placeholder + note in ship report; AI Head decides whether to ship Phase 1 with token-count = constant approximation (acceptable — rate cap + wake count still bound damage).

---

## §Open Director questions surfaced during build

These are deferred to AI Head for resolution; brief proceeds with the stated defaults:

1. **Token-to-EUR conversion** — placeholder `tokens * 0.0001 EUR`. Refine after first 7d burn-in based on actual Anthropic invoice mapping. Not a blocker.
2. **Slack channel for breaker/digest pushes** — use existing Director Slack webhook (same as `actions_log.md` notifications). If a dedicated `#baker-workers` channel is preferred, AI Head changes the webhook value in installer; no brief change needed.
3. **What to do on bus daemon hard-down >1h** — Phase 1 default: silent no-op + breaker doesn't trip. If Director wants Slack push on prolonged outage, follow-up brief.

---

## Acceptance criteria

- [ ] `pytest tests/test_worker_wake_audit.py tests/test_baker_worker.py -v` literal green output in ship report
- [ ] `migrations/20260514_worker_self_wake.sql` applied on staging Neon branch
- [ ] `/api/worker/wake` deployed to baker-master; `curl -X POST -H "X-Baker-Key: $BAKER_KEY" ... /api/worker/wake` returns 200 + new row in baker_actions
- [ ] `/api/worker/digest` returns expected shape
- [ ] `scripts/install_workers.sh` runs idempotently on Director's Mac (manual test, not CI)
- [ ] `launchctl list | grep com.baker.worker` shows 4 entries after install
- [ ] One-shot kickstart on worker-b1 produces clean log entry (no bus messages → silent exit)
- [ ] End-to-end: AI Head posts test bus message to b1 → worker fires ≤120s later → claude session runs → message acked → baker_actions row written
- [ ] Token-count probe completed; `_parse_tokens()` either parses real values OR documented as constant-approximation with rationale in ship report
- [ ] Breaker / rate cap / cost cap each probed manually (3 simple tests)
- [ ] SessionStart hook updated to write `wake.lock` on interactive picker open (concurrent-picker collision mitigation)
- [ ] Ship report includes the 10 Quality Checkpoint outcomes + literal pytest output

## Ship gate

Literal `pytest` green output for both test files. NO "pass by inspection". If any probe (token-count, manual kick, concurrent-picker) fails, REQUEST_CHANGES — those are load-bearing for Phase 1 confidence.

## Trigger class

`TIER_B_AGENT_RUNTIME` — new automation surface (worker invokes claude CLI autonomously). Mandatory 2nd-pass per SKILL.md §Code-reviewer 2nd-pass Protocol triggers:
- Touches authentication / token handling (terminal keys, BAKER_KEY)
- Introduces new automation surface (external bus polling + claude spawn)
- Concurrency-ordering primitive (wake.lock semantics)

Plan after B-code ships: AH2 static → AH2 `/security-review` → picker-architect → `feature-dev:code-reviewer` 2nd-pass (parallel). All 4 must clear.
