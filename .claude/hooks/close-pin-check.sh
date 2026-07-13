#!/usr/bin/env bash
# Close-pin gate — CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1 (P-E23.1).
#
# WHY: rollover state loss (E23). A session that closes WITHOUT writing a
# checkpoint/pin loses its live matter state; the Director becomes the fleet's
# memory (bb-desk lost two signing-blocker risks at rollover, 2026-07-12). A
# voluntary "please pin before you go" decays like every other prompt rule (E3).
# This gate makes persist-before-close STRUCTURAL for any seat holding live state.
#
# HOOK-EVENT CAPABILITY (R1, verified against code.claude.com/docs/en/hooks 2026-07-13):
#   - Stop CAN block (decision:block) AND CAN show systemMessage. Fires at the end
#     of EACH assistant turn — it cannot tell "this is the last turn / a close".
#   - SessionEnd fires on real session termination (reason: clear/logout/
#     prompt_input_exit/resume/other; a terminal window-close maps to logout) but
#     its output is IGNORED — it can neither block nor show a message. Side-effect
#     only.
#   => A HARD BLOCK exactly at close is impossible in this harness: the event that
#      detects close (SessionEnd) can't act, and the event that can act (Stop)
#      can't detect close. So this gate is honest about that:
#        * Stop  + dirty  -> LOUD warn via systemMessage, at-most-once per session
#          (marker-gated so it doesn't nag every turn). Optional block-once only if
#          the seat opted in via close_pin_block_on_stop (default OFF — blocking a
#          non-final Stop would trap mid-arc work, the context-hook self-feed trap).
#        * SessionEnd + dirty -> the only thing that works at true close is a
#          SIDE EFFECT: for a non-interactive worker, auto-write an UNVERIFIED-AUTO
#          STUB checkpoint (pointers only, R3). Interactive seats can't be warned
#          here (output ignored), so we drop a breadcrumb to a warn-log — never a
#          silent skip, never a fabricated full pin.
#
# CONTRACT (matches context-threshold-check.sh):
#   - Always exit 0. Fault-tolerant on every path. Drains stdin (no SIGPIPE).
#   - Enforces the pin-protocol LIGHT floor as the minimum content contract.
#   - Fail-loud: a seat that cannot persist surfaces the gap by name, never a
#     silent pass.

PAYLOAD="$(cat 2>/dev/null || true)"

_HOOK_SRC="${BASH_SOURCE[0]:-$0}"
CLOSE_PIN_HOOK_DIR="$(cd "$(dirname "$_HOOK_SRC")" >/dev/null 2>&1 && pwd -P || true)"

CLOSE_PIN_PAYLOAD="$PAYLOAD" CLOSE_PIN_HOOK_DIR="$CLOSE_PIN_HOOK_DIR" \
BAKER_ROLE="${BAKER_ROLE:-}" python3 - <<'PY'
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Parse the payload FIRST (stdlib only) so that even a broken predicate import can
# still be surfaced against the right event (blocker #1: the fail-loud gate must
# not itself fail silent).
try:
    payload = json.loads(os.environ.get("CLOSE_PIN_PAYLOAD", "") or "{}")
except json.JSONDecodeError:
    raise SystemExit(0)
if not isinstance(payload, dict):
    raise SystemExit(0)

event = payload.get("hook_event_name") or ""
cwd = payload.get("cwd") or os.getcwd()
transcript = payload.get("transcript_path")
session_id = payload.get("session_id") or ""
role = (os.environ.get("BAKER_ROLE") or "").strip()

cwd_p = Path(str(cwd)).expanduser()

hook_dir = os.environ.get("CLOSE_PIN_HOOK_DIR") or str(Path(__file__).resolve().parent)
if hook_dir and hook_dir not in sys.path:
    sys.path.insert(0, hook_dir)
try:
    import live_state_predicate
except Exception as _imp_exc:
    # The shared predicate is unimportable — this gate cannot evaluate. It must NOT
    # exit silent (that is the exact fail-loud failure codex flagged, blocker #1).
    # Surface the broken gate by the loudest channel the event allows, then exit 0
    # (never crash the session).
    _why = ("[close-pin] GATE DOWN: live_state_predicate could not be imported "
            "({}). This seat's close-pin enforcement is NOT running — persist your "
            "state manually (pin-protocol LIGHT floor) and report the broken hook to "
            "your dispatching superior.".format(_imp_exc))
    if event == "Stop":
        print(json.dumps({"systemMessage": _why}))
    else:
        # SessionEnd/other: output is ignored by the harness, so leave a durable
        # breadcrumb naming the failure (audit surface), never a silent skip.
        try:
            d = cwd_p / "briefs" / "_checkpoints"
            d.mkdir(parents=True, exist_ok=True)
            d.joinpath(".close-pin-failed").write_text(
                "PREDICATE IMPORT FAILED seat={} event={}: {}\n".format(
                    role or "?", event or "?", _imp_exc))
        except OSError:
            pass
    raise SystemExit(0)


# ---- config: settings.local.json (per-seat) then settings.json (base) ----------
def _settings_docs() -> list:
    docs = []
    for name in ("settings.local.json", "settings.json"):
        p = cwd_p / ".claude" / name
        try:
            docs.append(json.loads(p.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return docs


def _cfg(key, default=None):
    for d in _settings_docs():
        if key in d:
            return d[key]
        nested = d.get("close_pin") if isinstance(d.get("close_pin"), dict) else {}
        short = key[len("close_pin_"):] if key.startswith("close_pin_") else key
        if short in nested:
            return nested[short]
    return default


# ---- seat interactivity ---------------------------------------------------------
# Non-interactive = orchestrator-spawned workers whose checkpoint content is
# mechanically derivable (brief mailbox + git). Default: b-codes. Everyone else is
# interactive (a human closes the window; E17 — cannot be force-terminated). A seat
# can override with close_pin_interactive true/false.
def _is_interactive() -> bool:
    override = _cfg("close_pin_interactive")
    if isinstance(override, bool):
        return override
    return not bool(re.match(r"b\d+$", role or "", re.IGNORECASE))


verdict = live_state_predicate.evaluate(str(cwd_p), role, transcript)
if not verdict.get("dirty"):
    raise SystemExit(0)  # clean seat: nothing to persist.

reasons = verdict.get("reasons") or []
reason_txt = "; ".join(reasons) if reasons else "live state present"

LIGHT_FLOOR_WORKER = (
    "pin-protocol LIGHT floor for a worker = write/refresh "
    "briefs/_checkpoints/<BRIEF_ID>.checkpoint.md (5 fields: brief id, what's done, "
    "what's left, key paths/commits, next concrete step), commit + push it, post the "
    "respawn request to your dispatching superior."
)
LIGHT_FLOOR_SEAT = (
    "pin-protocol LIGHT floor = (1) update PINNED §A (what shipped + top next actions "
    "+ pointers), (2) append an activity-log entry, (3) append an audit-log entry for "
    "any Tier-B action. Then close."
)


def _emit_stop(text: str, block: bool) -> None:
    out = {"systemMessage": text}
    if block:
        out["decision"] = "block"
        out["reason"] = text
    print(json.dumps(out))


def _marker(suffix: str) -> Path:
    base = str(transcript) if transcript else str(cwd_p / f".close-pin-{session_id or 'nosess'}")
    return Path(base + suffix)


# =================================================================================
# Stop: can warn + can block. Warn at-most-once per session; block only if opted in.
# =================================================================================
if event == "Stop":
    marker = _marker(".close-pin-warned")
    if marker.exists():
        raise SystemExit(0)  # already nudged this session; don't nag every turn.
    floor = LIGHT_FLOOR_SEAT if _is_interactive() else LIGHT_FLOOR_WORKER
    try:
        marker.write_text(reason_txt[:500])
        marked = True
    except OSError:
        marked = False  # if we can't mark, do not block (would loop forever).
    want_block = bool(_cfg("close_pin_block_on_stop", False)) and marked
    _emit_stop(
        "[close-pin] You are holding live matter state ({}) and have NOT checkpointed "
        "this session. Rollover would lose it (E23). Persist before you close: {} "
        "This is a one-time reminder this session.".format(reason_txt, floor),
        block=want_block,
    )
    raise SystemExit(0)


# =================================================================================
# SessionEnd: output is IGNORED (can't warn, can't block). Side effect only.
#   non-interactive worker -> auto-write an UNVERIFIED-AUTO STUB checkpoint (R3).
#   interactive seat        -> drop a warn-log breadcrumb (never silent, never a
#                              fabricated pin).
# =================================================================================
if event == "SessionEnd":
    reason_field = payload.get("reason") or "other"

    def _git(*args) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(cwd_p), *args],
                capture_output=True, text=True, timeout=8,
            )
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:
            return ""

    def _brief_id() -> str:
        mb = None
        for r in reasons:
            m = re.search(r"active brief mailbox: (.+)$", r)
            if m:
                mb = m.group(1).strip()
                break
        if mb and Path(mb).exists():
            try:
                head = Path(mb).read_text(errors="ignore")[:4000]
            except OSError:
                head = ""
            m = re.search(r"^\s*brief_id\s*:\s*(\S+)", head, re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1)
        return "UNKNOWN-{}".format(role or "seat")

    if _is_interactive():
        # Cannot warn (SessionEnd output ignored); leave a durable breadcrumb so the
        # gap is never silent. No fabricated pin (R3).
        try:
            logdir = cwd_p / "briefs" / "_checkpoints"
            logdir.mkdir(parents=True, exist_ok=True)
            log = logdir / ".close-pin-warnlog"
            with log.open("a") as fh:
                fh.write("CLOSE-WITHOUT-PIN seat={} reason={} live={} at_session={}\n".format(
                    role or "?", reason_field, reason_txt, session_id or "?"))
        except OSError:
            pass  # fail-open: a breadcrumb we can't write is not worth crashing on.
        raise SystemExit(0)

    # Non-interactive worker: auto-write the stub (pointers only, clearly marked).
    brief_id = _brief_id()
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", brief_id) or "seat"
    cdir = cwd_p / "briefs" / "_checkpoints"
    stub = cdir / f"{safe}.autostub.checkpoint.md"
    head_short = _git("rev-parse", "--short", "HEAD")
    head_subj = _git("log", "-1", "--pretty=%s")
    dirty_files = _git("status", "--short")
    body = (
        "# {bid} — UNVERIFIED-AUTO STUB (close-pin, SessionEnd)\n\n"
        "> AUTO-GENERATED at session close by close-pin-check.sh because this worker\n"
        "> held live state ({reasons}) and had NOT written a fresh checkpoint. This is\n"
        "> a POINTER STUB, not a hand-written pin — the successor MUST verify against\n"
        "> git log + the mailbox before trusting it. Do NOT treat it as a completed\n"
        "> handover.\n\n"
        "- status: UNVERIFIED-AUTO — successor to confirm or supersede\n"
        "- seat: {role}\n"
        "- close reason: {reason}\n"
        "- brief mailbox: see briefs/_tasks/ (parsed brief_id: {bid})\n"
        "- last commit: {head} {subj}\n"
        "- uncommitted at close:\n{dirty}\n\n"
        "## Next concrete step (successor)\n"
        "- Read the mailbox + `git log`/`git status`, reconstruct real state, then\n"
        "  write the proper checkpoint and delete this stub. {floor}\n"
    ).format(
        bid=brief_id,
        reasons=reason_txt,
        role=role or "?",
        reason=reason_field,
        head=head_short or "(git unavailable)",
        subj=head_subj,
        dirty=("\n".join("    " + ln for ln in dirty_files.splitlines()) or "    (none / git unavailable)"),
        floor=LIGHT_FLOOR_WORKER,
    )
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        # Never clobber a hand-written checkpoint; the .autostub. infix guarantees a
        # distinct name, and we only reach here when no fresh checkpoint exists.
        stub.write_text(body)
    except OSError as exc:
        # Fail-loud: record the failure by name so it isn't a silent miss.
        try:
            (cdir if cdir.exists() else cwd_p).joinpath(".close-pin-failed").write_text(
                "AUTO-STUB WRITE FAILED for {}: {}\n".format(brief_id, exc))
        except OSError:
            pass
    raise SystemExit(0)

# Any other event: no-op.
raise SystemExit(0)
PY
exit 0
