#!/usr/bin/env bash
# Regression test for install_cockpit_ttyd.sh — per-seat ttyd credentials
# (COCKPIT_BRIDGE_HARDENING_2 D4, AC4).
#
# Guards:
#   1. Two seats get DISTINCT ttyd credentials in $DEPLOY_DIR/credentials.d/<slug>
#      (mode 0600), and each seat's generated plist embeds its OWN credential.
#   2. A plain reinstall does NOT rotate an existing per-seat cred (stable).
#   3. COCKPIT_TTYD_ROTATE=<slug> rotates ONLY that seat; the other is untouched.
#
# Method: dry-run (COCKPIT_TTYD_DRYRUN=1, no launchctl). Stub ttyd/tmux on PATH;
# jq + openssl are real. Manifest is pinned (COCKPIT_MANIFEST_SRC) so no live
# registry regeneration. Never touches launchd/network.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/install_cockpit_ttyd.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- stub ttyd + tmux on PATH (the installer requires both present) ---
BIN="$WORK/bin"; mkdir -p "$BIN"
for t in ttyd tmux; do printf '#!/bin/sh\nexit 0\n' > "$BIN/$t"; chmod +x "$BIN/$t"; done
export PATH="$BIN:$PATH"

# --- fake deploy layout ---
DEPLOY="$WORK/deploy"; LAUNCHD="$WORK/launchagents"; LOGS="$WORK/logs"
mkdir -p "$DEPLOY" "$LAUNCHD" "$LOGS"
# shared controller credential (0600) — required + read-only to the installer
printf 'shared-controller:secret\n' > "$DEPLOY/credentials"; chmod 600 "$DEPLOY/credentials"

# pinned 2-seat manifest
MANIFEST="$WORK/manifest.json"
cat > "$MANIFEST" <<'JSON'
{"entries":[{"slug":"b1","port":8801},{"slug":"b2","port":8802}]}
JSON

run_install() {
  # Extra "VAR=val" args (e.g. COCKPIT_TTYD_ROTATE=b1) are passed via env so the
  # assignment prefix is honored rather than run as a command.
  env \
    COCKPIT_TTYD_DRYRUN=1 \
    COCKPIT_MANIFEST_SRC="$MANIFEST" \
    COCKPIT_DEPLOY_DIR="$DEPLOY" \
    COCKPIT_LAUNCHD_DIR="$LAUNCHD" \
    COCKPIT_LOG_DIR="$LOGS" \
    COCKPIT_CREDENTIAL_FILE="$DEPLOY/credentials" \
    "$@" \
    bash "$SCRIPT" >/dev/null
}

fail() { echo "FAIL: $*" >&2; exit 1; }

# --- install 1: generate per-seat creds ---
run_install
CRED_B1="$DEPLOY/credentials.d/b1"
CRED_B2="$DEPLOY/credentials.d/b2"
[ -f "$CRED_B1" ] && [ -f "$CRED_B2" ] || fail "per-seat cred files not created"
[ "$(stat -f '%Lp' "$CRED_B1")" = "600" ] || fail "b1 cred not 0600"
[ "$(stat -f '%Lp' "$CRED_B2")" = "600" ] || fail "b2 cred not 0600"

B1_V1="$(cat "$CRED_B1")"; B2_V1="$(cat "$CRED_B2")"
[ "$B1_V1" != "$B2_V1" ] || fail "seats share the same credential (AC4 violation)"
[ "$B1_V1" != "shared-controller:secret" ] || fail "b1 embedded the SHARED cred, not a per-seat one"

# each plist embeds its OWN seat credential, not the other's, not the shared one
grep -q "$B1_V1" "$LAUNCHD/com.baker.cockpit-ttyd-b1.plist" || fail "b1 plist missing its own cred"
grep -q "$B2_V1" "$LAUNCHD/com.baker.cockpit-ttyd-b2.plist" || fail "b2 plist missing its own cred"
grep -q "$B2_V1" "$LAUNCHD/com.baker.cockpit-ttyd-b1.plist" && fail "b1 plist leaked b2's cred"
grep -q "shared-controller:secret" "$LAUNCHD/com.baker.cockpit-ttyd-b1.plist" && fail "b1 plist embedded the shared cred"

# --- install 2: plain reinstall is STABLE (no silent rotation) ---
run_install
[ "$(cat "$CRED_B1")" = "$B1_V1" ] || fail "reinstall rotated b1 (should be stable)"
[ "$(cat "$CRED_B2")" = "$B2_V1" ] || fail "reinstall rotated b2 (should be stable)"

# --- install 3: rotate ONLY b1 — b2 untouched (AC4 atomic rotation) ---
run_install COCKPIT_TTYD_ROTATE=b1
[ "$(cat "$CRED_B1")" != "$B1_V1" ] || fail "COCKPIT_TTYD_ROTATE=b1 did not rotate b1"
[ "$(cat "$CRED_B2")" = "$B2_V1" ] || fail "rotating b1 also changed b2 (AC4 isolation violation)"

# --- legacy opt-out: shared cred in every plist ---
rm -rf "$DEPLOY/credentials.d" "$LAUNCHD"/*.plist
run_install COCKPIT_TTYD_PER_SEAT_CREDS=0
grep -q "shared-controller:secret" "$LAUNCHD/com.baker.cockpit-ttyd-b1.plist" || fail "legacy mode did not embed shared cred"
[ ! -d "$DEPLOY/credentials.d" ] || fail "legacy mode should not create per-seat store"

echo "PASS: per-seat ttyd credentials distinct, stable on reinstall, atomically rotatable, legacy opt-out works"
