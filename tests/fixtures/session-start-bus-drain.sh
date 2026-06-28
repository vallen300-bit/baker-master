#!/usr/bin/env bash
# SessionStart hook: drain Brisen Lab V2 bus inbox for the current terminal's
# BAKER_ROLE slug and emit unread messages as additionalContext.
#
# Canonical source: tests/fixtures/session-start-bus-drain.sh in baker-master.
# Deployed as user-global at ~/.claude/hooks/session-start-bus-drain.sh
# (Director ratifies the cp pre-merge per BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN
# §Sequencing step 3). Drift detectable via:
#   diff ~/.claude/hooks/session-start-bus-drain.sh tests/fixtures/session-start-bus-drain.sh
#
# Contract: never block session start. Exit 0 on every path. Errors emit a
# short status line as additionalContext so Director sees the gap.
#
# Auth: resolves per-terminal key by literal env, then
# ~/.brisen-lab/keys/<slug>, then last-resort 1Password `op read`.
# Auto-resolves slug from BAKER_ROLE (matches scripts/bus_post.sh ROLE_TO_SLUG
# mapping).
#
# State: ~/.brisen-lab-bus-last-seen-<slug>.txt holds the ISO-8601 timestamp
# of the newest message drained on the previous SessionStart. First run uses
# the past 24h as the since cursor (drain-on-first-boot ceiling).
#
# V0.2 reviewer-fold deltas (vs brief §Implementation script body):
#   B1 — env vars on python3 invocation (not _emit pipe-tail) so os.environ[...] resolves.
#   B2 — atomic state-file write via tempfile.mkstemp + os.replace.
#   B4 — curl --max-time 4 (worst-case ~7s vs 15s hook timeout).
#   Token-budget — curl limit=50 + RENDER_CAP=30 in python3 block.
#
# V0.3 — rendered-ID ledger (ack-only-what-renders, 2026-06-11):
#   Every message actually RENDERED into additionalContext gets its id appended
#   to ~/.brisen-lab-bus-rendered-<slug>.txt. The turn-end Stop hook
#   (stop-bus-ack.sh) acks ONLY ids present in that ledger — never messages the
#   agent has not seen. Anchor: 2026-06-10 incident — 6 ship reports auto-acked
#   without rendering (PINNED §OPEN-2).

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

# --- resolve sender slug from BAKER_ROLE ---

# BEGIN GENERATED AGENT IDENTITY ROLE MAP
# Generated from /Users/dimitry/baker-vault/_ops/registries/agent_registry.yml
# SHA256: b664ecc827285b6d2c5d2af4c1188f16c6af7c315ae0d93aa89ceeb7dda22ab9
case "${BAKER_ROLE:-}" in
    AG-001|ag-001|lead|LEAD|AH1|aihead1|AIHEAD1) SLUG=lead ;;
    AG-002|ag-002|cowork-ah1|COWORK-AH1|cowork_ah1|COWORK_AH1|AH1-APP) SLUG=cowork-ah1 ;;
    AG-003|ag-003|deputy|DEPUTY|AH2|aihead2|AIHEAD2) SLUG=deputy ;;
    AG-004|ag-004|deputy-codex|DEPUTY-CODEX|deputy_codex|DEPUTY_CODEX) SLUG=deputy-codex ;;
    AG-005|ag-005|cortex|CORTEX) SLUG=cortex ;;
    AG-006|ag-006|aid|AID|ai-dennis|AI-DENNIS) SLUG=aid ;;
    AG-101|ag-101|b1|B1) SLUG=b1 ;;
    AG-102|ag-102|b2|B2) SLUG=b2 ;;
    AG-103|ag-103|b3|B3) SLUG=b3 ;;
    AG-104|ag-104|b4|B4) SLUG=b4 ;;
    AG-201|ag-201|researcher|RESEARCHER|research-agent|RESEARCH-AGENT) SLUG=researcher ;;
    AG-202|ag-202|codex|CODEX) SLUG=codex ;;
    AG-203|ag-203|codex-arch|CODEX-ARCH|codex_arch|CODEX_ARCH) SLUG=codex-arch ;;
    AG-204|ag-204|clerk|CLERK) SLUG=clerk ;;
    AG-205|ag-205|clerk-haiku|CLERK-HAIKU|clerk_haiku|CLERK_HAIKU) SLUG=clerk-haiku ;;
    AG-206|ag-206|russo-ai|RUSSO-AI|russo_ai|RUSSO_AI) SLUG=russo-ai ;;
    AG-207|ag-207|deep55|DEEP55|deep-55|DEEP-55|gpt-5.5-raw|GPT-5.5-RAW) SLUG=deep55 ;;
    AG-301|ag-301|hag-desk|HAG-DESK|hag_desk|HAG_DESK|hagenauer-desk|HAGENAUER-DESK) SLUG=hag-desk ;;
    AG-302|ag-302|origination-desk|ORIGINATION-DESK|origination_desk|ORIGINATION_DESK) SLUG=origination-desk ;;
    AG-303|ag-303|ao-desk|AO-DESK|ao_desk|AO_DESK) SLUG=ao-desk ;;
    AG-304|ag-304|movie-desk|MOVIE-DESK|movie_desk|MOVIE_DESK|moviedesk|MOVIEDESK) SLUG=movie-desk ;;
    AG-305|ag-305|baden-baden-desk|BADEN-BADEN-DESK|baden_baden_desk|BADEN_BADEN_DESK) SLUG=baden-baden-desk ;;
    AG-401|ag-401|CM-1|CM_1|cm-1) SLUG=CM-1 ;;
    AG-402|ag-402|CM-2|CM_2|cm-2) SLUG=CM-2 ;;
    AG-403|ag-403|CM-3|CM_3|cm-3) SLUG=CM-3 ;;
    AG-404|ag-404|CM-4|CM_4|cm-4) SLUG=CM-4 ;;
    AG-405|ag-405|hag-filer|HAG-FILER|hag_filer|HAG_FILER) SLUG=hag-filer ;;
    daemon|DAEMON) SLUG=daemon ;;
    dispatcher|DISPATCHER) SLUG=dispatcher ;;
    *)
        # No BAKER_ROLE → silent no-op. Cwd-based fallback intentionally NOT
        # mirrored here to avoid auto-draining for sessions not meant to be on
        # the fleet bus (e.g. Director's own Cowork sessions).
        exit 0
        ;;
esac
# END GENERATED AGENT IDENTITY ROLE MAP

# --- fetch terminal key: literal env → cache → 1Password fallback ---

_is_literal_terminal_key() {
  local value="${1:-}"
  [[ -n "$value" && "$value" != op://* ]]
}

_terminal_key_cache_file() {
  local slug="$1"
  printf '%s/.brisen-lab/keys/%s\n' "$HOME" "$slug"
}

_read_cached_terminal_key() {
  local slug="$1"
  local cache_file key
  cache_file="$(_terminal_key_cache_file "$slug")"
  [ -r "$cache_file" ] || return 1
  key="$(tr -d '\r\n' < "$cache_file" 2>/dev/null || true)"
  _is_literal_terminal_key "$key" || return 1
  printf '%s\n' "$key"
}

_write_cached_terminal_key() {
  local slug="$1"
  local key="$2"
  _is_literal_terminal_key "$key" || return 1
  [[ "$slug" =~ ^[A-Za-z0-9._-]+$ ]] || return 1

  local cache_dir cache_file tmp
  cache_dir="$HOME/.brisen-lab/keys"
  cache_file="$(_terminal_key_cache_file "$slug")"
  mkdir -p "$cache_dir" 2>/dev/null || return 1
  chmod 700 "$HOME/.brisen-lab" "$cache_dir" 2>/dev/null || true

  tmp="$(mktemp "${cache_dir}/.${slug}.tmp.XXXXXX" 2>/dev/null)" || return 1
  if printf '%s\n' "$key" > "$tmp" 2>/dev/null; then
    chmod 600 "$tmp" 2>/dev/null || true
    mv "$tmp" "$cache_file" 2>/dev/null || {
      rm -f "$tmp" 2>/dev/null || true
      return 1
    }
    chmod 600 "$cache_file" 2>/dev/null || true
    return 0
  fi

  rm -f "$tmp" 2>/dev/null || true
  return 1
}

_read_terminal_key() {
  local slug="$1"
  local env_value="${2:-}"

  if _is_literal_terminal_key "$env_value"; then
    printf '%s\n' "$env_value"
    return 0
  fi

  local cached
  cached="$(_read_cached_terminal_key "$slug" 2>/dev/null || true)"
  if _is_literal_terminal_key "$cached"; then
    printf '%s\n' "$cached"
    return 0
  fi

  command -v op >/dev/null 2>&1 || return 1

  local op_ref key
  if [[ "$env_value" == op://* ]]; then
    op_ref="$env_value"
  else
    op_ref="op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${slug}/credential"
  fi

  key="$(op read "$op_ref" 2>/dev/null || true)"
  _is_literal_terminal_key "$key" || return 1
  _write_cached_terminal_key "$slug" "$key" >/dev/null 2>&1 || true
  printf '%s\n' "$key"
}

KEY="$(_read_terminal_key "$SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
if [ -z "$KEY" ]; then
    printf '[bus-drain] 1Password fetch failed for slug=%s — skipping bus drain this session.\n' "$SLUG" | _emit
    exit 0
fi

# --- read last_seen state, default to 24h ago on first boot ---

STATE_FILE="${HOME}/.brisen-lab-bus-last-seen-${SLUG}.txt"
LEDGER_FILE="${HOME}/.brisen-lab-bus-rendered-${SLUG}.txt"
SINCE=""
if [ -f "$STATE_FILE" ]; then
    SINCE="$(cat "$STATE_FILE" 2>/dev/null | tr -d '\n\r ')"
fi
if [ -z "${SINCE:-}" ]; then
    SINCE="$(python3 -c 'import datetime; print((datetime.datetime.utcnow() - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
fi

# --- GET /msg/<slug>?since=<since>&limit=50 ---
#
# CURSOR-FORMAT-FIX (AH2 finding 2026-05-11): $SINCE contains an ISO-8601
# timestamp with literal `+00:00` offset (daemon returns offset-format, not
# Z-suffix). Raw URL interpolation causes curl to send `+` as space (URL
# spec), daemon parses garbled timestamp -> 500. Use -G + --data-urlencode
# so curl URL-encodes the cursor properly. Cursor stays in offset format on
# disk; this fix is read-side only — no state-file sweep needed.

RESP="$(curl -sS --max-time 4 -G -H "X-Terminal-Key: ${KEY}" \
        --data-urlencode "since=${SINCE}" \
        --data-urlencode "limit=50" \
        "${DAEMON_URL}/msg/${SLUG}" 2>/dev/null)" || {
    printf '[bus-drain] daemon unreachable (timeout 4s) for slug=%s — skipping.\n' "$SLUG" | _emit
    exit 0
}

# --- resolve a FRESH bus_post.sh for the reply hint (INSTALL_TOOLING_FASTFOLLOW_1
#     FIX 2, Director-ratified Option (b) via lead #4358) ---
# Never point at ~/Desktop/baker-code/scripts/bus_post.sh: that clone lags
# origin/main and its sibling agent_identity_generated.sh — which bus_post.sh
# sources via its own $0 dirname — carries a stale slug list that rejects
# newly-added slugs (the baden-baden-desk foot-gun). Prefer the agent's OWN
# running clone (no cross-clone coupling), then its per-role clone, then a fresh
# fleet clone.
BUS_POST_HINT=""
for _bp in \
    "${CLAUDE_PROJECT_DIR:-}/scripts/bus_post.sh" \
    "${HOME}/bm-${SLUG}/scripts/bus_post.sh" \
    "${HOME}/bm-aihead1/scripts/bus_post.sh"; do
  case "$_bp" in
    "/scripts/bus_post.sh") continue ;;                    # CLAUDE_PROJECT_DIR unset
    */Desktop/baker-code/scripts/bus_post.sh) continue ;;  # G2-F1: reject the stale Desktop clone even when it IS the cwd
  esac
  if [ -x "$_bp" ]; then BUS_POST_HINT="$_bp"; break; fi
done
# Last resort (nothing resolved on disk): name the per-role clone path — still
# actionable, still not the stale Desktop clone.
[ -n "$BUS_POST_HINT" ] || BUS_POST_HINT="${HOME}/bm-${SLUG}/scripts/bus_post.sh"

# Parse + render via python3 with env vars on the python3 invocation itself.
# B1 fold: env vars on python3, not on _emit pipe-tail (that's a separate subprocess).
# RESP plumbed via env-var instead of stdin so stdout flows cleanly into _emit.
RENDERED="$(RESP="$RESP" SLUG="$SLUG" STATE_FILE="$STATE_FILE" LEDGER_FILE="$LEDGER_FILE" \
            DAEMON_URL="$DAEMON_URL" BAKER_ROLE="${BAKER_ROLE:-}" SINCE="$SINCE" \
            BUS_POST_HINT="$BUS_POST_HINT" \
            python3 -c '
import json, os, sys, tempfile

try:
    d = json.loads(os.environ["RESP"])
except json.JSONDecodeError:
    print("[bus-drain] bad daemon response — skipping.")
    sys.exit(0)

if isinstance(d, dict) and "detail" in d and "messages" not in d:
    print("[bus-drain] daemon error: {} — skipping.".format(d["detail"]))
    sys.exit(0)

msgs = d.get("messages", []) if isinstance(d, dict) else []
if not msgs:
    # Quiet on empty — avoid noise in every session-start.
    sys.exit(0)

slug = os.environ["SLUG"]
state_file = os.environ["STATE_FILE"]
since = os.environ["SINCE"]
daemon_url = os.environ["DAEMON_URL"]
baker_role = os.environ["BAKER_ROLE"]

RENDER_CAP = 30
shown = msgs[:RENDER_CAP]
overflow = len(msgs) - len(shown)

lines = ["[bus-drain] {} unread message(s) for {} since {}:".format(len(msgs), slug, since)]
if overflow > 0:
    lines.append("  (rendering first {}; {} more elided — widen `since` to see all)".format(RENDER_CAP, overflow))
lines.append("")
for m in shown:
    topic = m.get("topic") or "-"
    thread = m.get("thread_id") or "-"
    acked = m["acknowledged_at"] or "no"
    lines.append("  #{} [{}] from {} -> {} | topic: {} | thread: {}".format(
        m["id"], m["kind"], m["from_terminal"], m["to_terminals"], topic, thread))
    lines.append("     posted: {}  acked: {}".format(m["created_at"], acked))
    body = m.get("body_preview") or ""
    body_lines = body.split("\n")
    first = body_lines[0] if body_lines else ""
    preview = first[:200] + ("..." if len(first) > 200 else "")
    lines.append("     body:   {}".format(preview))
    if len(body_lines) > 1:
        lines.append("     (... {} more line(s); full body via GET /event/{}/full)".format(len(body_lines) - 1, m["id"]))
    lines.append("")
lines.append("To ACK: POST {}/msg/<id>/ack with X-Terminal-Key header.".format(daemon_url))
bus_post = os.environ.get("BUS_POST_HINT") or "{}/bm-{}/scripts/bus_post.sh".format(os.environ.get("HOME", "~"), slug)
lines.append("To reply: BAKER_ROLE={} {} <recipient> \"<body>\" <topic>".format(baker_role, bus_post))

# B2 fold: atomic state-file write via tempfile.mkstemp + os.replace.
# On failure: leave canonical state file unchanged (re-drain next session beats
# silent cursor corruption). Still emit the rendered summary so messages are seen.
newest = max(m["created_at"] for m in shown)
state_dir = os.path.dirname(state_file) or "."
write_failed = False
tmp_path = None
try:
    fd, tmp_path = tempfile.mkstemp(prefix=".brisen-lab-bus-last-seen-tmp-", dir=state_dir)
    with os.fdopen(fd, "w") as f:
        f.write(newest)
    os.replace(tmp_path, state_file)
except OSError:
    write_failed = True
    if tmp_path is not None:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

if write_failed:
    lines.append("")
    lines.append("[bus-drain] state-file atomic write failed — re-drain next session.")

# V0.3 — rendered-ID ledger append. Only ids in `shown` (actually emitted into
# additionalContext) are eligible for turn-end auto-ack by stop-bus-ack.sh.
# Append-only; the Stop hook prunes acked ids. On failure: messages stay
# unacked (badge stays loud) — strictly safer than over-acking.
ledger_file = os.environ["LEDGER_FILE"]
try:
    with open(ledger_file, "a") as f:
        f.write("".join("{}\n".format(m["id"]) for m in shown))
except OSError:
    lines.append("")
    lines.append("[bus-drain] rendered-ledger append failed — turn-end auto-ack will skip these; ack manually.")

print("\n".join(lines))
')"

if [ -n "$RENDERED" ]; then
    printf '%s\n' "$RENDERED" | _emit
fi

exit 0
