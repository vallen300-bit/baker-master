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
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

# Precedence: literal env → ~/.brisen-lab/keys/codex cache → op fallback.
KEY="$(brisen_lab_read_terminal_key "codex" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"

if [[ -z "$KEY" ]]; then
  # Emit on stdout AND stderr — codex's bash-tool UI sometimes hides stderr,
  # causing the symptom "exited 1, no output". stdout guarantees the diagnostic
  # surfaces in codex's transcript regardless of stderr handling.
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex not in env/cache and 1P unreachable."
  echo "  Diagnostic: BRISEN_LAB_TERMINAL_KEY env var is empty/non-literal, cache miss, and 'op read' returned nothing."
  echo "  Fix: relaunch codex via the cdx() shell function (Shell -> New Window -> codex), which pre-fetches"
  echo "       the credential from 1Password in AH1's authenticated shell and exports it to codex's env."
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex not in env/cache and 1P unreachable." >&2
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
