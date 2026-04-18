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
    assert "awaiting_inbox_route" in params


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
    # 50 < 70 → inbox
    assert "awaiting_inbox_route" in params


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


def test_triage_parse_error_writes_failure_ledger_row_and_raises() -> None:
    conn = _triage_conn()
    gemma_payload = {"response": "not valid json at all"}
    with patch.object(step1_triage, "call_ollama", return_value=gemma_payload):
        with pytest.raises(TriageParseError):
            triage(signal_id=5, conn=conn)
    # Cost row written with success=False, no result UPDATE fired.
    cost_rows = [c for c in conn._calls if "kbl_cost_ledger" in c[0].lower()]
    assert cost_rows
    _, params = cost_rows[0]
    assert False in params  # success flag
    update_rows = [c for c in conn._calls if "update signal_queue set" in c[0].lower() and "primary_matter" in c[0].lower()]
    assert not update_rows  # no result row written on parse failure


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
