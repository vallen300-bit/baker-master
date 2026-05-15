#!/usr/bin/env bash
# install_workers.sh — Stage 3 Phase 1 idempotent installer for B-code self-wake workers.
# BRIEF_WORKER_SELFWAKE_PHASE_1 — Director-ratified 2026-05-14.
#
# Creates per-worker state dirs, fetches terminal-keys from 1Password, renders
# launchd plists from templates, loads them via launchctl. Optionally installs
# the daily-digest job too.
#
# Usage:
#   BAKER_KEY=$(op read 'op://Baker API Keys/BAKER_KEY/credential') \
#   SLACK_WEBHOOK_URL=$(op read 'op://Baker API Keys/SLACK_WEBHOOK_URL/credential') \
#   ./scripts/install_workers.sh
#
# Optional:
#   WORKERS="b1"          (default: "b1 b2 b3 b4"; install single worker first)
#   INSTALL_DIGEST=true   (default: false; load com.baker.worker-digest too)
#
# Idempotent: safe to re-run. Unloads + reloads plists on rerun.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_WORKER="$REPO_ROOT/scripts/templates/com.baker.worker-bN.plist.template"
TEMPLATE_DIGEST="$REPO_ROOT/scripts/templates/com.baker.worker-digest.plist.template"

WORKERS="${WORKERS:-b1 b2 b3 b4}"
INSTALL_DIGEST="${INSTALL_DIGEST:-false}"

if [ ! -f "$TEMPLATE_WORKER" ]; then
    echo "ERROR: missing $TEMPLATE_WORKER" >&2
    exit 1
fi
if [ -z "${BAKER_KEY:-}" ] || [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
    echo "ERROR: BAKER_KEY and SLACK_WEBHOOK_URL must be set in env" >&2
    echo "  Example: BAKER_KEY=\$(op read '...') SLACK_WEBHOOK_URL=\$(op read '...') $0" >&2
    exit 1
fi

LOG_DIR="$HOME/Library/Logs"
LA_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR" "$LA_DIR"

# Substitute placeholders in a plist template. Uses python3 (sed has trouble
# with special chars in BAKER_KEY / SLACK_WEBHOOK_URL — slashes, ampersands).
_render_plist() {
    local template_path="$1"
    local out_path="$2"
    local slug="${3:-}"
    python3 - "$template_path" "$out_path" "$slug" "$BAKER_KEY" "$SLACK_WEBHOOK_URL" <<'PY'
import sys
tpl, out, slug, baker_key, slack_url = sys.argv[1:6]
with open(tpl) as f:
    text = f.read()
if slug:
    text = text.replace("bN", slug)
n = text.count("<string>FILLED_BY_INSTALLER</string>")
if n < 1:
    sys.exit(f"ERROR: no FILLED_BY_INSTALLER placeholders in {tpl}")
# Replace first occurrence with BAKER_KEY, second with SLACK_WEBHOOK_URL.
parts = text.split("<string>FILLED_BY_INSTALLER</string>", 2)
text = parts[0] + f"<string>{baker_key}</string>" + parts[1]
if len(parts) == 3:
    text += f"<string>{slack_url}</string>" + parts[2]
with open(out, "w") as f:
    f.write(text)
PY
}

for N in $WORKERS; do
    case "$N" in
        b1|b2|b3|b4) ;;
        *) echo "ERROR: unsupported worker slug '$N' (Phase 1 = b1-b4)" >&2; exit 1 ;;
    esac

    STATE_DIR="$HOME/Library/Application Support/baker/worker-$N"
    PLIST="$LA_DIR/com.baker.worker-$N.plist"
    mkdir -p "$STATE_DIR"

    # Fetch + write terminal key (mode 0600). 1P CLI must be authenticated.
    KEY=$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_$N/credential")
    if [ -z "$KEY" ]; then
        echo "ERROR: empty terminal-key for $N" >&2
        exit 1
    fi
    umask 077
    printf '%s' "$KEY" > "$STATE_DIR/key"
    chmod 600 "$STATE_DIR/key"
    umask 022

    _render_plist "$TEMPLATE_WORKER" "$PLIST.tmp" "$N"
    mv "$PLIST.tmp" "$PLIST"
    chmod 600 "$PLIST"

    # Reload: unload (tolerated if not yet loaded) + load
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"

    echo "Installed worker-$N (state=$STATE_DIR, plist=$PLIST)"
done

if [ "$INSTALL_DIGEST" = "true" ]; then
    if [ ! -f "$TEMPLATE_DIGEST" ]; then
        echo "ERROR: missing $TEMPLATE_DIGEST" >&2
        exit 1
    fi
    PLIST="$LA_DIR/com.baker.worker-digest.plist"
    _render_plist "$TEMPLATE_DIGEST" "$PLIST.tmp" ""
    mv "$PLIST.tmp" "$PLIST"
    chmod 600 "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "Installed worker-digest (plist=$PLIST)"
fi

echo
echo "Verify:"
echo "  launchctl list | grep com.baker.worker"
echo "  tail -f $LOG_DIR/baker-worker-b1.log"
echo
echo "Manual kick (single cycle):"
echo "  launchctl kickstart -k gui/\$(id -u)/com.baker.worker-b1"
echo
echo "Disable: set BAKER_WORKER_ENABLED=false in plist + launchctl unload + launchctl load."
echo "Kill all:  for n in b1 b2 b3 b4; do launchctl unload $LA_DIR/com.baker.worker-\$n.plist; done"
