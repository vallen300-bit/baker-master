#!/usr/bin/env bash
# install_forge_drift_cron.sh — install the daily forge-agent drift-check launchd
# job on a host (#5641 task 2). Idempotent.
#
# Deploys a SELF-CONTAINED check bundle to a TCC-safe location (launchd can read
# ~/Library/Application Support/baker/, unlike a repo under ~/Desktop), so the
# daily job runs even where the git checkout is TCC-blocked. The bundle preserves
# install_forge_agent.sh's relative layout (scripts/forge-agent + tests/fixtures).
#
# Bundle layout ($BUNDLE_ROOT default ~/Library/Application Support/baker/forge-check):
#   forge_drift_check.sh              # the wrapper the launchd job runs
#   scripts/install_forge_agent.sh    # --check tool
#   scripts/forge-agent/*.sh          # canonical forge scripts (drift reference)
#   tests/fixtures/*.sh               # canonical bus hooks (drift reference)
#
# Re-run this whenever the canonical forge scripts change (it refreshes the
# bundle's reference copies). The daily wrapper compares DEPLOYED host files
# (~/forge-agent, ~/.claude) against this bundle's canonical copies.
#
# CONTRACT: fail loud on missing sources; never partially load the plist.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="com.brisen.forge-drift-check"
TEMPLATE="${REPO_ROOT}/launchd/${LABEL}.plist"

BUNDLE_ROOT="${FORGE_DRIFT_BUNDLE_DIR:-$HOME/Library/Application Support/baker/forge-check}"
LOGDIR="${FORGE_DRIFT_LOGDIR:-$HOME/Library/Logs}"
INSTALLED_PLIST="${FORGE_DRIFT_PLIST_DIR:-$HOME/Library/LaunchAgents}/${LABEL}.plist"

# Sources that must exist in the checkout.
SRC_INSTALLER="${SCRIPT_DIR}/install_forge_agent.sh"
SRC_WRAPPER="${SCRIPT_DIR}/forge_drift_check.sh"
SRC_FORGE_DIR="${SCRIPT_DIR}/forge-agent"
SRC_FIXTURES_DIR="${REPO_ROOT}/tests/fixtures"
for f in "$SRC_INSTALLER" "$SRC_WRAPPER" "$TEMPLATE"; do
  [[ -f "$f" ]] || { echo "FATAL: missing source $f" >&2; exit 2; }
done

# 1. Deploy the bundle.
mkdir -p "${BUNDLE_ROOT}/scripts/forge-agent" "${BUNDLE_ROOT}/tests/fixtures" "$LOGDIR"
cp "$SRC_INSTALLER" "${BUNDLE_ROOT}/scripts/install_forge_agent.sh"
cp "$SRC_WRAPPER"   "${BUNDLE_ROOT}/forge_drift_check.sh"
cp "${SRC_FORGE_DIR}"/*.sh "${BUNDLE_ROOT}/scripts/forge-agent/"
cp "${SRC_FIXTURES_DIR}/session-start-bus-drain.sh" \
   "${SRC_FIXTURES_DIR}/turn-bus-drain.sh" \
   "${SRC_FIXTURES_DIR}/stop-bus-ack.sh" \
   "${BUNDLE_ROOT}/tests/fixtures/"
chmod +x "${BUNDLE_ROOT}/forge_drift_check.sh" "${BUNDLE_ROOT}/scripts/install_forge_agent.sh" \
         "${BUNDLE_ROOT}/scripts/forge-agent/"*.sh "${BUNDLE_ROOT}/tests/fixtures/"*.sh
echo "  deployed check bundle -> $BUNDLE_ROOT"

# 2. Render the plist (str.replace — path content is arbitrary-safe).
RENDERED_PLIST="$(TEMPLATE="$TEMPLATE" WRAPPER="${BUNDLE_ROOT}/forge_drift_check.sh" \
  BUNDLE="${BUNDLE_ROOT}/scripts" LOGDIR="$LOGDIR" python3 -c '
import os
t = open(os.environ["TEMPLATE"]).read()
t = t.replace("__WRAPPER__", os.environ["WRAPPER"])
t = t.replace("__BUNDLE__",  os.environ["BUNDLE"])
t = t.replace("__LOGDIR__",  os.environ["LOGDIR"])
print(t)')"

# Dry-run (tests): write bundle + rendered plist to a temp, skip launchctl.
if [[ -n "${FORGE_DRIFT_DRYRUN:-}" ]]; then
  printf '%s' "$RENDERED_PLIST" > "${BUNDLE_ROOT}/.rendered.plist"
  echo "  dry-run: rendered plist -> ${BUNDLE_ROOT}/.rendered.plist (skipped launchctl)"
  exit 0
fi

mkdir -p "$(dirname "$INSTALLED_PLIST")"
printf '%s' "$RENDERED_PLIST" > "$INSTALLED_PLIST"
echo "  wrote $INSTALLED_PLIST"

# 3. Reload the job (unload any prior, then load -w to persist).
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
launchctl load -w "$INSTALLED_PLIST"
echo "  loaded $LABEL (daily 08:15 local)"
echo "install complete. Run once now: FORGE_CHECK_DIR=\"${BUNDLE_ROOT}/scripts\" bash \"${BUNDLE_ROOT}/forge_drift_check.sh\"; tail ~/.brisen-lab/forge-drift.log"
