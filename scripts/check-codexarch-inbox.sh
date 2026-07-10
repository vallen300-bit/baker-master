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

# BUS_READ_UNACKED_SCAN_FIX_1: default to a full-unacked scan (2000), not 10 —
# a small limit silently drops boundary unacked messages beyond the window.
LIMIT="${1:-2000}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

# Precedence: literal env → ~/.brisen-lab/keys/codex-arch cache → op fallback.
KEY="$(brisen_lab_read_terminal_key "codex-arch" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"

if [[ -z "$KEY" ]]; then
  # Emit on stdout AND stderr — codex's bash-tool UI sometimes hides stderr,
  # causing the symptom "exited 1, no output". stdout guarantees the diagnostic
  # surfaces in codex's transcript regardless of stderr handling.
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex-arch not in env/cache and 1P unreachable."
  echo "  Diagnostic: BRISEN_LAB_TERMINAL_KEY env var is empty/non-literal, cache miss, and 'op read' returned nothing."
  echo "  Fix: relaunch codex via the cdx() shell function (Shell -> New Window -> codex), which pre-fetches"
  echo "       the credential from 1Password in AH1's authenticated shell and exports it to codex's env."
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex-arch not in env/cache and 1P unreachable." >&2
  exit 2
fi

RESPONSE="$(curl -sS -H "X-Terminal-Key: $KEY" \
  "https://brisen-lab.onrender.com/msg/codex-arch?limit=${LIMIT}&unread=true")"

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
    print("codex-arch inbox: empty (no dispatches).")
    sys.exit(0)
# Unacked count excludes wildcard broadcasts (to_terminals==['*']) which 403 on
# per-terminal ack and permanently inflate the count (#7011). Seat-unacked is the
# figure that must match Lab dashboard ground truth for this slug.
unacked = [m for m in msgs if not m.get("acknowledged_at")]
residue = [m for m in unacked if m.get("to_terminals") == ['*']]
seat_unacked = [m for m in unacked if m.get("to_terminals") != ['*']]
print("codex-arch inbox:", len(msgs), "message(s),", len(seat_unacked),
      "unacked (seat),", len(residue), "broadcast residue.")
# codex G3: default render is seat-unacked ONLY + a compact residue id-list — a
# 2000-row full scan must not flood session-start bus checks with ACKed/residue
# rows. Full history (every row, ACK/UNACK/RESIDUE) behind BUS_INBOX_SHOW_ALL=1.
import os as _os
_show_all = _os.environ.get("BUS_INBOX_SHOW_ALL") == "1"
for m in (msgs if _show_all else seat_unacked):
    if not m.get("acknowledged_at"):
        state = "RESIDUE" if m.get("to_terminals") == ['*'] else "UNACK"
    else:
        state = "ACK"
    body = (m.get("body") or m.get("body_preview") or "")[:120].replace("\n", " ")
    print("  #" + str(m["id"]) + " [" + state + "] " +
          str(m.get("from_terminal","?")) + " -> " +
          str(m.get("topic","?")))
    print("      " + body)
if residue and not _show_all:
    print("  broadcast residue (wildcard, not seat-ackable): " +
          ", ".join("#" + str(m["id"]) for m in residue))
PYEOF
