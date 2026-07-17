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
        return PlainTextResponse(PAGE_MARKER + "\n<html>cockpit</html>", media_type="text/html")

    @app.post("/{path:path}")
    async def any_post(req: Request, path: str = ""):
        if not _check_auth(req):
            return JSONResponse({"detail": "auth required"}, status_code=401)
        body = await req.body()
        return JSONResponse({"ok": True, "path": path, "echo": body.decode() or None})

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
        return await bridge.proxy_http(req.method, "/" + path, req.url.query, headers, body)

    @app.get("/cockpit")
    async def cockpit_root(req: Request):
        return await _proxy(req, "")

    @app.get("/cockpit/{path:path}")
    async def cockpit_get(req: Request, path: str):
        return await _proxy(req, path)

    @app.post("/cockpit/{path:path}")
    async def cockpit_post(req: Request, path: str):
        return await _proxy(req, path)

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
