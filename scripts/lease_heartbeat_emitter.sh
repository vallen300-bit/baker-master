#!/usr/bin/env bash
# lease_heartbeat_emitter.sh — CASE_ONE_P2_LIVENESS_LIFECYCLE_1 (P2.2).
#
# The STRUCTURAL heartbeat emitter. Runs per-seat from launchd
# (com.baker.lease-heartbeat-emitter) on a fixed cadence and POSTs
# /lease/{seat}/heartbeat to the brisen-lab daemon, renewing the seat's lease.
#
# WHY structural (not a prompt line): prompt-level self-monitoring decays within
# a live session — the deepest Case-One lesson. A liveness signal that depends on
# the model remembering to send it is not a liveness signal. This emitter is
# launchd-driven and KeepAlive-hardened, so:
#   - a live seat's lease stays fresh with ZERO model involvement;
#   - the emitter dying (a snapshot-pusher-class outage, E9/tonight) becomes
#     detectable — its seat's heartbeat goes stale and the lease reads
#     "assigned but dead" instead of the seat silently going dark.
#
# Tolerant: any transient failure logs + exits 0 so launchd does NOT back off
# (non-zero = crash → KeepAlive relaunch storm). Exits non-zero ONLY on invalid
# config (missing seat/key), which is a real install fault worth surfacing.
#
# Cadence is set at install time (plist StartInterval, from
# BRISEN_LAB_HEARTBEAT_CADENCE_S — rider b, config not a constant). The daemon
# ALSO advertises cadence_s in the heartbeat response; this script logs any drift
# so a stale install is visible.

set -u
set -o pipefail

LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/agent_identity_generated.sh
. "$SCRIPT_DIR/agent_identity_generated.sh"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

# --- resolve this seat's slug (BAKER_ROLE → canonical slug, same map as bus_post) ---
if ! SEAT="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
  echo "[lease-hb] FATAL: BAKER_ROLE unset or unrecognized: '${BAKER_ROLE:-}'" >&2
  exit 2
fi

# --- terminal key (env → ~/.brisen-lab/keys/<slug> cache → 1Password) ---
KEY="$(brisen_lab_read_terminal_key "$SEAT" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
if [ -z "$KEY" ]; then
  echo "[lease-hb] FATAL: terminal key empty for seat=${SEAT}" >&2
  exit 2
fi

# --- single-instance guard (mkdir-mutex, POSIX-atomic; stale-lock reclaim) ---
# Per-seat lock so two seats on one host never collide, and a respawned emitter
# does not stack on a still-running one. Mirrors forge_snapshot_push.sh.
LOCK_DIR="${LOCK_DIR:-/tmp/lease_heartbeat_emitter.${SEAT}.lock}"
acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then echo "$$" > "$LOCK_DIR/pid"; return 0; fi
  local owner=""
  [ -f "$LOCK_DIR/pid" ] && owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo '')"
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then return 1; fi
  rm -rf "$LOCK_DIR" 2>/dev/null
  if mkdir "$LOCK_DIR" 2>/dev/null; then echo "$$" > "$LOCK_DIR/pid"; return 0; fi
  return 1
}
if ! acquire_lock; then
  echo "[lease-hb] another emitter instance for ${SEAT} is running; exiting" >&2
  exit 0   # exit 0 so launchd does not treat this as a crash
fi
trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT

# --- emit one heartbeat (renew the lease) ---
RESP_FILE="$(mktemp -t lease_hb.XXXXXX)"
trap 'rm -rf "$LOCK_DIR" 2>/dev/null; rm -f "$RESP_FILE" 2>/dev/null' EXIT

HTTP="$(curl -sS --connect-timeout 5 --max-time 15 \
    -o "$RESP_FILE" -w '%{http_code}' \
    -X POST "${LAB_URL}/lease/${SEAT}/heartbeat" \
    -H "X-Terminal-Key: ${KEY}" 2>/dev/null)" || HTTP="000"

case "$HTTP" in
  200)
    # Renewed. Log the daemon-advertised cadence so a stale plist StartInterval
    # (rider-b config drift) is visible in the log without failing the emit.
    cadence="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("cadence_s",""))' "$RESP_FILE" 2>/dev/null || echo '')"
    echo "[lease-hb] ${SEAT} renewed (daemon cadence_s=${cadence})"
    ;;
  404)
    # No active lease: the seat holds no dispatch right now. NOT an error — an
    # idle seat has nothing to renew (idle ≠ dead). Log + exit clean.
    echo "[lease-hb] ${SEAT} idle (no active lease to renew)"
    ;;
  000)
    echo "[lease-hb] ${SEAT} daemon unreachable (network/timeout); will retry next cadence" >&2
    ;;
  *)
    echo "[lease-hb] ${SEAT} heartbeat HTTP ${HTTP}: $(cat "$RESP_FILE" 2>/dev/null)" >&2
    ;;
esac

exit 0   # always 0 on a completed run — tolerance; launchd keeps the cadence
