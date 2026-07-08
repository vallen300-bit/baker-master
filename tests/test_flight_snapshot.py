"""BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1 — assembler + render unit tests.

Pure unit tests: the per-source DB readers are monkeypatched, so these run with no
live DB. They pin the two acceptance-critical behaviors:
  - a KNOWN flight with ZERO evidence rows renders cleanly, every D-24 field present
    as an explicit "no data yet" (the state before b4's outbound-writer drain lands);
  - an UNKNOWN project code returns None (route ⇒ 404).
Plus: seeded evidence populates the right fields, values are never invented, and the
HTML render carries the mandatory read-only banner + timestamp + all D-24 field labels.
"""
from __future__ import annotations

from orchestrator import flight_snapshot as fs

_FIELDS = [k for k, _ in fs._FIELD_LABELS]


def _patch_readers(monkeypatch, *, meta, events=None, tickets=None,
                   deadlines=None, actions=None):
    monkeypatch.setattr(fs, "_project_meta", lambda code: meta)
    monkeypatch.setattr(fs, "_outbound_events", lambda code: events or [])
    monkeypatch.setattr(fs, "_tickets", lambda ms, fl: tickets or [])
    monkeypatch.setattr(fs, "_deadlines", lambda ms: deadlines or [])
    monkeypatch.setattr(fs, "_audit_actions", lambda code: actions or [])


_META = {
    "project_number": "BB-AUK-001", "desk_code": "BB",
    "desk_owner": "baden-baden-desk", "matter_slug": "aukera-baden-baden",
    "clickup_list_id": "9016", "status": "active",
}


# --------------------------------------------------------------------------
# Unknown code ⇒ None (route ⇒ 404)
# --------------------------------------------------------------------------

def test_unknown_project_code_returns_none(monkeypatch):
    monkeypatch.setattr(fs, "_project_meta", lambda code: None)
    assert fs.build_flight_snapshot("NOPE-XXX-999") is None


def test_blank_code_returns_none():
    assert fs.build_flight_snapshot("") is None
    assert fs.build_flight_snapshot("   ") is None


# --------------------------------------------------------------------------
# Known + ZERO evidence ⇒ every D-24 field present as "no data yet", renders clean
# --------------------------------------------------------------------------

def test_zero_evidence_renders_every_field_as_no_data(monkeypatch):
    _patch_readers(monkeypatch, meta=_META)
    snap = fs.build_flight_snapshot("BB-AUK-001")
    assert snap is not None
    assert snap["authoritative"] is False
    assert snap["assembled_at"]
    # Every D-24 field is present...
    for key in _FIELDS:
        assert key in snap["fields"], f"missing D-24 field {key}"
    # ...and with no flight evidence, every purely event/ticket/deadline-derived
    # field is the explicit no-data marker. The two registry-backed fields
    # (next_owner_action → owning desk, clickup_refs → the matter's ClickUp list)
    # legitimately carry that real registry evidence — never invented flight data.
    _registry_backed = {"next_owner_action", "clickup_refs"}
    for key in _FIELDS:
        if key in _registry_backed:
            continue
        assert fs._nodata(snap["fields"][key]), f"{key} should be 'no data yet'"
    noa = snap["fields"]["next_owner_action"]
    assert noa["next_owner"] == "baden-baden-desk"
    assert noa["action_hint"] == "no data yet"
    assert snap["fields"]["clickup_refs"]["list_id"] == "9016"
    assert snap["fields"]["clickup_refs"]["task_refs"] == []
    assert snap["counts"] == {"outbound_events": 0, "tickets": 0,
                              "deadlines": 0, "audit_actions": 0}


def test_zero_evidence_html_renders_cleanly(monkeypatch):
    _patch_readers(monkeypatch, meta=_META)
    snap = fs.build_flight_snapshot("BB-AUK-001")
    page = fs.render_snapshot_html(snap)
    assert "<!DOCTYPE html>" in page
    # Mandatory D-24 read-only banner + not-authoritative wording + timestamp.
    assert "READ-ONLY SNAPSHOT" in page
    assert "not authoritative flight state" in page
    assert snap["assembled_at"] in page
    # All D-24 field section labels present.
    for _, label in fs._FIELD_LABELS:
        assert label in page
    # Empty fields shown honestly.
    assert "no data yet" in page
    assert "BB-AUK-001" in page


# --------------------------------------------------------------------------
# Seeded evidence ⇒ fields populate; current_state labeled derived, not authoritative
# --------------------------------------------------------------------------

def test_seeded_evidence_populates_fields(monkeypatch):
    events = [{
        "event_state": "FLIGHT_BLOCKED", "ratification_class": "auto",
        "flight_id": "f1", "flight_from_state": "waiting", "flight_to_state": "blocked",
        "clickup_list_id": "9016", "clickup_task_id": "t1", "clickup_status": "open",
        "clickup_operation": "create", "last_error": "boom", "message_id": "m1",
        "thread_id": "th1", "created_at": "2026-07-04T09:00:00+00:00",
        "updated_at": "2026-07-04T09:00:00+00:00",
    }]
    tickets = [{
        "ticket_id": "tk1", "status": "sent", "direction": "outbound",
        "source_channel": "email", "source_id": "eml1",
        "suspected_matter_slug": "aukera-baden-baden", "suspected_flight": "BB-AUK-001",
        "proposed_desk_slug": "baden-baden-desk", "bus_message_id": "b1",
        "bus_thread_id": "bt1", "nudge_count": 2, "last_nudged_at": "2026-07-03T00:00:00+00:00",
        "escalated_at": None, "check_in_outcome": None,
        "created_at": "2026-07-02T00:00:00+00:00", "updated_at": "2026-07-02T00:00:00+00:00",
    }]
    deadlines = [{
        "id": 1, "description": "Sign SPA", "due_date": "2026-07-10",
        "status": "active", "priority": "high", "severity": None,
        "assigned_to": "baden-baden-desk", "obligation_type": "deliverable",
    }]
    actions = [{
        "action_type": "airport_outbound.flight_transition_recorded",
        "trigger_source": "connector", "success": True,
        "created_at": "2026-07-04T08:00:00+00:00", "committed_at": None,
        "payload": {"project_code": "BB-AUK-001"},
    }]
    _patch_readers(monkeypatch, meta=_META, events=events, tickets=tickets,
                   deadlines=deadlines, actions=actions)
    snap = fs.build_flight_snapshot("BB-AUK-001")
    f = snap["fields"]

    # current_state derived + explicitly labeled (D-23/D-24: never authoritative).
    assert f["current_state"]["value"] == "blocked"
    assert "NOT authoritative" in f["current_state"]["derivation"]
    # blockers surfaced from the blocked event.
    assert isinstance(f["blockers"], list) and f["blockers"][0]["state"] == "FLIGHT_BLOCKED"
    # deadline from the matter.
    assert f["deadline"]["description"] == "Sign SPA"
    # nudges from tickets.
    assert f["human_nudges"][0]["nudge_count"] == 2
    # ticket + clickup + evidence + history all non-empty.
    assert not fs._nodata(f["ticket_dispatch_refs"])
    assert not fs._nodata(f["clickup_refs"])
    assert not fs._nodata(f["evidence"])
    assert not fs._nodata(f["history"])
    # history newest-first.
    ts = [h["ts"] for h in f["history"]]
    assert ts == sorted(ts, reverse=True)
    # outcome + condition_precedents have no store yet ⇒ still honest no-data.
    assert fs._nodata(f["outcome"])
    assert fs._nodata(f["condition_precedents"])
    assert snap["counts"]["outbound_events"] == 1


def test_html_escapes_values(monkeypatch):
    evil = dict(_META, matter_slug="<script>alert(1)</script>")
    _patch_readers(monkeypatch, meta=evil)
    page = fs.render_snapshot_html(fs.build_flight_snapshot("BB-AUK-001"))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# --------------------------------------------------------------------------
# Index render
# --------------------------------------------------------------------------

def test_index_render_lists_flights():
    flights = [{"project_number": "BB-AUK-001", "desk_owner": "baden-baden-desk",
                "matter_slug": "aukera-baden-baden", "status": "active"}]
    page = fs.render_index_html(flights)
    assert "BB-AUK-001" in page
    assert "/flights/BB-AUK-001" in page
    assert "READ-ONLY SNAPSHOTS" in page


def test_index_render_empty():
    page = fs.render_index_html([])
    assert "no registered flights" in page


# --------------------------------------------------------------------------
# Route behavior (TestClient) — feature-flag gate, auth, 404, 200 render.
# Lazy imports keep the pure unit tests above DB-free + fast.
# --------------------------------------------------------------------------

def _client(monkeypatch, *, enabled):
    import os
    os.environ["BAKER_API_KEY"] = "test-key"
    if enabled:
        os.environ["FLIGHT_SNAPSHOT_ENABLED"] = "true"
    else:
        os.environ.pop("FLIGHT_SNAPSHOT_ENABLED", None)
    from fastapi.testclient import TestClient
    from outputs.dashboard import app
    return TestClient(app)


def test_route_flag_off_returns_404(monkeypatch):
    c = _client(monkeypatch, enabled=False)
    r = c.get("/flights/BB-AUK-001?key=test-key")
    assert r.status_code == 404


def test_route_flag_on_no_key_401(monkeypatch):
    c = _client(monkeypatch, enabled=True)
    r = c.get("/flights/BB-AUK-001")
    assert r.status_code == 401


def test_route_unknown_code_404(monkeypatch):
    from orchestrator import flight_snapshot as _fs
    monkeypatch.setattr(_fs, "build_flight_snapshot", lambda code: None)
    c = _client(monkeypatch, enabled=True)
    r = c.get("/flights/NOPE-XXX-999?key=test-key")
    assert r.status_code == 404


def test_route_known_code_renders_200(monkeypatch):
    from orchestrator import flight_snapshot as _fs
    _patch_readers(monkeypatch, meta=_META)
    c = _client(monkeypatch, enabled=True)
    r = c.get("/flights/BB-AUK-001?key=test-key")
    assert r.status_code == 200
    assert "READ-ONLY SNAPSHOT" in r.text
    assert "BB-AUK-001" in r.text


def test_route_index_200(monkeypatch):
    from orchestrator import flight_snapshot as _fs
    monkeypatch.setattr(_fs, "list_registered_flights",
                        lambda: [{"project_number": "BB-AUK-001",
                                  "desk_owner": "baden-baden-desk",
                                  "matter_slug": "aukera-baden-baden",
                                  "status": "active"}])
    c = _client(monkeypatch, enabled=True)
    r = c.get("/flights?key=test-key")
    assert r.status_code == 200
    assert "/flights/BB-AUK-001" in r.text


# --------------------------------------------------------------------------
# Zero-write proof (codex F1): _project_meta must issue NO DDL and NO commit.
# The plain resolve_project_number bootstraps (CREATE TABLE + commit); this surface
# must use the SELECT-only path. Spy the connection to prove it.
# --------------------------------------------------------------------------

class _SpyCursor:
    def __init__(self, log):
        self._log = log
    def execute(self, sql, params=None):
        self._log["sql"].append(" ".join(str(sql).split()))
    def fetchall(self):
        return []
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _SpyConn:
    def __init__(self, log):
        self._log = log
    def cursor(self, *a, **k):
        return _SpyCursor(self._log)
    def commit(self):
        self._log["commit"] += 1
    def rollback(self):
        self._log["rollback"] += 1


def test_project_meta_is_strictly_read_only(monkeypatch):
    from contextlib import contextmanager
    import kbl.project_registry_store as prs

    log = {"sql": [], "commit": 0, "rollback": 0}

    @contextmanager
    def _spy_get_conn():
        yield _SpyConn(log)

    # Patch the get_conn used inside resolve_project_number_readonly.
    monkeypatch.setattr(prs, "get_conn", _spy_get_conn)

    fs._project_meta("BB-AUK-001")  # returns None (spy fetchall empty) — fine

    joined = " ".join(log["sql"]).upper()
    # No schema/data mutation of any kind.
    for verb in ("CREATE ", "ALTER ", "INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE "):
        assert verb not in joined, f"read-only path issued a write: {verb.strip()}"
    # No commit (the bootstrap path commits; this one must not).
    assert log["commit"] == 0, "read-only path must not commit"
    # It did run exactly the SELECT.
    assert any(s.upper().startswith("SELECT") for s in log["sql"])


def test_route_arrivals_cookie_authorizes(monkeypatch):
    """ARRIVALS_BOARD_LIVE_1 click-through: the Director PIN cookie set at
    /arrivals must open the read-only /flights/{code} snapshot (no MCP key)."""
    monkeypatch.setenv("ARRIVALS_BOARD_PIN", "6470")
    from orchestrator import flight_snapshot as _fs
    monkeypatch.setattr(
        _fs, "build_flight_snapshot",
        lambda code: {"project_code": code, "meta": {}, "fields": {},
                      "assembled_at": "t", "counts": {}})
    c = _client(monkeypatch, enabled=True)
    import outputs.dashboard as _dash
    token = _dash._arrivals_board_pin_token("6470")
    c.cookies.set(_dash._ARRIVALS_BOARD_PIN_COOKIE, token)
    r = c.get("/flights/BB-AUK-001")
    assert r.status_code == 200
