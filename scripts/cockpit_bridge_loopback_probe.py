#!/usr/bin/env python3
"""Loopback integration probe for the cockpit-in-Lab bridge.

COCKPIT_IN_LAB_BRIDGE_1 (b1, lead #12566). Phase-1 mandatory integration test.
Answers the prototype question: *does WS-mux relay of HTTP through uvicorn hold
up with the real cockpit request/response flow?* Entirely loopback — compliant
with the no-internet-exposure ruling.

Topology (all on 127.0.0.1):

    httpx client ──▶ REAL Lab app (uvicorn) /cockpit/*
                        │  (real websocket, real cockpit_mux frames)
                        ▼
                     REAL BridgeAgent
                        │  (httpx, injects Basic-auth)
                        ▼
                     fake cockpit controller (uvicorn) — stands in for :7800

Asserts: cockpit page GET 200 + body, /api/agents GET 200 JSON, Start POST 200
(echoes body), flag-off 404 on every /cockpit path, agent-absent 503.

Requires BOTH checkouts under ~/bm-b1 (brisen-lab + baker-master/scripts) and
uvicorn/websockets/httpx/fastapi. Run: python3 scripts/cockpit_bridge_loopback_probe.py
Exit 0 = all green.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import socket
import sys
import threading
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse

_HERE = Path(__file__).resolve().parent
_LAB_DIR = _HERE.parent / "brisen-lab"

# Import the real server + agent modules by path.
sys.path.insert(0, str(_LAB_DIR))


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


mux = _load("cockpit_mux", _LAB_DIR / "cockpit_mux.py")
cb = _load("cockpit_bridge", _LAB_DIR / "cockpit_bridge.py")
agent_mod = _load("cockpit_bridge_agent", _HERE / "cockpit_bridge_agent.py")

BRIDGE_KEY = "loopback-probe-key-do-not-ship"
CRED = "director:probe-pass"
PAGE_MARKER = "<!-- COCKPIT GRID PROBE -->"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- fake cockpit controller (stands in for the real :7800) -----------------

def build_fake_controller() -> FastAPI:
    app = FastAPI()

    def _check_auth(req: Request):
        got = req.headers.get("authorization")
        want = "Basic " + base64.b64encode(CRED.encode()).decode()
        return got == want

    @app.get("/")
    @app.get("/{path:path}")
    async def any_get(req: Request, path: str = ""):
        if not _check_auth(req):
            return JSONResponse({"detail": "auth required"}, status_code=401)
        if path.startswith("api/agents"):
            return JSONResponse({"agents": [{"slug": "b1", "state": "WORKING"}]})
        if path == "" or path.endswith("index.html") or path == "/":
            # realistic cockpit index.html (relative assets + a <head>) so the
            # probe can verify the Lab's Option-A base inject end-to-end.
            html = (
                "<!DOCTYPE html><html><head>\n"
                f"<!-- {PAGE_MARKER} -->\n"
                '<link rel="stylesheet" href="cockpit.css">\n'
                "</head><body><div id='grid'></div>"
                '<script src="cockpit.js"></script></body></html>'
            )
            return PlainTextResponse(html, media_type="text/html")
        if path.startswith("term/"):
            # simulate the ttyd terminal page (its own <head>) — must NOT be base-injected
            return PlainTextResponse("<html><head><title>ttyd</title></head><body>TTYD_PAGE</body></html>",
                                     media_type="text/html")
        return PlainTextResponse(PAGE_MARKER + "\n<html>cockpit</html>", media_type="text/html")

    @app.post("/{path:path}")
    async def any_post(req: Request, path: str = ""):
        if not _check_auth(req):
            return JSONResponse({"detail": "auth required"}, status_code=401)
        body = await req.body()
        return JSONResponse({"ok": True, "path": path, "echo": body.decode() or None})

    @app.websocket("/term/{slug}/{tail:path}")
    async def fake_ttyd(ws: WebSocket, slug: str, tail: str = ""):
        # Prove the agent injected Basic-auth on the upstream WS connect.
        want = "Basic " + base64.b64encode(CRED.encode()).decode()
        if ws.headers.get("authorization") != want:
            await ws.close(code=1008)
            return
        offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        await ws.accept(subprotocol="tty" if "tty" in offered else None)
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                if msg.get("text") is not None:
                    await ws.send_text("echo:" + msg["text"])
                elif msg.get("bytes") is not None:
                    await ws.send_bytes(b"echo:" + msg["bytes"])
        except WebSocketDisconnect:
            return

    return app


# --- minimal real Lab app: the ACTUAL bridge routes -------------------------

def build_lab_app() -> FastAPI:
    app = FastAPI()

    @app.websocket("/api/cockpit/bridge")
    async def bridge_ws(ws: WebSocket):
        expected = cb._bridge_key()
        presented = ws.headers.get("x-terminal-key")
        if not cb.cockpit_embed_enabled():
            await ws.close(code=1008, reason="disabled")
            return
        import hmac
        if not expected or not presented or not hmac.compare_digest(presented, expected):
            await ws.close(code=1008, reason="bad key")
            return
        bridge = cb.get_bridge()
        await ws.accept()
        await bridge.attach(ws)
        try:
            await bridge.reader_loop(ws)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await bridge.detach(ws)

    async def _proxy(req: Request, path: str):
        if not cb.cockpit_embed_enabled():
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        allowed, _ = cb.cockpit_access(req)
        if not allowed:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        body = await req.body()
        headers = cb.sanitize_request_headers(req.headers)
        bridge = cb.get_bridge()
        norm = path.strip("/")
        inject_base = (norm == "" or norm == "index.html")
        return await bridge.proxy_http(req.method, "/" + path,
                                       cb.strip_token_query(req.url.query), headers, body,
                                       inject_base=inject_base)

    @app.get("/cockpit")
    async def cockpit_root(req: Request):
        return await _proxy(req, "")

    @app.get("/cockpit/{path:path}")
    async def cockpit_get(req: Request, path: str):
        return await _proxy(req, path)

    @app.post("/cockpit/{path:path}")
    async def cockpit_post(req: Request, path: str):
        return await _proxy(req, path)

    @app.websocket("/cockpit/term/{slug}/{tail:path}")
    async def cockpit_term_ws(ws: WebSocket, slug: str, tail: str = ""):
        if not cb.cockpit_embed_enabled():
            await ws.close(code=1008, reason="disabled")
            return
        origin = ws.headers.get("origin", "")
        expected = cb._expected_origin()
        if origin and origin != expected:
            await ws.close(code=1008, reason="bad origin")
            return
        path = f"/term/{slug}/{tail}" if tail else f"/term/{slug}"
        headers = cb.sanitize_request_headers(ws.headers)
        subprotocols = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        await cb.get_bridge().proxy_ws(ws, path, ws.url.query, headers, subprotocols)

    return app


# --- orchestration ----------------------------------------------------------

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


async def run_probe():
    lab_port = _free_port()
    up_port = _free_port()
    os.environ["COCKPIT_EMBED_ENABLED"] = "1"
    os.environ["BRISEN_LAB_COCKPIT_BRIDGE_KEY"] = BRIDGE_KEY
    os.environ["BRISEN_LAB_ORIGIN"] = f"http://127.0.0.1:{lab_port}"
    os.environ.pop("COCKPIT_ACCESS_TOKEN", None)

    cred_file = Path(_HERE / ".probe_credentials")
    cred_file.write_text(CRED)

    lab_server = uvicorn.Server(uvicorn.Config(build_lab_app(), host="127.0.0.1", port=lab_port, log_level="warning"))
    up_server = uvicorn.Server(uvicorn.Config(build_fake_controller(), host="127.0.0.1", port=up_port, log_level="warning"))

    lab_task = asyncio.create_task(lab_server.serve())
    up_task = asyncio.create_task(up_server.serve())

    agent = agent_mod.BridgeAgent(
        lab_ws=f"ws://127.0.0.1:{lab_port}/api/cockpit/bridge",
        upstream=f"http://127.0.0.1:{up_port}",
        cred_path=str(cred_file),
    )
    agent_task = asyncio.create_task(agent.run_forever())

    try:
        # Wait for both servers up.
        for _ in range(200):
            if lab_server.started and up_server.started:
                break
            await asyncio.sleep(0.02)
        # Wait for the agent to connect (bridge.connected True).
        bridge = cb.get_bridge()
        for _ in range(200):
            if bridge.connected:
                break
            await asyncio.sleep(0.02)
        check("agent connected to Lab bridge", bridge.connected)

        base = f"http://127.0.0.1:{lab_port}"
        origin = {"Origin": base}
        async with httpx.AsyncClient(timeout=10) as client:
            # 1. cockpit page renders through the bridge
            r = await client.get(base + "/cockpit/", headers=origin)
            check("GET /cockpit/ -> 200 + page marker",
                  r.status_code == 200 and PAGE_MARKER in r.text, f"status={r.status_code}")

            # 1b. Option A (#12577): the served cockpit page is prefix-aware.
            r = await client.get(base + "/cockpit/", headers=origin)
            ok = (r.status_code == 200
                  and '<base href="/cockpit/">' in r.text
                  and "__COCKPIT_BASE__" in r.text
                  and PAGE_MARKER in r.text)
            check("GET /cockpit/ page carries base-inject (prefix-aware)", ok,
                  f"status={r.status_code}")

            # 1c. ttyd terminal PAGE (HTTP) must NOT be base-injected (would break
            #     the terminal's own relative asset/WS resolution).
            r = await client.get(base + "/cockpit/term/b1/", headers=origin)
            ok = (r.status_code == 200 and "TTYD_PAGE" in r.text
                  and "__COCKPIT_BASE__" not in r.text and '<base href="/cockpit/">' not in r.text)
            check("ttyd page NOT base-injected", ok, f"status={r.status_code}")

            # 2. /api/agents JSON
            r = await client.get(base + "/cockpit/api/agents", headers=origin)
            ok = r.status_code == 200 and r.json().get("agents", [{}])[0].get("slug") == "b1"
            check("GET /cockpit/api/agents -> 200 JSON", ok, f"status={r.status_code}")

            # 3. Start/GO POST through the bridge
            r = await client.post(base + "/cockpit/api/start/b1", headers=origin, content=b"")
            ok = r.status_code == 200 and r.json().get("ok") is True and r.json().get("path") == "api/start/b1"
            check("POST /cockpit/api/start/b1 -> 200", ok, f"status={r.status_code}")

            # 4. inbound Authorization must NOT reach the controller (agent injects its own)
            r = await client.get(base + "/cockpit/api/agents",
                                 headers={**origin, "Authorization": "Basic SNOOP"})
            check("inbound Authorization stripped (still 200)", r.status_code == 200, f"status={r.status_code}")

            # 5. cross-origin rejected -> 404
            r = await client.get(base + "/cockpit/api/agents", headers={"Origin": "https://evil.example"})
            check("cross-origin -> 404", r.status_code == 404, f"status={r.status_code}")

            # 6. flag OFF -> 404 on every path (incl page)
            os.environ["COCKPIT_EMBED_ENABLED"] = "0"
            r1 = await client.get(base + "/cockpit/", headers=origin)
            r2 = await client.get(base + "/cockpit/api/agents", headers=origin)
            check("flag OFF -> 404 on /cockpit paths", r1.status_code == 404 and r2.status_code == 404,
                  f"page={r1.status_code} api={r2.status_code}")
            os.environ["COCKPIT_EMBED_ENABLED"] = "1"

            # 6b. Phase 2 — ttyd WS live terminal round-trip through the bridge.
            try:
                from websockets.asyncio.client import connect as _wsc
            except ImportError:
                from websockets import connect as _wsc  # type: ignore
            ws_url = f"ws://127.0.0.1:{lab_port}/cockpit/term/b1/ws"
            try:
                async with _wsc(ws_url, additional_headers={"Origin": base},
                                subprotocols=["tty"]) as term:
                    await term.send("hello-term")
                    reply = await asyncio.wait_for(term.recv(), timeout=5)
                    sub = getattr(term, "subprotocol", None)
                    check("Phase2 ttyd WS round-trip (echo + subprotocol)",
                          reply == "echo:hello-term" and sub == "tty", f"reply={reply!r} sub={sub!r}")
            except Exception as exc:  # noqa: BLE001
                check("Phase2 ttyd WS round-trip (echo + subprotocol)", False, f"exc={exc}")

            # 6c. Phase 2 — flag OFF closes the terminal WS (never opens).
            os.environ["COCKPIT_EMBED_ENABLED"] = "0"
            ws_closed = False
            try:
                async with _wsc(ws_url, additional_headers={"Origin": base}, subprotocols=["tty"]) as term:
                    await asyncio.wait_for(term.recv(), timeout=2)
            except Exception:
                ws_closed = True
            check("Phase2 flag OFF -> terminal WS refused", ws_closed)
            os.environ["COCKPIT_EMBED_ENABLED"] = "1"

            # 7. agent absent -> 503
            agent_task.cancel()
            try:
                await agent_task
            except asyncio.CancelledError:
                pass
            await bridge.detach(bridge._ws) if bridge._ws else None
            bridge._ws = None
            r = await client.get(base + "/cockpit/api/agents", headers=origin)
            check("agent absent -> 503", r.status_code == 503, f"status={r.status_code}")
    finally:
        for t in (agent_task,):
            t.cancel()
        lab_server.should_exit = True
        up_server.should_exit = True
        await asyncio.gather(lab_task, up_task, return_exceptions=True)
        cred_file.unlink(missing_ok=True)


def main() -> int:
    print("cockpit bridge loopback probe (real uvicorn + real WS + real agent):")
    asyncio.run(run_probe())
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
