"""STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1 regression gates (2026-04-22).

Director's call after five single-bug patches landed in one day (#30-#35):
no more whack-a-mole. This module exhaustively pins the Step 5 stub →
Step 6 Pydantic-validation contract so every invariant in
:class:`kbl.schemas.silver.SilverFrontmatter` +
:class:`kbl.schemas.silver.SilverDocument` gets a regression gate, plus
the error-handler robustness fix (Axis 3) and the Opus user-prompt
``signal_id`` surfacing (Axis 5).

Matrix coverage (see ship report §2 for the readable version):

    * Axis 1 (field-level types) — ``title``, ``voice``, ``author``,
      ``created``, ``source_id``, ``primary_matter``, ``related_matters``,
      ``vedana``, ``status``. Each pinned by
      ``_yaml_roundtrip_then_validate``.
    * Axis 2 (cross-field invariants) — §4.2 null-primary ⇒ empty-related,
      no-primary-in-related dedupe, title shape (strip trailing period),
      ``_body_length`` 300 floor, ``_stub_status_matches_shape`` 600
      ceiling, slug-registry membership (retired slug demotion).
    * Axis 3 — fresh-connection error accounting survives a dead
      pipeline conn.
    * Axis 5 — ``signal_id`` placeholder lives in the user prompt + is
      passed to ``.format()``; system prompt names the §4.2 invariant.

Each test uses the shared fixture vault at
``tests/fixtures/vault_layer0/`` (slugs: ``ao``, ``movie``, ``gamma``).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from kbl import slug_registry
from kbl.schemas.silver import SilverDocument, SilverFrontmatter
from kbl.steps import step5_opus
from kbl.steps.step4_classify import ClassifyDecision
from kbl.steps.step5_opus import (
    _SignalInputs,
    _build_skip_inbox_stub,
    _build_stub_only_stub,
    _build_user_prompt,
    _normalize_stub_inputs,
    _normalize_stub_title,
    _PromptInputs,
    _R3_IDENTICAL,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VAULT = FIXTURES / "vault_layer0"

_AO = "ao"
_MOVIE = "movie"
_GAMMA = "gamma"
_RETIRED = "retired-slug-does-not-exist"


@pytest.fixture(autouse=True)
def _vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(VAULT))
    slug_registry.reload()
    step5_opus._reset_template_cache_for_tests()
    yield
    step5_opus._reset_template_cache_for_tests()
    slug_registry.reload()


# --------------------------- helpers ---------------------------


def _inputs(
    *,
    signal_id: int = 42,
    primary_matter=_AO,
    related_matters=None,
    vedana="routine",
    triage_summary="triage note",
    decision=ClassifyDecision.STUB_ONLY.value,
) -> _SignalInputs:
    return _SignalInputs(
        signal_id=signal_id,
        raw_content="raw",
        source="email",
        primary_matter=primary_matter,
        related_matters=list(related_matters or []),
        vedana=vedana,
        triage_summary=triage_summary,
        resolved_thread_paths=[],
        extracted_entities={},
        step_5_decision=decision,
    )


def _split_stub(stub: str) -> tuple[dict, str]:
    """Split a stub's frontmatter + body and parse the YAML. Mirrors
    Step 6's ``_split_frontmatter`` for the happy path."""
    assert stub.startswith("---\n"), "stub missing opening fence"
    after_open = stub[len("---\n"):]
    close_idx = after_open.find("\n---")
    assert close_idx >= 0, "stub missing closing fence"
    fm_text = after_open[:close_idx]
    body = after_open[close_idx + len("\n---"):].lstrip("\n")
    return yaml.safe_load(fm_text), body


def _yaml_roundtrip_then_validate(stub: str, *, signal_id: int) -> SilverDocument:
    """Step 5 stub → YAML parse → Step 6 telemetry inject →
    ``SilverDocument.model_validate``.

    Exercises the ENTIRE stub → Step 6 contract except the actual DB
    writes. Any invariant violation raises pydantic.ValidationError here.
    """
    fm_dict, body = _split_stub(stub)
    # Mirror Step 6's telemetry injection in finalize() lines ~615.
    fm_dict.setdefault("triage_score", 50)
    fm_dict.setdefault("triage_confidence", 0.7)
    fm_dict["source_id"] = str(signal_id)  # Step 6 force-override
    fm = SilverFrontmatter(**fm_dict)
    return SilverDocument(frontmatter=fm, body=body)


# ================================================================
# Axis 1 + 2: STUB FRONTMATTER + BODY INVARIANTS
# ================================================================
# The matrix: every stub, every SilverFrontmatter/SilverDocument
# validator, every cross-field invariant. If any fires, a bug
# regressed.


def test_skip_inbox_stub_validates_with_primary_slug_and_empty_related() -> None:
    stub = _build_skip_inbox_stub(
        _inputs(signal_id=101, primary_matter=_AO, related_matters=[])
    )
    doc = _yaml_roundtrip_then_validate(stub, signal_id=101)
    assert doc.frontmatter.primary_matter == _AO
    assert doc.frontmatter.related_matters == []
    assert doc.frontmatter.status == "stub_auto"


def test_stub_only_stub_validates_with_primary_slug_and_empty_related() -> None:
    stub = _build_stub_only_stub(
        _inputs(signal_id=102, primary_matter=_AO, related_matters=[])
    )
    doc = _yaml_roundtrip_then_validate(stub, signal_id=102)
    assert doc.frontmatter.primary_matter == _AO
    assert doc.frontmatter.status == "stub_auto"


# --------- Invariant §4.2: null-primary ⇒ empty-related ---------


def test_stub_with_null_primary_forces_empty_related_skip_inbox() -> None:
    """§4.2 — null primary + non-empty related is INVALID. Pre-audit,
    Step 1 could have populated ``related_matters`` on a signal that
    Step 4 then skip-inboxed (primary → null); the stub writer passed
    both through verbatim and blew up at Step 6 Pydantic validate.
    Post-audit, stub writer forces ``related=[]`` when ``primary=None``.
    """
    stub = _build_skip_inbox_stub(
        _inputs(
            signal_id=103,
            primary_matter=None,
            related_matters=[_AO, _MOVIE],  # would violate §4.2 raw
        )
    )
    fm, _ = _split_stub(stub)
    assert fm["primary_matter"] is None
    assert fm["related_matters"] == []
    # Pydantic round-trip validates cleanly.
    doc = _yaml_roundtrip_then_validate(stub, signal_id=103)
    assert doc.frontmatter.primary_matter is None
    assert doc.frontmatter.related_matters == []


def test_stub_with_null_primary_forces_empty_related_stub_only() -> None:
    stub = _build_stub_only_stub(
        _inputs(
            signal_id=104,
            primary_matter=None,
            related_matters=[_AO, _MOVIE],
        )
    )
    fm, _ = _split_stub(stub)
    assert fm["primary_matter"] is None
    assert fm["related_matters"] == []
    doc = _yaml_roundtrip_then_validate(stub, signal_id=104)
    assert doc.frontmatter.primary_matter is None


# --------- Invariant no-primary-in-related ---------


def test_stub_dedupes_primary_out_of_related() -> None:
    """The model validator rejects drafts where ``primary_matter`` shows
    up again in ``related_matters`` (Step 1's Layer 0 occasionally
    surfaced the primary into both lists — e.g. when a signal has two
    strong slugs and Step 4 chose one as primary). Stub writer now
    strips the duplicate so the downstream validator never sees it.
    """
    stub = _build_stub_only_stub(
        _inputs(
            signal_id=105,
            primary_matter=_AO,
            related_matters=[_AO, _MOVIE, _AO, _GAMMA],  # primary repeated twice + extras
        )
    )
    fm, _ = _split_stub(stub)
    assert fm["primary_matter"] == _AO
    # Order-preserving, primary stripped, duplicates removed.
    assert fm["related_matters"] == [_MOVIE, _GAMMA]
    _yaml_roundtrip_then_validate(stub, signal_id=105)


# --------- Slug registry membership (MatterSlug AfterValidator) ---------


def test_stub_filters_retired_related_slug_through_registry() -> None:
    """A slug that's not in the ACTIVE set (retired, typo'd, drift from
    a future producer) would fail ``_validate_slug_against_registry``.
    Stub writer drops non-active related slugs silently — the raw_text
    still lives in signal_queue.payload for audit."""
    stub = _build_stub_only_stub(
        _inputs(
            signal_id=106,
            primary_matter=_AO,
            related_matters=[_MOVIE, _RETIRED, _GAMMA],
        )
    )
    fm, _ = _split_stub(stub)
    assert _RETIRED not in fm["related_matters"]
    assert fm["related_matters"] == [_MOVIE, _GAMMA]
    _yaml_roundtrip_then_validate(stub, signal_id=106)


def test_stub_demotes_retired_primary_to_null_which_empties_related() -> None:
    """If the primary itself is a retired slug (Step 1 wrote a slug that's
    since been removed from slugs.yml ACTIVE), demote to null — which
    then cascades to empty related via §4.2. The alternative (crashing)
    strands the row; demotion keeps the pipeline flowing and surfaces
    the loss as an inbox-routed stub."""
    stub = _build_skip_inbox_stub(
        _inputs(
            signal_id=107,
            primary_matter=_RETIRED,
            related_matters=[_AO, _MOVIE],
        )
    )
    fm, _ = _split_stub(stub)
    assert fm["primary_matter"] is None
    assert fm["related_matters"] == []
    _yaml_roundtrip_then_validate(stub, signal_id=107)


# --------- Title shape invariants ---------


def test_stub_only_title_strips_trailing_period() -> None:
    """``_title_shape`` rejects titles ending in ``.``. The stub_only
    writer takes ``triage_summary[:60]`` which can and does end in a
    period when the triage writer produced a full sentence; rstrip
    clears it."""
    stub = _build_stub_only_stub(
        _inputs(
            signal_id=108,
            primary_matter=_AO,
            triage_summary="Director review required for AO settlement hearing.",
        )
    )
    fm, _ = _split_stub(stub)
    assert not fm["title"].endswith(".")
    _yaml_roundtrip_then_validate(stub, signal_id=108)


def test_stub_only_title_falls_back_when_summary_is_punctuation_only() -> None:
    """Pathological input: a triage_summary that's entirely whitespace
    + periods would rstrip to empty. Stub writer uses the fallback
    "triage noise-band signal" so ``_title_shape`` doesn't reject."""
    stub = _build_stub_only_stub(
        _inputs(
            signal_id=109,
            primary_matter=_AO,
            triage_summary=". . .  ",
        )
    )
    fm, _ = _split_stub(stub)
    assert fm["title"] == "triage noise-band signal"
    _yaml_roundtrip_then_validate(stub, signal_id=109)


def test_normalize_stub_title_caps_at_160_chars() -> None:
    """Title shape validator caps at 160 chars. Triage summaries are
    ``[:60]`` already so this is defense-in-depth for hardcoded titles
    or future callers."""
    normalized = _normalize_stub_title("x" * 300, fallback="fallback")
    assert len(normalized) <= 160


# --------- Vedana Literal coercion ---------


@pytest.mark.parametrize("bad_vedana", ["neutral", "", None, "unclear", "THREAT"])
def test_stub_coerces_invalid_vedana_to_routine(bad_vedana) -> None:
    """Step 4 is supposed to write threat/opportunity/routine but
    historical drift has surfaced "neutral", empty string, and NULL.
    Stub writer coerces anything outside the Literal set to "routine"
    so the frontmatter validates."""
    stub = _build_stub_only_stub(
        _inputs(signal_id=110, primary_matter=_AO, vedana=bad_vedana)
    )
    fm, _ = _split_stub(stub)
    assert fm["vedana"] == "routine"
    _yaml_roundtrip_then_validate(stub, signal_id=110)


@pytest.mark.parametrize("valid_vedana", ["threat", "opportunity", "routine"])
def test_stub_preserves_valid_vedana(valid_vedana) -> None:
    stub = _build_stub_only_stub(
        _inputs(signal_id=111, primary_matter=_AO, vedana=valid_vedana)
    )
    fm, _ = _split_stub(stub)
    assert fm["vedana"] == valid_vedana
    _yaml_roundtrip_then_validate(stub, signal_id=111)


# --------- Body length invariants ---------


def test_skip_inbox_stub_body_meets_300_char_floor() -> None:
    """``SilverDocument._body_length`` requires ``len(body) >= 300``.
    Pre-audit, skip_inbox emitted ~240 chars; pre-audit stub_only with
    a short triage_summary emitted <150 chars. Both failed at Step 6
    Pydantic validate (the failure surfaced post-PR-#34 once the YAML
    parse layer stopped being the first blocker). Padding helper now
    guarantees the floor."""
    stub = _build_skip_inbox_stub(_inputs(signal_id=112, primary_matter=_AO))
    _, body = _split_stub(stub)
    assert len(body) >= 300, f"skip_inbox stub body too short: {len(body)}"


def test_stub_only_stub_body_meets_300_char_floor_even_with_empty_triage() -> None:
    stub = _build_stub_only_stub(
        _inputs(signal_id=113, primary_matter=_AO, triage_summary="")
    )
    _, body = _split_stub(stub)
    assert len(body) >= 300, f"stub_only body too short: {len(body)}"


def test_stub_body_stays_under_600_char_ceiling() -> None:
    """``SilverDocument._stub_status_matches_shape``: status set ⇒ body
    ≤ 600. Cap helper trims on word boundary when triage_summary is
    large enough to blow past the ceiling."""
    long_summary = "x " * 400  # 800 chars → would blow the cap
    stub = _build_stub_only_stub(
        _inputs(signal_id=114, primary_matter=_AO, triage_summary=long_summary)
    )
    _, body = _split_stub(stub)
    assert len(body) <= 600, f"stub body exceeds cap: {len(body)}"
    # Must still validate post-cap.
    _yaml_roundtrip_then_validate(stub, signal_id=114)


# --------- Body forbidden markers (R18 backup) ---------


def test_stub_bodies_never_emit_forbidden_gold_self_promotion_markers() -> None:
    """``_no_gold_self_promotion`` rejects any body containing
    ``voice: gold`` or ``author: director`` verbatim. Stub filler prose
    was rephrased to avoid these literals — this test locks the
    prohibition so future filler edits can't regress."""
    for builder in (_build_skip_inbox_stub, _build_stub_only_stub):
        stub = builder(_inputs(signal_id=115, primary_matter=_AO))
        _, body = _split_stub(stub)
        low = body.lower()
        assert "voice: gold" not in low
        assert "voice:gold" not in low
        assert "author: director" not in low
        assert "author:director" not in low


# --------- source_id: str invariant (covered by existing tests too) ---------


def test_normalize_stub_inputs_returns_three_tuple() -> None:
    """Unit test for the helper itself — useful for tracing if this
    helper ever gets wrapped / replaced."""
    primary, related, vedana = _normalize_stub_inputs(
        _inputs(
            signal_id=1,
            primary_matter=_AO,
            related_matters=[_AO, _MOVIE, _RETIRED],
            vedana="neutral",
        )
    )
    assert primary == _AO
    assert related == [_MOVIE]  # primary + retired both stripped
    assert vedana == "routine"  # "neutral" coerced


# ================================================================
# Axis 5: Opus user prompt surfaces signal_id
# ================================================================


def test_opus_user_prompt_template_contains_signal_id_placeholder() -> None:
    """Pre-audit the user prompt had no ``{signal_id}``; FULL_SYNTHESIS
    Opus had no way to emit the correct source_id and relied on Step 6's
    override (belt-only). Post-audit both layers (producer + override)
    exist."""
    template = step5_opus._load_user_template()
    assert "{signal_id}" in template, (
        "Opus user prompt is missing {signal_id} placeholder — "
        "FULL_SYNTHESIS can't surface the DB-authoritative id to the model"
    )


def test_build_user_prompt_renders_signal_id_without_keyerror() -> None:
    """``_build_user_prompt`` passes ``signal_id`` to the template
    ``.format()`` call; a missing kwarg would raise KeyError. Lock it."""
    inputs = _inputs(signal_id=9_999_001, primary_matter=_AO)
    prompt_inputs = _PromptInputs(
        gold_block="(no prior Gold)",
        hot_md_block="(no current-priorities cache)",
        ledger_block="(no recent Director actions)",
    )
    rendered = _build_user_prompt(
        inputs, prompt_inputs, attempt=_R3_IDENTICAL
    )
    # The id shows up as a decimal literal in the rendered user block.
    assert "9999001" in rendered


def test_opus_system_prompt_names_null_primary_implies_empty_related_invariant() -> None:
    """System prompt must teach Opus the §4.2 invariant so
    FULL_SYNTHESIS drafts don't fail Step 6 Pydantic validate. Lock it."""
    template = step5_opus._load_system_template()
    low = template.lower()
    # Phrasing is flexible — look for the load-bearing noun phrases.
    assert "null" in low and "related_matters" in low
    assert "empty" in low or "[]" in low
    # Explicit §4.2 mention keeps the thread back to the schema.
    assert "§4.2" in template or "4.2" in template or "null primary" in low


# ================================================================
# Axis 3: _route_validation_failure uses a fresh connection
# ================================================================


def _make_dead_conn() -> MagicMock:
    """Pipeline ``conn`` that raises on every cursor/execute call —
    models Neon's 'SSL connection has been closed unexpectedly' +
    'connection already closed' cascade that motivated Axis 3.
    """
    import psycopg2

    conn = MagicMock()

    def _raise_closed(*_a, **_kw):
        raise psycopg2.InterfaceError("connection already closed")

    conn.cursor.side_effect = _raise_closed
    conn.commit.side_effect = _raise_closed
    conn.rollback.side_effect = _raise_closed
    return conn


def _make_tracking_fresh_conn() -> MagicMock:
    """Fresh ``conn`` with the same tracking shape ``_mock_conn`` uses
    in test_step6_finalize — records SQL + serves a scripted fetchone."""
    fresh = MagicMock()
    calls: list = []

    def _make_cursor():
        cur = MagicMock()

        def _execute(sql, params=None):
            calls.append((sql, params))
            s = sql.lower()
            if "finalize_retry_count" in s and "returning" in s:
                cur.fetchone.return_value = (1,)
            else:
                cur.fetchone.return_value = None

        cur.execute.side_effect = _execute
        return cur

    def _cursor():
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_cursor()
        ctx.__exit__.return_value = False
        return ctx

    fresh.cursor.side_effect = _cursor
    fresh._calls = calls
    return fresh


def test_route_validation_failure_uses_fresh_conn_for_state_writes() -> None:
    """Axis 3 contract: ``_route_validation_failure`` must NOT touch the
    pipeline ``conn`` passed into ``finalize()`` for error accounting.
    It opens a fresh short-lived conn via ``kbl.db.get_conn`` and does
    all the retry-bump + terminal-state-flip + commit there.

    Regression: pre-audit, the retry-bump UPDATE ran on the pipeline
    ``conn``; if that conn had been silently reaped by Neon during a
    long Step 5 Opus call, the UPDATE raised
    ``psycopg2.InterfaceError: connection already closed`` and the row
    stranded at ``finalize_running`` forever.
    """
    from contextlib import contextmanager

    from kbl.exceptions import FinalizationError
    from kbl.steps.step6_finalize import _SignalRow, _route_validation_failure

    fresh = _make_tracking_fresh_conn()

    @contextmanager
    def _fake_get_conn():
        yield fresh

    row = _SignalRow(
        signal_id=9001,
        opus_draft_markdown="dummy",
        step_5_decision="stub_only",
        triage_score=50,
        triage_confidence=0.5,
        finalize_retry_count=0,
    )

    with patch(
        "kbl.steps.step6_finalize.get_conn", side_effect=_fake_get_conn
    ):
        _route_validation_failure(row, error_count=1)

    # All writes landed on the fresh conn.
    assert fresh.commit.call_count == 1
    sqls = " ".join(c[0].lower() for c in fresh._calls)
    assert "finalize_retry_count" in sqls
    assert "update signal_queue" in sqls
    # And the fresh conn was used at least once.
    assert fresh.cursor.call_count >= 1


def test_route_validation_failure_swallows_fresh_conn_exception() -> None:
    """Belt-and-suspenders: if the fresh connection ALSO fails (DB is
    entirely down), the error handler must not mask the caller's
    pending ``FinalizationError`` raise by throwing its own exception.
    We log to stderr and return — caller still sees the ValidationError
    that got us here.
    """
    from kbl.steps.step6_finalize import _SignalRow, _route_validation_failure

    row = _SignalRow(
        signal_id=9002,
        opus_draft_markdown="dummy",
        step_5_decision="stub_only",
        triage_score=50,
        triage_confidence=0.5,
        finalize_retry_count=0,
    )

    with patch(
        "kbl.steps.step6_finalize.get_conn",
        side_effect=RuntimeError("DB entirely unreachable"),
    ):
        # Should NOT raise — even though get_conn() itself blew up,
        # error accounting is best-effort and must never crash the caller.
        _route_validation_failure(row, error_count=1)


def test_finalize_with_dead_primary_conn_still_records_failure_on_fresh_conn() -> None:
    """End-to-end: a stub draft that fails Pydantic validation (bad
    vedana through a bypass path — see below) + a pipeline ``conn``
    whose cursor raises at retry-bump time. Post-audit the fresh-conn
    path still records the retry bump + terminal flip.

    Construction note: the main pipeline ``conn`` IS used for
    ``_fetch_signal_row`` + ``_mark_running`` at the top of
    ``finalize()``; those succeed here. Only the post-ValidationError
    ``_route_validation_failure`` needs isolation. We build a main conn
    that serves the initial SELECT but "dies" before the error path
    runs — simulated by a per-call counter.
    """
    from kbl.exceptions import FinalizationError
    from kbl.steps.step6_finalize import finalize

    # --- Build a draft that reaches Pydantic validation then fails ---
    draft = (
        "---\n"
        "title: bad vedana stub\n"
        "voice: silver\n"
        "author: pipeline\n"
        "created: 2026-04-22T12:00:00Z\n"
        "source_id: '9003'\n"
        f"primary_matter: {_AO}\n"
        "related_matters: []\n"
        "vedana: neutral\n"  # not in Literal — ValidationError
        "status: stub_auto\n"
        "---\n\n"
    ) + ("A" * 400) + "\n"

    # --- Main pipeline conn: SELECT works, all subsequent execute raises ---
    import psycopg2

    main_conn = MagicMock()
    state = {"selects": 0}

    def _make_main_cursor():
        cur = MagicMock()

        def _execute(sql, params=None):
            s = sql.lower()
            if "alter table" in s:
                return None
            if "select" in s and "from signal_queue" in s:
                state["selects"] += 1
                cur.fetchone.return_value = (draft, "stub_only", 50, 0.7, 0)
                return None
            if "update signal_queue" in s and "mark running" not in s:
                # Permit _mark_running to pass; raise on any later update.
                if state["selects"] >= 1:
                    # _mark_running is the first update after SELECT.
                    if not state.get("mark_running_seen"):
                        state["mark_running_seen"] = True
                        return None
                    raise psycopg2.InterfaceError(
                        "connection already closed (simulated)"
                    )
            return None

        cur.execute.side_effect = _execute
        return cur

    def _main_cursor():
        ctx = MagicMock()
        ctx.__enter__.return_value = _make_main_cursor()
        ctx.__exit__.return_value = False
        return ctx

    main_conn.cursor.side_effect = _main_cursor

    # --- Fresh conn: healthy, tracks retry + terminal-state UPDATE ---
    fresh = _make_tracking_fresh_conn()

    from contextlib import contextmanager

    @contextmanager
    def _fake_get_conn():
        yield fresh

    with patch(
        "kbl.steps.step6_finalize.get_conn", side_effect=_fake_get_conn
    ), pytest.raises(FinalizationError, match="validation failed"):
        finalize(signal_id=9003, conn=main_conn)

    # The fresh conn handled the error accounting — retry bump UPDATE
    # + opus_failed state flip both landed, and it committed once.
    assert fresh.commit.call_count == 1
    sqls = " ".join(c[0].lower() for c in fresh._calls)
    assert "finalize_retry_count" in sqls
    opus_failed_updates = [
        c for c in fresh._calls if c[1] == ("opus_failed", 9003)
    ]
    assert opus_failed_updates, "fresh conn did not flip state to opus_failed"
