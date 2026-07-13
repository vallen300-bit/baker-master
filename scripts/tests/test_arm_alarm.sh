#!/usr/bin/env bash
# test_arm_alarm.sh — ARM_OUT_OF_BAND_ALARM_1 regression suite.
# Exercises the watchdog (verdict eval + dedupe + recovery), the installer
# (dry-run + --check drift + interval clamp), the drift sentinel (fail-open),
# and the structural invariants (crash-only KeepAlive, TCC-safe deploy dir,
# zero-secret plist, <=5-min SLO, non-bus). Hermetic: the email/notification
# senders are injected as recorders — NO real Outlook send, NO launchctl, NO bus.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKER="$ROOT/scripts/arm_alarm_check.sh"
INSTALLER="$ROOT/scripts/install_arm_alarm_job.sh"
DRIFT="$ROOT/scripts/arm_alarm_drift_check.sh"
PLIST="$ROOT/scripts/launchd/com.baker.arm-alarm.plist"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); }
bad() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

TMP="$(mktemp -d -t arm_alarm_test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

# Recorders: append one line per email / notification so we can count sends.
EMAIL_LOG="$TMP/emails.log"; NOTIFY_LOG="$TMP/notify.log"
: > "$EMAIL_LOG"; : > "$NOTIFY_LOG"
SEND_CMD='printf "%s\n" "$ARM_ALARM_SUBJECT" >> '"$EMAIL_LOG"
NOTIFY_CMD='printf "%s\n" "$ARM_ALARM_TITLE" >> '"$NOTIFY_LOG"

now="$(date +%s)"
iso() { python3 -c "import sys,datetime; print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" "$1"; }

# Fresh helpers: write a report/canary marker with an age (seconds).
write_report() { mkdir -p "$1/markers"; printf '{"delivered_at": "%s"}\n' "$(iso $(( now - $2 )) )" > "$1/markers/report.json"; }
write_canary() { mkdir -p "$1/markers"; printf '{"ok": %s, "checked_at": "%s"}\n' "$3" "$(iso $(( now - $2 )) )" > "$1/markers/canary.json"; }

# run_worker <alarm_dir> [extra NAME=val ...] — invoke with recorders + fast
# thresholds. Uses env so the caller's extra NAME=val args apply as environment
# (a bare "$@" prefix would be parsed as a command word, not an assignment).
run_worker() {
  local dir="$1"; shift
  env ARM_ALARM_DIR="$dir" ARM_ALARM_LOG="$dir/alarm.log" \
    ARM_ALARM_SEND_CMD="$SEND_CMD" ARM_ALARM_NOTIFY_CMD="$NOTIFY_CMD" \
    ARM_ALARM_REPORT_MAX_AGE_S=3600 ARM_ALARM_CANARY_MAX_AGE_S=3600 \
    "$@" bash "$WORKER"
}
emails() { wc -l < "$EMAIL_LOG" | tr -d ' '; }
reset_recorders() { : > "$EMAIL_LOG"; : > "$NOTIFY_LOG"; }

# --- 0. syntax probes (lost-exec/truncation guard) --------------------------
for s in "$WORKER" "$INSTALLER" "$DRIFT"; do
  bash -n "$s" 2>/dev/null && ok || bad "syntax: $s"
done

# --- 1. structural invariants (static assertions) ---------------------------
grep -q 'SuccessfulExit' "$PLIST" && grep -q '<false/>' "$PLIST" && ok || bad "plist not crash-only KeepAlive"
grep -q 'StartInterval' "$PLIST" && ok || bad "plist has no StartInterval"
grep -q 'Application Support/baker' "$INSTALLER" && ok || bad "installer not deploying to TCC-safe dir"
grep -q 'Desktop' "$INSTALLER" && bad "installer references ~/Desktop (TCC lesson)" || ok
grep -q '__KEY__' "$PLIST" && bad "plist embeds a secret token (Outlook M365 auth, none needed)" || ok
# Non-bus invariant: no actual bus CALL (curl to the daemon, terminal-key auth,
# or LAB_URL). A local ~/.brisen-lab/ path or a doc mention of "bus" is fine —
# only a live network call to the bus violates the out-of-band contract.
grep -Eq 'X-Terminal-Key|LAB_URL|curl[^|]*(/msg/|bus_health|brisen-lab\.onrender)' "$WORKER" && bad "worker makes a bus call (must be non-bus)" || ok
grep -Eq 'exit 0[[:space:]]*$|exit 0 ' "$WORKER" && ok || bad "worker missing tolerant exit 0"
grep -q 'gt 300' "$INSTALLER" && ok || bad "installer does not clamp interval to <=300s (SLO)"

# --- 2. all-fresh markers => NO alarm ---------------------------------------
D="$TMP/fresh"; write_report "$D" 60; write_canary "$D" 60 true
reset_recorders; run_worker "$D"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "fresh-markers run exit=$rc (should be 0)"
[ "$(emails)" -eq 0 ] && ok || bad "fresh markers fired $(emails) alarm(s) (expected 0)"

# --- 3. stale report marker => exactly ONE alarm ----------------------------
D="$TMP/stale"; write_report "$D" 7200; write_canary "$D" 60 true   # report 2h > 1h threshold
reset_recorders; run_worker "$D"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "stale-report run exit=$rc"
[ "$(emails)" -eq 1 ] && ok || bad "stale report fired $(emails) alarm(s) (expected 1)"
grep -q 'report' "$EMAIL_LOG" && ok || bad "alarm subject did not name the report source"
[ "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" -eq 1 ] && ok || bad "notification not sent alongside email"

# --- 4. dedupe: second run still stale within cooldown => NO new alarm -------
reset_recorders; run_worker "$D" ARM_ALARM_COOLDOWN_S=21600; rc=$?
[ "$(emails)" -eq 0 ] && ok || bad "dedupe failed: re-alarmed within cooldown ($(emails))"

# --- 5. cooldown backstop: still stale, cooldown=0 => re-alarm ---------------
reset_recorders; run_worker "$D" ARM_ALARM_COOLDOWN_S=0; rc=$?
[ "$(emails)" -eq 1 ] && ok || bad "cooldown backstop did not re-alarm with cooldown=0 ($(emails))"
grep -q 'STILL FAILING' "$EMAIL_LOG" && ok || bad "re-alarm not marked STILL FAILING"

# --- 6. recovery: report marker fresh again => recovery notice + re-arm ------
write_report "$D" 60   # fresh now
reset_recorders; run_worker "$D"; rc=$?
[ "$(emails)" -eq 1 ] && ok || bad "recovery did not send exactly 1 notice ($(emails))"
grep -q 'RECOVERY' "$EMAIL_LOG" && ok || bad "recovery notice missing RECOVERY marker"
# state incident cleared (active=false)
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); inc=d["incidents"]["report:stale"]; assert inc["active"] is False' "$D/state.json" && ok || bad "recovery did not clear active incident"
# subsequent clean run => no further alarm (re-armed, but healthy)
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 0 ] && ok || bad "post-recovery clean run alarmed ($(emails))"

# --- 7. canary ok=false => alarm even though timestamp is fresh --------------
D="$TMP/canaryfail"; write_report "$D" 60; write_canary "$D" 60 false
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 1 ] && ok || bad "canary ok=false did not alarm ($(emails))"
grep -q 'canary' "$EMAIL_LOG" && ok || bad "canary-fail alarm did not name canary source"

# --- 8. missing marker: AMBER default (no alarm), RED when flipped -----------
D="$TMP/missing"; mkdir -p "$D/markers"   # no marker files at all
reset_recorders; run_worker "$D"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "missing-marker default run exit=$rc"
[ "$(emails)" -eq 0 ] && ok || bad "missing marker false-paged with MISSING_IS_RED=0 ($(emails))"
grep -q 'AMBER' "$D/alarm.log" && ok || bad "missing marker not logged AMBER"
reset_recorders; run_worker "$D" ARM_ALARM_MISSING_IS_RED=1
[ "$(emails)" -ge 1 ] && ok || bad "MISSING_IS_RED=1 did not alarm on absent markers ($(emails))"

# --- 9. installer dry-run deploys the worker (no launchctl) ------------------
DEPLOY="$TMP/deploy"
ARM_ALARM_DRYRUN=1 ARM_ALARM_DEPLOY_DIR="$DEPLOY" ARM_ALARM_DIR="$TMP/adir" \
  bash "$INSTALLER" >/dev/null 2>&1
[ -x "$DEPLOY/arm_alarm_check.sh" ] && ok || bad "dry-run did not deploy executable worker"

# --- 10. installer interval clamp: >300 clamps to 300 (dry-run echo) ---------
OUT="$(ARM_ALARM_DRYRUN=1 ARM_ALARM_INTERVAL_S=99999 ARM_ALARM_DEPLOY_DIR="$TMP/d2" ARM_ALARM_DIR="$TMP/a2" bash "$INSTALLER" 2>&1)"
echo "$OUT" | grep -q 'interval=300s' && ok || bad "interval not clamped to 300s (got: $(echo "$OUT" | grep -o 'interval=[0-9]*s'))"

# --- 11. installer --check reports DRIFT when nothing is installed -----------
ARM_ALARM_DEPLOY_DIR="$TMP/empty" ARM_ALARM_DIR="$TMP/empty-a" \
  bash "$INSTALLER" --check >"$TMP/check.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "--check returned 0 on a non-installed job"
grep -q 'RESULT: DRIFT' "$TMP/check.out" && ok || bad "--check did not print RESULT: DRIFT"

# --- 12. drift sentinel is fail-open (exit 0) + logs on drift ----------------
ARM_ALARM_CHECK_DIR="$ROOT/scripts" \
  ARM_ALARM_DEPLOY_DIR="$TMP/empty" ARM_ALARM_DIR="$TMP/empty-a" \
  ARM_ALARM_DRIFT_LOG="$TMP/drift.log" ARM_ALARM_DRIFT_BUS_ROLE="__nokey__" \
  bash "$DRIFT"
rc=$?
[ "$rc" -eq 0 ] && ok || bad "drift sentinel not fail-open (exit=$rc)"
grep -q 'arm-alarm-drift' "$TMP/drift.log" 2>/dev/null && ok || bad "drift sentinel wrote no log line"

echo "arm_alarm tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
