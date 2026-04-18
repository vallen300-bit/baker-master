"""Tests for kbl.steps.step1_triage — Step 1 Gemma triage evaluator."""
from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kbl import slug_registry
from kbl.exceptions import OllamaUnavailableError, TriageParseError
from kbl.steps import step1_triage
from kbl.steps.step1_triage import (
    TriageResult,
    build_prompt,
    call_ollama,
    normalize_matter,
    parse_gemma_response,
    triage,
)

FIXTURES = Path(__file__).parent / "fixtures"
VAULT_LAYER0 = FIXTURES / "vault_layer0"


# ------------------------------ shared fixtures ------------------------------


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    slug_registry.reload()
    step1_triage._reset_template_cache()
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT_LAYER0))
    monkeypatch.delenv("KBL_PIPELINE_TRIAGE_THRESHOLD", raising=False)
    yield
    slug_registry.reload()
    step1_triage._reset_template_cache()


def _mock_conn_with_ledger(rows: list[tuple] | None = None) -> MagicMock:
    """Connection whose cursor returns the given ledger rows on fetchall.
    ``load_recent_feedback`` issues SELECT … FROM feedback_ledger and calls
    ``fetchall``; the default test DB shape covers that."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = ctx
    return conn


# ------------------------------ build_prompt ------------------------------


def test_build_prompt_contains_signal_block() -> None:
    conn = _mock_conn_with_ledger()
    out = build_prompt("Please confirm meeting tomorrow.", conn)
    assert 'Signal: "Please confirm meeting tomorrow."' in out


def test_build_prompt_escapes_quotes() -> None:
    conn = _mock_conn_with_ledger()
    out = build_prompt('He said "hello"', conn)
    # Outer wrapper survives; inner quotes downgraded to apostrophes.
    assert "Signal: \"He said 'hello'\"" in out


def test_build_prompt_truncates_long_signal() -> None:
    conn = _mock_conn_with_ledger()
    long = "x" * 5000
    out = build_prompt(long, conn)
    assert "x" * 3000 in out
    assert "x" * 3001 not in out


def test_build_prompt_contains_all_slugs_glossary() -> None:
    """Inv 3 / Inv 10: glossary pulled from slug_registry on every call.
    All active slugs MUST appear in the prompt."""
    conn = _mock_conn_with_ledger()
    out = build_prompt("signal", conn)
    for slug in slug_registry.active_slugs():
        assert slug in out, f"slug {slug!r} missing from prompt glossary"


def test_build_prompt_empty_hot_md_uses_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inv 1: missing hot.md is a valid zero-Gold state — fallback string
    renders, but the READ was still attempted."""
    # Point vault at a directory with no wiki/hot.md file.
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    slug_registry.reload()
    (tmp_path / "slugs.yml").write_text(
        "version: 1\nmatters:\n  - {slug: x, status: active, description: 'x'}\n",
        encoding="utf-8",
    )
    conn = _mock_conn_with_ledger()
    out = build_prompt("sig", conn)
    assert "(no current-priorities cache available)" in out


def test_build_prompt_empty_ledger_uses_fallback() -> None:
    """Inv 1: empty ledger renders the zero-Gold fallback string."""
    conn = _mock_conn_with_ledger(rows=[])
    out = build_prompt("sig", conn)
    assert "(no recent Director actions)" in out


def test_build_prompt_renders_ledger_rows() -> None:
    """Inv 3: ledger rows render into the prompt feedback block."""
    from datetime import datetime, timezone

    rows = [
        (
            1,
            datetime(2026, 4, 17, tzinfo=timezone.utc),
            "correct",
            "movie",
            None,
            42,
            {"note": "typo"},
            "fix matter typo",
        )
    ]
    conn = _mock_conn_with_ledger(rows=rows)
    out = build_prompt("sig", conn)
    assert "2026-04-17" in out
    assert "correct" in out
    assert "fix matter typo" in out


def test_build_prompt_reads_on_every_call() -> None:
    """Inv 3: hot.md + ledger MUST be read on every invocation. No caching."""
    conn = _mock_conn_with_ledger()
    with patch(
        "kbl.steps.step1_triage.load_hot_md", return_value="- active: movie"
    ) as m_hot, patch(
        "kbl.steps.step1_triage.load_recent_feedback", return_value=[]
    ) as m_ledger:
        build_prompt("sig a", conn)
        build_prompt("sig b", conn)
        build_prompt("sig c", conn)
    assert m_hot.call_count == 3
    assert m_ledger.call_count == 3


def test_build_prompt_hot_md_block_content_rendered() -> None:
    conn = _mock_conn_with_ledger()
    with patch(
        "kbl.steps.step1_triage.load_hot_md",
        return_value="- ACTIVE: movie — hotel ops\n- BACKBURNER: ao",
    ):
        out = build_prompt("sig", conn)
    assert "ACTIVE: movie" in out
    assert "BACKBURNER: ao" in out


# ------------------------------ _build_pared_prompt ------------------------------


def test_pared_prompt_omits_ledger() -> None:
    """R3 retry uses a pared prompt — the feedback ledger block is
    replaced with a short marker so the template still formats cleanly.
    The actual ledger rows must NOT appear in the retry text."""
    pared = step1_triage._build_pared_prompt(
        signal_text="Confirm payment deadline tomorrow.",
        slug_glossary="  movie   — hotel",
        hot_md_block="- ACTIVE: movie — hotel ops",
    )
    # Marker present + signal + hot.md + glossary all present.
    assert "[LEDGER OMITTED — R3 retry]" in pared
    assert 'Signal: "Confirm payment deadline tomorrow."' in pared
    assert "ACTIVE: movie" in pared
    assert "movie" in pared  # slug glossary

    # Ledger-row content (e.g., a "correct"/"override" action line) is
    # NOT in the pared prompt. Any Director-action phrase typical of
    # render_ledger output would sit under the ledger block.
    assert "Director ledger" not in pared
    # All placeholders substituted.
    for placeholder in ("{signal}", "{slug_glossary}", "{hot_md_block}", "{feedback_ledger_block}"):
        assert placeholder not in pared


def test_pared_prompt_escapes_quotes_and_truncates() -> None:
    """Pared helper inherits the same signal-escape + 3000-char truncate
    rules as ``build_prompt`` — produces a well-formed ``Signal: "..."``
    wrapper regardless of input content."""
    long = 'He said "hello" ' + "x" * 5000
    pared = step1_triage._build_pared_prompt(
        signal_text=long,
        slug_glossary="  movie   — hotel",
        hot_md_block="- ACTIVE: movie",
    )
    # Outer wrapper survives; inner quotes downgraded.
    assert "Signal: \"He said 'hello' " in pared
    # Signal truncated at 3000 chars (post-escape length check).
    assert "x" * 2980 in pared  # some x content reached the prompt
    assert "x" * 5000 not in pared  # but not the full 5000


def test_pared_prompt_does_not_read_hot_md_or_ledger() -> None:
    """``_build_pared_prompt`` is a pure render helper — it takes already-
    computed blocks. Inv 3 is satisfied by ``triage()`` reading fresh
    inputs once per invocation via ``_read_prompt_inputs`` and sharing
    the values across both attempts, NOT by the retry re-reading."""
    with patch("kbl.steps.step1_triage.load_hot_md") as m_hot, patch(
        "kbl.steps.step1_triage.load_recent_feedback"
    ) as m_ledger:
        step1_triage._build_pared_prompt(
            signal_text="s",
            slug_glossary="glossary",
            hot_md_block="hot",
        )
    assert m_hot.call_count == 0
    assert m_ledger.call_count == 0


def test_triage_invocation_reads_hot_md_and_ledger_once() -> None:
    """Inv 3 anchor: every ``triage()`` call produces at least one fresh
    read of hot.md AND the feedback ledger — regardless of whether the
    parse happy-path or the retry path is taken. Retries reuse the
    already-fresh values; they don't re-read, but they don't skip either."""
    conn = _triage_conn()
    valid = {
        "response": _sample_response(primary_matter="movie"),
        "prompt_eval_count": 100,
        "eval_count": 30,
    }
    with patch.object(
        step1_triage, "call_ollama", return_value=valid
    ), patch(
        "kbl.steps.step1_triage.load_hot_md", return_value="- ACTIVE: movie"
    ) as m_hot, patch(
        "kbl.steps.step1_triage.load_recent_feedback", return_value=[]
    ) as m_ledger:
        triage(signal_id=1, conn=conn)
    # Exactly one read each per invocation (happy path, no retry needed).
    assert m_hot.call_count == 1
    assert m_ledger.call_count == 1

    # Same Inv 3 contract on the retries-exhausted path — still one
    # read each, not zero.
    conn2 = _triage_conn()
    unparseable = {"response": "garbage", "prompt_eval_count": 100, "eval_count": 20}
    with patch.object(
        step1_triage, "call_ollama", side_effect=[unparseable, unparseable]
    ), patch(
        "kbl.steps.step1_triage.load_hot_md", return_value="- ACTIVE: movie"
    ) as m_hot2, patch(
        "kbl.steps.step1_triage.load_recent_feedback", return_value=[]
    ) as m_ledger2:
        triage(signal_id=2, conn=conn2)
    assert m_hot2.call_count == 1
    assert m_ledger2.call_count == 1


# ------------------------------ normalize_matter ------------------------------


def test_normalize_matter_canonical() -> None:
    assert normalize_matter("movie") == "movie"


def test_normalize_matter_alias_resolves() -> None:
    # vault_layer0 has alias 'oskolkov' → 'ao'
    assert normalize_matter("oskolkov") == "ao"
    assert normalize_matter("Oskolkov") == "ao"  # case-insensitive


def test_normalize_matter_whitespace_alias() -> None:
    # 'mandarin oriental' (with space) is an alias in the fixture
    assert normalize_matter("Mandarin Oriental") == "movie"


def test_normalize_matter_null_variants() -> None:
    assert normalize_matter(None) is None
    assert normalize_matter("") is None
    assert normalize_matter("null") is None
    assert normalize_matter("none") is None
    assert normalize_matter("NONE") is None


def test_normalize_matter_unknown_returns_none() -> None:
    """Generic categories + unknown slugs collapse to None."""
    assert normalize_matter("investment") is None
    assert normalize_matter("real_estate") is None
    assert normalize_matter("made-up-slug") is None


# ------------------------------ parse_gemma_response ------------------------------


def _sample_response(**overrides: Any) -> str:
    body = {
        "primary_matter": "movie",
        "related_matters": [],
        "vedana": "routine",
        "triage_score": 65,
        "triage_confidence": 0.82,
        "summary": "hotel status update",
    }
    body.update(overrides)
    return json.dumps(body)


def test_parse_happy_path() -> None:
    r = parse_gemma_response(_sample_response())
    assert r.primary_matter == "movie"
    assert r.related_matters == ()
    assert r.vedana == "routine"
    assert r.triage_score == 65
    assert r.triage_confidence == pytest.approx(0.82)
    assert r.summary == "hotel status update"


def test_parse_primary_matter_null() -> None:
    r = parse_gemma_response(_sample_response(primary_matter=None))
    assert r.primary_matter is None


def test_parse_primary_matter_string_null() -> None:
    r = parse_gemma_response(_sample_response(primary_matter="null"))
    assert r.primary_matter is None


def test_parse_related_matters_deduped_against_primary() -> None:
    r = parse_gemma_response(
        _sample_response(
            primary_matter="movie",
            related_matters=["movie", "ao", "gamma", "ao"],
        )
    )
    # primary removed, duplicate ao collapsed, order preserved.
    assert r.related_matters == ("ao", "gamma")


def test_parse_related_matters_unknown_dropped() -> None:
    r = parse_gemma_response(
        _sample_response(related_matters=["gamma", "does-not-exist"])
    )
    assert r.related_matters == ("gamma",)


def test_parse_malformed_json_raises() -> None:
    with pytest.raises(TriageParseError, match="invalid JSON"):
        parse_gemma_response("{not valid json")


def test_parse_empty_string_raises() -> None:
    with pytest.raises(TriageParseError, match="empty model response"):
        parse_gemma_response("")


def test_parse_non_object_raises() -> None:
    with pytest.raises(TriageParseError, match="top-level must be object"):
        parse_gemma_response('["a", "b"]')


def test_parse_missing_key_raises() -> None:
    partial = {"vedana": "routine", "triage_score": 10}
    with pytest.raises(TriageParseError, match="missing required keys"):
        parse_gemma_response(json.dumps(partial))


def test_parse_bad_vedana_raises() -> None:
    with pytest.raises(TriageParseError, match="vedana must be one of"):
        parse_gemma_response(_sample_response(vedana="urgent"))


def test_parse_score_out_of_range_clamps() -> None:
    r = parse_gemma_response(_sample_response(triage_score=150))
    assert r.triage_score == 100
    r2 = parse_gemma_response(_sample_response(triage_score=-5))
    assert r2.triage_score == 0


def test_parse_confidence_out_of_range_clamps() -> None:
    r = parse_gemma_response(_sample_response(triage_confidence=1.5))
    assert r.triage_confidence == 1.0


def test_parse_score_from_string_accepted() -> None:
    """Gemma sometimes emits ``"triage_score": "65"`` — coerce politely."""
    r = parse_gemma_response(_sample_response(triage_score="65"))
    assert r.triage_score == 65


def test_parse_score_bool_rejected() -> None:
    with pytest.raises(TriageParseError, match="bool"):
        parse_gemma_response(_sample_response(triage_score=True))


def test_parse_related_matters_not_list_raises() -> None:
    with pytest.raises(TriageParseError, match="related_matters must be a list"):
        parse_gemma_response(_sample_response(related_matters="movie"))


# ------------------------------ call_ollama ------------------------------


def _fake_response(payload: dict[str, Any]):
    """Build a fake urlopen context-manager response."""
    ctx = MagicMock()
    ctx.read.return_value = json.dumps(payload).encode("utf-8")
    ctx.__enter__ = lambda self: ctx
    ctx.__exit__ = lambda self, *a: False
    return ctx


def test_call_ollama_posts_to_generate_endpoint() -> None:
    with patch("urllib.request.urlopen") as m_open:
        m_open.return_value = _fake_response(
            {"response": '{"primary_matter": null, "vedana": "routine"}'}
        )
        out = call_ollama("prompt", host="http://127.0.0.1:11434")
    assert out["response"].startswith("{")
    req = m_open.call_args.args[0]
    assert req.full_url == "http://127.0.0.1:11434/api/generate"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gemma2:8b"
    assert body["stream"] is False
    assert body["format"] == "json"
    assert body["options"]["temperature"] == 0.0
    assert body["options"]["seed"] == 42


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
        side_effect=urllib.error.HTTPError(
            "http://x", 503, "service unavailable", {}, None
        ),
    ):
        with pytest.raises(OllamaUnavailableError, match="HTTP 503"):
            call_ollama("prompt")


def test_call_ollama_raises_on_urlerror() -> None:
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
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
        bad.read.return_value = b"not json at all"
        bad.__enter__ = lambda self: bad
        bad.__exit__ = lambda self, *a: False
        m_open.return_value = bad
        with pytest.raises(OllamaUnavailableError, match="non-JSON envelope"):
            call_ollama("prompt")


# ------------------------------ triage() end-to-end ------------------------------


def _triage_conn(
    raw_content: str = "Deadline Monday — please sign the agreement.",
    ledger_rows: list[tuple] | None = None,
) -> MagicMock:
    """Conn that serves signal_queue SELECT + all subsequent writes.

    signal_queue SELECT returns ``(raw_content,)``.
    feedback_ledger SELECT (via load_recent_feedback) returns ``ledger_rows``.
    Writes (UPDATE / INSERT) are no-ops on the MagicMock.
    """
    conn = MagicMock()
    call_sequence = []

    def _make_cursor():
        cur = MagicMock()

        def _execute(sql, params=None):
            call_sequence.append((sql, params))
            sql_lower = sql.lower()
            if "from signal_queue" in sql_lower and "select" in sql_lower:
                cur.fetchone.return_value = (raw_content,)
            elif "from feedback_ledger" in sql_lower:
                cur.fetchall.return_value = ledger_rows or []
            else:
                cur.fetchone.return_value = None
                cur.fetchall.return_value = []

        cur.execute.side_effect = _execute
        return cur

    def _cursor():
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    conn.cursor.side_effect = _cursor
    conn._calls = call_sequence
    return conn


def test_triage_writes_result_and_advances_state_high_score() -> None:
    conn = _triage_conn()
    gemma_payload = {
        "response": _sample_response(triage_score=80, primary_matter="movie"),
        "prompt_eval_count": 1200,
        "eval_count": 85,
    }
    with patch.object(step1_triage, "call_ollama", return_value=gemma_payload):
        result = triage(signal_id=42, conn=conn)
    assert result.primary_matter == "movie"
    assert result.triage_score == 80

    # Inspect the SQL stream to verify state transition + writes.
    sqls = [s.lower() for s, _ in conn._calls]
    # Must mark running BEFORE the update with the result.
    assert any("status = 'triage_running'" in s for s in sqls)
    # Final UPDATE uses awaiting_resolve (score >= threshold 40)
    update_sqls = [s for s, p in conn._calls if "update signal_queue set" in s.lower() and "primary_matter" in s.lower()]
    assert update_sqls
    _, params = [c for c in conn._calls if "update signal_queue set" in c[0].lower() and "primary_matter" in c[0].lower()][0]
    assert "awaiting_resolve" in params
    # Cost ledger row written with success=True
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert cost_rows
    _, cost_params = cost_rows[0]
    assert 42 in cost_params
    assert "gemma2:8b" in cost_params
    assert 1200 in cost_params
    assert 85 in cost_params
    assert True in cost_params  # success flag


def test_triage_routes_low_score_to_inbox() -> None:
    conn = _triage_conn()
    gemma_payload = {
        "response": _sample_response(triage_score=25, primary_matter=None),
        "prompt_eval_count": 1000,
        "eval_count": 50,
    }
    with patch.object(step1_triage, "call_ollama", return_value=gemma_payload):
        result = triage(signal_id=7, conn=conn)
    assert result.triage_score == 25
    update_rows = [c for c in conn._calls if "update signal_queue set" in c[0].lower() and "primary_matter" in c[0].lower()]
    assert update_rows
    _, params = update_rows[0]
    assert "routed_inbox" in params


def test_triage_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """KBL_PIPELINE_TRIAGE_THRESHOLD raises the bar for 'resolve' routing."""
    monkeypatch.setenv("KBL_PIPELINE_TRIAGE_THRESHOLD", "70")
    conn = _triage_conn()
    gemma_payload = {
        "response": _sample_response(triage_score=50, primary_matter="movie"),
        "prompt_eval_count": 1000,
        "eval_count": 50,
    }
    with patch.object(step1_triage, "call_ollama", return_value=gemma_payload):
        triage(signal_id=99, conn=conn)
    update_rows = [c for c in conn._calls if "update signal_queue set" in c[0].lower() and "primary_matter" in c[0].lower()]
    _, params = update_rows[0]
    # 50 < 70 → terminal inbox state
    assert "routed_inbox" in params


def test_triage_boundary_at_threshold_routes_to_resolve() -> None:
    """Score == threshold lands on the resolve side (>= threshold)."""
    conn = _triage_conn()
    gemma_payload = {
        "response": _sample_response(triage_score=40, primary_matter=None),
        "prompt_eval_count": 1000,
        "eval_count": 50,
    }
    with patch.object(step1_triage, "call_ollama", return_value=gemma_payload):
        triage(signal_id=11, conn=conn)
    update_rows = [c for c in conn._calls if "update signal_queue set" in c[0].lower() and "primary_matter" in c[0].lower()]
    _, params = update_rows[0]
    assert "awaiting_resolve" in params


def test_triage_parse_error_first_attempt_triggers_retry() -> None:
    """R3 retry path: first call unparseable, second call valid → final
    result written once + ONE success=True cost row (from the good
    second attempt). The failed first attempt writes its own
    success=False cost row. No raise escapes."""
    conn = _triage_conn()
    unparseable = {"response": "not json at all", "prompt_eval_count": 1000, "eval_count": 40}
    valid = {
        "response": _sample_response(triage_score=55, primary_matter="movie"),
        "prompt_eval_count": 1100,
        "eval_count": 60,
    }
    with patch.object(
        step1_triage, "call_ollama", side_effect=[unparseable, valid]
    ) as m_call:
        result = triage(signal_id=42, conn=conn)

    assert m_call.call_count == 2
    # The pared retry prompt must NOT include the ledger content —
    # capture the second call's prompt and assert the marker surfaces.
    _, second_kwargs = m_call.call_args_list[1]
    second_prompt = (
        m_call.call_args_list[1].args[0]
        if m_call.call_args_list[1].args
        else second_kwargs["prompt"]
    )
    assert "[LEDGER OMITTED — R3 retry]" in second_prompt

    assert result.primary_matter == "movie"
    assert result.triage_score == 55

    # Exactly TWO cost rows: first success=False (parse fail), second
    # success=True (good result). Order-preserving.
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert len(cost_rows) == 2
    assert cost_rows[0][1][-1] is False  # failed attempt
    assert cost_rows[1][1][-1] is True  # winning attempt

    # Exactly ONE result UPDATE (the winning attempt).
    update_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "primary_matter" in c[0].lower()
    ]
    assert len(update_rows) == 1
    _, params = update_rows[0]
    # Route based on score (55 ≥ 40 → awaiting_resolve).
    assert "awaiting_resolve" in params


def test_triage_parse_error_retries_exhausted_writes_stub() -> None:
    """§7 row 3 terminal path: both attempts unparseable → stub written,
    status routes to the terminal ``routed_inbox`` state, TWO cost rows
    both success=False. No raise — pipeline keeps flowing."""
    conn = _triage_conn()
    unparseable = {"response": "garbage", "prompt_eval_count": 1000, "eval_count": 40}

    with patch.object(
        step1_triage, "call_ollama", side_effect=[unparseable, unparseable]
    ) as m_call:
        result = triage(signal_id=11, conn=conn)

    assert m_call.call_count == 2

    # Stub shape per brief: primary_matter=None, vedana=None, score=0,
    # confidence=0.0, summary='parse_failed'.
    assert result.primary_matter is None
    assert result.vedana is None
    assert result.triage_score == 0
    assert result.triage_confidence == 0.0
    assert result.summary == "parse_failed"
    assert result.related_matters == ()

    # Exactly TWO cost rows, both success=False.
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert len(cost_rows) == 2
    for _, params in cost_rows:
        assert params[-1] is False

    # Exactly ONE result UPDATE — the stub write. Status = terminal
    # ``routed_inbox`` (§4.2 canonical name; not a pre-claim hold).
    update_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "primary_matter" in c[0].lower()
    ]
    assert len(update_rows) == 1
    _, params = update_rows[0]
    assert "routed_inbox" in params
    # The stub values are the row written.
    assert None in params  # primary_matter=None
    assert "parse_failed" in params


def test_triage_parse_error_does_not_raise_past_retry_budget() -> None:
    """Explicit companion to the retries-exhausted test: ``TriageParseError``
    is absorbed internally and MUST NOT leak past ``triage()``."""
    conn = _triage_conn()
    unparseable = {"response": "garbage", "prompt_eval_count": 500, "eval_count": 20}
    with patch.object(
        step1_triage, "call_ollama", side_effect=[unparseable, unparseable]
    ):
        # No ``pytest.raises`` — the exception must not escape.
        triage(signal_id=99, conn=conn)


def test_triage_ollama_unreachable_still_propagates() -> None:
    """``OllamaUnavailableError`` is transport — NOT part of the parse
    retry budget. It bubbles unchanged so the caller can defer the signal
    and let availability-fallback take over on the next tick."""
    conn = _triage_conn()
    with patch.object(
        step1_triage,
        "call_ollama",
        side_effect=step1_triage.OllamaUnavailableError("down"),
    ):
        with pytest.raises(step1_triage.OllamaUnavailableError, match="down"):
            triage(signal_id=1, conn=conn)


def test_triage_signal_not_found_raises() -> None:
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx

    with pytest.raises(LookupError, match="row not found"):
        triage(signal_id=999, conn=conn)


# ------------------------------ template + module surface ------------------------------


def test_template_file_exists_and_has_all_placeholders() -> None:
    text = step1_triage._load_template()
    assert "{signal}" in text
    assert "{slug_glossary}" in text
    assert "{hot_md_block}" in text
    assert "{feedback_ledger_block}" in text


def test_triage_result_is_frozen() -> None:
    r = TriageResult(primary_matter=None)
    with pytest.raises(Exception):
        r.triage_score = 99  # type: ignore[misc]


def test_module_public_surface() -> None:
    for name in (
        "build_prompt",
        "parse_gemma_response",
        "normalize_matter",
        "call_ollama",
        "triage",
        "TriageResult",
    ):
        assert hasattr(step1_triage, name)
