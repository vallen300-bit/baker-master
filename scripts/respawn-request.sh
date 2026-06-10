#!/usr/bin/env bash
# Post a rollover respawn request to the dispatcher and this worker's own slug.
set -euo pipefail

if [ $# -lt 6 ]; then
  echo "Usage: $0 <dispatcher-slug> <brief-id> <checkpoint-path> <attempt> <branch> <state>" >&2
  exit 2
fi

DISPATCHER="$1"
BRIEF_ID="$2"
CHECKPOINT_PATH="$3"
ATTEMPT="$4"
BRANCH="$5"
STATE="$6"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/agent_identity_generated.sh
. "$SCRIPT_DIR/agent_identity_generated.sh"

if ! SELF="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
  echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'" >&2
  exit 1
fi

BODY="RESPAWN_REQUEST ${BRIEF_ID}: checkpoint=${CHECKPOINT_PATH}; attempt=${ATTEMPT}; branch=${BRANCH}; state=${STATE}; claim=attempt-bump-commit-not-ack."
TO="${DISPATCHER},${SELF}"
TOPIC="rollover/${BRIEF_ID}"

if [ "${RESPAWN_REQUEST_DRY_RUN:-}" = "true" ]; then
  printf 'to=%s\nkind=dispatch\ntopic=%s\nbody=%s\n' "$TO" "$TOPIC" "$BODY"
  exit 0
fi

BAKER_ROLE="$SELF" "$SCRIPT_DIR/bus_post.py" --to "$TO" --body "$BODY" --topic "$TOPIC" --kind dispatch --tier B
