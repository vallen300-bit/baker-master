"""HEALTH_PROBE_SLIM_1 — Render health check must be a cheap liveness probe.

Incident 2026-06-30T08:48Z: Render's 5s HTTP health probe pointed at the heavy
`/health` (DB + Qdrant + sentinel iteration + object-store) was starved while a
23s dashboard request saturated the single instance. Render restarted a live
process — a ~78s self-inflicted outage worse than the transient blip.

Fix: a `/livez` (alias `/healthz`) probe that does NO I/O — it answers only "is
the event loop responsive?". Render's healthCheckPath repoints to `/livez`; the
rich `/health` stays for monitoring/dashboard consumers.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ─── Source-level checks (always run, no import needed) ──────────────────────


def _livez_body() -> str:
    src = Path("outputs/dashboard.py").read_text()
    start = src.index("async def liveness_probe()")
    return src[start:src.index("async def health_check()")]


def test_livez_and_healthz_routes_registered():
    src = Path("outputs/dashboard.py").read_text()
    assert '@app.get("/livez"' in src
    assert '@app.get("/healthz"' in src


def test_liveness_probe_does_no_io():
    """Kill criterion: a probe that touches DB/Qdrant/sentinel/store would
    reintroduce the starvation failure mode the fix removes."""
    body = _livez_body()
    for forbidden in ("_get_store", "_get_conn", "qdrant", "sentinel_health",
                      "mirror_status", "storage_health", "await "):
        assert forbidden not in body, f"liveness probe must not call {forbidden!r}"
    assert 'return {"status": "ok"}' in body


# ─── Functional checks (TestClient on the real app) ──────────────────────────


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


@_skip
def test_livez_returns_ok_fast():
    from fastapi.testclient import TestClient
    from outputs.dashboard import app

    client = TestClient(app)
    for path in ("/livez", "/healthz"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
        assert r.json() == {"status": "ok"}, path
