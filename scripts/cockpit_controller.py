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
from dataclasses import dataclass
import hmac
import json
import logging
import os
from pathlib import Path
import re
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
)
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
    lab_url: str = "https://brisen-lab.onrender.com/api/v2/terminals"
    lab_cache_seconds: float = 30.0
    lab_timeout_seconds: float = 5.0
    command_timeout_seconds: float = 10.0
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


class LabGlance:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._expires_at = 0.0
        self._value: dict[str, dict[str, Any]] = {}

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
) -> FastAPI:
    config = settings or Settings.from_env()
    credentials = CredentialStore(config.credential_path)
    glance = lab_glance or LabGlance(config)
    app = FastAPI(title="Baker Cockpit Controller", docs_url=None, redoc_url=None)
    app.add_middleware(OriginGuardMiddleware, settings=config)
    app.add_middleware(BasicAuthMiddleware, credentials=credentials)
    app.state.settings = config
    app.state.credentials = credentials
    app.state.lab_glance = glance

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
        agents = []
        for entry in entries:
            values = lab.get(entry.slug, {})
            agents.append(
                {
                    "slug": entry.slug,
                    "alias": entry.alias,
                    "port": entry.port,
                    "session_up": entry.slug in sessions,
                    **{field: values.get(field) for field in GLANCE_FIELDS},
                }
            )
        return {"agents": agents}

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
