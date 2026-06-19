"""STATIC_HTML_NOCACHE_REVALIDATE_1 — static HTML must revalidate every load.

Director opened the AI-Hotel dashboard after the #381 deploy and saw a STALE
cached page (the StaticFiles mount set etag + last-modified but no Cache-Control,
so browsers/iOS-PWA heuristically cached the HTML). The fix stamps
`Cache-Control: no-cache` on text/html responses only — keeping the cheap etag
304 path for unchanged files.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ─── Source-level checks (always run) ───────────────────────────────────────


def test_mount_uses_nocache_subclass():
    src = Path("outputs/dashboard.py").read_text()
    assert "class NoCacheHTMLStaticFiles(StaticFiles):" in src
    # the mount swaps the bare StaticFiles for the subclass
    assert 'app.mount("/static", NoCacheHTMLStaticFiles(directory=str(_static_dir)), name="static")' in src
    # bare StaticFiles must no longer be mounted at /static
    assert 'app.mount("/static", StaticFiles(' not in src


def test_uses_no_cache_not_no_store():
    """Kill criterion: no-store would kill the cheap 304 path. (The docstring
    explains why no-store is avoided — check the assigned value, not prose.)"""
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("class NoCacheHTMLStaticFiles"):src.index("class NoCacheHTMLStaticFiles") + 1400]
    assert 'resp.headers["Cache-Control"] = "no-cache"' in seg
    assert '"no-store"' not in seg          # never assigned (docstring uses ``no-store`` backticks)


# ─── Functional checks (TestClient) ─────────────────────────────────────────


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


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    app = FastAPI()
    app.mount("/static", dash.NoCacheHTMLStaticFiles(directory="outputs/static"), name="static")
    return TestClient(app)


@_skip
def test_ac1_html_carries_no_cache():
    client = _client()
    r = client.get("/static/ai-hotel.html")
    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == "no-cache"
    assert r.headers.get("content-type", "").startswith("text/html")


@_skip
def test_ac1_capture_page_also_no_cache():
    client = _client()
    r = client.get("/static/ai-hotel-capture.html")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


@_skip
def test_ac2_non_html_not_forced_no_cache():
    client = _client()
    for asset in ("style.css", "app.js", "manifest.json"):
        r = client.get(f"/static/{asset}")
        assert r.status_code == 200, asset
        # a non-HTML asset must NOT be force-stamped no-cache (normal caching)
        assert r.headers.get("cache-control") != "no-cache", asset
        assert not r.headers.get("content-type", "").startswith("text/html"), asset


@_skip
def test_ac3_body_served_and_etag_intact():
    client = _client()
    r = client.get("/static/ai-hotel.html")
    assert r.status_code == 200
    assert b"Field notes" in r.content          # real body, no serve regression
    etag = r.headers.get("etag")
    assert etag                                  # etag still present
    # conditional revalidation still yields a cheap 304 (the no-cache contract)
    r2 = client.get("/static/ai-hotel.html", headers={"If-None-Match": etag})
    assert r2.status_code == 304          # cheap revalidation path preserved (no-cache, not no-store)
