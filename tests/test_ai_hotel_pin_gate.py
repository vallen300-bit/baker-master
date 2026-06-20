"""AI_HOTEL_PIN_GATE_1 — short PIN -> scoped AI-Hotel read cookie.

The master X-Baker-Key is still the only write/admin credential. The PIN flow
sets an httpOnly signed cookie that is accepted only by AI-Hotel read routes.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable in this interpreter",
)


class _Cur:
    def __init__(self):
        self._res = []

    def execute(self, sql, params=None):
        if "FROM ai_hotel_captures" in sql:
            self._res = []
        else:
            self._res = []

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res

    def close(self):
        pass


class _Conn:
    def cursor(self, cursor_factory=None):
        return _Cur()

    def commit(self):
        pass

    def rollback(self):
        pass


class _Store:
    def _get_conn(self):
        return _Conn()

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, *, pin="6470", session_secret="session-secret"):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash

    monkeypatch.setattr(dash, "_BAKER_API_KEY", "master-key")
    if pin is None:
        monkeypatch.delenv("AI_HOTEL_PIN", raising=False)
    else:
        monkeypatch.setenv("AI_HOTEL_PIN", pin)
    if session_secret is None:
        monkeypatch.delenv("AI_HOTEL_SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("AI_HOTEL_SESSION_SECRET", session_secret)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", 5)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_FAILURES", 10)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_S", 900)
    dash._ai_hotel_pin_state.clear()
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    dash.app.dependency_overrides.pop(dash.verify_ai_hotel_read_access, None)
    monkeypatch.setattr(dash, "_get_store", lambda: _Store())
    return TestClient(dash.app, base_url="https://testserver"), dash


def test_pin_route_and_scoped_read_dependency_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/ai-hotel/pin-auth"' in src
    assert "hmac.compare_digest(supplied, expected)" in src
    assert 'os.getenv("AI_HOTEL_PIN") or "6470"' not in src
    assert 'os.getenv("AI_HOTEL_SESSION_SECRET") or _BAKER_API_KEY' not in src
    assert "client_ip_source=%s" in src
    log_block = src[
        src.index("logger.info(\n        \"ai_hotel PIN auth client_ip_source"):
        src.index("_ai_hotel_pin_rate_check(ip)")
    ]
    assert "payload.pin" not in log_block
    assert 'key=_AI_HOTEL_SESSION_COOKIE' in src
    assert 'httponly=True' in src and 'secure=True' in src and 'samesite="strict"' in src

    list_seg = src[src.index('@app.get("/api/ai-hotel/captures"'):src.index("async def ai_hotel_captures(")]
    assert "verify_ai_hotel_read_access" in list_seg
    write_seg = src[src.index('@app.post("/api/ai-hotel/capture"'):src.index("async def ai_hotel_capture(")]
    assert "verify_api_key" in write_seg
    presign_seg = src[src.index('media/presign"'):src.index("async def ai_hotel_capture_media_presign(")]
    assert "verify_api_key" in presign_seg


def test_pin_ui_uses_cookie_flow_without_key_storage():
    src = Path("outputs/static/ai-hotel.html").read_text()
    seg = src[src.index("function renderKeyEntry(main)"):src.index("function renderNotes(main)")]
    assert "Enter access code" in seg
    assert "fetch('/api/ai-hotel/pin-auth'" in seg
    assert "credentials:'same-origin'" in seg
    assert "Code not accepted" in seg
    assert "localStorage.setItem('aih.key',p)" not in seg
    assert "X-Baker-Key':p" not in seg
    assert "aiHotelReadOptions()" in src


@_skip
def test_pin_success_sets_secure_cookie_and_reads_only_ai_hotel(monkeypatch):
    client, _dash = _client(monkeypatch)

    resp = client.post(
        "/api/ai-hotel/pin-auth",
        json={"pin": "6470"},
        headers={"x-forwarded-for": "198.51.100.10"},
    )

    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers["set-cookie"]
    assert "aih_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "Path=/api/ai-hotel" in set_cookie
    assert "master-key" not in resp.text
    assert "master-key" not in set_cookie

    # Cookie alone can read AI-Hotel field notes.
    assert client.get("/api/ai-hotel/captures").status_code == 200
    # The same cookie does not satisfy the global Baker auth dependency.
    assert client.get("/api/status").status_code == 401


@_skip
def test_wrong_pin_is_generic_401(monkeypatch):
    client, _dash = _client(monkeypatch)

    resp = client.post(
        "/api/ai-hotel/pin-auth",
        json={"pin": "0000"},
        headers={"x-forwarded-for": "198.51.100.11"},
    )

    assert resp.status_code == 401
    assert "master-key" not in resp.text
    assert "0000" not in resp.text


@_skip
def test_pin_auth_fails_closed_without_configured_pin(monkeypatch):
    client, _dash = _client(monkeypatch, pin=None)

    resp = client.post(
        "/api/ai-hotel/pin-auth",
        json={"pin": "6470"},
        headers={"x-forwarded-for": "198.51.100.14"},
    )

    assert resp.status_code == 503
    assert "aih_session=" not in resp.headers.get("set-cookie", "")


@_skip
def test_pin_auth_requires_dedicated_session_secret(monkeypatch):
    client, _dash = _client(monkeypatch, session_secret=None)

    resp = client.post(
        "/api/ai-hotel/pin-auth",
        json={"pin": "6470"},
        headers={"x-forwarded-for": "198.51.100.15"},
    )

    assert resp.status_code == 503
    assert "master-key" not in resp.text
    assert "aih_session=" not in resp.headers.get("set-cookie", "")


@_skip
def test_pin_rate_limit_and_lockout(monkeypatch):
    client, dash = _client(monkeypatch)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_FAILURES", 10)
    ip = "198.51.100.12"

    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0000"}, headers={"x-forwarded-for": ip}).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0001"}, headers={"x-forwarded-for": ip}).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0002"}, headers={"x-forwarded-for": ip}).status_code == 429

    client, dash = _client(monkeypatch)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", 50)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_FAILURES", 3)
    ip = "198.51.100.13"
    for wrong in ("1000", "1001", "1002"):
        assert client.post("/api/ai-hotel/pin-auth", json={"pin": wrong}, headers={"x-forwarded-for": ip}).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "6470"}, headers={"x-forwarded-for": ip}).status_code == 429


@_skip
def test_cf_connecting_ip_is_limiter_key(monkeypatch):
    client, dash = _client(monkeypatch)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_FAILURES", 10)

    # Render is Cloudflare-fronted; Cloudflare sets CF-Connecting-IP to the
    # observed client IP. The limiter must key off that header when present.
    headers = [
        {"cf-connecting-ip": "198.51.100.20"},
        {"cf-connecting-ip": "198.51.100.20"},
        {"cf-connecting-ip": "198.51.100.20"},
    ]

    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0000"}, headers=headers[0]).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0001"}, headers=headers[1]).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0002"}, headers=headers[2]).status_code == 429


@_skip
def test_spoofed_xff_cannot_influence_key_when_cf_connecting_ip_present(monkeypatch):
    client, dash = _client(monkeypatch)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_LOCKOUT_FAILURES", 10)

    headers = [
        {"cf-connecting-ip": "198.51.100.21", "x-forwarded-for": "203.0.113.1"},
        {"cf-connecting-ip": "198.51.100.21", "x-forwarded-for": "203.0.113.2"},
        {"cf-connecting-ip": "198.51.100.21", "x-forwarded-for": "203.0.113.3"},
    ]

    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0000"}, headers=headers[0]).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0001"}, headers=headers[1]).status_code == 401
    assert client.post("/api/ai-hotel/pin-auth", json={"pin": "0002"}, headers=headers[2]).status_code == 429


def test_client_ip_header_fallbacks_are_fault_tolerant():
    import outputs.dashboard as dash

    class _Headers:
        def __init__(self, vals):
            self.vals = vals

        def getlist(self, name):
            return self.vals.get(name, [])

    class _Client:
        host = "127.0.0.1"

    class _Req:
        def __init__(self, vals):
            self.headers = _Headers(vals)
            self.client = _Client()

    assert dash._ai_hotel_client_ip(_Req({"cf-connecting-ip": ["", "198.51.100.22"]})) == "198.51.100.22"
    assert dash._ai_hotel_client_ip(_Req({"true-client-ip": ["198.51.100.23"]})) == "198.51.100.23"
    assert dash._ai_hotel_client_ip(_Req({"x-forwarded-for": ["203.0.113.99"]})) == "127.0.0.1"


def test_pin_state_prunes_stale_entries(monkeypatch):
    import outputs.dashboard as dash

    now = time.time()
    stale = now - dash._AI_HOTEL_PIN_WINDOW_S - dash._AI_HOTEL_PIN_LOCKOUT_S - 30
    dash._ai_hotel_pin_state.clear()
    dash._ai_hotel_pin_state.update({
        "198.51.100.30": {
            "attempts": [stale],
            "failures": 1,
            "locked_until": stale,
            "last_seen": stale,
        },
        "198.51.100.31": {
            "attempts": [now],
            "failures": 1,
            "locked_until": 0.0,
            "last_seen": now,
        },
    })

    dash._ai_hotel_pin_rate_check("198.51.100.32")

    assert "198.51.100.30" not in dash._ai_hotel_pin_state
    assert "198.51.100.31" in dash._ai_hotel_pin_state
    assert "198.51.100.32" in dash._ai_hotel_pin_state


def test_pin_state_hard_cap_evicts_oldest(monkeypatch):
    import outputs.dashboard as dash

    now = time.time()
    monkeypatch.setattr(dash, "_AI_HOTEL_PIN_STATE_MAX", 2)
    dash._ai_hotel_pin_state.clear()
    dash._ai_hotel_pin_state.update({
        "198.51.100.40": {
            "attempts": [now - 10],
            "failures": 1,
            "locked_until": 0.0,
            "last_seen": now - 10,
        },
        "198.51.100.41": {
            "attempts": [now - 5],
            "failures": 1,
            "locked_until": 0.0,
            "last_seen": now - 5,
        },
    })

    dash._ai_hotel_pin_rate_check("198.51.100.42")

    assert len(dash._ai_hotel_pin_state) <= 2
    assert "198.51.100.40" not in dash._ai_hotel_pin_state
    assert "198.51.100.42" in dash._ai_hotel_pin_state
