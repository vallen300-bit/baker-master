"""Laptop bridge agent tests (baker-master).

COCKPIT_IN_LAB_BRIDGE_1 — key resolution precedence, Basic-auth injection,
inbound-Authorization stripping, and the OPEN/DATA/END -> upstream -> response
frames path (fake ws + fake httpx client). No network, no real controller.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import sys

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_SCRIPTS, filename))
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


mux = _load("cockpit_mux", "cockpit_mux.py")
agent_mod = _load("cockpit_bridge_agent", "cockpit_bridge_agent.py")


# --- fakes ------------------------------------------------------------------


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FakeResponse:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content


class FakeClient:
    """Records the outbound request, returns a canned response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def request(self, method, url, headers=None, content=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "content": content})
        return self._response


# --- key resolution ---------------------------------------------------------


def test_resolve_key_env_first(monkeypatch):
    monkeypatch.setenv("BRISEN_LAB_COCKPIT_BRIDGE_KEY", "envkey")
    assert agent_mod.resolve_bridge_key() == "envkey"


def test_resolve_key_from_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("BRISEN_LAB_COCKPIT_BRIDGE_KEY", raising=False)
    monkeypatch.delenv("BRISEN_LAB_TERMINAL_KEY", raising=False)
    cache = tmp_path / "cockpit-bridge"
    cache.write_text("cachekey\n")
    monkeypatch.setattr(agent_mod, "_key_cache_file", lambda slug: cache)
    # avoid a real `op` call in the fallback path
    monkeypatch.setenv("PATH", "")
    assert agent_mod.resolve_bridge_key() == "cachekey"


def test_load_basic_auth_format(tmp_path):
    cred = tmp_path / "credentials"
    cred.write_text("director:hunter2")
    header = agent_mod.load_basic_auth(str(cred))
    assert header == "Basic " + base64.b64encode(b"director:hunter2").decode()


def test_load_basic_auth_missing_returns_none(tmp_path):
    assert agent_mod.load_basic_auth(str(tmp_path / "nope")) is None


# --- upstream request shape -------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_injects_auth_and_origin(monkeypatch, tmp_path):
    cred = tmp_path / "credentials"
    cred.write_text("u:p")
    agent = agent_mod.BridgeAgent(lab_ws="wss://x/bridge",
                                  upstream="http://127.0.0.1:7800", cred_path=str(cred))
    agent._client = FakeClient(FakeResponse(200, {"content-type": "text/html"}, b"<html>"))
    head = {"method": "GET", "path": "/api/agents", "query": "x=1",
            "headers": {"Authorization": "Basic SNOOP", "X-Keep": "yes", "Host": "evil"}}
    resp = await agent._proxy_to_controller(head, b"")
    call = agent._client.calls[0]
    assert call["url"] == "http://127.0.0.1:7800/api/agents?x=1"
    # inbound Authorization dropped; local Basic-auth injected
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"u:p").decode()
    # Host/Origin forced to controller authority (OriginGuard)
    assert call["headers"]["Host"] == "127.0.0.1:7800"
    assert call["headers"]["Origin"] == "http://127.0.0.1:7800"
    assert call["headers"]["X-Keep"] == "yes"
    assert resp.status_code == 200


# --- OPEN/DATA/END -> response frames ---------------------------------------


@pytest.mark.asyncio
async def test_request_lifecycle_emits_response_frames(tmp_path):
    cred = tmp_path / "credentials"
    cred.write_text("u:p")
    agent = agent_mod.BridgeAgent(lab_ws="wss://x/bridge",
                                  upstream="http://127.0.0.1:7800", cred_path=str(cred))
    agent._client = FakeClient(FakeResponse(200, {"content-type": "application/json"}, b'{"ok":1}'))
    ws = FakeWS()
    sid = 5
    head = json.dumps({"method": "GET", "path": "/api/agents", "query": "", "headers": {}}).encode()
    await agent._on_frame(ws, mux.Frame(sid, mux.OPEN, head))
    await agent._on_frame(ws, mux.Frame(sid, mux.END, b""))
    # _on_frame schedules the handler as a task; let it run.
    await asyncio.sleep(0.05)

    frames, leftover = mux.iter_frames(b"".join(ws.sent))
    assert leftover == b""
    types = [f.type for f in frames]
    assert types == [mux.OPEN, mux.DATA, mux.END]
    resp_head = json.loads(frames[0].payload.decode())
    assert resp_head["status"] == 200
    assert frames[1].payload == b'{"ok":1}'
    assert all(f.stream_id == sid for f in frames)


@pytest.mark.asyncio
async def test_ping_replies_pong():
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path="/none")
    ws = FakeWS()
    await agent._on_frame(ws, mux.Frame(0, mux.PING, b""))
    frames, _ = mux.iter_frames(b"".join(ws.sent))
    assert [f.type for f in frames] == [mux.PONG]


@pytest.mark.asyncio
async def test_upstream_error_sends_502(tmp_path):
    import httpx
    cred = tmp_path / "credentials"
    cred.write_text("u:p")

    class BoomClient:
        async def request(self, *a, **k):
            raise httpx.ConnectError("refused")

    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path=str(cred))
    agent._client = BoomClient()
    ws = FakeWS()
    sid = 9
    head = json.dumps({"method": "GET", "path": "/x", "query": "", "headers": {}}).encode()
    await agent._handle_request(ws, sid, {"head": json.loads(head), "body": bytearray()})
    frames, _ = mux.iter_frames(b"".join(ws.sent))
    resp_head = json.loads(frames[0].payload.decode())
    assert resp_head["status"] == 502
