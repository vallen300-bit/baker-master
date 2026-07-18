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


class FakeUpstreamWS:
    """Agent-side upstream (ttyd) double: async-iterates canned messages."""

    def __init__(self, messages, subprotocol="tty"):
        self._messages = list(messages)
        self.subprotocol = subprotocol
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self._messages:
            yield m

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_handle_ws_acks_and_pipes(monkeypatch, tmp_path):
    cred = tmp_path / "credentials"
    cred.write_text("u:p")
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path=str(cred))

    captured = {}

    def fake_connect(target, **kwargs):
        captured["target"] = target
        captured["headers"] = kwargs.get("additional_headers")
        captured["subprotocols"] = kwargs.get("subprotocols")
        return FakeUpstreamWS(messages=["term-output"], subprotocol="tty")

    monkeypatch.setattr(agent_mod, "ws_connect", fake_connect)

    lab_ws = FakeWS()
    inbound = asyncio.Queue()
    head = {"path": "/term/b1/ws", "query": "", "headers": {}, "subprotocols": ["tty"]}
    await agent._handle_ws(lab_ws, 3, head, inbound)

    # Upstream dialed at the ws:// authority with the ttyd path; NO manual Host.
    assert captured["target"] == "ws://127.0.0.1:7800/term/b1/ws"
    assert "Host" not in captured["headers"]
    assert captured["headers"]["Origin"] == "http://127.0.0.1:7800"
    assert captured["headers"]["Authorization"].startswith("Basic ")

    frames, _ = mux.iter_frames(b"".join(lab_ws.sent))
    types = [f.type for f in frames]
    # WS_OPEN ack (with subprotocol), WS_DATA(term-output), then WS_CLOSE.
    assert types[0] == mux.WS_OPEN
    assert json.loads(frames[0].payload.decode())["subprotocol"] == "tty"
    assert mux.WS_DATA in types
    data_frame = next(f for f in frames if f.type == mux.WS_DATA)
    assert data_frame.payload == bytes([mux.WS_KIND_TEXT]) + b"term-output"
    assert types[-1] == mux.WS_CLOSE


@pytest.mark.asyncio
async def test_handle_ws_suppresses_lab_close_race(monkeypatch, tmp_path):
    """finally WS_CLOSE must not crash when the Lab socket already closed.

    Models codex's ConnectionClosedOK race: the ttyd stream tears down after
    the Director closed the tab / the Lab reconnected, so lab_ws.send raises
    ConnectionClosed on the finally WS_CLOSE. _handle_ws must swallow it.
    """
    from websockets.exceptions import ConnectionClosed

    class ClosingLabWS:
        """Succeeds for the WS_OPEN ack + piped WS_DATA, then the Lab socket is
        gone so every later send raises ConnectionClosed (incl. the finally)."""

        def __init__(self, ok_sends):
            self.sent = []
            self._ok = ok_sends

        async def send(self, data):
            if len(self.sent) >= self._ok:
                raise ConnectionClosed(None, None)
            self.sent.append(data)

    cred = tmp_path / "credentials"
    cred.write_text("u:p")
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path=str(cred))
    monkeypatch.setattr(
        agent_mod, "ws_connect",
        lambda target, **kw: FakeUpstreamWS(messages=["term-output"], subprotocol="tty"),
    )

    lab_ws = ClosingLabWS(ok_sends=2)  # WS_OPEN + WS_DATA ok; WS_CLOSE raises
    inbound = asyncio.Queue()
    head = {"path": "/term/b1/ws", "query": "", "headers": {}, "subprotocols": ["tty"]}
    # Must return cleanly — the finally's WS_CLOSE close-race is suppressed.
    await agent._handle_ws(lab_ws, 3, head, inbound)
    assert 3 not in agent._ws_streams


@pytest.mark.asyncio
async def test_oversize_request_body_resets_stream(monkeypatch):
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path="/none")
    monkeypatch.setattr(agent_mod, "_MAX_STREAM_BODY", 8)
    ws = FakeWS()
    sid = 3
    head = json.dumps({"method": "POST", "path": "/x", "query": "", "headers": {}}).encode()
    await agent._on_frame(ws, mux.Frame(sid, mux.OPEN, head))
    await agent._on_frame(ws, mux.Frame(sid, mux.DATA, b"0123456789"))  # 10 > 8
    await asyncio.sleep(0.02)  # let the RESET task run
    assert sid not in agent._streams
    frames, _ = mux.iter_frames(b"".join(ws.sent))
    assert any(f.type == mux.RESET for f in frames)


def test_reset_connection_state_cancels_ws_tasks_and_clears():
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path="/none")

    async def _drive():
        async def _sleeper():
            await asyncio.sleep(100)
        t = asyncio.ensure_future(_sleeper())
        agent._ws_tasks[1] = t
        agent._ws_streams[1] = asyncio.Queue()
        agent._streams[2] = {"head": {}, "body": bytearray()}
        agent._reset_connection_state()
        await asyncio.sleep(0)  # let the cancel propagate
        assert agent._ws_tasks == {}
        assert agent._ws_streams == {}
        assert agent._streams == {}
        assert t.cancelled()

    asyncio.get_event_loop().run_until_complete(_drive())


@pytest.mark.asyncio
async def test_ws_frames_route_to_stream_queue():
    agent = agent_mod.BridgeAgent(lab_ws="wss://x", upstream="http://127.0.0.1:7800", cred_path="/none")
    ws = FakeWS()
    q = asyncio.Queue()
    agent._ws_streams[4] = q
    await agent._on_frame(ws, mux.Frame(4, mux.WS_DATA, bytes([mux.WS_KIND_TEXT]) + b"x"))
    await agent._on_frame(ws, mux.Frame(4, mux.WS_CLOSE, b""))
    assert q.qsize() == 2
    assert q.get_nowait().type == mux.WS_DATA
    assert q.get_nowait().type == mux.WS_CLOSE


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
