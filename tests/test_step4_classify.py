"""Tests for kbl.steps.step4_classify — deterministic policy classifier."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import ClassifyError
from kbl.steps import step4_classify
from kbl.steps.step4_classify import (
    ClassifyDecision,
    _evaluate_rules,
    _load_allowed_scope,
    _parse_hot_md_active,
    classify,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Strip all Step 4 env vars so tests control threshold / noise band
    / scope override deterministically. Callers opt in via setenv."""
    for var in (
        "KBL_PIPELINE_TRIAGE_THRESHOLD",
        "KBL_STEP4_NOISE_BAND",
        "KBL_MATTER_SCOPE_ALLOWED",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# --------------------------- _parse_hot_md_active ---------------------------


def test_parse_hot_md_extracts_active_slugs() -> None:
    hot = (
        "# hot\n"
        "## Actively pressing\n"
        "- **movie**: hotel\n"
        "- **ao**: capital\n"
        "- **cupial**: litigation\n"
        "\n"
        "## Backburner\n"
        "- **kempinski**: deprioritised\n"
    )
    assert _parse_hot_md_active(hot) == frozenset({"movie", "ao", "cupial"})


def test_parse_hot_md_none_returns_empty() -> None:
    assert _parse_hot_md_active(None) == frozenset()


def test_parse_hot_md_empty_string_returns_empty() -> None:
    assert _parse_hot_md_active("") == frozenset()


def test_parse_hot_md_missing_active_section_returns_empty() -> None:
    """Inv 1 zero-Gold: without the section header the allowlist is empty
    — Rule 1 then fires for every non-null matter."""
    hot = "# hot\n\nSome intro text but no section header.\n"
    assert _parse_hot_md_active(hot) == frozenset()


def test_parse_hot_md_case_insensitive_header() -> None:
    hot = "## ACTIVELY Pressing\n- **movie**: yes\n"
    assert _parse_hot_md_active(hot) == frozenset({"movie"})


def test_parse_hot_md_supports_dashes_and_underscores_in_slugs() -> None:
    hot = (
        "## Actively pressing\n"
        "- **hagenauer-rg7**: live\n"
        "- **ao_holding**: capital\n"
    )
    assert _parse_hot_md_active(hot) == frozenset(
        {"hagenauer-rg7", "ao_holding"}
    )


def test_parse_hot_md_stops_at_next_h2() -> None:
    """Backburner / archive matters must NOT leak into the active set."""
    hot = (
        "## Actively pressing\n"
        "- **movie**: hot\n"
        "## Archive\n"
        "- **legacy_matter**: cold\n"
    )
    assert _parse_hot_md_active(hot) == frozenset({"movie"})


# ---- STEP4_HOT_MD_PARSER_FIX_1 regression set (2026-04-22) ----
#
# Before the fix: the live hot.md header carried a parenthetical suffix
# (`## Actively pressing (elevate — deadline/decision this week)`) and
# the section regex anchored on `\s*$` immediately after "pressing" — so
# the section match returned `None`, every scope lookup returned an empty
# set, and Rule 1 rejected every signal as out-of-scope. Combo bullets
# (`**lilienmatt + annaberg + aukera**:`) were also invisible because the
# slug regex rejected whitespace and `+` inside the `**...**` fences.
#
# These 5 tests lock the fix in: parenthetical headers parse, bare headers
# still parse (backward compat), single-slug bullets still parse, combo
# bullets tokenize into their component slugs, and mixed bodies yield the
# correct union.


def test_parse_hot_md_live_parenthetical_header() -> None:
    """Live hot.md heading shape — parenthetical suffix must not kill the
    section match. Prior behavior: returned empty set."""
    hot = (
        "## Actively pressing (elevate — deadline/decision this week)\n"
        "- **hagenauer-rg7**: GC takeover\n"
        "- **ao**: capital call\n"
    )
    assert _parse_hot_md_active(hot) == frozenset({"hagenauer-rg7", "ao"})


def test_parse_hot_md_bare_header_still_parses() -> None:
    """Backward compat — the prior-shape header (no parenthetical)
    continues to parse identically post-fix."""
    hot = (
        "## Actively pressing\n"
        "- **hagenauer-rg7**: GC takeover\n"
        "- **ao**: capital call\n"
    )
    assert _parse_hot_md_active(hot) == frozenset({"hagenauer-rg7", "ao"})


def test_parse_hot_md_single_slug_bullet_backward_compat() -> None:
    """Single-slug bullets across a mix of dash/underscore slugs must
    round-trip unchanged — the combo-bullet split on `+` must not alter
    slugs that don't contain a `+`."""
    hot = (
        "## Actively pressing\n"
        "- **hagenauer-rg7**: live\n"
        "- **mo-vie-am**: live\n"
        "- **ao_holding**: live\n"
    )
    assert _parse_hot_md_active(hot) == frozenset(
        {"hagenauer-rg7", "mo-vie-am", "ao_holding"}
    )


def test_parse_hot_md_multi_slug_combo_bullet() -> None:
    """Hot.md line 13 documents `slug1 + slug2` as an intentional combo
    bullet format — this is the format in live use for `lilienmatt +
    annaberg + aukera`, `nvidia + corinthia`, `aukera + mo-vie-am`. The
    parser must tokenize on `+` and yield each slug individually."""
    hot = (
        "## Actively pressing\n"
        "- **lilienmatt + annaberg + aukera**: restructure\n"
    )
    assert _parse_hot_md_active(hot) == frozenset(
        {"lilienmatt", "annaberg", "aukera"}
    )


def test_parse_hot_md_mixed_single_and_multi_slug_bullets() -> None:
    """Live hot.md body shape — single + combo bullets interleaved, with
    the live parenthetical header. Union of all tokens across bullet
    shapes, next-H2 boundary honored."""
    hot = (
        "## Actively pressing (elevate — deadline/decision this week)\n"
        "- **hagenauer-rg7**: GC takeover\n"
        "- **ao**: capital call\n"
        "- **nvidia + corinthia**: proposal\n"
        "- **mo-vie-am**: residence offer\n"
        "- **lilienmatt + annaberg + aukera**: restructure\n"
        "- **cap-ferrat**: BDO questions\n"
        "\n"
        "## Watch list (elevate on any mention)\n"
        "- **leak_slug**: must not appear\n"
    )
    assert _parse_hot_md_active(hot) == frozenset(
        {
            "hagenauer-rg7",
            "ao",
            "nvidia",
            "corinthia",
            "mo-vie-am",
            "lilienmatt",
            "annaberg",
            "aukera",
            "cap-ferrat",
        }
    )


# --------------------------- _load_allowed_scope ---------------------------


def test_load_allowed_scope_union_of_hot_md_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "cupial, extra_override")
    with patch(
        "kbl.steps.step4_classify.load_hot_md",
        return_value="## Actively pressing\n- **movie**: yes\n",
    ):
        scope = _load_allowed_scope()
    assert scope == frozenset({"movie", "cupial", "extra_override"})


def test_load_allowed_scope_hot_md_only_when_env_unset() -> None:
    with patch(
        "kbl.steps.step4_classify.load_hot_md",
        return_value="## Actively pressing\n- **movie**: yes\n- **ao**: yes\n",
    ):
        assert _load_allowed_scope() == frozenset({"movie", "ao"})


def test_load_allowed_scope_env_only_when_hot_md_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "movie, ao")
    with patch("kbl.steps.step4_classify.load_hot_md", return_value=None):
        assert _load_allowed_scope() == frozenset({"movie", "ao"})


def test_load_allowed_scope_both_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero-Gold: empty env + empty hot.md → empty scope. Under that
    state every signal with a non-null primary_matter falls into Rule 1
    (SKIP_INBOX). Brief §4 ratified behavior."""
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "")
    with patch("kbl.steps.step4_classify.load_hot_md", return_value=None):
        assert _load_allowed_scope() == frozenset()


def test_load_allowed_scope_env_whitespace_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spaces and empty tokens inside the comma-separated env value are
    stripped — `"  , movie, , ao,"` → {movie, ao}."""
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "  , movie, , ao,")
    with patch("kbl.steps.step4_classify.load_hot_md", return_value=None):
        assert _load_allowed_scope() == frozenset({"movie", "ao"})


def test_load_allowed_scope_reads_hot_md_on_every_call() -> None:
    """Inv 3 anchor: hot.md is read fresh per ``classify()`` invocation,
    NOT cached module-level. The Director's edits propagate to the next
    signal without a process restart."""
    with patch("kbl.steps.step4_classify.load_hot_md", return_value=None) as m_hot:
        _load_allowed_scope()
        _load_allowed_scope()
        _load_allowed_scope()
    assert m_hot.call_count == 3


# --------------------------- _evaluate_rules ---------------------------


def _rule_kwargs(**overrides: Any) -> dict[str, Any]:
    """Base kwargs for ``_evaluate_rules`` — override specific fields."""
    defaults: dict[str, Any] = dict(
        triage_score=60,
        primary_matter="movie",
        related_matters=[],
        resolved_thread_paths=[],
        allowed_scope=frozenset({"movie", "ao"}),
        threshold=40,
        noise_band=5,
    )
    defaults.update(overrides)
    return defaults


def test_rule1_matter_not_in_scope_skip_inbox() -> None:
    """§4.5 Rule 1: primary_matter outside allowlist → SKIP_INBOX."""
    decision, hint = _evaluate_rules(**_rule_kwargs(primary_matter="unknown"))
    assert decision is ClassifyDecision.SKIP_INBOX
    assert hint is False


def test_rule1_null_primary_matter_skip_inbox() -> None:
    """``primary_matter IS NULL`` is treated as outside the scope (can't
    be in the allowlist) and routes to inbox."""
    decision, hint = _evaluate_rules(**_rule_kwargs(primary_matter=None))
    assert decision is ClassifyDecision.SKIP_INBOX
    assert hint is False


def test_rule2_score_in_noise_band_stub_only() -> None:
    """§4.5 Rule 2: threshold ≤ score < threshold+noise_band → STUB_ONLY."""
    decision, hint = _evaluate_rules(**_rule_kwargs(triage_score=43))
    assert decision is ClassifyDecision.STUB_ONLY
    assert hint is False


def test_rule2_boundary_at_threshold_is_stub() -> None:
    """Exactly at threshold (score=40, band=5): 40 < 45 → STUB_ONLY."""
    decision, _ = _evaluate_rules(**_rule_kwargs(triage_score=40))
    assert decision is ClassifyDecision.STUB_ONLY


def test_rule2_boundary_above_noise_band_falls_through() -> None:
    """score = threshold + noise_band (45) → not STUB_ONLY; falls to
    Rule 3+ → FULL_SYNTHESIS."""
    decision, _ = _evaluate_rules(**_rule_kwargs(triage_score=45))
    assert decision is ClassifyDecision.FULL_SYNTHESIS


def test_rule3_empty_paths_empty_related_full_synthesis_new_arc() -> None:
    """§4.5 Rule 3: no thread history + no related matters → new arc
    FULL_SYNTHESIS, no cross-link hint."""
    decision, hint = _evaluate_rules(
        **_rule_kwargs(resolved_thread_paths=[], related_matters=[])
    )
    assert decision is ClassifyDecision.FULL_SYNTHESIS
    assert hint is False


def test_rule4_empty_paths_with_related_sets_cross_link_hint() -> None:
    """§4.5 Rule 4: new arc but related_matters populated → FULL_SYNTHESIS
    with the cross-link hint flipped TRUE for Step 6."""
    decision, hint = _evaluate_rules(
        **_rule_kwargs(
            resolved_thread_paths=[],
            related_matters=["ao", "cupial"],
        )
    )
    assert decision is ClassifyDecision.FULL_SYNTHESIS
    assert hint is True


def test_rule5_with_resolved_paths_is_continuation() -> None:
    """§4.5 Rule 5: resolved_thread_paths non-empty → continuation;
    cross-link hint STAYS FALSE even if related_matters also populated
    (prior arc already owns the signal)."""
    decision, hint = _evaluate_rules(
        **_rule_kwargs(
            resolved_thread_paths=["wiki/movie/2026-04-10_notes.md"],
            related_matters=["ao"],
        )
    )
    assert decision is ClassifyDecision.FULL_SYNTHESIS
    assert hint is False


def test_rule0_below_threshold_is_unreachable_and_raises() -> None:
    """Pipeline invariant: Step 1 routes below-threshold signals to
    ``routed_inbox``; they should never reach Step 4. If Step 4 sees
    one, ``ClassifyError`` halts the signal rather than silently
    picking a decision."""
    with pytest.raises(ClassifyError, match="pipeline invariant violated"):
        _evaluate_rules(**_rule_kwargs(triage_score=20))


def test_rule_precedence_scope_before_noise_band() -> None:
    """Rule 1 fires before Rule 2 — out-of-scope matter with a low
    score still routes to SKIP_INBOX, not STUB_ONLY."""
    decision, _ = _evaluate_rules(
        **_rule_kwargs(triage_score=42, primary_matter="unknown")
    )
    assert decision is ClassifyDecision.SKIP_INBOX


# --------------------------- end-to-end classify() ---------------------------


def _classify_conn(
    triage_score: int = 60,
    primary_matter: str | None = "movie",
    related_matters: list[str] | None = None,
    resolved_thread_paths: list[str] | None = None,
) -> MagicMock:
    """Mock connection whose cursor serves the SELECT + records all
    subsequent writes."""
    conn = MagicMock()
    call_sequence: list[tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            call_sequence.append((sql, params))
            sql_lower = sql.lower()
            if "from signal_queue" in sql_lower and "select" in sql_lower:
                cur.fetchone.return_value = (
                    triage_score,
                    primary_matter,
                    related_matters if related_matters is not None else [],
                    resolved_thread_paths
                    if resolved_thread_paths is not None
                    else [],
                )
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


def _patch_scope(*slugs: str):
    """Install ``_load_allowed_scope`` patch for a given set of slugs."""
    return patch(
        "kbl.steps.step4_classify._load_allowed_scope",
        return_value=frozenset(slugs),
    )


def test_classify_full_synthesis_happy_path_writes_and_advances() -> None:
    conn = _classify_conn(triage_score=75, primary_matter="movie")
    with _patch_scope("movie", "ao"):
        result = classify(signal_id=42, conn=conn)

    assert result is ClassifyDecision.FULL_SYNTHESIS

    sqls = [s.lower() for s, _ in conn._calls]
    # Running status written BEFORE the result UPDATE.
    assert any(
        "update signal_queue set status = %s where id = %s" in s for s in sqls
    )
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    assert len(decision_rows) == 1
    _, params = decision_rows[0]
    decision_value, cross_link_hint, next_state, sid = params
    assert decision_value == "full_synthesis"
    assert cross_link_hint is False
    assert next_state == "awaiting_opus"
    assert sid == 42


def test_classify_cross_link_hint_on_rule4() -> None:
    """Rule 4 fires cross_link_hint=TRUE — asserted at the SQL params
    level so downstream Step 6 can filter without re-deriving."""
    conn = _classify_conn(
        triage_score=80,
        primary_matter="movie",
        related_matters=["ao", "cupial"],
        resolved_thread_paths=[],
    )
    with _patch_scope("movie", "ao", "cupial"):
        classify(signal_id=1, conn=conn)

    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    _, params = decision_rows[0]
    decision_value, cross_link_hint, *_ = params
    assert decision_value == "full_synthesis"
    assert cross_link_hint is True


def test_classify_rule3_new_arc_hint_false() -> None:
    conn = _classify_conn(
        triage_score=70,
        primary_matter="movie",
        related_matters=[],
        resolved_thread_paths=[],
    )
    with _patch_scope("movie"):
        classify(signal_id=2, conn=conn)
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    _, params = decision_rows[0]
    _, cross_link_hint, *_ = params
    assert cross_link_hint is False


def test_classify_skip_inbox_when_matter_out_of_scope(caplog: pytest.LogCaptureFixture) -> None:
    conn = _classify_conn(triage_score=80, primary_matter="unknown")
    with _patch_scope("movie", "ao"), caplog.at_level("INFO"):
        result = classify(signal_id=5, conn=conn)

    assert result is ClassifyDecision.SKIP_INBOX
    # §4.5 logging — Layer 2 gate block INFO message.
    log_msgs = [
        r.getMessage() for r in caplog.records if r.name.startswith("kbl.steps")
    ]
    assert any("layer2_blocked" in m and "'unknown'" in m for m in log_msgs)

    # Still advances to awaiting_opus — Step 5 writes a stub for
    # skip_inbox rows so the pipeline keeps flowing (Inv 6).
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    _, params = decision_rows[0]
    assert params[0] == "skip_inbox"
    assert params[2] == "awaiting_opus"


def test_classify_stub_only_when_in_noise_band() -> None:
    conn = _classify_conn(triage_score=42, primary_matter="movie")
    with _patch_scope("movie"):
        result = classify(signal_id=7, conn=conn)
    assert result is ClassifyDecision.STUB_ONLY
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    _, params = decision_rows[0]
    assert params[0] == "stub_only"
    assert params[1] is False


def test_classify_below_threshold_raises_and_marks_failed() -> None:
    """``ClassifyError`` → state flips to ``classify_failed`` BEFORE the
    exception bubbles, so the operator can see the halt surface."""
    conn = _classify_conn(triage_score=20, primary_matter="movie")
    with _patch_scope("movie"):
        with pytest.raises(ClassifyError, match="pipeline invariant violated"):
            classify(signal_id=99, conn=conn)

    # A status UPDATE to classify_failed must be present.
    failed_rows = [
        c for c in conn._calls
        if "update signal_queue set status = %s" in c[0].lower()
        and c[1] == ("classify_failed", 99)
    ]
    assert failed_rows
    # No decision write on failure.
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    assert not decision_rows


def test_classify_cross_link_only_guard_raises_and_marks_failed() -> None:
    """Phase 2 reserved-decision guard — B2 PR #13 S1.

    No Phase 1 rule currently maps to ``CROSS_LINK_ONLY``; the guard in
    ``classify()`` catches the case where a future table edit (or a
    buggy monkeypatch) emits it anyway, then halts the signal the same
    way as any other pipeline-invariant violation: flip status to
    ``classify_failed`` BEFORE raising ``ClassifyError``. Without this
    test the guard is unreachable code that CI can't validate.
    """
    conn = _classify_conn(triage_score=80, primary_matter="movie")
    with _patch_scope("movie"), patch(
        "kbl.steps.step4_classify._evaluate_rules",
        return_value=(ClassifyDecision.CROSS_LINK_ONLY, False),
    ):
        with pytest.raises(ClassifyError, match="CROSS_LINK_ONLY"):
            classify(signal_id=77, conn=conn)

    # Status flip happened BEFORE the raise — same pattern as the
    # below-threshold path in `test_classify_below_threshold_raises_...`.
    failed_rows = [
        c for c in conn._calls
        if "update signal_queue set status = %s" in c[0].lower()
        and c[1] == ("classify_failed", 77)
    ]
    assert failed_rows
    # Guard fires AFTER _evaluate_rules returns, so no decision row
    # should be written.
    decision_rows = [
        c for c in conn._calls
        if "update signal_queue set" in c[0].lower()
        and "step_5_decision" in c[0].lower()
    ]
    assert not decision_rows


def test_classify_signal_not_found_raises() -> None:
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    conn.cursor.return_value = ctx

    with pytest.raises(LookupError, match="row not found"):
        classify(signal_id=999, conn=conn)


def test_classify_reads_hot_md_on_every_invocation() -> None:
    """Inv 3 end-to-end: every classify() triggers exactly one
    ``load_hot_md`` call (via ``_load_allowed_scope``). No
    process-lifetime caching."""
    conn1 = _classify_conn(triage_score=70, primary_matter="movie")
    conn2 = _classify_conn(triage_score=70, primary_matter="movie")
    with patch(
        "kbl.steps.step4_classify.load_hot_md",
        return_value="## Actively pressing\n- **movie**: yes\n",
    ) as m_hot:
        classify(signal_id=1, conn=conn1)
        classify(signal_id=2, conn=conn2)
    assert m_hot.call_count == 2


def test_classify_null_triage_score_treated_as_zero_and_raises() -> None:
    """Defensive: NULL ``triage_score`` → coerced to 0 → Rule 0 fires
    → ClassifyError. Prevents silent FULL_SYNTHESIS on a broken row."""
    conn = _classify_conn(triage_score=None, primary_matter="movie")  # type: ignore[arg-type]
    with _patch_scope("movie"):
        with pytest.raises(ClassifyError):
            classify(signal_id=1, conn=conn)


# --------------------------- env parsing robustness ---------------------------


def test_noise_band_env_malformed_falls_back(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("KBL_STEP4_NOISE_BAND", "abc")
    with caplog.at_level("WARNING"):
        assert step4_classify._get_noise_band() == step4_classify._DEFAULT_NOISE_BAND
    assert any("invalid KBL_STEP4_NOISE_BAND" in r.getMessage() for r in caplog.records)


def test_noise_band_env_int_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_STEP4_NOISE_BAND", "12")
    assert step4_classify._get_noise_band() == 12


def test_threshold_env_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_PIPELINE_TRIAGE_THRESHOLD", "70")
    assert step4_classify._get_triage_threshold() == 70


def test_threshold_env_malformed_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBL_PIPELINE_TRIAGE_THRESHOLD", "not-a-number")
    assert step4_classify._get_triage_threshold() == step4_classify._DEFAULT_TRIAGE_THRESHOLD


def test_scope_env_unset_or_empty_yields_empty_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset — default fixture already deletes the var.
    assert step4_classify._get_scope_env_override() == frozenset()
    # Empty string.
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "")
    assert step4_classify._get_scope_env_override() == frozenset()
    # Only whitespace / commas.
    monkeypatch.setenv("KBL_MATTER_SCOPE_ALLOWED", "  , , ,")
    assert step4_classify._get_scope_env_override() == frozenset()


# --------------------------- module surface ---------------------------


def test_module_public_surface() -> None:
    for name in ("ClassifyDecision", "classify"):
        assert hasattr(step4_classify, name)


def test_classify_decision_enum_values_stable() -> None:
    assert ClassifyDecision.FULL_SYNTHESIS.value == "full_synthesis"
    assert ClassifyDecision.STUB_ONLY.value == "stub_only"
    assert ClassifyDecision.CROSS_LINK_ONLY.value == "cross_link_only"
    assert ClassifyDecision.SKIP_INBOX.value == "skip_inbox"
    # str-mixin compares against plain strings.
    assert ClassifyDecision.FULL_SYNTHESIS == "full_synthesis"


def test_status_values_are_in_canonical_set() -> None:
    """State-machine values written by Step 4 must live in the 34-value
    CHECK set widened by PR #12."""
    assert step4_classify._STATE_RUNNING == "classify_running"
    assert step4_classify._STATE_NEXT == "awaiting_opus"
    assert step4_classify._STATE_FAILED == "classify_failed"


# --------------------------- live-PG round-trip ---------------------------

psycopg2 = pytest.importorskip(
    "psycopg2", reason="psycopg2 required for live-PG integration test"
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

requires_db = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL unset"
)


@requires_db
def test_classify_live_pg_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply the Step 4 migration, insert a signal with Step 1-3 columns
    populated, run ``classify()``, verify the row holds a CHECK-compliant
    status + the decision column string. Exercises psycopg2 end-to-end."""
    mig_sql = (
        MIGRATIONS_DIR
        / "20260418_step4_signal_queue_step5_decision.sql"
    ).read_text(encoding="utf-8")
    # Extract UP section.
    up_start = mig_sql.index("-- == migrate:up ==")
    up_end = mig_sql.index("-- == migrate:down ==")
    up_sql = mig_sql[up_start:up_end]

    conn = psycopg2.connect(TEST_DB_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(up_sql)
            conn.commit()
            cur.execute(
                # STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 (2026-04-21):
                # ``raw_content`` is not a real column — the bridge writes
                # body text into ``payload->>'alert_body'``. Step 4 does
                # not read the body at all, so a minimal payload with the
                # ``alert_body`` key suffices to keep the row structurally
                # realistic for future re-reads.
                "INSERT INTO signal_queue "
                "(source, payload, status, triage_score, primary_matter, "
                " related_matters, resolved_thread_paths) "
                "VALUES ('step4_live_test', "
                "        '{\"alert_body\": \"content\"}'::jsonb, "
                "        'awaiting_classify', "
                "        75, 'movie', ARRAY[]::TEXT[], '[]'::jsonb) "
                "RETURNING id",
            )
            signal_id = cur.fetchone()[0]
            conn.commit()

        with patch(
            "kbl.steps.step4_classify._load_allowed_scope",
            return_value=frozenset({"movie"}),
        ):
            result = classify(signal_id=signal_id, conn=conn)
        conn.commit()

        assert result is ClassifyDecision.FULL_SYNTHESIS

        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, step_5_decision, cross_link_hint "
                "FROM signal_queue WHERE id = %s",
                (signal_id,),
            )
            status, decision_value, cross_link_hint = cur.fetchone()
        assert status == "awaiting_opus"
        assert decision_value == "full_synthesis"
        assert cross_link_hint is False
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM signal_queue WHERE source='step4_live_test'")
                conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
