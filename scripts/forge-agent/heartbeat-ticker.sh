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
# LIVENESS_WORKING_SPLIT_1 (PR 2) — low-frequency IDLE keepalive. While idle (no
# turn flag) the ticker still POSTs at this cadence with idle=true, which the
# daemon uses to refresh last_alive_at (the SESSION-ALIVE signal slug_live reads)
# WITHOUT touching the dashboard amber (idle=true backdates last_seen_at). Must be
# < the 120s freshness window so an idle-but-alive seat never stales out of
# slug_live and a cross-host wake never clones it. Default 90s.
IDLE_KEEPALIVE_INTERVAL="${HEARTBEAT_IDLE_KEEPALIVE_INTERVAL:-90}"
LOG="$HOME/forge-agent/heartbeat-ticker.log"

# POST one heartbeat. $1 = idle flag ("true" -> idle keepalive: refresh
# last_alive_at, leave amber off; anything else -> working beat: idle omitted).
# Fire-and-forget: short timeout, capture ONLY the numeric HTTP status (never the
# body, never the key). `|| true` so a curl failure can never surface to or kill
# the ticker. Logs class/status only on a non-2xx, keeping the log tiny + key-free.
_post_heartbeat() {
  local idle_flag="$1" body code
  if [ "$idle_flag" = "true" ]; then
    body="{\"session_uuid\":\"$SESSION_UUID\",\"terminal_alias\":\"$TERMINAL_ALIAS\",\"idle\":true}"
  else
    body="{\"session_uuid\":\"$SESSION_UUID\",\"terminal_alias\":\"$TERMINAL_ALIAS\"}"
  fi
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$LAB_URL/api/heartbeat" \
    -H "X-Forge-Key: $FORGE_KEY" \
    -H "Content-Type: application/json" \
    -d "$body" \
    --max-time "$TIMEOUT" 2>/dev/null || echo "000")
  case "$code" in
    2*) : ;;  # ok, stay silent
    *)  printf '%s heartbeat %s -> %s\n' "$(date -u +%FT%TZ)" "$TERMINAL_ALIAS" "$code" >> "$LOG" 2>/dev/null || true ;;
  esac
}

# Guard: without a session_uuid + a live parent we cannot run a non-zombie
# ticker, so refuse to start one. (Stop-on-end depends on a real parent PID.)
[ -z "$SESSION_UUID" ] && exit 0
[ -z "$PARENT_PID" ] && exit 0
kill -0 "$PARENT_PID" 2>/dev/null || exit 0

_last_idle_beat=0     # epoch of the last idle keepalive (0 = none yet)

while true; do
  # Stop-on-end: the Claude Code session is gone -> clear our own turn-flag
  # (hygiene against a stale flag if the session was killed mid-turn before the
  # Stop hook fired) then exit, no further heartbeats.
  kill -0 "$PARENT_PID" 2>/dev/null || { rm -f "$HOME/forge-agent/active/$SESSION_UUID" 2>/dev/null; exit 0; }

  if [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
    if [ -f "$HOME/forge-agent/active/$SESSION_UUID" ]; then
      # Turn ACTIVE (flag set by turn-start-hook, cleared by turn-stop-hook):
      # working beat every INTERVAL. idle omitted -> daemon sets last_seen_at=NOW
      # (amber ON) + last_alive_at=NOW.
      _post_heartbeat working
      _last_idle_beat=0     # re-arm so the first idle beat fires promptly on idle
    else
      # Turn IDLE. Pre-split this skipped the POST so last_seen_at staled and the
      # amber extinguished — but that ALSO staled the liveness signal, so an
      # idle-but-alive seat went slug_live=false and a cross-host wake could clone
      # it (#5625). Now: a LOW-FREQUENCY idle keepalive (idle=true) refreshes
      # last_alive_at (slug_live stays true) while the daemon keeps last_seen_at
      # backdated (amber STAYS off). Gated to IDLE_KEEPALIVE_INTERVAL so it's a
      # keepalive, not a 45s idle spam.
      _now=$(date +%s 2>/dev/null || echo 0)
      if [ "$_last_idle_beat" = 0 ] || [ $((_now - _last_idle_beat)) -ge "$IDLE_KEEPALIVE_INTERVAL" ]; then
        _post_heartbeat true
        _last_idle_beat="$_now"
      fi
    fi
  fi

  sleep "$INTERVAL"
done
