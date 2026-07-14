#!/usr/bin/env bash
# arm_fleet_parity.sh — read-only parity sweep for the ARM launchd fleet.
#
# The manifest is the expected fleet. A listed job that is absent, unloaded, or
# otherwise unhealthy is RED; it is never silently skipped.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname -- "$0")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
MANIFEST="${ARM_FLEET_MANIFEST:-${SCRIPT_DIR}/arm_fleet_manifest.json}"

usage() {
  cat <<'EOF'
Usage: arm_fleet_parity.sh [--manifest PATH]

Read-only sweep of the host-side jobs in arm_fleet_manifest.json.
Exit status is non-zero when any expected job is missing or drifted.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --manifest)
      [[ "$#" -ge 2 ]] || { echo "ERROR: --manifest requires a path" >&2; exit 2; }
      MANIFEST="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

[[ -f "$MANIFEST" ]] || {
  echo "RED fleet manifest missing: $MANIFEST"
  exit 1
}

failed=0
seen=0

while IFS=$'\t' read -r job_label installer worker_src expected_interval host_role; do
  [[ -n "$job_label" ]] || continue
  seen=$((seen + 1))
  installer_path="$REPO_ROOT/$installer"
  if [[ ! -f "$installer_path" ]]; then
    echo "RED $job_label NOT-INSTALLED installer-missing=$installer"
    failed=1
    continue
  fi
  if [[ ! -f "$REPO_ROOT/$worker_src" ]]; then
    echo "RED $job_label NOT-INSTALLED worker-source-missing=$worker_src"
    failed=1
    continue
  fi

  out="$(bash "$installer_path" --check 2>&1)"
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "CLEAN $job_label interval=${expected_interval}s host_role=${host_role}"
    continue
  fi

  failures="$(printf '%s\n' "$out" \
    | grep -E '\[FAIL\]|RESULT: DRIFT' \
    | tr '\n' ';' | sed 's/;$//')"
  if printf '%s\n' "$out" | grep -qE '\[FAIL\] (worker not deployed|worker not executable|plist missing|launchd job .* not loaded)'; then
    echo "RED $job_label NOT-INSTALLED ${failures:-see-installer}"
  else
    echo "DRIFT $job_label ${failures:-see-installer}"
  fi
  failed=1
done < <(
  python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    manifest = json.load(fh)

for job in manifest.get("host_jobs", []):
    print("\t".join([
        str(job.get("job_label", "")),
        str(job.get("installer", "")),
        str(job.get("worker_src", "")),
        str(job.get("expected_interval_s", "")),
        str(job.get("host_role", "")),
    ]))
PY
)

if [[ "$seen" -eq 0 ]]; then
  echo "RED fleet manifest contains no host_jobs: $MANIFEST"
  exit 1
fi
exit "$failed"
