#!/usr/bin/env bash
# arm_cadence_poll.sh — ARM_CADENCE_LAUNCHD_JOB_1 (charter D2 + §4).
#
# The ARM custodian's MACHINE cadence. Runs from launchd
# (com.baker.arm-cadence) every 30 min and captures a bus-health telemetry
# SNAPSHOT that ARM's report-synthesis session reads at wake. curl-only, ZERO
# LLM tokens per poll (charter §5: polling = curl/SQL, zero model cost).
#
# WHY structural (not a prompt line): "remember to check the bus" decays inside
# a live session — the deepest Case-One lesson (prompt-rule-decay; charter §4).
# A watchdog that depends on the model remembering to run is not a watchdog.
# This poller is launchd-driven and KeepAlive-hardened, so the fleet's comms
# telemetry is captured with ZERO model involvement, and ARM only spends tokens
# on report synthesis + alarm wording (charter D2).
#
# WHAT it captures (v0): GET /api/bus_health — the JSON MACHINE surface
# (charter [F1]: /api/bus_health = machine, /bus-health = human HTML). It
# already aggregates per-seat unacked + oldest-unacked age, latency percentiles,
# integrity counters, and delivery SLA. The `arm_sql` lease/heartbeat/wake_events/
# envelope telemetry is added here as CASE_ONE P1–P4 tables land (charter §1
# "table allow-list updated at each ship, introspected against LIVE schema —
# never guessed"); the SOURCES array below is the single extension point.
#
# WHERE it writes: ~/.brisen-lab/arm-cadence/ (TCC-safe, same neighbourhood as
# forge-drift.log). latest.json is the pointer ARM synthesis reads; timestamped
# history files back the D3 overnight-anomalies digest. Writes are atomic
# (temp + mv) so a reader never sees a half-written snapshot.
#
# TOLERANCE: any transient failure logs + exits 0 so launchd does NOT back off
# (non-zero exit → KeepAlive relaunch storm, collapsing the 30-min cadence into a
# hot-loop). Snapshot FRESHNESS is the health signal (checked by
# arm_cadence_drift_check.sh), never this script's exit code. There is no config
# fault path that exits non-zero: the poller has no required secret (the machine
# surface is public, verified 2026-07-13 http=200 unauth).

set -u
set -o pipefail

POLLER_VERSION="1"
LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
SNAP_DIR="${ARM_CADENCE_SNAPSHOT_DIR:-$HOME/.brisen-lab/arm-cadence}"
LOG="${ARM_CADENCE_LOG:-$HOME/.brisen-lab/arm-cadence.log}"
# How many timestamped history snapshots to retain (default 96 = 2 days @ 30 min).
RETAIN="${ARM_CADENCE_RETAIN:-96}"
TS="$(date -u +%FT%TZ)"
TS_FILE="$(date -u +%Y%m%dT%H%M%SZ)"
HOST="$(hostname 2>/dev/null || echo unknown)"

# SOURCES: machine telemetry endpoints captured each poll. Extension point for
# the arm_sql lease/wake/envelope surfaces as P1–P4 land — add "<key> <path>"
# rows; the loop below captures each into the snapshot under its key. Each MUST
# be a read-only, non-secret GET (curl/SQL-level, zero LLM — charter D2).
SOURCES=(
  "bus_health /api/bus_health"
)

mkdir -p "$SNAP_DIR" 2>/dev/null || true
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

log_line() { printf '%s arm-cadence %s %s\n' "$TS" "$HOST" "$*" >> "$LOG" 2>/dev/null || true; }

# --- single-instance guard (mkdir-mutex, POSIX-atomic; stale-lock reclaim) ---
# A slow poll must not stack on a still-running one (a 30-min cadence with a
# hung curl could otherwise pile up). Mirrors lease_heartbeat_emitter.sh.
LOCK_DIR="${ARM_CADENCE_LOCK:-/tmp/arm_cadence_poll.lock}"
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
  log_line "SKIP another poll already running"
  exit 0
fi

TMP_BODY="$(mktemp -t arm_cadence_body.XXXXXX)"
TMP_SNAP="$(mktemp -t arm_cadence_snap.XXXXXX)"
trap 'rm -rf "$LOCK_DIR" 2>/dev/null; rm -f "$TMP_BODY" "$TMP_SNAP" 2>/dev/null' EXIT

# --- capture each source into a per-key JSON fragment -----------------------
# Build a JSON object: {captured_at, host, source_url, poller_version, ok,
# sources: {<key>: {http, ok, data|error}}}. Python does the assembly so the
# raw endpoint JSON is embedded structurally (not string-spliced).
FRAGMENTS=()   # "key<TAB>http<TAB>bodyfile"
OVERALL_OK=1
for entry in "${SOURCES[@]}"; do
  key="${entry%% *}"; path="${entry#* }"
  : > "$TMP_BODY"
  http="$(curl -sS --connect-timeout 5 --max-time 25 \
      -o "$TMP_BODY" -w '%{http_code}' \
      "${LAB_URL}${path}" 2>/dev/null)" || http="000"
  bf="$(mktemp -t arm_cadence_frag.XXXXXX)"
  cp "$TMP_BODY" "$bf" 2>/dev/null || : > "$bf"
  FRAGMENTS+=("${key}"$'\t'"${http}"$'\t'"${bf}")
  if [ "$http" != "200" ]; then OVERALL_OK=0; fi
done

# --- assemble the snapshot atomically ---------------------------------------
if ARM_TS="$TS" ARM_HOST="$HOST" ARM_URL="$LAB_URL" ARM_VER="$POLLER_VERSION" \
   ARM_OK="$OVERALL_OK" python3 -c '
import json, os, sys
ts, host, url, ver, ok = (os.environ["ARM_TS"], os.environ["ARM_HOST"],
                          os.environ["ARM_URL"], os.environ["ARM_VER"],
                          os.environ["ARM_OK"] == "1")
sources = {}
# argv: key http bodyfile  key http bodyfile ...
args = sys.argv[1:]
for i in range(0, len(args), 3):
    key, http, bf = args[i], args[i+1], args[i+2]
    entry = {"http": http, "ok": http == "200"}
    try:
        with open(bf) as fh:
            raw = fh.read()
        entry["data"] = json.loads(raw) if raw.strip() else None
        if entry["data"] is None and http == "200":
            entry["ok"] = False
            entry["error"] = "empty body"
    except Exception as exc:  # non-JSON / parse failure — record, do not crash
        entry["ok"] = False
        entry["error"] = "unparseable: %s" % (exc,)
    if not entry.get("ok"):
        ok = False
    sources[key] = entry
snap = {
    "captured_at": ts,
    "host": host,
    "source_url": url,
    "poller_version": int(ver),
    "ok": ok,
    "sources": sources,
}
json.dump(snap, sys.stdout, indent=2, sort_keys=True)
' $(for f in "${FRAGMENTS[@]}"; do printf '%s\t' "$f"; done | tr '\t' '\n' | sed '/^$/d' | tr '\n' ' ') > "$TMP_SNAP" 2>/dev/null
then
  mv -f "$TMP_SNAP" "${SNAP_DIR}/${TS_FILE}.json" 2>/dev/null
  # latest.json = atomic copy (mv within same dir) so ARM never reads a partial.
  cp "${SNAP_DIR}/${TS_FILE}.json" "${SNAP_DIR}/.latest.tmp" 2>/dev/null \
    && mv -f "${SNAP_DIR}/.latest.tmp" "${SNAP_DIR}/latest.json" 2>/dev/null
  if [ "$OVERALL_OK" = "1" ]; then
    log_line "OK snapshot ${TS_FILE}.json (sources=${#SOURCES[@]})"
  else
    log_line "DEGRADED snapshot ${TS_FILE}.json (a source returned non-200/unparseable)"
  fi
else
  log_line "ERROR snapshot assembly failed (${TS_FILE})"
fi

# clean up fragment temp files
for entry in "${FRAGMENTS[@]}"; do
  bf="${entry##*$'\t'}"; rm -f "$bf" 2>/dev/null
done

# --- prune history beyond RETAIN (keep latest.json always) ------------------
if [[ "$RETAIN" =~ ^[0-9]+$ ]] && [ "$RETAIN" -gt 0 ]; then
  # shellcheck disable=SC2012 — filenames are ISO-8601, ls sorts chronologically.
  ls -1t "${SNAP_DIR}"/*.json 2>/dev/null | grep -v '/latest\.json$' \
    | tail -n +"$((RETAIN + 1))" | while read -r old; do rm -f "$old" 2>/dev/null; done
fi

exit 0   # always 0 on a completed run — tolerance; launchd keeps the cadence
