#!/usr/bin/env bash
# install_cockpit_ttyd.sh — deploy the Cockpit tmux/ttyd substrate for BRIEF A
# (FLEET_TMUX_LAUNCH_1, scope §6/§6c). Mirrors install_forge_push.sh: TCC-safe
# deploy to ~/Library/Application Support/baker/cockpit, generate launchd plists,
# launchctl load. Idempotent.
#
# Owns the substrate side of the A<->B integration contract: the merged controller
# installer (install_cockpit_controller.sh) VALIDATES but does not copy the fleet
# launcher + manifest — so this script deploys them to the paths the controller
# reads ($DEPLOY_DIR/fleet_terminals.sh + $DEPLOY_DIR/launch_manifest.json).
#
# Credential: OWNED by the controller installer (#12074). This script only READS
# $DEPLOY_DIR/credentials for ttyd -c and NEVER writes/creates it. If it is absent
# at run time we FAIL LOUD and tell the operator to run the controller installer
# (or ask deputy-codex) — we never fabricate it.
#
# Usage:
#   install_cockpit_ttyd.sh [slug ...]     # no args = all manifest seats; else only the named seats
# Env:
#   COCKPIT_TTYD_DRYRUN=1   deploy files only; skip launchctl + plist mutation (tests/pilot staging)

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEPLOY_DIR="${COCKPIT_DEPLOY_DIR:-$HOME/Library/Application Support/baker/cockpit}"
LAUNCHD_DIR="${COCKPIT_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
LOG_DIR="${COCKPIT_LOG_DIR:-$HOME/Library/Logs/baker/cockpit}"
CREDENTIAL_PATH="${COCKPIT_CREDENTIAL_FILE:-$DEPLOY_DIR/credentials}"

MANIFEST_SRC="${COCKPIT_MANIFEST_SRC:-$SCRIPT_DIR/cockpit_launch_manifest.json}"
FLEET_SRC="$SCRIPT_DIR/fleet_terminals.sh"
TEMPLATE="$SCRIPT_DIR/launchd/com.baker.cockpit-ttyd.plist.template"
MANIFEST_DEPLOY="$DEPLOY_DIR/launch_manifest.json"   # name the controller expects
FLEET_DEPLOY="$DEPLOY_DIR/fleet_terminals.sh"

die() { echo "FATAL: $*" >&2; exit 2; }

command -v jq >/dev/null 2>&1 || die "jq required but not found"
TTYD_BIN="$(command -v ttyd || true)"; [ -n "$TTYD_BIN" ] || die "ttyd not found (brew install ttyd)"
TMUX_BIN="$(command -v tmux || true)"; [ -n "$TMUX_BIN" ] || die "tmux not found (brew install tmux)"
# P1-4 (codex #12118): never install a stale/blind committed manifest. Regenerate
# from live sources + --strict FIRST, so the substrate reflects the real registry +
# Terminal profiles at install time and fails loud on any unresolved/conflicting
# seat. Skipped only when the caller pins an explicit manifest (COCKPIT_MANIFEST_SRC,
# e.g. tests) — then it is used verbatim.
if [ -z "${COCKPIT_MANIFEST_SRC:-}" ]; then
  GENERATOR="$SCRIPT_DIR/generate_cockpit_manifest.py"
  [ -f "$GENERATOR" ] || die "manifest generator missing at $GENERATOR"
  echo "regenerating manifest from live sources (--strict)..."
  python3 "$GENERATOR" --write --strict >/dev/null \
    || die "manifest --strict failed — resolve unresolved/conflicting seats at source (fix the zsh function markers, not a table) before install"
fi
[ -f "$MANIFEST_SRC" ] || die "manifest missing at $MANIFEST_SRC — run generate_cockpit_manifest.py --write"
[ -f "$FLEET_SRC" ]    || die "fleet_terminals.sh missing at $FLEET_SRC"
[ -f "$TEMPLATE" ]     || die "ttyd plist template missing at $TEMPLATE"

mkdir -p "$DEPLOY_DIR" "$LAUNCHD_DIR" "$LOG_DIR"

# 1. Deploy the substrate the controller reads (fleet launcher + manifest).
cp "$FLEET_SRC" "$FLEET_DEPLOY"; chmod 755 "$FLEET_DEPLOY"
cp "$MANIFEST_SRC" "$MANIFEST_DEPLOY"; chmod 644 "$MANIFEST_DEPLOY"

# 2. Credential is controller-owned — READ ONLY, never create (#12074).
if [ ! -f "$CREDENTIAL_PATH" ]; then
  die "credential $CREDENTIAL_PATH ABSENT — it is owned by the controller installer (#12074). Run install_cockpit_controller.sh (or coordinate with deputy-codex) first; this script never creates it."
fi
[ "$(stat -f '%Lp' "$CREDENTIAL_PATH")" = "600" ] || die "credential must be mode 0600: $CREDENTIAL_PATH"
CREDENTIAL="$(head -n1 "$CREDENTIAL_PATH")"
[ -n "$CREDENTIAL" ] || die "credential file is empty: $CREDENTIAL_PATH"

# 3. Which seats to install for (default = all manifest seats).
if [ "$#" -gt 0 ]; then
  SEATS=("$@")
else
  # stock macOS ships bash 3.2 (no mapfile) — while-read is 3.2-compatible (codex P1-2)
  SEATS=()
  while IFS= read -r _slug; do
    [ -n "$_slug" ] && SEATS+=("$_slug")
  done < <(jq -r '.entries[].slug' "$MANIFEST_SRC")
fi

installed=0
for slug in "${SEATS[@]}"; do
  entry="$(jq -c --arg s "$slug" '.entries[] | select(.slug==$s)' "$MANIFEST_SRC")"
  [ -n "$entry" ] || die "seat '$slug' not in manifest"
  port="$(printf '%s' "$entry" | jq -r '.port')"
  label="com.baker.cockpit-ttyd-$slug"
  installed_plist="$LAUNCHD_DIR/$label.plist"

  # base path the controller proxies this seat under (unstripped): /term/<slug>/
  base_path="/term/$slug/"
  TTYD_BIN="$TTYD_BIN" TMUX_BIN="$TMUX_BIN" python3 - \
    "$TEMPLATE" "$installed_plist" "$label" "$port" "$CREDENTIAL" "$slug" \
    "$LOG_DIR/ttyd-$slug.log" "$LOG_DIR/ttyd-$slug.error.log" "$base_path" <<'PY'
import os, sys, pathlib
tmpl, out, label, port, cred, slug, logp, errp, base = sys.argv[1:]
body = pathlib.Path(tmpl).read_text()
for k, v in {
    "__LABEL__": label, "__TTYD_BIN__": os.environ["TTYD_BIN"],
    "__TMUX_BIN__": os.environ["TMUX_BIN"], "__PORT__": port,
    "__CREDENTIAL__": cred, "__SLUG__": slug, "__BASE_PATH__": base,
    "__LOG_PATH__": logp, "__ERROR_LOG_PATH__": errp,
}.items():
    body = body.replace(k, v)
pathlib.Path(out).write_text(body)
PY
  chmod 600 "$installed_plist"   # protects the embedded Basic-auth credential

  if [ -n "${COCKPIT_TTYD_DRYRUN:-}" ]; then
    echo "dry-run: generated $installed_plist (port $port, seat $slug)"
  else
    launchctl unload "$installed_plist" 2>/dev/null || true
    launchctl load -w "$installed_plist"
    echo "loaded $label (127.0.0.1:$port -> tmux attach -t $slug)"
  fi
  installed=$((installed+1))
done

if [ -n "${COCKPIT_TTYD_DRYRUN:-}" ]; then verb="generated (dry-run: no launchctl mutation)"; else verb="installed"; fi
echo "cockpit ttyd substrate: deployed fleet+manifest to $DEPLOY_DIR; ${installed} ttyd plist(s) ${verb}."
echo "verify: launchctl list | grep com.baker.cockpit-ttyd ; lsof -nP -iTCP -sTCP:LISTEN | grep ttyd"
exit 0
