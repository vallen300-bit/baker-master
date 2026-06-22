"""Regression anchors for the System Health Console (Workstream C of
BAKER_DASHBOARD_V2_NOISY_COCKPIT_CONSOLIDATED_1 — brief
BAKER_DASHBOARD_V2_SYSTEM_HEALTH_CONSOLE_1).

The console is a *frontend* reshape: it consumes four EXISTING read-only,
auth-gated health endpoints and computes overall status / last-checked in the
browser. No new backend route is added. These tests pin the two backend
invariants the brief calls out for that reuse:

  1. The four health endpoints stay auth-gated (no key -> not 200).
  2. Their payloads are secret-free (no env-var / credential material), and the
     DB-light ones still answer 200 when the database is absent (partial-failure
     degradation is a frontend concern, but the endpoints must not throw secrets
     into an error body either).

No live DB required: ``/api/data-freshness`` is exercised only for the auth gate
(it needs Postgres for content); the other three return safe defaults when their
backing stores are unreachable.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


# Endpoints the System console reads. data-freshness is DB-backed (auth-gate
# only); the rest degrade to safe defaults without a DB.
_HEALTH_ENDPOINTS = [
    "/api/sentinel-health",
    "/api/data-freshness",
    "/api/scheduler-status",
    "/api/triage/verifier/health",
]
_DB_LIGHT_ENDPOINTS = [
    "/api/sentinel-health",
    "/api/scheduler-status",
    "/api/triage/verifier/health",
]

# Substrings that must never appear in a health payload (keys or string values).
_FORBIDDEN = [
    "baker_api_key", "anthropic", "api_key", "apikey", "secret",
    "password", "passwd", "bearer", "x-baker-key", "database_url",
    "postgres://", "voyage", "qdrant_api", "neon_api",
]


@contextmanager
def _client_authless():
    """TestClient with auth bypassed (content/secret checks)."""
    import outputs.dashboard as dash

    dash.app.dependency_overrides[dash.verify_api_key] = lambda: None
    try:
        yield TestClient(dash.app)
    finally:
        dash.app.dependency_overrides.pop(dash.verify_api_key, None)


@contextmanager
def _client_with_key(monkeypatch, key="unit-test-key"):
    """TestClient with a configured API key and NO dependency override, so the
    real ``verify_api_key`` runs."""
    import outputs.dashboard as dash

    monkeypatch.setattr(dash, "_BAKER_API_KEY", key, raising=False)
    # Ensure no stray override leaks in from another test.
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    yield TestClient(dash.app), key


def _walk_strings(obj):
    """Yield every key and string value in a nested JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_strings(item)
    elif isinstance(obj, str):
        yield obj


@pytest.mark.parametrize("path", _HEALTH_ENDPOINTS)
def test_health_endpoint_requires_auth(monkeypatch, path):
    """No X-Baker-Key -> the endpoint must NOT serve a 200 health payload."""
    with _client_with_key(monkeypatch) as (client, _key):
        resp = client.get(path)
    assert resp.status_code != 200, (
        f"{path} served a 200 without an API key — auth gate missing"
    )
    assert resp.status_code in (401, 403), (
        f"{path} returned {resp.status_code}, expected 401/403 for missing key"
    )


@pytest.mark.parametrize("path", _HEALTH_ENDPOINTS)
def test_health_endpoint_accepts_valid_key(monkeypatch, path):
    """A correct key passes the gate (status is not the 401/403 auth refusal).

    Content may still be 200 or a DB-driven 5xx for data-freshness; the point
    here is only that the gate itself opens with the right key."""
    with _client_with_key(monkeypatch) as (client, key):
        resp = client.get(path, headers={"X-Baker-Key": key})
    assert resp.status_code not in (401, 403), (
        f"{path} rejected a valid key with {resp.status_code}"
    )


@pytest.mark.parametrize("path", _DB_LIGHT_ENDPOINTS)
def test_db_light_endpoint_ok_without_database(path):
    """sentinel / scheduler / verifier health degrade to a safe 200 with no DB
    (so the console renders a real partial-failure state, not a hard error)."""
    with _client_authless() as client:
        resp = client.get(path)
    assert resp.status_code == 200, (
        f"{path} returned {resp.status_code} without a DB; expected safe 200"
    )
    assert isinstance(resp.json(), dict)


@pytest.mark.parametrize("path", _DB_LIGHT_ENDPOINTS)
def test_health_payload_has_no_secrets(path):
    """Health payloads must not leak env vars / credentials (brief hard
    exclusion: no secrets, no env-var display)."""
    with _client_authless() as client:
        resp = client.get(path)
    assert resp.status_code == 200
    blob = json.dumps(resp.json()).lower()
    for needle in _FORBIDDEN:
        assert needle not in blob, (
            f"{path} payload contains forbidden token {needle!r}: secret leak"
        )
    # Also scan structurally so a forbidden token never hides as a bare key.
    for token in _walk_strings(resp.json()):
        low = token.lower()
        for needle in _FORBIDDEN:
            assert needle not in low, (
                f"{path} exposes {needle!r} via {token!r}"
            )
