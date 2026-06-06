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
# Auth: fetches per-terminal key from 1Password via `op read`. Auto-resolves
# slug from BAKER_ROLE (matches scripts/bus_post.sh ROLE_TO_SLUG mapping).
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
# SHA256: 851feca2101e2324f4bfdddd0db0bc5f3be0ec1163195e52de922f2c0f1a732d
case "${BAKER_ROLE:-}" in
    lead|LEAD|AH1|aihead1|AIHEAD1) SLUG=lead ;;
    cowork-ah1|COWORK-AH1|cowork_ah1|COWORK_AH1|AH1-APP) SLUG=cowork-ah1 ;;
    deputy|DEPUTY|AH2|aihead2|AIHEAD2) SLUG=deputy ;;
    deputy-codex|DEPUTY-CODEX|deputy_codex|DEPUTY_CODEX) SLUG=deputy-codex ;;
    cortex|CORTEX) SLUG=cortex ;;
    aid|AID|ai-dennis|AI-DENNIS) SLUG=aid ;;
    b1|B1) SLUG=b1 ;;
    b2|B2) SLUG=b2 ;;
    b3|B3) SLUG=b3 ;;
    b4|B4) SLUG=b4 ;;
    researcher|RESEARCHER|research-agent|RESEARCH-AGENT) SLUG=researcher ;;
    codex|CODEX) SLUG=codex ;;
    codex-arch|CODEX-ARCH|codex_arch|CODEX_ARCH) SLUG=codex-arch ;;
    clerk|CLERK) SLUG=clerk ;;
    clerk-haiku|CLERK-HAIKU|clerk_haiku|CLERK_HAIKU) SLUG=clerk-haiku ;;
    hag-desk|HAG-DESK|hag_desk|HAG_DESK|hagenauer-desk|HAGENAUER-DESK) SLUG=hag-desk ;;
    origination-desk|ORIGINATION-DESK|origination_desk|ORIGINATION_DESK) SLUG=origination-desk ;;
    CM-1|CM_1|cm-1) SLUG=CM-1 ;;
    CM-2|CM_2|cm-2) SLUG=CM-2 ;;
    CM-3|CM_3|cm-3) SLUG=CM-3 ;;
    CM-4|CM_4|cm-4) SLUG=CM-4 ;;
    hag-filer|HAG-FILER|hag_filer|HAG_FILER) SLUG=hag-filer ;;
    *)
        # No BAKER_ROLE → silent no-op. Cwd-based fallback intentionally NOT
        # mirrored here to avoid auto-draining for sessions not meant to be on
        # the fleet bus (e.g. Director's own Cowork sessions).
        exit 0
        ;;
esac
# END GENERATED AGENT IDENTITY ROLE MAP

# --- fetch terminal key from 1Password ---

KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SLUG}/credential" 2>/dev/null)"
if [ -z "$KEY" ]; then
    printf '[bus-drain] 1Password fetch failed for slug=%s — skipping bus drain this session.\n' "$SLUG" | _emit
    exit 0
fi

# --- read last_seen state, default to 24h ago on first boot ---

STATE_FILE="${HOME}/.brisen-lab-bus-last-seen-${SLUG}.txt"
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

# Parse + render via python3 with env vars on the python3 invocation itself.
# B1 fold: env vars on python3, not on _emit pipe-tail (that's a separate subprocess).
# RESP plumbed via env-var instead of stdin so stdout flows cleanly into _emit.
RENDERED="$(RESP="$RESP" SLUG="$SLUG" STATE_FILE="$STATE_FILE" \
            DAEMON_URL="$DAEMON_URL" BAKER_ROLE="${BAKER_ROLE:-}" SINCE="$SINCE" \
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
lines.append("To reply: BAKER_ROLE={} ~/Desktop/baker-code/scripts/bus_post.sh <recipient> \"<body>\" <topic>".format(baker_role))

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

print("\n".join(lines))
')"

if [ -n "$RENDERED" ]; then
    printf '%s\n' "$RENDERED" | _emit
fi

exit 0
