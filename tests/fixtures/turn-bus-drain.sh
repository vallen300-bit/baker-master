#!/usr/bin/env bash
# UserPromptSubmit hook: drain mid-session Brisen Lab bus arrivals.
# The SessionStart hook owns the shared drain core; this wrapper supplies the
# event name, the 60-second burst guard, and the prompt-latency timeout.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BUS_DRAIN_HOOK_EVENT="UserPromptSubmit"
export BUS_DRAIN_COOLDOWN_SECONDS="60"
export BUS_DRAIN_MAX_TIME="4"
export BUS_DRAIN_CONNECT_TIMEOUT="1"
exec "${SCRIPT_DIR}/session-start-bus-drain.sh"
