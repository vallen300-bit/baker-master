#!/usr/bin/env bash
# codex-bus-reply.sh — codex replies to AH1 on the bus, credential-safe.
# Wraps bus_post.sh with BAKER_ROLE=codex set internally so the key
# never appears in codex's argv (guardian-friendly).
#
# Usage: bash ~/bm-aihead1/scripts/codex-bus-reply.sh <topic> "<body>"
# Example: bash ~/bm-aihead1/scripts/codex-bus-reply.sh verify/pr-268 "PASS — no findings"
#
# Director-ratified 2026-05-29 codex install Phase 1 fold (INSTALL.md §Fold 3).

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <topic> \"<body>\"" >&2
  echo "Example: $0 verify/pr-268 \"PASS — no findings\"" >&2
  exit 1
fi

TOPIC="$1"
BODY="$2"

# Locate canonical bus_post.sh — try common paths in order.
for P in \
    "${HOME}/bm-aihead1/scripts/bus_post.sh" \
    "${HOME}/Desktop/baker-code/scripts/bus_post.sh"; do
  if [[ -x "$P" ]]; then
    BUS_POST="$P"
    break
  fi
done

if [[ -z "${BUS_POST:-}" ]]; then
  echo "ERROR: bus_post.sh not found in known locations." >&2
  exit 2
fi

BAKER_ROLE=codex exec "$BUS_POST" lead "$BODY" "$TOPIC"
