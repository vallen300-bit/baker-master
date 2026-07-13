#!/usr/bin/env bash
# Session-open orientation contract — CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1 (P-E23.2).
#
# WHY: a fresh session that checks ONLY the bus and sees 0-unacked concludes
# "clear" — but pending work lives in the brief, OPERATING.md, armed deadlines, and
# the last handover, not on the bus (a message channel, not the state store). "Bus
# clean" proved nothing about pending matter state, and bb-desk opened blind to two
# live signing-blocker risks (E23b, 2026-07-12). This SessionStart hook makes
# orientation read the seat's OWN state sources and surface pending work, so a clean
# bus can never read as "nothing pending". Composes WITH the bus-drain SessionStart
# check (adds to it, never replaces it).
#
# CONTRACT (matches session-start-role.sh):
#   - Always exit 0. Never block. Fault-tolerant on every path. Drains stdin.
#   - Emits an additionalContext JSON envelope Claude injects at session start.
#   - R2 BUDGET: summary is <=30 lines, pending-items-only, POINTER-STYLE (path +
#     one-line hook, no content dumps). A truly-clean seat emits ONE line
#     ("checked N sources, none pending") — the fail-loud inverse of a silent empty.

PAYLOAD="$(cat 2>/dev/null || true)"

_HOOK_SRC="${BASH_SOURCE[0]:-$0}"
ORIENT_HOOK_DIR="$(cd "$(dirname "$_HOOK_SRC")" >/dev/null 2>&1 && pwd -P || true)"

ORIENT_PAYLOAD="$PAYLOAD" ORIENT_HOOK_DIR="$ORIENT_HOOK_DIR" \
BAKER_ROLE="${BAKER_ROLE:-}" HOME_DIR="${HOME}" python3 - <<'PY'
import json
import os
import re
import sys
from pathlib import Path

hook_dir = os.environ.get("ORIENT_HOOK_DIR") or str(Path(__file__).resolve().parent)
if hook_dir and hook_dir not in sys.path:
    sys.path.insert(0, hook_dir)
try:
    import live_state_predicate as lsp  # reuse mailbox/pinned readers (no drift)
except Exception:
    lsp = None

MAX_LINES = 30

try:
    payload = json.loads(os.environ.get("ORIENT_PAYLOAD", "") or "{}")
except json.JSONDecodeError:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

event = payload.get("hook_event_name") or "SessionStart"
cwd = payload.get("cwd") or os.getcwd()
role = (os.environ.get("BAKER_ROLE") or "").strip()
home = Path(os.environ.get("HOME_DIR") or os.path.expanduser("~"))
cwd_p = Path(str(cwd)).expanduser()


def _emit(text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": event, "additionalContext": text}}))


# Each check appends to `pending` (a surfaced item) and always increments `checked`
# (so "none pending" can report the denominator — the fail-loud inverse of silent).
pending: list[str] = []
checked = 0


def _first_line(text: str, pat: str) -> str:
    m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


# ---- source 1: active brief mailbox (brief-tail) --------------------------------
checked += 1
try:
    mailbox = lsp._active_mailbox(cwd_p, role) if lsp else None
    if mailbox and Path(mailbox).exists():
        head = Path(mailbox).read_text(errors="ignore")[:4000]
        bid = _first_line(head, r"^\s*brief_id\s*:\s*(\S+)") or "active"
        rel = os.path.relpath(mailbox, str(cwd_p))
        pending.append(f"[brief] {bid} ACTIVE — {rel}")
except Exception:
    pending.append("[brief] mailbox unreadable — check briefs/_tasks/ by hand")


# ---- source 2: OPERATING.md (seat operating / wait-state) ------------------------
checked += 1
try:
    op_candidates = [
        cwd_p / "OPERATING.md",
        cwd_p / "briefs" / "OPERATING.md",
        home / "baker-vault" / "_ops" / "agents" / role.lower() / "operating.md",
    ]
    for op in op_candidates:
        if op.exists() and op.stat().st_size > 0:
            txt = op.read_text(errors="ignore")
            if re.search(r"\b(OPEN|PENDING|WAIT|IN[-_ ]?FLIGHT|TODO)\b", txt, re.IGNORECASE):
                pending.append(f"[operating] open item in {op}")
            break
except Exception:
    pass


# ---- source 3: armed deadlines --------------------------------------------------
checked += 1
try:
    dl_dirs = [cwd_p / "briefs" / "_deadlines", cwd_p / "_deadlines"]
    for d in dl_dirs:
        if d.is_dir():
            armed = [f for f in d.iterdir() if f.is_file() and not f.name.startswith(".")]
            if armed:
                pending.append(f"[deadline] {len(armed)} armed in {d} (nearest first — read them)")
            break
except Exception:
    pass


# ---- source 4: latest handover / PINNED §A OPEN ---------------------------------
checked += 1
try:
    if lsp:
        pin = lsp._open_pinned_item(cwd_p)
        if pin:
            pending.append(f"[pinned] unresolved OPEN item — {pin}")
    cdir = cwd_p / "briefs" / "_checkpoints"
    if cdir.is_dir():
        cps = [f for f in cdir.iterdir()
               if f.is_file() and f.suffix == ".md" and "checkpoint" in f.name]
        if cps:
            newest = max(cps, key=lambda f: f.stat().st_mtime)
            tag = " (UNVERIFIED-AUTO STUB — verify!)" if ".autostub." in newest.name else ""
            pending.append(f"[handover] latest checkpoint {newest.name}{tag} — read before resuming")
except Exception:
    pass


# ---- assemble (R2: <=30 lines, pointer-style) -----------------------------------
if not pending:
    _emit("[orientation] checked {} state sources (brief / operating / deadlines / "
          "handover) — none pending. (Bus messages are checked separately by the "
          "bus-drain hook.)".format(checked))
    raise SystemExit(0)

header = ("[orientation] {} pending item(s) across your OWN state sources — a clean "
          "bus does NOT mean nothing pending (E23b). Read these before acting:".format(len(pending)))
lines = [header] + [f"  - {p}" for p in pending]
lines.append("  (bus messages checked separately by the bus-drain hook)")
if len(lines) > MAX_LINES:
    kept = lines[:MAX_LINES - 1]
    kept.append(f"  ... +{len(lines) - (MAX_LINES - 1)} more (budget cap {MAX_LINES} lines)")
    lines = kept
_emit("\n".join(lines))
raise SystemExit(0)
PY
exit 0
