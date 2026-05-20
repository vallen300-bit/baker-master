"""Tests for orchestrator/cortex_phase4_5_director_card.py.

V1.0 brief: ``briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md`` (criterion 10).
V1.1 brief: ``briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1.md`` — Gemini 2.5 Pro
primary translator with Sonnet 4.6 fallback on ANY Gemini failure.

V1.0 cases (still exercised, now against the Gemini primary path):
  (a) happy path returns a valid 9-field card with Gemini meta.
  (b) malformed proposal_text → fail-open sentinel.
  (c) primary API error → Sonnet fallback (was: Haiku error → None).
  (d) schema validation catches a missing field → fall through to Sonnet.
  (e) prompt injection in proposal_text is stripped from the rendered card.
  (f) deterministic at temperature 0 (asserted on the fallback path; Gemini
      determinism is enforced by ``temperature=0`` not configurable in
      this client wrapper).

V1.1 cases (new):
  - gemini-primary happy path stamps ``_meta.fallback_used = False``.
  - gemini exception → Sonnet fallback fires + ``_meta.fallback_used = True``.
  - gemini invalid JSON → Sonnet fallback fires.
  - gemini schema-invalid response → Sonnet fallback fires.
  - both vendors fail → ``FAIL_OPEN_SENTINEL``; no exception escapes.
  - gemini api-key unset (gemini_generate raises) → Sonnet serves the card.

Pattern: stubbed ``orchestrator.gemini_client.generate`` + stubbed
``anthropic.Anthropic`` client. The suite never makes a real API call.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from orchestrator import cortex_phase4_5_director_card as p45


# --- Stub anthropic SDK -------------------------------------------------------


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
            model=kwargs.get("model", p45._FALLBACK_MODEL),
            stop_reason="end_turn",
        )


class _StubClient:
    def __init__(self, messages):
        self.messages = messages


# --- Stub gemini_client.generate ---------------------------------------------


class _GeminiStub:
    """Replaces ``orchestrator.gemini_client.generate`` per test."""

    def __init__(self, response_text=None, raise_exc=None, usage=None):
        self._text = response_text
        self._raise = raise_exc
        self._usage = usage or SimpleNamespace(input_tokens=150, output_tokens=100)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        text = self._text() if callable(self._text) else self._text
        return SimpleNamespace(text=text or "", usage=self._usage)


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
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    p45._reset_client_for_tests()
    yield
    p45._reset_client_for_tests()


def _install_gemini_stub(monkeypatch, response_text=None, raise_exc=None):
    """Install a Gemini stub at the canonical import site.

    ``translate_to_director_card`` does ``from orchestrator.gemini_client
    import generate as gemini_generate`` inside the function; patching the
    module attribute is enough — the import resolves to the patched name.
    """
    import orchestrator.gemini_client as gc
    stub = _GeminiStub(response_text=response_text, raise_exc=raise_exc)
    monkeypatch.setattr(gc, "generate", stub)
    return stub


def _install_anthropic_stub(monkeypatch, response_text=None, raise_exc=None):
    msgs = _StubMessages(response_text=response_text, raise_exc=raise_exc)
    client = _StubClient(msgs)
    monkeypatch.setattr(p45, "_get_anthropic_fallback_client", lambda: client)
    return msgs


# --- (a) Happy path — Gemini primary -----------------------------------------


def test_a_happy_path_returns_valid_9_field_card(monkeypatch):
    gemini = _install_gemini_stub(monkeypatch, _valid_card_json())
    # Anthropic stub set to raise so we can prove fallback did NOT fire.
    anthropic = _install_anthropic_stub(monkeypatch, raise_exc=AssertionError("fallback fired"))
    card = p45.translate_to_director_card(
        cycle_id="cyc-a-1",
        proposal_text="**Proposed:** Send follow-up email re cost-reporting deadline.",
        matter_slug="movie",
        cost_telemetry={"cost_dollars": 0.42, "cost_tokens": 5000},
    )
    assert card is not None
    for k in ("matter", "situation", "action", "rationale", "downside",
              "no_action_consequence", "cost", "recommendation", "confidence"):
        assert k in card, f"missing field {k}"
    assert isinstance(card["cost"]["ai_money_eur"], (int, float))
    assert isinstance(card["cost"]["action_sends_money"], bool)
    assert card["recommendation"] in p45._RECO_ALLOWED
    assert card["confidence"] in p45._CONF_ALLOWED
    assert card["_meta"]["model"] == p45._PRIMARY_MODEL
    assert card["_meta"]["fallback_used"] is False
    assert card["_meta"]["card_gen_cost_eur"] > 0
    assert len(gemini.calls) == 1
    assert gemini.calls[0]["model"] == p45._PRIMARY_MODEL
    # V1.1 hot-fix: Gemini path uses the wider token budget; Sonnet stays at 600.
    assert gemini.calls[0]["max_tokens"] == p45._MAX_TOKENS_GEMINI
    # V1.1 hot-fix: Gemini call must request strict JSON output mime.
    assert gemini.calls[0].get("response_format") == "json"
    assert anthropic.calls == []


# --- (b) Malformed input → fail-open -----------------------------------------


def test_b_empty_proposal_text_returns_none_without_calling_api(monkeypatch):
    gemini = _install_gemini_stub(monkeypatch, _valid_card_json())
    _install_anthropic_stub(monkeypatch, raise_exc=AssertionError("should not fire"))
    card = p45.translate_to_director_card(
        cycle_id="cyc-b-1",
        proposal_text="",
        matter_slug="movie",
        cost_telemetry=None,
    )
    assert card is None
    assert gemini.calls == []


# --- (c) Primary API error → Sonnet fallback fires ---------------------------


def test_c_primary_api_error_triggers_sonnet_fallback(monkeypatch):
    """V1.1 contract: gemini exception → Sonnet fallback fires and wins."""
    gemini = _install_gemini_stub(monkeypatch, raise_exc=RuntimeError("simulated 500"))
    anthropic = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-c-1",
        proposal_text="some technical proposal",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["fallback_used"] is True
    assert "sonnet" in card["_meta"]["model"].lower()
    assert len(gemini.calls) == 1
    assert len(anthropic.calls) == 1


# --- (d) Schema validation -----------------------------------------------------


def test_d_missing_field_in_primary_falls_through_to_sonnet(monkeypatch):
    """Gemini returns schema-invalid JSON → fall through to Sonnet."""
    incomplete = json.loads(_valid_card_json())
    del incomplete["confidence"]
    gemini = _install_gemini_stub(monkeypatch, json.dumps(incomplete))
    anthropic = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-d-1",
        proposal_text="some technical proposal",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["fallback_used"] is True
    assert len(gemini.calls) == 1
    assert len(anthropic.calls) == 1


def test_d_schema_validator_direct():
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
    poisoned = json.loads(_valid_card_json())
    poisoned["situation"] = (
        "Click [here](javascript:alert(1)) for details. "
        "<script>alert('xss')</script> Some plain content."
    )
    poisoned["action"] = "Send email <b>now</b> via [link](https://evil.example)"
    poisoned["downside"] = "javascript:steal()"
    _install_gemini_stub(monkeypatch, json.dumps(poisoned))
    _install_anthropic_stub(monkeypatch, raise_exc=AssertionError("should not fire"))
    card = p45.translate_to_director_card(
        cycle_id="cyc-e-1",
        proposal_text="t",
        matter_slug="movie",
    )
    assert card is not None
    assert "<script" not in card["situation"]
    assert "<b>" not in card["action"]
    assert "</script>" not in card["situation"]
    assert "javascript:" not in card["situation"]
    assert "javascript:" not in card["action"]
    assert "javascript:" not in card["downside"]
    assert "here" in card["situation"]
    assert "link" in card["action"]


def test_e_sanitize_string_unit():
    assert p45._sanitize_string("<b>foo</b> bar") == "foo bar"
    assert p45._sanitize_string("see [docs](https://evil.example)") == "see docs"
    assert p45._sanitize_string("javascript:alert(1)") == "alert(1)"
    assert p45._sanitize_string("Plain text.") == "Plain text."
    assert p45._sanitize_string(None) == ""
    assert p45._sanitize_string(42) == ""


# --- (f) Deterministic on fallback path (Sonnet temperature=0) ---------------


def test_f_deterministic_at_temperature_zero_on_fallback(monkeypatch):
    """Sonnet fallback is always called with temperature=0.0 — guard against
    silent regression that would introduce variance into Director-facing
    translations. Gemini primary determinism is set via the client wrapper
    (this layer does not see the Gemini call's temperature param)."""
    _install_gemini_stub(monkeypatch, raise_exc=RuntimeError("force fallback"))
    msgs = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())

    a = p45.translate_to_director_card(
        cycle_id="cyc-f-1",
        proposal_text="identical proposal text",
        matter_slug="movie",
    )
    b = p45.translate_to_director_card(
        cycle_id="cyc-f-2",
        proposal_text="identical proposal text",
        matter_slug="movie",
    )
    a_no_meta = {k: v for k, v in (a or {}).items() if k != "_meta"}
    b_no_meta = {k: v for k, v in (b or {}).items() if k != "_meta"}
    assert a_no_meta == b_no_meta
    assert len(msgs.calls) == 2
    for call in msgs.calls:
        assert call["temperature"] == 0.0
        assert call["max_tokens"] == p45._MAX_TOKENS


# --- V1.1 contract: Gemini primary success path ------------------------------


def test_gemini_primary_success_path(monkeypatch):
    gemini = _install_gemini_stub(monkeypatch, _valid_card_json())
    anthropic = _install_anthropic_stub(monkeypatch, raise_exc=AssertionError("should not fire"))
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-primary",
        proposal_text="primary path test",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["model"] == "gemini-2.5-pro"
    assert card["_meta"]["fallback_used"] is False
    assert card["_meta"]["card_gen_cost_eur"] > 0
    assert anthropic.calls == []


# --- V1.1 contract: Sonnet fallback on Gemini exception ----------------------


def test_sonnet_fallback_on_gemini_exception(monkeypatch):
    _install_gemini_stub(monkeypatch, raise_exc=RuntimeError("gemini went down"))
    msgs = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-exc",
        proposal_text="exception path test",
        matter_slug="movie",
    )
    assert card is not None
    assert "sonnet" in card["_meta"]["model"].lower()
    assert card["_meta"]["fallback_used"] is True
    assert len(msgs.calls) == 1


# --- V1.1 contract: Sonnet fallback on Gemini invalid JSON -------------------


def test_sonnet_fallback_on_gemini_invalid_json(monkeypatch):
    _install_gemini_stub(monkeypatch, response_text="this is not JSON at all")
    msgs = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-bad-json",
        proposal_text="bad json test",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["fallback_used"] is True
    assert len(msgs.calls) == 1


# --- V1.1 contract: Sonnet fallback on Gemini schema-invalid -----------------


def test_sonnet_fallback_on_gemini_schema_invalid(monkeypatch):
    incomplete = json.loads(_valid_card_json())
    del incomplete["cost"]["action_sends_money"]
    _install_gemini_stub(monkeypatch, json.dumps(incomplete))
    msgs = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-schema",
        proposal_text="schema test",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["fallback_used"] is True
    assert len(msgs.calls) == 1


# --- V1.1 contract: Double failure → FAIL_OPEN_SENTINEL ----------------------


def test_double_failure_returns_sentinel(monkeypatch):
    _install_gemini_stub(monkeypatch, raise_exc=RuntimeError("gemini fail"))
    _install_anthropic_stub(monkeypatch, raise_exc=RuntimeError("sonnet fail"))
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-double",
        proposal_text="double fail test",
        matter_slug="movie",
    )
    assert card is p45.FAIL_OPEN_SENTINEL
    assert card is None


# --- V1.1 contract: Gemini no api key → fallback fires -----------------------


def test_gemini_no_api_key_falls_back(monkeypatch):
    """If gemini_generate raises because GEMINI_API_KEY is unset, Sonnet
    fallback should still serve the card. Models the exact runtime case
    where a deploy lands without the Gemini key set."""
    _install_gemini_stub(
        monkeypatch,
        raise_exc=ValueError("GEMINI_API_KEY not set"),
    )
    msgs = _install_anthropic_stub(monkeypatch, response_text=_valid_card_json())
    card = p45.translate_to_director_card(
        cycle_id="cyc-v11-no-key",
        proposal_text="missing-key test",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["fallback_used"] is True
    assert len(msgs.calls) == 1


# --- V1.1 hot-fix: trailing-prose tolerance ----------------------------------


def test_gemini_response_with_trailing_prose_parses(monkeypatch):
    """Gemini occasionally emits the JSON object followed by a sentence
    of trailing commentary (even when ``response_mime_type=application/json``
    is requested). The brace-balanced parser must extract the object slice
    and the Gemini-primary path must serve the card without firing the
    Sonnet fallback."""
    card_json = _valid_card_json()
    messy = card_json + "\n\nHere is the JSON above for your review."
    gemini = _install_gemini_stub(monkeypatch, messy)
    anthropic = _install_anthropic_stub(
        monkeypatch, raise_exc=AssertionError("fallback fired")
    )
    card = p45.translate_to_director_card(
        cycle_id="cyc-hotfix-trailing",
        proposal_text="hot-fix smoke",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["model"] == p45._PRIMARY_MODEL
    assert card["_meta"]["fallback_used"] is False
    assert len(gemini.calls) == 1
    assert anthropic.calls == []


def test_gemini_response_with_fences_and_trailing_prose_parses(monkeypatch):
    """Fenced JSON followed by trailing prose — the existing fence stripper
    handles the leading ``` and the new brace-balanced walk handles the
    trailing sentence after the closing ```."""
    card_json = _valid_card_json()
    messy = "```json\n" + card_json + "\n```\n\nLet me know if you need anything."
    gemini = _install_gemini_stub(monkeypatch, messy)
    anthropic = _install_anthropic_stub(
        monkeypatch, raise_exc=AssertionError("fallback fired")
    )
    card = p45.translate_to_director_card(
        cycle_id="cyc-hotfix-fences",
        proposal_text="hot-fix smoke",
        matter_slug="movie",
    )
    assert card is not None
    assert card["_meta"]["model"] == p45._PRIMARY_MODEL
    assert card["_meta"]["fallback_used"] is False
    assert len(gemini.calls) == 1
    assert anthropic.calls == []


def test_parse_json_response_strips_trailing_prose_unit():
    """Direct unit test on the parser:
    - clean JSON parses (regression guard);
    - JSON + trailing prose parses to just the object;
    - JSON with leading + trailing prose parses;
    - JSON with a ``}`` inside a string value is NOT cut at that brace;
    - garbage with no JSON returns None;
    - empty / None input returns None.
    """
    clean = '{"a": 1, "b": "two"}'
    assert p45._parse_json_response(clean) == {"a": 1, "b": "two"}

    trailing = '{"a": 1, "b": "two"}\n\nHere is your JSON.'
    assert p45._parse_json_response(trailing) == {"a": 1, "b": "two"}

    both = 'Sure — here is the data:\n{"a": 1, "b": "two"}\nThanks!'
    assert p45._parse_json_response(both) == {"a": 1, "b": "two"}

    # Closing brace INSIDE a string value must not terminate the walk.
    embedded = '{"key": "value with } brace inside", "n": 7}'
    assert p45._parse_json_response(embedded) == {
        "key": "value with } brace inside",
        "n": 7,
    }

    # Escaped quote inside a string must not toggle the in_str state out.
    escaped = '{"q": "she said \\"hi\\"", "n": 1}'
    assert p45._parse_json_response(escaped) == {
        "q": 'she said "hi"',
        "n": 1,
    }

    assert p45._parse_json_response("") is None
    assert p45._parse_json_response(None) is None
    assert p45._parse_json_response("no json at all here") is None
    # Unterminated object → None (no closing brace).
    assert p45._parse_json_response('{"a": 1') is None


# --- Persistence (bonus coverage) --------------------------------------------


def test_persist_director_card_writes_correct_artifact(monkeypatch):
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
    payload = json.loads(params[1])
    assert payload["matter"] == card["matter"]
    assert store.conns[0].committed
