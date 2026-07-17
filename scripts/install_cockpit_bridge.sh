#!/usr/bin/env bash
# install_cockpit_bridge.sh — stage (and, only with --load, start) the
# cockpit-in-Lab bridge agent launchd daemon.
#
# COCKPIT_IN_LAB_BRIDGE_1 (b1, lead #12566). BUILD-NOT-FLIP: by default this
# script only DEPLOYS the worker + plist. It does NOT load the launchd agent —
# loading is a morning-GO step, gated behind --load (or COCKPIT_BRIDGE_LOAD=1).
#
# TCC-aware, mirrors install_forge_push.sh: the worker + its shared codec are
# copied to ~/Library/Application Support/baker/cockpit-bridge/ so launchd can
# read them (the repo path may be TCC-blocked).
#
# The bridge KEY is never handled here and never embedded in the plist. Provision
# it out of band before loading:
#     mkdir -p ~/.brisen-lab/keys && chmod 700 ~/.brisen-lab/keys
#     printf '%s' '<key>' > ~/.brisen-lab/keys/cockpit-bridge
#     chmod 600 ~/.brisen-lab/keys/cockpit-bridge
# and set the SAME value as BRISEN_LAB_COCKPIT_BRIDGE_KEY on the Lab (Render env).

set -euo pipefail

LABEL="com.baker.cockpit-bridge"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER_SRC="${SCRIPT_DIR}/cockpit_bridge_agent.py"
CODEC_SRC="${SCRIPT_DIR}/cockpit_mux.py"
TEMPLATE="${SCRIPT_DIR}/launchd/${LABEL}.plist"

DEPLOY_DIR="${COCKPIT_BRIDGE_DEPLOY_DIR:-$HOME/Library/Application Support/baker/cockpit-bridge}"
WORKER_DEPLOY="${DEPLOY_DIR}/cockpit_bridge_agent.py"
CODEC_DEPLOY="${DEPLOY_DIR}/cockpit_mux.py"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

# Python that has httpx + websockets installed. Override with COCKPIT_BRIDGE_PYTHON.
PYTHON_BIN="${COCKPIT_BRIDGE_PYTHON:-$(command -v python3)}"

DO_LOAD=0
for arg in "$@"; do
  case "$arg" in
    --load) DO_LOAD=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
[[ "${COCKPIT_BRIDGE_LOAD:-}" == "1" ]] && DO_LOAD=1

[[ -f "$WORKER_SRC"   ]] || { echo "FATAL: worker missing at $WORKER_SRC"   >&2; exit 2; }
[[ -f "$CODEC_SRC"    ]] || { echo "FATAL: codec missing at $CODEC_SRC"     >&2; exit 2; }
[[ -f "$TEMPLATE"     ]] || { echo "FATAL: plist template missing at $TEMPLATE" >&2; exit 2; }
[[ -n "$PYTHON_BIN"   ]] || { echo "FATAL: no python3 found (set COCKPIT_BRIDGE_PYTHON)" >&2; exit 2; }

# 1. Deploy worker + shared codec to the TCC-safe location.
mkdir -p "$DEPLOY_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY"; chmod +x "$WORKER_DEPLOY"
cp "$CODEC_SRC"  "$CODEC_DEPLOY"

# 2. Render the plist (no secret substituted — only python + worker path).
python3 -c "
import sys
tpl, py, worker = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(tpl).read().replace('__PYTHON__', py).replace('__WORKER_PATH__', worker)
sys.stdout.write(body)
" "$TEMPLATE" "$PYTHON_BIN" "$WORKER_DEPLOY" > "$INSTALLED_PLIST"
chmod 644 "$INSTALLED_PLIST"

echo "Staged:"
echo "  Worker:   $WORKER_DEPLOY"
echo "  Codec:    $CODEC_DEPLOY"
echo "  Plist:    $INSTALLED_PLIST"
echo "  Python:   $PYTHON_BIN"

if [[ "$DO_LOAD" -ne 1 ]]; then
  echo
  echo "BUILD-NOT-FLIP: launchd agent NOT loaded (default)."
  echo "Morning GO steps:"
  echo "  1. Provision key: ~/.brisen-lab/keys/cockpit-bridge (chmod 600) + Lab env BRISEN_LAB_COCKPIT_BRIDGE_KEY (same value)."
  echo "  2. Set Render env COCKPIT_EMBED_ENABLED=1 (and COCKPIT_ACCESS_TOKEN recommended)."
  echo "  3. Load agent: bash $0 --load   (or: launchctl load -w \"$INSTALLED_PLIST\")."
  echo "  4. Verify: launchctl list | grep $LABEL ; tail ~/Library/Logs/cockpit-bridge-agent.log"
  exit 0
fi

# 3. (--load only) start the daemon.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
launchctl load -w "$INSTALLED_PLIST"
echo
echo "Loaded launchd agent $LABEL."
echo "Verify: launchctl list | grep $LABEL"
echo "Log:    ~/Library/Logs/cockpit-bridge-agent.log"
echo "Kill switch: launchctl bootout gui/\$(id -u)/$LABEL   (or unset COCKPIT_EMBED_ENABLED on the Lab)."
