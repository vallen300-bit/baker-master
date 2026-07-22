"""Regression coverage for the dashboard's source freshness keys."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


class _FakeCursor:
    def __init__(self, fresh_watermark: datetime):
        self._fresh_watermark = fresh_watermark
        self._next_row = None
        self.watermark_sources: list[str] = []

    def execute(self, sql: str, params=None):
        if sql.startswith("SELECT COUNT(*)"):
            self._next_row = {"cnt": 0, "latest": None}
        elif "FROM trigger_watermarks" in sql:
            source = params[0]
            self.watermark_sources.append(source)
            self._next_row = (
                {"last_seen": self._fresh_watermark}
                if source == "plaud"
                else None
            )

    def fetchone(self):
        return self._next_row

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor


class _FakeStore:
    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    def _get_conn(self):
        return self._conn

    def _put_conn(self, conn):
        pass


@pytest.mark.asyncio
async def test_meetings_freshness_uses_plaud_watermark_and_goes_green(monkeypatch):
    import outputs.dashboard as dash

    fresh = datetime.now(timezone.utc)
    cursor = _FakeCursor(fresh)
    monkeypatch.setattr(dash, "_get_store", lambda: _FakeStore(_FakeConnection(cursor)))

    payload = await dash.get_data_freshness()

    meetings = next(source for source in payload["sources"] if source["source"] == "Meetings")
    assert meetings["watermark"].startswith(fresh.isoformat()[:19])
    assert meetings["status"] == "green"
    assert "plaud" in cursor.watermark_sources
    assert "fireflies" not in cursor.watermark_sources
