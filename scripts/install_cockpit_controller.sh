#!/usr/bin/env bash
# Install the local cockpit controller and its launchd reboot owner.
set -euo pipefail

LABEL="com.baker.cockpit-controller"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="${COCKPIT_DEPLOY_DIR:-$HOME/Library/Application Support/baker/cockpit}"
LAUNCHD_DIR="${COCKPIT_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
MANIFEST_PATH="${COCKPIT_MANIFEST_FILE:-$DEPLOY_DIR/launch_manifest.json}"
CREDENTIAL_PATH="${COCKPIT_CREDENTIAL_FILE:-$DEPLOY_DIR/credentials}"
STATIC_DIR="${COCKPIT_STATIC_DIR:-$DEPLOY_DIR/static}"
FLEET_SCRIPT="${COCKPIT_FLEET_SCRIPT:-$DEPLOY_DIR/fleet_terminals.sh}"
PORT="${COCKPIT_PORT:-7800}"

CONTROLLER_SRC="$SCRIPT_DIR/cockpit_controller.py"
LAUNCHER_SRC="$SCRIPT_DIR/cockpit_controller_launch.sh"
TEMPLATE="$SCRIPT_DIR/launchd/$LABEL.plist"
CONTROLLER_DEPLOY="$DEPLOY_DIR/cockpit_controller.py"
LAUNCHER_DEPLOY="$DEPLOY_DIR/cockpit_controller_launch.sh"
INSTALLED_PLIST="$LAUNCHD_DIR/$LABEL.plist"
LOG_DIR="${COCKPIT_LOG_DIR:-$HOME/Library/Logs/baker/cockpit}"

for required in "$CONTROLLER_SRC" "$LAUNCHER_SRC" "$TEMPLATE"; do
  [[ -f "$required" ]] || {
    echo "FATAL: required source missing: $required" >&2
    exit 2
  }
done
[[ -f "$CREDENTIAL_PATH" ]] || {
  echo "FATAL: credential file missing: $CREDENTIAL_PATH" >&2
  echo "Create username:password with mode 0600 before installing." >&2
  exit 2
}
[[ "$(stat -f '%Lp' "$CREDENTIAL_PATH")" == "600" ]] || {
  echo "FATAL: credential file must be mode 0600: $CREDENTIAL_PATH" >&2
  exit 2
}
[[ -x "$FLEET_SCRIPT" ]] || {
  echo "FATAL: fleet launcher missing or not executable: $FLEET_SCRIPT" >&2
  exit 2
}
[[ -f "$MANIFEST_PATH" ]] || {
  echo "FATAL: launch manifest missing: $MANIFEST_PATH" >&2
  exit 2
}

mkdir -p "$DEPLOY_DIR" "$LAUNCHD_DIR" "$STATIC_DIR" "$LOG_DIR"
cp "$CONTROLLER_SRC" "$CONTROLLER_DEPLOY"
cp "$LAUNCHER_SRC" "$LAUNCHER_DEPLOY"
chmod 700 "$CONTROLLER_DEPLOY" "$LAUNCHER_DEPLOY"

python3 - "$TEMPLATE" "$INSTALLED_PLIST" \
  "$LAUNCHER_DEPLOY" "$DEPLOY_DIR" "$CONTROLLER_DEPLOY" "$FLEET_SCRIPT" \
  "$MANIFEST_PATH" "$CREDENTIAL_PATH" "$STATIC_DIR" "$PORT" "$LOG_DIR" <<'PY'
import pathlib
import sys

(
    template_path,
    output_path,
    launcher_path,
    deploy_dir,
    controller_path,
    fleet_script,
    manifest_path,
    credential_path,
    static_dir,
    port,
    log_dir,
) = sys.argv[1:]
body = pathlib.Path(template_path).read_text(encoding="utf-8")
replacements = {
    "__LAUNCHER_PATH__": launcher_path,
    "__DEPLOY_DIR__": deploy_dir,
    "__CONTROLLER_PATH__": controller_path,
    "__FLEET_SCRIPT__": fleet_script,
    "__MANIFEST_PATH__": manifest_path,
    "__CREDENTIAL_PATH__": credential_path,
    "__STATIC_DIR__": static_dir,
    "__PORT__": port,
    "__LOG_PATH__": str(pathlib.Path(log_dir) / "controller.log"),
    "__ERROR_LOG_PATH__": str(pathlib.Path(log_dir) / "controller.error.log"),
}
for marker, value in replacements.items():
    body = body.replace(marker, value)
pathlib.Path(output_path).write_text(body, encoding="utf-8")
PY
chmod 600 "$INSTALLED_PLIST"

# Dry-run path for validation and packaging checks. No launchd mutation occurs.
if [[ -n "${COCKPIT_INSTALL_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed controller + launcher to $DEPLOY_DIR."
  echo "  Plist: $INSTALLED_PLIST"
  exit 0
fi

launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
launchctl load -w "$INSTALLED_PLIST"

echo "Installed $LABEL"
echo "  Plist:      $INSTALLED_PLIST"
echo "  Controller: $CONTROLLER_DEPLOY"
echo "  Manifest:   $MANIFEST_PATH"
echo "  URL:        http://127.0.0.1:$PORT/"
