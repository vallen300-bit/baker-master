"""ARRIVALS_BOARD_LIVE_1 tests.

Pure tests cover overlay/render behavior without a DB. The upsert round-trip is
live-PG gated through ``needs_live_pg`` and skips cleanly when no test DB exists.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient

from orchestrator import arrivals_board as ab

NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
MIGRATION = Path("migrations/20260708a_flight_board_state.sql")


def test_effective_status_overlays_past_due_without_hiding_terminal_states():
    assert ab.effective_status(
        {"status": "ON TIME", "arrives_on": date(2026, 7, 7)},
        today=date(2026, 7, 8),
    ) == "DELAYED"
    assert ab.effective_status(
        {"status": "LANDED", "arrives_on": date(2026, 7, 7)},
        today=date(2026, 7, 8),
    ) == "LANDED"
    assert ab.effective_status({}, today=date(2026, 7, 8)) == "CHECK-IN"
    assert ab.effective_status(
        {"status": "ON TIME", "arrives_on": date(2026, 7, 8)},
        today=date(2026, 7, 8),
    ) == "ON TIME"


def test_migration_shape_has_flight_board_contract():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- == migrate:up ==" in sql
    assert "CREATE TABLE IF NOT EXISTS flight_board_state" in sql
    for col in (
        "project_code",
        "status",
        "arrives_on",
        "cockpit_url",
        "updated_by",
        "updated_at",
    ):
        assert col in sql
    for status in ab.STATUSES:
        assert status in sql


def test_render_board_html_uses_template_tokens_and_filters_old_landed():
    rows = [
        {
            "project_number": "BB-AUK-001",
            "desk_owner": "baden-baden-desk",
            "matter_slug": "lilienmatt",
            "status": "FINAL APPROACH",
            "arrives_on": date(2026, 7, 10),
            "airline": "Baden-Baden",
            "destination": "Aukera financing",
            "cockpit_url": "/\\external.example/landing",
            "updated_at": NOW,
        },
        {
            "project_number": "AO-OSK-001",
            "desk_owner": "ao-desk",
            "matter_slug": "ao",
            "status": None,
            "updated_at": None,
        },
        {
            "project_number": "OLD-LND-001",
            "desk_owner": "brisen-desk",
            "matter_slug": "brisen",
            "status": "LANDED",
            "updated_at": NOW - timedelta(days=8),
        },
    ]
    html = ab.render_board_html(rows, now=NOW)
    assert 'data-flap="BB-AUK-001"' in html
    assert "external.example" not in html
    assert 'onclick="location.href=&quot;/flights/BB-AUK-001&quot;"' in html
    assert "blinkgrp" in html
    assert 'data-flap="FINAL APPROACH"' in html
    assert 'data-flap="PENDING"' in html
    assert 'data-flap="CHECK-IN"' in html
    assert "OLD-LND-001" not in html
    assert "__ROWS__" not in html
    assert "__STAMP__" not in html
    assert '<meta http-equiv="refresh" content="120">' in html
    assert 'style="overflow-x:auto"' in html


def test_cockpit_url_rejects_backslashes():
    assert ab._optional_cockpit_url("/flights/BB-AUK-001") == "/flights/BB-AUK-001"
    for url in ("/\\evil.example/path", "/flights\\BB-AUK-001"):
        with pytest.raises(ValueError):
            ab._optional_cockpit_url(url)


def _bootstrap_live_pg(dsn: str) -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS baker_actions (
                    id SERIAL PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_task_id TEXT,
                    payload JSONB,
                    trigger_source TEXT,
                    success BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "DELETE FROM flight_board_state WHERE project_code = %s",
                ("TST-ARR-001",),
            )
            cur.execute(
                "DELETE FROM baker_actions WHERE target_task_id = %s",
                ("TST-ARR-001",),
            )


def test_upsert_board_state_validates_and_audits_live_pg(needs_live_pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    _bootstrap_live_pg(needs_live_pg)

    try:
        try:
            ab.upsert_board_state("TST-ARR-001", {"status": "BOARDING"}, "pytest")
            raise AssertionError("bad status should have raised")
        except ValueError:
            pass

        row = ab.upsert_board_state(
            "TST-ARR-001",
            {
                "status": "ON TIME",
                "arrives_on": "2026-07-10",
                "airline": "Test Air",
                "destination": "Control Tower",
                "cockpit_url": "/flights/TST-ARR-001",
                "page_version": "pytest",
            },
            "pytest",
        )
        assert row["project_code"] == "TST-ARR-001"
        assert row["status"] == "ON TIME"

        with psycopg2.connect(needs_live_pg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                     WHERE table_name = 'flight_board_state'
                     ORDER BY column_name
                    """
                )
                cols = {r[0] for r in cur.fetchall()}
                assert {"project_code", "status", "arrives_on", "updated_by"} <= cols
                cur.execute(
                    """
                    SELECT COUNT(*) FROM baker_actions
                     WHERE target_task_id = %s AND trigger_source = %s
                    """,
                    ("TST-ARR-001", "arrivals_board"),
                )
                assert cur.fetchone()[0] == 1
    finally:
        with psycopg2.connect(needs_live_pg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM flight_board_state WHERE project_code = %s",
                    ("TST-ARR-001",),
                )
                cur.execute(
                    "DELETE FROM baker_actions WHERE target_task_id = %s",
                    ("TST-ARR-001",),
                )


def _client(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)
    return TestClient(dashboard.app)


def test_flight_board_endpoint_requires_key_and_rejects_bad_status(monkeypatch):
    client = _client(monkeypatch)
    no_key = client.post("/api/flight-board/BB-AUK-001", json={"status": "ON TIME"})
    assert no_key.status_code in (401, 403)

    bad = client.post(
        "/api/flight-board/BB-AUK-001",
        headers={"X-Baker-Key": "test-key"},
        json={"status": "BOARDING"},
    )
    assert bad.status_code == 422


def test_arrivals_json_uses_effective_status(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("ARRIVALS_BOARD_PIN", "123456")
    from outputs import dashboard

    rows = [
        {
            "project_number": "BB-AUK-001",
            "desk_owner": "baden-baden-desk",
            "matter_slug": "lilienmatt",
            "status": "ON TIME",
            "arrives_on": date(2026, 7, 7),
            "updated_at": NOW,
        }
    ]
    monkeypatch.setattr(ab, "list_board_rows", lambda: rows)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    client = TestClient(dashboard.app, base_url="https://testserver")

    no_key = client.get("/api/arrivals.json")
    assert no_key.status_code == 404

    page_no_key = client.get("/arrivals")
    assert page_no_key.status_code == 404

    wrong_pin = client.get("/arrivals?pin=111111")
    assert wrong_pin.status_code == 404

    page = client.get("/arrivals?key=test-key")
    assert page.status_code == 200
    assert 'data-flap="BB-AUK-001"' in page.text

    header_page = client.get("/arrivals", headers={"X-Baker-Key": "test-key"})
    assert header_page.status_code == 200

    pin_page = client.get("/arrivals?pin=123456")
    assert pin_page.status_code == 200
    set_cookie = pin_page.headers.get("set-cookie", "")
    assert "arrivals_board_access" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie

    bare_page_with_cookie = client.get("/arrivals")
    assert bare_page_with_cookie.status_code == 200
    assert 'data-flap="BB-AUK-001"' in bare_page_with_cookie.text

    resp = client.get("/api/arrivals.json?key=test-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["rows"][0]["effective_status"] == "DELAYED"

    fresh_client = TestClient(dashboard.app, base_url="https://testserver")
    pin_resp = fresh_client.get("/api/arrivals.json?pin=123456")
    assert pin_resp.status_code == 200
    api_set_cookie = pin_resp.headers.get("set-cookie", "")
    assert "arrivals_board_access" in api_set_cookie
    assert "HttpOnly" in api_set_cookie
    assert "Secure" in api_set_cookie
    assert "SameSite=strict" in api_set_cookie

    cookie_resp = fresh_client.get("/api/arrivals.json")
    assert cookie_resp.status_code == 200
    assert cookie_resp.json()["rows"][0]["effective_status"] == "DELAYED"
