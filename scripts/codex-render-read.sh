#!/usr/bin/env bash
# codex-render-read.sh — codex queries Render API read-only with explicit endpoint whitelist.
# Fetches RENDER_API_KEY from 1Password internally. HARD-LIMITS the allowed
# endpoints; any URL containing /env-vars (secret-leak surface) is REJECTED
# at the script level.
#
# Usage: bash ~/bm-aihead1/scripts/codex-render-read.sh <endpoint>
# Examples:
#   bash ~/bm-aihead1/scripts/codex-render-read.sh /services
#   bash ~/bm-aihead1/scripts/codex-render-read.sh /services/srv-d6dgsbctgctc73f55730/deploys
#   bash ~/bm-aihead1/scripts/codex-render-read.sh /services/srv-d6dgsbctgctc73f55730/deploys/dep-d8cn3tbtqb8s738lfg50
#
# Director-ratified 2026-05-29 codex install Phase 2 §Surface 4.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <endpoint>" >&2
  echo "Whitelist: /services, /services/<id>, /services/<id>/deploys[/<id>], /services/<id>/builds, /services/<id>/events, /services/<id>/logs" >&2
  exit 1
fi

ENDPOINT="$1"

# HARD REJECT env-vars endpoint — protects all secrets.
if [[ "$ENDPOINT" == *"/env-vars"* ]]; then
  echo "ERROR: /env-vars blocked for codex by INSTALL.md Phase 2 §Surface 4 (secrets endpoint)." >&2
  echo "       For env-related questions, ask AH1 (slug 'lead') via bus." >&2
  exit 2
fi

# Allow only whitelisted endpoint shapes — defence-in-depth against typos that
# might accidentally hit a write endpoint.
# Allowed shapes:
#   /services
#   /services/<id>
#   /services/<id>/deploys
#   /services/<id>/deploys/<id>
#   /services/<id>/builds
#   /services/<id>/builds/<id>
#   /services/<id>/events
#   /services/<id>/logs (with query string is fine)
# Tight whitelist via regex anchors — wildcards in srv-<id> must NOT extend
# into additional path segments (foot-gun fixed 2026-05-29 chat: original case
# patterns let /services/srv-<id>/restart slip through).
ALLOWED=0

# Helper: strip query string for path-shape checks.
PATH_ONLY="${ENDPOINT%%\?*}"

if   [[ "$PATH_ONLY" == "/services" ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/deploys$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/deploys/dep-[A-Za-z0-9]+$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/builds$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/builds/bld-[A-Za-z0-9]+$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/events$ ]] \
  || [[ "$PATH_ONLY" =~ ^/services/srv-[A-Za-z0-9]+/logs$ ]] \
  || [[ "$PATH_ONLY" =~ ^/logs$ ]]; then
  ALLOWED=1
fi

if [[ "$ALLOWED" -ne 1 ]]; then
  echo "ERROR: endpoint not on codex whitelist: '$ENDPOINT'" >&2
  echo "Allowed: /services[/<id>[/deploys|/builds|/events|/logs]]." >&2
  exit 3
fi

# Refuse non-GET — codex must not POST / PUT / PATCH / DELETE to Render.
# (Script never specifies a method; we just leave HTTP verb as default GET.)

KEY="${CODEX_RENDER_API_KEY:-}"
if [[ -z "$KEY" ]] && command -v op >/dev/null 2>&1; then
  KEY="$(op read 'op://Baker API Keys/API Render/credential' 2>/dev/null || true)"
fi
if [[ -z "$KEY" ]]; then
  echo "ERROR: CODEX_RENDER_API_KEY not in env and 1P unreachable." >&2
  echo "       Relaunch via 'cdx' (it pre-fetches) or run 'op signin'." >&2
  exit 4
fi

URL="https://api.render.com/v1${ENDPOINT}"
exec curl -sS -H "Authorization: Bearer $KEY" "$URL"
