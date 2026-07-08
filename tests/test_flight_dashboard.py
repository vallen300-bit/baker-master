"""TDD gate for BB_AUK_001_DASHBOARD_V1 — read-only CEO flight dashboard.

DB-free: the machine §4 counter is exercised via _aggregate_counts (pure) and via a
monkeypatched get_conn (spy / failure). No live DB required — these run in plain pytest.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import flight_dashboard as fd

NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


# --- Test 1: §4 counts computed from seeded ledger rows match expected tallies -------
def test_aggregate_counts_matches_status_tallies():
    # Mirrors the BB readout: checked_in URGENT=8 + VALID=12; sent=8; rejected=2.
    rows = [
        {"status": "checked_in", "urgency_hint": "urgent", "n": 8},
        {"status": "checked_in", "urgency_hint": "normal", "n": 12},
        {"status": "sent", "urgency_hint": None, "n": 8},
        {"status": "rejected", "urgency_hint": None, "n": 2},
    ]
    agg = fd._aggregate_counts(rows)
    assert agg["checked_in"] == 20
    assert agg["urgent"] == 8          # urgency dimension, not a status
    assert agg["awaiting"] == 8        # 'sent' == awaiting check-in
    assert agg["rejected"] == 2
    assert agg["total"] == 30


def test_count_flight_tickets_available_on_clean_read(monkeypatch):
    captured = {}

    class _Cur:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
        def fetchall(self):
            return [
                {"status": "checked_in", "urgency_hint": "urgent", "n": 8},
                {"status": "sent", "urgency_hint": None, "n": 8},
            ]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fd, "get_conn", lambda: _Conn())
    out = fd.count_flight_tickets("aukera-annaberg-financing")
    assert out["available"] is True
    assert out["checked_in"] == 8 and out["awaiting"] == 8 and out["urgent"] == 8
    assert captured["sql"].strip().lower().startswith("select")
    assert captured["params"][0] == ["aukera-annaberg-financing"]


def test_count_flight_tickets_dual_matches_legacy_label_with_matter_guard(monkeypatch):
    captured = {}

    class _Cur:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
        def fetchall(self):
            return [{"status": "checked_in", "urgency_hint": "normal", "n": 179}]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fd, "get_conn", lambda: _Conn())
    out = fd.count_flight_tickets(
        "BB-AUK-001",
        legacy_suspected_flights=["aukera-annaberg-financing"],
        legacy_matter_slugs=["lilienmatt"],
    )
    assert out["total"] == 179
    assert "suspected_matter_slug = any" in captured["sql"].lower()
    assert captured["params"][0] == ["BB-AUK-001"]
    assert captured["params"][1] == ["aukera-annaberg-financing"]
    assert captured["params"][2] == ["lilienmatt"]


# --- Test 2: query failure -> "ledger unavailable", no crash, no fabricated zeros ----
def test_ledger_failure_yields_unavailable_not_zeros(monkeypatch):
    def _boom():
        raise RuntimeError("pool dead")
    monkeypatch.setattr(fd, "get_conn", _boom)
    out = fd.count_flight_tickets("aukera-annaberg-financing")
    assert out == {"available": False}          # NOT {checked_in:0,...} — no fabricated zeros
    # And the render shows a visible unavailable state, not a crash.
    html = fd._tickets_html({"tickets": out})
    assert "ledger unavailable" in html.lower()
    assert "CHECKED-IN" not in html            # zeros are not drawn when unavailable


# --- Test 3: honest-empty — a section with no data renders "none this week" ----------
def test_honest_empty_renders_none_this_week():
    data = {
        "project_code": "BB-AUK-001",
        "what_changed": {"updated_at": NOW.isoformat(), "rows": []},
        "stale": {},
    }
    html = fd._risks_changed_html(data)
    assert "none this week" in html


# --- Test 4: staleness — 49h -> amber, 97h -> red, fresh -> None --------------------
def test_staleness_thresholds():
    amber = (NOW - timedelta(hours=49)).isoformat()
    red = (NOW - timedelta(hours=97)).isoformat()
    fresh = (NOW - timedelta(hours=3)).isoformat()
    assert fd.staleness_flag(amber, now=NOW) == "amber"
    assert fd.staleness_flag(red, now=NOW) == "red"
    assert fd.staleness_flag(fresh, now=NOW) is None
    assert fd.staleness_flag(None, now=NOW) is None       # missing stamp: no false alarm


# --- Test 5: read-only — the handler issues zero writes against airport_tickets ------
def test_read_path_issues_no_writes(monkeypatch):
    executed = []

    class _Cur:
        def execute(self, sql, params=None):
            executed.append(sql)
            assert sql.strip().lower().startswith("select"), f"non-SELECT issued: {sql}"
        def fetchall(self):
            return []
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self, cursor_factory=None):
            return _Cur()
        def commit(self):
            raise AssertionError("commit() called on a read-only path")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fd, "get_conn", lambda: _Conn())
    fd.count_flight_tickets("aukera-annaberg-financing")
    assert executed, "expected at least one SELECT"
    blob = " ".join(executed).lower()
    for verb in ("insert", "update", "delete", "drop", "alter"):
        assert verb not in blob


# --- Test 6: footer carries no false blanket conformance claim ----------------------
def test_footer_has_no_false_conformance_claim():
    # v4's false claim was the bare assertion "every row has owner + date + receipt".
    assert "every row has owner" not in fd.FOOTER_TEXT.lower()
    # The corrected footer describes the contract conditionally ("where recorded").
    assert "where recorded" in fd.FOOTER_TEXT.lower()
    # And it renders into the page.
    data = fd.build_flight_dashboard("BB-AUK-001", now=NOW)
    assert data is not None, "BB-AUK-001 snapshot must load"
    html = fd.render_dashboard_html(data)
    assert "every row has owner + date + receipt" not in html


# --- Bonus: end-to-end assembly + render of the committed snapshot (no live DB) ------
def test_build_and_render_committed_snapshot(monkeypatch):
    # Force the ledger unavailable so this stays DB-free but still renders fully.
    monkeypatch.setattr(fd, "count_flight_tickets", lambda f, **kw: {"available": False})
    data = fd.build_flight_dashboard("BB-AUK-001", now=NOW)
    assert data is not None
    html = fd.render_dashboard_html(data)
    assert "READ-ONLY snapshot" in html
    assert "Aukera financing" in html
    assert "CEO view" in html
    assert fd.build_flight_dashboard("NOPE-999", now=NOW) is None   # unknown -> None (404)


# --------------------------------------------------------------------------
# Route behavior (TestClient) — feature-flag gate, auth, 404, 200 render.
# --------------------------------------------------------------------------

def _client(*, enabled):
    import os
    os.environ["BAKER_API_KEY"] = "test-key"
    if enabled:
        os.environ["FLIGHT_DASHBOARD_ENABLED"] = "true"
    else:
        os.environ.pop("FLIGHT_DASHBOARD_ENABLED", None)
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    return TestClient(app)


def test_route_flag_off_returns_404():
    r = _client(enabled=False).get("/flight/BB-AUK-001?key=test-key")
    assert r.status_code == 404


def test_route_flag_on_no_key_401():
    r = _client(enabled=True).get("/flight/BB-AUK-001")
    assert r.status_code == 401


def test_route_unknown_code_404(monkeypatch):
    monkeypatch.setattr(fd, "build_flight_dashboard", lambda code: None)
    r = _client(enabled=True).get("/flight/NOPE-XXX-999?key=test-key")
    assert r.status_code == 404


def test_route_known_code_renders_200(monkeypatch):
    # Ledger unavailable keeps it DB-free; the desk snapshot still renders.
    monkeypatch.setattr(fd, "count_flight_tickets", lambda f, **kw: {"available": False})
    r = _client(enabled=True).get("/flight/BB-AUK-001?key=test-key")
    assert r.status_code == 200
    assert "READ-ONLY snapshot" in r.text
    assert "BB-AUK-001" in r.text
    assert "every row has owner + date + receipt" not in r.text   # G0 fix 2 holds end-to-end
