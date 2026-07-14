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

# --- authoritative status-aware fetch + bounded retry ---
# CLIENT_AUTHORITATIVE_READ_CONTRACT_1 (E27 recurrence, lead #10901): the daemon
# read path (#130) fail-closes a degraded read to HTTP 503 `bus_busy_retry` and
# ships an authoritative-completeness envelope (`complete`). A plain `curl -sS`
# (no status check) that then does `data.get("messages", [])` turns that 503 body
# into `[]` → a FALSE "no unacked messages" — exactly the 05:48Z E27 recurrence.
# So: capture the HTTP status (`-w`); a non-200 is a LOUD error, never empty;
# bounded-retry the transient ones (transport fail / 5xx / 429); and claim an
# all-clear ONLY on 200 AND complete:true.
#
# -G + --data-urlencode so the '+' offset in a timestamp is encoded correctly.
# unread=true is REQUIRED (codex verdict #8761, MEDIUM, Lesson #89 class): the
# daemon's unread branch is server-side filtered so the LIMIT window is spent only
# on candidate-unacked rows. The client-side unacked/wildcard filter stays as
# defense-in-depth.
_RETRY_MAX="${CHECK_INBOX_RETRY_MAX:-3}"
_RETRY_SLEEP="${CHECK_INBOX_RETRY_SLEEP:-2}"

CURL_ARGS=(-sS --max-time 20 -w '\n%{http_code}' -G
           -H "X-Terminal-Key: ${KEY}"
           --data-urlencode "limit=${LIMIT}"
           --data-urlencode "unread=true")
if [ -n "$SINCE" ]; then
    CURL_ARGS+=(--data-urlencode "since=${SINCE}")
fi

HTTP_CODE=""
RESP=""
_attempt=0
while : ; do
    # -w appends '\n<status>' AFTER the body: last line = status, rest = body.
    if OUT="$(curl "${CURL_ARGS[@]}" "${DAEMON_URL}/msg/${SLUG}" 2>/dev/null)"; then
        HTTP_CODE="${OUT##*$'\n'}"
        RESP="${OUT%$'\n'*}"
    else
        HTTP_CODE="000"   # transport failure (timeout / connection refused)
        RESP=""
    fi
    case "$HTTP_CODE" in
        000 | 5[0-9][0-9] | 429)
            _attempt=$((_attempt + 1))
            if [ "$_attempt" -le "$_RETRY_MAX" ]; then
                if [ "$_RETRY_SLEEP" -gt 0 ] 2>/dev/null; then sleep "$_RETRY_SLEEP"; fi
                continue
            fi
            ;;
    esac
    break
done

# Transport failure after retries → loud, NEVER an all-clear.
if [ "$HTTP_CODE" = "000" ]; then
    echo "ERROR: brisen-lab unreachable (GET /msg/${SLUG}) after $((_RETRY_MAX + 1)) attempt(s)" >&2
    exit 1
fi

# Non-200 → LOUD error surfacing the daemon detail (esp. 503 bus_busy_retry).
# This is the E27-recurrence guard: a busy/degraded daemon must NOT read as empty.
if [ "$HTTP_CODE" != "200" ]; then
    _DETAIL="$(printf '%s' "$RESP" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("detail",""))
except Exception:
    print("")' 2>/dev/null || true)"
    echo "ERROR: brisen-lab GET /msg/${SLUG} returned HTTP ${HTTP_CODE}${_DETAIL:+ (${_DETAIL})} — NOT an all-clear; the bus is busy/degraded, retry shortly." >&2
    exit 4
fi

if [ -z "$RESP" ] || printf '%s' "$RESP" | grep -q 'bad_terminal_key'; then
    echo "ERROR: brisen-lab rejected key for slug=${SLUG}. Response: ${RESP}" >&2
    exit 3
fi

# --- render unacked; all-clear ONLY when the read is authoritative (complete) ---
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

# Defensive double-guard (belt-and-suspenders with the bash status check above):
# a detail-only error body must never fall through to an empty all-clear.
if isinstance(data, dict) and "detail" in data and "messages" not in data:
    print("ERROR: daemon error body (not an all-clear): %s" % data.get("detail"),
          file=sys.stderr)
    sys.exit(4)

msgs = data if isinstance(data, list) else data.get("messages", [])
# complete==True means the daemon counted the FULL match set before LIMIT — the
# ONLY authoritative all-clear (BUS_READ_PATH_FALSE_EMPTY_FIX_1 envelope). A bare
# list is the legacy shape with no envelope → treat as complete for back-compat.
complete = True if isinstance(data, list) else data.get("complete", True)

def is_wildcard(m):
    to = m.get("to_terminals")
    return isinstance(to, list) and to == ["*"]

unacked = [m for m in msgs
           if not m.get("acknowledged_at")
           and not is_wildcard(m)]
unacked.sort(key=lambda m: m.get("created_at", ""))

if not unacked:
    if complete is False:
        print("%s inbox: PARTIAL read (complete=false) — the page did not cover the "
              "full unacked set; widen limit or drain the cursor. NOT an all-clear." % slug,
              file=sys.stderr)
        sys.exit(5)
    print("%s inbox: no unacked messages." % slug)
    sys.exit(0)

print("%s inbox: %d unacked.%s" % (
    slug, len(unacked), "" if complete else " (PARTIAL — more may remain past this page)"))
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
