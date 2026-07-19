#!/usr/bin/env python3
"""Local Baker Cockpit controller.

The controller is the single localhost origin for the cockpit page. It consumes
the launch manifest produced by BRIEF A and never regenerates registry or
Terminal-profile data.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import contextlib
from dataclasses import dataclass
import hmac
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Iterable
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

try:
    from websockets.asyncio.client import connect as websocket_connect
except ImportError:  # pragma: no cover - compatibility with older websockets
    from websockets import connect as websocket_connect
from websockets.exceptions import ConnectionClosedOK


LOG = logging.getLogger("baker.cockpit")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_+-]+$")
GLANCE_FIELDS = (
    "is_working",
    "has_telemetry",
    "needs_go",
    "unacked_count",
    "oldest_unacked_age_sec",
    "unacked_topics",
    # D4 — context-window usage. Populated by ``derive_context_pct`` from the
    # Lab context-band slice (LAB_CONTEXT_BAND_EXPOSURE_1 / #12055); until that
    # slice is live the source field is absent and null flows through, so the
    # card-face context bar stays hidden (null-safe).
    "context_pct",
    # D5 — per-seat unacked message list (id / kind / topic / created_at) so the
    # terminal panel can list them and D6 can name/type the oldest wake nudge.
    "unacked_messages",
    # COCKPIT_UI_POLISH_1 D9 — the App-resident card's bus-message panel binds the
    # same Lab feed the "Production & Lab" component uses: the most recent message
    # (even if acked) + the acknowledged count. Same bus-metadata class already
    # exposed by unacked_messages — no new leak surface (no body/transcript).
    "last_message",
    "acked_count",
)
# D6 — wake-on-open: same-message re-nudge dedupe window. Newer messages for the
# same seat must be allowed through promptly; a separate seat floor below keeps
# bursty arrivals from producing a wake storm.
WAKE_DEDUPE_SECONDS = 600.0
# Command/dispatch messages are actionable and may need a quicker repeat knock.
WAKE_COMMAND_DEDUPE_SECONDS = 120.0
# Minimum spacing between any two injections into one seat, regardless of message.
WAKE_SEAT_FLOOR_SECONDS = 60.0
# WAKE_COMPOSER_SUBMIT_FIX_1: settle gap between text→Enter and Enter→submit-Return.
# 0.3s mirrors the ratified `delay 0.3` in the wake handler app's submit-Return
# (BUS_AUTOWAKE_SUBMIT_GENERALIZE_1) — long enough for the composer to absorb the
# burst, short enough to keep the wake snappy.
WAKE_SUBMIT_SETTLE_S = 0.3
# WAKE_INJECT_SUBMIT_FIX_2 (#12874): after the FIX_1 submit-Returns, verify the
# nudge actually left the composer. A residual park survived FIX_1 on at least one
# seat (b3, 2026-07-18). Settle before the verify capture so the redraw lands; a
# park then gets exactly ONE recovery Enter, and an unrecoverable park fails loud.
WAKE_VERIFY_SETTLE_S = 1.0
# Number of trailing non-empty pane lines inspected for a parked nudge. The
# composer input box lives at the bottom of the pane; once submitted the nudge
# scrolls above the spinner/response, out of this tail.
WAKE_PARK_TAIL_LINES = 6
# A nudge line is "still in the composer box" only when it shares a line with a
# composer marker: the input prompt glyph or the box border. A *submitted* user
# turn renders as a plain `> ` line with neither, so this disambiguates parked
# (boxed) from sent (plain) — see COMPOSER_RESIDUAL_DIAG_20260718 pane captures.
WAKE_COMPOSER_MARKERS = ("❯", "│")  # ❯  │
# Codex TUI prints "Ctrl+L is disabled" for the repaint keystroke. Keep the
# capture verification, but skip that cosmetic repaint on Codex-family seats.
CODEX_FAMILY_SLUGS = frozenset({"codex", "codex-arch", "deputy-codex"})
# WAKE_INJECT_SUBMIT_FIX_2 D3 — every machine-injected nudge carries this visible
# origin prefix so freeform seat input is attributable at a glance. The reading
# agent treats a leading bracket tag as provenance, not instruction.
WAKE_ORIGIN_TAG = "[wake]"

# LAB_CONTEXT_BAND_EXPOSURE_1 (#12055) exposes per-seat context-window usage as
# ``context_used_percent`` on the public /api/v2/terminals payload. The cockpit
# D4 band renders ``context_pct`` (0-100, filled green→amber→red by USAGE), so
# the consumer maps used-% → context_pct. The Lab side already nulls its context
# fields on a stale (>900s) or absent heartbeat, so a missing used-% flows
# straight through to a hidden band. Session age NEVER feeds this field
# (codex-arch OBJECT, #12055) — the mapping only ever reads the usage percent.
CONTEXT_USED_FIELD = "context_used_percent"


def derive_context_pct(row: dict[str, Any]) -> float | None:
    """Return the D4 context-usage percent (0-100) for a Lab row, or None.

    Honors an explicit ``context_pct`` if the Lab payload ever carries one;
    otherwise falls back to the pinned-contract ``context_used_percent``. Any
    absent / non-numeric / boolean value yields None so the band hides rather
    than rendering a wrong bar (fault-tolerant). Numeric values are clamped to
    [0, 100]."""
    for key in ("context_pct", CONTEXT_USED_FIELD):
        val = row.get(key)
        # bool is an int subclass — reject it so True/False never render as 1/0.
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            # NaN/±inf would clamp to a confident 100% (a false full band) —
            # treat non-finite telemetry as unknown so the band hides instead.
            if not math.isfinite(val):
                continue
            return max(0.0, min(100.0, float(val)))
    return None


def glance_row_from_lab(row: dict[str, Any]) -> dict[str, Any]:
    """Project one Lab /api/v2/terminals row down to the pinned glance fields.

    Copies ONLY ``GLANCE_FIELDS`` (so no body/transcript/session detail leaks to
    the local page) and derives the D4 ``context_pct`` from the Lab context-band
    usage field."""
    glance = {field: row.get(field) for field in GLANCE_FIELDS}
    glance["context_pct"] = derive_context_pct(row)
    return glance

# LAB_COCKPIT_NOTIFY_SLICE_1 — controller-side macOS banner+sound when a bus
# dispatch lands (unacked_count 0→N) on a NON-self-awake seat that Wake.app does
# not already banner. Fires from the controller poll loop so it works with the
# page closed. The eligible-seat set is derived at generate time (registry →
# ``notify_eligible`` per card in cockpit_layout.json); the controller only reads
# that flag, never a hand-kept slug list (brief: "no hand-kept list").
NOTIFY_POLL_SECONDS = 15.0
# Per-seat re-fire cooldown: a seat that keeps receiving messages (N→N+1) never
# re-banners; only a fresh 0→N rising edge does, and even that is suppressed
# within this window as a storm guard.
NOTIFY_COOLDOWN_SECONDS = 300.0
NOTIFY_SOUND = "Ping"
# WAKE_RESPAWN_BACKLOG_DRAIN_1 — self-heal for a wake lost during a seat refresh.
# Zero disables the loop; positive values are seconds and can be tuned without a
# code change. Existing per-message dedupe and seat-floor guards contain repeats.
BACKLOG_SWEEP_SECONDS = 600.0


def load_notify_seats(static_dir: Path) -> set[str]:
    """Return the slugs whose generated card carries ``notify_eligible`` true.

    Source of truth is the generated ``cockpit_layout.json`` (registry-derived at
    generate time), so the controller keeps NO hand-kept seat list. Fault-tolerant:
    any read/parse error yields an empty set (fire nothing) rather than raising."""
    try:
        raw = json.loads((static_dir / "cockpit_layout.json").read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    seats: set[str] = set()
    plates = raw.get("plates") or raw.get("sections") or []
    if not isinstance(plates, list):
        return set()
    for plate in plates:
        for card in (plate or {}).get("cards", []) or []:
            if isinstance(card, dict) and card.get("notify_eligible") and card.get("slug"):
                seats.add(str(card["slug"]))
    return seats


def compute_notifications(
    prev_counts: dict[str, int],
    rows: dict[str, dict[str, Any]],
    eligible: set[str],
    last_fired: dict[str, float],
    *,
    now: float,
    cooldown: float,
) -> tuple[list[tuple[str, int]], dict[str, int], dict[str, float]]:
    """Pure transition detector. Returns (to_fire, new_prev_counts, new_last_fired).

    Fire rule for an eligible seat: a rising edge from zero — previous observed
    count == 0 and current > 0. The FIRST observation of a seat only seeds the
    baseline (prev is None) and never fires, so a controller restart does not
    banner the existing backlog. N→N+1 (prev>0) never fires; N→0 resets so a later
    0→N re-fires. A per-seat cooldown suppresses re-fires within ``cooldown`` s."""
    to_fire: list[tuple[str, int]] = []
    new_prev = dict(prev_counts)
    new_last = dict(last_fired)
    for slug in eligible:
        row = rows.get(slug) or {}
        cur = int(row.get("unacked_count") or 0)
        prev = prev_counts.get(slug)
        if prev is not None and prev == 0 and cur > 0:
            last = last_fired.get(slug)
            if last is None or (now - last) >= cooldown:
                to_fire.append((slug, cur))
                new_last[slug] = now
        new_prev[slug] = cur
    return to_fire, new_prev, new_last


def read_mute(path: Path) -> bool:
    """Read the persisted mute flag (default False = notifications on). Any
    read/parse failure reads as un-muted so a corrupt file never silences alerts."""
    try:
        return bool(json.loads(path.read_text("utf-8")).get("muted", False))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def write_mute(path: Path, muted: bool) -> None:
    """Persist the mute flag so page-closed firing honours the last toggle.

    Raises OSError on a persistence failure — the caller MUST surface it rather
    than report a false success (the UI would show "muted" while banners keep
    firing, codex #12354). ``read_mute`` still fails safe (toward alerting)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"muted": bool(muted)}), "utf-8")


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    """Read a non-negative float setting without making startup env fragile."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except (TypeError, ValueError):
        return default


def notify_macos(settings: "Settings", slug: str, count: int) -> None:
    """Fire one macOS banner + sound naming the seat. terminal-notifier if present
    (richer banner), else osascript. Best-effort: never raises into the poll loop."""
    plural = "s" if count != 1 else ""
    message = f"{slug}: {count} unread bus message{plural} — poke it"
    tn = shutil.which("terminal-notifier")
    try:
        if tn:
            cmd = [
                tn, "-title", "Baker Cockpit", "-message", message,
                "-sound", settings.notify_sound, "-group", f"cockpit-notify-{slug}",
            ]
        else:
            safe = message.replace('"', "'")
            script = (
                f'display notification "{safe}" with title "Baker Cockpit" '
                f'sound name "{settings.notify_sound}"'
            )
            cmd = ["osascript", "-e", script]
        subprocess.run(
            cmd, check=False, capture_output=True,
            timeout=settings.command_timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("notify send failed for %s: %s", slug, exc)
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True)
class Settings:
    bind_host: str = "127.0.0.1"
    port: int = 7800
    manifest_path: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/launch_manifest.json"
        )
    )
    credential_path: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/credentials"
        )
    )
    static_dir: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/static"
        )
    )
    fleet_script: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/fleet_terminals.sh"
        )
    )
    wake_audit_path: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/wake_audit.log"
        )
    )
    # LAB_COCKPIT_NOTIFY_SLICE_1 — persisted mute flag (page-closed firing honours
    # the last toggle); background poll cadence; per-seat re-fire cooldown; sound.
    notify_mute_path: Path = Path(
        os.path.expanduser(
            "~/Library/Application Support/baker/cockpit/notify_mute.json"
        )
    )
    notify_enabled: bool = True
    notify_poll_seconds: float = NOTIFY_POLL_SECONDS
    notify_cooldown_seconds: float = NOTIFY_COOLDOWN_SECONDS
    notify_sound: str = NOTIFY_SOUND
    lab_url: str = "https://brisen-lab.onrender.com/api/v2/terminals"
    lab_cache_seconds: float = 30.0
    lab_timeout_seconds: float = 5.0
    backlog_sweep_seconds: float = BACKLOG_SWEEP_SECONDS
    command_timeout_seconds: float = 10.0
    # Per-seat ttyd reachability probe budget — a local loopback TCP connect,
    # kept short so a hung seat never stalls the whole /api/agents response.
    ttyd_probe_timeout_seconds: float = 0.5
    tmux_binary: str = "tmux"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            bind_host=os.environ.get("COCKPIT_HOST", defaults.bind_host),
            port=int(os.environ.get("COCKPIT_PORT", defaults.port)),
            manifest_path=Path(
                os.path.expanduser(
                    os.environ.get(
                        "COCKPIT_MANIFEST_FILE", str(defaults.manifest_path)
                    )
                )
            ),
            credential_path=Path(
                os.path.expanduser(
                    os.environ.get(
                        "COCKPIT_CREDENTIAL_FILE", str(defaults.credential_path)
                    )
                )
            ),
            static_dir=Path(
                os.path.expanduser(
                    os.environ.get(
                        "COCKPIT_STATIC_DIR", str(defaults.static_dir)
                    )
                )
            ),
            fleet_script=Path(
                os.path.expanduser(
                    os.environ.get(
                        "COCKPIT_FLEET_SCRIPT", str(defaults.fleet_script)
                    )
                )
            ),
            lab_url=os.environ.get("COCKPIT_LAB_URL", defaults.lab_url),
            backlog_sweep_seconds=_float_env(
                "COCKPIT_BACKLOG_SWEEP_SECONDS",
                defaults.backlog_sweep_seconds,
            ),
            tmux_binary=os.environ.get("COCKPIT_TMUX_BINARY", defaults.tmux_binary),
            notify_enabled=os.environ.get(
                "COCKPIT_NOTIFY_ENABLED", "1" if defaults.notify_enabled else "0"
            ).strip().lower() not in ("0", "false", "no", ""),
        )

    @property
    def authority(self) -> str:
        return f"{self.bind_host}:{self.port}"

    @property
    def origin(self) -> str:
        return f"http://{self.authority}"


@dataclass(frozen=True)
class ManifestEntry:
    slug: str
    alias: str
    port: int


def _validate_slug(value: Any) -> str:
    slug = str(value or "")
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid manifest slug: {slug!r}")
    return slug


def _validate_alias(value: Any) -> str:
    alias = str(value or "")
    if not ALIAS_RE.fullmatch(alias):
        raise ValueError(f"invalid manifest alias: {alias!r}")
    return alias


def load_manifest(path: Path) -> tuple[ManifestEntry, ...]:
    """Load eligible seats in manifest order; never derive missing fields."""
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        rows = raw.get(
            "entries",
            raw.get("seats", raw.get("agents", [])),
        )
    else:
        rows = raw
    if not isinstance(rows, list):
        raise ValueError("launch manifest must contain a seat list")

    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("eligible") is not True:
            continue
        slug = _validate_slug(row.get("slug"))
        alias = _validate_alias(row.get("alias"))
        try:
            port = int(row["port"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid port for manifest slug {slug!r}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid port for manifest slug {slug!r}")
        if slug in seen:
            raise ValueError(f"duplicate manifest slug: {slug!r}")
        seen.add(slug)
        entries.append(ManifestEntry(slug=slug, alias=alias, port=port))
    return tuple(entries)


def _basic_credentials(raw: str) -> tuple[str, str] | None:
    if not raw.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(raw[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator or not username:
        return None
    return username, password


class CredentialStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> tuple[str, str]:
        stat = self.path.stat()
        if stat.st_mode & 0o077:
            raise RuntimeError(
                f"credential file must be mode 0600 or stricter: {self.path}"
            )
        raw = self.path.read_text(encoding="utf-8").strip()
        credentials = _basic_credentials(
            "Basic "
            + base64.b64encode(raw.encode("utf-8")).decode("ascii")
        )
        if credentials is None:
            raise RuntimeError(
                "credential file must contain username:password"
            )
        return credentials

    def verify(self, authorization: str | None) -> bool:
        supplied = _basic_credentials(authorization or "")
        if supplied is None:
            return False
        expected = self.read()
        return all(
            hmac.compare_digest(left, right)
            for left, right in zip(supplied, expected)
        )


def tmux_session_names(settings: Settings) -> set[str]:
    try:
        result = subprocess.run(
            [settings.tmux_binary, "ls", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=settings.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode not in (0, 1):
        LOG.warning("tmux ls failed: %s", result.stderr.strip())
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


# COCKPIT_UI_POLISH_1 D8 — local working signal. The Lab glance feed reports
# is_working:false for seats that are visibly working (Director 2026-07-18 defect),
# so the controller derives a LOCAL signal from tmux's own per-window output clock
# (#{window_activity}, the epoch of the last pane output) and ORs it with Lab
# telemetry in /api/agents. window_activity is the tmux server's output-activity
# timestamp — NOT a rendered-grid capture — so it needs no force-redraw and is
# immune to the stale-render effect (COMPOSER_RESIDUAL_DIAG). Read-only, no
# keystrokes into any seat. AC8: a seat with output within this window reads amber
# within one poll (<=30s), and goes quiet <=60s after output stops.
LOCAL_WORKING_WINDOW_S = 45.0


def tmux_window_activity(settings: Settings) -> dict[str, int]:
    """slug -> last output-activity epoch, from ONE `tmux list-windows -a` call.
    Empty on any tmux error (fault-tolerant — the Lab signal still stands)."""
    try:
        result = subprocess.run(
            [settings.tmux_binary, "list-windows", "-a", "-F",
             "#{session_name}:#{window_activity}"],
            capture_output=True,
            text=True,
            timeout=settings.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode not in (0, 1):
        LOG.warning("tmux list-windows failed: %s", result.stderr.strip())
        return {}
    out: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, _, ts = line.rpartition(":")
        try:
            epoch = int(ts)
        except ValueError:
            continue
        # A session can hold multiple windows; keep its most-recent activity.
        if name and (name not in out or epoch > out[name]):
            out[name] = epoch
    return out


def _run_tmux(settings: Settings, args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [settings.tmux_binary, *args],
        capture_output=True,
        text=True,
        timeout=settings.command_timeout_seconds,
        check=False,
    )


def ensure_session(settings: Settings, entry: ManifestEntry) -> dict[str, Any]:
    if entry.slug in tmux_session_names(settings):
        return {"ok": True, "started": False, "session_up": True}
    result = _run_tmux(
        settings,
        [
            "new-session",
            "-d",
            "-A",
            "-s",
            entry.slug,
            "/bin/zsh",
            "-lic",
            entry.alias,
        ],
    )
    if result.returncode != 0:
        if entry.slug in tmux_session_names(settings):
            return {"ok": True, "started": False, "session_up": True}
        detail = result.stderr.strip() or "tmux session start failed"
        raise RuntimeError(detail)
    return {"ok": True, "started": True, "session_up": True}


def send_go(settings: Settings, entry: ManifestEntry) -> dict[str, Any]:
    result = _run_tmux(
        settings,
        ["send-keys", "-t", entry.slug, "Enter"],
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "tmux GO failed"
        raise RuntimeError(detail)
    return {"ok": True, "sent": "Enter", "slug": entry.slug}


def _oldest_unacked_row(messages: Any) -> dict[str, Any] | None:
    """The oldest unacked message row by created_at, or None."""
    rows = [
        m for m in (messages or [])
        if isinstance(m, dict) and m.get("id") is not None
    ]
    if not rows:
        return None
    return min(rows, key=lambda m: str(m.get("created_at") or ""))


def _oldest_unacked(messages: Any) -> tuple[Any, str] | None:
    """(id, topic) of the oldest unacked message by created_at, or None."""
    oldest = _oldest_unacked_row(messages)
    if oldest is None:
        return None
    return oldest.get("id"), str(oldest.get("topic") or "")


def _wake_repeat_window(message: dict[str, Any]) -> float:
    """Return the repeat window for one message's typed intent."""
    kinds = {
        str(message.get("kind") or "").strip().lower(),
        str(message.get("intent") or "").strip().lower(),
    }
    if kinds & {"command", "dispatch"}:
        return WAKE_COMMAND_DEDUPE_SECONDS
    return WAKE_DEDUPE_SECONDS


def wake_skip_reason(glance_row: dict[str, Any] | None) -> str | None:
    """D6 guards. Returns None when a wake nudge is allowed, else the skip
    reason. NEVER wake a WORKING seat (it is busy) or a needs_go seat (the GO
    flow owns those); only nudge when there is a real unacked message to name."""
    if not glance_row:
        return "no telemetry"
    if glance_row.get("needs_go") is True:
        return "needs_go (GO flow owns it)"
    if glance_row.get("is_working") is True:
        return "working"
    if not (glance_row.get("unacked_count") or 0) > 0:
        return "no unacked"
    if _oldest_unacked(glance_row.get("unacked_messages")) is None:
        return "no unacked message id"
    return None


def _audit_wake(
    settings: Settings,
    slug: str,
    msg_id: Any,
    topic: str,
    line: str,
    *,
    suppressed_count: int = 0,
    skipped: str | None = None,
    source: str | None = None,
) -> None:
    """Append a durable audit line for sent or coalesced wake attempts."""
    entry = {
        "ts": time.time(), "slug": slug, "msg_id": msg_id,
        "topic": topic, "line": line,
    }
    if skipped is not None:
        entry["skipped"] = skipped
    if source is not None:
        entry["source"] = source
    if suppressed_count > 0:
        entry["suppressed_count"] = suppressed_count
    try:
        settings.wake_audit_path.parent.mkdir(parents=True, exist_ok=True)
        with settings.wake_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError as exc:  # audit is best-effort; never fail the send on it
        LOG.warning("wake audit write failed for %s: %s", slug, exc)
    LOG.info("cockpit wake %s -> %s", slug, line)


def wake_inject_writes(line: str) -> list[tuple[str, str]]:
    """The ordered PTY-level writes a machine wake injection performs, as
    ``(kind, data)`` pairs: a literal text write, then a bare carriage-return as
    its OWN write.

    The separate-CR shape is load-bearing: a newline coalesced into the text or
    wrapped inside an xterm bracketed paste (``ESC[200~ … \\n … ESC[201~``) is
    inserted literally by the composer and never submits — only a CR delivered as
    its own PTY write submits. See COMPOSER_RESIDUAL_DIAG_20260718. ``send_wake``
    realises these writes via ``_tmux_write_args`` (so this helper is the single
    production source, not dead code); the PTY regression test drives the same
    writes through a real PTY to prove the pattern submits.
    """
    return [("literal", line), ("cr", "\r")]


def _tmux_write_args(slug: str, kind: str, data: str) -> list[str]:
    """Realise one ``wake_inject_writes`` element as a tmux send-keys argv.

    ``literal`` → ``send-keys -l <text>`` (exact bytes, '#'/spaces stay literal).
    ``cr``      → ``send-keys Enter`` (tmux emits a bare CR as its own write —
    the separate-CR that submits; ``data`` is the ``"\\r"`` it stands for)."""
    if kind == "literal":
        return ["send-keys", "-t", slug, "-l", data]
    if kind == "cr":
        return ["send-keys", "-t", slug, "Enter"]
    raise ValueError(f"unknown wake write kind: {kind!r}")


def _composer_holds(pane_text: str, injected_line: str) -> bool:
    """True if OUR machine-injected nudge still sits in the composer input BOX
    (parked). ``injected_line`` is the full tagged line (``[wake] check bus
    #<id> …``).

    Match requires BOTH the ``[wake]`` origin tag on a boxed tail line (a
    composer marker — prompt glyph / box border) AND the nudge's ``#<id>`` token
    in the tail. Requiring the tag is load-bearing for AC3: human-composed text
    never carries the machine tag, so a human line like ``check bus #7 mine`` can
    never match and never triggers a recovery Enter. A *submitted* nudge renders
    as a plain ``> `` line with no box marker and scrolls above the spinner, so it
    does not match either. Empty/absent pane or an untagged needle → not parked."""
    if not pane_text or WAKE_ORIGIN_TAG not in (injected_line or ""):
        return False
    lines = [ln for ln in pane_text.splitlines() if ln.strip()]
    tail = lines[-WAKE_PARK_TAIL_LINES:]
    tag_boxed = any(
        WAKE_ORIGIN_TAG in ln and any(m in ln for m in WAKE_COMPOSER_MARKERS)
        for ln in tail
    )
    if not tag_boxed:
        return False
    id_match = re.search(r"#\d+", injected_line)
    if id_match and not any(id_match.group(0) in ln for ln in tail):
        return False
    return True


def _is_codex_family_slug(slug: str) -> bool:
    return slug in CODEX_FAMILY_SLUGS


def _post_park_flag(settings: Settings, slug: str, needle: str) -> None:
    """Fail-loud on an unrecoverable park: append a durable local record AND
    best-effort post a bus flag to lead (topic ``fleet/wake-inject-park``). Both
    are wrapped so a park never fails the wake; the local record is the guaranteed
    fail-loud surface even when the bus post cannot authenticate."""
    payload = {"ts": time.time(), "slug": slug, "line": needle, "event": "park_unrecovered"}
    try:
        settings.wake_audit_path.parent.mkdir(parents=True, exist_ok=True)
        with settings.wake_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError as exc:
        LOG.warning("park-flag audit write failed for %s: %s", slug, exc)
    body = f"wake nudge PARKED unrecovered on {slug}: {needle!r} — recovery Enter did not submit"
    script = Path(__file__).resolve().parent / "bus_post.sh"
    try:
        subprocess.run(
            ["bash", str(script), "lead", body, "fleet/wake-inject-park"],
            capture_output=True, text=True, timeout=15, check=False,
            env={**os.environ, "BAKER_ROLE": os.environ.get("BAKER_ROLE", "cockpit")},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("park-flag bus post failed for %s: %s", slug, exc)


def _verify_wake_submit(settings: Settings, slug: str, injected_line: str) -> dict[str, Any]:
    """WAKE_INJECT_SUBMIT_FIX_2 D2 — confirm the nudge left the composer; recover
    once if it parked; fail loud if it can't be recovered.

    Matches on the full tagged ``injected_line`` so only OUR machine nudge can
    trigger a recovery Enter — never human-composed text (AC3).

    Returns ``{"verified": <state>}`` where state is one of ``submitted`` (cleared
    on first check), ``recovered`` (one recovery Enter cleared it), ``unknown``
    (pane unreadable — no action, never a false recovery), or ``park_unrecovered``
    (still boxed after one recovery Enter → logged + bus-flagged)."""
    needle = injected_line

    def _read_pane() -> str | None:
        # Force a redraw first: capture-pane serves a STALE composer render after
        # edits (diag stale-render caveat), so a naive read false-positives and
        # false-negatives. Codex TUI rejects C-l with cosmetic noise, so its
        # family skips only the repaint and keeps the capture verification.
        if not _is_codex_family_slug(slug):
            _run_tmux(settings, ["send-keys", "-t", slug, "C-l"])
        time.sleep(WAKE_VERIFY_SETTLE_S)
        cap = _run_tmux(settings, ["capture-pane", "-t", slug, "-p"])
        return cap.stdout if cap.returncode == 0 else None

    pane = _read_pane()
    if pane is None:
        return {"verified": "unknown"}
    if not _composer_holds(pane, needle):
        return {"verified": "submitted"}
    # Parked. Exactly ONE recovery Enter — never more (double-submit guard from
    # FIX_1 stands; a second recovery could double parked text on a live seat).
    _run_tmux(settings, ["send-keys", "-t", slug, "Enter"])
    pane2 = _read_pane()
    if pane2 is None or not _composer_holds(pane2, needle):
        return {"verified": "recovered"}
    LOG.error("wake nudge PARKED unrecovered for %s: %r", slug, needle)
    _post_park_flag(settings, slug, needle)
    return {"verified": "park_unrecovered"}


def send_wake(
    settings: Settings,
    entry: ManifestEntry,
    glance_row: dict[str, Any] | None,
    *,
    now: float,
    last_wake: dict[str, dict[str, Any]],
    audit: bool = True,
    verify: bool = True,
    force: bool = False,
    audit_source: str | None = None,
) -> dict[str, Any]:
    """D6 wake-on-open: send one `check bus #<oldest-id> <topic>` + Enter into the
    seat's tmux. Guarded (wake_skip_reason), deduped for the same message, and
    rate-limited per seat. Returns a result dict; a guarded/deduped skip is a
    no-op, not an error."""
    reason = wake_skip_reason(glance_row)
    if reason is not None:
        if audit and audit_source:
            oldest = _oldest_unacked_row((glance_row or {}).get("unacked_messages"))
            _audit_wake(
                settings,
                entry.slug,
                oldest.get("id") if oldest else None,
                str(oldest.get("topic") or "") if oldest else "",
                "",
                skipped=reason,
                source=audit_source,
            )
        return {"ok": True, "sent": False, "skipped": reason, "slug": entry.slug}
    oldest = _oldest_unacked_row(glance_row.get("unacked_messages"))
    if oldest is None:  # defensive: wake_skip_reason already checks this condition
        if audit and audit_source:
            _audit_wake(
                settings,
                entry.slug,
                None,
                "",
                "",
                skipped="no unacked message id",
                source=audit_source,
            )
        return {"ok": True, "sent": False, "skipped": "no unacked message id", "slug": entry.slug}
    msg_id = oldest.get("id")
    topic = str(oldest.get("topic") or "")
    repeat_window = _wake_repeat_window(oldest)
    line = f"{WAKE_ORIGIN_TAG} check bus #{msg_id} {topic}".rstrip()

    state = last_wake.get(entry.slug)
    if not isinstance(state, dict):
        state = {
            "last_injection": state if isinstance(state, (int, float)) else None,
            "message_last": {},
        }
        last_wake[entry.slug] = state
    # Keep only the active same-message window so a long-lived controller does
    # not accumulate one timestamp per historical bus message.
    message_last = state.get("message_last")
    if not isinstance(message_last, dict):
        message_last = {}
        state["message_last"] = message_last
    suppressed_last = state.get("suppressed_count")
    if not isinstance(suppressed_last, dict):
        suppressed_last = {}
        state["suppressed_count"] = suppressed_last
    for key, timestamp in list(message_last.items()):
        timestamp_value = (
            timestamp.get("at")
            if isinstance(timestamp, dict)
            else timestamp
        )
        if (
            not isinstance(timestamp_value, (int, float))
            or (now - timestamp_value) >= WAKE_DEDUPE_SECONDS
        ):
            message_last.pop(key, None)
            # The suppression counter belongs to the same message window.
            # Drop it with the timestamp so historical coalesced messages do
            # not accumulate one stale counter per message.
            suppressed_last.pop(key, None)
    message_key = str(msg_id)
    previous_message = message_last.get(message_key)
    previous_message_at = (
        previous_message.get("at")
        if isinstance(previous_message, dict)
        else previous_message
    )
    if (
        not force
        and previous_message_at is not None
        and (now - previous_message_at) < repeat_window
    ):
        suppressed_last[message_key] = int(suppressed_last.get(message_key, 0)) + 1
        if audit:
            _audit_wake(
                settings,
                entry.slug,
                msg_id,
                topic,
                line,
                suppressed_count=suppressed_last[message_key],
                skipped="deduped",
                source=audit_source,
            )
        return {"ok": True, "sent": False, "skipped": "deduped", "slug": entry.slug}

    previous_injection = state.get("last_injection")
    if (
        not force
        and previous_injection is not None
        and (now - previous_injection) < WAKE_SEAT_FLOOR_SECONDS
    ):
        suppressed_last[message_key] = int(suppressed_last.get(message_key, 0)) + 1
        if audit:
            _audit_wake(
                settings,
                entry.slug,
                msg_id,
                topic,
                line,
                suppressed_count=suppressed_last[message_key],
                skipped="seat_floor",
                source=audit_source,
            )
        return {"ok": True, "sent": False, "skipped": "seat_floor", "slug": entry.slug}

    # D3 — visible [wake] origin tag so freeform seat input is attributable at a
    # glance (WAKE_INJECT_SUBMIT_FIX_2). The nudge stays `check bus #<id> <topic>`.
    # Realise the injection from wake_inject_writes so the write pattern has ONE
    # production source (also exercised by the PTY regression test): a literal
    # text write, then a bare CR as its own write. '#'/spaces stay literal.
    literal_kind, literal_data = wake_inject_writes(line)[0]
    literal = _run_tmux(settings, _tmux_write_args(entry.slug, literal_kind, literal_data))
    if literal.returncode != 0:
        raise RuntimeError(literal.stderr.strip() or "tmux wake send failed")
    # WAKE_COMPOSER_SUBMIT_FIX_1 (gap 5, bus #12631): a burst-injected Enter can be
    # swallowed by the composer (banner shown / text not yet absorbed) — the line
    # parks in the input box unsubmitted and the wake silently dies. Same failure
    # family as the Terminal-era bug fixed by BUS_AUTOWAKE_SUBMIT_GENERALIZE_1 in
    # the wake handler app; this ports that ratified pattern to the tmux path:
    # settle before Enter, then ONE best-effort bare submit-Return after another
    # settle. A bare Return at an empty/generating composer is a no-op, and it is
    # NEVER retried beyond this (lead ruling #5897 — re-injection on a busy-but-
    # live seat could double parked text; log-only on failure).
    cr_kind, cr_data = wake_inject_writes(line)[1]
    time.sleep(WAKE_SUBMIT_SETTLE_S)
    enter = _run_tmux(settings, _tmux_write_args(entry.slug, cr_kind, cr_data))
    if enter.returncode != 0:
        raise RuntimeError(enter.stderr.strip() or "tmux wake Enter failed")
    time.sleep(WAKE_SUBMIT_SETTLE_S)
    resubmit = _run_tmux(settings, _tmux_write_args(entry.slug, cr_kind, cr_data))
    if resubmit.returncode != 0:
        LOG.warning("wake submit-Return failed for %s (wake already sent): %s",
                    entry.slug, resubmit.stderr.strip())
    state["last_injection"] = now
    message_last[message_key] = {"at": now, "window": repeat_window}
    suppressed_count = int(suppressed_last.pop(message_key, 0))
    if audit:
        _audit_wake(
            settings,
            entry.slug,
            msg_id,
            topic,
            line,
            suppressed_count=suppressed_count,
            source=audit_source,
        )
    result = {
        "ok": True, "sent": True, "slug": entry.slug,
        "msg_id": msg_id, "topic": topic, "line": line,
    }
    # D2 — verify the nudge left the composer; recover once; fail loud otherwise.
    if verify:
        result.update(_verify_wake_submit(settings, entry.slug, line))
    return result


async def probe_ttyd(host: str, port: int, timeout: float) -> bool:
    """True if the seat's ttyd terminal server accepts a loopback TCP connect.

    tmux (session_up) and ttyd (the browser-facing terminal server) fail
    independently: a seat can be session_up yet have a dead ttyd, in which case
    the /term proxy 502s. The cockpit renders that as an explicit error card, so
    it needs a per-seat ttyd signal distinct from session_up.
    """
    try:
        reader_writer = asyncio.open_connection(host, port)
        _reader, writer = await asyncio.wait_for(reader_writer, timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError):
        pass
    return True


class LabGlance:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._expires_at = 0.0
        self._value: dict[str, dict[str, Any]] = {}
        # Whether the last actual (non-cached) Lab read succeeded. A full outage
        # collapses every seat's glance to {} — the page must show that
        # explicitly rather than letting all seats read as idle.
        self.last_ok = True

    async def read(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if now < self._expires_at:
            return self._value
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.lab_timeout_seconds
            ) as client:
                response = await client.get(self.settings.lab_url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            LOG.warning("Lab glance unavailable: %s", exc)
            self.last_ok = False
            self._value = {}
            self._expires_at = now + min(self.settings.lab_cache_seconds, 5.0)
            return {}

        result: dict[str, dict[str, Any]] = {}
        rows = payload.get("terminals", []) if isinstance(payload, dict) else []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not row.get("slug"):
                    continue
                result[str(row["slug"])] = glance_row_from_lab(row)
        self.last_ok = True
        self._value = result
        self._expires_at = now + self.settings.lab_cache_seconds
        return result

    async def force_refresh(self) -> dict[str, dict[str, Any]]:
        """Read Lab state immediately, bypassing the controller glance cache."""
        self._expires_at = 0.0
        return await self.read()


def _allowed_authority(headers: Any, settings: Settings) -> bool:
    host = str(headers.get("host", ""))
    if host != settings.authority:
        return False
    origin = headers.get("origin")
    return origin in (None, settings.origin)


class OriginGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if not _allowed_authority(request.headers, self.settings):
            return JSONResponse(
                {"detail": "invalid cockpit origin"},
                status_code=403,
            )
        return await call_next(request)


def _auth_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": 'Basic realm="Baker Cockpit"'},
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, credentials: CredentialStore):
        super().__init__(app)
        self.credentials = credentials

    async def dispatch(self, request: Request, call_next):
        try:
            valid = self.credentials.verify(
                request.headers.get("authorization")
            )
        except (OSError, RuntimeError) as exc:
            LOG.error("cockpit credential failure: %s", exc)
            return JSONResponse(
                {"detail": "cockpit credentials unavailable"},
                status_code=503,
            )
        if not valid:
            return JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Baker Cockpit"'},
            )
        return await call_next(request)


def _copy_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and key.lower() not in {"content-length", "content-encoding"}
    }


def _target_path(slug: str, tail: str, query: str) -> str:
    path = f"/term/{slug}/"
    if tail:
        path += tail.lstrip("/")
    if query:
        path += "?" + query
    return path


def _upstream_headers(request_headers: Any, target_authority: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and key.lower() not in {"host", "origin", "content-length"}
    }
    headers["Host"] = target_authority
    headers["Origin"] = f"http://{target_authority}"
    return headers


def _entry_for(entries: tuple[ManifestEntry, ...], slug: str) -> ManifestEntry:
    for entry in entries:
        if entry.slug == slug:
            return entry
    raise HTTPException(status_code=404, detail="unknown cockpit seat")


def create_app(
    settings: Settings | None = None,
    *,
    lab_glance: LabGlance | None = None,
    ttyd_prober: Any | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    credentials = CredentialStore(config.credential_path)
    glance = lab_glance or LabGlance(config)

    async def default_prober(entry: ManifestEntry) -> bool:
        return await probe_ttyd(
            config.bind_host, entry.port, config.ttyd_probe_timeout_seconds
        )

    prober = ttyd_prober or default_prober

    async def _fresh_glance_read() -> dict[str, dict[str, Any]]:
        force_refresh = getattr(glance, "force_refresh", None)
        if callable(force_refresh):
            return await force_refresh()
        # Test doubles and compatible glance providers may only expose read().
        return await glance.read()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        # NOTIFY_SLICE — background poll loop for unread-bus banners. Runs only
        # when enabled; cleanly cancelled on shutdown. _notify_loop is defined
        # below in this closure and resolves at runtime (startup), not at def.
        tasks = []
        if config.notify_enabled:
            tasks.append(asyncio.create_task(_notify_loop()))
        if config.backlog_sweep_seconds > 0:
            tasks.append(asyncio.create_task(_backlog_sweep_loop()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="Baker Cockpit Controller", docs_url=None, redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(OriginGuardMiddleware, settings=config)
    app.add_middleware(BasicAuthMiddleware, credentials=credentials)
    app.state.settings = config
    app.state.credentials = credentials
    app.state.lab_glance = glance
    # D6/P2 — per-seat wake dedupe state: same-message timestamps plus a
    # cross-message injection floor.
    app.state.wake_last = {}
    # NOTIFY_SLICE — per-seat last-observed unacked baseline + last-fire timestamps
    # for the 0→N transition detector (advanced by the lifespan poll loop).
    app.state.notify_prev = {}
    app.state.notify_last_fired = {}

    def manifest() -> tuple[ManifestEntry, ...]:
        try:
            return load_manifest(config.manifest_path)
        except (OSError, ValueError) as exc:
            LOG.error("launch manifest unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="launch manifest unavailable",
            ) from exc

    async def require_websocket_auth(websocket: WebSocket) -> bool:
        if not _allowed_authority(websocket.headers, config):
            await websocket.close(code=1008, reason="invalid cockpit origin")
            return False
        try:
            valid = credentials.verify(websocket.headers.get("authorization"))
        except (OSError, RuntimeError):
            await websocket.close(code=1011, reason="cockpit credentials unavailable")
            return False
        if not valid:
            await websocket.close(code=1008, reason="authentication required")
            return False
        return True

    @app.get("/api/agents")
    async def get_agents(request: Request):
        entries = manifest()
        sessions = tmux_session_names(config)
        activity = tmux_window_activity(config)   # D8 — local output-activity clock
        now_epoch = time.time()
        lab = await glance.read()
        lab_ok = getattr(glance, "last_ok", True)
        ttyd_states = await asyncio.gather(
            *(prober(entry) for entry in entries)
        )
        agents = []
        for entry, ttyd_up in zip(entries, ttyd_states):
            values = lab.get(entry.slug, {})
            glance_fields = {field: values.get(field) for field in GLANCE_FIELDS}
            session_up = entry.slug in sessions
            # D8 — OR a local tmux output-activity signal into is_working so a seat
            # the Lab feed under-reports still reads as working while it produces
            # output. Live tmux seats only; fault-tolerant when activity is absent.
            last_act = activity.get(entry.slug)
            local_working = bool(
                session_up and last_act is not None
                and (now_epoch - last_act) <= LOCAL_WORKING_WINDOW_S
            )
            if local_working:
                glance_fields["is_working"] = True
            agents.append(
                {
                    "slug": entry.slug,
                    "alias": entry.alias,
                    "port": entry.port,
                    "session_up": session_up,
                    "ttyd_up": bool(ttyd_up),
                    **glance_fields,
                    "local_working": local_working,   # D8 — surfaced for tests/transparency
                }
            )
        return {"agents": agents, "lab_glance_ok": bool(lab_ok)}

    @app.post("/api/sessions/{slug}/start")
    async def start_session(slug: str, request: Request):
        entry = _entry_for(manifest(), slug)
        try:
            return ensure_session(config, entry)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/sessions/{slug}/go")
    async def go_session(slug: str, request: Request):
        entry = _entry_for(manifest(), slug)
        try:
            return send_go(config, entry)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/sessions/{slug}/wake")
    async def wake_session(slug: str, request: Request):
        # D6 — wake-on-open. Same origin/auth guards as start/go (middleware).
        entry = _entry_for(manifest(), slug)
        if entry.slug not in tmux_session_names(config):
            return {"ok": True, "sent": False, "skipped": "session down", "slug": entry.slug}
        lab = await glance.read()
        row = lab.get(entry.slug) or {}
        force = request.query_params.get("force") == "1"
        try:
            result = send_wake(
                config, entry, row,
                now=time.monotonic(), last_wake=app.state.wake_last,
                force=force,
            )
            if result.get("skipped") == "no unacked":
                # The Lab has its own short cache, and this controller has a
                # separate glance cache. A cached zero must not be authoritative
                # for a wake decision; one forced read closes the stale-glance gap.
                fresh_lab = await _fresh_glance_read()
                fresh_row = fresh_lab.get(entry.slug) or {}
                result = send_wake(
                    config, entry, fresh_row,
                    now=time.monotonic(), last_wake=app.state.wake_last,
                    force=force,
                )
            return result
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/notify/state")
    async def notify_state(request: Request):
        # NOTIFY_SLICE — hydrate the header mute toggle. Eligible set is exposed
        # for observability (which seats the controller will banner).
        return {
            "muted": read_mute(config.notify_mute_path),
            "enabled": config.notify_enabled,
            "eligible": sorted(load_notify_seats(config.static_dir)),
        }

    @app.post("/api/notify/mute")
    async def notify_mute(request: Request):
        # NOTIFY_SLICE — persist the mute flag so page-closed firing honours it.
        # Same origin/auth guards as start/go/wake (middleware).
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            payload = {}
        muted = bool(payload.get("muted")) if isinstance(payload, dict) else False
        # A persistence failure must surface, not read back as success — otherwise
        # the UI shows "muted" while the controller keeps banner-ing (codex #12354).
        try:
            write_mute(config.notify_mute_path, muted)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"mute persistence failed: {exc}"
            ) from exc
        return {"ok": True, "muted": muted}

    async def _notify_tick() -> None:
        """One poll cycle: read glance, detect 0→N on eligible seats, banner unless
        muted. The baseline is ALWAYS advanced (even while muted) so un-muting does
        not dump the accumulated backlog as a burst of banners."""
        rows = await glance.read()
        if not getattr(glance, "last_ok", True):
            return  # a full Lab outage collapses every seat to {}; do not fire
        eligible = load_notify_seats(config.static_dir)
        to_fire, app.state.notify_prev, app.state.notify_last_fired = (
            compute_notifications(
                app.state.notify_prev, rows, eligible, app.state.notify_last_fired,
                now=time.monotonic(), cooldown=config.notify_cooldown_seconds,
            )
        )
        if read_mute(config.notify_mute_path):
            return
        for slug, count in to_fire:
            notify_macos(config, slug, count)

    async def _backlog_sweep_tick() -> list[dict[str, Any]]:
        """Re-wake idle seats whose old backlog outlived its original wake."""
        if config.backlog_sweep_seconds <= 0:
            return []
        rows = await glance.read()
        if not getattr(glance, "last_ok", True):
            return []
        sessions = tmux_session_names(config)
        now = time.monotonic()
        outcomes: list[dict[str, Any]] = []
        for entry in manifest():
            row = rows.get(entry.slug) or {}
            try:
                oldest_age = float(row.get("oldest_unacked_age_sec") or 0)
            except (TypeError, ValueError):
                oldest_age = 0.0
            if (
                entry.slug not in sessions
                or row.get("is_working") is True
                or int(row.get("unacked_count") or 0) <= 0
                or oldest_age <= config.backlog_sweep_seconds
            ):
                continue
            try:
                result = send_wake(
                    config,
                    entry,
                    row,
                    now=now,
                    last_wake=app.state.wake_last,
                    audit_source="sweep",
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                LOG.warning("backlog sweep wake failed for %s: %s", entry.slug, exc)
                result = {
                    "ok": False,
                    "sent": False,
                    "skipped": "error",
                    "slug": entry.slug,
                }
            outcomes.append(result)
        return outcomes

    # Expose one tick for deterministic tests (codex #12354) — the committed test
    # awaits this directly to prove a 0→N transition banners once through the real
    # read→compute→fire path, without depending on background-task timing.
    app.state.notify_tick = _notify_tick
    app.state.backlog_sweep_tick = _backlog_sweep_tick

    async def _notify_loop() -> None:
        while True:
            try:
                await _notify_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad tick must never kill the loop
                LOG.warning("notify tick failed: %s", exc)
            await asyncio.sleep(config.notify_poll_seconds)

    async def _backlog_sweep_loop() -> None:
        while True:
            try:
                await _backlog_sweep_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad cycle must never kill the loop
                LOG.warning("backlog sweep tick failed: %s", exc)
            await asyncio.sleep(config.backlog_sweep_seconds)

    async def proxy_http(request: Request, slug: str, tail: str = ""):
        entry = _entry_for(manifest(), slug)
        target_authority = f"127.0.0.1:{entry.port}"
        target = (
            f"http://{target_authority}"
            + _target_path(slug, tail, request.url.query)
        )
        headers = _upstream_headers(request.headers, target_authority)
        try:
            async with httpx.AsyncClient(
                timeout=config.lab_timeout_seconds,
                follow_redirects=False,
            ) as client:
                upstream = await client.request(
                    request.method,
                    target,
                    headers=headers,
                    content=await request.body(),
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="ttyd unavailable") from exc
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_copy_response_headers(upstream.headers),
            media_type=upstream.headers.get("content-type"),
        )

    @app.api_route(
        "/term/{slug}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_http_root(request: Request, slug: str):
        return await proxy_http(request, slug)

    @app.api_route(
        "/term/{slug}/{tail:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy_http_path(request: Request, slug: str, tail: str):
        return await proxy_http(request, slug, tail)

    async def proxy_websocket(websocket: WebSocket, slug: str, tail: str = ""):
        if not await require_websocket_auth(websocket):
            return
        entry = _entry_for(manifest(), slug)
        target_authority = f"127.0.0.1:{entry.port}"
        target = (
            f"ws://{target_authority}"
            + _target_path(slug, tail, websocket.url.query)
        )
        auth_header = websocket.headers.get("authorization")
        headers = {"Authorization": auth_header} if auth_header else {}
        requested_protocols = [
            value.strip()
            for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if value.strip()
        ]
        try:
            connect_kwargs: dict[str, Any] = {
                "origin": f"http://{target_authority}",
                "additional_headers": headers,
                "open_timeout": config.lab_timeout_seconds,
                "proxy": None,
            }
            if requested_protocols:
                connect_kwargs["subprotocols"] = requested_protocols
            async with websocket_connect(target, **connect_kwargs) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)

                async def browser_to_ttyd() -> None:
                    while True:
                        message = await websocket.receive()
                        message_type = message.get("type")
                        if message_type == "websocket.disconnect":
                            return
                        if message_type == "websocket.receive":
                            if message.get("text") is not None:
                                await upstream.send(message["text"])
                            elif message.get("bytes") is not None:
                                await upstream.send(message["bytes"])

                async def ttyd_to_browser() -> None:
                    while True:
                        message = await upstream.recv()
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [
                    asyncio.create_task(browser_to_ttyd()),
                    asyncio.create_task(ttyd_to_browser()),
                ]
                _done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                for task in _done:
                    if not task.cancelled() and task.exception():
                        raise task.exception()
        except WebSocketDisconnect:
            return
        except ConnectionClosedOK:
            return
        except Exception as exc:
            LOG.warning("ttyd websocket proxy failed for %s: %s", slug, exc)
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1011, reason="ttyd unavailable")

    @app.websocket("/term/{slug}")
    async def proxy_websocket_root(websocket: WebSocket, slug: str):
        await proxy_websocket(websocket, slug)

    @app.websocket("/term/{slug}/{tail:path}")
    async def proxy_websocket_path(
        websocket: WebSocket, slug: str, tail: str
    ):
        await proxy_websocket(websocket, slug, tail)

    if config.static_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(config.static_dir), html=True),
            name="cockpit-static",
        )

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("COCKPIT_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("COCKPIT_PORT", "7800")),
    )
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
