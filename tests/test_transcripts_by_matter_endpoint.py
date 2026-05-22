"""PLAUD_TRANSCRIPT_BY_MATTER_1 — endpoint tests for
``GET /api/transcripts/by-matter/{matter_slug}``.

Ten cases per the brief:
  T1. Source-level: route is registered with auth + tag.
  T2. 401 without auth.
  T3. 404 for unknown slug.
  T4. 404 for inactive slug.
  T5. 200 with valid auth + canonical active slug; filters by matter_slug.
  T6. since=... filter.
  T7. limit cap (>200 → 400).
  T8. Default response omits full_transcript; include_body=true includes it.
  T9. since malformed → 400.
  T10. invalid source → 400; source=plaud filter applies.

DB layer is monkeypatched (fake conn/cursor) so the suite is self-contained.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


# ---------------------------------------------------------------------------
# T1 — source-level: route registered with auth + tag
# ---------------------------------------------------------------------------


def test_endpoint_route_registered_in_dashboard_source():
    src = Path("outputs/dashboard.py").read_text()
    assert "/api/transcripts/by-matter/{matter_slug}" in src
    assert 'tags=["transcripts"]' in src
    assert "dependencies=[Depends(verify_api_key)]" in src
    assert "async def get_transcripts_by_matter(" in src


# ---------------------------------------------------------------------------
# Shared TestClient + fake DB for the live cases
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Returns a controllable row-set; records the executed SQL + params."""

    def __init__(self, rows: list[tuple] | None = None,
                 description: list[tuple] | None = None) -> None:
        self.rows = rows or []
        self.description = description or []
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        self.statements.append((sql, tuple(params or ())))

    def fetchall(self) -> list[tuple]:
        return list(self.rows)

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def rollback(self) -> None:
        pass


def _client_with_fake_store(monkeypatch, rows=None, description=None,
                             active=("hagenauer-rg7",)):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import importlib
    import outputs.dashboard as dash
    importlib.reload(dash)

    # Bypass verify_api_key for tests that exercise the handler body. For 401
    # tests, we use a separate client without override.
    from kbl import slug_registry

    monkeypatch.setattr(
        slug_registry, "active_slugs", lambda: set(active),
    )

    cur = _FakeCursor(rows=rows, description=description)
    conn = _FakeConn(cur)

    class _StubStore:
        def _get_conn(self):
            return conn

        def _put_conn(self, c):
            return None

    monkeypatch.setattr(dash, "_get_store", lambda: _StubStore())

    return TestClient(dash.app), cur


def _client_no_override(monkeypatch):
    """For 401-path tests — verify_api_key NOT overridden."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    import importlib
    import outputs.dashboard as dash
    importlib.reload(dash)
    return TestClient(dash.app)


# ---------------------------------------------------------------------------
# T2 — 401 without auth
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_returns_401_without_auth(monkeypatch):
    client = _client_no_override(monkeypatch)
    r = client.get("/api/transcripts/by-matter/hagenauer-rg7")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# T3 — 404 for unknown slug (not in registry at all)
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_returns_404_for_unknown_slug(monkeypatch):
    client, _cur = _client_with_fake_store(monkeypatch, active=("hagenauer-rg7",))
    r = client.get(
        "/api/transcripts/by-matter/totally-not-a-matter",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 404
    assert "Unknown or inactive matter_slug" in r.json()["detail"]


# ---------------------------------------------------------------------------
# T4 — 404 for inactive slug (in registry but status != active)
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_returns_404_for_inactive_slug(monkeypatch):
    # active_slugs() returns only 'hagenauer-rg7' — so a known-but-inactive
    # slug 'retired-matter' also fails the gate.
    client, _cur = _client_with_fake_store(monkeypatch, active=("hagenauer-rg7",))
    r = client.get(
        "/api/transcripts/by-matter/retired-matter",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# T5 — 200 happy path; filters by matter_slug
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_returns_200_filtered_by_matter_slug(monkeypatch):
    description = [
        ("id",), ("title",), ("meeting_date",), ("duration",),
        ("organizer",), ("participants",), ("summary",), ("source",),
    ]
    rows = [
        ("plaud_h1", "Hagenauer call",
         datetime(2026, 5, 20, 14, 0, tzinfo=timezone.utc),
         "45m", "alice@x", "alice,bob", "summary", "plaud"),
        ("fireflies_h2", "Hagenauer follow-up",
         datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
         "30m", "bob@x", "alice,bob", "summary2", "fireflies"),
    ]
    client, cur = _client_with_fake_store(
        monkeypatch, rows=rows, description=description,
    )
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["matter_slug"] == "hagenauer-rg7"
    assert body["count"] == 2
    assert body["limit"] == 50
    assert body["include_body"] is False
    assert {t["id"] for t in body["transcripts"]} == {"plaud_h1", "fireflies_h2"}
    # WHERE clause uses matter_slug = %s with the requested slug
    select_calls = [s for s in cur.statements if s[0].startswith("SELECT ")]
    assert len(select_calls) == 1
    sql, params = select_calls[0]
    assert "matter_slug = %s" in sql
    assert params[0] == "hagenauer-rg7"


# ---------------------------------------------------------------------------
# T6 — since=... filter is wired into the SQL WHERE clause + params
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_since_filter_passes_to_sql(monkeypatch):
    description = [
        ("id",), ("title",), ("meeting_date",), ("duration",),
        ("organizer",), ("participants",), ("summary",), ("source",),
    ]
    client, cur = _client_with_fake_store(
        monkeypatch, rows=[], description=description,
    )
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?since=2026-05-01T00:00:00Z",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 200
    select_calls = [s for s in cur.statements if s[0].startswith("SELECT ")]
    sql, params = select_calls[0]
    assert "meeting_date >= %s" in sql
    assert "2026-05-01T00:00:00Z" in params


# ---------------------------------------------------------------------------
# T7 — limit cap: >200 returns 400
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_limit_above_200_returns_400(monkeypatch):
    client, _cur = _client_with_fake_store(monkeypatch)
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?limit=500",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 400
    assert "1..200" in r.json()["detail"]


# ---------------------------------------------------------------------------
# T8 — default omits full_transcript; include_body=true includes it
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_default_excludes_full_transcript_include_body_includes_it(monkeypatch):
    # Default response — full_transcript NOT in SELECT
    description_no_body = [
        ("id",), ("title",), ("meeting_date",), ("duration",),
        ("organizer",), ("participants",), ("summary",), ("source",),
    ]
    client, cur = _client_with_fake_store(
        monkeypatch,
        rows=[("plaud_x", "T", None, "30m", "o", "p", "s", "plaud")],
        description=description_no_body,
    )
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["include_body"] is False
    for t in body["transcripts"]:
        assert "full_transcript" not in t
    select_sql = next(s[0] for s in cur.statements if s[0].startswith("SELECT "))
    assert "full_transcript" not in select_sql

    # include_body=true — full_transcript IS in SELECT
    description_with_body = description_no_body + [("full_transcript",)]
    client2, cur2 = _client_with_fake_store(
        monkeypatch,
        rows=[("plaud_x", "T", None, "30m", "o", "p", "s", "plaud", "BODY")],
        description=description_with_body,
    )
    r2 = client2.get(
        "/api/transcripts/by-matter/hagenauer-rg7?include_body=true",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["include_body"] is True
    for t in body2["transcripts"]:
        assert t.get("full_transcript") == "BODY"
    select_sql_2 = next(s[0] for s in cur2.statements if s[0].startswith("SELECT "))
    assert "full_transcript" in select_sql_2


# ---------------------------------------------------------------------------
# T9 — malformed since returns 400 with clear message
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_since_malformed_returns_400(monkeypatch):
    client, _cur = _client_with_fake_store(monkeypatch)
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?since=yesterday",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 400
    assert "ISO 8601" in r.json()["detail"]


# ---------------------------------------------------------------------------
# T10 — invalid source returns 400; source=plaud filter wired
# ---------------------------------------------------------------------------


@_skip_without_dashboard
def test_invalid_source_returns_400_and_valid_source_filters(monkeypatch):
    # Invalid source → 400
    client, _cur = _client_with_fake_store(monkeypatch)
    r = client.get(
        "/api/transcripts/by-matter/hagenauer-rg7?source=teams",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r.status_code == 400
    assert "source must be one of" in r.json()["detail"]

    # Valid source filter (plaud) → 200 + source = %s in SQL
    description = [
        ("id",), ("title",), ("meeting_date",), ("duration",),
        ("organizer",), ("participants",), ("summary",), ("source",),
    ]
    client2, cur2 = _client_with_fake_store(
        monkeypatch, rows=[], description=description,
    )
    r2 = client2.get(
        "/api/transcripts/by-matter/hagenauer-rg7?source=plaud",
        headers={"X-Baker-Key": "test-key"},
    )
    assert r2.status_code == 200
    select_call = next(s for s in cur2.statements if s[0].startswith("SELECT "))
    sql, params = select_call
    assert "source = %s" in sql
    assert "plaud" in params
