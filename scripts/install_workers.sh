#!/usr/bin/env bash
# install_workers.sh — Stage 3 Phase 1 idempotent installer.
# BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.
#
# Per B-code:
#   - Creates ~/Library/Application Support/baker/worker-bN/
#   - Fetches BRISEN_LAB_TERMINAL_KEY_bN from 1Password, writes mode 0600 key file
#   - Renders com.baker.worker-bN.plist from template (string substitution only)
#   - launchctl unload (best-effort) + launchctl load
#
# Plus the daily digest job (com.baker.worker-digest).
#
# Usage:
#   BAKER_API_KEY=$(op read "op://Baker API Keys/BAKER_API_KEY/credential") \
#   SLACK_WEBHOOK_URL=$(op read "op://Baker API Keys/BAKER_WORKER_SLACK_WEBHOOK/credential") \
#   ./scripts/install_workers.sh
# Optional:
#   WORKERS="b1 b2"          # default: b1 b2 b3 b4
#   SCRIPTS_DIR=/abs/path    # default: dirname of this script
#   SKIP_DIGEST=1            # don't install com.baker.worker-digest
#
# Idempotent: safe to re-run. Unloads + reloads each plist.

set -euo pipefail

WORKERS="${WORKERS:-b1 b2 b3 b4}"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "$SCRIPT_PATH")" && pwd)}"
TEMPLATE_BN="$SCRIPTS_DIR/templates/com.baker.worker-bN.plist.template"
TEMPLATE_DIGEST="$SCRIPTS_DIR/templates/com.baker.worker-digest.plist.template"
WORKER_PY="$SCRIPTS_DIR/baker_worker.py"
DIGEST_PY="$SCRIPTS_DIR/worker_digest.py"

if [ ! -f "$TEMPLATE_BN" ]; then
    echo "ERROR: missing $TEMPLATE_BN" >&2
    exit 1
fi
if [ ! -f "$WORKER_PY" ]; then
    echo "ERROR: missing $WORKER_PY" >&2
    exit 1
fi
if [ -z "${BAKER_API_KEY:-}" ] || [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
    echo "ERROR: BAKER_API_KEY and SLACK_WEBHOOK_URL must be set in env" >&2
    exit 1
fi
if ! command -v op >/dev/null 2>&1; then
    echo "ERROR: 1Password CLI 'op' not found in PATH" >&2
    exit 1
fi

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LAUNCH_AGENTS" "$LOG_DIR"

# Substitute placeholders in a template file → stdout.
# Uses python3 to avoid sed escaping headaches with key/webhook chars.
_render_template() {
    local tpl="$1"; shift
    python3 - "$tpl" "$@" <<'PY'
import sys
tpl = open(sys.argv[1]).read()
# argv[2:] are alternating key value pairs.
pairs = sys.argv[2:]
if len(pairs) % 2 != 0:
    sys.exit("template render: odd argv count")
for i in range(0, len(pairs), 2):
    tpl = tpl.replace(pairs[i], pairs[i + 1])
sys.stdout.write(tpl)
PY
}

for N in $WORKERS; do
    case "$N" in
        b1|b2|b3|b4) ;;
        *) echo "ERROR: invalid worker slug: $N (must be b1-b4)" >&2; exit 1 ;;
    esac

    STATE_DIR="$HOME/Library/Application Support/baker/worker-$N"
    PLIST="$LAUNCH_AGENTS/com.baker.worker-$N.plist"
    KEY_FILE="$STATE_DIR/key"

    mkdir -p "$STATE_DIR"

    KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_$N/credential" 2>/dev/null || true)"
    if [ -z "$KEY" ]; then
        echo "ERROR: empty/missing 1P entry BRISEN_LAB_TERMINAL_KEY_$N" >&2
        exit 1
    fi
    umask 077
    printf '%s\n' "$KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    umask 022

    _render_template "$TEMPLATE_BN" \
        "__SLUG__" "$N" \
        "__HOME__" "$HOME" \
        "__WORKER_PATH__" "$WORKER_PY" \
        "__BAKER_API_KEY__" "$BAKER_API_KEY" \
        "__SLACK_WEBHOOK_URL__" "$SLACK_WEBHOOK_URL" \
        > "$PLIST.tmp"
    chmod 600 "$PLIST.tmp"
    mv "$PLIST.tmp" "$PLIST"

    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"

    echo "Installed worker-$N (state=$STATE_DIR plist=$PLIST)"
done

if [ -z "${SKIP_DIGEST:-}" ]; then
    if [ ! -f "$TEMPLATE_DIGEST" ] || [ ! -f "$DIGEST_PY" ]; then
        echo "WARN: digest template/script missing; skipping digest install" >&2
    else
        DIGEST_PLIST="$LAUNCH_AGENTS/com.baker.worker-digest.plist"
        _render_template "$TEMPLATE_DIGEST" \
            "__HOME__" "$HOME" \
            "__DIGEST_PATH__" "$DIGEST_PY" \
            "__BAKER_API_KEY__" "$BAKER_API_KEY" \
            "__SLACK_WEBHOOK_URL__" "$SLACK_WEBHOOK_URL" \
            > "$DIGEST_PLIST.tmp"
        chmod 600 "$DIGEST_PLIST.tmp"
        mv "$DIGEST_PLIST.tmp" "$DIGEST_PLIST"
        launchctl unload "$DIGEST_PLIST" 2>/dev/null || true
        launchctl load "$DIGEST_PLIST"
        echo "Installed worker-digest (plist=$DIGEST_PLIST)"
    fi
fi

echo
echo "Verify:"
echo "  launchctl list | grep com.baker.worker"
echo "  tail -f ~/Library/Logs/baker-worker-b1.log"
echo
echo "Manual kick (test wake):"
echo "  launchctl kickstart -k gui/\$(id -u)/com.baker.worker-b1"
echo
echo "Disable a worker: edit its plist BAKER_WORKER_ENABLED=false + reload."
echo "Kill all: for N in b1 b2 b3 b4; do launchctl unload ~/Library/LaunchAgents/com.baker.worker-\$N.plist; done"
