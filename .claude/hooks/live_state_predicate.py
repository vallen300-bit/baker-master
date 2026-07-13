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
  fresh_checkpoint: a checkpoint/handover file was written at or after the LATEST
                    live-state CHANGE — not merely after session start. A checkpoint
                    that predates a later Write/Edit does NOT cover that edit, so it
                    is stale (codex #10226 blocker 3: mtime-after-session-start
                    wrongly suppressed dirty when a later edit existed).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Cap the transcript tail we scan for tool-use, so a huge transcript never makes
# the hook slow enough to risk the 10s timeout.
_TRANSCRIPT_TAIL_BYTES = 512 * 1024
_EDIT_TOOL_RE = re.compile(r'"name"\s*:\s*"(Write|Edit|MultiEdit|NotebookEdit)"')


def _parse_iso(ts) -> Optional[float]:
    if not ts:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _mtime(path) -> Optional[float]:
    try:
        return Path(str(path)).stat().st_mtime
    except OSError:
        return None


def _last_edit(transcript_path: Optional[str]) -> tuple:
    """Return (has_edit, ts) where ts is when the LATEST Write/Edit happened.
    Prefer the timestamp on the last edit line; fall back to the transcript's mtime
    (an upper bound for the last activity). BIAS: an unreadable transcript is
    treated as a very recent edit (has_edit True, ts=now) so freshness can never be
    proven by an unverifiable transcript."""
    if not transcript_path:
        return (False, None)
    p = Path(str(transcript_path))
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > _TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - _TRANSCRIPT_TAIL_BYTES)
            blob = fh.read()
    except OSError:
        return (True, time.time())  # unreadable -> assume a recent edit (bias to fire)
    text = blob.decode("utf-8", errors="ignore")
    last_ts = None
    found = False
    for line in reversed(text.splitlines()):
        if _EDIT_TOOL_RE.search(line):
            found = True
            try:
                last_ts = _parse_iso(json.loads(line).get("timestamp"))
            except Exception:
                last_ts = None
            break
    if found and last_ts is None:
        # Edit present but its line carried no parseable timestamp: use the
        # transcript mtime (>= the last edit) so a later edit still beats an older
        # checkpoint.
        last_ts = _mtime(p) or time.time()
    return (found, last_ts)


def _session_start_ts(transcript_path: Optional[str]) -> Optional[float]:
    """First transcript line's ISO `timestamp` (informational only — no longer used
    for freshness). Falls back to birth/ctime, then None."""
    if not transcript_path:
        return None
    p = Path(str(transcript_path))
    try:
        with p.open("r", errors="ignore") as fh:
            first = fh.readline()
        ts = _parse_iso(json.loads(first).get("timestamp")) if first else None
        if ts is not None:
            return ts
    except Exception:
        pass
    try:
        st = p.stat()
        return getattr(st, "st_birthtime", None) or st.st_ctime
    except OSError:
        return None


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


def _newest_checkpoint(cwd: Path) -> tuple:
    """Return (mtime, path) of the newest checkpoint .md, else (None, None). Only
    .md files count (the .close-pin-warnlog / .close-pin-failed dot-markers are not
    checkpoints and must not be read as persistence)."""
    cdir = _checkpoint_dir(cwd)
    if not cdir.is_dir():
        return (None, None)
    best_ts = None
    best_path = None
    try:
        for f in cdir.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if best_ts is None or mt > best_ts:
                best_ts, best_path = mt, str(f)
    except OSError:
        return (None, None)
    return (best_ts, best_path)


def evaluate(cwd: str, role: str, transcript_path: Optional[str] = None) -> dict:
    """The single dirty verdict. Never raises; on internal error returns dirty=True
    with reason 'predicate_error' (fail-toward-firing).

    Freshness (blocker-3 fix): a checkpoint is fresh only if it was written at/after
    the LATEST live-state change (max of the active signals' timestamps), NOT merely
    after session start. So a checkpoint that predates a later Write/Edit is stale.
    """
    try:
        cwd_p = Path(str(cwd or ".")).expanduser()

        # Each signal carries the timestamp of the state it represents, so a later
        # change beats an older checkpoint.
        signals: list = []  # (reason, ts|None)
        mailbox = _active_mailbox(cwd_p, role)
        if mailbox:
            signals.append((f"active brief mailbox: {mailbox}", _mtime(mailbox)))
        has_edit, edit_ts = _last_edit(transcript_path)
        if has_edit:
            signals.append(("this session wrote a draft/file (Write/Edit tool-use)", edit_ts))
        pinned = _open_pinned_item(cwd_p)
        if pinned:
            signals.append((f"unresolved OPEN item in {pinned}", _mtime(pinned)))

        reasons = [r for r, _ in signals]
        has_live_state = bool(signals)
        ts_values = [ts for _, ts in signals if ts is not None]
        latest_change = max(ts_values) if ts_values else None

        cp_ts, cp_path = _newest_checkpoint(cwd_p)
        if not has_live_state:
            fresh_checkpoint = True  # nothing to cover
        elif cp_ts is None:
            fresh_checkpoint = False  # live state, no checkpoint at all
        elif latest_change is None:
            fresh_checkpoint = False  # live state we can't timestamp -> bias to fire
        else:
            fresh_checkpoint = (cp_ts + 1) >= latest_change  # 1s slop

        dirty = has_live_state and not fresh_checkpoint
        return {
            "dirty": dirty,
            "has_live_state": has_live_state,
            "reasons": reasons,
            "fresh_checkpoint": fresh_checkpoint,
            "fresh_checkpoint_path": cp_path if fresh_checkpoint else None,
            "latest_state_change_ts": latest_change,
            "newest_checkpoint_ts": cp_ts,
            "session_start_ts": _session_start_ts(transcript_path),
            "checkpoint_dir": str(_checkpoint_dir(cwd_p)),
        }
    except Exception as exc:  # noqa: BLE001 — must never break the hook
        return {
            "dirty": True,
            "has_live_state": True,
            "reasons": [f"predicate_error: {exc}"],
            "fresh_checkpoint": False,
            "fresh_checkpoint_path": None,
            "latest_state_change_ts": None,
            "newest_checkpoint_ts": None,
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
