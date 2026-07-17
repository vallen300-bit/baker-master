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
    # D4 — context-window usage (forge telemetry via #12055). Absent today →
    # null flows through and the card-face context bar stays hidden (null-safe).
    "context_pct",
    # D5 — per-seat unacked message list (id / topic / created_at) so the
    # terminal panel can list them and D6 can name the oldest in the wake nudge.
    "unacked_messages",
)
# D6 — wake-on-open: re-nudge dedupe window (a seat is nudged at most once per
# this many seconds, so re-opening a seat does not spam its tmux).
WAKE_DEDUPE_SECONDS = 600.0

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


def _oldest_unacked(messages: Any) -> tuple[Any, str] | None:
    """(id, topic) of the oldest unacked message by created_at, or None."""
    rows = [
        m for m in (messages or [])
        if isinstance(m, dict) and m.get("id") is not None
    ]
    if not rows:
        return None
    oldest = min(rows, key=lambda m: str(m.get("created_at") or ""))
    return oldest.get("id"), str(oldest.get("topic") or "")


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


def _audit_wake(settings: Settings, slug: str, msg_id: Any, topic: str, line: str) -> None:
    """Append a durable audit line for every wake nudge sent (D6)."""
    entry = {
        "ts": time.time(), "slug": slug, "msg_id": msg_id,
        "topic": topic, "line": line,
    }
    try:
        settings.wake_audit_path.parent.mkdir(parents=True, exist_ok=True)
        with settings.wake_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError as exc:  # audit is best-effort; never fail the send on it
        LOG.warning("wake audit write failed for %s: %s", slug, exc)
    LOG.info("cockpit wake %s -> %s", slug, line)


def send_wake(
    settings: Settings,
    entry: ManifestEntry,
    glance_row: dict[str, Any] | None,
    *,
    now: float,
    last_wake: dict[str, float],
    audit: bool = True,
) -> dict[str, Any]:
    """D6 wake-on-open: send one `check bus #<oldest-id> <topic>` + Enter into the
    seat's tmux. Guarded (wake_skip_reason) and deduped (WAKE_DEDUPE_SECONDS per
    seat). Returns a result dict; a guarded/deduped skip is a no-op, not an error."""
    reason = wake_skip_reason(glance_row)
    if reason is not None:
        return {"ok": True, "sent": False, "skipped": reason, "slug": entry.slug}
    prev = last_wake.get(entry.slug)
    if prev is not None and (now - prev) < WAKE_DEDUPE_SECONDS:
        return {"ok": True, "sent": False, "skipped": "deduped", "slug": entry.slug}
    msg_id, topic = _oldest_unacked(glance_row.get("unacked_messages"))
    line = f"check bus #{msg_id} {topic}".rstrip()
    # Send the literal line, then Enter, as two sends so '#'/spaces stay literal.
    literal = _run_tmux(settings, ["send-keys", "-t", entry.slug, "-l", line])
    if literal.returncode != 0:
        raise RuntimeError(literal.stderr.strip() or "tmux wake send failed")
    enter = _run_tmux(settings, ["send-keys", "-t", entry.slug, "Enter"])
    if enter.returncode != 0:
        raise RuntimeError(enter.stderr.strip() or "tmux wake Enter failed")
    last_wake[entry.slug] = now
    if audit:
        _audit_wake(settings, entry.slug, msg_id, topic, line)
    return {
        "ok": True, "sent": True, "slug": entry.slug,
        "msg_id": msg_id, "topic": topic, "line": line,
    }


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
                result[str(row["slug"])] = {
                    field: row.get(field) for field in GLANCE_FIELDS
                }
        self.last_ok = True
        self._value = result
        self._expires_at = now + self.settings.lab_cache_seconds
        return result


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

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        # NOTIFY_SLICE — background poll loop for unread-bus banners. Runs only
        # when enabled; cleanly cancelled on shutdown. _notify_loop is defined
        # below in this closure and resolves at runtime (startup), not at def.
        task = (
            asyncio.create_task(_notify_loop()) if config.notify_enabled else None
        )
        try:
            yield
        finally:
            if task is not None:
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
    # D6 — per-seat last-wake monotonic timestamps for the re-nudge dedupe window.
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
        lab = await glance.read()
        lab_ok = getattr(glance, "last_ok", True)
        ttyd_states = await asyncio.gather(
            *(prober(entry) for entry in entries)
        )
        agents = []
        for entry, ttyd_up in zip(entries, ttyd_states):
            values = lab.get(entry.slug, {})
            agents.append(
                {
                    "slug": entry.slug,
                    "alias": entry.alias,
                    "port": entry.port,
                    "session_up": entry.slug in sessions,
                    "ttyd_up": bool(ttyd_up),
                    **{field: values.get(field) for field in GLANCE_FIELDS},
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
        try:
            return send_wake(
                config, entry, row,
                now=time.monotonic(), last_wake=app.state.wake_last,
            )
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

    # Expose one tick for deterministic tests (codex #12354) — the committed test
    # awaits this directly to prove a 0→N transition banners once through the real
    # read→compute→fire path, without depending on background-task timing.
    app.state.notify_tick = _notify_tick

    async def _notify_loop() -> None:
        while True:
            try:
                await _notify_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad tick must never kill the loop
                LOG.warning("notify tick failed: %s", exc)
            await asyncio.sleep(config.notify_poll_seconds)

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
