"""BAKER_DASHBOARD_V2_VERIFIER_1 — tests for the trusted Opus-class candidate
verifier (orchestrator/candidate_verifier.py) and the AC5 Cortex promotion helper
(orchestrator/candidate_ingest.promote_candidate_verified_by_cortex).

Three tiers:
  1. Pure-logic (always run) — source-adapter allowlist + hard-coded SQL proof,
     strict-JSON parse, evidence validation, sanitization (no raw-body leak), and
     the orchestration guards (refuse non-awaiting, cost-breaker-before-LLM,
     log-cost-after-LLM, Opus-class-only model) driven with fake LLM/DB seams.
  2. Endpoint (TestClient) — auth gate + error-code mapping for /verify-auto and
     /verifier/health, plus a no-raw-body-key assertion on the response.
  3. Live-PG (gated via needs_live_pg) — full candidate -> verified through the
     REAL promotion helper: Cortex actor + verifier model in verification_events,
     extraction_model=verifier, original model preserved, untrusted_legacy
     promotable here (unlike manual), and the row readable by Today.
"""
from __future__ import annotations

import inspect

import pytest

import orchestrator.candidate_verifier as cv
import orchestrator.candidate_ingest as ci
import orchestrator.model_policy as mp

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeResp:
    """Mimics kbl.anthropic_client.call_opus's response object."""

    def __init__(self, text: str, model_id: str = "claude-opus-4-8"):
        self.text = text
        self.model_id = model_id
        self.input_tokens = 1200
        self.output_tokens = 300
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0


_GOOD_JSON = (
    '{"verdict":"promote","item_type":"deadline","claim":"Counterparty must '
    'deliver the SW spec by 2026-07-01.","why_matters":"Blocks handover.",'
    '"next_action":"Chase Hassa.","owner":"Director","due_at":"2026-07-01T00:00:00Z",'
    '"confidence":"high","matter_slug":"hagenauer-rg7","related_matters":[],'
    '"people":["Hassa"],"source_trust":"known_counterparty",'
    '"verification_summary":"Cross-checked the email body against the matter '
    'timeline.","counterargument":"Could be a non-binding acknowledgement.",'
    '"reject_reason":null}'
)


def _awaiting_candidate(**over):
    base = {
        "id": 7, "raw_source_table": "email_messages", "raw_source_id": "msg-7",
        "candidate_type": "deadline", "summary": "owes SW spec",
        "extraction_model": "gemini-2.5-pro", "extraction_confidence": "high",
        "source_model": None, "matter_slug": "hagenauer-rg7", "people": ["Hassa"],
        "source_trust": "known_counterparty", "status": "awaiting_verification",
        "dismiss_reason": None, "due_at": None, "created_at": None,
    }
    base.update(over)
    return base


def _patch_verify_seams(monkeypatch, *, candidate=None, breaker=(True, 1.0),
                        resp=None, existing=None):
    """Wire verify_candidate's DB/LLM/cost seams to fakes. Returns a dict of
    call-trackers the test can assert on."""
    import orchestrator.cost_monitor as cm

    tracker = {"opus_called": False, "cost_logged": [], "promote_called": []}

    monkeypatch.setattr(ci, "get_candidate",
                        lambda cid: candidate if candidate is not None else _awaiting_candidate())
    monkeypatch.setattr(ci, "_get_conn", lambda: object())  # non-None sentinel
    monkeypatch.setattr(ci, "_put_conn", lambda c: None)
    monkeypatch.setattr(cv, "_existing_verified_item_id", lambda conn, cid: existing)
    monkeypatch.setattr(
        cv, "fetch_source_context",
        lambda conn, table, rid: {
            "ok": True, "source_type": table,
            "source_ref": {"table": table, "id": rid},
            "metadata": {"subject": "SW spec"},
            "text_for_prompt": "RAW EMAIL BODY — must stay prompt-only",
        },
    )
    monkeypatch.setattr(cm, "check_circuit_breaker", lambda: breaker)

    def _fake_log(*a, **k):
        tracker["cost_logged"].append((a, k))

    monkeypatch.setattr(cm, "log_api_cost", _fake_log)

    def _fake_opus(system, user, *, model, max_tokens):
        tracker["opus_called"] = True
        tracker["opus_model"] = model
        tracker["opus_user"] = user
        return resp if resp is not None else FakeResp(_GOOD_JSON)

    monkeypatch.setattr(cv, "_call_opus", _fake_opus)

    def _fake_promote(cid, *, evidence, actor_id, verifier_model):
        tracker["promote_called"].append(
            {"cid": cid, "evidence": evidence, "actor_id": actor_id,
             "verifier_model": verifier_model})
        return {"ok": True, "verified_item_id": 555, "candidate_id": cid}

    monkeypatch.setattr(ci, "promote_candidate_verified_by_cortex", _fake_promote)
    return tracker


# ============================================================================
# Tier 1 — pure logic + orchestration guards
# ============================================================================


def test_supported_source_tables_are_allowlisted():
    assert cv.SUPPORTED_SOURCE_TABLES == (
        "email_messages", "whatsapp_messages", "meeting_transcripts",
        "documents", "alerts", "deadlines",
    )
    # adapter map keys exactly match the allowlist — no extra/hidden tables.
    assert set(cv._SOURCE_ADAPTERS.keys()) == set(cv.SUPPORTED_SOURCE_TABLES)


def test_source_adapter_uses_parameterized_sql_no_dynamic_table_interpolation():
    """AC3 — each adapter hard-codes its table name and uses %s for the id; no
    adapter ever interpolates raw_source_table into SQL."""
    for table, adapter in cv._SOURCE_ADAPTERS.items():
        src = inspect.getsource(adapter)
        assert f"FROM {table}" in src, f"{table} adapter must hard-code its table"
        assert "%s" in src, f"{table} adapter must use a parameterized placeholder"
        assert "raw_source_table" not in src, (
            f"{table} adapter must not reference raw_source_table in SQL")
        # no f-string / .format() table-name building inside the SELECT.
        assert ".format(" not in src and 'f"SELECT' not in src and "f'SELECT" not in src


def test_fetch_source_context_unsupported_table_never_queries():
    """AC3 — an unknown table fails BEFORE any DB call (conn must not be touched)."""
    class Boom:
        def cursor(self, *a, **k):
            raise AssertionError("DB must not be reached for an unsupported table")

    out = cv.fetch_source_context(Boom(), "secret_table", "x")
    assert out == {"ok": False, "error": "unsupported_source", "detail": "secret_table"}


def test_parse_verifier_json_rejects_markdown_or_bad_json():
    assert cv.parse_verifier_json("")["_parse_error"] == "empty"
    assert cv.parse_verifier_json("here is your answer: nope")["_parse_error"] == "not_a_json_object"
    assert cv.parse_verifier_json("[1,2,3]")["_parse_error"] == "not_a_json_object"
    assert cv.parse_verifier_json("{bad json}")["_parse_error"].startswith("json_decode")
    # a clean object parses; a single ```json fence is tolerated defensively.
    assert cv.parse_verifier_json('{"verdict":"reject"}')["verdict"] == "reject"
    assert cv.parse_verifier_json('```json\n{"verdict":"promote"}\n```')["verdict"] == "promote"


def test_validate_evidence_requires_claim_why_summary_counterargument():
    # complete promote packet -> no reasons
    assert cv.validate_verifier_evidence({
        "verdict": "promote", "confidence": "high", "claim": "c",
        "why_matters": "w", "verification_summary": "s", "counterargument": "k",
    }) == []
    # missing each required field is reported
    miss = cv.validate_verifier_evidence({
        "verdict": "promote", "confidence": "high", "claim": "", "why_matters": " ",
        "verification_summary": None, "counterargument": "",
    })
    assert set(miss) == {"missing_claim", "missing_why_matters",
                         "missing_verification_summary", "missing_counterargument"}
    assert cv.validate_verifier_evidence({"_parse_error": "x"}) == ["bad_json"]
    assert cv.validate_verifier_evidence({"verdict": "wat"}) == ["illegal_verdict"]


def test_low_confidence_or_needs_human_does_not_promote():
    assert cv.validate_verifier_evidence({
        "verdict": "promote", "confidence": "low", "claim": "c", "why_matters": "w",
        "verification_summary": "s", "counterargument": "k",
    }) == ["low_confidence"]
    assert cv.validate_verifier_evidence({"verdict": "needs_human"}) == ["verdict_needs_human"]
    assert cv.validate_verifier_evidence({"verdict": "reject"}) == ["verdict_reject"]


def test_sanitize_result_removes_raw_body_fields():
    dirty = {
        "ok": True, "verified_item_id": 1, "full_body": "secret",
        "nested": {"full_text": "secret2", "keep": "ok", "raw_body": "x"},
        "list": [{"text_for_prompt": "p", "id": 3}],
        "prompt": "system+user", "source_text": "s",
    }
    clean = cv.sanitize_verifier_result(dirty)
    flat = repr(clean)
    for k in cv._RAW_BODY_KEYS:
        assert k not in clean
        assert f"'{k}'" not in flat  # not hiding in a nested dict/list either
    assert clean["nested"]["keep"] == "ok" and clean["list"][0]["id"] == 3


def test_verify_candidate_refuses_non_awaiting_candidate(monkeypatch):
    _patch_verify_seams(monkeypatch, candidate=_awaiting_candidate(status="promoted"))
    out = cv.verify_candidate(7)
    assert out["ok"] is False and out["error"] == "bad_candidate_status"


def test_verify_candidate_refuses_missing_candidate(monkeypatch):
    monkeypatch.setattr(ci, "get_candidate", lambda cid: None)
    out = cv.verify_candidate(404)
    assert out["ok"] is False and out["error"] == "not_found"


def test_verify_candidate_checks_cost_breaker_before_llm(monkeypatch):
    """AC10 — a tripped breaker returns cost_hard_stop and the Opus call never fires."""
    tr = _patch_verify_seams(monkeypatch, breaker=(False, 987.65))
    out = cv.verify_candidate(7)
    assert out["ok"] is False and out["error"] == "cost_hard_stop"
    assert out["daily_cost_eur"] == 987.65
    assert tr["opus_called"] is False


def test_verify_candidate_logs_cost_after_llm(monkeypatch):
    """AC10 — a successful model call logs cost with source='dashboard_v2_verifier'."""
    tr = _patch_verify_seams(monkeypatch)
    out = cv.verify_candidate(7)
    assert out["ok"] is True and out["verified_item_id"] == 555
    assert len(tr["cost_logged"]) == 1
    _args, kwargs = tr["cost_logged"][0]
    assert kwargs.get("source") == "dashboard_v2_verifier"
    assert kwargs.get("matter_slug") == "hagenauer-rg7"


def test_verify_candidate_uses_trusted_verification_model_not_gemini_or_sonnet(monkeypatch):
    """AC1 — default verifier model is Opus-class; a weak explicit model is refused
    before any DB/LLM work."""
    tr = _patch_verify_seams(monkeypatch)
    cv.verify_candidate(7)
    assert mp.is_allowed_for_trusted_verification(tr["opus_model"])
    assert "sonnet" not in tr["opus_model"] and not tr["opus_model"].startswith("gemini-")

    # explicit weak model -> model_not_allowed, breaker/LLM never reached.
    tr2 = _patch_verify_seams(monkeypatch)
    out = cv.verify_candidate(7, model="gemini-2.5-pro")
    assert out["ok"] is False and out["error"] == "model_not_allowed"
    assert tr2["opus_called"] is False


def test_verify_candidate_dry_run_does_not_promote(monkeypatch):
    tr = _patch_verify_seams(monkeypatch)
    out = cv.verify_candidate(7, dry_run=True)
    assert out["ok"] is True and out["dry_run"] is True and out["would_promote"] is True
    assert tr["promote_called"] == []  # nothing written


def test_verify_candidate_refusal_path_is_sanitized(monkeypatch):
    """A reject verdict returns verification_refused and never promotes."""
    reject = FakeResp('{"verdict":"reject","reject_reason":"noise"}')
    tr = _patch_verify_seams(monkeypatch, resp=reject)
    out = cv.verify_candidate(7)
    assert out["ok"] is False and out["error"] == "verification_refused"
    assert tr["promote_called"] == []
    for k in cv._RAW_BODY_KEYS:
        assert k not in out


def test_verify_candidate_already_verified_conflict(monkeypatch):
    _patch_verify_seams(monkeypatch, existing=42)
    out = cv.verify_candidate(7)
    assert out["ok"] is False and out["error"] == "already_verified"
    assert out["verified_item_id"] == 42


def test_existing_verified_item_id_ignores_orphaned_candidate_shell():
    """The dedup pre-check must only fire on a row that actually reached
    verified/ratified — an orphaned 'candidate'-state shell left by a failed
    transition must NOT block a retry with a false already_verified."""
    captured = {}

    class _Cur:
        def execute(self, sql, params):
            captured["sql"] = " ".join(sql.split())
        def fetchone(self):
            return None  # no verified/ratified row matches the filtered query
        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

    assert cv._existing_verified_item_id(_Conn(), 7) is None
    # the query is state-filtered so a 'candidate'-state shell can't match it
    assert "state in ('verified', 'ratified')" in captured["sql"].lower()


def test_verify_candidate_builds_metadata_only_packet(monkeypatch):
    """AC7 — the evidence packet handed to the promotion helper carries only
    metadata source_refs; raw prompt text never enters it."""
    tr = _patch_verify_seams(monkeypatch)
    cv.verify_candidate(7)
    assert len(tr["promote_called"]) == 1
    packet = tr["promote_called"][0]["evidence"]
    assert packet["source_refs"] == [
        {"table": "email_messages", "id": "msg-7", "candidate_id": 7}]
    assert "text_for_prompt" not in repr(packet)
    assert packet["candidate_extraction_model"] == "gemini-2.5-pro"


# ============================================================================
# Tier 1b — AC5 promotion helper guards (fake create/transition, no live DB)
# ============================================================================


def _good_packet(**over):
    p = {
        "item_type": "deadline", "claim": "c", "why_matters": "w",
        "next_action": "n", "owner": "Director", "due_at": None,
        "confidence": "high", "matter_slug": "hagenauer-rg7", "related_matters": [],
        "people": ["Hassa"], "source_type": "email_messages",
        "source_trust": "known_counterparty",
        "source_refs": [{"table": "email_messages", "id": "m", "candidate_id": 7}],
        "verification_summary": "s", "counterargument": "k",
        "candidate_extraction_model": "gemini-2.5-pro",
    }
    p.update(over)
    return p


def test_cortex_promote_rejects_weak_verifier_model(monkeypatch):
    monkeypatch.setattr(ci, "get_candidate", lambda cid: _awaiting_candidate())
    for bad in ("gemini-2.5-pro", "gemini-2.5-flash", "claude-sonnet-4-6",
                "claude-haiku-4-5", "", None):
        out = ci.promote_candidate_verified_by_cortex(
            7, evidence=_good_packet(), actor_id="cortex:x", verifier_model=bad)
        assert out["ok"] is False and out["error"] == "model_not_allowed", bad


def test_cortex_promote_requires_actor_id(monkeypatch):
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(), actor_id="  ", verifier_model="claude-opus-4-8")
    assert out["ok"] is False and out["error"] == "missing_actor"


def test_cortex_promote_refuses_non_awaiting(monkeypatch):
    monkeypatch.setattr(ci, "get_candidate",
                        lambda cid: _awaiting_candidate(status="promoted"))
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(), actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert out["ok"] is False and out["error"] == "bad_candidate_status"


def test_cortex_promote_missing_evidence(monkeypatch):
    monkeypatch.setattr(ci, "get_candidate", lambda cid: _awaiting_candidate())
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(counterargument=""), actor_id="cortex:x",
        verifier_model="claude-opus-4-8")
    assert out["ok"] is False and out["error"] == "missing_evidence"


def _patch_promote_seams(monkeypatch, *, candidate=None, create_id=900,
                         transition_ok=True):
    import models.verified_items as vi
    calls = {"create_kwargs": None, "transition": None, "released": 0, "claimed": 0}

    monkeypatch.setattr(ci, "get_candidate",
                        lambda cid: candidate if candidate is not None else _awaiting_candidate())

    def _claim(cid):
        calls["claimed"] += 1
        return True

    def _release(cid):
        calls["released"] += 1

    monkeypatch.setattr(ci, "_claim_candidate_for_promotion", _claim)
    monkeypatch.setattr(ci, "_release_candidate_claim", _release)

    def _create(**kwargs):
        calls["create_kwargs"] = kwargs
        return create_id

    def _transition(item_id, to_state, **kwargs):
        calls["transition"] = {"item_id": item_id, "to_state": to_state, **kwargs}
        return {"ok": transition_ok, "event_id": 1} if transition_ok else {"ok": False, "error": "x"}

    monkeypatch.setattr(vi, "create_verified_item", _create)
    monkeypatch.setattr(vi, "transition_item", _transition)
    return calls


def test_cortex_promote_sets_verifier_extraction_model_and_preserves_original(monkeypatch):
    """AC5.8/AC5.9/AC5.10 — verified_items.extraction_model = verifier model,
    source_model preserves the original candidate model, and the verified-event
    records actor_type=cortex_tier_b + model=verifier + original in evidence_delta."""
    calls = _patch_promote_seams(monkeypatch)
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(), actor_id="cortex:dashboard-v2-verifier",
        verifier_model="claude-opus-4-8")
    assert out["ok"] is True and out["verified_item_id"] == 900

    ck = calls["create_kwargs"]
    assert ck["state"] == "candidate"
    assert ck["extraction_model"] == "claude-opus-4-8"        # AC5.8 — verifier model
    assert ck["source_model"] == "gemini-2.5-pro"             # AC5.9 — original preserved

    tr = calls["transition"]
    assert tr["to_state"] == "verified" and tr["actor_type"] == "cortex_tier_b"
    assert tr["actor_id"] == "cortex:dashboard-v2-verifier"
    assert tr["model"] == "claude-opus-4-8"                   # AC5.10
    assert tr["evidence_delta"]["candidate_extraction_model"] == "gemini-2.5-pro"
    assert tr["evidence_delta"]["verifier_model"] == "claude-opus-4-8"


def test_cortex_promote_allows_untrusted_legacy_unlike_manual(monkeypatch):
    """The DEFINING distinction (STOP cond 5): the Cortex helper MAY promote an
    untrusted_legacy / Flash-extracted candidate because the Opus re-verification
    IS the re-extraction. promote_candidate_manual refuses the same candidate."""
    legacy = _awaiting_candidate(source_trust="untrusted_legacy",
                                 extraction_model="gemini-2.5-flash")
    calls = _patch_promote_seams(monkeypatch, candidate=legacy)
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(candidate_extraction_model="gemini-2.5-flash"),
        actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert out["ok"] is True  # promoted despite untrusted_legacy
    # original (barred) model still preserved for the audit trail
    assert calls["create_kwargs"]["source_model"] == "gemini-2.5-flash"


def test_cortex_promote_releases_claim_on_create_failure(monkeypatch):
    calls = _patch_promote_seams(monkeypatch, create_id=None)
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(), actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert out["ok"] is False and out["error"] == "create_failed"
    assert calls["claimed"] == 1 and calls["released"] == 1


def test_cortex_promote_releases_claim_on_transition_failure(monkeypatch):
    calls = _patch_promote_seams(monkeypatch, transition_ok=False)
    out = ci.promote_candidate_verified_by_cortex(
        7, evidence=_good_packet(), actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert out["ok"] is False and out["error"] == "promote_failed"
    assert calls["claimed"] == 1 and calls["released"] == 1


# ============================================================================
# Tier 1c — verifier health
# ============================================================================


def test_get_verifier_health_metadata_only(monkeypatch):
    monkeypatch.setattr(ci, "_get_conn", lambda: None)  # count unavailable path
    monkeypatch.setattr(ci, "_put_conn", lambda c: None)
    h = cv.get_verifier_health()
    assert h["status"] == "ok"
    assert mp.is_allowed_for_trusted_verification(h["verifier_model"])
    assert h["verifier_model_allowed"] is True
    assert set(h["supported_source_tables"]) == set(cv.SUPPORTED_SOURCE_TABLES)
    for k in cv._RAW_BODY_KEYS:
        assert k not in repr(h)


# ============================================================================
# Tier 2 — endpoints (TestClient)
# ============================================================================


def _client(monkeypatch, key="test-key-verifier"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    try:
        from fastapi.testclient import TestClient
        import outputs.dashboard as dash
    except Exception as e:  # pragma: no cover - env-dependent import
        pytest.skip(f"dashboard app unavailable: {e}")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", key, raising=False)
    return TestClient(dash.app), dash, key


def test_health_endpoint_rejects_missing_key(monkeypatch):
    client, _dash, _key = _client(monkeypatch)
    r = client.get("/api/triage/verifier/health")
    assert r.status_code in (401, 403)


def test_health_endpoint_returns_allowed_model_with_key(monkeypatch):
    client, dash, key = _client(monkeypatch)
    monkeypatch.setattr(
        cv, "get_verifier_health",
        lambda: {"status": "ok", "verifier_model": "claude-opus-4-8",
                 "verifier_model_allowed": True,
                 "supported_source_tables": list(cv.SUPPORTED_SOURCE_TABLES)},
    )
    r = client.get("/api/triage/verifier/health", headers={"X-Baker-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["verifier_model_allowed"] is True
    assert body["verifier_model"] == "claude-opus-4-8"


def test_verify_auto_endpoint_rejects_missing_key(monkeypatch):
    client, _dash, _key = _client(monkeypatch)
    r = client.post("/api/triage/7/verify-auto", json={})
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("error,code", [
    ("not_found", 404),
    ("source_not_found", 404),
    ("bad_candidate_status", 409),
    ("already_verified", 409),
    ("cost_hard_stop", 503),
    ("provider_unavailable", 503),
    ("unsupported_source", 400),
    ("verification_refused", 400),
    ("model_not_allowed", 400),
    ("missing_evidence", 400),
    ("bad_json", 400),
    ("promote_failed", 500),
])
def test_verify_auto_endpoint_error_mapping(monkeypatch, error, code):
    client, _dash, key = _client(monkeypatch)
    monkeypatch.setattr(cv, "verify_candidate",
                        lambda *a, **k: {"ok": False, "error": error})
    r = client.post("/api/triage/7/verify-auto", headers={"X-Baker-Key": key}, json={})
    assert r.status_code == code, f"{error} should map to {code}, got {r.status_code}"


def test_verify_auto_endpoint_success_no_raw_body(monkeypatch):
    client, _dash, key = _client(monkeypatch)
    monkeypatch.setattr(
        cv, "verify_candidate",
        lambda *a, **k: {"ok": True, "candidate_id": 7, "verified_item_id": 555,
                         "verifier_model": "claude-opus-4-8", "confidence": "high"},
    )
    r = client.post("/api/triage/7/verify-auto", headers={"X-Baker-Key": key},
                    json={"dry_run": False})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["verified_item_id"] == 555
    for k in cv._RAW_BODY_KEYS:
        assert k not in r.text


def test_verify_auto_endpoint_default_actor_and_dry_run(monkeypatch):
    client, _dash, key = _client(monkeypatch)
    seen = {}

    def _fake(candidate_id, *, actor_id, dry_run, model=None):
        seen["actor_id"] = actor_id
        seen["dry_run"] = dry_run
        return {"ok": True, "dry_run": dry_run, "candidate_id": candidate_id}

    monkeypatch.setattr(cv, "verify_candidate", _fake)
    # empty body -> default actor, dry_run False
    client.post("/api/triage/7/verify-auto", headers={"X-Baker-Key": key}, json={})
    assert seen["actor_id"] == "cortex:dashboard-v2-verifier" and seen["dry_run"] is False
    client.post("/api/triage/7/verify-auto", headers={"X-Baker-Key": key},
                json={"actor_id": "cortex:custom", "dry_run": True})
    assert seen["actor_id"] == "cortex:custom" and seen["dry_run"] is True


# ============================================================================
# Tier 3 — live-PG: full candidate -> verified through the REAL helper
# ============================================================================

from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_MIG_C = REPO / "migrations" / "20260622c_dashboard_v2_evidence_packet.sql"
_MIG_D = REPO / "migrations" / "20260622d_signal_candidates_dedup.sql"

import re  # noqa: E402

_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _up_section(sql: str) -> str:
    matches = list(_SECTION_RE.finditer(sql))
    for i, m in enumerate(matches):
        if m.group(1) == "up":
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(sql)
            return sql[start:end].strip()
    return sql


@pytest.fixture
def live_verifier(needs_live_pg, monkeypatch):
    """Apply the evidence-packet + dedup migrations to the live test DB and
    redirect candidate_ingest + verified_items connection helpers there."""
    import models.verified_items as vi

    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            for path in (_MIG_C, _MIG_D):
                cur.execute(_up_section(path.read_text()))
                conn.commit()
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


def test_cortex_promotion_full_flow_live(live_verifier):
    """Live: a Cortex-verified candidate becomes a `verified` item whose audit
    event records actor_type='cortex_tier_b' + the verifier model; the row carries
    extraction_model=verifier, preserves the original model, and is readable by
    Today. Also proves an untrusted_legacy candidate is promotable on this path."""
    from models.verified_items import get_events, list_items, list_today_items

    cand = ci.create_candidate(
        "email_messages", "live-promote-1", "deadline",
        "Counterparty owes the SW spec", "gemini-2.5-flash",  # barred -> untrusted_legacy
        matter_slug="hagenauer-rg7", people=["Hassa"])
    assert cand["ok"] and cand["source_trust"] == "untrusted_legacy"

    packet = _good_packet(
        source_refs=[{"table": "email_messages", "id": "live-promote-1",
                      "candidate_id": cand["id"]}],
        candidate_extraction_model="gemini-2.5-flash")
    res = ci.promote_candidate_verified_by_cortex(
        cand["id"], evidence=packet, actor_id="cortex:dashboard-v2-verifier",
        verifier_model="claude-opus-4-8")
    assert res["ok"], res
    item_id = res["verified_item_id"]

    # candidate is now claimed/promoted
    assert ci.get_candidate(cand["id"])["status"] == "promoted"

    # the verified item carries verifier-as-extraction-model + original preserved
    item = next(x for x in list_items(state="verified") if x["id"] == item_id)
    assert item["extraction_model"] == "claude-opus-4-8"
    assert item["source_model"] == "gemini-2.5-flash"
    assert item["signal_candidate_id"] == cand["id"]

    # audit event records the Cortex verifier + verifier model + original model
    verify_evts = [e for e in get_events(item_id) if e["to_state"] == "verified"]
    assert len(verify_evts) == 1
    ve = verify_evts[0]
    assert ve["actor_type"] == "cortex_tier_b" and ve["actor_id"]
    assert ve["actor_type"] != "system"
    assert ve["model"] == "claude-opus-4-8"
    assert ve["evidence_delta"]["candidate_extraction_model"] == "gemini-2.5-flash"

    # Today can read it (state == verified)
    assert any(r["id"] == item_id for r in list_today_items())


def test_cortex_promotion_double_submit_is_conflict_live(live_verifier):
    """A second promotion of the same candidate loses the atomic claim -> conflict,
    no duplicate verified row."""
    cand = ci.create_candidate("email_messages", "live-dup-1", "deadline",
                               "owes spec", "gemini-2.5-pro", matter_slug="ao")
    packet = _good_packet(source_refs=[{"table": "email_messages", "id": "live-dup-1",
                                        "candidate_id": cand["id"]}])
    first = ci.promote_candidate_verified_by_cortex(
        cand["id"], evidence=packet, actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert first["ok"]
    second = ci.promote_candidate_verified_by_cortex(
        cand["id"], evidence=packet, actor_id="cortex:x", verifier_model="claude-opus-4-8")
    assert second["ok"] is False and second["error"] == "bad_candidate_status"
