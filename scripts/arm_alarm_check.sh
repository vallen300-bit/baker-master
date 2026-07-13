#!/usr/bin/env bash
# arm_alarm_check.sh — ARM_OUT_OF_BAND_ALARM_1 (Plan v3 micro-brief, bus #10404).
#
# The ARM custodian's OUT-OF-BAND alarm path. Runs from launchd
# (com.baker.arm-alarm) every <=5 min and fires an alarm OFF the bus (email via
# Outlook.app + a macOS notification) when a canary round-trip fails or ARM's
# daily report is missed.
#
# WHY out-of-band (the whole point): ARM's NORMAL alarms fire *through the bus*
# (the `arm_flag_lead` lane). But the two failure modes below are exactly the
# ones a bus alarm cannot deliver:
#   - CANARY FAILURE — the post->wake->ack loop is broken, so a bus alarm never
#     lands. Charter D3: canary RED is ARM-custodian-specific.
#   - REPORT-MISS — ARM never woke to synthesise its report, so it cannot post
#     its own "I'm dead" alarm. Charter §3: "missed by 07:00 UTC = RED
#     (fail-loud — the watchdog must be watched)."
# This job is that meta-watchdog. It reads ONLY local freshness markers and
# sends ONLY out-of-band (email + local notification). It NEVER touches the bus
# (brief: "explicitly non-bus … keep separate from bus reliability controls").
#
# SLO: <=5 min from failure to alarm. Guaranteed structurally: launchd
# StartInterval defaults to 180s (see install_arm_alarm_job.sh), detection
# latency <= one poll interval, email/notification send is sub-second, so
# worst-case end-to-end is ~180s + send << 300s. Interval is config, clamped
# <=300s so the SLO cannot be misconfigured away (installer enforces the clamp).
#
# WHAT it reads (v0): local freshness MARKERS written by the producers, NOT the
# bus. Each marker is a tiny JSON file the producer atomically rewrites:
#   report.json  {"delivered_at": "<iso8601>"}      — ARM report synthesis writes this each daily report.
#   canary.json  {"ok": true, "checked_at": "<iso>"} — the canary verifier writes this each round-trip check.
# The SOURCES array is the single extension point (mirrors arm_cadence_poll.sh):
# add "<key> <marker-file> <max_age_s> <kind>" rows as new out-of-band signals land.
#
# MISSING-MARKER POLICY (graceful degradation for producers-not-yet-shipped):
# the canary cron + report pipeline are separate briefs that may not be live on
# install day. A marker that has NEVER existed is AMBER (logged, no alarm) by
# default — so install day does not false-page. Once a marker has appeared and
# then goes stale, that is RED. Flip ARM_ALARM_MISSING_IS_RED=1 once every
# producer is guaranteed live to make a never-seen marker RED too.
#
# DEDUPE + COOLDOWN (mirrors charter F4): one alarm per incident key
# (source-key + incident-type, e.g. "report:stale"). A recovery (marker fresh
# again) is emailed and re-arms the key; while an incident stays active, a
# re-alarm fires only after ARM_ALARM_COOLDOWN_S (default 6h) as a backstop.
#
# TOLERANCE: any transient failure logs + exits 0 so launchd's crash-only
# KeepAlive does NOT back off into a relaunch storm (same rationale as
# arm_cadence_poll.sh). Marker freshness — not this script's exit code — is the
# health signal; the arm_alarm_drift_check.sh sentinel checks that THIS job is
# installed and healthy (and it may use the bus, since that is an install-health
# meta-check, not the out-of-band alarm itself).
#
# TEST SEAMS (hermetic suite): ARM_ALARM_SEND_CMD and ARM_ALARM_NOTIFY_CMD, when
# set, replace the real Outlook send / macOS notification with a recorder, so the
# suite exercises the full dedupe/recovery logic with zero real email.

set -u
set -o pipefail

ALARM_VERSION="1"
HOST="$(hostname 2>/dev/null || echo unknown)"
TS="$(date -u +%FT%TZ)"
NOW="$(date +%s)"

ALARM_DIR="${ARM_ALARM_DIR:-$HOME/.brisen-lab/arm-alarm}"
MARKER_DIR="${ARM_ALARM_MARKER_DIR:-$ALARM_DIR/markers}"
STATE_FILE="${ARM_ALARM_STATE:-$ALARM_DIR/state.json}"
LOG="${ARM_ALARM_LOG:-$HOME/.brisen-lab/arm-alarm.log}"

# Out-of-band email recipient. Default flagged for lead review (see ship report):
# the point of THIS path is to reach a human when the bus is down, so it targets
# the Director's ops address, overridable per host.
EMAIL_TO="${ARM_ALARM_EMAIL_TO:-dvallen@brisengroup.com}"

# never-seen marker => RED? default 0 (AMBER) so install day does not false-page.
MISSING_IS_RED="${ARM_ALARM_MISSING_IS_RED:-0}"
# re-alarm backstop for a still-active incident.
COOLDOWN_S="${ARM_ALARM_COOLDOWN_S:-21600}"   # 6h

# SOURCES: "<key> <marker-file> <max_age_s> <kind>". kind ∈ {report, canary}.
#   report: stale if now-delivered_at > max_age (default 26h = 24h + 2h grace).
#   canary: stale if now-checked_at > max_age OR the marker's ok flag is false.
# Extension point — add rows here as new out-of-band signals land; no code change.
SOURCES=(
  "report ${MARKER_DIR}/report.json ${ARM_ALARM_REPORT_MAX_AGE_S:-93600} report"
  "canary ${MARKER_DIR}/canary.json ${ARM_ALARM_CANARY_MAX_AGE_S:-93600} canary"
)

mkdir -p "$ALARM_DIR" "$MARKER_DIR" 2>/dev/null || true
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

log_line() { printf '%s arm-alarm %s %s\n' "$TS" "$HOST" "$*" >> "$LOG" 2>/dev/null || true; }

# --- single-instance guard (mkdir-mutex; stale-lock reclaim) ----------------
LOCK_DIR="${ARM_ALARM_LOCK:-/tmp/arm_alarm_check.lock}"
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
  log_line "SKIP another check already running"
  exit 0
fi
trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT

# --- out-of-band delivery (email + macOS notification) ----------------------
# Both are best-effort and injectable for tests. Neither touches the bus.
send_email() {
  # $1 subject  $2 body
  local subj="$1" body="$2"
  if [ -n "${ARM_ALARM_SEND_CMD:-}" ]; then
    ARM_ALARM_SUBJECT="$subj" ARM_ALARM_BODY="$body" ARM_ALARM_TO="$EMAIL_TO" \
      bash -c "$ARM_ALARM_SEND_CMD" >/dev/null 2>&1
    return $?
  fi
  # Real path: Outlook.app autonomous send (Pattern A) — no compose window, no
  # human, because the alarm fires when nobody is watching the bus. Plain-text
  # content; Director-personal identity (internal ops alert, no Baker signature).
  command -v osascript >/dev/null 2>&1 || return 1
  ARM_SUBJ="$subj" ARM_BODY="$body" ARM_TO="$EMAIL_TO" python3 - <<'PY' >/dev/null 2>&1
import os, subprocess
def esc(s): return s.replace('\\', '\\\\').replace('"', '\\"')
subj = esc(os.environ["ARM_SUBJ"]); body = esc(os.environ["ARM_BODY"]); to = esc(os.environ["ARM_TO"])
scpt = (
    'tell application "Microsoft Outlook"\n'
    '\tset m to make new outgoing message with properties {subject:"%s", content:"%s"}\n'
    '\tmake new recipient at m with properties {email address:{address:"%s"}}\n'
    '\tsend m\n'
    'end tell\n' % (subj, body, to)
)
subprocess.run(["osascript", "-e", scpt], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
}

send_notification() {
  # $1 title  $2 message  — a local macOS banner: a zero-dependency second
  # out-of-band channel that works even if Outlook/M365 auth is broken.
  local title="$1" msg="$2"
  if [ -n "${ARM_ALARM_NOTIFY_CMD:-}" ]; then
    ARM_ALARM_TITLE="$title" ARM_ALARM_MSG="$msg" bash -c "$ARM_ALARM_NOTIFY_CMD" >/dev/null 2>&1
    return $?
  fi
  command -v osascript >/dev/null 2>&1 || return 1
  local t="${title//\"/\\\"}" m="${msg//\"/\\\"}"
  osascript -e "display notification \"$m\" with title \"$t\"" >/dev/null 2>&1
}

# --- evaluate every source into a verdict -----------------------------------
# Emits, per source, one line: "<key>\t<incident-type|OK>\t<detail>".
#   incident-type: stale | failed | missing | OK
declare -a VERDICTS=()
for entry in "${SOURCES[@]}"; do
  # shellcheck disable=SC2086
  set -- $entry
  key="$1"; mfile="$2"; maxage="$3"; kind="$4"
  if [ ! -f "$mfile" ]; then
    if [ "$MISSING_IS_RED" = "1" ]; then
      VERDICTS+=("${key}"$'\t'"missing"$'\t'"marker never written: $mfile")
    else
      VERDICTS+=("${key}"$'\t'"OK"$'\t'"marker absent (AMBER, MISSING_IS_RED=0): $mfile")
      log_line "AMBER ${key} marker absent $mfile"
    fi
    continue
  fi
  # Parse the marker; compute freshness/ok. Python keeps ISO parsing robust.
  verdict="$(MK_FILE="$mfile" MK_KIND="$kind" MK_MAX="$maxage" MK_NOW="$NOW" python3 - <<'PY' 2>/dev/null
import json, os, sys
from datetime import datetime, timezone
f = os.environ["MK_FILE"]; kind = os.environ["MK_KIND"]
maxage = int(os.environ["MK_MAX"]); now = int(os.environ["MK_NOW"])
def iso_epoch(s):
    s = s.strip()
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
try:
    d = json.load(open(f))
except Exception as e:
    print("stale\tunparseable marker: %s" % e); sys.exit(0)
field = "delivered_at" if kind == "report" else "checked_at"
ts = d.get(field)
if not ts:
    print("stale\tmarker missing %s field" % field); sys.exit(0)
try:
    age = now - iso_epoch(ts)
except Exception as e:
    print("stale\tbad %s timestamp: %s" % (field, e)); sys.exit(0)
if kind == "canary" and d.get("ok") is False:
    print("failed\tcanary ok=false (checked %ss ago)" % age); sys.exit(0)
if age > maxage:
    print("stale\t%s is %ss old (> %ss)" % (field, age, maxage)); sys.exit(0)
print("OK\t%s fresh (%ss old)" % (field, age))
PY
)"
  itype="${verdict%%$'\t'*}"; detail="${verdict#*$'\t'}"
  [ -z "$itype" ] && { itype="stale"; detail="marker eval produced no verdict"; }
  VERDICTS+=("${key}"$'\t'"${itype}"$'\t'"${detail}")
done

# --- reconcile verdicts against dedupe state; fire/recover as needed ---------
# STATE_FILE schema: {"incidents": {"<key:type>": {"active":true,"opened_at":N,
# "last_alarm_at":N,"alarm_count":N}}}. Python owns the read-modify-write so the
# dedupe logic is one auditable place; it prints ACTION lines the shell delivers.
ACTIONS="$(STATE_FILE="$STATE_FILE" NOW="$NOW" COOLDOWN_S="$COOLDOWN_S" HOST="$HOST" \
  python3 - "${VERDICTS[@]}" <<'PY' 2>>"$LOG"
import json, os, sys, tempfile
state_file = os.environ["STATE_FILE"]; now = int(os.environ["NOW"])
cooldown = int(os.environ["COOLDOWN_S"]); host = os.environ["HOST"]
try:
    state = json.load(open(state_file))
except Exception:
    state = {}
inc = state.setdefault("incidents", {})
# Parse verdict argv: each arg is "key\ttype\tdetail".
verdicts = {}
for a in sys.argv[1:]:
    parts = a.split("\t", 2)
    if len(parts) < 2: continue
    key, itype = parts[0], parts[1]
    detail = parts[2] if len(parts) > 2 else ""
    verdicts[key] = (itype, detail)
actions = []  # "FIRE|RECOVER\tincident_key\tsubject\tbody"
failing_keys = set()
for key, (itype, detail) in verdicts.items():
    if itype == "OK":
        continue
    ik = "%s:%s" % (key, itype)
    failing_keys.add(ik)
    rec = inc.get(ik)
    subject = "[ARM OUT-OF-BAND ALARM] %s (%s) on %s" % (key, itype, host)
    body = ("ARM out-of-band watchdog fired OFF the bus.\n\n"
            "  incident : %s\n  source   : %s\n  type     : %s\n  detail   : %s\n  host     : %s\n\n"
            "This alarm bypassed the bus on purpose: a canary failure or report-miss "
            "means the bus alarm lane cannot be trusted to deliver.\n\n"
            "Remediate: check the ARM host — is the report synthesis / canary cron running? "
            "Is the bus reachable? See ~/.brisen-lab/arm-alarm.log and the arm-cadence snapshot.\n"
            % (ik, key, itype, detail, host))
    # Each action is ONE tab-delimited line; newlines in the body are escaped to
    # a literal \n so a multi-line body cannot spill into the next record (the
    # shell reader expands them back with printf %b). NOTE: no apostrophes in
    # this heredoc — macOS bash 3.2 mis-scans a lone quote inside a $() heredoc.
    body_esc = body.replace("\n", "\\n")
    if rec is None or not rec.get("active"):
        inc[ik] = {"active": True, "opened_at": now, "last_alarm_at": now, "alarm_count": 1}
        actions.append("FIRE\t%s\t%s\t%s" % (ik, subject, body_esc))
    else:
        # still active: re-alarm only past the cooldown backstop.
        if now - int(rec.get("last_alarm_at", 0)) >= cooldown:
            rec["last_alarm_at"] = now
            rec["alarm_count"] = int(rec.get("alarm_count", 0)) + 1
            subject = "[ARM OUT-OF-BAND ALARM · STILL FAILING] %s (%s) on %s" % (key, itype, host)
            actions.append("FIRE\t%s\t%s\t%s" % (ik, subject, body_esc))
        # else: within cooldown — suppressed (dedupe).
# recoveries: any active incident whose key is no longer failing.
for ik, rec in list(inc.items()):
    if rec.get("active") and ik not in failing_keys:
        rec["active"] = False
        rec["recovered_at"] = now
        subject = "[ARM OUT-OF-BAND RECOVERY] %s on %s" % (ik, host)
        body = ("ARM out-of-band watchdog: incident %s has RECOVERED (marker fresh again). "
                "The key is re-armed.\n" % ik)
        actions.append("RECOVER\t%s\t%s\t%s" % (ik, subject, body.replace("\n", "\\n")))
# atomic state write.
try:
    d = os.path.dirname(state_file) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".arm_alarm_state.")
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_file)
except Exception as e:
    sys.stderr.write("arm-alarm state write failed: %s\n" % e)
sys.stdout.write("\n".join(actions))
PY
)"

# --- deliver the actions out-of-band ----------------------------------------
fired=0; recovered=0
if [ -n "$ACTIONS" ]; then
  while IFS=$'\t' read -r action ik subject body; do
    [ -z "$action" ] && continue
    # body was newline-encoded by python via literal \n in the string — the
    # tab-split keeps it intact on one field; expand \n for delivery.
    real_body="$(printf '%b' "$body")"
    send_email "$subject" "$real_body"
    send_notification "ARM alarm" "$subject"
    if [ "$action" = "FIRE" ]; then
      fired=$((fired+1)); log_line "FIRE $ik :: $subject"
    else
      recovered=$((recovered+1)); log_line "RECOVER $ik :: $subject"
    fi
  done <<< "$ACTIONS"
fi

if [ "$fired" -eq 0 ] && [ "$recovered" -eq 0 ]; then
  log_line "OK no incidents (sources=${#SOURCES[@]})"
fi

exit 0   # always 0 on a completed run — tolerance; freshness is the signal
