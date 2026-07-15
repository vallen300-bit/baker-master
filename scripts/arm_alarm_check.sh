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
#   semantic.json {"schema":"semantic_delivery_verdict_v1","evaluated_at":"<iso>",
#                  "semantic_ok": true, ...}          — b2's SEMANTIC_DELIVERY_EVALUATOR_1
#                  (#10544) writes this; consumed here as a 3rd kind (silent-skip
#                  until enforced — see SEMANTIC_ENFORCE / MISSING-MARKER POLICY).
# The SOURCES array is the single extension point (mirrors arm_cadence_poll.sh):
# add "<key> <marker-file> <max_age_s> <kind>" rows as new out-of-band signals land;
# a NEW kind also needs a matching branch in the freshness eval (field + ok clause).
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
# NOW is overridable (ARM_ALARM_NOW) ONLY so the test suite can advance the clock
# deterministically to exercise the bounded-backoff retry schedule; production
# never sets it.
NOW="${ARM_ALARM_NOW:-$(date +%s)}"

ALARM_DIR="${ARM_ALARM_DIR:-$HOME/.brisen-lab/arm-alarm}"
MARKER_DIR="${ARM_ALARM_MARKER_DIR:-$ALARM_DIR/markers}"
STATE_FILE="${ARM_ALARM_STATE:-$ALARM_DIR/state.json}"
LOG="${ARM_ALARM_LOG:-$HOME/.brisen-lab/arm-alarm.log}"

# Out-of-band email recipient. Default flagged for lead review (see ship report):
# the point of THIS path is to reach a human when the bus is down, so it targets
# the Director's ops address, overridable per host.
EMAIL_TO="${ARM_ALARM_EMAIL_TO:-dvallen@brisengroup.com}"

# PER-KIND RECIPIENT ROUTING (ARM_ALARM_RECIPIENT_SPLIT_1). Each alarm is routed
# by incident source: the delivery path reads ARM_ALARM_EMAIL_TO_<SOURCE> (upper-
# cased source, e.g. ARM_ALARM_EMAIL_TO_SEMANTIC) and, when set + non-blank, sends
# to that address; otherwise it falls back to EMAIL_TO. This lets routine enforced
# semantic red retarget to lead while report/canary emergencies stay on the
# Director ops address — the prerequisite for arming ARM_ALARM_SEMANTIC_ENFORCE=1
# without paging the Director on routine semantic delivery (lead ruling #11674/#11679).
# The routing map is NOT hardcoded here; it is applied as envs at install.
#
# PRODUCTION ROUTING (deploy note, AC7):
#   source    class      env set at install               -> recipient
#   semantic  routine    ARM_ALARM_EMAIL_TO_SEMANTIC=<lead addr>  -> lead
#   report    emergency  (unset -> fallback)              -> EMAIL_TO (Director)
#   canary    emergency  (unset -> fallback)              -> EMAIL_TO (Director)
#   cadence / future     (unset -> fallback)              -> EMAIL_TO (Director)
# DEPLOY: the launchd plist EnvironmentVariables dict must carry
# ARM_ALARM_EMAIL_TO_SEMANTIC=<lead address> (launchd env is inherited by this
# script and its python3 delivery child). The installer regenerates the plist
# from scripts/launchd/com.baker.arm-alarm.plist on every reinstall, so to survive
# a fleet reinstall the semantic env belongs in that template's EnvironmentVariables
# (installer-owned change, tracked separately — see build-complete report to deputy).

# never-seen marker => RED? default 0 (AMBER) so install day does not false-page.
MISSING_IS_RED="${ARM_ALARM_MISSING_IS_RED:-0}"
# re-alarm backstop for a still-active incident.
COOLDOWN_S="${ARM_ALARM_COOLDOWN_S:-21600}"   # 6h

# SEMANTIC consumer gate (rider (a), lead #10630). b2's SEMANTIC_DELIVERY_
# EVALUATOR_1 (#10544) is the producer of semantic.json; it may not be live/
# installed yet. Until it is, an ABSENT semantic.json is a SILENT-SKIP — not
# AMBER, not RED, not even a log line — so this job neither false-pages nor
# log-spams for a producer that has not shipped. Flip ARM_ALARM_SEMANTIC_ENFORCE=1
# once b2's evaluator is guaranteed live; an absent semantic.json then follows the
# normal MISSING_IS_RED policy like every other kind. A PRESENT semantic.json is
# ALWAYS evaluated regardless of this flag (defensive: if the file exists, the
# producer is live). Coordinate the enforce-flip with b2 on evaluator cadence.
SEMANTIC_ENFORCE="${ARM_ALARM_SEMANTIC_ENFORCE:-0}"
# Marker-version guard (coordinated with b2 #10544): supported semantic marker
# schema. A PRESENT marker whose "schema" is an unknown major version is skipped
# (no page) rather than mis-evaluated — a contract we cannot interpret must never
# false-fire. A missing "schema" field is tolerated (evaluated on the v1 fields).
SEMANTIC_SCHEMA_PREFIX="${ARM_ALARM_SEMANTIC_SCHEMA_PREFIX:-semantic_delivery_verdict_v1}"

# SOURCES: "<key> <marker-file> <max_age_s> <kind>". kind ∈ {report, canary,
# semantic, cadence}.
#   report:   stale if now-delivered_at > max_age (default 26h = 24h + 2h grace).
#   canary:   stale if now-checked_at   > max_age OR the marker's ok flag is false.
#   semantic: stale if now-evaluated_at > max_age OR the marker semantic_ok is false
#             (SEMANTIC_DELIVERY_EVALUATOR_1 #10544 — b2 writes the marker, this job
#             consumes it; absent-marker handling is gated by SEMANTIC_ENFORCE above).
#   cadence: stale if now-captured_at > max_age OR the snapshot carries
#            health=db_unreachable. A fresh health=degraded snapshot is recorded
#            but does not page: parseable non-200 is not a connection failure.
# Extension point — add rows here as new out-of-band signals land. A NEW kind needs
# a matching branch in the freshness eval below (field map + any ok-flag clause).
SOURCES=(
  "report ${MARKER_DIR}/report.json ${ARM_ALARM_REPORT_MAX_AGE_S:-93600} report"
  "canary ${MARKER_DIR}/canary.json ${ARM_ALARM_CANARY_MAX_AGE_S:-93600} canary"
  "semantic ${MARKER_DIR}/semantic.json ${ARM_ALARM_SEMANTIC_MAX_AGE_S:-93600} semantic"
  "cadence ${ARM_ALARM_CADENCE_SNAPSHOT:-$HOME/.brisen-lab/arm-cadence/latest.json} ${ARM_ALARM_CADENCE_MAX_AGE_S:-5400} cadence"
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

# --- out-of-band delivery -----------------------------------------------------
# DELIVERY TRUTH (codex G2 #10455): delivery is NOT a fire-and-forget side effect
# of a shell loop that runs after state has already been committed. It lives
# INSIDE the reconcile program below, so an incident is only marked "alarmed"
# (and future alarms suppressed) after at least one channel ACTUALLY succeeds.
# The two channels — Outlook.app email (Pattern A) + a macOS notification — sit
# behind a small transport adapter (env ARM_ALARM_SEND_CMD / ARM_ALARM_NOTIFY_CMD
# override the real senders; #10425 asked for the seam so push can be added later
# without touching trigger/dedupe). Neither channel touches the bus.

# --- evaluate every source into a verdict -----------------------------------
# Emits, per source, one line: "<key>\t<incident-type|OK>\t<detail>".
#   incident-type: stale | failed | missing | db_unreachable | OK
declare -a VERDICTS=()
for entry in "${SOURCES[@]}"; do
  # shellcheck disable=SC2086
  set -- $entry
  key="$1"; mfile="$2"; maxage="$3"; kind="$4"
  if [ ! -f "$mfile" ]; then
    # rider (a): semantic producer (b2 #10544) not guaranteed live yet. Until
    # SEMANTIC_ENFORCE=1, an absent semantic.json is a TRUE silent skip — no
    # verdict, no AMBER, no log line — so it neither pages nor spams pre-ship.
    if [ "$kind" = "semantic" ] && [ "$SEMANTIC_ENFORCE" != "1" ]; then
      continue
    fi
    if [ "$MISSING_IS_RED" = "1" ]; then
      VERDICTS+=("${key}"$'\t'"missing"$'\t'"marker never written: $mfile")
    else
      VERDICTS+=("${key}"$'\t'"OK"$'\t'"marker absent (AMBER, MISSING_IS_RED=0): $mfile")
      log_line "AMBER ${key} marker absent $mfile"
    fi
    continue
  fi
  if [ "$kind" = "semantic" ] && [ "$SEMANTIC_ENFORCE" != "1" ]; then continue; fi
  # Parse the marker; compute freshness/ok. Python keeps ISO parsing robust.
  verdict="$(MK_FILE="$mfile" MK_KIND="$kind" MK_MAX="$maxage" MK_NOW="$NOW" \
    MK_SCHEMA_PREFIX="$SEMANTIC_SCHEMA_PREFIX" python3 - <<'PY' 2>/dev/null
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
# marker-version guard (semantic only): an unknown schema major is skipped, not
# paged — a contract we cannot interpret must never false-fire. Missing schema is
# tolerated (evaluated on the v1 fields).
if kind == "semantic":
    schema = d.get("schema")
    prefix = os.environ.get("MK_SCHEMA_PREFIX", "semantic_delivery_verdict_v1")
    if schema is not None and not str(schema).startswith(prefix):
        print("OK\tsemantic schema %r unknown (want %s*): skipped, not paged"
              % (schema, prefix)); sys.exit(0)
if kind == "cadence":
    health = d.get("health")
    source_health = [
        value.get("health")
        for value in (d.get("sources") or {}).values()
        if isinstance(value, dict)
    ]
    if health == "db_unreachable" or "db_unreachable" in source_health:
        print("db_unreachable\tcadence health=db_unreachable")
        sys.exit(0)
field = {"report": "delivered_at", "canary": "checked_at",
         "semantic": "evaluated_at", "cadence": "captured_at"}.get(kind, "checked_at")
ts = d.get(field)
if not ts:
    print("stale\tmarker missing %s field" % field); sys.exit(0)
try:
    age = now - iso_epoch(ts)
except Exception as e:
    print("stale\tbad %s timestamp: %s" % (field, e)); sys.exit(0)
if kind == "canary" and d.get("ok") is False:
    print("failed\tcanary ok=false (checked %ss ago)" % age); sys.exit(0)
if kind == "semantic" and d.get("semantic_ok") is False:
    print("failed\tsemantic_ok=false (evaluated %ss ago)" % age); sys.exit(0)
if age > maxage:
    print("stale\t%s is %ss old (> %ss)" % (field, age, maxage)); sys.exit(0)
if kind == "cadence" and d.get("health") == "degraded":
    print("OK\tcadence health=degraded (%ss old); non-200 is not db_unreachable" % age)
    sys.exit(0)
print("OK\t%s fresh (%ss old)" % (field, age))
PY
)"
  itype="${verdict%%$'\t'*}"; detail="${verdict#*$'\t'}"
  [ -z "$itype" ] && { itype="stale"; detail="marker eval produced no verdict"; }
  VERDICTS+=("${key}"$'\t'"${itype}"$'\t'"${detail}")
done

# --- reconcile + deliver (delivery-truth: state committed only on real send) --
# One Python program owns the whole read -> decide -> DELIVER -> commit cycle, so
# an incident is marked "alarmed" (and dedupe-suppressed) ONLY after >=1 channel
# actually succeeds (codex G2 #10455). It prints one log line per outcome, which
# the shell appends to the log. NOTE: no apostrophes inside this heredoc — macOS
# bash 3.2 mis-scans a lone quote inside a $() heredoc.
#
# STATE_FILE schema per incident key "<source>:<type>":
#   active            bool  — a DELIVERED alarm is currently outstanding
#   delivery_pending  bool  — an alarm is due but has NOT yet been delivered
#   opened_at, last_alarm_at (last SUCCESSFUL delivery), alarm_count (successes)
#   send_fail_count, next_retry_at — bounded-backoff retry of a failed delivery
OUT="$(STATE_FILE="$STATE_FILE" NOW="$NOW" COOLDOWN_S="$COOLDOWN_S" HOST="$HOST" \
  EMAIL_TO="$EMAIL_TO" \
  ARM_ALARM_BACKOFF_BASE_S="${ARM_ALARM_BACKOFF_BASE_S:-60}" \
  ARM_ALARM_BACKOFF_CAP_S="${ARM_ALARM_BACKOFF_CAP_S:-1800}" \
  python3 - "${VERDICTS[@]}" <<'PY' 2>>"$LOG"
import json, os, sys, subprocess, tempfile
state_file = os.environ["STATE_FILE"]; now = int(os.environ["NOW"])
cooldown = int(os.environ["COOLDOWN_S"]); host = os.environ["HOST"]
email_to = os.environ.get("EMAIL_TO", "")
bk_base = int(os.environ.get("ARM_ALARM_BACKOFF_BASE_S", "60"))
bk_cap  = int(os.environ.get("ARM_ALARM_BACKOFF_CAP_S", "1800"))

# --- per-kind recipient resolution (ARM_ALARM_RECIPIENT_SPLIT_1) -------------
# Route the alarm by incident source. source = the part of the incident key
# before ":" (e.g. "semantic", "report", "canary"). ARM_ALARM_EMAIL_TO_<SOURCE>
# when set (and non-blank) wins; otherwise fall back to EMAIL_TO. Routine
# semantic red retargets to lead; report/canary stay on the Director ops address
# (routing map applied via envs in the launchd plist at install, NOT hardcoded).
# Resolution is deterministic on source, so FIRE / STILL-FAILING / RECOVERY for
# the same incident always land on the SAME recipient (lifecycle consistency).
def resolve_recipient(source):
    env_key = "ARM_ALARM_EMAIL_TO_" + source.upper()
    to = os.environ.get(env_key, "").strip()
    if to:
        return to, env_key
    return email_to, "EMAIL_TO"

def resolve_log(ik, source):
    # Fail-loud: every resolution emits one log line; never a silent no-send.
    to, rkey = resolve_recipient(source)
    if rkey == "EMAIL_TO":
        logs.append("resolved %s -> EMAIL_TO (no ARM_ALARM_EMAIL_TO_%s)" % (ik, source.upper()))
    else:
        logs.append("resolved %s -> %s" % (ik, rkey))
    return to

# --- transport adapter: each channel returns True ONLY on a real success ------
def _run(cmd, extra):
    env = dict(os.environ); env.update(extra)
    try:
        r = subprocess.run(["bash", "-c", cmd], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False

def send_email(subject, body, to):
    cmd = os.environ.get("ARM_ALARM_SEND_CMD")
    if cmd:
        return _run(cmd, {"ARM_ALARM_SUBJECT": subject, "ARM_ALARM_BODY": body,
                          "ARM_ALARM_TO": to})
    # Real path: Outlook.app autonomous send (Pattern A). returncode is the truth
    # signal — a non-zero osascript exit (Outlook down / auth broken / send error)
    # means the channel FAILED (the check=False bug codex flagged is fixed here).
    def esc(s): return s.replace("\\", "\\\\").replace('"', '\\"')
    scpt = (
        'tell application "Microsoft Outlook"\n'
        '\tset m to make new outgoing message with properties {subject:"%s", content:"%s"}\n'
        '\tmake new recipient at m with properties {email address:{address:"%s"}}\n'
        '\tsend m\n'
        'end tell\n' % (esc(subject), esc(body), esc(to)))
    try:
        r = subprocess.run(["osascript", "-e", scpt],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False

def send_notify(title, message):
    cmd = os.environ.get("ARM_ALARM_NOTIFY_CMD")
    if cmd:
        return _run(cmd, {"ARM_ALARM_TITLE": title, "ARM_ALARM_MSG": message})
    try:
        t = title.replace('"', '\\"'); m = message.replace('"', '\\"')
        r = subprocess.run(["osascript", "-e",
                            'display notification "%s" with title "%s"' % (m, t)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False

def deliver(subject, body, to):
    # Try BOTH channels; success = at least one delivered. Returns (email, notify).
    e = send_email(subject, body, to)
    n = send_notify("ARM alarm", subject)
    return e, n

def backoff(fails):
    return min(bk_base * (2 ** max(0, fails - 1)), bk_cap)

try:
    state = json.load(open(state_file))
except Exception:
    state = {}
inc = state.setdefault("incidents", {})

verdicts = {}
for a in sys.argv[1:]:
    parts = a.split("\t", 2)
    if len(parts) < 2: continue
    verdicts[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")

logs = []
failing = set()
summary_parts = []
for key, (itype, detail) in verdicts.items():
    if itype == "OK":
        continue
    if itype == "db_unreachable":
        summary_parts.append("%s(%s)" % (itype, key))
    else:
        summary_parts.append("%s:%s" % (key, itype))
red_summary = "RED: %s" % ", ".join(summary_parts) if summary_parts else "RED"
for key, (itype, detail) in verdicts.items():
    if itype == "OK":
        continue
    ik = "%s:%s" % (key, itype); failing.add(ik)
    rec = inc.get(ik) or {}
    active = bool(rec.get("active")); pending = bool(rec.get("delivery_pending"))
    subject = "[ARM OUT-OF-BAND ALARM] %s on %s" % (red_summary, host)
    body = ("ARM out-of-band watchdog fired OFF the bus.\n\n"
            "  red      : %s\n  incident : %s\n  source   : %s\n  type     : %s\n  detail   : %s\n  host     : %s\n\n"
            "This alarm bypassed the bus on purpose: a canary failure or report-miss "
            "means the bus alarm lane cannot be trusted to deliver.\n\n"
            "Remediate: check the ARM host - is report synthesis / the canary cron running? "
            "Is the bus reachable? See ~/.brisen-lab/arm-alarm.log and the arm-cadence snapshot.\n"
            % (red_summary, ik, key, itype, detail, host))
    # Is an alarm delivery DUE this poll?
    due = False; reason = ""
    if not active and not pending:
        due = True; reason = "new"
    elif pending:
        # a prior delivery FAILED; retry only once the bounded backoff has elapsed
        if now >= int(rec.get("next_retry_at", 0)):
            due = True; reason = "retry"
    elif active:
        # delivered alarm still outstanding; re-alarm only past the cooldown
        if now - int(rec.get("last_alarm_at", 0)) >= cooldown:
            due = True; reason = "still-failing"
    if not due:
        inc[ik] = rec
        continue
    if reason == "still-failing":
        subject = "[ARM OUT-OF-BAND ALARM STILL-FAILING] %s on %s" % (red_summary, host)
    # Route by incident source (semantic->lead, report/canary->EMAIL_TO). Resolve
    # ONCE at first fire and PIN the recipient on the incident record, so FIRE +
    # STILL-FAILING + RECOVERY all reach the same address even if the per-kind env
    # is changed mid-incident (e.g. a fleet reinstall while an incident is open).
    # Re-resolving live each poll would let such a change misroute a later
    # STILL-FAILING/RECOVERY to the Director (the rider #11679 misfire).
    source = ik.split(":", 1)[0]
    to = rec.get("recipient")
    if to:
        logs.append("resolved %s -> %s (pinned for lifecycle)" % (ik, to))
    else:
        to = resolve_log(ik, source)
    rec["recipient"] = to
    e_ok, n_ok = deliver(subject, body, to)
    if e_ok or n_ok:
        # DELIVERED — now (and only now) mark it alarmed + advance cooldown.
        rec.update({"active": True, "delivery_pending": False,
                    "opened_at": rec.get("opened_at", now),
                    "last_alarm_at": now,
                    "alarm_count": int(rec.get("alarm_count", 0)) + 1,
                    "send_fail_count": 0})
        rec.pop("next_retry_at", None)
        logs.append("FIRE %s (%s) delivered email=%s notify=%s :: %s"
                    % (ik, reason, e_ok, n_ok, subject))
    else:
        # NOT delivered — do NOT mark alarmed, do NOT advance cooldown; retry with
        # bounded backoff so a broken sender keeps being attempted (fail-loud).
        fails = int(rec.get("send_fail_count", 0)) + 1
        rec.update({"delivery_pending": True, "opened_at": rec.get("opened_at", now),
                    "send_fail_count": fails, "next_retry_at": now + backoff(fails)})
        logs.append("SEND-FAIL %s (%s) both channels failed; retry in %ss (fail#%d)"
                    % (ik, reason, backoff(fails), fails))
    inc[ik] = rec

# recoveries: incidents whose key is no longer failing.
for ik, rec in list(inc.items()):
    if ik in failing:
        continue
    if rec.get("active"):
        # a DELIVERED alarm recovered -> send a recovery notice (best-effort).
        # Reuse the recipient PINNED at fire, so a semantic recovery lands on lead
        # even if the per-kind env changed since (rider #11679). Fall back to a
        # fresh resolve only for a pre-pin incident (older state file).
        source = ik.split(":", 1)[0]
        to = rec.get("recipient")
        if to:
            logs.append("resolved %s -> %s (pinned for lifecycle)" % (ik, to))
        else:
            to = resolve_log(ik, source)
        subject = "[ARM OUT-OF-BAND RECOVERY] %s on %s" % (ik, host)
        body = ("ARM out-of-band watchdog: incident %s has RECOVERED (marker fresh again). "
                "The key is re-armed.\n" % ik)
        e_ok, n_ok = deliver(subject, body, to)
        logs.append("RECOVER %s delivered email=%s notify=%s" % (ik, e_ok, n_ok))
        # clear the pin on recovery so a future re-fire resolves fresh (env may
        # have legitimately changed by then).
        rec.update({"active": False, "delivery_pending": False, "recovered_at": now,
                    "send_fail_count": 0})
        rec.pop("next_retry_at", None); rec.pop("recipient", None)
        inc[ik] = rec
    elif rec.get("delivery_pending"):
        # an alarm that was NEVER delivered recovered -> clear silently (a recovery
        # for an alarm the human never saw would only confuse).
        rec.update({"delivery_pending": False, "recovered_at": now, "send_fail_count": 0})
        rec.pop("next_retry_at", None); rec.pop("recipient", None); inc[ik] = rec
        logs.append("CLEAR-UNDELIVERED %s (alarm never delivered; cleared on recovery)" % ik)

try:
    d = os.path.dirname(state_file) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".arm_alarm_state.")
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_file)
except Exception as e:
    logs.append("STATE-WRITE-FAIL %s" % e)

sys.stdout.write("\n".join(logs))
PY
)"

# --- log the outcome lines ---------------------------------------------------
if [ -n "$OUT" ]; then
  while IFS= read -r line; do [ -n "$line" ] && log_line "$line"; done <<< "$OUT"
else
  log_line "OK no incidents (sources=${#SOURCES[@]})"
fi

exit 0   # always 0 on a completed run — tolerance; freshness is the signal
