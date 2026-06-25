#!/usr/bin/env bash
# Smoke test for install_forge_push.sh — verifies the worker AND its sourced
# agent_identity_generated.sh sibling are BOTH co-deployed to the TCC-safe
# location.
#
# Regression for INSTALL_TOOLING_FASTFOLLOW_1 FIX 1: the prior installer copied
# only the worker, leaving a stale/missing deployed identity. Because the worker
# sources agent_identity_generated.sh from its own SCRIPT_DIR
# (forge_snapshot_push.sh:15), the deployed copy then carried an out-of-date
# slug list and the snapshot pusher rejected newly-added slugs
# (e.g. baden-baden-desk → HTTP 400 every 30s, card columns stayed null).
#
# Uses FORGE_INSTALL_DRYRUN=1 (skip launchctl/plist mutation) +
# FORGE_INSTALL_DEPLOY_DIR (redirect deploy into a tmp dir) so the test never
# touches the real launchd agent or ~/Library/Application Support/baker.

set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/install_forge_push.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }
SCRIPTS_DIR="$(dirname "$SCRIPT")"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DEPLOY="$TMP/deploy"
OUT="$TMP/out.log"

# ─────────────────────────────────────────────────────────────────────────────
# Run the installer's dry path: file deploy only, no launchctl/plist mutation.
# ─────────────────────────────────────────────────────────────────────────────
FORGE_KEY="test-key" \
FORGE_INSTALL_DRYRUN=1 \
FORGE_INSTALL_DEPLOY_DIR="$DEPLOY" \
  bash "$SCRIPT" > "$OUT" 2>&1 \
  || { echo "FAIL: installer dry-run exited non-zero" >&2; cat "$OUT" >&2; exit 1; }

# Case 1 — worker deployed.
[[ -f "$DEPLOY/forge_snapshot_push.sh" ]] \
  || { echo "FAIL: Case 1 — worker not deployed to $DEPLOY" >&2; cat "$OUT" >&2; exit 1; }
echo "PASS: Case 1 — worker deployed."

# Case 2 — identity sibling co-deployed (the FIX 1 regression).
[[ -f "$DEPLOY/agent_identity_generated.sh" ]] \
  || { echo "FAIL: Case 2 — agent_identity_generated.sh NOT co-deployed (FIX 1 regression)" >&2; cat "$OUT" >&2; exit 1; }
echo "PASS: Case 2 — identity sibling co-deployed alongside worker."

# Case 3 — deployed identity is byte-identical to the repo source (not stale).
cmp -s "$SCRIPTS_DIR/agent_identity_generated.sh" "$DEPLOY/agent_identity_generated.sh" \
  || { echo "FAIL: Case 3 — deployed identity differs from repo source (stale copy)" >&2; exit 1; }
echo "PASS: Case 3 — deployed identity byte-identical to repo source."

# Case 4 — identity perms are 600 (brief-specified; macOS + Linux stat).
perms="$(stat -f '%Lp' "$DEPLOY/agent_identity_generated.sh" 2>/dev/null \
         || stat -c '%a' "$DEPLOY/agent_identity_generated.sh")"
[[ "$perms" == "600" ]] \
  || { echo "FAIL: Case 4 — identity perms='$perms' (expected 600)" >&2; exit 1; }
echo "PASS: Case 4 — deployed identity perms 600."

# Case 5 — real-flow value: the deployed identity sources and validates a
# recently-added slug a stale copy would reject (the FIX 1 anchor slug).
( . "$DEPLOY/agent_identity_generated.sh"; agent_identity_is_valid_slug "baden-baden-desk" ) \
  || { echo "FAIL: Case 5 — deployed identity rejects baden-baden-desk (stale slug list)" >&2; exit 1; }
echo "PASS: Case 5 — deployed identity sources + validates baden-baden-desk."

echo ""
echo "All 5 cases PASS."
