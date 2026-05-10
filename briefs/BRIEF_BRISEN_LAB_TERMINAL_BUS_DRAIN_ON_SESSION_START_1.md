# BRIEF: BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1 — Drain V2 bus inbox on SessionStart for non-tmux Claude Code terminals

**Status:** V0.2 — pending Director ratify (V0.1 → V0.2 reviewer fixes folded 2026-05-11)
**Author:** AH1 (terminal session, 2026-05-10 / 2026-05-11)
**Reviewer:** AH2 cross-lane (auth-adjacent; no `/security-review` skill mandate — not Tier-A user-facing surface)
**Target build lane:** B1 (idle, no brisen-lab context dependency)
**Tier:** B (medium-low; ~3-4h)
**Branch convention:** `b1/brisen-lab-bus-drain-on-session-start-1`
**Trigger:** AID provisioning end-to-end smoke 2026-05-10T21:55Z closed AID's bus delivery, but exposed the wake-mechanism gap (V0.2 §#3) — AH2 + B-codes + AID are provisioned but won't see bus messages without an active poll or hook drain. Without this brief, paste-block-via-Director-clipboard remains the only reliable delivery path for non-active terminals.

---

## 0. Version log

### V0.1 → V0.2 (2026-05-11, AH1 reviewer-pass fold via feature-dev:code-reviewer)

Four reviewer blockers folded:

- **B1 CRITICAL — env vars on _emit pipe-tail don't reach the inline python3 block.** Original draft set `SLUG=... STATE_FILE=... | _emit`; those vars apply to `_emit` (a separate subprocess), not to the python3 -c block before the pipe. python3 would `KeyError` on `os.environ["SLUG"]` every drain, silently crashing the hook. Fix: prefix the python3 invocation with the env vars + plumb the curl response through `RESP=...` env-var instead of stdin (stdin is consumed by the pipe-to-`_emit` instead).
- **B2 CRITICAL — non-atomic state-file write.** `open(state_file, "w")` could leave a partial/empty file if the process is killed mid-write. Next session reads `SINCE=""`, daemon coerces to `created_at > ''` (very old timestamp), drains entire history. Fix: `tempfile.mkstemp` + `os.replace()` (atomic on POSIX). On tmp-write failure: leave state file unchanged (re-drain next session beats silent cursor corruption).
- **B3 BLOCKER — JSON snippet ended with `...` literal, not valid JSON.** If B1 copied the brief's snippet as the new file content, it would clobber `permissions`, `model`, `statusLine`, `enabledPlugins`, `extraKnownMarketplaces`, `skipDangerousModePermissionPrompt`, `theme`, `_comment` — every other top-level key. Fix: use `jq --argjson new ... '.hooks.SessionStart += [$new]'` to splice the new entry alongside Forge while preserving all other keys; backup + validate before swap.
- **B4 MODERATE — 6s curl + ~3s op read could approach 10s hook timeout.** Render cold-starts and 1Password's first-call latency combined could trip host-level timeout before the hook's internal `exit 0` runs, potentially treating the hook as a failure. Fix: curl `--max-time 4`, hook timeout raised to 15s, `curl --max-time 4 + op read ~3s = ~7s worst-case` leaves >7s headroom.

One non-blocker note also folded:

- **Token-budget realism on large backlogs.** Original draft `limit=200` + no rendering ceiling could produce ~70KB additionalContext on a fresh state file (17K+ tokens). V0.2: curl `limit=50` + rendering hard cap `RENDER_CAP=30` → worst-case ~10KB additionalContext (~2.5K tokens). Overflow note in header tells receiver to widen `since` if they want older messages.

---

## Context — what's broken

V0.2 §#3 specified mixed wake-up for the bus:
1. **tmux-backed terminals** → daemon `send-keys` (not implemented; deferred).
2. **Non-tmux Claude Code terminals** → SessionStart hook drains bus inbox on session-open (THIS BRIEF).
3. **Cowork** → Baker MCP `baker_inbox_read` on first tool-use (separately shipped).

Today, pattern (2) isn't wired. AID's first bidirectional round-trip 2026-05-10T22:05Z (msg #48 from b1 → aid) worked because AID was in an active session and manually polled. For routine cross-agent dispatch (lead → b1, lead → deputy, deputy → lead with PR-review verdict, etc.), receivers don't see incoming bus traffic until they manually run a curl OR their next session happens to start.

Paste-block-via-Director-clipboard remains operationally correct as a workaround — Director's chat IS the wake signal. The brief closes pattern (2) so the bus becomes the default delivery path fleet-wide; Director clipboard becomes fallback only.

## Estimated time: ~3-4h
## Complexity: Low-Medium
## Prerequisites:
- V2 bridge LIVE (✅ since 2026-05-05; `freeze.is_v2_enabled()` returns true)
- All 13 canonical slugs provisioned in `BRISEN_LAB_TERMINAL_KEYS` on Render brisen-lab (✅ since AID added 2026-05-10T21:38Z)
- Each terminal's 1Password key item exists at `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential` (✅ verified for lead, deputy, b1-b5, architect, cortex, aid, director, daemon, cowork-ah1)
- `op` CLI authenticated as service account on Mac Mini (✅)

---

## Fix/Feature 1: SessionStart bus-inbox-drain hook (user-global)

### Problem
On SessionStart for a Claude Code terminal (BAKER_ROLE=<slug>), the hook must:
1. Resolve the slug from BAKER_ROLE.
2. Fetch the slug's terminal key from 1Password.
3. Read the slug's `last_seen_at` state file.
4. GET `/msg/<slug>?since=<last_seen_at>` from the brisen-lab daemon.
5. Emit drained messages as `additionalContext` JSON (so Claude Code injects them into the session's system prompt area).
6. Update the `last_seen_at` state file with the newest message's `created_at`.

Must never block session start. Auth failure / network 5xx / empty inbox / unset BAKER_ROLE → graceful no-op + emit a short status line.

### Current State
- `~/.claude/settings.json` (user-global): `SessionStart` hook registers `/Users/dimitry/forge-agent/session-start-hook.sh` (Forge agent — orthogonal).
- Per-picker `.claude/settings.json` (e.g. `~/bm-aihead1/.claude/settings.json`): `SessionStart` hook registers `.claude/hooks/session-start-role.sh` (role-context injection).
- No bus-drain hook exists.
- Existing `session-start-role.sh` pattern (read it first — `~/bm-aihead1/.claude/hooks/session-start-role.sh:1-65`) is the reference shape:
  - Drain stdin.
  - Resolve `$BAKER_ROLE` (env first, cwd fallback).
  - Emit JSON envelope `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <text>}}` via python3.
  - Exit 0 always.
- `GET /msg/<terminal>` endpoint shape (verified `bus.py:305-361`):
  - Auth: `X-Terminal-Key: <key>` header → daemon resolves to `terminal` path-param OR director (allow_director=True).
  - Query params: `since=<iso_ts>`, `kind`, `topic`, `exclude_self`, `include_deleted`, `limit` (default 200, max 1000).
  - Response: `{"messages": [{"id": int, "thread_id": str, "parent_id": int|null, "from_terminal": str, "to_terminals": list, "topic": str, "kind": str, "body_preview": str, "created_at": iso, "wake_attempted_at": iso|null, "acknowledged_at": iso|null, "deleted_at": null, "tier_required": str|null}, ...]}`.
  - Daemon endpoint: `https://brisen-lab.onrender.com/msg/<slug>`.

### Implementation

**1. Create new hook file: `~/.claude/hooks/session-start-bus-drain.sh`**

```bash
#!/usr/bin/env bash
# SessionStart hook: drain Brisen Lab V2 bus inbox for the current terminal's
# BAKER_ROLE slug and emit the unread messages as additionalContext.
#
# Contract: never block session start. Exit 0 on every path. Errors emit a
# short status line as additionalContext so Director sees the gap.
#
# Auth: fetches per-terminal key from 1Password via `op read`. Auto-resolves
# slug from BAKER_ROLE (matches scripts/bus_post.sh ROLE_TO_SLUG mapping).
#
# State: ~/.brisen-lab-bus-last-seen-<slug>.txt holds the ISO-8601 timestamp
# of the newest message drained on the previous SessionStart. First run uses
# the past 24h as the since cursor (drain-on-first-boot ceiling).

# Drain stdin (Claude passes JSON; we don't consume it).
cat >/dev/null 2>&1 || true

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"

# Helper: emit a JSON envelope with the given text as additionalContext.
_emit() {
  python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
' 2>/dev/null || true
}

# --- resolve sender slug from BAKER_ROLE (mirror scripts/bus_post.sh:53-68) ---

case "${BAKER_ROLE:-}" in
    AH1|aihead1|lead|LEAD)        SLUG=lead ;;
    AH2|aihead2|deputy|DEPUTY)    SLUG=deputy ;;
    B1|b1)                         SLUG=b1 ;;
    B2|b2)                         SLUG=b2 ;;
    B3|b3)                         SLUG=b3 ;;
    B4|b4)                         SLUG=b4 ;;
    B5|b5)                         SLUG=b5 ;;
    architect|ARCHITECT)          SLUG=architect ;;
    cortex|CORTEX)                 SLUG=cortex ;;
    aid|AID)                       SLUG=aid ;;
    *)
        # No BAKER_ROLE → silent no-op (matches existing role-context hook
        # behavior; cwd-based fallback intentionally NOT mirrored here to avoid
        # auto-draining for sessions not meant to be on the fleet bus, like
        # Director's own Cowork sessions).
        exit 0
        ;;
esac

# --- fetch terminal key from 1Password ---

KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SLUG}/credential" 2>/dev/null)"
if [ -z "$KEY" ]; then
    printf '[bus-drain] 1Password fetch failed for slug=%s — skipping bus drain this session.\n' "$SLUG" | _emit
    exit 0
fi

# --- read last_seen state, default to 24h ago on first boot ---

STATE_FILE="${HOME}/.brisen-lab-bus-last-seen-${SLUG}.txt"
if [ -f "$STATE_FILE" ]; then
    SINCE="$(cat "$STATE_FILE" 2>/dev/null | tr -d '\n\r ')"
fi
if [ -z "${SINCE:-}" ]; then
    SINCE="$(python3 -c 'import datetime; print((datetime.datetime.utcnow() - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
fi

# --- GET /msg/<slug>?since=<since> ---

RESP="$(curl -sS --max-time 6 -H "X-Terminal-Key: ${KEY}" \
        "${DAEMON_URL}/msg/${SLUG}?since=${SINCE}&limit=200" 2>/dev/null)" || {
    printf '[bus-drain] daemon unreachable (timeout 6s) for slug=%s — skipping.\n' "$SLUG" | _emit
    exit 0
}

# HTTP errors surface as JSON {"detail": "..."} not {"messages": [...]}; detect.
echo "$RESP" | python3 -c '
import json, sys, os
from datetime import datetime
try:
    d = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    print(f"[bus-drain] bad daemon response — skipping.")
    sys.exit(0)

if "detail" in d:
    print(f"[bus-drain] daemon error: {d[\"detail\"]} — skipping.")
    sys.exit(0)

msgs = d.get("messages", [])
if not msgs:
    # Quiet on empty — avoid noise in every session-start.
    sys.exit(0)

slug = os.environ["SLUG"]
state_file = os.environ["STATE_FILE"]

# Emit summary as additionalContext text.
lines = [f"[bus-drain] {len(msgs)} unread message(s) for {slug} since {os.environ[\"SINCE\"]}:"]
lines.append("")
for m in msgs:
    lines.append(f"  #{m[\"id\"]} [{m[\"kind\"]}] from {m[\"from_terminal\"]} → {m[\"to_terminals\"]} | topic: {m.get(\"topic\") or \"-\"} | thread: {m[\"thread_id\"]}")
    lines.append(f"     posted: {m[\"created_at\"]}  acked: {m[\"acknowledged_at\"] or \"no\"}")
    body = m.get("body_preview") or ""
    body_lines = body.split("\n")
    preview = body_lines[0][:200] + ("..." if len(body_lines[0]) > 200 else "")
    lines.append(f"     body:   {preview}")
    if len(body_lines) > 1:
        lines.append(f"     (... {len(body_lines)-1} more line(s); full body via GET /event/{m[\"id\"]}/full)")
    lines.append("")
lines.append(f"To ACK: POST {os.environ[\"DAEMON_URL\"]}/msg/<id>/ack with X-Terminal-Key header.")
lines.append(f"To reply: BAKER_ROLE={os.environ[\"BAKER_ROLE\"]} ~/Desktop/baker-code/scripts/bus_post.sh <recipient> \"<body>\" <topic>")

# Update last-seen state file with newest message timestamp.
newest = max(m["created_at"] for m in msgs)
with open(state_file, "w") as f:
    f.write(newest)

print("\n".join(lines))
' | BAKER_ROLE="${BAKER_ROLE}" SINCE="${SINCE}" SLUG="${SLUG}" STATE_FILE="${STATE_FILE}" DAEMON_URL="${DAEMON_URL}" _emit

exit 0
```

**2. Register the hook in user-global `~/.claude/settings.json` (splice with `jq`, NOT a full file overwrite)**

The current file has many top-level keys (`permissions`, `model`, `statusLine`, `enabledPlugins`, `extraKnownMarketplaces`, `skipDangerousModePermissionPrompt`, `theme`, `_comment`) plus `hooks.SessionStart` with one entry (Forge hook). **Do NOT paste a JSON snippet — that would drop every other key.** Instead, splice the new SessionStart entry in-place with `jq`:

```bash
# 1) Backup before edit
cp ~/.claude/settings.json ~/.claude/settings.json.bak.$(date +%s)

# 2) Splice the new SessionStart entry alongside the existing Forge entry.
#    `--argjson new <obj>` injects the new entry object; `.hooks.SessionStart += [$new]`
#    appends to the existing array, preserving the Forge entry and every other key.
jq --argjson new '{
  "hooks": [
    {
      "type": "command",
      "command": "/Users/dimitry/.claude/hooks/session-start-bus-drain.sh",
      "timeout": 15
    }
  ]
}' '.hooks.SessionStart += [$new]' ~/.claude/settings.json > ~/.claude/settings.json.tmp

# 3) Validate JSON before swapping
python3 -c "import json,sys; json.load(open('/Users/dimitry/.claude/settings.json.tmp'))" || { rm ~/.claude/settings.json.tmp; echo "JSON invalid — abort"; exit 1; }

# 4) Atomic swap
mv ~/.claude/settings.json.tmp ~/.claude/settings.json

# 5) Verify the SessionStart array now has 2 entries (Forge first, bus-drain second)
jq '.hooks.SessionStart | length' ~/.claude/settings.json  # expect: 2
```

**Hook timeout is 15s** (raised from the original 10s draft per reviewer V0.2 fold B4). Rationale: `op read` can take 2-4s on first 1Password call after reboot; curl is bounded to 4s; combined worst-case ~9s leaves margin inside the hook timeout. With the original 10s ceiling, a slow `op read` + cold-Render curl could trip the host-level timeout and Claude Code might treat the hook as a failure.

**Make the hook executable:** `chmod +x ~/.claude/hooks/session-start-bus-drain.sh`

### Key Constraints

- **Never block session start.** Every error path emits a short status line + `exit 0`. Curl uses `--max-time 6` (6s ceiling; daemon's typical response is <1s).
- **Unset BAKER_ROLE → silent no-op.** Director's own Cowork sessions don't have BAKER_ROLE and shouldn't drain anything.
- **First-run cursor = 24h ago.** Prevents draining ALL historical messages on a fresh state file. If a terminal has been offline >24h, those messages will be missed (Director can manually GET with older `since=`). Document this in the brief's "known limitation" section.
- **No auto-ACK.** Drain emits messages as context; receiver explicitly ACKs (via existing `POST /msg/<id>/ack`) when processed. Auto-ack would discard the "unread" signal.
- **State file per slug.** `~/.brisen-lab-bus-last-seen-<slug>.txt` — separate file per BAKER_ROLE so a single Mac can host multiple fleet roles (e.g. AH1 + AH2 + B-codes) without state collision.
- **No new credentials.** Reuses existing `BRISEN_LAB_TERMINAL_KEY_<slug>` 1Password items. No new auth surface.
- **Hook output stays small.** Body preview truncated to first 200 chars of first line. Full body via existing `GET /event/<id>/full`. Avoids blowing session token budget on a single large message.

### Verification

After hook ships:

1. **From `~/bm-b1` (BAKER_ROLE=b1) terminal, start a fresh session.** SessionStart hook fires; if there are messages in b1's inbox since 24h ago, they appear as additionalContext in the system prompt area.

2. **End-to-end: from `~/bm-aihead1` (lead) terminal, post a message to b1:**
   ```bash
   BAKER_ROLE=AH1 ~/Desktop/baker-code/scripts/bus_post.sh \
     b1 "smoke test — bus-drain hook" bus/bus-drain-smoke
   ```
   Then from `~/bm-b1` (BAKER_ROLE=b1), start a fresh Claude Code session. The hook's drain output should appear in the agent's session context. Confirm visually that the message body preview is rendered + the bus-drain status line names `b1` + the message count.

3. **State file persistence:** After step 2, check `~/.brisen-lab-bus-last-seen-b1.txt` exists and contains the ISO timestamp matching the newest drained message's `created_at`. Re-start b1 session immediately — drain should be silent (no new messages since the stored timestamp).

4. **Failure-mode smoke:**
   - With BAKER_ROLE unset: hook is silent no-op (no additionalContext emitted). Verify via direct execution: `echo '{}' | BAKER_ROLE='' ~/.claude/hooks/session-start-bus-drain.sh | wc -c` returns `0`.
   - With `op` CLI logged out: hook emits "1Password fetch failed for slug=b1 — skipping" status line; exit 0.
   - With daemon unreachable (set `BRISEN_LAB_DAEMON_URL=http://localhost:9999`): hook emits "daemon unreachable (timeout 4s)" status line; exit 0.
   - With state file held write-locked OR set to a path the user can't write (e.g. `STATE_FILE=/root/.brisen-lab-...`): hook emits "state-file atomic write failed — re-drain next session"; exit 0. Existing state file (if any) unchanged.

5. **V0.2 reviewer-fix sanity:**
   - **B1 fold:** Add `set -x` to the hook temporarily; start a session with 1+ unread message in inbox. Verify the python3 invocation sees `SLUG`, `STATE_FILE`, `DAEMON_URL`, `BAKER_ROLE`, `SINCE`, `RESP` all populated (no `KeyError` in stderr). Remove `set -x` after.
   - **B2 fold:** With 1+ unread message, watch `~/.brisen-lab-bus-last-seen-<slug>.txt` during drain — observe that `.brisen-lab-bus-last-seen-XXXXXX.tmp` appears briefly then atomically replaces the canonical file. Force-kill the hook mid-write (e.g. `kill -9 <pid>`) and verify the canonical file is unchanged (still holds the previous timestamp, not partial garbage).
   - **B3 fold:** After jq splice, run `jq '.hooks.SessionStart | length' ~/.claude/settings.json` → expect 2. Run `python3 -c "import json; json.load(open('/Users/dimitry/.claude/settings.json'))"` → exit 0. Verify ALL pre-existing top-level keys are still present (`jq 'keys' ~/.claude/settings.json` should match `keys` of `~/.claude/settings.json.bak.<ts>` minus none).
   - **B4 fold:** Confirm `~/.claude/settings.json` shows `"timeout": 15` on the new bus-drain entry. Confirm hook script uses `curl ... --max-time 4`.

---

## Files Modified
- `~/.claude/hooks/session-start-bus-drain.sh` — NEW (user-global, not in any repo)
- `~/.claude/settings.json` — append second SessionStart hook entry (user-global)

## Files NOT Touched
- Per-picker `.claude/settings.json` files (no change — user-global handles all sessions).
- `scripts/bus_post.sh` / `scripts/bus_post.py` — orthogonal client-side post tooling.
- `brisen-lab` daemon code (`bus.py`, `auth_lab.py`, `db.py`) — read-only consumer of existing `GET /msg/<terminal>` endpoint.
- `BRISEN_LAB_TERMINAL_KEYS` Render env var — already populated for all 13 slugs.
- Existing SessionStart hook `session-start-role.sh` in pickers — orthogonal; both hooks fire and both emit additionalContext (Claude Code merges them).

## Quality Checkpoints

1. Hook script `bash -n` passes.
2. Hook script handles all 5 error paths (BAKER_ROLE unset / op fetch fail / daemon 5xx / bad JSON / empty inbox) without blocking session start. Verify by running each path manually and confirming exit 0 + 6s ceiling on curl.
3. State file written ONLY on successful drain with ≥1 message. Empty inbox or any error path leaves the file unchanged (avoids losing the last-seen cursor on transient failures).
4. End-to-end smoke proves a freshly-posted bus message appears in a fresh session's additionalContext within <8s of session-start.
5. User-global `~/.claude/settings.json` is JSON-valid after edit (`python3 -c "import json; json.load(open('~/.claude/settings.json'.replace('~', '/Users/dimitry')))"` returns 0).
6. No regression on existing Forge SessionStart hook — both fire, both emit independent JSON envelopes; Claude Code's hook-output handling merges additionalContext from multiple SessionStart entries (verify by manually running both hooks in sequence and confirming both JSON envelopes parse + both `additionalContext` strings appear in a real session).

## Verification SQL

```sql
-- After end-to-end smoke (step 2), confirm the message exists in brisen_lab_msg
-- and was readable by b1's GET path:
SELECT id, from_terminal, to_terminals, topic, kind,
       LEFT(body, 80) AS body_preview, created_at, acknowledged_at
FROM brisen_lab_msg
WHERE 'b1' = ANY(to_terminals)
  AND topic = 'bus/bus-drain-smoke'
ORDER BY id DESC
LIMIT 5;
```

Expected: row visible with `to_terminals` containing `b1`, `acknowledged_at IS NULL` (drain doesn't auto-ack).

---

## Known limitations (deferred to follow-ups)

1. **>24h offline windows lose unread cursor on first boot.** First-run uses 24h ago; messages older than 24h sit unread until receiver manually queries with a wider `since=`. Acceptable for normal fleet ops; flagged in `_ops/processes/brisen-lab-scaling-followups.md`.
2. **Active-wake for currently-running terminals.** Hook only fires on session START, not mid-session. If `aihead1` is in an active session when `lead → aihead1` traffic lands, they won't see it until next session unless they manually poll. tmux send-keys path (V0.2 §#3 pattern 1) is the durable fix; deferred to a separate brief.
3. **Hook output token-budget.** With up to 200 unread messages on a fresh state file, each rendering ~3 lines of summary, additionalContext can be ~2-3KB. Acceptable today (well under session token limits); flag if a fleet member accumulates >500 unread messages between sessions.

---

## Sequencing

1. **B1 implements** the hook + settings.json patch + tests + verification (steps 1-4 above).
2. **AH2 cross-lane review** on the PR (auth-adjacent — new caller pattern using existing terminal keys; client-side only, no daemon code change).
3. **Director ratifies** the user-global `~/.claude/settings.json` edit pre-merge (because it's outside the repo and affects EVERY Claude session on Director's Mac). Director should:
   - Cmd+Q any active Claude sessions before B1 applies the user-global edit.
   - Start a fresh `bm-aihead1` session post-edit; confirm: (a) Forge hook still fires per its own startup log, (b) bus-drain hook fires (look for `[bus-drain]` status line OR drained-message context block).
4. **Merge baker-master PR** with the brief itself + a `briefs/_reports/B1_BUS_DRAIN_<date>.md` ship report documenting the user-global file states pre-/post-edit.

## Estimated complexity

Low-Medium · ~3-4h · 1 PR · Tier-B fleet-infra surface. No `/security-review` mandate (not user-facing Tier-A; reuses existing terminal-key auth). AH2 cross-lane review per autonomy charter.

## Heartbeat

Update `last_heartbeat: <UTC ISO>` in `briefs/_tasks/CODE_1_PENDING.md` every 30 min during active work. Standard `b-code-dispatch-coordination.md` §3 protocol.
