#!/usr/bin/env bash
# codex-ack-inbox.sh — codex acknowledges a bus message, credential-safe.
# Fetches BRISEN_LAB_TERMINAL_KEY_codex from 1Password internally.
#
# Usage: bash ~/bm-aihead1/scripts/codex-ack-inbox.sh <message-id>
#
# Director-ratified 2026-05-29 codex install Phase 1 fold (INSTALL.md §Fold 4).

set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <message-id>" >&2
  exit 1
fi

MSG_ID="$1"

if ! [[ "$MSG_ID" =~ ^[0-9]+$ ]]; then
  echo "ERROR: message-id must be numeric, got '$MSG_ID'." >&2
  exit 1
fi

KEY="$(brisen_lab_read_terminal_key "codex-arch" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"

if [[ -z "$KEY" ]]; then
  echo "ERROR: BRISEN_LAB_TERMINAL_KEY_codex-arch not in env/cache and 1P unreachable." >&2
  echo "       Seed ~/.brisen-lab/keys/codex-arch, relaunch via 'cdx', or run 'op signin'." >&2
  exit 2
fi

HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST -H "X-Terminal-Key: $KEY" \
  "https://brisen-lab.onrender.com/msg/${MSG_ID}/ack")"

if [[ "$HTTP_CODE" == "200" ]]; then
  echo "ack #${MSG_ID} → 200"
else
  echo "ack #${MSG_ID} FAILED → HTTP $HTTP_CODE" >&2
  exit 3
fi
