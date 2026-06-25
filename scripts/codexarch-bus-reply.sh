#!/usr/bin/env bash
# codex-bus-reply.sh — codex replies to the DISPATCHING agent on the bus, credential-safe.
# Wraps bus_post.sh with BAKER_ROLE=codex set internally so the key
# never appears in codex's argv (guardian-friendly).
#
# REPLY-TO-SENDER (Director-ratified 2026-05-30): codex must reply to whoever
# dispatched the task, NOT a hardcoded slug. Read the inbound message's `sender`
# (lead | cowork-ah1 | deputy | …) and pass it as the 3rd arg. Defaults to `lead`
# only for backward compatibility when no recipient is given.
#
# Usage: bash ~/bm-aihead1/scripts/codex-bus-reply.sh <topic> "<body>" [recipient]
# Example: bash ~/bm-aihead1/scripts/codex-bus-reply.sh review/pr-268 "PASS — no findings" cowork-ah1
#
# Director-ratified 2026-05-29 codex install Phase 1 fold (INSTALL.md §Fold 3);
# reply-to-sender added 2026-05-30 (wrong-inbox incident: codex + b4 replied to
# lead on a cowork-ah1 dispatch).

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <topic> \"<body>\" [recipient]" >&2
  echo "Example: $0 review/pr-268 \"PASS — no findings\" cowork-ah1" >&2
  echo "  recipient = the slug that DISPATCHED the task (read the inbound msg sender)." >&2
  echo "  Defaults to 'lead' only if omitted (backward-compat)." >&2
  exit 1
fi

TOPIC="$1"
BODY="$2"
RECIPIENT="${3:-lead}"   # reply-to-sender; default lead for backward compat

# Locate canonical bus_post.sh — try FRESH code clones in order. Never the
# ~/Desktop/baker-code clone: it lags origin/main and its sourced
# agent_identity_generated.sh rejects newly-added slugs
# (INSTALL_TOOLING_FASTFOLLOW_1 FIX 2).
for P in \
    "${HOME}/bm-aihead1/scripts/bus_post.sh" \
    "${HOME}/bm-b1/scripts/bus_post.sh"; do
  if [[ -x "$P" ]]; then
    BUS_POST="$P"
    break
  fi
done

if [[ -z "${BUS_POST:-}" ]]; then
  echo "ERROR: bus_post.sh not found in known locations." >&2
  exit 2
fi

BAKER_ROLE=codex-arch exec "$BUS_POST" "$RECIPIENT" "$BODY" "$TOPIC"
