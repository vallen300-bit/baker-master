#!/bin/bash
# Brisen Lab — per-session heartbeat ticker (FORGE_HEARTBEAT_FRESHNESS_1).
#
# Spawned (backgrounded, detached) by session-start-hook.sh once per watched
# Claude Code session. POSTs /api/heartbeat every $HEARTBEAT_INTERVAL seconds so
# forge_sessions.last_seen_at stays fresh during reasoning / long single tool
# calls. That keeps the dashboard WORKING-amber dot honest when JSONL activity
# (which drives /api/event) goes quiet — closing the DASHBOARD_CARD_WORKSTATE_
# CLARITY_1 under-fire gap.
#
# STOP MECHANISM (single, load-bearing — codex G0 finding 2):
#   Watches the Claude Code session PID passed as $3 (the SessionStart hook's
#   own parent). Each iteration checks `kill -0 $PARENT_PID`; when that process
#   exits the ticker exits. The installed Claude Code SDK has NO SessionEnd hook,
#   so process-exit watch is the ONLY reliable stop. We do NOT watch our own
#   $PPID (the detached ticker is reparented to init immediately and would exit
#   at once). BANNED alternatives: launchd-per-session plist; a sessions.json-
#   only / global launchd loop with no per-session exit signal (zombie WORKING).
#
# CONTRACT: fire-and-forget. Exit 0 on every path. Never blocks the agent.
# Never logs FORGE_KEY. Args: $1=session_uuid  $2=terminal_alias  $3=parent_pid

SESSION_UUID="$1"
TERMINAL_ALIAS="$2"
PARENT_PID="$3"
INTERVAL="${HEARTBEAT_INTERVAL:-45}"            # 45s vs the 120s freshness window
TIMEOUT="${HEARTBEAT_HTTP_TIMEOUT:-5}"          # short, fire-and-forget
LOG="$HOME/forge-agent/heartbeat-ticker.log"

# Guard: without a session_uuid + a live parent we cannot run a non-zombie
# ticker, so refuse to start one. (Stop-on-end depends on a real parent PID.)
[ -z "$SESSION_UUID" ] && exit 0
[ -z "$PARENT_PID" ] && exit 0
kill -0 "$PARENT_PID" 2>/dev/null || exit 0

while true; do
  # Stop-on-end: the Claude Code session is gone -> clear our own turn-flag
  # (hygiene against a stale flag if the session was killed mid-turn before the
  # Stop hook fired) then exit, no further heartbeats.
  kill -0 "$PARENT_PID" 2>/dev/null || { rm -f "$HOME/forge-agent/active/$SESSION_UUID" 2>/dev/null; exit 0; }

  # Turn-gate (FORGE_HEARTBEAT_TURN_GATED_1): only refresh last_seen_at while a
  # turn is ACTIVE (flag set by turn-start-hook.sh, cleared by turn-stop-hook.sh).
  # No flag = idle -> skip the beat so last_seen_at stales and the dashboard
  # extinguishes amber ~within the 120s freshness window after the task ends.
  if [ -f "$HOME/forge-agent/active/$SESSION_UUID" ] && [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
    # Fire-and-forget: short timeout, capture ONLY the numeric HTTP status (never
    # the body, never the key). `|| true` so a curl failure can never surface to
    # or kill the ticker. We log class/status only on a non-2xx, keeping the log
    # tiny and FORGE_KEY-free.
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$LAB_URL/api/heartbeat" \
      -H "X-Forge-Key: $FORGE_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"session_uuid\":\"$SESSION_UUID\",\"terminal_alias\":\"$TERMINAL_ALIAS\"}" \
      --max-time "$TIMEOUT" 2>/dev/null || echo "000")
    case "$CODE" in
      2*) : ;;  # ok, stay silent
      *)  printf '%s heartbeat %s -> %s\n' "$(date -u +%FT%TZ)" "$TERMINAL_ALIAS" "$CODE" >> "$LOG" 2>/dev/null || true ;;
    esac
  fi

  sleep "$INTERVAL"
done
