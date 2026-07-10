#!/usr/bin/env bash
# check_inbox.sh — vetted READ-ONLY bus inbox reader for caged agents.
#
# RESEARCHER_CAGE_ENFORCE_REMEDIATION_1 (b1, 2026-07-10) — Fix 1. Closes the
# "no vetted inbox-READ path" gap that blocks the researcher Bash-cage ENFORCE
# flip: the researcher drained its inbox via `KEY=$(cat …) + curl + python3`,
# and command-substitution / curl / python3 are each DENIED by the Bash cage
# (_ops/hooks/researcher_bash_cage.sh). This script is the sanctioned reader —
# allow-listed by EXACT canonical path (`$HOME/bm-b1/scripts/check_inbox.sh`)
# in the cage, exactly like the vetted bus_post.sh. The cage inspects only the
# top-level Bash command, so this script's internal curl/python3 run normally
# WITHOUT widening the general allow-list (see the cage's F1 exact-path lesson).
#
# Generalized from ~/Desktop/baker-code/scripts/check-lead-inbox.sh: slug comes
# from BAKER_ROLE (via scripts/agent_identity_generated.sh, same sourcing as
# bus_post.sh), key from the env → ~/.brisen-lab/keys/<slug> cache → 1Password
# fallback (via scripts/brisen_lab_terminal_key.sh).
#
# SAFE-TO-TRUST posture (the cage trusts this path's internals): READ-ONLY.
#   - No writes: no state file, no ledger, no cache mutation of its own.
#   - No ack: never POSTs /ack — printing is not acking (ack stays a separate
#     explicit action via bus_post/ack tooling).
#   - No arg-driven exec: the only positional arg is an optional numeric limit,
#     regex-validated; no arg is ever expanded into a command.
#
# Usage:
#   BAKER_ROLE=researcher ~/bm-b1/scripts/check_inbox.sh          # unacked, last 72h, limit 200
#   BAKER_ROLE=researcher ~/bm-b1/scripts/check_inbox.sh 500      # widen the fetch limit
#
# Env:
#   BAKER_ROLE              — required. Maps to the reader's own slug. The cage
#                             pins this to the installed role (researcher) for
#                             vetted invocations, so it cannot be used to read
#                             another terminal's inbox (codex G3 #8628 F3).
#
# Exits non-zero on any failure with descriptive stderr.

set -u

# HARD-PINNED daemon URL (codex G3 #8628 F1, defense-in-depth): NO env override.
# A BRISEN_LAB_DAEMON_URL=evil prefix must never redirect the X-Terminal-Key to
# an attacker host. The cage's env-prefix choke point already denies any such
# prefix on a vetted script; pinning here holds even if the cage is bypassed.
DAEMON_URL="https://brisen-lab.onrender.com"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/agent_identity_generated.sh
. "$SCRIPT_DIR/agent_identity_generated.sh"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

# --- optional numeric limit arg (no arg-driven exec: digits only) ---
LIMIT=200
if [ "$#" -ge 1 ] && [ -n "${1:-}" ]; then
    case "$1" in
        *[!0-9]* | '') echo "ERROR: limit must be a positive integer, got: '$1'" >&2; exit 1 ;;
        *)             LIMIT="$1" ;;
    esac
fi

# --- reader slug from BAKER_ROLE ---
if ! SLUG="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
    echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'" >&2
    echo "  Valid registry roles: ${AGENT_IDENTITY_BUS_AGENT_SLUGS[*]} plus aliases" >&2
    exit 1
fi

# --- credential fetch (env → ~/.brisen-lab/keys/<slug> cache → 1P) ---
KEY="$(brisen_lab_read_terminal_key "$SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
if [ -z "$KEY" ]; then
    echo "ERROR: terminal key empty for slug=${SLUG} (no env, no cache, no 1P)" >&2
    exit 1
fi

# --- since floor at 72h (UTC) ---
# The daemon GET /msg/{terminal} returns OLDEST-first and ignores order params,
# so a small limit can truncate away the NEWEST (unacked) rows. Floor the window
# at 72h + a generous limit so recent unacked always surface (check-lead-inbox
# lost bus #1439 to exactly this; we mirror the floor, minus the state file).
if SINCE="$(date -u -v-72H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"; then
    :
else
    SINCE="$(date -u -d '72 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '')"
fi

# --- GET /msg/<slug>?since=<since>&limit=<N> (read-only) ---
# -G + --data-urlencode so the '+' offset in a timestamp is encoded correctly.
if [ -n "$SINCE" ]; then
    RESP="$(curl -sS --max-time 20 -G \
        -H "X-Terminal-Key: ${KEY}" \
        --data-urlencode "since=${SINCE}" \
        --data-urlencode "limit=${LIMIT}" \
        "${DAEMON_URL}/msg/${SLUG}" 2>/dev/null)" || {
        echo "ERROR: brisen-lab unreachable (GET /msg/${SLUG})" >&2
        exit 1
    }
else
    RESP="$(curl -sS --max-time 20 -G \
        -H "X-Terminal-Key: ${KEY}" \
        --data-urlencode "limit=${LIMIT}" \
        "${DAEMON_URL}/msg/${SLUG}" 2>/dev/null)" || {
        echo "ERROR: brisen-lab unreachable (GET /msg/${SLUG})" >&2
        exit 1
    }
fi

if [ -z "$RESP" ] || printf '%s' "$RESP" | grep -q 'bad_terminal_key'; then
    echo "ERROR: brisen-lab rejected key for slug=${SLUG}. Response: ${RESP}" >&2
    exit 3
fi

# --- render unacked, excluding wildcard broadcasts (read-only, no state) ---
# Wildcard broadcasts (to_terminals==['*']: daemon restart / forced-kill /
# refresh-cadence-sweep) are UNACKABLE by a named terminal, so they would show
# as a permanent false-pending floor — drop them, same as the drain hook.
printf '%s' "$RESP" | SLUG="$SLUG" python3 -c '
import json, os, sys
slug = os.environ.get("SLUG", "?")
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as exc:
    print("ERROR: could not parse daemon response: %s" % exc, file=sys.stderr)
    sys.exit(1)
msgs = data if isinstance(data, list) else data.get("messages", [])

def is_wildcard(m):
    to = m.get("to_terminals")
    return isinstance(to, list) and to == ["*"]

unacked = [m for m in msgs
           if not m.get("acknowledged_at")
           and not is_wildcard(m)]
unacked.sort(key=lambda m: m.get("created_at", ""))

if not unacked:
    print("%s inbox: no unacked messages." % slug)
    sys.exit(0)

print("%s inbox: %d unacked." % (slug, len(unacked)))
for m in unacked:
    body = (m.get("body") or m.get("body_preview") or "").replace("\n", " ")
    if len(body) > 200:
        body = body[:200] + "…"
    print("  #%s  %s  from=%s  topic=%s" % (
        m.get("id"), str(m.get("created_at", ""))[:19],
        m.get("from_terminal", "?"), m.get("topic", "?")))
    if body:
        print("      %s" % body)
'
