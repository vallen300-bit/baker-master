#!/usr/bin/env bash
# read_message.sh — vetted READ-ONLY full-text message reader for the researcher.
#
# RESEARCHER_FULL_TEXT_READER_1 (deputy, 2026-07-12; lead dispatch #9243 item 1,
# researcher capability-extension brief tranche-1). check_inbox.sh renders bodies
# capped at 200 chars (python body[:200]) SILENTLY — brief #9178 arrived truncated
# and only lead's after-the-fact confirmation saved the scope. This wrapper is the
# sanctioned "show the FULL message" path — same cage-trusted exact-path lineage as
# check_inbox.sh, allow-listed in researcher_bash_cage.sh. READ-ONLY: no ack, no
# writes, no arg-driven exec.
#
# DAEMON CONTRACT (empirically probed 2026-07-12, codex design review #9250):
#   - GET /msg/<id> returns reader_slug_mismatch even to the recipient's own key —
#     UNUSABLE. Full content comes only from the LIST endpoint GET /msg/researcher.
#   - On that endpoint the daemon caps `body_preview` at BODY_PREVIEW_CAP=8000 chars
#     and truncates SILENTLY (no ellipsis). `body` is null in list responses.
#   - The list is oldest-first and limit-bounded; there is NO cursor contract.
# Therefore:
#   - truncated=false is PROVABLE only when len(body_preview) < 8000 (below the cap
#     the daemon returns full content). len == 8000 => truncated=true, and the tail
#     is UNREACHABLE via the current API (needs a daemon full-body endpoint — a
#     tranche-2 follow-up; this reader never silently swallows the missing tail).
#   - --thread completeness cannot be proven if the single high-limit fetch reaches
#     the limit; in that case thread_complete=false is reported.
#
# Usage:
#   read_message.sh <msg-id>              # full body of one message in researcher's mailbox
#   read_message.sh --thread <thread-id>  # every message in that thread, full bodies
#   read_message.sh <msg-id> --page N --page-size K   # chunk a long (<=8000) body
set -u

DAEMON="https://brisen-lab.onrender.com"     # HARD-PINNED, no env override (cage lineage)
SLUG="researcher"                            # HARDCODED reader slug — own mailbox only
BODY_PREVIEW_CAP=8000                        # observed daemon body_preview cap (see header)
FETCH_LIMIT=2000                             # high limit; thread_complete=false if hit
SDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "read_message: $1" >&2; exit "${2:-1}"; }

# --- arg parse (no arg-driven exec: numeric / known-flag only) ---
MSGID=""
THREAD=""
PAGE=""
PAGE_SIZE=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --thread) THREAD="${2:-}"; shift 2 || fail "--thread needs a value" 1 ;;
        --page)   PAGE="${2:-}";   shift 2 || fail "--page needs a value" 1 ;;
        --page-size) PAGE_SIZE="${2:-}"; shift 2 || fail "--page-size needs a value" 1 ;;
        --*) fail "unknown flag '$1'" 1 ;;
        *) case "$1" in *[!0-9]*|'') fail "msg-id must be numeric (got '$1')" 1 ;; esac
           MSGID="$1"; shift ;;
    esac
done
[ -n "$THREAD" ] || [ -n "$MSGID" ] || fail "need a numeric <msg-id> or --thread <thread-id>" 1
[ -n "$THREAD" ] && [ -n "$MSGID" ] && fail "give either a msg-id or --thread, not both" 1
for v in "$PAGE" "$PAGE_SIZE"; do
    [ -z "$v" ] || case "$v" in *[!0-9]*) fail "--page/--page-size must be numeric" 1 ;; esac
done

# --- resolve researcher key (env -> cache -> 1P) ---
KEYHELPER=""
for C in "$SDIR/brisen_lab_terminal_key.sh" "$HOME/bm-b1/scripts/brisen_lab_terminal_key.sh"; do
    [ -f "$C" ] && { KEYHELPER="$C"; break; }
done
[ -n "$KEYHELPER" ] || fail "terminal-key helper not found (fail-closed)" 2
# shellcheck disable=SC1090
. "$KEYHELPER"
KEY="$(brisen_lab_read_terminal_key "$SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
[ -n "$KEY" ] || fail "researcher terminal key unavailable (no env, no cache, no 1P)" 2

# --- single high-limit fetch of the OWN mailbox (read-only). NO since-floor:
# codex #9250 — a since-floor would drop older thread members while claiming
# completeness. thread_complete is derived from whether we hit FETCH_LIMIT. ---
RESP="$(curl -sS --max-time 25 -G \
    -H "X-Terminal-Key: ${KEY}" \
    --data-urlencode "limit=${FETCH_LIMIT}" \
    "${DAEMON}/msg/${SLUG}" 2>/dev/null)" || fail "brisen-lab unreachable (GET /msg/${SLUG})" 3
[ -n "$RESP" ] || fail "empty response from daemon" 3
printf '%s' "$RESP" | grep -q 'bad_terminal_key' && fail "brisen-lab rejected researcher key" 3

printf '%s' "$RESP" | \
  MSGID="$MSGID" THREAD="$THREAD" PAGE="$PAGE" PAGE_SIZE="$PAGE_SIZE" \
  CAP="$BODY_PREVIEW_CAP" FETCH_LIMIT="$FETCH_LIMIT" python3 -c '
import json, os, sys

cap = int(os.environ["CAP"])
fetch_limit = int(os.environ["FETCH_LIMIT"])
msgid = os.environ.get("MSGID") or ""
thread = os.environ.get("THREAD") or ""
page = os.environ.get("PAGE") or ""
page_size = os.environ.get("PAGE_SIZE") or ""

try:
    data = json.loads(sys.stdin.read())
except Exception as exc:
    print("read_message: could not parse daemon response: %s" % exc, file=sys.stderr)
    sys.exit(1)
msgs = data if isinstance(data, list) else data.get("messages", [])
window_truncated = len(msgs) >= fetch_limit   # hit the limit => cannot prove completeness

def body_of(m):
    return m.get("body") or m.get("body_preview") or ""

def emit_header(m):
    to = m.get("to_terminals")
    print("── #%s ── thread=%s  from=%s  to=%s  topic=%s  %s" % (
        m.get("id"), m.get("thread_id"), m.get("from_terminal"),
        ",".join(to) if isinstance(to, list) else to,
        m.get("topic"), str(m.get("created_at", ""))[:19]))
    print("   acked=%s" % ("yes" if m.get("acknowledged_at") else "no"))

def emit_body(body):
    nbytes = len(body.encode("utf-8"))   # UTF-8 bytes, not char count (codex note)
    nchars = len(body)
    truncated = (nchars >= cap)          # provable: <cap = complete; ==cap = truncated
    print("   length: %d chars, %d UTF-8 bytes  |  truncated=%s" % (
        nchars, nbytes, "true" if truncated else "false"))
    if truncated:
        print("   ⚠ body is at the %d-char daemon cap — the tail is UNREACHABLE via the current"
              " API (GET /msg/<id> = reader_slug_mismatch). A daemon full-body endpoint is"
              " needed to read past the cap (tranche-2 follow-up)." % cap)
    # optional pagination of a single body
    if page and page_size:
        p = int(page); ps = int(page_size)
        start = (p - 1) * ps
        chunk = body[start:start + ps]
        total_pages = (nchars + ps - 1) // ps if ps else 1
        print("   ── page %d/%d (chars %d–%d) ──" % (p, total_pages, start, start + len(chunk)))
        print(chunk)
    else:
        print(body)

if thread:
    rows = [m for m in msgs if str(m.get("thread_id")) == thread]
    rows.sort(key=lambda m: m.get("created_at", ""))
    thread_complete = not window_truncated
    print("thread %s: %d message(s) in window  |  thread_complete=%s" % (
        thread, len(rows), "true" if thread_complete else "false"))
    if not thread_complete:
        print("⚠ the %d-row fetch window was full — older thread members may exist beyond it;"
              " thread_complete=false (no cursor contract in the list API)." % fetch_limit)
    if not rows:
        print("(no messages with that thread_id in the current window)")
    for m in rows:
        emit_header(m)
        emit_body(body_of(m))
    sys.exit(0)

# single message by id
hit = next((m for m in msgs if str(m.get("id")) == msgid), None)
if hit is None:
    if window_truncated:
        print("read_message: msg #%s not found in the newest %d messages — it may be older than"
              " the fetch window (no cursor contract to page further)." % (msgid, fetch_limit),
              file=sys.stderr)
    else:
        print("read_message: msg #%s is not in researcher\x27s mailbox." % msgid, file=sys.stderr)
    sys.exit(4)
emit_header(hit)
emit_body(body_of(hit))
'
