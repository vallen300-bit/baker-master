#!/usr/bin/env bash
# fleet_client_parity.sh — per-seat parity for fleet-distributed client scripts.
#
# Default mode checks the current checkout. --rollup checks explicit seat paths
# supplied by the dispatcher. The roll-up intentionally uses each seat's local
# git HEAD and working-tree contents; missing or unreadable seat telemetry is RED.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname -- "$0")" && pwd -P)"
if DEFAULT_REPO="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null)" \
  && [[ -n "$DEFAULT_REPO" ]]; then
  :
else
  DEFAULT_REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"
fi
REPO_ROOT="${FLEET_CLIENT_REPO:-$DEFAULT_REPO}"
MANIFEST="${FLEET_CLIENT_MANIFEST:-$REPO_ROOT/scripts/arm_fleet_manifest.json}"
DO_FETCH=1
CAPABILITY_PROBE=0
ROLLUP=0
SEATS=()

# shellcheck source=scripts/lib/parity.sh
. "${SCRIPT_DIR}/lib/parity.sh"

usage() {
  cat <<'EOF'
Usage:
  fleet_client_parity.sh [--no-fetch] [--capability-probe]
  fleet_client_parity.sh --rollup --seat NAME=REPO [--seat NAME=REPO ...]

The local check compares each manifest client script with origin/main. The
roll-up repeats that check for explicit seat repositories and returns RED for
missing or unreadable seats.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --no-fetch) DO_FETCH=0; shift ;;
    --capability-probe) CAPABILITY_PROBE=1; shift ;;
    --rollup) ROLLUP=1; shift ;;
    --seat)
      [[ "$#" -ge 2 ]] || { echo "ERROR: --seat requires NAME=REPO" >&2; exit 2; }
      SEATS+=("$2"); shift 2 ;;
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
  echo "RED manifest-missing $MANIFEST"
  exit 1
}

if [[ "$ROLLUP" -eq 1 ]]; then
  [[ "${#SEATS[@]}" -gt 0 ]] || {
    echo "RED rollup has no seat telemetry"
    exit 1
  }
  total_rc=0
  for seat in "${SEATS[@]}"; do
    name="${seat%%=*}"
    repo="${seat#*=}"
    if [[ "$seat" != *=* || -z "$name" || -z "$repo" || ! -d "$repo/.git" ]]; then
      echo "RED $name missing-or-unreachable-seat-repository=$repo"
      total_rc=1
      continue
    fi
    seat_manifest="$repo/scripts/arm_fleet_manifest.json"
    [[ -f "$seat_manifest" ]] || seat_manifest="$MANIFEST"
    echo "SEAT $name head=$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    child_args=()
    [[ "$DO_FETCH" -eq 0 ]] && child_args+=(--no-fetch)
    [[ "$CAPABILITY_PROBE" -eq 1 ]] && child_args+=(--capability-probe)
    if ! FLEET_CLIENT_REPO="$repo" FLEET_CLIENT_MANIFEST="$seat_manifest" \
      FLEET_CLIENT_SEAT_LABEL="$name" \
      bash "$0" "${child_args[@]}"; then
      total_rc=1
    fi
  done
  exit "$total_rc"
fi

if [[ "$DO_FETCH" -eq 1 && "${FLEET_CLIENT_SKIP_FETCH:-0}" != "1" ]]; then
  if ! git -C "$REPO_ROOT" fetch origin main --quiet 2>/dev/null; then
    echo "RED origin-fetch-failed repo=$REPO_ROOT"
    exit 1
  fi
fi

failed=0
seen=0

client_entry() {
  local path="$1"
  local marker="$2"
  local local_path="$REPO_ROOT/$path"
  local tracked=1
  local local_sha origin_sha
  local status detail prefix
  prefix="${FLEET_CLIENT_SEAT_LABEL:-}"

  seen=$((seen + 1))
  if [[ ! -f "$local_path" ]]; then
    if [[ -n "$prefix" ]]; then
      echo "RED $prefix $path missing-local-copy=$local_path"
    else
      echo "RED $path missing-local-copy=$local_path"
    fi
    failed=1
    return
  fi
  if ! git -C "$REPO_ROOT" ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    tracked=0
  fi
  if [[ "$tracked" -eq 0 ]] \
    || ! git -C "$REPO_ROOT" diff --quiet -- "$path" 2>/dev/null \
    || ! git -C "$REPO_ROOT" diff --cached --quiet -- "$path" 2>/dev/null; then
    if [[ -n "$prefix" ]]; then
      echo "UNTRACKED-MODIFIED $prefix $path"
    else
      echo "UNTRACKED-MODIFIED $path"
    fi
    failed=1
    return
  fi

  local_sha="$(_sha256 "$local_path" 2>/dev/null || true)"
  origin_sha="$(git -C "$REPO_ROOT" show "origin/main:$path" 2>/dev/null | _sha256_stream 2>/dev/null || true)"
  if [[ -z "$origin_sha" ]]; then
    if [[ -n "$prefix" ]]; then
      echo "RED $prefix $path missing-origin-canonical"
    else
      echo "RED $path missing-origin-canonical"
    fi
    failed=1
    return
  fi
  status="CLEAN"
  detail=""
  if [[ -z "$local_sha" || "$local_sha" != "$origin_sha" ]]; then
    status="STALE $path local=${local_sha:0:8} origin=${origin_sha:0:8}"
    failed=1
  fi

  if [[ "$CAPABILITY_PROBE" -eq 1 && -n "$marker" ]] \
    && ! grep -qF "$marker" "$local_path" 2>/dev/null; then
    if [[ "$marker" == *CLIENT_STARTED_EMISSION* ]]; then
      detail="missing the started-emit capability"
    else
      detail="missing capability marker ${marker}"
    fi
    if [[ "$status" == "CLEAN" ]]; then
      status="STALE $path"
    fi
    status="$status $detail"
    failed=1
  fi
  if [[ "$status" == "CLEAN" ]]; then
    if [[ -n "$prefix" ]]; then
      echo "CLEAN $prefix $path"
    else
      echo "CLEAN $path"
    fi
  else
    if [[ -n "$prefix" ]]; then
      echo "$prefix $status"
    else
      echo "$status"
    fi
  fi
}

while IFS=$'\t' read -r path marker; do
  [[ -n "$path" ]] || continue
  client_entry "$path" "$marker"
done < <(
  python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    manifest = json.load(fh)

for item in manifest.get("client_scripts", []):
    print(f"{item.get('path', '')}\t{item.get('capability_marker', '')}")
PY
)

if [[ "$seen" -eq 0 ]]; then
  echo "RED manifest contains no client_scripts: $MANIFEST"
  failed=1
fi
exit "$failed"
