#!/bin/bash
# install_kbl_mac_mini.sh — one-time KBL Mac Mini installer.
# Per briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md §6.
# Idempotent: safe to re-run after code updates (symlinks refresh,
# LaunchAgents reload).
#
# Usage:
#   ./scripts/install_kbl_mac_mini.sh
#
# Env overrides:
#   KBL_REPO   — path to baker-master clone (default: ~/Desktop/baker-code)
#   KBL_VAULT  — path to baker-vault clone  (default: ~/baker-vault)

set -euo pipefail

REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
VAULT="${KBL_VAULT:-${HOME}/baker-vault}"
TARGET_BIN="/usr/local/bin"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"

# --- Sanity checks ---
[ -d "${REPO}" ] || { echo "FAIL: ${REPO} not found. Set KBL_REPO or clone baker-master there."; exit 1; }
[ -d "${VAULT}" ] || { echo "FAIL: ${VAULT} not found. Clone baker-vault."; exit 1; }

command -v yq >/dev/null 2>&1 || { echo "FAIL: yq not installed. Run: brew install yq"; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "FAIL: flock not installed. Run: brew install util-linux"; exit 1; }
command -v ollama >/dev/null 2>&1 || { echo "FAIL: ollama not installed."; exit 1; }

ollama list | grep -q 'gemma4' || { echo "FAIL: gemma4 not pulled. Run: ollama pull gemma4:latest"; exit 1; }
ollama list | grep -q 'qwen2.5:14b' || { echo "FAIL: qwen2.5:14b not pulled. Run: ollama pull qwen2.5:14b"; exit 1; }

# R1.N3: enforce ~/.zshrc mode 0600 (defense for plaintext secrets per D4 override).
if [ -f "${HOME}/.zshrc" ]; then
    chmod 600 "${HOME}/.zshrc" 2>/dev/null && echo "OK: ~/.zshrc mode 0600 enforced" || echo "WARN: chmod 600 ~/.zshrc failed"
fi

# R1.M3: warn (not fail) if env.mac-mini.yml not yet in vault —
# Director may not have pushed yet; pipeline wrapper also guards this.
if [ ! -f "${VAULT}/config/env.mac-mini.yml" ]; then
    echo "WARN: ${VAULT}/config/env.mac-mini.yml not present yet."
    echo "      Install continues; pipeline will idle until Director pushes the yml file."
fi

# --- 1. Symlink pipeline scripts ---
for script in kbl-pipeline-tick.sh kbl-gold-drain.sh kbl-heartbeat.sh kbl-dropbox-mirror.sh kbl-purge-dedupe.sh; do
    [ -f "${REPO}/scripts/${script}" ] || { echo "FAIL: ${REPO}/scripts/${script} missing"; exit 1; }
    sudo ln -sf "${REPO}/scripts/${script}" "${TARGET_BIN}/${script}"
    sudo chmod +x "${REPO}/scripts/${script}"
done

# --- 2. Install LaunchAgent plists ---
mkdir -p "${LAUNCHD_DIR}"
for plist in com.brisen.kbl.pipeline com.brisen.kbl.heartbeat com.brisen.kbl.dropbox-mirror com.brisen.kbl.purge-dedupe; do
    [ -f "${REPO}/launchd/${plist}.plist" ] || { echo "FAIL: ${REPO}/launchd/${plist}.plist missing"; exit 1; }
    cp "${REPO}/launchd/${plist}.plist" "${LAUNCHD_DIR}/${plist}.plist"
    launchctl unload "${LAUNCHD_DIR}/${plist}.plist" 2>/dev/null || true
    launchctl load "${LAUNCHD_DIR}/${plist}.plist"
done

# --- 3. Create log dir (requires sudo) ---
if [ ! -d "/var/log/kbl" ]; then
    echo "Creating /var/log/kbl (requires sudo)..."
    sudo mkdir -p /var/log/kbl
    sudo chown "${USER}:staff" /var/log/kbl
    sudo chmod 755 /var/log/kbl
fi

if [ ! -f "/etc/newsyslog.d/kbl.conf" ]; then
    echo "Installing /etc/newsyslog.d/kbl.conf (requires sudo)..."
    sudo cp "${REPO}/config/newsyslog-kbl.conf" /etc/newsyslog.d/kbl.conf
    sudo chmod 644 /etc/newsyslog.d/kbl.conf
fi

# --- 4. Dropbox mirror dir ---
DROPBOX_DIR="${HOME}/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs"
[ -d "${DROPBOX_DIR}" ] || mkdir -p "${DROPBOX_DIR}"

# --- 5. Validate ---
echo ""
echo "=== KBL Mac Mini install complete ==="
echo "Scripts in ${TARGET_BIN}:"
ls -la "${TARGET_BIN}"/kbl-* 2>/dev/null || echo "  (none symlinked)"
echo "LaunchAgents loaded:"
launchctl list | grep brisen.kbl || echo "  (none loaded)"
echo "Log dir:"
ls -la /var/log/kbl
echo ""
echo "Next: verify env.mac-mini.yml exists at ${VAULT}/config/env.mac-mini.yml"
echo "Then trigger first pipeline tick: launchctl start com.brisen.kbl.pipeline"
