"""BAKER_DASHBOARD_V2_CARD_DETAIL_1: tests for the bounded detail route + service.

Pure-logic + service (monkeypatched DB) + endpoint (TestClient) — no live DB.
Proves: trusted item returns bounded metadata; untrusted is hidden (404); missing
returns 404; verification timeline appears when present; raw source-body fields
are NEVER returned (explicit assertion at unit, service, and route layers); the
route is auth-gated.
"""
from __future__ import annotations

import pytest

import orchestrator.verified_item_detail as d


def _row(**kw):
    base = dict(
        id=11, state="verified", item_type="deadline", claim="Counterparty owes SW spec",
        why_matters="blocks handover", next_action="send reminder", owner="DV",
        due_at="2026-06-25T00:00:00Z", confidence="high", matter_slug="hagenauer-rg7",
        related_matters=[], people=["AO"], source_type="email", source_trust="vip",
        source_refs=[{"table": "email_messages", "id": "42", "body": "RAW SECRET BODY",
                      "source_snippet": "SECRET SNIPPET"}],
        verification_summary="checked the contract", counterargument="maybe non-binding",
        dismiss_reason=None, signal_candidate_id=None, created_by="cortex_tier_b",
        extraction_model="gemini-2.5-pro", source_model="gpt-5",
        created_at="2026-06-22T00:00:00Z", updated_at="2026-06-22T01:00:00Z",
    )
    base.update(kw)
    return base


def _events():
    return [
        dict(id=1, from_state=None, to_state="candidate", actor_type="system",
             actor_id="ingest", model="gemini-2.5-pro", rationale="created",
             evidence_delta={"event": "create"}, created_at="2026-06-22T00:00:00Z"),
        dict(id=2, from_state="candidate", to_state="verified", actor_type="cortex_tier_b",
             actor_id="verifier-1", model="claude-opus", rationale="evidence sufficient",
             evidence_delta={"note": "ok", "raw_body": "DELTA SECRET"},
             created_at="2026-06-22T01:00:00Z"),
    ]


# --- _bound ----------------------------------------------------------------

def test_bound_truncates_long_strings_within_ceiling():
    long = "x" * 1000
    out = d._bound({"a": long, "b": ["y" * 5, {"c": long}]})
    # FINAL length (marker included) must be <= EXCERPT_MAX, never over (G0 F1).
    assert out["a"].endswith("…(truncated)") and len(out["a"]) <= d.EXCERPT_MAX
    assert out["b"][0] == "yyyyy"  # short strings untouched
    assert out["b"][1]["c"].endswith("…(truncated)") and len(out["b"][1]["c"]) <= d.EXCERPT_MAX


# --- build_detail (pure) ---------------------------------------------------

def test_build_detail_strips_raw_bodies():
    detail = d.build_detail(_row(), _events())
    blob = repr(detail)
    for secret in ("RAW SECRET BODY", "SECRET SNIPPET", "DELTA SECRET"):
        assert secret not in blob, f"{secret} leaked into detail"
    item = detail["item"]
    assert detail["status"] == "ok"
    assert item["id"] == 11 and item["state"] == "verified"
    assert item["lane"] == "promises"
    assert item["source_refs_count"] == 1
    assert "body" not in item["source_refs"][0]
    # benign metadata retained
    assert item["source_refs"][0]["table"] == "email_messages"


def test_build_detail_includes_safe_fields_and_reason():
    item = d.build_detail(_row(), _events())["item"]
    assert item["why_matters"] == "blocks handover"
    assert item["verification_summary"] == "checked the contract"
    assert item["counterargument"]  # Baker's own analysis is safe to surface
    assert item["evidence"]["extraction_model"] == "gemini-2.5-pro"
    assert item["evidence"]["source_model"] == "gpt-5"
    assert item["selected_reason"].startswith("Verified")
    assert "due 2026-06-25" in item["selected_reason"]
    assert "high confidence" in item["selected_reason"]


def test_build_detail_audit_timeline_present_and_sanitized():
    item = d.build_detail(_row(), _events())["item"]
    assert item["verification_event_count"] == 2
    ev = item["verification_events"]
    assert ev[0]["to_state"] == "candidate" and ev[1]["to_state"] == "verified"
    assert ev[1]["actor_type"] == "cortex_tier_b" and ev[1]["model"] == "claude-opus"
    # evidence_delta kept its benign key but dropped the raw_body key
    assert ev[1]["evidence_delta"].get("note") == "ok"
    assert "raw_body" not in ev[1]["evidence_delta"]


def test_build_detail_no_events_ok():
    item = d.build_detail(_row(), [])["item"]
    assert item["verification_events"] == []
    assert item["verification_event_count"] == 0


def test_all_free_text_scalars_bounded_to_ceiling():
    """G0 F1: every free-text scalar (esp. claim) is <= EXCERPT_MAX, including
    oversized source-ref metadata + event rationale/delta."""
    big = "Z" * 1000
    row = _row(
        claim=big, why_matters=big, next_action=big,
        verification_summary=big, counterargument=big, owner=big,
        source_refs=[{"table": big, "id": big, "note": big}],
    )
    events = [dict(id=3, from_state="candidate", to_state="verified",
                   actor_type="cortex_tier_b", actor_id="v", model="claude-opus",
                   rationale=big, evidence_delta={"why": big, "raw_body": "SECRET"},
                   created_at="2026-06-22T01:00:00Z")]
    item = d.build_detail(row, events)["item"]
    for f in ("claim", "why_matters", "next_action", "verification_summary",
              "counterargument", "owner"):
        assert len(item[f]) <= d.EXCERPT_MAX, f"{f} exceeds ceiling: {len(item[f])}"
    for v in item["source_refs"][0].values():
        assert len(v) <= d.EXCERPT_MAX
    ev = item["verification_events"][0]
    assert len(ev["rationale"]) <= d.EXCERPT_MAX
    assert len(ev["evidence_delta"]["why"]) <= d.EXCERPT_MAX
    assert "raw_body" not in ev["evidence_delta"]  # raw key still stripped
    assert "SECRET" not in repr(item)


# --- get_verified_item_detail (monkeypatched DB) ---------------------------

def test_service_trusted_returns_ok(monkeypatch):
    import models.verified_items as vi
    monkeypatch.setattr(vi, "get_item", lambda i: _row(id=i))
    monkeypatch.setattr(vi, "get_events", lambda i, limit=100: _events())
    res = d.get_verified_item_detail(11)
    assert res["status"] == "ok" and res["item"]["id"] == 11


def test_service_untrusted_hidden(monkeypatch):
    import models.verified_items as vi
    monkeypatch.setattr(vi, "get_item", lambda i: _row(id=i, state="candidate"))
    monkeypatch.setattr(vi, "get_events", lambda i, limit=100: [])
    assert d.get_verified_item_detail(11)["status"] == "not_trusted"
    monkeypatch.setattr(vi, "get_item", lambda i: _row(id=i, state="dismissed"))
    assert d.get_verified_item_detail(11)["status"] == "not_trusted"


def test_service_missing_returns_not_found(monkeypatch):
    import models.verified_items as vi
    monkeypatch.setattr(vi, "get_item", lambda i: None)
    monkeypatch.setattr(vi, "get_events", lambda i, limit=100: [])
    assert d.get_verified_item_detail(999)["status"] == "not_found"


# --- route (auth + status mapping + no leak) -------------------------------

def test_route_auth_and_status_mapping(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-detail-key")
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as e:  # pragma: no cover
        pytest.skip(f"dashboard app unavailable: {e}")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-detail-key", raising=False)
    import orchestrator.verified_item_detail as svc

    client = TestClient(dash.app)

    # no key -> rejected
    assert client.get("/api/verified-items/11").status_code in (401, 403)

    # trusted -> 200 bounded, no raw body
    monkeypatch.setattr(svc, "get_verified_item_detail",
                        lambda i: d.build_detail(_row(id=i), _events()))
    r = client.get("/api/verified-items/11", headers={"X-Baker-Key": "test-detail-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["item"]["id"] == 11
    for secret in ("RAW SECRET BODY", "SECRET SNIPPET", "DELTA SECRET"):
        assert secret not in r.text

    # untrusted -> 404 (hidden)
    monkeypatch.setattr(svc, "get_verified_item_detail", lambda i: {"status": "not_trusted"})
    assert client.get("/api/verified-items/11",
                      headers={"X-Baker-Key": "test-detail-key"}).status_code == 404

    # missing -> 404
    monkeypatch.setattr(svc, "get_verified_item_detail", lambda i: {"status": "not_found"})
    assert client.get("/api/verified-items/999",
                      headers={"X-Baker-Key": "test-detail-key"}).status_code == 404


def test_route_is_thin_and_delegates():
    """Route delegates to the service + runs no SQL of its own (cannot reach a raw
    table directly)."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "outputs" / "dashboard.py").read_text()
    m = re.search(r"async def get_verified_item_detail_route\(.*?(?=\nasync def |\n@app\.)", src, re.DOTALL)
    assert m, "route not found"
    body = m.group(0)
    assert "get_verified_item_detail" in body
    assert "execute(" not in body and "_get_conn" not in body
    assert "SELECT" not in body.upper()
