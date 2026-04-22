"""Tests for kbl.steps.step5_opus — Opus synthesis with R3 ladder + tx contract."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from kbl import slug_registry
from kbl.anthropic_client import OpusResponse
from kbl.cost_gate import CostDecision
from kbl.exceptions import (
    AnthropicUnavailableError,
    KblError,
    OpusRequestError,
)
from kbl.steps import step5_opus
from kbl.steps.step4_classify import ClassifyDecision
from kbl.steps.step5_opus import (
    SynthesisResult,
    _build_skip_inbox_stub,
    _build_stub_only_stub,
    _build_user_prompt,
    _PromptInputs,
    _R3_IDENTICAL,
    _R3_MINIMAL,
    _R3_PARED,
    _SignalInputs,
    _truncate_signal,
    synthesize,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VAULT_LAYER0 = FIXTURES / "vault_layer0"

_VALID_SLUG = "ao"
_UNKNOWN_SLUG = "unknown_matter_slug_123"


@pytest.fixture(autouse=True)
def _vault_and_templates(monkeypatch: pytest.MonkeyPatch):
    """Point slug_registry at the shared fixture vault so describe('ao')
    resolves, and reset the prompt template caches around every test."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT_LAYER0))
    slug_registry.reload()
    step5_opus._reset_template_cache_for_tests()
    yield
    step5_opus._reset_template_cache_for_tests()
    slug_registry.reload()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "KBL_STEP5_MODEL",
        "KBL_COST_DAILY_CAP_EUR",
        "KBL_CB_CONSECUTIVE_FAILURES",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# --------------------------- signal-loading + dispatch helpers ---------------------------


def _default_row(
    decision: str = ClassifyDecision.FULL_SYNTHESIS.value,
    primary_matter: Optional[str] = _VALID_SLUG,
    related_matters: Optional[list] = None,
    resolved_thread_paths: Optional[list] = None,
    raw_content: str = "signal body",
    source: str = "email",
    vedana: str = "routine",
    triage_summary: str = "Triage OK",
    extracted_entities: Optional[dict] = None,
) -> tuple:
    """Row shape returned by _fetch_signal_inputs's SELECT."""
    return (
        raw_content,
        source,
        primary_matter,
        related_matters if related_matters is not None else [],
        vedana,
        triage_summary,
        resolved_thread_paths if resolved_thread_paths is not None else [],
        extracted_entities if extracted_entities is not None else {},
        decision,
    )


def _mock_conn(row: Optional[tuple] = None) -> MagicMock:
    """Build a conn whose first SELECT returns ``row``; all writes
    recorded into conn._calls; commit/rollback counters tracked."""
    conn = MagicMock()
    call_sequence: list[tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            call_sequence.append((sql, params))
            s = sql.lower()
            if "from signal_queue" in s and "select" in s:
                cur.fetchone.return_value = row
            elif "from kbl_circuit_breaker" in s and "select" in s:
                cur.fetchone.return_value = (0, None, None)
            elif "update kbl_circuit_breaker" in s and "returning" in s:
                cur.fetchone.return_value = (1,)
            elif "coalesce(sum(cost_usd)" in s:
                cur.fetchone.return_value = (Decimal("0"),)
            else:
                cur.fetchone.return_value = None

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


def _sql_calls_matching(conn: MagicMock, needle: str) -> list[tuple[str, Any]]:
    n = needle.lower()
    return [c for c in conn._calls if n in c[0].lower()]


def _make_opus_response(
    text: str = "---\ntitle: x\nvoice: silver\nauthor: pipeline\n---\n\nbody",
    cost: Decimal = Decimal("0.15"),
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> OpusResponse:
    return OpusResponse(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost,
        latency_ms=1000,
        stop_reason="end_turn",
        model_id="claude-opus-4-7",
    )


# --------------------------- _truncate_signal ---------------------------


def test_truncate_signal_passes_through_short_text() -> None:
    assert _truncate_signal("hello") == "hello"


def test_truncate_signal_at_boundary_is_unchanged() -> None:
    boundary = "x" * 50_000
    assert _truncate_signal(boundary) == boundary


def test_truncate_signal_adds_marker_at_50k() -> None:
    oversized = "x" * 50_001
    result = _truncate_signal(oversized)
    assert result.startswith("x" * 50_000)
    assert "TRUNCATED" in result


# --------------------------- deterministic stubs ---------------------------


def test_build_skip_inbox_stub_has_frontmatter_contract() -> None:
    inputs = _SignalInputs(
        signal_id=1,
        raw_content="x",
        source="email",
        primary_matter=_UNKNOWN_SLUG,
        related_matters=[],
        vedana="routine",
        triage_summary="s",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.SKIP_INBOX.value,
    )
    stub = _build_skip_inbox_stub(inputs)
    # Inv 8: voice: silver + author: pipeline always.
    assert "voice: silver" in stub
    assert "author: pipeline" in stub
    # Stub marker so Director knows this wasn't Opus.
    assert "status: stub_auto" in stub


def test_build_stub_only_stub_emits_review_marker() -> None:
    inputs = _SignalInputs(
        signal_id=2,
        raw_content="x",
        source="email",
        primary_matter=_VALID_SLUG,
        related_matters=[],
        vedana="routine",
        triage_summary="noise",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.STUB_ONLY.value,
    )
    stub = _build_stub_only_stub(inputs)
    assert "status: stub_auto" in stub
    assert "low-confidence triage" in stub
    assert "voice: silver" in stub
    assert "author: pipeline" in stub


# ------------------- frontmatter YAML roundtrip (STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1) -------------------


def _split_fm_body(stub: str) -> tuple[dict, str]:
    """Mirror Step 6's ``_split_frontmatter`` (simplified) for test use."""
    import yaml as _yaml

    assert stub.startswith("---\n"), "stub missing opening fence"
    after_open = stub[len("---\n") :]
    close_idx = after_open.find("\n---")
    assert close_idx >= 0, "stub missing closing fence"
    fm_text = after_open[:close_idx]
    body = after_open[close_idx + len("\n---") :].lstrip("\n")
    return _yaml.safe_load(fm_text), body


def test_skip_inbox_stub_frontmatter_parses_cleanly_despite_colon_in_title() -> None:
    """Regression: pre-fix, the literal title
    ``"Layer 2 gate: matter not in current scope"`` broke YAML parse
    with "mapping values are not allowed here" because the f-string
    concat emitter left the colon unquoted. Post-fix, safe_dump
    auto-quotes and the roundtrip succeeds."""
    inputs = _SignalInputs(
        signal_id=42,
        raw_content="x",
        source="email",
        primary_matter=None,
        related_matters=[],
        vedana=None,
        triage_summary="",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.SKIP_INBOX.value,
    )
    stub = _build_skip_inbox_stub(inputs)

    fm, body = _split_fm_body(stub)

    # Round-tripped title survives the colon verbatim.
    assert fm["title"] == "Layer 2 gate: matter not in current scope"
    # Inv 8 structural fields survive the refactor.
    assert fm["voice"] == "silver"
    assert fm["author"] == "pipeline"
    assert fm["status"] == "stub_auto"
    # None-safe primary_matter round-trips as Python None (YAML null),
    # matching pre-fix ``primary_matter: null`` literal semantics.
    assert fm["primary_matter"] is None
    # Empty list round-trips as empty list, not "[]" string.
    assert fm["related_matters"] == []
    # Default vedana when inputs.vedana is None.
    assert fm["vedana"] == "routine"
    # source_id is the signal_id cast to str (SilverFrontmatter.source_id: str;
    # producer-side cast per STEP5_STUB_SOURCE_ID_TYPE_FIX_1 — Pydantic v2
    # does NOT coerce int → str, so this assertion was stale from PR #34).
    assert fm["source_id"] == "42"
    # Body still present, not swallowed by frontmatter.
    assert "Layer 2 scope gate blocked this signal" in body


def test_stub_only_stub_frontmatter_survives_pathological_triage_summary() -> None:
    """Triage summaries are free-form and can contain colons, ``#``
    hashes, leading dashes, newlines, quote characters — every such
    char broke the pre-fix f-string concat. safe_dump handles all."""
    hostile = 'RE: meeting @ 14:00 — "urgent" #priority\n- item'
    # Use "movie" as the related slug — active in the fixture registry.
    # STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1: _normalize_stub_inputs
    # now filters related_matters against the active slug registry and
    # dedupes the primary out — the pre-fix [_VALID_SLUG, "mo_vie"]
    # input was pathological on both counts (primary-in-related + a
    # non-active typo'd slug) and would have failed Step 6 Pydantic
    # validation. Replaced with a legitimate cross-link shape.
    inputs = _SignalInputs(
        signal_id=99,
        raw_content="x",
        source="email",
        primary_matter=_VALID_SLUG,
        related_matters=[_VALID_SLUG, "movie"],
        vedana="threat",
        triage_summary=hostile,
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.STUB_ONLY.value,
    )
    stub = _build_stub_only_stub(inputs)

    fm, body = _split_fm_body(stub)

    # Title is triage_summary[:60] normalized (rstrip period/whitespace).
    assert fm["title"] == hostile[:60].rstrip(". \t")
    # Normalization: primary 'ao' de-duped out of related; 'movie' kept.
    assert fm["related_matters"] == ["movie"]
    assert fm["vedana"] == "threat"
    assert fm["status"] == "stub_auto"
    # Body preserved.
    assert "low-confidence triage" in body
    assert hostile in body  # full triage_summary in body text


def test_stub_frontmatter_field_order_is_stable() -> None:
    """Step 6 + Director eye both rely on stable key order. The refactor
    preserves the pre-fix sequence exactly."""
    inputs = _SignalInputs(
        signal_id=1,
        raw_content="x",
        source="email",
        primary_matter=_VALID_SLUG,
        related_matters=[],
        vedana="routine",
        triage_summary="short",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.STUB_ONLY.value,
    )
    stub = _build_stub_only_stub(inputs)
    fm, _ = _split_fm_body(stub)

    expected_order = [
        "title",
        "voice",
        "author",
        "created",
        "source_id",
        "primary_matter",
        "related_matters",
        "vedana",
        "status",
    ]
    assert list(fm.keys()) == expected_order


def test_stub_parses_through_step6_split_frontmatter() -> None:
    """End-to-end: Step 5 stub -> Step 6's actual ``_split_frontmatter``.
    Guards the exact failure mode reported in the field (4 rows stranded
    at ``status='opus_failed'`` with "mapping values are not allowed
    here")."""
    from kbl.steps.step6_finalize import _split_frontmatter

    inputs = _SignalInputs(
        signal_id=500,
        raw_content="x",
        source="email",
        primary_matter=None,
        related_matters=[],
        vedana=None,
        triage_summary="",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.SKIP_INBOX.value,
    )
    stub = _build_skip_inbox_stub(inputs)

    fm_dict, body = _split_frontmatter(stub)

    assert fm_dict["title"] == "Layer 2 gate: matter not in current scope"
    assert fm_dict["status"] == "stub_auto"
    assert body.startswith("Layer 2 scope gate blocked this signal")


# ------------------- source_id type (STEP5_STUB_SOURCE_ID_TYPE_FIX_1) -------------------


def test_stub_frontmatter_emits_source_id_as_string() -> None:
    """Regression: pre-fix, ``source_id: inputs.signal_id`` wrote a raw
    int; ``yaml.safe_dump({'source_id': 17})`` emits ``source_id: 17``
    (unquoted); ``yaml.safe_load`` returns Python ``int``; Pydantic v2
    ``source_id: str`` rejects with "Input should be a valid string".

    Post-fix, the producer casts via ``str(inputs.signal_id)`` so the
    round-tripped value is a string."""
    import yaml

    inputs = _SignalInputs(
        signal_id=17,
        raw_content="x",
        source="email",
        primary_matter=None,
        related_matters=[],
        vedana=None,
        triage_summary="",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.SKIP_INBOX.value,
    )
    stub = _build_skip_inbox_stub(inputs)
    after_open = stub[len("---\n") :]
    close_idx = after_open.find("\n---")
    fm = yaml.safe_load(after_open[:close_idx])

    assert isinstance(fm["source_id"], str), (
        f"source_id type drift: {type(fm['source_id']).__name__} "
        f"value={fm['source_id']!r}"
    )
    assert fm["source_id"] == "17"


@pytest.mark.parametrize("signal_id", [1, 0, 17, 2_147_483_647, 9_999_999_999])
def test_stub_source_id_is_string_across_id_sizes(signal_id: int) -> None:
    """Property-style: every plausible ``signal_id`` (incl. 0 and
    >32-bit ids) must serialize as a YAML string."""
    import yaml

    inputs = _SignalInputs(
        signal_id=signal_id,
        raw_content="x",
        source="email",
        primary_matter=None,
        related_matters=[],
        vedana="routine",
        triage_summary="noise",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.STUB_ONLY.value,
    )
    stub = _build_stub_only_stub(inputs)
    after_open = stub[len("---\n") :]
    close_idx = after_open.find("\n---")
    fm = yaml.safe_load(after_open[:close_idx])

    assert isinstance(fm["source_id"], str)
    assert fm["source_id"] == str(signal_id)


def test_stub_validates_against_silver_frontmatter_schema() -> None:
    """End-to-end: Step 5 stub -> YAML roundtrip -> Step 6 injects
    telemetry -> ``SilverFrontmatter(**fm_dict)`` accepts.

    Guards the composite contract: colon-safe YAML + str-typed
    source_id + stub_auto status + slug in active set + datetime-coercible
    ``created``. Pre-PR-#34 this failed at YAML parse; pre-this-PR it
    failed at Pydantic ``source_id: str``; post-this-PR it passes."""
    import yaml
    from kbl.schemas.silver import SilverFrontmatter

    inputs = _SignalInputs(
        signal_id=42,
        raw_content="x",
        source="email",
        primary_matter=_VALID_SLUG,  # 'ao' — registered ACTIVE fixture slug
        related_matters=[],
        vedana="routine",
        triage_summary="triage note",
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=ClassifyDecision.STUB_ONLY.value,
    )
    stub = _build_stub_only_stub(inputs)
    after_open = stub[len("---\n") :]
    close_idx = after_open.find("\n---")
    fm_dict = yaml.safe_load(after_open[:close_idx])

    # Step 6 injects triage telemetry before Pydantic validate (see
    # finalize() ~line 615). Mirror that so this is a truthful contract
    # test of the producer + injection chain.
    fm_dict.setdefault("triage_score", 5)
    fm_dict.setdefault("triage_confidence", 0.1)
    fm_dict["source_id"] = str(inputs.signal_id)  # mirrors Step 6 force-set

    fm = SilverFrontmatter(**fm_dict)

    assert fm.source_id == "42"
    assert fm.voice == "silver"
    assert fm.author == "pipeline"
    assert fm.primary_matter == _VALID_SLUG
    assert fm.status == "stub_auto"


# --------------------------- synthesize — routing ---------------------------


def test_synthesize_skip_inbox_writes_stub_no_opus_call() -> None:
    row = _default_row(decision=ClassifyDecision.SKIP_INBOX.value)
    conn = _mock_conn(row=row)

    with patch("kbl.steps.step5_opus.call_opus") as m_call_opus:
        result = synthesize(signal_id=1, conn=conn)

    assert m_call_opus.call_count == 0
    assert result.decision == ClassifyDecision.SKIP_INBOX.value
    assert result.terminal_state == "awaiting_finalize"
    assert result.opus_response is None
    # Draft written + status advanced.
    drafts = _sql_calls_matching(conn, "opus_draft_markdown")
    assert len(drafts) == 1
    _, params = drafts[0]
    draft_text, next_state, sid = params
    assert "status: stub_auto" in draft_text
    assert next_state == "awaiting_finalize"
    assert sid == 1


def test_synthesize_stub_only_writes_stub_no_opus_call() -> None:
    row = _default_row(decision=ClassifyDecision.STUB_ONLY.value)
    conn = _mock_conn(row=row)

    with patch("kbl.steps.step5_opus.call_opus") as m_call_opus:
        result = synthesize(signal_id=2, conn=conn)

    assert m_call_opus.call_count == 0
    assert result.decision == ClassifyDecision.STUB_ONLY.value
    assert result.opus_response is None
    drafts = _sql_calls_matching(conn, "opus_draft_markdown")
    assert "low-confidence triage" in drafts[0][1][0]


def test_synthesize_full_synthesis_happy_path_writes_opus_draft() -> None:
    row = _default_row(decision=ClassifyDecision.FULL_SYNTHESIS.value)
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus", return_value=_make_opus_response(text="opus-body")
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        result = synthesize(signal_id=3, conn=conn)

    assert result.decision == ClassifyDecision.FULL_SYNTHESIS.value
    assert result.terminal_state == "awaiting_finalize"
    assert result.opus_response is not None
    assert result.opus_response.text == "opus-body"
    drafts = _sql_calls_matching(conn, "opus_draft_markdown")
    assert drafts[0][1][0] == "opus-body"
    # Cost ledger row for the successful call.
    cost_rows = _sql_calls_matching(conn, "insert into kbl_cost_ledger")
    assert len(cost_rows) == 1


def test_synthesize_unknown_decision_raises_kbl_error() -> None:
    row = _default_row(decision=None)
    conn = _mock_conn(row=row)

    with pytest.raises(KblError, match="step_5_decision"):
        synthesize(signal_id=1, conn=conn)

    # Commit-before-raise so the opus_failed state survives.
    assert conn.commit.call_count == 1
    failed_rows = [
        c for c in conn._calls
        if "update signal_queue set status = %s" in c[0].lower()
        and c[1] == ("opus_failed", 1)
    ]
    assert failed_rows


def test_synthesize_missing_signal_raises_lookup_error() -> None:
    conn = _mock_conn(row=None)
    with pytest.raises(LookupError):
        synthesize(signal_id=999, conn=conn)


# --------------------------- R3 retry ladder ---------------------------


def test_r3_retry_ladder_succeeds_on_attempt_2() -> None:
    """First attempt fails with AnthropicUnavailableError, second
    attempt (pared) succeeds — verify the pared prompt was tried."""
    row = _default_row()
    conn = _mock_conn(row=row)

    call_count = {"n": 0}

    def _fake_call(*, system: str, user: str, **kwargs: Any) -> OpusResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise AnthropicUnavailableError("transient")
        return _make_opus_response(text="saved-on-retry")

    with patch(
        "kbl.steps.step5_opus.call_opus", side_effect=_fake_call
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        result = synthesize(signal_id=5, conn=conn)

    assert call_count["n"] == 2
    assert result.terminal_state == "awaiting_finalize"
    assert result.opus_response is not None
    assert result.opus_response.text == "saved-on-retry"
    # Two cost_ledger rows: one failed (attempt 0), one success (attempt 1).
    cost_rows = _sql_calls_matching(conn, "insert into kbl_cost_ledger")
    assert len(cost_rows) == 2


def test_r3_retry_ladder_exhausted_raises_and_marks_failed() -> None:
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus",
        side_effect=AnthropicUnavailableError("5xx x3"),
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        with pytest.raises(AnthropicUnavailableError):
            synthesize(signal_id=7, conn=conn)

    # opus_failed state written, committed before raise.
    assert conn.commit.call_count == 1
    failed_rows = [
        c for c in conn._calls
        if "update signal_queue set status = %s" in c[0].lower()
        and c[1] == ("opus_failed", 7)
    ]
    assert failed_rows
    # Circuit breaker failure recorded.
    cb_updates = [
        c for c in conn._calls
        if "update kbl_circuit_breaker" in c[0].lower()
        and "returning" in c[0].lower()
    ]
    assert cb_updates
    # 3 failed cost_ledger rows.
    cost_rows = _sql_calls_matching(conn, "insert into kbl_cost_ledger")
    assert len(cost_rows) == 3


def test_r3_opus_request_error_bypasses_retry_ladder() -> None:
    """4xx user error — retrying the same prompt won't recover. Go
    straight to opus_failed after one attempt."""
    row = _default_row()
    conn = _mock_conn(row=row)

    call_count = {"n": 0}

    def _fake_call(*, system: str, user: str, **kwargs: Any) -> OpusResponse:
        call_count["n"] += 1
        raise OpusRequestError("400 invalid model")

    with patch(
        "kbl.steps.step5_opus.call_opus", side_effect=_fake_call
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        with pytest.raises(OpusRequestError):
            synthesize(signal_id=8, conn=conn)

    # Only ONE call — ladder bypassed.
    assert call_count["n"] == 1


def test_r3_retry_ladder_successful_call_pattern() -> None:
    """Happy path on attempt 1 — verify only one cost ledger row and
    no circuit breaker failure recorded."""
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus", return_value=_make_opus_response()
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        synthesize(signal_id=9, conn=conn)

    cost_rows = _sql_calls_matching(conn, "insert into kbl_cost_ledger")
    assert len(cost_rows) == 1
    # Success path writes record_opus_success (circuit reset).
    cb_reset = [
        c for c in conn._calls
        if "update kbl_circuit_breaker" in c[0].lower()
        and "consecutive_failures = 0" in c[0].lower()
    ]
    assert cb_reset


# --------------------------- prompt shape R3 variants ---------------------------


def _tiny_signal() -> _SignalInputs:
    return _SignalInputs(
        signal_id=1,
        raw_content="body",
        source="email",
        primary_matter=_VALID_SLUG,
        related_matters=["cupial"],
        vedana="opportunity",
        triage_summary="triage summary text",
        resolved_thread_paths=[],
        extracted_entities={"people": []},
        step_5_decision=ClassifyDecision.FULL_SYNTHESIS.value,
    )


def test_pared_user_prompt_omits_ledger_but_keeps_hot_md() -> None:
    inputs = _tiny_signal()
    prompt_inputs = _PromptInputs(
        gold_block="(zero gold)",
        hot_md_block="## Actively pressing\n- **ao**: x\n",
        ledger_block="[2026-04-15] correct ao: check",
    )
    text = _build_user_prompt(inputs, prompt_inputs, attempt=_R3_PARED)
    assert "Actively pressing" in text
    assert "R3 pared retry" in text or "omitted — R3 pared" in text
    # The actual ledger content must NOT appear.
    assert "[2026-04-15] correct ao: check" not in text


def test_minimal_user_prompt_omits_ledger_and_hot_md() -> None:
    inputs = _tiny_signal()
    prompt_inputs = _PromptInputs(
        gold_block="(zero gold)",
        hot_md_block="## Actively pressing\n- **ao**: x\n",
        ledger_block="[2026-04-15] correct ao: check",
    )
    text = _build_user_prompt(inputs, prompt_inputs, attempt=_R3_MINIMAL)
    # Minimal drops both.
    assert "Actively pressing" not in text
    assert "[2026-04-15] correct ao: check" not in text
    assert "R3 minimal retry" in text or "omitted — R3 minimal" in text


def test_identical_user_prompt_keeps_everything() -> None:
    inputs = _tiny_signal()
    prompt_inputs = _PromptInputs(
        gold_block="(zero gold)",
        hot_md_block="## Actively pressing\n- **ao**: x\n",
        ledger_block="[2026-04-15] correct ao: check",
    )
    text = _build_user_prompt(inputs, prompt_inputs, attempt=_R3_IDENTICAL)
    assert "Actively pressing" in text
    assert "[2026-04-15] correct ao: check" in text


# --------------------------- cost gate integration ---------------------------


def test_synthesize_cost_gate_denial_parks_signal() -> None:
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.can_fire_step5",
        return_value=CostDecision.DAILY_CAP_EXCEEDED,
    ), patch(
        "kbl.steps.step5_opus.call_opus"
    ) as m_call_opus, patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        result = synthesize(signal_id=11, conn=conn)

    # No Opus call at all.
    assert m_call_opus.call_count == 0
    # Signal parked at paused_cost_cap.
    assert result.terminal_state == "paused_cost_cap"
    parked = [
        c for c in conn._calls
        if "update signal_queue set status = %s" in c[0].lower()
        and c[1] == ("paused_cost_cap", 11)
    ]
    assert parked
    # Commit-before-return so park survives rollback.
    assert conn.commit.call_count == 1


def test_synthesize_circuit_breaker_open_also_parks() -> None:
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.can_fire_step5",
        return_value=CostDecision.CIRCUIT_BREAKER_OPEN,
    ), patch(
        "kbl.steps.step5_opus.call_opus"
    ) as m_call_opus, patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        result = synthesize(signal_id=12, conn=conn)

    assert m_call_opus.call_count == 0
    assert result.terminal_state == "paused_cost_cap"


# --------------------------- CHANDA invariant tests ---------------------------


def test_chanda_inv1_zero_gold_produces_callable_prompt() -> None:
    """Inv 1: zero-Gold matter — the prompt is still built, Opus is still
    called, stub paths are NOT triggered."""
    row = _default_row()
    conn = _mock_conn(row=row)

    captured = {}

    def _capture(*, system: str, user: str, **kwargs: Any) -> OpusResponse:
        captured["user"] = user
        return _make_opus_response()

    with patch(
        "kbl.steps.step5_opus.call_opus", side_effect=_capture
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        synthesize(signal_id=13, conn=conn)

    # G2 sentinel is the zero-Gold representation — valid state, not an error.
    assert "no prior Gold" in captured["user"]


def test_chanda_inv3_hot_md_and_ledger_read_on_every_synthesize() -> None:
    """Inv 3: per-invocation fresh reads. Two synthesize() calls →
    two hot.md reads + two ledger reads. No process-lifetime cache."""
    row = _default_row()

    conn1 = _mock_conn(row=row)
    conn2 = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus", return_value=_make_opus_response()
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value="## Actively pressing\n- **ao**: x\n"
    ) as m_hot, patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ) as m_ledger, patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        synthesize(signal_id=14, conn=conn1)
        synthesize(signal_id=15, conn=conn2)

    assert m_hot.call_count == 2
    assert m_ledger.call_count == 2


def test_chanda_inv8_stub_paths_emit_silver_pipeline_never_gold_director() -> None:
    """Inv 8: voice: silver + author: pipeline on all stub paths —
    never director / gold."""
    for decision in (
        ClassifyDecision.SKIP_INBOX.value,
        ClassifyDecision.STUB_ONLY.value,
    ):
        row = _default_row(decision=decision)
        conn = _mock_conn(row=row)

        synthesize(signal_id=1, conn=conn)
        drafts = _sql_calls_matching(conn, "opus_draft_markdown")
        body = drafts[0][1][0]
        assert "voice: silver" in body
        assert "author: pipeline" in body
        assert "voice: gold" not in body
        assert "author: director" not in body


# --------------------------- transaction-boundary contract ---------------------------


def test_synthesize_happy_path_does_not_commit() -> None:
    """Caller-owns-commit: synthesize() doesn't commit on the happy
    FULL_SYNTHESIS path. Only the pre-raise terminal-state flips commit."""
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus", return_value=_make_opus_response()
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        synthesize(signal_id=20, conn=conn)

    # No internal commit on happy path — caller owns it.
    assert conn.commit.call_count == 0


def test_synthesize_stub_paths_do_not_commit() -> None:
    """Same contract for deterministic stubs."""
    for decision in (
        ClassifyDecision.SKIP_INBOX.value,
        ClassifyDecision.STUB_ONLY.value,
    ):
        row = _default_row(decision=decision)
        conn = _mock_conn(row=row)
        synthesize(signal_id=1, conn=conn)
        assert conn.commit.call_count == 0


def test_synthesize_r3_exhaust_commits_before_raise() -> None:
    """Terminal-state flip (opus_failed) commits so operator sees halt
    surface even if caller's rollback fires."""
    row = _default_row()
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus",
        side_effect=AnthropicUnavailableError("x"),
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ):
        with pytest.raises(AnthropicUnavailableError):
            synthesize(signal_id=21, conn=conn)

    assert conn.commit.call_count == 1


# --------------------------- STEP5_EMPTY_DRAFT_INVESTIGATION_1: emit_log observability ---------------------------
# Prior to this brief, kbl/steps/step5_opus.py did not import emit_log at
# all (PR #40 Part B Q4 finding: 0 rows with component='step5_opus' over
# 48h). These tests lock in the trace points that let a future brief
# bisect the 3 branches of the empty-draft class (transient error / Opus
# 200 empty content / capture bug).


def _emit_log_messages_at_level(
    m_emit: MagicMock, level: str
) -> list[tuple[str, int, str]]:
    """Flatten ``emit_log.call_args_list`` to ``(component, sid, message)``
    tuples for the given level."""
    out: list[tuple[str, int, str]] = []
    for call in m_emit.call_args_list:
        args = call.args
        if len(args) >= 4 and args[0] == level:
            out.append((args[1], args[2], args[3]))
    return out


def test_emit_log_skip_inbox_logs_entry_and_stub_written() -> None:
    """SKIP_INBOX path emits the ``step5 entry`` + ``stub draft written``
    INFO pair, and does NOT emit any WARN/ERROR."""
    row = _default_row(decision=ClassifyDecision.SKIP_INBOX.value)
    conn = _mock_conn(row=row)

    with patch("kbl.steps.step5_opus.emit_log") as m_emit, patch(
        "kbl.steps.step5_opus.call_opus"
    ):
        synthesize(signal_id=101, conn=conn)

    infos = _emit_log_messages_at_level(m_emit, "INFO")
    entry = [t for t in infos if t[2].startswith("step5 entry:")]
    stub_written = [t for t in infos if t[2].startswith("stub draft written:")]
    assert len(entry) == 1, f"expected 1 entry log, got {entry}"
    assert entry[0][0] == "step5_opus"
    assert entry[0][1] == 101
    assert "decision='skip_inbox'" in entry[0][2]
    assert len(stub_written) == 1, f"expected 1 stub_written log, got {stub_written}"
    assert "decision=skip_inbox" in stub_written[0][2]
    assert "draft_len=" in stub_written[0][2]
    # No WARN/ERROR on happy stub path.
    assert _emit_log_messages_at_level(m_emit, "WARN") == []
    assert _emit_log_messages_at_level(m_emit, "ERROR") == []


def test_emit_log_full_synthesis_happy_path_logs_trace_points() -> None:
    """FULL_SYNTHESIS happy path emits entry + opus call start + opus
    call return + draft written (all INFO). The opus-call-start log
    anchors attempt=0; opus-call-return carries stop_reason + output
    tokens for cost/behavior correlation."""
    row = _default_row(decision=ClassifyDecision.FULL_SYNTHESIS.value)
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus",
        return_value=_make_opus_response(text="real-draft-body", output_tokens=42),
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ), patch("kbl.steps.step5_opus.emit_log") as m_emit:
        synthesize(signal_id=202, conn=conn)

    infos = _emit_log_messages_at_level(m_emit, "INFO")
    prefixes = {t[2].split(":", 1)[0] for t in infos}
    # All four critical INFO anchors present.
    assert "step5 entry" in prefixes
    assert "opus call start" in prefixes
    assert "opus call return" in prefixes
    assert "draft written" in prefixes
    # All four carry signal_id=202 + component='step5_opus'.
    for comp, sid, _msg in infos:
        assert comp == "step5_opus"
        assert sid == 202
    # opus-call-return log includes stop_reason + output_tokens so a
    # future diagnostic can correlate with api_cost_log.
    ret_log = [t for t in infos if t[2].startswith("opus call return:")][0]
    assert "stop_reason='end_turn'" in ret_log[2]
    assert "output_tokens=42" in ret_log[2]
    # draft-written log carries the real length (no WARN because len > 0).
    written_log = [t for t in infos if t[2].startswith("draft written:")][0]
    assert "draft_len=" in written_log[2]
    assert _emit_log_messages_at_level(m_emit, "WARN") == []


def test_emit_log_full_synthesis_empty_response_warns_with_bisection_signal() -> None:
    """The CRITICAL test for the empty-draft class.

    When Opus returns 200 with empty ``content[0].text`` (content-filter,
    thinking-only block, etc.), Step 5 currently still writes ``''`` to
    ``opus_draft_markdown`` and advances to ``awaiting_finalize`` — Step 6
    then exhausts its retry ladder on ``body too short`` and the row
    lands at ``finalize_failed`` with content-lost state. Fixing that
    routing is out of scope for this brief (STEP5_EMPTY_DRAFT_INVESTIGATION_1
    is observability-only); but the log trace must surface the empty
    response at two points so a future brief can diagnose from kbl_log
    alone:

    1. WARN ``empty draft from Opus 200`` inside ``_fire_opus_with_r3``
       — exposes whether the Opus SDK returned a 200 with blank text.
    2. WARN ``wrote empty draft (draft_len=0)`` after the write — the
       explicit smoking-gun line the brief asked for.
    """
    row = _default_row(decision=ClassifyDecision.FULL_SYNTHESIS.value)
    conn = _mock_conn(row=row)

    with patch(
        "kbl.steps.step5_opus.call_opus",
        return_value=_make_opus_response(text="", output_tokens=0),
    ), patch(
        "kbl.steps.step5_opus.load_hot_md", return_value=None
    ), patch(
        "kbl.steps.step5_opus.load_recent_feedback", return_value=[]
    ), patch(
        "kbl.steps.step5_opus.load_gold_context_by_matter", return_value=""
    ), patch("kbl.steps.step5_opus.emit_log") as m_emit:
        result = synthesize(signal_id=303, conn=conn)

    # Pipeline advances (this is the bug — but out of scope to fix here).
    assert result.terminal_state == "awaiting_finalize"
    assert result.opus_response is not None
    assert result.opus_response.text == ""

    warns = _emit_log_messages_at_level(m_emit, "WARN")
    warn_prefixes = [t[2].split(":", 1)[0] for t in warns]
    # Both smoking-gun WARN lines present.
    assert "empty draft from Opus 200" in warn_prefixes
    assert "wrote empty draft (draft_len=0)" in warn_prefixes
    # Smoking-gun line carries stop_reason + output_tokens so a
    # replay-from-logs brief can bisect without re-running Opus.
    smoking = [
        t for t in warns
        if t[2].startswith("wrote empty draft (draft_len=0)")
    ][0]
    assert "stop_reason=" in smoking[2]
    assert "output_tokens=0" in smoking[2]
    assert smoking[0] == "step5_opus"
    assert smoking[1] == 303
