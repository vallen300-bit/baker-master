#!/usr/bin/env bash
# test_arm_cadence.sh — ARM_CADENCE_LAUNCHD_JOB_1 regression suite.
# Exercises the poller (snapshot write + tolerance), the installer (dry-run +
# --check drift), the drift sentinel (fail-open), and the structural invariants
# (crash-only KeepAlive, TCC-safe deploy dir, zero-secret plist). Hermetic: uses
# a local HTTP stub for the machine surface; no live brisen-lab, no launchctl.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POLLER="$ROOT/scripts/arm_cadence_poll.sh"
INSTALLER="$ROOT/scripts/install_arm_cadence_job.sh"
DRIFT="$ROOT/scripts/arm_cadence_drift_check.sh"
PLIST="$ROOT/scripts/launchd/com.baker.arm-cadence.plist"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

TMP="$(mktemp -d -t arm_cadence_test.XXXXXX)"
trap 'rm -rf "$TMP"; [ -n "${STUB_PID:-}" ] && kill "$STUB_PID" 2>/dev/null' EXIT

# --- 0. syntax probes (lost-exec/truncation guard, E23 blocker #2 lesson) ----
for s in "$POLLER" "$INSTALLER" "$DRIFT"; do
  bash -n "$s" 2>/dev/null && ok || bad "syntax: $s"
done

# --- 1. structural invariants (static assertions) ---------------------------
grep -q 'SuccessfulExit' "$PLIST" && grep -q '<false/>' "$PLIST" && ok || bad "plist not crash-only KeepAlive"
grep -q 'StartInterval' "$PLIST" && ok || bad "plist has no StartInterval"
grep -q 'Application Support/baker' "$INSTALLER" && ok || bad "installer not deploying to TCC-safe dir"
grep -q 'Desktop' "$INSTALLER" && bad "installer references ~/Desktop (TCC lesson)" || ok
grep -q '__KEY__' "$PLIST" && bad "plist embeds a secret token (endpoint is public)" || ok
grep -Eq 'exit 0[[:space:]]*$|exit 0 ' "$POLLER" && ok || bad "poller missing tolerant exit 0"

# --- 2. poller writes a valid snapshot from a stubbed machine surface --------
STUB_JSON="$TMP/bus_health.json"
cat > "$STUB_JSON" <<'JSON'
{"latency":{"p50_s":1.0,"acked":10,"total":12},"seats":[{"seat":"lead","unacked":1,"oldest_age_s":30}],"delivery":{"sla_s":3600}}
JSON
# Minimal HTTP stub: serve the JSON for ANY path on an ephemeral localhost port.
PORT_FILE="$TMP/port"
python3 - "$STUB_JSON" "$PORT_FILE" <<'PY' &
import http.server, socketserver, sys, threading
body = open(sys.argv[1],'rb').read()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass
srv = socketserver.TCPServer(('127.0.0.1',0), H)
open(sys.argv[2],'w').write(str(srv.server_address[1]))
srv.serve_forever()
PY
STUB_PID=$!
# wait for the stub to publish its port
for _ in $(seq 1 50); do [ -s "$PORT_FILE" ] && break; sleep 0.1; done
PORT="$(cat "$PORT_FILE" 2>/dev/null || echo '')"
if [ -n "$PORT" ]; then
  SNAP_DIR="$TMP/snap"
  LAB_URL="http://127.0.0.1:${PORT}" ARM_CADENCE_SNAPSHOT_DIR="$SNAP_DIR" \
    ARM_CADENCE_LOG="$TMP/cadence.log" bash "$POLLER"
  rc=$?
  [ "$rc" -eq 0 ] && ok || bad "poller exit=$rc (should be 0)"
  if [ -f "$SNAP_DIR/latest.json" ]; then
    python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
assert d["ok"] is True, "ok flag"
bh=d["sources"]["bus_health"]
assert bh["http"]=="200" and bh["ok"] is True, "bus_health source"
assert bh["data"]["seats"][0]["seat"]=="lead", "embedded data"
' "$SNAP_DIR/latest.json" && ok || bad "snapshot content invalid"
    # a timestamped history file also exists
    ls "$SNAP_DIR"/*.json | grep -qv 'latest.json' && ok || bad "no timestamped history snapshot"
  else
    bad "poller wrote no latest.json"
  fi
else
  echo "SKIP: could not start HTTP stub"
fi

# --- 3. poller tolerance: unreachable endpoint still exits 0 + DEGRADED ------
SNAP2="$TMP/snap2"
LAB_URL="http://127.0.0.1:1" ARM_CADENCE_SNAPSHOT_DIR="$SNAP2" \
  ARM_CADENCE_LOG="$TMP/cadence2.log" bash "$POLLER"
rc=$?
[ "$rc" -eq 0 ] && ok || bad "poller not tolerant of unreachable endpoint (exit=$rc)"
if [ -f "$SNAP2/latest.json" ]; then
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] is False; assert d["sources"]["bus_health"]["ok"] is False' "$SNAP2/latest.json" && ok || bad "degraded snapshot not marked ok=false"
else
  bad "poller wrote no snapshot on unreachable endpoint"
fi
grep -q 'DEGRADED' "$TMP/cadence2.log" 2>/dev/null && ok || bad "degraded poll not logged"

# --- 4. installer dry-run deploys the worker (no launchctl) ------------------
DEPLOY="$TMP/deploy"
ARM_CADENCE_DRYRUN=1 ARM_CADENCE_DEPLOY_DIR="$DEPLOY" ARM_CADENCE_SNAPSHOT_DIR="$TMP/snap3" \
  bash "$INSTALLER" >/dev/null 2>&1
[ -x "$DEPLOY/arm_cadence_poll.sh" ] && ok || bad "dry-run did not deploy executable worker"

# --- 5. installer --check reports DRIFT when nothing is installed ------------
# Point the check at empty dirs so it must fail (no plist, no snapshot).
ARM_CADENCE_DEPLOY_DIR="$TMP/empty" ARM_CADENCE_SNAPSHOT_DIR="$TMP/empty-snap" \
  bash "$INSTALLER" --check >"$TMP/check.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "--check returned 0 on a non-installed job"
grep -q 'RESULT: DRIFT' "$TMP/check.out" && ok || bad "--check did not print RESULT: DRIFT"

# --- 6. drift sentinel is fail-open (exit 0) + logs on drift -----------------
ARM_CADENCE_CHECK_DIR="$ROOT/scripts" \
  ARM_CADENCE_DEPLOY_DIR="$TMP/empty" ARM_CADENCE_SNAPSHOT_DIR="$TMP/empty-snap" \
  ARM_CADENCE_DRIFT_LOG="$TMP/drift.log" ARM_CADENCE_DRIFT_BUS_ROLE="__nokey__" \
  bash "$DRIFT"
rc=$?
[ "$rc" -eq 0 ] && ok || bad "drift sentinel not fail-open (exit=$rc)"
grep -q 'arm-cadence-drift' "$TMP/drift.log" 2>/dev/null && ok || bad "drift sentinel wrote no log line"

echo "arm_cadence tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
