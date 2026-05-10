"""Tests for ``GET /api/dashboard/matters-summary``.

Covers the cockpit-sidebar wiring brief (CORTEX_COCKPIT_SIDEBAR_WIRING):
priorities-overlay path, severity-from-priority (NOT worst_tier),
Director-dismissed slug exclusion, fallback-when-priorities-missing
(legacy SQL+matter_registry branch), and ``_safe_describe`` KeyError
catch.

Both source layers are mocked at the module boundary:
    * ``outputs.dashboard.get_all_priorities`` — return a controlled list
      of ``Priority`` records (or empty for the fallback test).
    * ``outputs.dashboard._get_store`` — return a fake store whose
      cursor yields RealDictCursor-shaped row dicts.

No real DB or vault needed. The two test paths exercise the production
code's two branches (priorities present vs empty).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from kbl.priorities_registry import Priority


# ---------------------------------------------------------------------------
# Fake DB plumbing
# ---------------------------------------------------------------------------


class _FakeCursor:
    """RealDictCursor-shaped cursor. Each ``execute()`` consumes the next
    queued result; rows are list[dict] (the production endpoint iterates
    them as dicts).
    """

    def __init__(self, queued):
        self._queued = list(queued)
        self._rows: list[dict] = []

    def execute(self, sql, params=None):
        if not self._queued:
            raise AssertionError(f"Unexpected query: {sql[:80]!r}")
        self._rows = list(self._queued.pop(0))

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def close(self):
        pass


class _FakeConn:
    def __init__(self, queued):
        self._cursor = _FakeCursor(queued)
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        # The real endpoint passes RealDictCursor; we ignore the factory
        # and emit dicts directly from the queued rows.
        return self._cursor

    def rollback(self):
        self.rolled_back = True


class _FakeStore:
    def __init__(self, conn):
        self._conn = conn

    def _get_conn(self):
        return self._conn

    def _put_conn(self, conn):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs.dashboard import app, verify_api_key
    app.dependency_overrides[verify_api_key] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


def _patch_store(queued_results):
    """Patch ``_get_store`` so the endpoint sees our fake conn/cursor."""
    fake_conn = _FakeConn(queued_results)
    fake_store = _FakeStore(fake_conn)
    return patch("outputs.dashboard._get_store", return_value=fake_store), fake_conn


# ---------------------------------------------------------------------------
# Sample priority data
# ---------------------------------------------------------------------------


_SAMPLE_PRIORITIES = [
    Priority(
        slug="hagenauer-rg7",
        when="urgent",
        importance="critical",
        category="active-deal",
        triaga_ref="Q1",
        description="GC takeover — complete hotel + residences build",
    ),
    Priority(
        slug="mrci",
        when="urgent",
        importance="high",
        category="active-deal",
        triaga_ref="Q6",
        description="Plan Balgerstrasse development",
    ),
    Priority(
        slug="lilienmatt",
        when="asap",
        importance="medium",
        category="active-deal",
        triaga_ref="Q7",
        description="Move financing — multi-entity restructure",
    ),
    Priority(
        slug="vie-tax",
        when="4w",
        importance="low",
        category="tax",
        triaga_ref="Q12",
        description="Vienna tax return prep",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_matters_summary_priorities_overlay(client):
    """Priority slugs render in projects/operations even when alerts table
    has zero rows for them."""
    alerts_rows: list[dict] = []  # no pending alerts

    store_patch, _ = _patch_store([alerts_rows])
    with store_patch, \
         patch("outputs.dashboard.get_all_priorities", return_value=_SAMPLE_PRIORITIES), \
         patch("outputs.dashboard.priorities_registry_version", return_value=1), \
         patch("outputs.dashboard.priorities_registry_ratified_at", return_value="2026-04-29T18:45:00+02:00"), \
         patch("outputs.dashboard.slug_describe", side_effect=lambda s: f"DESC({s})"), \
         patch("outputs.dashboard.slug_normalize", side_effect=lambda s: s):
        resp = client.get("/api/dashboard/matters-summary")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    project_slugs = {p["matter_slug"] for p in body["projects"]}
    assert {"hagenauer-rg7", "mrci", "lilienmatt"}.issubset(project_slugs)

    op_slugs = {p["matter_slug"] for p in body["operations"]}
    assert "vie-tax" in op_slugs

    # display_label sourced from slug_describe
    hag = next(p for p in body["projects"] if p["matter_slug"] == "hagenauer-rg7")
    assert hag["display_label"] == "DESC(hagenauer-rg7)"
    assert hag["triaga_ref"] == "Q1"
    assert body["fallback_mode"] is None
    assert body["priorities_version"] == 1


def test_matters_summary_severity_from_priority_not_worst_tier(client):
    """Priority importance drives `severity` even when alerts.worst_tier
    would suggest a different colour."""
    alerts_rows = [
        # Hagenauer is critical via priorities (Q1) but has only tier-3 alerts —
        # legacy logic would map this to slate; new logic must keep critical.
        {"matter_slug": "hagenauer-rg7", "item_count": 2, "worst_tier": 3, "new_count": 0},
    ]

    store_patch, _ = _patch_store([alerts_rows])
    with store_patch, \
         patch("outputs.dashboard.get_all_priorities", return_value=_SAMPLE_PRIORITIES), \
         patch("outputs.dashboard.priorities_registry_version", return_value=1), \
         patch("outputs.dashboard.priorities_registry_ratified_at", return_value="x"), \
         patch("outputs.dashboard.slug_describe", side_effect=lambda s: s), \
         patch("outputs.dashboard.slug_normalize", side_effect=lambda s: s):
        resp = client.get("/api/dashboard/matters-summary")

    assert resp.status_code == 200
    hag = next(p for p in resp.json()["projects"] if p["matter_slug"] == "hagenauer-rg7")
    assert hag["severity"] == "critical"
    assert hag["worst_tier"] == 3  # retained for tooltip
    assert hag["item_count"] == 2


def test_matters_summary_dismissed_slug_excluded(client):
    """A slug that's in alerts but NOT in priorities lands in inbox,
    not projects/operations. Anchor: kitz-kempinski (Director-dismissed Q34)."""
    alerts_rows = [
        {"matter_slug": "kitz-kempinski", "item_count": 5, "worst_tier": 1, "new_count": 1},
        {"matter_slug": "mrci", "item_count": 2, "worst_tier": 2, "new_count": 0},
    ]

    store_patch, _ = _patch_store([alerts_rows])
    with store_patch, \
         patch("outputs.dashboard.get_all_priorities", return_value=_SAMPLE_PRIORITIES), \
         patch("outputs.dashboard.priorities_registry_version", return_value=1), \
         patch("outputs.dashboard.priorities_registry_ratified_at", return_value="x"), \
         patch("outputs.dashboard.slug_describe", side_effect=lambda s: s), \
         patch("outputs.dashboard.slug_normalize", side_effect=lambda s: s):
        resp = client.get("/api/dashboard/matters-summary")

    body = resp.json()
    project_slugs = {p["matter_slug"] for p in body["projects"]}
    op_slugs = {p["matter_slug"] for p in body["operations"]}
    inbox_slugs = {p["matter_slug"] for p in body["inbox"]}

    # Dismissed slug NOT in projects/operations.
    assert "kitz-kempinski" not in project_slugs
    assert "kitz-kempinski" not in op_slugs
    # ... but DOES surface in inbox so the items aren't lost silently.
    assert "kitz-kempinski" in inbox_slugs


def test_matters_summary_priorities_unavailable_falls_back(client):
    """When priorities_registry returns empty, endpoint runs the legacy
    matter_registry-bucketed query and reports fallback_mode."""
    legacy_rows = [
        {"matter_slug": "morv", "item_count": 7, "worst_tier": 1, "new_count": 1, "category": "project"},
        {"matter_slug": "_ungrouped", "item_count": 3, "worst_tier": 4, "new_count": 0, "category": "inbox"},
    ]

    store_patch, _ = _patch_store([legacy_rows])
    with store_patch, \
         patch("outputs.dashboard.get_all_priorities", return_value=[]), \
         patch("outputs.dashboard.priorities_registry_version", return_value=None), \
         patch("outputs.dashboard.priorities_registry_ratified_at", return_value=None):
        resp = client.get("/api/dashboard/matters-summary")

    body = resp.json()
    assert body["fallback_mode"] == "legacy_no_priorities"
    assert body["priorities_version"] is None
    assert body["count"] == 2
    project_slugs = {p["matter_slug"] for p in body["projects"]}
    assert "morv" in project_slugs


def test_matters_summary_safe_describe_unknown_slug_returns_raw(client):
    """If slug_registry.describe raises KeyError, _safe_describe returns the
    raw slug — endpoint must not 500."""
    alerts_rows: list[dict] = []
    store_patch, _ = _patch_store([alerts_rows])

    def _describe_raises(slug):
        raise KeyError(slug)

    with store_patch, \
         patch("outputs.dashboard.get_all_priorities", return_value=_SAMPLE_PRIORITIES), \
         patch("outputs.dashboard.priorities_registry_version", return_value=1), \
         patch("outputs.dashboard.priorities_registry_ratified_at", return_value="x"), \
         patch("outputs.dashboard.slug_describe", side_effect=_describe_raises), \
         patch("outputs.dashboard.slug_normalize", side_effect=lambda s: s):
        resp = client.get("/api/dashboard/matters-summary")

    assert resp.status_code == 200
    body = resp.json()
    hag = next(p for p in body["projects"] if p["matter_slug"] == "hagenauer-rg7")
    # _safe_describe falls back to raw slug.
    assert hag["display_label"] == "hagenauer-rg7"
