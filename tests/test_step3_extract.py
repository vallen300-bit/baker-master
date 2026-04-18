"""Tests for kbl.steps.step3_extract — Step 3 Gemma extraction evaluator."""
from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import ExtractParseError, OllamaUnavailableError
from kbl.steps import step3_extract
from kbl.steps.step3_extract import (
    ExtractedEntities,
    build_prompt,
    call_ollama,
    extract,
    parse_gemma_response,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    step3_extract._reset_template_cache()
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    yield
    step3_extract._reset_template_cache()


# ---------------------------- build_prompt ----------------------------


def test_build_prompt_contains_signal_block() -> None:
    out = build_prompt("Confirm meeting tomorrow.", "email", "movie", [])
    assert 'Signal: "Confirm meeting tomorrow."' in out


def test_build_prompt_escapes_double_quotes() -> None:
    out = build_prompt('He said "hi"', "email", None, None)
    # Outer wrapper survives; inner quotes downgraded to apostrophes so
    # the Signal: "..." wrapper stays well-formed.
    assert "Signal: \"He said 'hi'\"" in out


def test_build_prompt_truncates_long_signal() -> None:
    long = "x" * 5000
    out = build_prompt(long, "scan", None, None)
    assert "x" * 3000 in out
    assert "x" * 3001 not in out


def test_build_prompt_context_source() -> None:
    out = build_prompt("sig", "whatsapp", None, None)
    assert "source:         whatsapp" in out


def test_build_prompt_context_matter_filled() -> None:
    out = build_prompt("sig", "email", "hagenauer-rg7", None)
    assert "primary_matter: hagenauer-rg7" in out


def test_build_prompt_context_matter_null_renders_fallback() -> None:
    out = build_prompt("sig", "email", None, None)
    assert "primary_matter: none (null matter)" in out


def test_build_prompt_thread_context_fallback_when_empty() -> None:
    out = build_prompt("sig", "email", "movie", [])
    assert "thread_context: new thread" in out
    out_none = build_prompt("sig", "email", "movie", None)
    assert "thread_context: new thread" in out_none


def test_build_prompt_thread_context_joins_up_to_three() -> None:
    paths = [
        "wiki/movie/a.md",
        "wiki/movie/b.md",
        "wiki/movie/c.md",
        "wiki/movie/d.md",
    ]
    out = build_prompt("sig", "email", "movie", paths)
    assert "thread_context: wiki/movie/a.md; wiki/movie/b.md; wiki/movie/c.md" in out
    # 4th path is dropped — stays off the line.
    assert "wiki/movie/d.md" not in out


def test_build_prompt_no_placeholders_leak() -> None:
    out = build_prompt("s", "email", "movie", ["wiki/movie/a.md"])
    for placeholder in ("{signal}", "{source}", "{matter_hint}", "{thread_hint}"):
        assert placeholder not in out


def test_build_prompt_template_cached_across_calls() -> None:
    """Inv 10: template text is code-frozen — one read per process."""
    with patch.object(
        step3_extract.Path,
        "read_text",
        return_value=step3_extract._TEMPLATE_PATH.read_text(encoding="utf-8"),
        autospec=False,
    ):
        step3_extract._reset_template_cache()
        step3_extract._load_template()
        step3_extract._load_template()
        step3_extract._load_template()
        # Cache populated on first call; further calls served from memory.
        # Assert by inspecting the private cache directly.
        assert step3_extract._template_cache is not None


# ---------------------------- parse_gemma_response — happy path ----------------------------


def _response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "people": [],
        "orgs": [],
        "money": [],
        "dates": [],
        "references": [],
        "action_items": [],
    }
    body.update(overrides)
    return json.dumps(body)


def test_parse_happy_path_all_six_keys_populated() -> None:
    raw = _response(
        people=[{"name": "Thomas Leitner", "company": "Brisengroup"}],
        orgs=[{"name": "Wertheimer SFO", "type": "family_office"}],
        money=[{"amount": 17000000, "currency": "CHF", "context": "possible deal"}],
        dates=[{"date": "2026-02-04", "event": "letter reference"}],
        references=[{"type": "letter", "id": "EH-AT.FID2087"}],
        action_items=[
            {"actor": "Thomas", "action": "send letter", "deadline": "Friday"}
        ],
    )
    r = parse_gemma_response(raw)
    assert len(r.people) == 1
    # Director-linked person by company field passes the filter (we filter
    # the Director himself, not everyone at Brisengroup).
    assert r.people[0]["name"] == "Thomas Leitner"
    assert r.people[0]["company"] == "Brisengroup"
    assert r.orgs[0]["type"] == "family_office"
    assert r.money[0]["amount"] == 17000000
    assert r.money[0]["currency"] == "CHF"
    assert r.dates[0]["date"] == "2026-02-04"
    assert r.references[0]["id"] == "EH-AT.FID2087"
    assert r.action_items[0]["deadline"] == "Friday"


def test_parse_empty_arrays_valid() -> None:
    r = parse_gemma_response(_response())
    assert r.people == ()
    assert r.orgs == ()
    assert r.money == ()
    assert r.dates == ()
    assert r.references == ()
    assert r.action_items == ()


# ---------------------------- parse_gemma_response — partial JSON ----------------------------


def test_parse_partial_json_missing_keys_default_to_empty() -> None:
    """§7 row 2: missing top-level keys fill with []. Four-of-six present
    is a legal partial response."""
    partial = json.dumps(
        {
            "people": [{"name": "Alice"}],
            "orgs": [{"name": "Globex"}],
            "money": [{"amount": 50000, "currency": "EUR"}],
            "dates": [{"date": "2026-05-01"}],
            # references + action_items missing entirely
        }
    )
    r = parse_gemma_response(partial)
    assert len(r.people) == 1
    assert len(r.orgs) == 1
    assert len(r.money) == 1
    assert len(r.dates) == 1
    assert r.references == ()
    assert r.action_items == ()


def test_parse_top_level_non_array_replaced_with_empty() -> None:
    """§7 row 3: top-level value that isn't a list → []."""
    bad = json.dumps(
        {
            "people": "not a list",
            "orgs": {"also": "not a list"},
            "money": [],
            "dates": [],
            "references": [],
            "action_items": [],
        }
    )
    r = parse_gemma_response(bad)
    assert r.people == ()
    assert r.orgs == ()


# ---------------------------- parse_gemma_response — unparseable ----------------------------


def test_parse_empty_string_raises() -> None:
    with pytest.raises(ExtractParseError, match="empty model response"):
        parse_gemma_response("")


def test_parse_malformed_json_raises() -> None:
    with pytest.raises(ExtractParseError, match="invalid JSON"):
        parse_gemma_response("{not valid")


def test_parse_non_object_root_raises() -> None:
    with pytest.raises(ExtractParseError, match="top-level must be object"):
        parse_gemma_response(json.dumps(["a", "b"]))


# ---------------------------- parse_gemma_response — sub-field sanitization ----------------------------


def test_parse_drops_money_with_string_amount() -> None:
    """§7 row 5: `amount: "17 million"` → drop the entry."""
    raw = _response(money=[{"amount": "17 million", "currency": "EUR"}])
    r = parse_gemma_response(raw)
    assert r.money == ()


def test_parse_drops_money_with_unknown_currency() -> None:
    raw = _response(money=[{"amount": 1000, "currency": "BTC"}])
    r = parse_gemma_response(raw)
    assert r.money == ()


def test_parse_drops_money_where_amount_is_bool() -> None:
    raw = _response(money=[{"amount": True, "currency": "EUR"}])
    r = parse_gemma_response(raw)
    assert r.money == ()


def test_parse_drops_non_iso_date() -> None:
    """§7 row 6: date not ISO 8601 → drop the entry."""
    raw = _response(
        dates=[
            {"date": "end of Q2", "event": "deadline"},
            {"date": "2026-05-15", "event": "hearing"},
        ]
    )
    r = parse_gemma_response(raw)
    assert len(r.dates) == 1
    assert r.dates[0]["date"] == "2026-05-15"


def test_parse_drops_reference_without_id() -> None:
    raw = _response(
        references=[
            {"type": "contract"},  # no id
            {"type": "invoice", "id": "2026/42"},
        ]
    )
    r = parse_gemma_response(raw)
    assert len(r.references) == 1
    assert r.references[0]["id"] == "2026/42"


def test_parse_drops_person_with_empty_name() -> None:
    raw = _response(people=[{"name": ""}, {"name": "   "}, {"name": "Alice"}])
    r = parse_gemma_response(raw)
    assert len(r.people) == 1
    assert r.people[0]["name"] == "Alice"


def test_parse_omits_null_sub_fields_from_output() -> None:
    """Rule 1 ("omit, don't null"): if Gemma emits role=null or role='',
    the parser drops that sub-key instead of propagating the null."""
    raw = _response(
        people=[{"name": "Alice", "role": None, "company": ""}]
    )
    r = parse_gemma_response(raw)
    entry = r.people[0]
    assert entry == {"name": "Alice"}
    assert "role" not in entry
    assert "company" not in entry


def test_parse_strips_director_self_reference_from_people() -> None:
    """§7 row 7: Dimitry appears in people despite prompt rule → strip."""
    raw = _response(
        people=[
            {"name": "Dimitry Vallen"},
            {"name": "Alice"},
            {"name": "dimitry vallen", "role": "signatory"},
        ]
    )
    r = parse_gemma_response(raw)
    assert len(r.people) == 1
    assert r.people[0]["name"] == "Alice"


def test_parse_strips_director_company_from_orgs() -> None:
    """Brisen / Brisengroup should never appear as a standalone org."""
    raw = _response(
        orgs=[
            {"name": "Brisen", "type": "other"},
            {"name": "Brisengroup", "type": "other"},
            {"name": "Engin+Hanousek", "type": "law_firm"},
        ]
    )
    r = parse_gemma_response(raw)
    assert len(r.orgs) == 1
    assert r.orgs[0]["name"] == "Engin+Hanousek"


def test_parse_drops_org_with_unknown_type_keeps_name() -> None:
    """Unknown org `type` is stripped (sub-field drop) but the entry
    still lands because `name` is the only required sub-field."""
    raw = _response(orgs=[{"name": "Globex", "type": "space_elevator"}])
    r = parse_gemma_response(raw)
    assert len(r.orgs) == 1
    assert r.orgs[0]["name"] == "Globex"
    assert "type" not in r.orgs[0]


def test_parse_drops_action_item_missing_actor_or_action() -> None:
    raw = _response(
        action_items=[
            {"action": "send letter"},  # no actor
            {"actor": "Thomas"},  # no action
            {"actor": "Thomas", "action": "send letter"},
        ]
    )
    r = parse_gemma_response(raw)
    assert len(r.action_items) == 1
    assert r.action_items[0] == {"actor": "Thomas", "action": "send letter"}


def test_parse_drops_non_dict_entries() -> None:
    raw = _response(people=["not a dict", 42, {"name": "Alice"}, None])
    r = parse_gemma_response(raw)
    assert len(r.people) == 1


# ---------------------------- ExtractedEntities ----------------------------


def test_extracted_entities_is_frozen() -> None:
    e = ExtractedEntities()
    with pytest.raises(Exception):
        e.people = ({"name": "x"},)  # type: ignore[misc]


def test_extracted_entities_empty_factory() -> None:
    e = ExtractedEntities.empty()
    assert e.to_dict() == {
        "people": [],
        "orgs": [],
        "money": [],
        "dates": [],
        "references": [],
        "action_items": [],
    }


def test_extracted_entities_to_dict_shape() -> None:
    e = ExtractedEntities(
        people=({"name": "Alice"},),
        orgs=({"name": "Globex", "type": "other"},),
    )
    d = e.to_dict()
    # All six keys always present in output (Inv: shape is stable).
    assert set(d.keys()) == {
        "people",
        "orgs",
        "money",
        "dates",
        "references",
        "action_items",
    }
    assert d["people"] == [{"name": "Alice"}]


# ---------------------------- call_ollama ----------------------------


def _fake_response(payload: dict[str, Any]):
    ctx = MagicMock()
    ctx.read.return_value = json.dumps(payload).encode("utf-8")
    ctx.__enter__ = lambda self: ctx
    ctx.__exit__ = lambda self, *a: False
    return ctx


def test_call_ollama_posts_to_generate_endpoint_with_correct_sampling() -> None:
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response({"response": "{}"})
        call_ollama("prompt", host="http://127.0.0.1:11434")
    req = m_open.call_args.args[0]
    assert req.full_url == "http://127.0.0.1:11434/api/generate"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gemma2:8b"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["options"]["temperature"] == 0.0
    assert body["options"]["seed"] == 42
    assert body["options"]["num_predict"] == 1024  # Step 3 larger than Step 1


def test_call_ollama_uses_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.brisen-infra.com")
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response({"response": "{}"})
        call_ollama("prompt")
    req = m_open.call_args.args[0]
    assert req.full_url == "http://ollama.brisen-infra.com/api/generate"


def test_call_ollama_raises_on_http_error() -> None:
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("http://x", 503, "down", {}, None),
    ):
        with pytest.raises(OllamaUnavailableError, match="HTTP 503"):
            call_ollama("prompt")


def test_call_ollama_raises_on_url_error() -> None:
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("refused")
    ):
        with pytest.raises(OllamaUnavailableError, match="unreachable"):
            call_ollama("prompt")


def test_call_ollama_raises_on_timeout() -> None:
    with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
        with pytest.raises(OllamaUnavailableError, match="unreachable"):
            call_ollama("prompt", timeout=1)


def test_call_ollama_raises_on_bad_envelope() -> None:
    with patch("urllib.request.urlopen") as m_open:
        bad = MagicMock()
        bad.read.return_value = b"not json"
        bad.__enter__ = lambda self: bad
        bad.__exit__ = lambda self, *a: False
        m_open.return_value = bad
        with pytest.raises(OllamaUnavailableError, match="non-JSON envelope"):
            call_ollama("prompt")


# ---------------------------- extract() end-to-end ----------------------------


def _extract_conn(
    raw_content: str = "Please confirm the CHF 17M deal.",
    source: str = "email",
    primary_matter: str | None = "movie",
    resolved_thread_paths: list[str] | None = None,
) -> MagicMock:
    """Build a connection whose cursor:
      - serves SELECT from signal_queue with the tuple above
      - accepts all subsequent UPDATE / INSERT calls as no-ops
      - records every (sql, params) for assertion
    """
    conn = MagicMock()
    call_sequence: list[tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            call_sequence.append((sql, params))
            sql_lower = sql.lower()
            if "from signal_queue" in sql_lower and "select" in sql_lower:
                cur.fetchone.return_value = (
                    raw_content,
                    source,
                    primary_matter,
                    resolved_thread_paths if resolved_thread_paths is not None else [],
                )
            else:
                cur.fetchone.return_value = None
                cur.fetchall.return_value = []

        cur.execute.side_effect = _execute
        return cur

    def _cursor() -> MagicMock:
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = call_sequence
    return conn


def _valid_gemma_envelope(**overrides: Any) -> dict[str, Any]:
    return {
        "response": _response(**overrides),
        "prompt_eval_count": 1600,
        "eval_count": 200,
    }


def test_extract_writes_result_and_advances_state() -> None:
    conn = _extract_conn()
    envelope = _valid_gemma_envelope(
        people=[{"name": "Alice"}],
        money=[{"amount": 17000000, "currency": "CHF", "context": "deal"}],
    )
    with patch.object(step3_extract, "call_ollama", return_value=envelope):
        result = extract(signal_id=42, conn=conn)

    assert len(result.people) == 1
    assert result.money[0]["amount"] == 17000000

    sqls = [s.lower() for s, _ in conn._calls]
    # Running status written BEFORE the result UPDATE.
    assert any("status = %s" in s and "update signal_queue" in s for s in sqls)
    # Final UPDATE with extracted_entities.
    update_rows = [
        c for c in conn._calls
        if "update signal_queue" in c[0].lower()
        and "extracted_entities" in c[0].lower()
    ]
    assert update_rows
    _, params = update_rows[0]
    entities_json, next_state, sid = params
    assert sid == 42
    assert next_state == "awaiting_classify"
    payload = json.loads(entities_json)
    assert set(payload.keys()) == {
        "people",
        "orgs",
        "money",
        "dates",
        "references",
        "action_items",
    }
    assert payload["people"][0]["name"] == "Alice"

    # Cost ledger row written with success=True and correct step label.
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert cost_rows
    _, cost_params = cost_rows[0]
    # Params: (signal_id, model, input_tokens, output_tokens, latency_ms, success)
    assert cost_params[0] == 42
    assert cost_params[1] == "gemma2:8b"
    assert cost_params[2] == 1600
    assert cost_params[3] == 200
    assert cost_params[5] is True
    # step label hard-coded in the INSERT literal — verify the SQL itself.
    assert "'extract'" in cost_rows[0][0]


def test_extract_writes_all_six_keys_even_when_empty() -> None:
    """§4.4 invariant: extracted_entities is always an object with six
    array-valued keys. Empty Gemma response → all six arrays present."""
    conn = _extract_conn()
    envelope = _valid_gemma_envelope()  # every array empty
    with patch.object(step3_extract, "call_ollama", return_value=envelope):
        extract(signal_id=1, conn=conn)
    update_rows = [
        c for c in conn._calls
        if "update signal_queue" in c[0].lower()
        and "extracted_entities" in c[0].lower()
    ]
    _, params = update_rows[0]
    payload = json.loads(params[0])
    assert payload == {
        "people": [],
        "orgs": [],
        "money": [],
        "dates": [],
        "references": [],
        "action_items": [],
    }


def test_extract_signal_not_found_raises() -> None:
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx

    with pytest.raises(LookupError, match="row not found"):
        extract(signal_id=999, conn=conn)


def test_extract_retries_on_parse_error_then_succeeds() -> None:
    """R3 retry path: first call unparseable, second call valid → final
    result written with success=True."""
    conn = _extract_conn()
    unparseable = {"response": "not json at all", "prompt_eval_count": 1500, "eval_count": 30}
    valid = _valid_gemma_envelope(people=[{"name": "Bob"}])

    with patch.object(
        step3_extract, "call_ollama", side_effect=[unparseable, valid]
    ) as m_call:
        result = extract(signal_id=7, conn=conn)

    assert m_call.call_count == 2
    assert len(result.people) == 1
    assert result.people[0]["name"] == "Bob"

    # Single result UPDATE (second call succeeded).
    update_rows = [
        c for c in conn._calls
        if "update signal_queue" in c[0].lower()
        and "extracted_entities" in c[0].lower()
    ]
    assert len(update_rows) == 1
    # Cost ledger row written with success=True (final outcome).
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert len(cost_rows) == 1
    assert cost_rows[0][1][5] is True


def test_extract_retries_exhausted_writes_stub_and_continues() -> None:
    """§7 row 1: second parse failure → write empty stub, advance state,
    cost row success=False. Pipeline keeps flowing."""
    conn = _extract_conn()
    unparseable = {"response": "garbage", "prompt_eval_count": 1500, "eval_count": 30}

    with patch.object(
        step3_extract, "call_ollama", side_effect=[unparseable, unparseable]
    ) as m_call:
        result = extract(signal_id=11, conn=conn)

    assert m_call.call_count == 2
    # Empty stub returned — all six arrays empty.
    assert result.people == ()
    assert result.money == ()

    # Result UPDATE with the stub + awaiting_classify (NOT extract_failed).
    update_rows = [
        c for c in conn._calls
        if "update signal_queue" in c[0].lower()
        and "extracted_entities" in c[0].lower()
    ]
    assert len(update_rows) == 1
    _, params = update_rows[0]
    assert params[1] == "awaiting_classify"
    payload = json.loads(params[0])
    assert payload == {
        "people": [],
        "orgs": [],
        "money": [],
        "dates": [],
        "references": [],
        "action_items": [],
    }
    # Cost row written with success=False.
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert len(cost_rows) == 1
    assert cost_rows[0][1][5] is False


def test_extract_ollama_unreachable_propagates() -> None:
    """Ollama availability is the caller's (pipeline tick) concern — it
    swaps to fallback or defers. Step 3 raises unchanged."""
    conn = _extract_conn()
    with patch.object(
        step3_extract,
        "call_ollama",
        side_effect=OllamaUnavailableError("down"),
    ):
        with pytest.raises(OllamaUnavailableError, match="down"):
            extract(signal_id=1, conn=conn)


def test_extract_handles_resolved_thread_paths_as_jsonb_string() -> None:
    """Defensive: if psycopg2 hands back JSONB as a string (old driver /
    row cached before cast), the helper still parses it."""
    conn = _extract_conn(
        resolved_thread_paths=['["wiki/movie/a.md","wiki/movie/b.md"]'],  # intentionally wrapped as [str]
    )

    # Replace the SELECT row with the stringified form.
    def _make_cursor():
        cur = MagicMock()

        def _execute(sql, params=None):
            conn._calls.append((sql, params))
            if "from signal_queue" in sql.lower() and "select" in sql.lower():
                cur.fetchone.return_value = (
                    "sig",
                    "email",
                    "movie",
                    '["wiki/movie/a.md","wiki/movie/b.md"]',
                )

        cur.execute.side_effect = _execute
        return cur

    def _cursor():
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = []

    envelope = _valid_gemma_envelope()
    captured_prompts: list[str] = []

    def _capture(prompt: str, **_kwargs: Any) -> dict[str, Any]:
        captured_prompts.append(prompt)
        return envelope

    with patch.object(step3_extract, "call_ollama", side_effect=_capture):
        extract(signal_id=1, conn=conn)

    assert any("wiki/movie/a.md" in p for p in captured_prompts)


# ---------------------------- template + module surface ----------------------------


def test_template_file_has_all_four_placeholders() -> None:
    text = step3_extract._load_template()
    assert "{signal}" in text
    assert "{source}" in text
    assert "{matter_hint}" in text
    assert "{thread_hint}" in text


def test_module_public_surface() -> None:
    for name in (
        "build_prompt",
        "parse_gemma_response",
        "call_ollama",
        "extract",
        "ExtractedEntities",
    ):
        assert hasattr(step3_extract, name)
