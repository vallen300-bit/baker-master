"""BAKER_DASHBOARD_V2_TODAY_1: tests for the trusted Today read service.

All pure-logic + one SQL-capture + endpoint tests (no live DB needed). Proves:
candidates/raw legacy rows cannot leak, source refs are sanitized, lanes are
allowlisted + limited, empty state is stable, list_today_items reads only
verified_items, and the route is auth-gated.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import orchestrator.today_v2 as t

REPO = Path(__file__).resolve().parent.parent
TODAY_SRC = REPO / "orchestrator" / "today_v2.py"
DASHBOARD = REPO / "outputs" / "dashboard.py"


def _row(**kw):
    base = dict(
        id=1, state="verified", item_type="deadline", claim="c", why_matters=None,
        next_action=None, owner=None, due_at=None, confidence="high",
        matter_slug="ao", people=[], source_type="email", source_trust="vip",
        source_refs=[], verification_summary="s", counterargument="x",
        dismiss_reason=None, signal_candidate_id=None, created_by="system",
        extraction_model="gemini-2.5-pro", source_model=None,
        created_at="2026-06-22T00:00:00Z", updated_at="2026-06-22T00:00:00Z",
    )
    base.update(kw)
    return base


# 1 — lane mapper
def test_lane_mapper_allowlist_and_unknown():
    assert t.lane_for_item_type("critical") == "critical"
    assert t.lane_for_item_type("critical_item") == "critical"
    assert t.lane_for_item_type("promise") == "promises"
    assert t.lane_for_item_type("commitment") == "promises"
    assert t.lane_for_item_type("deadline") == "promises"
    assert t.lane_for_item_type("action_item") == "promises"
    assert t.lane_for_item_type("meeting") == "meetings"
    assert t.lane_for_item_type("meeting_prep") == "meetings"
    assert t.lane_for_item_type("meeting_followup") == "meetings"
    assert t.lane_for_item_type("travel") == "travel"
    assert t.lane_for_item_type("travel_obligation") == "travel"
    assert t.lane_for_item_type("trip") == "travel"
    # case-insensitive
    assert t.lane_for_item_type("DEADLINE") == "promises"
    # unknown / empty -> excluded (None), never a 5th lane
    assert t.lane_for_item_type("random_type") is None
    assert t.lane_for_item_type(None) is None
    assert t.lane_for_item_type("") is None


# 2 — AC8: candidate + dismissed excluded, only verified + ratified appear
def test_build_excludes_candidate_and_dismissed():
    rows = [
        _row(id=1, state="candidate", item_type="deadline", claim="CANDIDATE-LEAK"),
        _row(id=2, state="dismissed", item_type="meeting", claim="DISMISSED-LEAK"),
        _row(id=3, state="verified", item_type="deadline", claim="real promise"),
        _row(id=4, state="ratified", item_type="meeting", claim="real meeting"),
    ]
    payload = t.build_today_payload(rows, limit_per_lane=5)
    claims = [c["claim"] for lane in t.LANES for c in payload["lanes"][lane]]
    assert "CANDIDATE-LEAK" not in claims
    assert "DISMISSED-LEAK" not in claims
    assert "real promise" in payload["lanes"]["promises"][0]["claim"]
    assert "real meeting" in payload["lanes"]["meetings"][0]["claim"]
    assert payload["counts"]["total"] == 2


# 3 / AC5 — source refs sanitized
def test_source_refs_sanitized():
    refs = [{
        "table": "email_messages", "id": "42",
        "body": "SECRET BODY", "source_snippet": "SECRET SNIPPET",
        "email_text": "SECRET TEXT", "full_content": "SECRET CONTENT",
        "transcript": "SECRET TRANSCRIPT", "nested": {"raw_body": "DEEP SECRET", "ok": 1},
    }]
    sanitized, count = t.sanitize_source_refs(refs)
    assert count == 1
    flat = repr(sanitized)
    for secret in ("SECRET BODY", "SECRET SNIPPET", "SECRET TEXT",
                   "SECRET CONTENT", "SECRET TRANSCRIPT", "DEEP SECRET"):
        assert secret not in flat
    # benign metadata kept
    assert sanitized[0]["table"] == "email_messages"
    assert sanitized[0]["id"] == "42"
    assert sanitized[0]["nested"]["ok"] == 1
    # malformed (non-list) -> empty
    assert t.sanitize_source_refs({"body": "x"}) == ([], 0)
    assert t.sanitize_source_refs(None) == ([], 0)


def test_build_strips_raw_keys_end_to_end():
    rows = [_row(id=9, state="verified", item_type="deadline",
                 source_refs=[{"id": "1", "body": "LEAK", "source_snippet": "LEAK2"}])]
    payload = t.build_today_payload(rows)
    card = payload["lanes"]["promises"][0]
    assert card["source_refs_count"] == 1
    assert "LEAK" not in repr(card["source_refs"])
    assert "LEAK2" not in repr(card["source_refs"])
    assert "body" not in card["source_refs"][0]


# 4 / AC6 — per-lane limit
def test_per_lane_limit_enforced():
    rows = [_row(id=i, state="verified", item_type="deadline", claim=f"p{i}")
            for i in range(7)]
    payload = t.build_today_payload(rows, limit_per_lane=5)
    assert len(payload["lanes"]["promises"]) == 5
    assert payload["counts"]["promises"] == 5
    # clamp absurd values
    payload2 = t.build_today_payload(rows, limit_per_lane=999)
    assert len(payload2["lanes"]["promises"]) == 7  # capped at 20, only 7 rows
    payload3 = t.build_today_payload(rows, limit_per_lane=0)
    assert len(payload3["lanes"]["promises"]) == 5  # invalid -> default 5


def test_unknown_item_type_counted_excluded():
    rows = [
        _row(id=1, state="verified", item_type="deadline"),
        _row(id=2, state="verified", item_type="weird_unmapped_type"),
    ]
    payload = t.build_today_payload(rows)
    assert payload["counts"]["excluded"] == 1
    assert payload["counts"]["total"] == 1


# 5 / AC9 — empty state stable shape
def test_empty_state_stable_shape():
    payload = t.build_today_payload([], limit_per_lane=5)
    assert payload == {
        "status": "ok",
        "lanes": {"critical": [], "promises": [], "meetings": [], "travel": []},
        "counts": {"critical": 0, "promises": 0, "meetings": 0, "travel": 0,
                   "total": 0, "excluded": 0},
    }
    # get_today_payload over a degraded DB also yields the empty shape (AC9)
    import models.verified_items as vi
    import orchestrator.today_v2 as tv
    orig = vi.list_today_items
    try:
        vi.list_today_items = lambda limit=200: []
        assert tv.get_today_payload(limit_per_lane=5)["counts"]["total"] == 0
    finally:
        vi.list_today_items = orig


# 6 — list_today_items reads ONLY verified_items + trusted states
def test_list_today_items_sql_reads_only_verified_items(monkeypatch):
    import models.verified_items as vi

    captured = []

    class _Cur:
        def execute(self, sql, params=None):
            captured.append(sql)
        def fetchall(self):
            return []
        def close(self):
            pass

    class _Conn:
        def cursor(self, **kw):
            return _Cur()
        def rollback(self):
            pass
        def commit(self):
            pass

    monkeypatch.setattr(vi, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(vi, "_put_conn", lambda c: None)
    vi.list_today_items(limit=10)
    assert captured, "no SQL executed"
    sql = captured[0]
    assert "verified_items" in sql
    assert "state IN ('verified', 'ratified')" in sql
    for forbidden in ("signal_candidates", "alerts", "deadlines"):
        assert forbidden not in sql, f"list_today_items must not read {forbidden}"


# 7 — route auth-gated + returns mocked payload
def test_route_requires_key_and_returns_payload(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-today-key")
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as e:  # pragma: no cover
        pytest.skip(f"dashboard app unavailable: {e}")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-today-key", raising=False)
    import orchestrator.today_v2 as tv
    monkeypatch.setattr(
        tv, "get_today_payload",
        lambda limit_per_lane=5: {"status": "ok", "lanes": {"critical": [],
            "promises": [], "meetings": [], "travel": []},
            "counts": {"critical": 0, "promises": 0, "meetings": 0, "travel": 0,
                       "total": 0, "excluded": 0}},
    )
    client = TestClient(dash.app)
    # no key -> rejected
    assert client.get("/api/today").status_code in (401, 403)
    # with key -> ok shape
    r = client.get("/api/today?limit_per_lane=5", headers={"X-Baker-Key": "test-today-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and set(body["lanes"]) == set(t.LANES)


# live-PG integration — real read path (proves the ORDER BY ... NULLS LAST SQL is
# valid against real Postgres and the end-to-end service works, not just mocks)
def test_get_today_payload_live_read_path(needs_live_pg, monkeypatch):
    import psycopg2
    import models.verified_items as vi

    mig = REPO / "migrations" / "20260622c_dashboard_v2_evidence_packet.sql"
    sec = re.search(r"== migrate:up ==(.*?)== migrate:down ==", mig.read_text(), re.DOTALL).group(1)
    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            cur.execute(sec)
            conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(vi, "_get_conn", lambda: psycopg2.connect(needs_live_pg))
    monkeypatch.setattr(vi, "_put_conn", lambda c: c.close() if c else None)

    # empty -> stable empty shape (AC9) against a real DB
    import orchestrator.today_v2 as tv
    assert tv.get_today_payload()["counts"]["total"] == 0

    # insert a verified deadline carrying a body-like source ref
    # Seed via the AUDITED path (G0 F1 — verified is no longer a direct-create
    # state): create the candidate shell, then transition it to verified.
    item_id = vi.create_verified_item(
        item_type="deadline", claim="Counterparty owes SW spec",
        created_by="system", state="candidate", confidence="high",
        source_trust="known_counterparty",
        source_refs=[{"table": "email_messages", "id": "1", "body": "RAW SECRET"}],
        verification_summary="checked", counterargument="maybe non-binding",
        matter_slug="hagenauer-rg7",
    )
    assert isinstance(item_id, int)
    tr = vi.transition_item(item_id, "verified", actor_type="cortex_tier_b",
                            actor_id="test-seed")
    assert tr["ok"]

    payload = tv.get_today_payload(limit_per_lane=5)
    assert payload["counts"]["promises"] == 1
    card = payload["lanes"]["promises"][0]
    assert card["id"] == item_id and card["state"] == "verified"
    assert card["source_refs_count"] == 1
    assert "RAW SECRET" not in repr(card["source_refs"])  # body stripped live too


# 8 — structural: Today service + route never touch raw/candidate/legacy tables
def test_today_service_does_not_read_raw_tables():
    src = TODAY_SRC.read_text()
    # only mentions in comments/docstrings explaining what it does NOT read; assert
    # there is no SQL/select against these tables in the module.
    for forbidden in ("signal_candidates", "alerts", "deadlines"):
        assert f"FROM {forbidden}" not in src
        assert f"from {forbidden}" not in src


def test_get_today_route_is_thin_and_delegates():
    """The route must delegate to today_v2.get_today_payload and run NO SQL of its
    own — so it cannot reach any raw/legacy table directly (AC7). (Table names may
    appear in the docstring as documentation; what matters is no query path.)"""
    src = DASHBOARD.read_text()
    m = re.search(r"async def get_today\(.*?(?=\nasync def |\n@app\.)", src, re.DOTALL)
    assert m, "get_today route not found"
    body = m.group(0)
    assert "get_today_payload" in body, "route must delegate to the today_v2 service"
    # thin: no direct DB access in the route body
    assert "execute(" not in body
    assert "_get_conn" not in body
    assert "SELECT" not in body.upper().replace("SELECTED", "")
