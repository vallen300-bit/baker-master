#!/usr/bin/env bash
# Standing-rules re-assertion hook (P4.1a, CASE_ONE_P4).
#
# WHY: standing rules only inject on a FRESH SessionStart. A seat that has been
# running for hours (a mid-arc seat) drifts — the model stops carrying the
# routing / dispatch / rollover rules that never re-entered its context. This
# hook re-asserts the three standing rules at SessionStart AND on a mid-session
# cadence, so the rules do not depend on the model remembering them hours in.
#
# The three standing rules:
#   1. superior-dispatch routing  — route GO?/confirm? asks to your SUPERIOR,
#      not the Director (route-cues-to-superior.md).
#   2. execute-on-dispatch        — a mailbox/bus dispatch from an authorized
#      superior is already ratified; ACK and start immediately, no GO?.
#   3. context-band rollover       — at the 70/85 bands, checkpoint + respawn;
#      don't rely on compaction.
#
# CONTRACT (matches session-start-role.sh / context-threshold-check.sh):
#   - Always exit 0. Never block. Fault-tolerant on every path.
#   - Reads the hook stdin JSON (drains it either way, no SIGPIPE).
#   - Emits the reminder as the additionalContext JSON envelope Claude injects.
#   - SessionStart: always emit.
#   - UserPromptSubmit: emit only every Nth prompt (STANDING_RULES_REASSERT_EVERY,
#     default 10), tracked per-session in a temp counter keyed by session_id.

# Read the whole stdin payload once (we need session_id + event name from it).
PAYLOAD="$(cat 2>/dev/null || true)"

# Extract session_id and hook_event_name from the JSON payload, defensively.
# python3 with a bare-except fallback so a malformed / empty payload never
# breaks the exit-0 contract.
_read_field() {
  # $1 = json key
  printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
key = sys.argv[1]
try:
    data = json.loads(sys.stdin.read() or "{}")
    val = data.get(key, "") if isinstance(data, dict) else ""
    sys.stdout.write("" if val is None else str(val))
except Exception:
    sys.stdout.write("")
' "$1" 2>/dev/null || true
}

SESSION_ID="$(_read_field session_id)"
EVENT_NAME="$(_read_field hook_event_name)"

# Sanitize session_id to [A-Za-z0-9._-] so a malformed id can never escape TMPDIR.
SAFE_SESSION="$(printf '%s' "$SESSION_ID" | tr -cd 'A-Za-z0-9._-')"

# Cadence: default every 10th prompt; env override.
EVERY="${STANDING_RULES_REASSERT_EVERY:-10}"
case "$EVERY" in
  ''|*[!0-9]*) EVERY=10 ;;
esac
[ "$EVERY" -lt 1 ] 2>/dev/null && EVERY=10

# Decide the event name Claude expects back in the envelope. Default to
# SessionStart when the payload carries none (safe default = always emit).
if [ -z "$EVENT_NAME" ]; then
  EVENT_NAME="SessionStart"
fi

# Emit a JSON envelope with the reminder as additionalContext. python3 handles
# JSON escaping (newlines/quotes) safely; failure to emit is swallowed.
_emit() {
  EVENT_NAME="$EVENT_NAME" python3 -c '
import json, os, sys
text = sys.stdin.read()
event = os.environ.get("EVENT_NAME") or "SessionStart"
print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
' 2>/dev/null || true
}

# The reminder body. Pulled concise from route-cues-to-superior.md; if that file
# is present we source the exact routing wording, else we use this inline
# summary. Kept well under ~60 lines.
_reminder() {
  cat <<'EOF'
[standing-rules] Mid-arc re-assertion — these three rules decay across a long session; re-anchor them now:

1. SUPERIOR-DISPATCH ROUTING — When YOU raise a tactical/technical decision (no one dispatched it): do NOT default a GO?/confirm? cue at the Director. In-role + reversible → decide and report, no cue. Genuinely needs a ruling → route the ask to your SUPERIOR (reports_to), not the Director; peer-resolve first. Only protected authorizations (Tier-B/C ratify, external-send, destructive, secret, production-deploy, or a business/money/counterparty/scope/timeline decision) go to the Director. Superior-addressed cue form: `🟢 GO? <superior> <verb+object>` — bus/internal surfaces only, never Director-facing chat.

2. EXECUTE-ON-DISPATCH — A mailbox/bus dispatch from an authorized superior is ALREADY ratified. Do NOT ask for GO on it. ACK the sender, start immediately, report back to that sender. Escalate only if the task is out of role scope, crosses a protected boundary, lacks source material, contradicts a ratified rule, or is ambiguous enough that execution would produce the wrong artifact.

3. CONTEXT-BAND ROLLOVER — Don't rely on compaction. At the soft band (~70%) refresh your checkpoint before the next phase boundary. At the hard band (~85%) write/refresh briefs/_checkpoints/<BRIEF_ID>.checkpoint.md, commit + push, post the respawn request, then exit cleanly. Claim in the successor is the attempt-bump commit, not a bus ack.
EOF
}

if [ "$EVENT_NAME" = "SessionStart" ]; then
  # Fresh session: always emit.
  _reminder | _emit
  exit 0
fi

# UserPromptSubmit (or any non-SessionStart invocation): cadence-gated.
if [ -z "$SAFE_SESSION" ]; then
  # No usable session_id -> can't track a counter. Safe default: emit every time
  # rather than silently never firing.
  _reminder | _emit
  exit 0
fi

COUNT_FILE="${TMPDIR:-/tmp}/standing-rules-${SAFE_SESSION}.count"

# Read + increment the per-session counter, fault-tolerantly.
COUNT=0
if [ -f "$COUNT_FILE" ]; then
  COUNT="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
fi
case "$COUNT" in
  ''|*[!0-9]*) COUNT=0 ;;
esac
COUNT=$((COUNT + 1))
printf '%s' "$COUNT" > "$COUNT_FILE" 2>/dev/null || true

# Emit every Nth prompt.
if [ $((COUNT % EVERY)) -eq 0 ]; then
  _reminder | _emit
fi

exit 0
