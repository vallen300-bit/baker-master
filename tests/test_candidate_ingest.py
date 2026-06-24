"""BAKER_DASHBOARD_V2_CANDIDATE_INGEST_1: tests for candidate ingestion, dedup,
legacy bridges, source-trust + model floor, triage reads/dismiss, and manual
promotion.

Two tiers:
  1. Pure-logic (always run) — trust classifier, model floor, dedup key, dismiss
     reason gate, verifier-required gate, fault tolerance, migration parse-level,
     and the AC8 structural proof that morning-brief never reads signal_candidates.
  2. Live-PG (gated via needs_live_pg) — applies migrations 20260622c + 20260622d,
     then exercises dedup idempotency, the Flash->untrusted_legacy floor (AC2),
     legacy bridge idempotency (AC3), manual promotion with the HUMAN verifier
     recorded in verification_events (deputy/codex-arch guard #6), AC2.3 refusal,
     and triage dismiss.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import orchestrator.candidate_ingest as ci

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required")

REPO = Path(__file__).resolve().parent.parent
MIG_C = REPO / "migrations" / "20260622c_dashboard_v2_evidence_packet.sql"
MIG_D = REPO / "migrations" / "20260622d_signal_candidates_dedup.sql"
DASHBOARD = REPO / "outputs" / "dashboard.py"

_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _strip_comment_leader(line: str) -> str:
    s = line.lstrip()
    if s.startswith("--"):
        rest = s[2:]
        return line.replace("-- ", "", 1) if rest.startswith(" ") else line.replace("--", "", 1)
    return line


def _parse_sections(sql: str) -> dict:
    matches = list(_SECTION_RE.finditer(sql))
    out: dict = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql)
        body = sql[start:end].strip()
        if label == "down":
            body = "\n".join(_strip_comment_leader(ln) for ln in body.splitlines()).strip()
        out[label] = body
    return out


# ============================================================================
# Tier 1 — pure logic
# ============================================================================


def test_source_trust_vocab():
    assert ci.SOURCE_TRUST_VALUES == frozenset({
        "director", "vip", "known_counterparty", "internal_system",
        "public_source", "marketing_or_bulk", "unknown", "untrusted_legacy",
    })


def test_classify_flash_model_is_untrusted_legacy():
    """AC2 — a barred (Flash) extraction model can never be trusted, even from
    the Director."""
    assert ci.classify_source_trust(
        extraction_model="gemini-2.5-flash", is_director=True
    ) == "untrusted_legacy"
    # empty model also fails closed
    assert ci.classify_source_trust(extraction_model="") == "untrusted_legacy"


def test_classify_legacy_flag_and_hints_and_default():
    assert ci.classify_source_trust(legacy=True) == "untrusted_legacy"
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro", is_director=True) == "director"
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro", is_vip=True) == "vip"
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro",
                                    is_known_counterparty=True) == "known_counterparty"
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro",
                                    is_marketing_or_bulk=True) == "marketing_or_bulk"
    assert ci.classify_source_trust(source_type="clickup", extraction_model="gemini-2.5-pro") == "internal_system"
    assert ci.classify_source_trust(source_type="rss", extraction_model="gemini-2.5-pro") == "public_source"
    assert ci.classify_source_trust(source_type="email", extraction_model="gemini-2.5-pro") == "unknown"
    # explicit valid value passes through (when model trusted + not legacy)
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro", explicit="vip") == "vip"
    # explicit garbage ignored -> falls through to default
    assert ci.classify_source_trust(extraction_model="gemini-2.5-pro", explicit="bogus") == "unknown"


def test_can_promote():
    assert ci.can_promote("director") is True
    assert ci.can_promote("unknown") is True
    assert ci.can_promote("untrusted_legacy") is False


def test_dedup_key_content_based():
    k1 = ci.compute_dedup_key("Counterparty missed the SW deadline", "hagenauer-rg7", ["Hassa"], None)
    # whitespace + case normalized -> same key
    k2 = ci.compute_dedup_key("counterparty   missed the SW DEADLINE", "hagenauer-rg7", ["Hassa"], None)
    assert k1 == k2
    # people order-independent
    k3 = ci.compute_dedup_key("x", "m", ["A", "B"], None)
    k4 = ci.compute_dedup_key("x", "m", ["B", "A"], None)
    assert k3 == k4
    # different matter -> different key
    assert ci.compute_dedup_key("x", "m1", [], None) != ci.compute_dedup_key("x", "m2", [], None)
    # different summary -> different key
    assert k1 != ci.compute_dedup_key("totally different", "hagenauer-rg7", ["Hassa"], None)


def test_dismiss_reason_gate(monkeypatch):
    monkeypatch.setattr(ci, "_get_conn", lambda: pytest.fail("DB must not be reached"))
    r = ci.dismiss_candidate(1, "not-a-reason", "director")
    assert r["ok"] is False and r["error"] == "bad_dismiss_reason"


@pytest.mark.parametrize(
    "source,title",
    [
        ("scheduler_job_liveness", "SCHEDULER JOB STALE: gold_audit"),
        # G3 #4162 blocker — the WAHA-UNREACHABLE '_poll' variant (live leak,
        # alert id=25165) must also skip; it matches no title regex.
        ("waha_session_poll", "WAHA UNREACHABLE"),
    ],
)
def test_bridge_alert_skips_infra_stoplist_noise(monkeypatch, source, title):
    """INFRA_ALERT_FILTER_1 — the V2 alert bridge reuses the shared stoplist so
    infra-health alerts never reach the Director Today feed. Test the public
    chokepoint: a stoplist source short-circuits BEFORE create_candidate (no DB)."""
    monkeypatch.setattr(
        ci, "create_candidate",
        lambda *a, **k: pytest.fail("create_candidate must not be called for stoplist noise"),
    )
    res = ci.bridge_alert_to_candidate({"id": 1, "source": source, "title": title})
    assert res["ok"] is True
    assert res["created"] is False
    assert res["skipped_reason"] == "stoplist_noise"


def test_bridge_alert_bridges_real_matter_alert(monkeypatch):
    """INFRA_ALERT_FILTER_1 — a real matter alert (non-stoplist source, real
    title) passes the filter and reaches create_candidate (created=True)."""
    captured = {}

    def _fake_create_candidate(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "created": True, "candidate_id": 99}

    monkeypatch.setattr(ci, "create_candidate", _fake_create_candidate)
    res = ci.bridge_alert_to_candidate(
        {"id": 42, "source": "pipeline", "title": "Hassa settlement counter-offer received",
         "matter_slug": "hagenauer-rg7"}
    )
    assert res["ok"] is True
    assert res["created"] is True
    assert captured["raw_source_table"] == "alerts"
    assert captured["raw_source_id"] == "42"


def test_verifier_actor_allowlist_vocab():
    """deputy-codex F1 — manual verifier must be an allowlisted actor (mirrors
    RATIFY_ACTOR_TYPES), not just 'not system'."""
    from models.verified_items import RATIFY_ACTOR_TYPES
    assert ci.VERIFIER_ACTOR_TYPES == frozenset({"director", "head_of_desk", "cortex_tier_b"})
    assert ci.VERIFIER_ACTOR_TYPES == RATIFY_ACTOR_TYPES


@pytest.mark.parametrize("actor_type", ["system", "anonymous", "unknown", "", "bot"])
def test_verify_manual_rejects_non_allowlisted_verifier(monkeypatch, actor_type):
    """Guard #6 + deputy-codex F1 — any non-allowlisted verifier (system,
    anonymous, unknown, blank, arbitrary) is refused before DB access."""
    monkeypatch.setattr(ci, "_get_conn", lambda: pytest.fail("DB must not be reached"))
    r = ci.promote_candidate_manual(
        1, item_type="deadline", claim="c", actor_type=actor_type, actor_id="x",
        confidence="high", source_trust="director", verification_summary="s",
        counterargument="c2",
    )
    assert r["ok"] is False and r["error"] == "verifier_required"


def test_fault_tolerant_no_connection(monkeypatch):
    monkeypatch.setattr(ci, "_get_conn", lambda: None)
    monkeypatch.setattr(ci, "_put_conn", lambda c: None)
    assert ci.create_candidate("email", "1", "deadline", "s", "gemini-2.5-pro")["error"] == "db_error"
    assert ci.list_candidates() == []
    assert ci.get_candidate(1) is None
    assert ci.dismiss_candidate(1, "duplicate", "director")["error"] == "db_error"


# ---- migration parse-level ----


def test_migration_d_parses_and_is_idempotent():
    sec = _parse_sections(MIG_D.read_text())
    assert "up" in sec and "down" in sec
    assert "ADD COLUMN IF NOT EXISTS dedup_key" in sec["up"]
    assert "ADD COLUMN IF NOT EXISTS due_at" in sec["up"]
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_candidates_dedup" in sec["up"]
    assert "CONCURRENTLY" not in sec["up"].upper()
    # every ADD COLUMN / CREATE INDEX is IF NOT EXISTS
    for kind, tail in re.findall(r"(ADD COLUMN|CREATE INDEX|CREATE UNIQUE INDEX)([^\n;]*)", sec["up"]):
        assert "IF NOT EXISTS" in tail, f"non-idempotent {kind}: {tail.strip()}"


def test_migration_d_down_commented_in_raw():
    raw = MIG_D.read_text()
    down = raw[raw.index("== migrate:down =="):]
    for line in down.splitlines():
        if "DROP" in line:
            assert line.lstrip().startswith("--"), f"uncommented DROP in raw file: {line}"


def test_verify_manual_endpoint_maps_bad_status_to_409(monkeypatch):
    """F3 — the verify-manual endpoint maps an expected bad_candidate_status
    (double-click / already-dismissed) to HTTP 409, not a 500."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key-f3")
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as e:  # pragma: no cover - env-dependent import
        pytest.skip(f"dashboard app unavailable: {e}")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key-f3", raising=False)
    # endpoint re-imports promote_candidate_manual from the module at call time,
    # so patching the module attribute is sufficient. actor_type='director' clears
    # the endpoint's verifier allowlist; the patched service then returns the
    # conflict we want mapped.
    monkeypatch.setattr(
        ci, "promote_candidate_manual",
        lambda *a, **k: {"ok": False, "error": "bad_candidate_status", "detail": "already promoted"},
    )
    client = TestClient(dash.app)
    r = client.post(
        "/api/triage/5/verify-manual",
        headers={"X-Baker-Key": "test-key-f3"},
        json={"item_type": "deadline", "claim": "c", "actor_type": "director",
              "actor_id": "dvallen", "confidence": "high", "source_trust": "director",
              "verification_summary": "s", "counterargument": "c2"},
    )
    assert r.status_code == 409


def test_verify_manual_endpoint_rejects_non_allowlisted_actor(monkeypatch):
    """F1 (endpoint boundary) — a non-allowlisted actor_type is a 400 at the
    endpoint, before the service is even called."""
    monkeypatch.setenv("BAKER_API_KEY", "test-key-f1")
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as e:  # pragma: no cover
        pytest.skip(f"dashboard app unavailable: {e}")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key-f1", raising=False)
    client = TestClient(dash.app)
    r = client.post(
        "/api/triage/5/verify-manual",
        headers={"X-Baker-Key": "test-key-f1"},
        json={"item_type": "deadline", "claim": "c", "actor_type": "anonymous",
              "actor_id": "x", "confidence": "high", "source_trust": "director",
              "verification_summary": "s", "counterargument": "c2"},
    )
    assert r.status_code == 400


def test_morning_brief_does_not_read_signal_candidates():
    """AC8 (structural) — the morning-brief endpoint must never query
    signal_candidates, so candidates can't leak into Today."""
    src = DASHBOARD.read_text()
    m = re.search(r"async def get_morning_brief\(.*?(?=\nasync def |\n@app\.)", src, re.DOTALL)
    assert m, "get_morning_brief function not found"
    body = m.group(0)
    assert "signal_candidates" not in body, "morning-brief must not read signal_candidates"


# ============================================================================
# Tier 2 — live-PG
# ============================================================================


def _apply_migrations(conn):
    for path in (MIG_C, MIG_D):
        sec = _parse_sections(path.read_text())
        with conn.cursor() as cur:
            cur.execute(sec["up"])
            conn.commit()
            cur.execute(sec["up"])  # idempotency
            conn.commit()


@pytest.fixture
def live_ci(needs_live_pg, monkeypatch):
    """Apply 20260622c + 20260622d to the live test DB and redirect both
    candidate_ingest and verified_items connection helpers there."""
    import models.verified_items as vi

    conn = psycopg2.connect(needs_live_pg)
    try:
        _apply_migrations(conn)
    finally:
        conn.close()

    def _get():
        return psycopg2.connect(needs_live_pg)

    def _put(c):
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    monkeypatch.setattr(ci, "_get_conn", _get)
    monkeypatch.setattr(ci, "_put_conn", _put)
    monkeypatch.setattr(vi, "_get_conn", _get)
    monkeypatch.setattr(vi, "_put_conn", _put)
    return needs_live_pg


def test_create_candidate_dedup_idempotent(live_ci):
    """AC4 — two creates with identical content collapse to one row."""
    r1 = ci.create_candidate("email", "msg-1", "deadline", "Pay invoice by Friday",
                             "gemini-2.5-pro", matter_slug="ao", people=["Hassa"])
    assert r1["ok"] and r1["created"] is True
    r2 = ci.create_candidate("email", "msg-DIFFERENT-ID", "deadline",
                             "pay invoice  by FRIDAY", "gemini-2.5-pro",
                             matter_slug="ao", people=["Hassa"])
    assert r2["ok"] and r2["created"] is False  # same dedup_key
    assert r2["id"] == r1["id"]


def test_create_candidate_flash_is_untrusted(live_ci):
    """AC2 — a Flash extraction model yields an untrusted_legacy candidate that
    cannot be promoted."""
    r = ci.create_candidate("email", "flash-1", "deadline", "flash-extracted claim",
                            "gemini-2.5-flash", matter_slug="ao")
    assert r["ok"] and r["trusted_model"] is False
    assert r["source_trust"] == "untrusted_legacy"
    assert ci.can_promote(r["source_trust"]) is False


def test_legacy_bridge_idempotent(live_ci):
    """AC3 — bridging the same alert twice creates exactly one candidate."""
    alert = {"id": 4242, "title": "Quiet thread with Hassa", "body": "no reply 5d",
             "matter_slug": "hagenauer-rg7", "structured_actions": {"trigger": "quiet_thread"}}
    a = ci.bridge_alert_to_candidate(alert)
    assert a["ok"] and a["created"] is True and a["source_trust"] == "untrusted_legacy"
    b = ci.bridge_alert_to_candidate(alert)
    assert b["ok"] and b["created"] is False and b["id"] == a["id"]


def test_batch_bridge_pending_alerts(live_ci):
    """AC3 — batch bridge reads pending alerts and is idempotent on re-run."""
    conn = psycopg2.connect(live_ci)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY, title TEXT, body TEXT, matter_slug TEXT,
                    status TEXT, structured_actions JSONB, created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("DELETE FROM alerts")
            cur.execute(
                "INSERT INTO alerts (title, body, matter_slug, status, structured_actions) "
                "VALUES ('Legacy fire', 'body', 'ao', 'pending', '{}'::jsonb)"
            )
            conn.commit()
    finally:
        conn.close()
    first = ci.bridge_pending_alerts()
    assert first["ok"] and first["bridged"] == 1
    second = ci.bridge_pending_alerts()
    assert second["ok"] and second["bridged"] == 0 and second["skipped"] == 1


def test_verify_manual_records_human_verifier_in_events(live_ci):
    """GUARD #6 (mandatory) — manual promotion records the HUMAN verifier in
    verification_events (to_state='verified', actor_type/actor_id = the verifier),
    not only in created_by, and not actor_type='system'."""
    cand = ci.create_candidate("email", "promote-1", "deadline",
                               "Counterparty owes SW spec", "gemini-2.5-pro",
                               matter_slug="hagenauer-rg7", people=["Hassa"])
    assert cand["ok"] and ci.can_promote(cand["source_trust"])

    res = ci.promote_candidate_manual(
        cand["id"], item_type="deadline",
        claim="Counterparty must deliver SW spec by 2026-07-01.",
        actor_type="director", actor_id="dvallen",
        confidence="high", source_trust="known_counterparty",
        verification_summary="Checked email + matter timeline.",
        counterargument="Could be a non-binding acknowledgement.",
    )
    assert res["ok"], res
    item_id = res["verified_item_id"]

    from models.verified_items import get_events, list_items
    events = get_events(item_id)
    # creation event (system) + verification event (human)
    verify_evts = [e for e in events if e["to_state"] == "verified"]
    assert len(verify_evts) == 1
    ve = verify_evts[0]
    assert ve["actor_type"] == "director" and ve["actor_id"] == "dvallen"
    assert ve["actor_type"] != "system"
    # the verified item exists and links back to the candidate
    item = next(x for x in list_items(state="verified") if x["id"] == item_id)
    assert item["signal_candidate_id"] == cand["id"]


def test_verify_manual_refuses_untrusted_legacy(live_ci):
    """AC2.3 — an untrusted_legacy candidate cannot be promoted without re-extraction."""
    cand = ci.create_candidate("alerts", "legacy-9", "alert", "old flash claim",
                               "gemini-2.5-flash", matter_slug="ao")
    assert cand["ok"]
    res = ci.promote_candidate_manual(
        cand["id"], item_type="alert", claim="c", actor_type="director",
        actor_id="dvallen", confidence="high", source_trust="internal_system",
        verification_summary="s", counterargument="c2",
    )
    assert res["ok"] is False and res["error"] == "not_promotable"


def test_dismiss_candidate_live(live_ci):
    """AC10 — dismiss stores a structured reason."""
    cand = ci.create_candidate("email", "dismiss-1", "alert", "marketing blast",
                               "gemini-2.5-pro")
    r = ci.dismiss_candidate(cand["id"], "marketing", "director")
    assert r["ok"] and r["dismiss_reason"] == "marketing"
    fetched = ci.get_candidate(cand["id"])
    assert fetched["status"] == "dismissed" and fetched["dismiss_reason"] == "marketing"


def test_list_candidates_filters(live_ci):
    """AC7 — matter/trust/status filters work and return no raw-body columns (AC9)."""
    ci.create_candidate("email", "f-1", "deadline", "matter ao item", "gemini-2.5-pro",
                        matter_slug="ao")
    ci.create_candidate("email", "f-2", "deadline", "matter hag item", "gemini-2.5-pro",
                        matter_slug="hagenauer-rg7")
    ao = ci.list_candidates(matter_slug="ao")
    assert ao and all(r["matter_slug"] == "ao" for r in ao)
    # AC9 — no raw body fields surface
    for r in ao:
        assert "body" not in r and "raw_body" not in r
        assert set(r.keys()) <= set(ci._CANDIDATE_PUBLIC_COLS)


def test_verify_manual_refuses_dismissed_candidate(live_ci):
    """Codex F1 — a dismissed candidate cannot be promoted (quarantine integrity)."""
    cand = ci.create_candidate("email", "f1-dismissed", "alert", "noise blast",
                               "gemini-2.5-pro", matter_slug="ao")
    assert ci.dismiss_candidate(cand["id"], "marketing", "director")["ok"]
    res = ci.promote_candidate_manual(
        cand["id"], item_type="alert", claim="c", actor_type="director",
        actor_id="dvallen", confidence="high", source_trust="internal_system",
        verification_summary="s", counterargument="c2",
    )
    assert res["ok"] is False and res["error"] == "bad_candidate_status"


def test_verify_manual_no_double_promote(live_ci):
    """Codex F1 — a second verify-manual on an already-promoted candidate is
    refused, so no duplicate verified_items is minted for one signal_candidate."""
    cand = ci.create_candidate("email", "f1-double", "deadline", "real obligation",
                               "gemini-2.5-pro", matter_slug="hagenauer-rg7")
    common = dict(
        item_type="deadline", claim="Deliver SW spec.", actor_type="director",
        actor_id="dvallen", confidence="high", source_trust="known_counterparty",
        verification_summary="checked", counterargument="maybe non-binding",
    )
    first = ci.promote_candidate_manual(cand["id"], **common)
    assert first["ok"], first
    second = ci.promote_candidate_manual(cand["id"], **common)
    assert second["ok"] is False and second["error"] == "bad_candidate_status"
    # exactly one verified_items row references this candidate
    conn = psycopg2.connect(live_ci)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM verified_items WHERE signal_candidate_id = %s",
                (cand["id"],),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def _insert_raw_candidate(dsn, *, extraction_model, source_trust, dedup_key):
    """Insert a candidate row directly (bypassing create_candidate's classifier)
    so we can craft the null-source_trust cases deputy-codex F2 probes."""
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO signal_candidates "
                "(raw_source_table, raw_source_id, candidate_type, summary, "
                " extraction_model, source_trust, status, dedup_key) "
                "VALUES ('email', %s, 'deadline', 'crafted row', %s, %s, "
                "'awaiting_verification', %s) RETURNING id",
                (dedup_key, extraction_model, source_trust, dedup_key),
            )
            cid = cur.fetchone()[0]
            conn.commit()
            return cid
    finally:
        conn.close()


def test_verify_manual_refuses_flash_extraction_even_when_trust_null(live_ci):
    """deputy-codex F2 — a candidate with NULL source_trust but a Flash
    extraction_model cannot be promoted (the model gate fires regardless of
    stored trust)."""
    cid = _insert_raw_candidate(live_ci, extraction_model="gemini-2.5-flash",
                                source_trust=None, dedup_key="f2-flash-null")
    res = ci.promote_candidate_manual(
        cid, item_type="deadline", claim="c", actor_type="director",
        actor_id="dvallen", confidence="high", source_trust="known_counterparty",
        verification_summary="s", counterargument="c2",
    )
    assert res["ok"] is False and res["error"] == "not_promotable"


def test_verify_manual_allows_pro_extraction_when_trust_null(live_ci):
    """deputy-codex F2 — a candidate with NULL source_trust but a Pro
    extraction_model + a complete human evidence packet CAN be promoted."""
    cid = _insert_raw_candidate(live_ci, extraction_model="gemini-2.5-pro",
                                source_trust=None, dedup_key="f2-pro-null")
    res = ci.promote_candidate_manual(
        cid, item_type="deadline", claim="Real obligation.", actor_type="director",
        actor_id="dvallen", confidence="high", source_trust="known_counterparty",
        verification_summary="checked", counterargument="maybe non-binding",
    )
    assert res["ok"] is True
    # human verifier still recorded in verification_events (guard #6 holds)
    from models.verified_items import get_events
    ve = [e for e in get_events(res["verified_item_id"]) if e["to_state"] == "verified"]
    assert ve and ve[0]["actor_type"] == "director"


def test_list_candidates_created_window(live_ci):
    """Codex F2 / AC7 — created-date window filter works at the service layer."""
    from datetime import datetime, timedelta, timezone
    ci.create_candidate("email", "window-1", "deadline", "windowed item",
                        "gemini-2.5-pro", matter_slug="window-test")
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    # created_after in the future -> excluded
    assert ci.list_candidates(matter_slug="window-test", created_after=future) == []
    # created_after in the past AND created_before in the future -> included
    got = ci.list_candidates(matter_slug="window-test", created_after=past,
                             created_before=future)
    assert any(r["matter_slug"] == "window-test" for r in got)
