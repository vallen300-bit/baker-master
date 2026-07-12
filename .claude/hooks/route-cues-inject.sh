#!/usr/bin/env bash
# SessionStart hook: inject ONLY the route-permission-cues-to-superior clause.
#
# For "symlink-camp" seats whose role-context IS the laconic register symlink
# (researcher, and the follow-up fleet seats), the full register already reaches
# them via their existing mechanism (global laconic-reminder.sh + role-context).
# What they lack is the standalone routing clause. This hook appends JUST that
# clause — no role identity, no register — so there is no double-injection.
#
# Wired into a seat's project .claude/settings.json under SessionStart. baker-master
# clones do NOT wire this (they get the clause via session-start-role.sh instead).
#
# ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1, 2026-07-12 — standing directive #6727,
# lead ruling #9173 (researcher = v1). Graceful no-op until deputy's PR #165 merges
# and ~/baker-vault carries the file (the [ -f ] guard keeps SessionStart clean).
#
# CONTRACT: always exit 0 — never block claude from starting.

# Drain stdin (claude passes session JSON; we don't consume it).
cat >/dev/null 2>&1 || true

ROUTE_CUES_FILE="$HOME/baker-vault/_ops/role-contexts/route-cues-to-superior.md"

[ -f "$ROUTE_CUES_FILE" ] || exit 0

python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
' < "$ROUTE_CUES_FILE" 2>/dev/null || true
exit 0
