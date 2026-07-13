#!/usr/bin/env python3
"""Shared live-state predicate for the E23 close-pin + orientation hooks.

CASE_ONE_E23_SESSION_STATE_PERSISTENCE_1. ONE definition of "this seat is holding
live matter state that would be lost on a rollover" — imported by both
close-pin-check.sh (persist-before-exit) and session-open-orientation.sh (surface
pending on open), and callable as a CLI for the fleet audit. A single source so the
two hooks can never drift on what "dirty" means (done-rubric #3).

Design contract (brief P-E23.1 trigger predicate):
  - Does NOT depend on any prompt rule; reads only durable state (mailbox, PINNED,
    checkpoints, the transcript's own tool-use record).
  - BIASED TO FIRE. A false fire is a harmless extra warn; a false miss loses
    matter state. So every uncertainty resolves toward dirty=True:
      * cannot read a live-state source  -> assume live_state True
      * cannot determine session start    -> treat the newest checkpoint as stale
  - Never raises out to the caller: evaluate() swallows everything and returns a
    dirty=True verdict on internal error (fail-toward-firing).

"dirty" = has_live_state AND NOT fresh_checkpoint, where:
  has_live_state  : an ACTIVE brief mailbox, a written draft this session (a
                    Write/Edit tool-use in the transcript), or an OPEN PINNED item.
  fresh_checkpoint: a checkpoint/handover file was written at or after this
                    session's start (i.e. the seat already persisted this session).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Cap the transcript tail we scan for tool-use, so a huge transcript never makes
# the hook slow enough to risk the 10s timeout.
_TRANSCRIPT_TAIL_BYTES = 512 * 1024
_EDIT_TOOL_RE = re.compile(r'"name"\s*:\s*"(Write|Edit|MultiEdit|NotebookEdit)"')


def _session_start_ts(transcript_path: Optional[str]) -> Optional[float]:
    """Best-effort epoch seconds for when this session began. Prefer the first
    transcript line's ISO `timestamp`; fall back to the file's birth/ctime. Returns
    None when nothing is knowable — the caller then biases toward 'stale'."""
    if not transcript_path:
        return None
    p = Path(str(transcript_path))
    try:
        with p.open("r", errors="ignore") as fh:
            first = fh.readline()
        if first:
            try:
                obj = json.loads(first)
                ts = obj.get("timestamp")
                if ts:
                    # ISO-8601, tolerate a trailing Z.
                    from datetime import datetime

                    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
    except OSError:
        pass
    # Fall back to file birth time (macOS) then ctime.
    try:
        st = p.stat()
        return getattr(st, "st_birthtime", None) or st.st_ctime
    except OSError:
        return None


def _transcript_has_edit(transcript_path: Optional[str]) -> bool:
    """True if the transcript records a Write/Edit/MultiEdit tool-use — i.e. this
    session produced a draft/file change that is live state worth persisting."""
    if not transcript_path:
        return False
    p = Path(str(transcript_path))
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > _TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - _TRANSCRIPT_TAIL_BYTES)
            blob = fh.read()
        return bool(_EDIT_TOOL_RE.search(blob.decode("utf-8", errors="ignore")))
    except OSError:
        # Cannot read the transcript -> bias to fire (assume an edit happened).
        return True


def _active_mailbox(cwd: Path, role: str) -> Optional[str]:
    """Return a pointer string to an ACTIVE/PENDING brief mailbox, else None.
    Workers use briefs/_tasks/CODE_<N>_PENDING.md; we also sweep any *PENDING*.md
    in _tasks so a non-worker mailbox is not missed (bias to fire)."""
    tasks = cwd / "briefs" / "_tasks"
    if not tasks.is_dir():
        return None
    candidates = []
    m = re.match(r"b(\d+)$", role or "", re.IGNORECASE)
    if m:
        candidates.append(tasks / f"CODE_{m.group(1)}_PENDING.md")
    try:
        candidates.extend(sorted(tasks.glob("*PENDING*.md")))
    except OSError:
        pass
    seen = set()
    for f in candidates:
        if f in seen or not f.exists():
            continue
        seen.add(f)
        try:
            head = f.read_text(errors="ignore")[:4000]
        except OSError:
            # Unreadable mailbox -> bias to fire.
            return str(f)
        if re.search(r"^\s*status\s*:\s*(ACTIVE|PENDING)\b", head, re.IGNORECASE | re.MULTILINE):
            return str(f)
    return None


def _open_pinned_item(cwd: Path) -> Optional[str]:
    """Return a pointer if a PINNED.md exists with an unresolved §A OPEN item.
    B-codes have no PINNED (returns None); desks/AH do."""
    for name in ("PINNED.md", "briefs/PINNED.md", ".claude/PINNED.md"):
        p = cwd / name
        if not p.exists():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            return str(p)  # bias to fire
        if re.search(r"\bOPEN\b", text):
            return str(p)
    return None


def _checkpoint_dir(cwd: Path) -> Path:
    return cwd / "briefs" / "_checkpoints"


def _fresh_checkpoint(cwd: Path, session_start_ts: Optional[float]) -> Optional[str]:
    """Return the path of a checkpoint/handover written at/after session start, else
    None. When session_start_ts is unknown we CANNOT prove freshness -> return None
    (treated as stale, biasing toward dirty)."""
    if session_start_ts is None:
        return None
    cdir = _checkpoint_dir(cwd)
    if not cdir.is_dir():
        return None
    try:
        for f in cdir.iterdir():
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime >= session_start_ts - 1:  # 1s slop
                    return str(f)
            except OSError:
                continue
    except OSError:
        return None
    return None


def evaluate(cwd: str, role: str, transcript_path: Optional[str] = None) -> dict:
    """The single dirty verdict. Never raises; on internal error returns dirty=True
    with reason 'predicate_error' (fail-toward-firing)."""
    try:
        cwd_p = Path(str(cwd or ".")).expanduser()
        session_start_ts = _session_start_ts(transcript_path)

        reasons: list[str] = []
        mailbox = _active_mailbox(cwd_p, role)
        if mailbox:
            reasons.append(f"active brief mailbox: {mailbox}")
        if _transcript_has_edit(transcript_path):
            reasons.append("this session wrote a draft/file (Write/Edit tool-use)")
        pinned = _open_pinned_item(cwd_p)
        if pinned:
            reasons.append(f"unresolved OPEN item in {pinned}")

        has_live_state = bool(reasons)
        fresh = _fresh_checkpoint(cwd_p, session_start_ts)
        fresh_checkpoint = fresh is not None
        dirty = has_live_state and not fresh_checkpoint
        return {
            "dirty": dirty,
            "has_live_state": has_live_state,
            "reasons": reasons,
            "fresh_checkpoint": fresh_checkpoint,
            "fresh_checkpoint_path": fresh,
            "session_start_ts": session_start_ts,
            "checkpoint_dir": str(_checkpoint_dir(cwd_p)),
        }
    except Exception as exc:  # noqa: BLE001 — must never break the hook
        return {
            "dirty": True,
            "has_live_state": True,
            "reasons": [f"predicate_error: {exc}"],
            "fresh_checkpoint": False,
            "fresh_checkpoint_path": None,
            "session_start_ts": None,
            "checkpoint_dir": "",
        }


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Evaluate the E23 live-state predicate for a seat.")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--role", default=os.environ.get("BAKER_ROLE", ""))
    ap.add_argument("--transcript", default=None)
    ap.add_argument("--json", action="store_true", help="emit the full verdict as JSON")
    args = ap.parse_args()
    verdict = evaluate(args.cwd, args.role, args.transcript)
    if args.json:
        print(json.dumps(verdict, indent=2))
    else:
        print("DIRTY" if verdict["dirty"] else "CLEAN")
        for r in verdict["reasons"]:
            print(f"  - {r}")
    # Exit 0 always: this is a predicate, not a gate; callers decide.
    return 0


if __name__ == "__main__":
    sys.exit(_main())
