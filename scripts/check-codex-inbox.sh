#!/usr/bin/env bash
# check-codex-inbox.sh — codex bus inbox poll, credential-safe.
# Fetches BRISEN_LAB_TERMINAL_KEY_codex from 1Password internally so guardian
# never sees credential in argv. Prints summary of unacked dispatches.
#
# Usage: bash ~/bm-aihead1/scripts/check-codex-inbox.sh [limit]
# Default limit: 10. Use 50 to drain backlog.
#
# Director-ratified 2026-05-29 codex install Phase 1 fold (INSTALL.md §Fold 3).

set -euo pipefail

LIMIT="${1:-10}"
KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_codex/credential' 2>/dev/null)"

if [[ -z "$KEY" ]]; then
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex not retrievable from 1Password." >&2
  echo "       Confirm 'op signin' or service-account token then retry." >&2
  exit 2
fi

RESPONSE="$(curl -sS -H "X-Terminal-Key: $KEY" \
  "https://brisen-lab.onrender.com/msg/codex?limit=${LIMIT}")"

if [[ -z "$RESPONSE" ]] || [[ "$RESPONSE" == *"bad_terminal_key"* ]]; then
  echo "ERROR: brisen-lab rejected codex key. Response: $RESPONSE" >&2
  exit 3
fi

RESPONSE_FILE="$(mktemp -t codex-inbox.XXXXXX)"
trap 'rm -f "$RESPONSE_FILE"' EXIT
printf '%s' "$RESPONSE" > "$RESPONSE_FILE"

python3 - "$RESPONSE_FILE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    try:
        d = json.load(f)
    except Exception as e:
        print("parse_error:", e); sys.exit(1)
msgs = d if isinstance(d, list) else d.get("messages", [])
if not msgs:
    print("codex inbox: empty (no dispatches).")
    sys.exit(0)
unacked = [m for m in msgs if not m.get("acknowledged_at")]
print("codex inbox:", len(msgs), "message(s),", len(unacked), "unacked.")
for m in msgs:
    state = "ACK" if m.get("acknowledged_at") else "UNACK"
    body = (m.get("body") or m.get("body_preview") or "")[:120].replace("\n", " ")
    print("  #" + str(m["id"]) + " [" + state + "] " +
          str(m.get("from_terminal","?")) + " -> " +
          str(m.get("topic","?")))
    print("      " + body)
PYEOF
