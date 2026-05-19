"""Tests for orchestrator/cortex_phase4_5_director_card.py — CORTEX_DIRECTOR_CARD_V1.

Brief: ``briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md`` (criterion 10).

Six cases:
  (a) happy path returns a valid 9-field card.
  (b) malformed proposal_text → fail-open sentinel (None).
  (c) Haiku API error → fail-open sentinel (None).
  (d) schema validation catches a missing field → fail-open sentinel.
  (e) prompt-injection in proposal_text (markdown link / HTML / javascript:)
      is stripped from the rendered card.
  (f) deterministic at temperature 0: same input → same output across two
      runs (we assert the SDK was called with temperature=0).

Pattern: fixture-stubbed Anthropic client (``StubClient``) so the suite
never makes a real API call.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from orchestrator import cortex_phase4_5_director_card as p45


# --- Stub SDK -----------------------------------------------------------------


class _StubMessages:
    def __init__(self, response_text, raise_exc=None, usage=None):
        self._text = response_text
        self._raise = raise_exc
        self._usage = usage or SimpleNamespace(input_tokens=120, output_tokens=80)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        text = self._text() if callable(self._text) else self._text
        content = [SimpleNamespace(type="text", text=text)]
        return SimpleNamespace(
            content=content,
            usage=self._usage,
            model=kwargs.get("model", p45._DEFAULT_MODEL),
            stop_reason="end_turn",
        )


class _StubClient:
    def __init__(self, messages):
        self.messages = messages


def _valid_card_json(matter="Mandarin Oriental Vienna",
                     reco="approve", conf="medium",
                     situation="The operator missed the cost-reporting deadline.",
                     action="Send a follow-up email asking for the missing report by Friday.",
                     rationale="Director needs the data for the bank-call on Monday. Polite follow-up costs nothing.",
                     downside="Operator could push back on tone — low downside.",
                     no_action_consequence="Bank-call goes ahead without the data; missed leverage.",
                     ai_money=0.0034, rw_money=None, sends_money=False) -> str:
    return json.dumps({
        "matter": matter,
        "situation": situation,
        "action": action,
        "rationale": rationale,
        "downside": downside,
        "no_action_consequence": no_action_consequence,
        "cost": {
            "ai_money_eur": ai_money,
            "real_world_money_eur": rw_money,
            "action_sends_money": sends_money,
        },
        "recommendation": reco,
        "confidence": conf,
    })


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Reset module-level cached client.
    p45._reset_client_for_tests()
    yield
    p45._reset_client_for_tests()


def _install_stub_client(monkeypatch, response_text, raise_exc=None):
    messages = _StubMessages(response_text=response_text, raise_exc=raise_exc)
    client = _StubClient(messages)
    monkeypatch.setattr(p45, "_get_client", lambda: client)
    return messages


# --- (a) Happy path -----------------------------------------------------------


def test_a_happy_path_returns_valid_9_field_card(monkeypatch):
    msgs = _install_stub_client(monkeypatch, _valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-a-1",
        proposal_text="**Proposed:** Send follow-up email re cost-reporting deadline.",
        matter_slug="movie",
        cost_telemetry={"cost_dollars": 0.42, "cost_tokens": 5000},
    )
    assert card is not None
    # 9 required top-level fields
    for k in ("matter", "situation", "action", "rationale", "downside",
              "no_action_consequence", "cost", "recommendation", "confidence"):
        assert k in card, f"missing field {k}"
    # cost sub-object shape
    assert isinstance(card["cost"]["ai_money_eur"], (int, float))
    assert isinstance(card["cost"]["action_sends_money"], bool)
    assert card["recommendation"] in p45._RECO_ALLOWED
    assert card["confidence"] in p45._CONF_ALLOWED
    # Meta block stamped for audit
    assert "_meta" in card
    assert card["_meta"]["model"]
    # SDK was called with the configured deterministic settings
    assert msgs.calls[0]["temperature"] == 0.0
    assert msgs.calls[0]["max_tokens"] == p45._MAX_TOKENS


# --- (b) Malformed input → fail-open -----------------------------------------


def test_b_empty_proposal_text_returns_none_without_calling_api(monkeypatch):
    msgs = _install_stub_client(monkeypatch, _valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-b-1",
        proposal_text="",
        matter_slug="movie",
        cost_telemetry=None,
    )
    assert card is None
    # Never called the SDK — short-circuit on empty input.
    assert msgs.calls == []


def test_b_non_json_response_returns_none(monkeypatch):
    msgs = _install_stub_client(monkeypatch, "I cannot do that.")
    card = p45.translate_to_director_card(
        cycle_id="cyc-b-2",
        proposal_text="some technical proposal",
        matter_slug="movie",
    )
    assert card is None
    assert len(msgs.calls) == 1  # SDK was called, but returned non-JSON


# --- (c) Haiku API error → fail-open -----------------------------------------


def test_c_api_error_returns_none(monkeypatch):
    msgs = _install_stub_client(
        monkeypatch,
        response_text=None,
        raise_exc=RuntimeError("simulated 500"),
    )
    card = p45.translate_to_director_card(
        cycle_id="cyc-c-1",
        proposal_text="some technical proposal",
        matter_slug="movie",
    )
    assert card is None


# --- (d) Schema validation catches missing field -----------------------------


def test_d_missing_field_in_response_returns_none(monkeypatch):
    """Model returns valid JSON but drops the 'confidence' field — must fail-open."""
    incomplete = json.loads(_valid_card_json())
    del incomplete["confidence"]
    msgs = _install_stub_client(monkeypatch, json.dumps(incomplete))
    card = p45.translate_to_director_card(
        cycle_id="cyc-d-1",
        proposal_text="some technical proposal",
        matter_slug="movie",
    )
    assert card is None


def test_d_schema_validator_direct():
    """Direct validator unit check — covers the error-string surface."""
    err = p45._validate_card_schema({})
    assert err and "missing required field" in err

    bad_reco = json.loads(_valid_card_json(reco="defenestrate"))
    err = p45._validate_card_schema(bad_reco)
    assert err and "recommendation" in err

    bad_conf = json.loads(_valid_card_json(conf="superb"))
    err = p45._validate_card_schema(bad_conf)
    assert err and "confidence" in err

    good = json.loads(_valid_card_json())
    assert p45._validate_card_schema(good) is None


# --- (e) Prompt injection sanitization ---------------------------------------


def test_e_prompt_injection_in_card_fields_is_stripped(monkeypatch):
    """The model echoes attacker content into a field; sanitization MUST
    strip HTML tags, markdown links, and javascript: schemes before the
    card returns to the caller."""
    poisoned = json.loads(_valid_card_json())
    poisoned["situation"] = (
        "Click [here](javascript:alert(1)) for details. "
        "<script>alert('xss')</script> Some plain content."
    )
    poisoned["action"] = "Send email <b>now</b> via [link](https://evil.example)"
    poisoned["downside"] = "javascript:steal()"
    msgs = _install_stub_client(monkeypatch, json.dumps(poisoned))
    card = p45.translate_to_director_card(
        cycle_id="cyc-e-1",
        proposal_text="t",
        matter_slug="movie",
    )
    assert card is not None
    # No HTML tags survive
    assert "<script" not in card["situation"]
    assert "<b>" not in card["action"]
    assert "</script>" not in card["situation"]
    # Markdown link target stripped, label kept
    assert "javascript:" not in card["situation"]
    assert "javascript:" not in card["action"]
    assert "javascript:" not in card["downside"]
    # Visible label preserved
    assert "here" in card["situation"]
    assert "link" in card["action"]


def test_e_sanitize_string_unit():
    assert p45._sanitize_string("<b>foo</b> bar") == "foo bar"
    # Simple markdown link (no nested parens): label kept, target dropped.
    assert p45._sanitize_string("see [docs](https://evil.example)") == "see docs"
    assert p45._sanitize_string("javascript:alert(1)") == "alert(1)"
    assert p45._sanitize_string("Plain text.") == "Plain text."
    assert p45._sanitize_string(None) == ""
    assert p45._sanitize_string(42) == ""


# --- (f) Deterministic at temperature 0 --------------------------------------


def test_f_deterministic_at_temperature_zero(monkeypatch):
    """Same input across two runs should produce same output AND the
    SDK is always called with temperature=0.0."""
    fixed_json = _valid_card_json()
    msgs = _install_stub_client(monkeypatch, fixed_json)

    a = p45.translate_to_director_card(
        cycle_id="cyc-f-1",
        proposal_text="identical proposal text",
        matter_slug="movie",
    )
    b = p45.translate_to_director_card(
        cycle_id="cyc-f-1",
        proposal_text="identical proposal text",
        matter_slug="movie",
    )
    # Strip the audit meta block (which carries per-call cost — could differ
    # if usage numbers vary, though in this stub they don't). The card itself
    # should be identical.
    a_no_meta = {k: v for k, v in (a or {}).items() if k != "_meta"}
    b_no_meta = {k: v for k, v in (b or {}).items() if k != "_meta"}
    assert a_no_meta == b_no_meta
    assert len(msgs.calls) == 2
    for call in msgs.calls:
        assert call["temperature"] == 0.0


# --- Persistence (bonus coverage) --------------------------------------------


def test_persist_director_card_writes_correct_artifact(monkeypatch):
    """Captured-SQL check: persist_director_card writes the expected
    INSERT against cortex_phase_outputs."""

    class _Cur:
        def __init__(self):
            self.queries = []
        def execute(self, q, params=None):
            self.queries.append((q, params))
        def close(self):
            pass

    class _Conn:
        def __init__(self):
            self.cur = _Cur()
            self.committed = False
        def cursor(self):
            return self.cur
        def commit(self):
            self.committed = True
        def rollback(self):
            pass

    class _Store:
        def __init__(self):
            self.conns = []
        def _get_conn(self):
            c = _Conn()
            self.conns.append(c)
            return c
        def _put_conn(self, c):
            pass

    store = _Store()
    monkeypatch.setattr(p45, "_get_store", lambda: store)
    card = json.loads(_valid_card_json())
    ok = p45.persist_director_card("cyc-persist-1", card)
    assert ok is True
    assert len(store.conns) == 1
    q, params = store.conns[0].cur.queries[0]
    assert "INSERT INTO cortex_phase_outputs" in q
    assert "director_card" in q
    assert params[0] == "cyc-persist-1"
    # Payload is JSON-stringified
    payload = json.loads(params[1])
    assert payload["matter"] == card["matter"]
    assert store.conns[0].committed
