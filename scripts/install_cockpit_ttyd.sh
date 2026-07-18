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
# Credentials:
#   * SHARED controller credential ($DEPLOY_DIR/credentials) is OWNED by the
#     controller installer (#12074) — READ ONLY here, never written/created. It
#     still authenticates the controller's single HTTP API.
#   * PER-SEAT ttyd credentials (COCKPIT_BRIDGE_HARDENING_2 D4) live in
#     $DEPLOY_DIR/credentials.d/<slug> (mode 0600) and are what each seat's ttyd
#     plist embeds — so a leak of one seat's plist/cred no longer exposes every
#     seat. This script GENERATES a per-seat cred (random) on first install for a
#     seat and REUSES it thereafter. The agent injects credentials.d/<slug> when
#     dialing /term/<slug>/ (resolve_ttyd_cred_path), falling back to the shared
#     cred during rollout. Per-seat creds are a NEW namespace — they do not touch
#     the controller-owned shared file.
#
# Atomic per-seat rotation (D4): to rotate ONE seat without touching others —
#     rm "$DEPLOY_DIR/credentials.d/<slug>" && install_cockpit_ttyd.sh <slug>
#   (or COCKPIT_TTYD_ROTATE=<slug> install_cockpit_ttyd.sh <slug>). Only that
#   seat's cred + plist change; every other seat's ttyd keeps its own credential.
#
# Usage:
#   install_cockpit_ttyd.sh [slug ...]     # no args = all manifest seats; else only the named seats
# Env:
#   COCKPIT_TTYD_DRYRUN=1        deploy files only; skip launchctl + plist mutation (tests/pilot staging)
#   COCKPIT_TTYD_PER_SEAT_CREDS=0  legacy: embed the shared credential in every plist (pre-D4 behavior)
#   COCKPIT_TTYD_ROTATE=<slug>   force-regenerate the per-seat cred for <slug> this run

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

# 2. Shared controller credential is controller-owned — READ ONLY, never create
#    (#12074). Still required: the agent's HTTP-proxy path authenticates the
#    controller's single HTTP API with it. Per-seat ttyd creds (D4) are separate.
if [ ! -f "$CREDENTIAL_PATH" ]; then
  die "credential $CREDENTIAL_PATH ABSENT — it is owned by the controller installer (#12074). Run install_cockpit_controller.sh (or coordinate with deputy-codex) first; this script never creates it."
fi
[ "$(stat -f '%Lp' "$CREDENTIAL_PATH")" = "600" ] || die "credential must be mode 0600: $CREDENTIAL_PATH"
SHARED_CREDENTIAL="$(head -n1 "$CREDENTIAL_PATH")"
[ -n "$SHARED_CREDENTIAL" ] || die "credential file is empty: $CREDENTIAL_PATH"

# Per-seat ttyd credential store (D4). New namespace beside the shared file; the
# controller-owned $CREDENTIAL_PATH is never touched.
PER_SEAT_CREDS="${COCKPIT_TTYD_PER_SEAT_CREDS:-1}"
CREDENTIALS_D="$DEPLOY_DIR/credentials.d"
if [ "$PER_SEAT_CREDS" != "0" ]; then
  mkdir -p "$CREDENTIALS_D"; chmod 700 "$CREDENTIALS_D"
fi

# Resolve (or generate on first use / on rotation) the per-seat ttyd credential
# for a slug, echo `user:pass`. Reused across installs so a plain reinstall does
# NOT rotate. Random 24-byte password; username namespaced per seat.
seat_credential() {
  local slug="$1" f="$CREDENTIALS_D/$slug" cred pw tmp rotate=0
  if [ "$PER_SEAT_CREDS" = "0" ]; then
    printf '%s' "$SHARED_CREDENTIAL"; return 0
  fi
  # Rotation must be ATOMIC and non-destructive (codex #12968): never delete the
  # existing cred up-front — a mid-generation failure (openssl/mktemp/write) would
  # leave the seat with no cred while the plist still pins the OLD ttyd password,
  # so the agent silently falls back to the shared cred (violates AC4). Instead we
  # only SKIP the reuse branch below; the old file survives untouched until the
  # single atomic `mv` overwrites it once a fully-validated replacement exists.
  if [ "${COCKPIT_TTYD_ROTATE:-}" = "$slug" ]; then
    rotate=1
  fi
  if [ "$rotate" = "0" ] && [ -f "$f" ]; then
    [ "$(stat -f '%Lp' "$f")" = "600" ] || die "per-seat cred must be mode 0600: $f"
    cred="$(head -n1 "$f")"
    if [ -n "$cred" ]; then printf '%s' "$cred"; return 0; fi
  fi
  pw="$(openssl rand -hex 24 2>/dev/null)" || die "openssl required to generate per-seat cred"
  [ -n "$pw" ] || die "per-seat cred generation produced empty password for $slug"
  cred="cockpit-$slug:$pw"
  tmp="$(mktemp "$CREDENTIALS_D/.$slug.XXXXXX")" || die "mktemp failed for per-seat cred $slug"
  printf '%s\n' "$cred" > "$tmp"; chmod 600 "$tmp"; mv "$tmp" "$f"
  printf '%s' "$cred"
}

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
  seat_cred="$(seat_credential "$slug")"
  TTYD_BIN="$TTYD_BIN" TMUX_BIN="$TMUX_BIN" python3 - \
    "$TEMPLATE" "$installed_plist" "$label" "$port" "$seat_cred" "$slug" \
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
