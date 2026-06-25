#!/usr/bin/env bash
# install_forge_push.sh — install or reinstall the forge-snapshot-push launchd agent.
# Idempotent: unloads existing, regenerates plist with current FORGE_KEY, reloads.
# TCC-aware: deploys worker script to ~/Library/Application Support/baker/ so
# launchd can read it (the repo path under ~/Desktop is blocked by TCC).

set -euo pipefail

if [[ -z "${FORGE_KEY:-}" ]]; then
  echo "FATAL: FORGE_KEY env var must be set in the calling shell" >&2
  exit 2
fi

LABEL="com.baker.forge-snapshot-push"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER_SRC="${SCRIPT_DIR}/forge_snapshot_push.sh"
# IDENTITY_SRC: the generated agent-identity registry the worker sources at
# runtime via its own SCRIPT_DIR (forge_snapshot_push.sh:15). It MUST be
# co-deployed next to the worker, or the launchd copy sources a stale/missing
# slug list and the snapshot pusher rejects newly-added slugs (e.g. it 400s
# on a desk added after the last deploy). Prior installs copied only the
# worker — INSTALL_TOOLING_FASTFOLLOW_1 FIX 1 closes that gap.
IDENTITY_SRC="${SCRIPT_DIR}/agent_identity_generated.sh"
# Deploy dir is overridable for tests (FORGE_INSTALL_DEPLOY_DIR); production
# default is the TCC-safe Application Support path launchd can read.
WORKER_DEPLOY_DIR="${FORGE_INSTALL_DEPLOY_DIR:-$HOME/Library/Application Support/baker}"
WORKER_DEPLOY="${WORKER_DEPLOY_DIR}/forge_snapshot_push.sh"
IDENTITY_DEPLOY="${WORKER_DEPLOY_DIR}/agent_identity_generated.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/${LABEL}.plist"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

[[ -f "$WORKER_SRC"   ]] || { echo "FATAL: worker script missing at $WORKER_SRC"     >&2; exit 2; }
[[ -f "$IDENTITY_SRC" ]] || { echo "FATAL: identity script missing at $IDENTITY_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"     ]] || { echo "FATAL: plist template missing at $TEMPLATE"      >&2; exit 2; }

# 1. Deploy worker script + its sourced identity sibling to TCC-safe location.
mkdir -p "$WORKER_DEPLOY_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY"
chmod +x "$WORKER_DEPLOY"
cp "$IDENTITY_SRC" "$IDENTITY_DEPLOY"
chmod 600 "$IDENTITY_DEPLOY"

# Dry-run path (tests): file deploy only — skip launchctl + plist mutation so
# the smoke test never touches the real launchd agent or the live deploy dir.
if [[ -n "${FORGE_INSTALL_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed worker + identity to $WORKER_DEPLOY_DIR (skipped launchctl/plist)."
  echo "  Worker:   $WORKER_DEPLOY"
  echo "  Identity: $IDENTITY_DEPLOY"
  exit 0
fi

# 2. Unload existing agent if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 3. Generate plist with FORGE_KEY + WORKER_PATH substituted via Python
# str.replace — unconditionally safe regardless of key content (no
# delimiter-escape concerns).
python3 -c "
import os, sys
template_path = sys.argv[1]
worker_deploy = sys.argv[2]
forge_key = os.environ['FORGE_KEY']
with open(template_path) as f:
    body = f.read()
body = body.replace('__FORGE_KEY__', forge_key)
body = body.replace('__WORKER_PATH__', worker_deploy)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" > "$INSTALLED_PLIST"
chmod 600 "$INSTALLED_PLIST"   # protect the embedded secret

# 4. Load the agent.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed:"
echo "  Worker:   $WORKER_DEPLOY"
echo "  Identity: $IDENTITY_DEPLOY"
echo "  Plist:    $INSTALLED_PLIST"
echo "Verify: launchctl list | grep $LABEL"
echo "Log:    ~/Library/Logs/forge-snapshot-push.log"
