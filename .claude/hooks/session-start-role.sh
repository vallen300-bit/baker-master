#!/usr/bin/env bash
# SessionStart hook: emit per-role context block based on $BAKER_ROLE,
# wrapped in the additionalContext JSON envelope so Claude Code injects it
# into the session's system prompt area.
#
# CONTRACT: Always exit 0 — never block claude from starting. Drain stdin
# (Claude passes session metadata as JSON; we don't need it but must not SIGPIPE).
#
# Resolution order:
#   1. $BAKER_ROLE env var (set by macOS Terminal profile)
#   2. cwd-based fallback (~/bm-b<N> -> b<N>; otherwise unknown)
#
# If no role can be resolved, emit a one-line nudge as additionalContext so
# Director sees the gap inside the session itself.

# Drain stdin (claude passes JSON; we don't consume it, just absorb it).
cat >/dev/null 2>&1 || true

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ROLE="${BAKER_ROLE:-}"

if [ -z "$ROLE" ]; then
  case "$REPO_ROOT" in
    */bm-aihead1-cowork|*/bm-aihead1-cowork/.claude/worktrees/*) ROLE="cowork-ah1" ;;
    */bm-aihead1|*/bm-aihead1/.claude/worktrees/*) ROLE="aihead1" ;;
    */bm-aihead2|*/bm-aihead2/.claude/worktrees/*) ROLE="aihead2" ;;
    */bm-b1|*/bm-b1/.claude/worktrees/*) ROLE="b1" ;;
    */bm-b2|*/bm-b2/.claude/worktrees/*) ROLE="b2" ;;
    */bm-b3|*/bm-b3/.claude/worktrees/*) ROLE="b3" ;;
    */bm-b4|*/bm-b4/.claude/worktrees/*) ROLE="b4" ;;
    */bm-b5|*/bm-b5/.claude/worktrees/*) ROLE="b5" ;;
    */bm-CM-1|*/bm-CM-1/.claude/worktrees/*) ROLE="CM-1" ;;
    */bm-CM-2|*/bm-CM-2/.claude/worktrees/*) ROLE="CM-2" ;;
    */bm-CM-3|*/bm-CM-3/.claude/worktrees/*) ROLE="CM-3" ;;
    */bm-CM-4|*/bm-CM-4/.claude/worktrees/*) ROLE="CM-4" ;;
    */bm-hag-filer|*/bm-hag-filer/.claude/worktrees/*) ROLE="hag-filer" ;;
    # bm-researcher is a standalone (non-baker-master) picker dir; this same hook is
    # copied there to give researcher the route-cues clause injection at SessionStart
    # (ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1, 2026-07-12, lead ruling #9173 middle-path).
    */bm-researcher|*/bm-researcher/.claude/worktrees/*) ROLE="researcher" ;;
    *)      ROLE="" ;;
  esac
fi

# Helper: emit a JSON envelope with the given text as additionalContext.
# Uses python3 to handle JSON escaping safely (newlines, quotes, etc.).
_emit() {
  python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
' 2>/dev/null || true
}

if [ -z "$ROLE" ]; then
  _emit <<'EOF'
[role-onboard] BAKER_ROLE env var not set and cwd not under bm-b<N>. Cannot auto-onboard role.
Director: set BAKER_ROLE in this terminal profile (Terminal → Settings → Profiles → "Run command: export BAKER_ROLE=<role>"). Valid values: aihead1, aihead2, b1, b2, b3, b4, b5 (case-insensitive; file lookup is lowercased).
Until set, paste the role identity manually as before.
EOF
  exit 0
fi

ROLE_LC="$(echo "$ROLE" | tr '[:upper:]' '[:lower:]')"
CTX_FILE="$REPO_ROOT/.claude/role-context/${ROLE_LC}.md"

if [ ! -f "$CTX_FILE" ]; then
  printf '[role-onboard] BAKER_ROLE=%s but no context file at %s. No injection this session.\n' "$ROLE" "$CTX_FILE" \
    | _emit
  exit 0
fi

# FLEET_DEPLOY_PARITY_1 (F5): surface the current checkout's client-script parity
# in the existing SessionStart context. This is a local cached-ref check: the
# dispatcher can run the fetching roll-up separately, while a seat self-reports
# stale code before it can emit a misleading started/drain signal.
CLIENT_PARITY_SUMMARY=""
CLIENT_PARITY="$REPO_ROOT/scripts/fleet_client_parity.sh"
if [ -f "$CLIENT_PARITY" ] && [ -f "$REPO_ROOT/scripts/arm_fleet_manifest.json" ]; then
  CLIENT_PARITY_OUT="$(FLEET_CLIENT_REPO="$REPO_ROOT" bash "$CLIENT_PARITY" \
    --no-fetch --capability-probe 2>&1 || true)"
  CLIENT_PARITY_SUMMARY="$(printf '%s\n' "$CLIENT_PARITY_OUT" \
    | grep -E '^(CLEAN|STALE|RED|UNTRACKED-MODIFIED|SEAT) ' \
    | tr '\n' ';' | sed 's/;$//' | cut -c1-1200)"
fi

# Assemble the injected context in three layers:
#   1. Role identity (always — $CTX_FILE).
#   2. Route-permission-cues-to-superior clause — appended for EVERY Director-facing /
#      bus-enabled seat, INCLUDING b-codes (which are banned from the full laconic
#      register). Standalone separable artifact so non-laconic seats get the routing
#      rule without the rest of the register; laconic-default.md + superior-dispatch-
#      authority.md reference it rather than restate it.
#      (ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1, 2026-07-12 — standing directive #6727.)
#   3. Full laconic register — appended ONLY for the Director-facing verdict seats
#      (deputy / deputy-codex / aihead2). deputy-codex is the Codex sibling of
#      deputy/AH2 and emits Director-facing verdicts, so it mirrors deputy
#      (AH2_LACONIC_TIER0_RETIRE_1, 2026-06-10 — retires the Tier-0 Read of
#      ~/.claude/skills/laconic/SKILL.md, ~5k tokens/session).
LACONIC_FILE="$HOME/baker-vault/_ops/role-contexts/laconic-default.md"
ROUTE_CUES_FILE="$HOME/baker-vault/_ops/role-contexts/route-cues-to-superior.md"

{
  cat "$CTX_FILE"
  if [ -n "$CLIENT_PARITY_SUMMARY" ]; then
    printf '\n[fleet-client-parity] %s\n' "$CLIENT_PARITY_SUMMARY"
  fi
  [ -f "$ROUTE_CUES_FILE" ] && cat "$ROUTE_CUES_FILE"
  case "$ROLE_LC" in
    deputy|deputy-codex|aihead2)
      [ -f "$LACONIC_FILE" ] && cat "$LACONIC_FILE"
      ;;
  esac
} | _emit
exit 0
