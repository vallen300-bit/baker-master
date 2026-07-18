#!/usr/bin/env python3
"""Cockpit-in-Lab reverse bridge — laptop agent (baker-master).

COCKPIT_IN_LAB_BRIDGE_1 (b1, lead dispatch #12566). Opens ONE outbound websocket
to the Lab (`wss://brisen-lab.onrender.com/api/cockpit/bridge`) and services muxed
HTTP requests by proxying them to the laptop's loopback cockpit controller
(http://127.0.0.1:7800), injecting the controller's Basic-auth at request time.
Nothing inbound is opened on the laptop; the laptop dials out.

Security rails:
  * The bridge key (slug `cockpit-bridge`) is resolved via env -> key-cache -> 1P,
    NEVER read from argv and NEVER logged. It authenticates the WS to the Lab.
  * The controller Basic-auth credential is read from the local credentials file
    at request time and injected into the upstream request only. It NEVER leaves
    the laptop process — never sent to the Lab, never in config, never logged.
  * Reconnect forever with exponential backoff + jitter; a Lab outage or a
    displaced connection self-heals.

Byte-for-byte shared framing: scripts/cockpit_mux.py (identical to
brisen-lab/cockpit_mux.py; guarded by scripts/cockpit_mux_vectors.json).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

try:  # websockets >=13 asyncio client
    from websockets.asyncio.client import connect as ws_connect
    _WS_HEADERS_KW = "additional_headers"
except ImportError:  # pragma: no cover - older websockets (<=12) use the legacy kw
    from websockets import connect as ws_connect  # type: ignore
    _WS_HEADERS_KW = "extra_headers"
from websockets.exceptions import ConnectionClosed

# Import the shared codec by path so this script runs standalone.
import importlib.util as _ilu

_HERE = Path(__file__).resolve().parent
_spec = _ilu.spec_from_file_location("cockpit_mux", str(_HERE / "cockpit_mux.py"))
mux = _ilu.module_from_spec(_spec)  # type: ignore
sys.modules.setdefault("cockpit_mux", mux)
_spec.loader.exec_module(mux)  # type: ignore

LOG = logging.getLogger("cockpit_bridge_agent")

# --- defaults ---------------------------------------------------------------

DEFAULT_LAB_WS = "wss://brisen-lab.onrender.com/api/cockpit/bridge"
DEFAULT_UPSTREAM = "http://127.0.0.1:7800"
DEFAULT_CRED_PATH = os.path.expanduser(
    "~/Library/Application Support/baker/cockpit/credentials"
)
BRIDGE_SLUG = "cockpit-bridge"
_REQUEST_TIMEOUT_S = 30.0
_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 60.0
# Aggregate per-request body cap (codex #5). Cockpit is a control surface — its
# requests are tiny; this only backstops a pathological/hostile stream.
_MAX_STREAM_BODY = 32 * 1024 * 1024  # 32 MiB

# Deterministic jitter without Math.random-style nondeterminism concerns: a
# monotonic-seeded small perturbation is enough to de-sync reconnect storms.
import random as _random  # noqa: E402  (kept local; only used for reconnect jitter)


# ---------------------------------------------------------------------------
# Secret resolution — never argv, never logged
# ---------------------------------------------------------------------------


def _key_cache_file(slug: str) -> Path:
    return Path(os.path.expanduser(f"~/.brisen-lab/keys/{slug}"))


def resolve_bridge_key() -> Optional[str]:
    """Resolve the DEDICATED cockpit-bridge key only. No generic-key fallback.

    Precedence (all cockpit-bridge-dedicated sources):
      1. BRISEN_LAB_COCKPIT_BRIDGE_KEY (matches the server env name).
      2. ~/.brisen-lab/keys/cockpit-bridge cache file (slug-scoped).
      3. `op read` 1Password fallback on the cockpit-bridge item (best-effort).
    Returns the key or None. NEVER logs the value.

    COCKPIT_BRIDGE_HARDENING_2 D2 (codex-arch finding): the generic
    BRISEN_LAB_TERMINAL_KEY env fallback is REMOVED. The bridge is a separate
    surface from the bus, so a bus/terminal key must NEVER authenticate the
    bridge — otherwise any seat's generic key could open the Director control
    channel. The server (app.py cockpit_bridge_ws) already checks ONLY
    BRISEN_LAB_COCKPIT_BRIDGE_KEY; this makes the agent symmetric.
    """
    val = os.environ.get("BRISEN_LAB_COCKPIT_BRIDGE_KEY")
    if val and val.strip():
        return val.strip()
    cache = _key_cache_file(BRIDGE_SLUG)
    try:
        if cache.exists():
            txt = cache.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except OSError:
        pass
    # 1Password fallback (codex #4): match the canonical resolver's item scheme
    # (brisen_lab_terminal_key.sh -> op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>)
    # so a machine provisioned the standard way resolves the bridge key.
    op_ref = os.environ.get(
        "BRISEN_LAB_COCKPIT_BRIDGE_OP_REF",
        f"op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_{BRIDGE_SLUG}/credential",
    )
    try:
        out = subprocess.run(
            ["op", "read", op_ref], capture_output=True, text=True, timeout=15, check=False
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def load_basic_auth(cred_path: str) -> Optional[str]:
    """Read `username:password` from the local credentials file, return the
    `Basic <b64>` Authorization header value. Read at REQUEST time so a rotation
    takes effect without restart. Returns None if unreadable (caller proceeds
    without auth; the controller then 401s — surfaced, not silently succeeded)."""
    try:
        raw = Path(cred_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or ":" not in raw:
        return None
    token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _slug_from_term_path(path: str) -> Optional[str]:
    """Extract <slug> from a ttyd path `/term/<slug>/...`. None if it doesn't
    match (then the shared credential is used).

    Positional parse (do NOT collapse empty segments): `/term//ws` has an EMPTY
    slug and must yield None, not silently promote `ws`. Any slug carrying a
    path/separator/dot char (traversal) is refused."""
    segs = (path or "").split("/")  # "/term/b1/ws" -> ["", "term", "b1", "ws"]
    if len(segs) >= 3 and segs[1] == "term":
        slug = segs[2]
        if slug and all(c.isalnum() or c in "-_" for c in slug):
            return slug
    return None


def resolve_ttyd_cred_path(base_cred_path: str, path: str) -> str:
    """Per-seat ttyd credential (COCKPIT_BRIDGE_HARDENING_2 D4).

    Each seat's ttyd now embeds its OWN Basic credential (install_cockpit_ttyd.sh
    writes `<deploy>/credentials.d/<slug>`), so a leak of one seat's plist/cred no
    longer exposes every seat. Given the ttyd path `/term/<slug>/...`, return that
    seat's credential file if it exists, else fall back to the shared credential
    (`base_cred_path`) so the transition is safe before every seat is provisioned.
    The shared credential is still used for the controller's HTTP API (a single
    surface, not per-seat)."""
    slug = _slug_from_term_path(path)
    if slug:
        per_seat = Path(base_cred_path).parent / "credentials.d" / slug
        try:
            if per_seat.is_file():
                return str(per_seat)
        except OSError:
            pass
    return base_cred_path


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BridgeAgent:
    def __init__(self, *, lab_ws: str, upstream: str, cred_path: str) -> None:
        self.lab_ws = lab_ws
        self.upstream = upstream.rstrip("/")
        self.cred_path = cred_path
        # host:port authority the controller's OriginGuard expects.
        self._authority = self.upstream.split("://", 1)[-1]
        self._streams: dict[int, dict] = {}
        self._ws_streams: dict[int, "asyncio.Queue"] = {}
        self._send_lock = asyncio.Lock()
        self._ws_tasks: dict[int, "asyncio.Task"] = {}
        self._client: Optional[httpx.AsyncClient] = None
        # ws:// base for dialing the controller's ttyd proxy (http->ws, https->wss).
        self._ws_upstream = ("wss://" if self.upstream.startswith("https://") else "ws://") + self._authority

    def _reset_connection_state(self) -> None:
        """Drop all per-connection stream state on (re)connect. Codex #6: a bare
        _streams.clear() stranded Phase-2 ttyd pump tasks + _ws_streams across a
        Lab reconnect, and reused stream ids let stale cleanup clobber new
        streams. Cancel outstanding ws handlers and clear both maps."""
        self._streams.clear()
        self._ws_streams.clear()
        for task in self._ws_tasks.values():
            task.cancel()
        self._ws_tasks.clear()

    # -- one connection ------------------------------------------------------

    async def run_forever(self) -> None:
        backoff = _BACKOFF_START_S
        # trust_env=False (codex #1): the loopback request carries the injected
        # controller Basic-auth; if HTTP(S)_PROXY/ALL_PROXY is set without
        # 127.0.0.1 in NO_PROXY, trust_env=True would route that credential
        # through an external proxy, breaking "the credential never leaves the
        # laptop". The upstream is always loopback, so a proxy is never wanted.
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S, trust_env=False) as client:
            self._client = client
            while True:
                key = resolve_bridge_key()
                if not key:
                    LOG.error("bridge key unavailable (env/cache/1P all empty); retry in %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(_BACKOFF_MAX_S, backoff * 2)
                    continue
                try:
                    await self._serve_once(key)
                    backoff = _BACKOFF_START_S  # clean close -> reset backoff
                except ConnectionClosed as exc:
                    LOG.info("bridge closed (code=%s); reconnecting", getattr(exc, "code", "?"))
                except Exception as exc:  # noqa: BLE001 — a daemon must not die
                    LOG.warning("bridge error: %s; reconnecting", exc)
                sleep_s = min(_BACKOFF_MAX_S, backoff) * (1.0 + _random.random() * 0.25)
                await asyncio.sleep(sleep_s)
                backoff = min(_BACKOFF_MAX_S, backoff * 2)

    async def _serve_once(self, key: str) -> None:
        # Key travels only in the connection header — never argv, never logged.
        # _WS_HEADERS_KW picks additional_headers (websockets>=13) vs extra_headers
        # (legacy<=12) so a permitted old pin does not brick every connection.
        connect_kwargs = {
            _WS_HEADERS_KW: {"X-Terminal-Key": key},
            "max_size": mux.MAX_FRAME_PAYLOAD + mux.HEADER_LEN + 64,
        }
        async with ws_connect(self.lab_ws, **connect_kwargs) as ws:
            LOG.info("bridge connected to %s", self.lab_ws)
            self._reset_connection_state()
            buf = b""
            async for message in ws:
                if isinstance(message, str):
                    message = message.encode("utf-8")
                buf += message
                frames, buf = mux.iter_frames(buf)
                for frame in frames:
                    await self._on_frame(ws, frame)

    async def _send(self, ws, data: bytes) -> None:
        async with self._send_lock:
            await ws.send(data)

    async def _on_frame(self, ws, frame) -> None:
        if frame.type == mux.PING:
            await self._send(ws, mux.encode_frame(frame.stream_id, mux.PONG))
            return
        if frame.type == mux.PONG:
            return
        if frame.type == mux.OPEN:
            head = json.loads(frame.payload.decode("utf-8"))
            self._streams[frame.stream_id] = {"head": head, "body": bytearray()}
            return
        st = self._streams.get(frame.stream_id)
        if frame.type == mux.DATA:
            if st is not None:
                st["body"].extend(frame.payload)
                # Codex #5: aggregate per-stream cap so a runaway request body can
                # never buffer without bound (the 256KiB cap is per-frame only).
                if len(st["body"]) > _MAX_STREAM_BODY:
                    self._streams.pop(frame.stream_id, None)
                    asyncio.create_task(self._send(ws, mux.encode_frame(
                        frame.stream_id, mux.RESET, b'{"reason":"request_too_large"}')))
            return
        if frame.type == mux.RESET:
            self._streams.pop(frame.stream_id, None)
            return
        if frame.type == mux.END:
            if st is not None:
                self._streams.pop(frame.stream_id, None)
                asyncio.create_task(self._handle_request(ws, frame.stream_id, st))
            return
        # --- Phase 2: proxied ttyd websocket ---
        if frame.type == mux.WS_OPEN:
            head = json.loads(frame.payload.decode("utf-8")) if frame.payload else {}
            q: "asyncio.Queue" = asyncio.Queue()
            self._ws_streams[frame.stream_id] = q
            sid = frame.stream_id
            task = asyncio.create_task(self._handle_ws(ws, sid, head, q))
            self._ws_tasks[sid] = task
            # Guard against unregistering a REPLACEMENT task if an old task for a
            # reused sid completes late (codex re-verify race).
            def _clear(_t, s=sid):
                if self._ws_tasks.get(s) is _t:
                    self._ws_tasks.pop(s, None)
            task.add_done_callback(_clear)
            return
        if frame.type in (mux.WS_DATA, mux.WS_CLOSE):
            q = self._ws_streams.get(frame.stream_id)
            if q is not None:
                q.put_nowait(frame)
            return

    async def _handle_request(self, ws, stream_id: int, st: dict) -> None:
        head = st["head"]
        body = bytes(st["body"])
        try:
            resp = await self._proxy_to_controller(head, body)
            resp_head = json.dumps(
                {"status": resp.status_code, "headers": dict(resp.headers)},
                separators=(",", ":"),
            ).encode("utf-8")
            await self._send(ws, mux.encode_frame(stream_id, mux.OPEN, resp_head))
            for chunk in mux.chunk_body(stream_id, resp.content):
                await self._send(ws, chunk)
        except httpx.HTTPError as exc:
            LOG.warning("upstream error stream=%s: %s", stream_id, exc)
            await self._send_error(ws, stream_id, 502, "cockpit controller unreachable")
        except Exception as exc:  # noqa: BLE001
            LOG.warning("handler error stream=%s: %s", stream_id, exc)
            await self._send_error(ws, stream_id, 500, "bridge agent error")

    async def _send_error(self, ws, stream_id: int, status: int, detail: str) -> None:
        head = json.dumps({"status": status, "headers": {"content-type": "application/json"}},
                          separators=(",", ":")).encode("utf-8")
        with_body = json.dumps({"detail": detail}).encode("utf-8")
        try:
            await self._send(ws, mux.encode_frame(stream_id, mux.OPEN, head))
            for chunk in mux.chunk_body(stream_id, with_body):
                await self._send(ws, chunk)
        except Exception:
            pass

    # -- Phase 2: proxied ttyd websocket -------------------------------------

    async def _handle_ws(self, lab_ws, sid: int, head: dict, inbound: "asyncio.Queue") -> None:
        """Dial the laptop controller's ttyd WS and pipe it to the Lab over mux."""
        path = head.get("path", "/")
        query = head.get("query", "")
        target = self._ws_upstream + path + (("?" + query) if query else "")
        subprotocols = head.get("subprotocols") or []
        # NB: do NOT set Host manually — the websockets client derives it from the
        # target URI (== the controller authority the OriginGuard expects); a manual
        # duplicate corrupts the handshake (400). Origin is what OriginGuard checks.
        upstream_headers = {"Origin": self.upstream}
        # D4: inject this SEAT's own ttyd credential (credentials.d/<slug>) when
        # present, falling back to the shared credential during rollout.
        auth = load_basic_auth(resolve_ttyd_cred_path(self.cred_path, path))
        if auth:
            upstream_headers["Authorization"] = auth
        connect_kwargs = {_WS_HEADERS_KW: upstream_headers}
        if subprotocols:
            connect_kwargs["subprotocols"] = subprotocols
        try:
            async with ws_connect(target, **connect_kwargs) as upstream:
                chosen = getattr(upstream, "subprotocol", None)
                ack = json.dumps({"subprotocol": chosen}, separators=(",", ":")).encode("utf-8")
                await self._send(lab_ws, mux.encode_frame(sid, mux.WS_OPEN, ack))
                pump_up = asyncio.create_task(self._ws_upstream_to_lab(lab_ws, sid, upstream))
                pump_down = asyncio.create_task(self._ws_lab_to_upstream(inbound, upstream))
                # try/finally so BOTH pumps are cancelled + awaited whether the
                # wait completes normally OR _handle_ws is externally cancelled on
                # a Lab reconnect (codex re-verify #6: asyncio.wait does NOT cancel
                # its pending children when the awaiter is cancelled, so without
                # this finally the loser pump leaks per ttyd stream per reconnect).
                try:
                    await asyncio.wait({pump_up, pump_down}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in (pump_up, pump_down):
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(pump_up, pump_down, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001 — surface as a clean close, never crash
            LOG.info("ttyd ws dial failed stream=%s: %s", sid, exc)
            await self._send_ws_close(lab_ws, sid)
        finally:
            self._ws_streams.pop(sid, None)
            await self._send_ws_close(lab_ws, sid)

    async def _send_ws_close(self, lab_ws, sid: int) -> None:
        """Best-effort WS_CLOSE to the Lab. By the time a ttyd stream tears down
        the Lab socket may already be gone (Director closed the tab, or the Lab
        reconnected and dropped the old mux) — the close notification is then
        moot. Suppress the ConnectionClosed(OK) race so it never escapes the
        _handle_ws finally and crashes the connection loop (codex verify:
        unhandled ConnectionClosedOK at the finally send)."""
        try:
            await self._send(lab_ws, mux.encode_frame(sid, mux.WS_CLOSE, b""))
        except ConnectionClosed:
            pass

    async def _ws_upstream_to_lab(self, lab_ws, sid: int, upstream) -> None:
        try:
            async for message in upstream:
                if isinstance(message, str):
                    payload = bytes([mux.WS_KIND_TEXT]) + message.encode("utf-8")
                else:
                    payload = bytes([mux.WS_KIND_BINARY]) + message
                if len(payload) > mux.MAX_FRAME_PAYLOAD:
                    continue
                await self._send(lab_ws, mux.encode_frame(sid, mux.WS_DATA, payload))
        except ConnectionClosed:
            return

    async def _ws_lab_to_upstream(self, inbound: "asyncio.Queue", upstream) -> None:
        try:
            while True:
                frame = await inbound.get()
                if frame.type == mux.WS_CLOSE:
                    await upstream.close()
                    return
                if frame.type != mux.WS_DATA or not frame.payload:
                    continue
                kind, data = frame.payload[0], frame.payload[1:]
                if kind == mux.WS_KIND_TEXT:
                    await upstream.send(data.decode("utf-8", "replace"))
                else:
                    await upstream.send(data)
        except ConnectionClosed:
            return

    async def _proxy_to_controller(self, head: dict, body: bytes) -> httpx.Response:
        assert self._client is not None
        method = head.get("method", "GET")
        path = head.get("path", "/")
        query = head.get("query", "")
        url = self.upstream + path + (("?" + query) if query else "")
        headers = {str(k): str(v) for k, v in (head.get("headers") or {}).items()
                   if k.lower() not in ("host", "origin", "authorization", "content-length")}
        # Satisfy the controller's OriginGuard + inject its Basic-auth locally.
        headers["Host"] = self._authority
        headers["Origin"] = self.upstream
        auth = load_basic_auth(self.cred_path)
        if auth:
            headers["Authorization"] = auth
        return await self._client.request(method, url, headers=headers, content=body)


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cockpit-in-Lab bridge agent (laptop side)")
    p.add_argument("--lab-ws", default=os.environ.get("COCKPIT_BRIDGE_LAB_WS", DEFAULT_LAB_WS))
    p.add_argument("--upstream", default=os.environ.get("COCKPIT_BRIDGE_UPSTREAM", DEFAULT_UPSTREAM))
    p.add_argument("--cred-path", default=os.environ.get("COCKPIT_CREDENTIAL_FILE", DEFAULT_CRED_PATH))
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s cockpit-bridge-agent %(levelname)s %(message)s",
    )
    agent = BridgeAgent(lab_ws=args.lab_ws, upstream=args.upstream, cred_path=args.cred_path)
    try:
        asyncio.run(agent.run_forever())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
