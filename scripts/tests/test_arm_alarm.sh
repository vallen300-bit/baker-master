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
# TO_LOG records the resolved recipient the email channel would use (ARM_ALARM_TO)
# so the per-kind recipient-split tests can assert routing without a real send.
EMAIL_LOG="$TMP/emails.log"; NOTIFY_LOG="$TMP/notify.log"; TO_LOG="$TMP/to.log"
: > "$EMAIL_LOG"; : > "$NOTIFY_LOG"; : > "$TO_LOG"
SEND_CMD='printf "%s\n" "$ARM_ALARM_SUBJECT" >> '"$EMAIL_LOG"'; printf "%s\n" "$ARM_ALARM_TO" >> '"$TO_LOG"
NOTIFY_CMD='printf "%s\n" "$ARM_ALARM_TITLE" >> '"$NOTIFY_LOG"

now="$(date +%s)"
iso() { python3 -c "import sys,datetime; print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" "$1"; }

# Fresh helpers: write a report/canary/semantic marker with an age (seconds).
write_report() { mkdir -p "$1/markers"; printf '{"delivered_at": "%s"}\n' "$(iso $(( now - $2 )) )" > "$1/markers/report.json"; }
write_canary() { mkdir -p "$1/markers"; printf '{"ok": %s, "checked_at": "%s"}\n' "$3" "$(iso $(( now - $2 )) )" > "$1/markers/canary.json"; }
# write_semantic <dir> <age_s> <semantic_ok true|false> [schema]
write_semantic() { mkdir -p "$1/markers"; printf '{"schema":"%s","evaluated_at":"%s","semantic_ok":%s}\n' "${4:-semantic_delivery_verdict_v1}" "$(iso $(( now - $2 )) )" "$3" > "$1/markers/semantic.json"; }
write_cadence() {
  mkdir -p "$(dirname "$1")"
  printf '{"captured_at":"%s","health":"%s","ok":%s}\n' \
    "$(iso $(( now - $3 )) )" "$2" "$4" > "$1"
}

# run_worker <alarm_dir> [extra NAME=val ...] — invoke with recorders + fast
# thresholds. Uses env so the caller's extra NAME=val args apply as environment
# (a bare "$@" prefix would be parsed as a command word, not an assignment).
run_worker() {
  local dir="$1"; shift
  env ARM_ALARM_DIR="$dir" ARM_ALARM_LOG="$dir/alarm.log" \
    ARM_ALARM_CADENCE_SNAPSHOT="$dir/cadence.json" \
    ARM_ALARM_SEND_CMD="$SEND_CMD" ARM_ALARM_NOTIFY_CMD="$NOTIFY_CMD" \
    ARM_ALARM_REPORT_MAX_AGE_S=3600 ARM_ALARM_CANARY_MAX_AGE_S=3600 \
    "$@" bash "$WORKER"
}
emails() { wc -l < "$EMAIL_LOG" | tr -d ' '; }
last_to() { tail -n 1 "$TO_LOG" 2>/dev/null; }
tos() { sort -u "$TO_LOG" 2>/dev/null | grep -c .; }   # count of DISTINCT recipients recorded
reset_recorders() { : > "$EMAIL_LOG"; : > "$NOTIFY_LOG"; : > "$TO_LOG"; }

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
grep -q 'STILL-FAILING' "$EMAIL_LOG" && ok || bad "re-alarm not marked STILL-FAILING"

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

# --- 8. cadence health: db_unreachable is RED, parseable degraded is not -----
D="$TMP/cadence-db"; write_report "$D" 60; write_canary "$D" 60 true
write_cadence "$D/cadence.json" db_unreachable 60 false
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 1 ] && ok || bad "db_unreachable cadence did not alarm ($(emails))"
grep -q 'db_unreachable(cadence)' "$EMAIL_LOG" && ok || bad "db_unreachable alarm did not name cadence"

D="$TMP/cadence-degraded"; write_report "$D" 60; write_canary "$D" 60 true
write_cadence "$D/cadence.json" degraded 60 false
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 0 ] && ok || bad "parseable degraded cadence false-paged ($(emails))"

# --- 9. cadence stale after a fresh marker is RED ----------------------------
D="$TMP/cadence-stale"; write_report "$D" 60; write_canary "$D" 60 true
write_cadence "$D/cadence.json" ok 7200 true
reset_recorders; run_worker "$D" ARM_ALARM_CADENCE_MAX_AGE_S=3600
[ "$(emails)" -eq 1 ] && ok || bad "stale cadence did not alarm ($(emails))"
grep -q 'cadence:stale' "$D/alarm.log" && ok || bad "stale cadence not logged cadence:stale"

# --- 10. missing marker: AMBER default (no alarm), RED when flipped -----------
D="$TMP/missing"; mkdir -p "$D/markers"   # no marker files at all
reset_recorders; run_worker "$D"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "missing-marker default run exit=$rc"
[ "$(emails)" -eq 0 ] && ok || bad "missing marker false-paged with MISSING_IS_RED=0 ($(emails))"
grep -q 'AMBER' "$D/alarm.log" && ok || bad "missing marker not logged AMBER"
reset_recorders; run_worker "$D" ARM_ALARM_MISSING_IS_RED=1
[ "$(emails)" -ge 1 ] && ok || bad "MISSING_IS_RED=1 did not alarm on absent markers ($(emails))"

# --- 11. installer dry-run deploys the worker (no launchctl) -----------------
DEPLOY="$TMP/deploy"
ARM_ALARM_DRYRUN=1 ARM_ALARM_DEPLOY_DIR="$DEPLOY" ARM_ALARM_DIR="$TMP/adir" \
  bash "$INSTALLER" >/dev/null 2>&1
[ -x "$DEPLOY/arm_alarm_check.sh" ] && ok || bad "dry-run did not deploy executable worker"

# --- 12. installer interval clamp: >300 clamps to 300 (dry-run echo) ----------
OUT="$(ARM_ALARM_DRYRUN=1 ARM_ALARM_INTERVAL_S=99999 ARM_ALARM_DEPLOY_DIR="$TMP/d2" ARM_ALARM_DIR="$TMP/a2" bash "$INSTALLER" 2>&1)"
echo "$OUT" | grep -q 'interval=300s' && ok || bad "interval not clamped to 300s (got: $(echo "$OUT" | grep -o 'interval=[0-9]*s'))"

# --- 13. installer parity: current deploy CLEAN, one-byte drift RED ----------
CHECK_HOME="$TMP/check-home"
mkdir -p "$CHECK_HOME/Library/LaunchAgents" "$TMP/bin"
cat > "$TMP/bin/launchctl" <<'SH'
#!/usr/bin/env bash
printf '123 0 com.baker.arm-alarm\n'
SH
chmod +x "$TMP/bin/launchctl"
python3 - "$PLIST" "$DEPLOY/arm_alarm_check.sh" "$CHECK_HOME/Library/LaunchAgents/com.baker.arm-alarm.plist" <<'PY'
import sys
tpl, worker, out = sys.argv[1:]
body = open(tpl).read()
for old, new in (
    ("__WORKER_PATH__", worker),
    ("__LABEL__", "com.baker.arm-alarm"),
    ("__CADENCE__", "180"),
    ("__LOG__", "/tmp/arm-alarm.log"),
    ("__ERRLOG__", "/tmp/arm-alarm.err.log"),
    ("__ALARM_DIR__", "/tmp/arm-alarm"),
    ("__ALARM_LOG__", "/tmp/arm-alarm.log"),
    ("__EMAIL_TO__", "test@example.invalid"),
):
    body = body.replace(old, new)
open(out, "w").write(body)
PY
PATH="$TMP/bin:$PATH" HOME="$CHECK_HOME" ARM_ALARM_DEPLOY_DIR="$DEPLOY" \
  ARM_ALARM_DIR="$TMP/check-alarm" bash "$INSTALLER" --check >"$TMP/parity-clean.out" 2>&1
[ "$?" -eq 0 ] && ok || bad "current worker parity did not pass"
grep -q 'RESULT: CLEAN' "$TMP/parity-clean.out" && ok || bad "parity CLEAN missing"
printf '\n# deliberate parity drift\n' >> "$DEPLOY/arm_alarm_check.sh"
PATH="$TMP/bin:$PATH" HOME="$CHECK_HOME" ARM_ALARM_DEPLOY_DIR="$DEPLOY" \
  ARM_ALARM_DIR="$TMP/check-alarm" bash "$INSTALLER" --check >"$TMP/parity-drift.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "worker parity drift returned 0"
grep -q 'deployed worker drifted from repo source' "$TMP/parity-drift.out" && ok || bad "worker parity failure not named"

# --- 14. installer --check reports DRIFT when nothing is installed ------------
ARM_ALARM_DEPLOY_DIR="$TMP/empty" ARM_ALARM_DIR="$TMP/empty-a" \
  bash "$INSTALLER" --check >"$TMP/check.out" 2>&1
rc=$?
[ "$rc" -ne 0 ] && ok || bad "--check returned 0 on a non-installed job"
grep -q 'RESULT: DRIFT' "$TMP/check.out" && ok || bad "--check did not print RESULT: DRIFT"

# --- 15. drift sentinel is fail-open (exit 0) + logs on drift -----------------
ARM_ALARM_CHECK_DIR="$ROOT/scripts" \
  ARM_ALARM_DEPLOY_DIR="$TMP/empty" ARM_ALARM_DIR="$TMP/empty-a" \
  ARM_ALARM_DRIFT_LOG="$TMP/drift.log" ARM_ALARM_DRIFT_BUS_ROLE="__nokey__" \
  bash "$DRIFT"
rc=$?
[ "$rc" -eq 0 ] && ok || bad "drift sentinel not fail-open (exit=$rc)"
grep -q 'arm-alarm-drift' "$TMP/drift.log" 2>/dev/null && ok || bad "drift sentinel wrote no log line"

# === DELIVERY-TRUTH regression tests (codex G2 #10455) ======================
# state field reader.
jqf() { python3 -c "import json,sys; d=json.load(open(sys.argv[1])); k=sys.argv[2]; print(d['incidents'].get(k,{}).get(sys.argv[3],''))" "$1" "$2" "$3" 2>/dev/null; }

# --- 16. BOTH channels fail => incident NOT marked alarmed; retry, no suppress -
D="$TMP/bothfail"; write_report "$D" 7200; write_canary "$D" 60 true
reset_recorders
run_worker "$D" ARM_ALARM_SEND_CMD='exit 1' ARM_ALARM_NOTIFY_CMD='exit 1' ARM_ALARM_BACKOFF_BASE_S=0
[ "$(emails)" -eq 0 ] && ok || bad "failed-delivery still recorded an email ($(emails))"
grep -q 'SEND-FAIL' "$D/alarm.log" && ok || bad "both-channel failure not logged SEND-FAIL"
[ "$(jqf "$D/state.json" report:stale delivery_pending)" = "True" ] && ok || bad "failed delivery did not set delivery_pending"
[ "$(jqf "$D/state.json" report:stale active)" != "True" ] && ok || bad "failed delivery wrongly marked incident active (delivery-truth bug)"
# next poll (working sender, backoff=0 so immediately due) => now delivers
reset_recorders
run_worker "$D" ARM_ALARM_BACKOFF_BASE_S=0
[ "$(emails)" -eq 1 ] && ok || bad "failed incident was suppressed instead of retried ($(emails))"
[ "$(jqf "$D/state.json" report:stale active)" = "True" ] && ok || bad "successful retry did not mark incident active"
[ "$(jqf "$D/state.json" report:stale delivery_pending)" = "False" ] && ok || bad "successful retry did not clear delivery_pending"

# --- 17. PARTIAL success (email fails, notification ok) => delivered once -----
D="$TMP/partial"; write_report "$D" 7200; write_canary "$D" 60 true
reset_recorders
run_worker "$D" ARM_ALARM_SEND_CMD='exit 1'   # email fails; notify recorder succeeds
[ "$(emails)" -eq 0 ] && ok || bad "email channel recorded a send despite exit 1 ($(emails))"
[ "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" -ge 1 ] && ok || bad "notification channel not attempted on email failure"
[ "$(jqf "$D/state.json" report:stale active)" = "True" ] && ok || bad "partial success (1 channel) did not mark incident delivered"

# --- 18. RECOVERY of an UNDELIVERED alarm => cleared silently, no recovery mail
D="$TMP/undeliv"; write_report "$D" 7200; write_canary "$D" 60 true
run_worker "$D" ARM_ALARM_SEND_CMD='exit 1' ARM_ALARM_NOTIFY_CMD='exit 1' ARM_ALARM_BACKOFF_BASE_S=0 >/dev/null 2>&1
write_report "$D" 60   # marker fresh again before any alarm ever delivered
reset_recorders
run_worker "$D" ARM_ALARM_BACKOFF_BASE_S=0
[ "$(emails)" -eq 0 ] && ok || bad "undelivered-then-recovered sent a spurious recovery email ($(emails))"
grep -q 'CLEAR-UNDELIVERED' "$D/alarm.log" && ok || bad "undelivered recovery not logged CLEAR-UNDELIVERED"

# --- 19. BOUNDED BACKOFF grows across failed retries (deterministic clock) ----
D="$TMP/backoff"; mkdir -p "$D/markers"
printf '{"delivered_at": "1970-01-01T00:00:00Z"}\n' > "$D/markers/report.json"  # always stale
FAILENV=(ARM_ALARM_SEND_CMD='exit 1' ARM_ALARM_NOTIFY_CMD='exit 1' ARM_ALARM_REPORT_MAX_AGE_S=1 ARM_ALARM_CANARY_MAX_AGE_S=1 ARM_ALARM_BACKOFF_BASE_S=10 ARM_ALARM_BACKOFF_CAP_S=1000)
run_worker "$D" ARM_ALARM_NOW=1000 "${FAILENV[@]}" >/dev/null 2>&1   # fail#1 -> next_retry 1010
[ "$(jqf "$D/state.json" report:stale next_retry_at)" = "1010" ] && ok || bad "backoff#1 next_retry_at != 1010 (got $(jqf "$D/state.json" report:stale next_retry_at))"
run_worker "$D" ARM_ALARM_NOW=1005 "${FAILENV[@]}" >/dev/null 2>&1   # within backoff -> suppressed, still fail#1
[ "$(jqf "$D/state.json" report:stale send_fail_count)" = "1" ] && ok || bad "retry fired before backoff elapsed (send_fail_count=$(jqf "$D/state.json" report:stale send_fail_count))"
run_worker "$D" ARM_ALARM_NOW=1020 "${FAILENV[@]}" >/dev/null 2>&1   # backoff elapsed -> fail#2, next_retry 1040
[ "$(jqf "$D/state.json" report:stale send_fail_count)" = "2" ] && ok || bad "backoff-elapsed retry did not increment send_fail_count"
[ "$(jqf "$D/state.json" report:stale next_retry_at)" = "1040" ] && ok || bad "backoff did not grow 10->20 (next_retry_at=$(jqf "$D/state.json" report:stale next_retry_at), expected 1040)"

# === SEMANTIC kind regression tests (micro-lane lead #10630) ================
# rider (b) is covered by tests 2-16 above staying green (report/canary unchanged
# with semantic added to SOURCES); the tests below cover the new kind itself.

# --- 20. absent semantic + SEMANTIC_ENFORCE=0 (default) => TRUE silent skip ---
# report+canary fresh so only the semantic source is in question. Absent semantic
# must not page AND must not log (not even AMBER) pre-ship (rider a).
D="$TMP/sem_absent"; write_report "$D" 60; write_canary "$D" 60 true
reset_recorders; run_worker "$D"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "sem-absent run exit=$rc"
[ "$(emails)" -eq 0 ] && ok || bad "absent semantic false-paged with ENFORCE=0 ($(emails))"
grep -qi 'semantic' "$D/alarm.log" && bad "absent semantic logged (should be TRUE silent skip)" || ok

# --- 21. present semantic_ok=false + ENFORCE=0 => TRUE silent skip ----------
D="$TMP/sem_fail"; write_report "$D" 60; write_canary "$D" 60 true; write_semantic "$D" 60 false
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 0 ] && ok || bad "present semantic false-paged with ENFORCE=0 ($(emails))"
grep -qi 'semantic' "$D/alarm.log" && bad "present semantic logged while ENFORCE=0" || ok

# --- 22. present semantic_ok=false + ENFORCE=1 => alarm ----------------------
reset_recorders; run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1
[ "$(emails)" -eq 1 ] && ok || bad "enforced semantic_ok=false did not alarm ($(emails))"
grep -q 'semantic' "$EMAIL_LOG" && ok || bad "enforced semantic alarm did not name semantic source"
[ "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" -eq 1 ] && ok || bad "enforced semantic alarm sent no notification"

# --- 23. present semantic stale evaluated_at => stale alarm ------------------
D="$TMP/sem_stale"; write_report "$D" 60; write_canary "$D" 60 true; write_semantic "$D" 7200 true
reset_recorders; run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_SEMANTIC_MAX_AGE_S=3600
[ "$(emails)" -eq 1 ] && ok || bad "stale semantic did not alarm ($(emails))"
grep -q 'semantic:stale' "$D/alarm.log" && ok || bad "stale semantic not logged semantic:stale"

# --- 24. present semantic fresh + semantic_ok=true => NO alarm --------------
D="$TMP/sem_ok"; write_report "$D" 60; write_canary "$D" 60 true; write_semantic "$D" 60 true
reset_recorders; run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1; [ "$(emails)" -eq 0 ] && ok || bad "healthy semantic marker fired an alarm ($(emails))"

# --- 25. unknown schema major => skipped, NOT paged (marker-version guard) ---
D="$TMP/sem_badver"; write_report "$D" 60; write_canary "$D" 60 true
write_semantic "$D" 60 false semantic_delivery_verdict_v2   # ok=false but unknown schema
reset_recorders; run_worker "$D"; [ "$(emails)" -eq 0 ] && ok || bad "unknown-schema semantic false-paged ($(emails))"

# --- 26. SEMANTIC_ENFORCE=1 + absent => normal MISSING policy (AMBER, then RED)
D="$TMP/sem_enforce"; write_report "$D" 60; write_canary "$D" 60 true   # only semantic absent
reset_recorders; run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1
[ "$(emails)" -eq 0 ] && ok || bad "enforce=1 absent semantic paged under MISSING_IS_RED=0 ($(emails))"
grep -qi 'AMBER' "$D/alarm.log" && ok || bad "enforce=1 absent semantic not logged AMBER"
reset_recorders; run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_MISSING_IS_RED=1
[ "$(emails)" -ge 1 ] && ok || bad "enforce=1 + MISSING_IS_RED=1 did not alarm on absent semantic ($(emails))"
grep -q 'semantic' "$EMAIL_LOG" && ok || bad "enforced absent-semantic alarm did not name semantic source"

# === PER-KIND RECIPIENT SPLIT tests (ARM_ALARM_RECIPIENT_SPLIT_1) ===========
# The alarm routes email by incident source: ARM_ALARM_EMAIL_TO_<KIND> when set,
# else fallback EMAIL_TO. Routine semantic red -> lead; report/canary -> Director.
DIRECTOR="director@test.invalid"; LEAD="lead@test.invalid"

# --- 27. AC3 backward-compat: no per-kind env => every kind resolves to EMAIL_TO
# report red, no ARM_ALARM_EMAIL_TO_* set => recipient is exactly EMAIL_TO.
D="$TMP/split_compat"; write_report "$D" 7200; write_canary "$D" 60 true
reset_recorders; run_worker "$D" ARM_ALARM_EMAIL_TO="$DIRECTOR"
[ "$(emails)" -eq 1 ] && ok || bad "AC3 compat: report red did not fire once ($(emails))"
[ "$(last_to)" = "$DIRECTOR" ] && ok || bad "AC3 compat: report resolved to '$(last_to)' not EMAIL_TO ($DIRECTOR)"
grep -q 'resolved report:stale -> EMAIL_TO (no ARM_ALARM_EMAIL_TO_REPORT)' "$D/alarm.log" && ok \
  || bad "AC3/AC5 compat: fallback resolve log line missing"

# --- 28. AC2 semantic red => lead (per-kind env), report red => Director (fallback)
# Both a semantic incident and a report incident fire in ONE run; assert each
# lands on its own recipient (semantic->lead via per-kind, report->EMAIL_TO).
D="$TMP/split_route"; write_report "$D" 7200; write_canary "$D" 60 true; write_semantic "$D" 60 false
reset_recorders
run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_EMAIL_TO="$DIRECTOR" ARM_ALARM_EMAIL_TO_SEMANTIC="$LEAD"
[ "$(emails)" -eq 2 ] && ok || bad "AC2 route: expected 2 alarms (semantic+report), got $(emails)"
grep -qx "$LEAD" "$TO_LOG" && ok || bad "AC2 route: semantic red did not resolve to lead ($LEAD)"
grep -qx "$DIRECTOR" "$TO_LOG" && ok || bad "AC2 route: report red did not resolve to Director/EMAIL_TO ($DIRECTOR)"
grep -q 'resolved semantic:failed -> ARM_ALARM_EMAIL_TO_SEMANTIC' "$D/alarm.log" && ok \
  || bad "AC2/AC5: per-kind resolve log line missing"
grep -q 'resolved report:stale -> EMAIL_TO (no ARM_ALARM_EMAIL_TO_REPORT)' "$D/alarm.log" && ok \
  || bad "AC2/AC5: report fallback resolve log line missing"

# --- 29. AC2 lifecycle consistency (rider #11679): FIRE + STILL-FAILING + RECOVERY
# of the SAME semantic incident all resolve to lead, never Director.
D="$TMP/split_lifecycle"; write_report "$D" 60; write_canary "$D" 60 true; write_semantic "$D" 60 false
# FIRE
reset_recorders
run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_EMAIL_TO="$DIRECTOR" ARM_ALARM_EMAIL_TO_SEMANTIC="$LEAD"
[ "$(last_to)" = "$LEAD" ] && ok || bad "lifecycle FIRE: semantic did not resolve to lead ($(last_to))"
grep -q 'FIRE semantic:failed' "$D/alarm.log" && ok || bad "lifecycle FIRE: no FIRE log for semantic"
# STILL-FAILING (cooldown=0 forces a re-alarm on the still-red incident)
reset_recorders
run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_COOLDOWN_S=0 ARM_ALARM_EMAIL_TO="$DIRECTOR" ARM_ALARM_EMAIL_TO_SEMANTIC="$LEAD"
[ "$(emails)" -eq 1 ] && ok || bad "lifecycle STILL-FAILING: did not re-alarm ($(emails))"
grep -q 'STILL-FAILING' "$EMAIL_LOG" && ok || bad "lifecycle STILL-FAILING: subject not marked"
[ "$(last_to)" = "$LEAD" ] && ok || bad "lifecycle STILL-FAILING: resolved to '$(last_to)' not lead"
# RECOVERY (semantic marker healthy again => recovery notice, still to lead)
write_semantic "$D" 60 true
reset_recorders
run_worker "$D" ARM_ALARM_SEMANTIC_ENFORCE=1 ARM_ALARM_EMAIL_TO="$DIRECTOR" ARM_ALARM_EMAIL_TO_SEMANTIC="$LEAD"
[ "$(emails)" -eq 1 ] && ok || bad "lifecycle RECOVERY: did not send exactly one notice ($(emails))"
grep -q 'RECOVERY' "$EMAIL_LOG" && ok || bad "lifecycle RECOVERY: notice not marked RECOVERY"
[ "$(last_to)" = "$LEAD" ] && ok || bad "lifecycle RECOVERY: semantic recovery went to '$(last_to)' not lead (Director-misfire regression)"
grep -qx "$DIRECTOR" "$TO_LOG" && bad "lifecycle RECOVERY: a semantic-lifecycle notice reached Director" || ok

# --- 30. per-kind env for one kind does NOT leak to another kind --------------
# Set ONLY ARM_ALARM_EMAIL_TO_SEMANTIC; a report red must still fall back to EMAIL_TO.
D="$TMP/split_noleak"; write_report "$D" 7200; write_canary "$D" 60 true
reset_recorders
run_worker "$D" ARM_ALARM_EMAIL_TO="$DIRECTOR" ARM_ALARM_EMAIL_TO_SEMANTIC="$LEAD"
[ "$(last_to)" = "$DIRECTOR" ] && ok || bad "no-leak: report resolved to '$(last_to)' (semantic env leaked)"

echo "arm_alarm tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
