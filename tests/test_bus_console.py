"""Tests for BUS_CONSOLE_LIVE_PAGE_1 — the Director-facing read-only bus console.

Brief: briefs/_tasks/BUS_CONSOLE_LIVE_PAGE_1.md.

Coverage (per brief §AC):
  AC1 — /bus-console + /api/bus-console.json are PIN-gated: 404 unauth, 200 with
        PIN (?pin= / ?key= / cookie).
  AC2 — /api/bus-console.json returns real bus rows; NO terminal-key string
        anywhere in the served HTML/JS (server-side proxy only).
  AC3 — recipient + unacked-only filters work (server-side, deterministic).
  AC4 — brisen-lab unreachable → honest banner data (bus_ok False), page still
        renders HTTP 200 (never a stack trace).

The proxy fetch is monkeypatched so tests never hit the live brisen-lab daemon,
except AC4's connection-refused case which exercises the real except handler.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PIN = "123456"

SAMPLE_ROWS = [
    {"id": 9001, "from": "lead", "to": ["b4"], "topic": "dispatch/x", "kind": "dispatch",
     "body_preview": "start work", "created_at": "2026-07-11T10:00:00+00:00", "acknowledged_at": "2026-07-11T10:01:00+00:00"},
    {"id": 9002, "from": "b4", "to": ["lead"], "topic": "ship/x", "kind": "dispatch",
     "body_preview": "shipped", "created_at": "2026-07-11T10:05:00+00:00", "acknowledged_at": None},
    {"id": 9003, "from": "deputy", "to": ["b3"], "topic": "note/y", "kind": "dispatch",
     "body_preview": "fyi", "created_at": "2026-07-11T10:07:00+00:00", "acknowledged_at": None},
]


def _client(monkeypatch, rows=None, bus_ok=True, bus_error=None):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("ARRIVALS_BOARD_PIN", PIN)
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)

    if rows is not None or not bus_ok:
        def fake_fetch(recipient=None, limit=200):
            return {
                "bus_ok": bus_ok,
                "bus_error": bus_error,
                "source": "msg/all" if bus_ok else None,
                "rows": list(rows or []),
                "count": len(rows or []),
            }
        monkeypatch.setattr(dashboard, "_bus_console_fetch", fake_fetch)

    return TestClient(dashboard.app, base_url="https://testserver")


# --- AC1 -------------------------------------------------------------------
def test_bus_console_auth_gate(monkeypatch):
    client = _client(monkeypatch, rows=SAMPLE_ROWS)

    assert client.get("/bus-console").status_code == 404
    assert client.get("/api/bus-console.json").status_code == 404
    assert client.get("/bus-console?pin=000000").status_code == 404

    page = client.get("/bus-console?key=test-key")
    assert page.status_code == 200
    assert "BUS CONSOLE" in page.text

    pin_page = client.get("/bus-console?pin=" + PIN)
    assert pin_page.status_code == 200
    set_cookie = pin_page.headers.get("set-cookie", "")
    assert "arrivals_board_access" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    # ARRIVALS_EMBED_COOKIE_FIX_1: bus-console reuses the shared
    # arrivals_board_access cookie helper, so it inherits SameSite=None. The
    # cookie stays HttpOnly (unreadable cross-site); the bus-console page itself
    # is NOT reframed with a frame-ancestors CSP by this brief (arrivals-scoped)
    # — flagged to lead as a follow-up (read-only surface, low clickjacking risk).
    assert "SameSite=none" in set_cookie

    # cookie now carries → bare request authorized
    assert client.get("/bus-console").status_code == 200


# --- AC2 -------------------------------------------------------------------
def test_bus_console_json_rows_and_no_key_leak(monkeypatch):
    client = _client(monkeypatch, rows=SAMPLE_ROWS)

    resp = client.get("/api/bus-console.json?key=test-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bus_ok"] is True
    assert body["count"] == 3
    assert {r["id"] for r in body["rows"]} == {9001, 9002, 9003}

    # No terminal-key material anywhere in the served page HTML/JS.
    page = client.get("/bus-console?key=test-key").text
    for needle in ("X-Terminal-Key", "BRISEN_LAB_CONSOLE_KEY", "BRISEN_LAB_TERMINAL_KEY"):
        assert needle not in page, f"{needle} leaked into served page"


def test_template_file_has_no_key_reference():
    from pathlib import Path
    tpl = Path(__file__).resolve().parents[1] / "outputs" / "templates" / "bus_console_template.html"
    text = tpl.read_text(encoding="utf-8")
    assert "X-Terminal-Key" not in text
    assert "CONSOLE_KEY" not in text


# --- AC3 -------------------------------------------------------------------
def test_bus_console_recipient_filter(monkeypatch):
    client = _client(monkeypatch, rows=SAMPLE_ROWS)
    resp = client.get("/api/bus-console.json?key=test-key&recipient=b3")
    assert resp.status_code == 200
    body = resp.json()
    # only the deputy->b3 row matches
    assert body["count"] == 1
    assert body["rows"][0]["id"] == 9003
    assert body["recipient"] == "b3"


def test_bus_console_unacked_filter(monkeypatch):
    client = _client(monkeypatch, rows=SAMPLE_ROWS)
    resp = client.get("/api/bus-console.json?key=test-key&unacked_only=1")
    assert resp.status_code == 200
    body = resp.json()
    ids = {r["id"] for r in body["rows"]}
    assert ids == {9002, 9003}  # 9001 is acked → excluded
    assert body["unacked_only"] is True


# --- AC4 -------------------------------------------------------------------
def test_bus_console_unreachable_banner(monkeypatch):
    """Bus proxy fails → honest bus_ok False, page still 200 (no stack trace)."""
    client = _client(monkeypatch, bus_ok=False, bus_error="ConnectionError: refused")

    resp = client.get("/api/bus-console.json?key=test-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bus_ok"] is False
    assert body["bus_error"]
    assert body["rows"] == []

    # page itself must still render
    assert client.get("/bus-console?key=test-key").status_code == 200


def test_bus_console_real_fetch_connection_refused(monkeypatch):
    """Exercise the REAL _bus_console_fetch except path against a dead host."""
    monkeypatch.setenv("BRISEN_LAB_CONSOLE_KEY", "dummy-key")
    monkeypatch.setenv("BRISEN_LAB_DAEMON_URL", "http://127.0.0.1:9")  # refuses instantly
    from outputs import dashboard
    result = dashboard._bus_console_fetch(limit=10)
    assert result["bus_ok"] is False
    assert result["bus_error"]
    assert result["rows"] == []


def test_bus_console_no_key_configured(monkeypatch):
    """No console key → honest 'not configured', never a crash."""
    monkeypatch.delenv("BRISEN_LAB_CONSOLE_KEY", raising=False)
    from outputs import dashboard
    result = dashboard._bus_console_fetch(limit=10)
    assert result["bus_ok"] is False
    assert "not configured" in result["bus_error"]


# --- regression: /api/bus-console.json must NOT block the event loop --------
# (codex G3 P1: the async endpoint calls a blocking requests-based fetch; it
# must be offloaded to a thread so a slow upstream can't starve the worker.)
def test_bus_console_json_does_not_block_event_loop(monkeypatch):
    import asyncio
    import time as _time
    from starlette.requests import Request
    from outputs import dashboard

    monkeypatch.setenv("ARRIVALS_BOARD_PIN", PIN)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)

    # Simulate a SLOW blocking upstream (like a stalled requests.get).
    def slow_fetch(recipient=None, limit=200):
        _time.sleep(0.30)
        return {"bus_ok": True, "bus_error": None, "source": "msg/all", "rows": [], "count": 0}
    monkeypatch.setattr(dashboard, "_bus_console_fetch", slow_fetch)

    def _make_request():
        scope = {
            "type": "http", "method": "GET", "path": "/api/bus-console.json",
            "query_string": b"key=test-key", "headers": [], "client": ("test", 1),
        }
        return Request(scope)

    async def scenario():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        await asyncio.sleep(0)  # let the ticker start before the fetch
        resp = await dashboard.bus_console_json(_make_request())
        ticks_at_finish = ticks  # ticks accumulated DURING the ~0.30s fetch
        stop = True
        await t
        return ticks_at_finish, resp.status_code

    ticks, status = asyncio.run(scenario())
    assert status == 200
    # If the 0.30s blocking fetch ran on the loop thread, the ticker is starved
    # during that window (~0 ticks). Offloaded to a thread → ~30 ticks elapse.
    assert ticks >= 15, f"event loop was blocked during fetch (ticks={ticks})"
