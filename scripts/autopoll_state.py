"""Autopoll state-machine helper for briefs/_tasks/CODE_N_PENDING.md.

Frontmatter contract per BRIEF_B_CODE_AUTOPOLL_1. All transitions go
through transition_state(); no direct frontmatter writes.
"""
from __future__ import annotations

import os
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


VALID_STATUSES = {
    "OPEN",
    "IN_PROGRESS",
    "BLOCKED-AI-HEAD-Q",
    "BLOCKED-DIRECTOR-Q",
    "COMPLETE",
    "RETIRED",
}

LEGAL_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS"},
    "IN_PROGRESS": {
        "BLOCKED-AI-HEAD-Q",
        "BLOCKED-DIRECTOR-Q",
        "COMPLETE",
        "OPEN",
    },
    "BLOCKED-AI-HEAD-Q": {"IN_PROGRESS"},
    "BLOCKED-DIRECTOR-Q": {"IN_PROGRESS"},
    "COMPLETE": {"RETIRED"},
    "RETIRED": set(),
}


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"malformed YAML in frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a mapping")
    body = text[end + 5:]
    return fm, body


def _serialize(fm: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body


def read_state(path: str | Path) -> dict:
    """Parse frontmatter dict from a CODE_N_PENDING.md file."""
    text = Path(path).read_text()
    try:
        fm, _ = _split_frontmatter(text)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    return fm


def transition_state(path: str | Path, *, to: str, **fields) -> None:
    """Atomically transition mailbox state. Raises on illegal transition.

    Caller is responsible for git add/commit/push after.
    """
    if to not in VALID_STATUSES:
        raise ValueError(f"invalid status: {to}")
    p = Path(path)
    fm, body = _split_frontmatter(p.read_text())
    current = fm.get("status")
    if current and to not in LEGAL_TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal transition: {current} -> {to}")

    fm["status"] = to
    fm.update(fields)

    if to == "IN_PROGRESS" and "claimed_at" not in fields:
        fm["claimed_at"] = datetime.now(timezone.utc).isoformat()

    p.write_text(_serialize(fm, body))


def heartbeat(path: str | Path) -> None:
    """B-code writes during long-running execution (~10-15 min cadence)."""
    p = Path(path)
    fm, body = _split_frontmatter(p.read_text())
    fm["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    p.write_text(_serialize(fm, body))


def find_stale_claims(
    tasks_dir: str | Path, max_age_minutes: int = 60
) -> list[Path]:
    """Return CODE_N_PENDING.md paths with IN_PROGRESS but heartbeat > max_age.

    Claims with no heartbeat yet (None) are skipped — too early to be
    considered stale; AI Head treats them as freshly-claimed.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_minutes * 60
    stale: list[Path] = []
    for p in sorted(Path(tasks_dir).glob("CODE_*_PENDING.md")):
        try:
            fm = read_state(p)
        except ValueError:
            continue
        if fm.get("status") != "IN_PROGRESS":
            continue
        hb = fm.get("last_heartbeat")
        if not hb:
            continue
        try:
            if isinstance(hb, datetime):
                hb_dt = hb
            else:
                hb_dt = datetime.fromisoformat(str(hb))
            ts = hb_dt.timestamp()
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            stale.append(p)
    return stale


def push_state_transition(
    code_path: str | Path,
    *,
    to: str,
    extra: Optional[str] = None,
) -> None:
    """Slack-push state transition. Best-effort — never raises.

    DM (D0AFY28N030): high-signal events (IN_PROGRESS claim, COMPLETE,
    BLOCKED-*).
    #baker-overnight (env BAKER_OVERNIGHT_CHANNEL_ID, default
    C0AF4FVN3FB): every transition.
    """
    try:
        from outputs.slack_notifier import post_to_channel
    except Exception:
        return
    try:
        fm = read_state(code_path)
    except ValueError:
        return
    brief = fm.get("brief", "?")
    code = Path(code_path).name
    bn = fm.get("claimed_by") or "?"
    line = f"[{to}] {code} ({bn}) — {brief}"
    if extra:
        line += f" — {extra}"
    high_signal = to in {
        "IN_PROGRESS",
        "COMPLETE",
        "BLOCKED-AI-HEAD-Q",
        "BLOCKED-DIRECTOR-Q",
    }
    overnight_channel = os.getenv("BAKER_OVERNIGHT_CHANNEL_ID", "C0AF4FVN3FB")
    try:
        post_to_channel(overnight_channel, line)
        if high_signal:
            post_to_channel("D0AFY28N030", line)
    except Exception:
        return


_IDLE_STATE_DIR = Path.home() / ".autopoll_state"


def _idle_state_path(b_code: str) -> Path:
    """Per-B-code local state file. Survives across wakes; outside any repo."""
    return _IDLE_STATE_DIR / f"{b_code}.yaml"


def read_idle_count(b_code: str) -> int:
    """Return current idle wake count for this B-code (0 if no state file)."""
    p = _idle_state_path(b_code)
    if not p.exists():
        return 0
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except (yaml.YAMLError, ValueError, OSError):
        return 0
    val = data.get("idle_count", 0)
    return int(val) if isinstance(val, int) else 0


def increment_idle_count(b_code: str) -> int:
    """Increment idle counter, return new value. Creates state dir if missing."""
    _IDLE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = _idle_state_path(b_code)
    new = read_idle_count(b_code) + 1
    p.write_text(yaml.safe_dump({
        "idle_count": new,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "b_code": b_code,
    }, sort_keys=False))
    return new


def reset_idle_count(b_code: str) -> None:
    """Reset to 0 (call after successful claim of fresh dispatch)."""
    p = _idle_state_path(b_code)
    if p.exists():
        p.unlink()
