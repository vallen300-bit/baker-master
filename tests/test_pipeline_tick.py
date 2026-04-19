"""Tests for ``kbl.pipeline_tick._process_signal`` — the transaction-
boundary contract (Task K YELLOW remediation).

Contract (verbatim from the module docstring):
    1. Each step function is caller-owns-commit — step writes, orchestrator
       commits on successful return, rolls back on exception.
    2. A step MAY internally commit to preserve a terminal-state flip
       across the caller's rollback (Step 1/4/5 ``*_failed`` states,
       Step 5 ``paused_cost_cap``).

These tests mirror the ``_mock_conn`` pattern from ``tests/test_step5_opus.py``
and ``tests/test_cost_gate.py``. All five step functions are patched at
``kbl.steps.<module>.<fn>`` (picked up through ``_process_signal``'s
deferred imports).
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kbl.exceptions import (
    AnthropicUnavailableError,
    ResolverError,
    TriageParseError,
)
from kbl.pipeline_tick import _process_signal


# --------------------------- mock conn ---------------------------


def _mock_conn(
    post_step1_status: str = "awaiting_resolve",
    post_step5_status: str = "awaiting_finalize",
    post_step6_status: str = "awaiting_commit",
) -> MagicMock:
    """Build a MagicMock conn.

    The orchestrator issues three status re-checks:
      1. After Step 1 — decides whether to run Steps 2-5.
      2. After Step 5 — decides whether to run Step 6 (skipped on
         ``paused_cost_cap``).
      3. After Step 6 — decides whether to run Step 7 (skipped on
         ``finalize_failed``).

    Each ``SELECT status FROM signal_queue WHERE id = %s`` returns the
    next value from the queue built from the three ``post_*`` args. Any
    further SELECT returns the final value in the queue (harmless —
    Step 7 is terminal).

    Commit/rollback counts are auto-tracked by MagicMock — assert on
    ``conn.commit.call_count`` / ``conn.rollback.call_count``.
    """
    conn = MagicMock()
    status_queue: list[str] = [
        post_step1_status,
        post_step5_status,
        post_step6_status,
    ]
    status_iter_state = {"idx": 0}

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            s = sql.lower()
            if "select status from signal_queue" in s:
                i = min(status_iter_state["idx"], len(status_queue) - 1)
                cur.fetchone.return_value = (status_queue[i],)
                status_iter_state["idx"] += 1
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
    return conn


# --------------------------- patch bundle ---------------------------


_STEP_PATHS = [
    ("step1", "kbl.steps.step1_triage.triage"),
    ("step2", "kbl.steps.step2_resolve.resolve"),
    ("step3", "kbl.steps.step3_extract.extract"),
    ("step4", "kbl.steps.step4_classify.classify"),
    ("step5", "kbl.steps.step5_opus.synthesize"),
    ("step6", "kbl.steps.step6_finalize.finalize"),
    ("step7", "kbl.steps.step7_commit.commit"),
]


def _enter_all_steps(stack: ExitStack) -> dict[str, MagicMock]:
    """Patch all seven step functions; return {name: mock}."""
    mocks: dict[str, MagicMock] = {}
    for name, path in _STEP_PATHS:
        mocks[name] = stack.enter_context(patch(path))
    return mocks


def _tracked_step(log: list[str], name: str):
    """Side effect that records the call order into ``log``."""

    def _se(signal_id: int, conn: Any) -> None:
        log.append(name)

    return _se


# --------------------------- happy path ---------------------------


def test_process_signal_happy_path_commits_once_per_step() -> None:
    """All 7 steps succeed → orchestrator commits exactly 7 times (one
    per step), never rolls back, and calls steps in the fixed
    1→2→3→4→5→6→7 order with ``(signal_id, conn)``. Signal ends at
    terminal ``completed``."""
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="awaiting_commit",
    )
    call_log: list[str] = []

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        for name, mock in mocks.items():
            mock.side_effect = _tracked_step(call_log, name)

        _process_signal(signal_id=42, conn=conn)

    # 7 commits (one per step), 0 rollbacks.
    assert conn.commit.call_count == 7
    assert conn.rollback.call_count == 0

    # Every step invoked with the same (signal_id, conn).
    for name, mock in mocks.items():
        mock.assert_called_once_with(42, conn)

    # Strict 1→7 ordering.
    assert call_log == [
        "step1", "step2", "step3", "step4", "step5", "step6", "step7"
    ]


# --------------------------- early return on routed_inbox ---------------------------


def test_process_signal_routed_inbox_after_step1_returns_early() -> None:
    """Step 1 may terminal-route a low-score signal to ``routed_inbox``.
    Orchestrator re-checks status and returns — Steps 2-5 never called,
    only Step 1's commit fires."""
    conn = _mock_conn(post_step1_status="routed_inbox")

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        _process_signal(signal_id=7, conn=conn)

    # Step 1 called, its post-success commit fired.
    mocks["step1"].assert_called_once_with(7, conn)
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0

    # Steps 2-5 never called — the pipeline stopped at the status check.
    for name in ("step2", "step3", "step4", "step5"):
        assert mocks[name].call_count == 0, f"{name} was called unexpectedly"


# --------------------------- Step 1 failure ---------------------------


def test_process_signal_step1_raises_triage_parse_error_rolls_back() -> None:
    """Step 1 raises → orchestrator rolls back, re-raises, Steps 2-5
    never called, no commits."""
    conn = _mock_conn()

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step1"].side_effect = TriageParseError("bad json")

        with pytest.raises(TriageParseError, match="bad json"):
            _process_signal(signal_id=11, conn=conn)

    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 1
    # No subsequent step ran.
    for name in ("step2", "step3", "step4", "step5"):
        assert mocks[name].call_count == 0


# --------------------------- Step 2 failure ---------------------------


def test_process_signal_step2_raises_resolver_error_preserves_step1_commit() -> None:
    """Step 1's commit lands before Step 2 raises. Orchestrator rolls
    back the Step 2 fragment only — Step 1's writes are preserved in
    the PG sense because the step 1 commit already sealed them. On
    the MagicMock we see commit_count=1 (step 1) + rollback_count=1
    (step 2). Steps 3-5 not called."""
    conn = _mock_conn()

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step2"].side_effect = ResolverError("malformed payload")

        with pytest.raises(ResolverError, match="malformed"):
            _process_signal(signal_id=13, conn=conn)

    assert conn.commit.call_count == 1  # Step 1 sealed.
    assert conn.rollback.call_count == 1  # Step 2 fragment rolled back.
    mocks["step1"].assert_called_once_with(13, conn)
    mocks["step2"].assert_called_once_with(13, conn)
    for name in ("step3", "step4", "step5"):
        assert mocks[name].call_count == 0


# --------------------------- Step 5 R3 exhaust ---------------------------


def test_process_signal_step5_r3_exhaust_internal_commit_then_rollback() -> None:
    """Step 5 simulates the R3-exhausted path: it commits internally to
    preserve the ``opus_failed`` terminal flip, then raises
    ``AnthropicUnavailableError``. Orchestrator's rollback fires, but
    the step's own commit already sealed the failure state.

    Expected on the MagicMock:
      - commit_count == 5 = 4 orchestrator commits (steps 1-4) + 1
        step-internal commit (step 5's opus_failed flip).
      - rollback_count == 1 (orchestrator reacts to the raise).
    """
    conn = _mock_conn()

    def _step5_r3_exhaust(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal terminal-state flip
        raise AnthropicUnavailableError("R3 exhausted")

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step5"].side_effect = _step5_r3_exhaust

        with pytest.raises(AnthropicUnavailableError, match="R3 exhausted"):
            _process_signal(signal_id=21, conn=conn)

    assert conn.commit.call_count == 5  # 4 orchestrator + 1 step-internal.
    assert conn.rollback.call_count == 1
    # All 5 steps were attempted.
    for name in ("step1", "step2", "step3", "step4", "step5"):
        mocks[name].assert_called_once_with(21, conn)


# --------------------------- Step 5 cost-cap pause ---------------------------


def test_process_signal_step5_cost_cap_pause_returns_normally() -> None:
    """Step 5 parked via cost gate: it internally commits the
    ``paused_cost_cap`` flip and returns normally (no raise). Orchestrator
    then commits again on successful return. The post-Step-5 status check
    sees ``paused_cost_cap`` (not ``awaiting_finalize``) and skips Step 6
    + Step 7. No rollback.

    Expected commit count == 6: 4 orchestrator commits (steps 1-4) +
    1 step-internal (paused_cost_cap flip) + 1 orchestrator commit after
    Step 5 returns. Steps 6-7 are gated out by the status check.
    """
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="paused_cost_cap",
    )

    def _step5_cost_pause(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal paused_cost_cap flip
        return None  # normal return — no raise

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step5"].side_effect = _step5_cost_pause

        # Must not raise.
        _process_signal(signal_id=33, conn=conn)

    assert conn.commit.call_count == 6
    assert conn.rollback.call_count == 0
    mocks["step5"].assert_called_once_with(33, conn)
    # Steps 6 + 7 gated out by status check — never invoked.
    assert mocks["step6"].call_count == 0
    assert mocks["step7"].call_count == 0


# --------------------------- Step 6 → Step 7 gate ---------------------------


def test_process_signal_step6_to_step7_gate_advances_to_commit() -> None:
    """Step 6 returns → post-Step-6 status check sees ``awaiting_commit``
    → Step 7 runs. Orchestrator commits 7 times (one per step), no
    rollback."""
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="awaiting_commit",
    )

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        _process_signal(signal_id=55, conn=conn)

    assert conn.commit.call_count == 7
    assert conn.rollback.call_count == 0
    mocks["step6"].assert_called_once_with(55, conn)
    mocks["step7"].assert_called_once_with(55, conn)


def test_process_signal_step6_finalize_failed_gates_out_step7() -> None:
    """Step 6 terminal-flips ``finalize_failed`` (3 Opus retries exhausted)
    and returns normally. Post-Step-6 status check sees
    ``finalize_failed`` (not ``awaiting_commit``) and skips Step 7.
    """
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="finalize_failed",
    )

    def _step6_terminal_returns(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal finalize_failed flip
        return None  # return normally — orchestrator evaluates status

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step6"].side_effect = _step6_terminal_returns
        _process_signal(signal_id=56, conn=conn)

    # Step 7 never invoked.
    assert mocks["step7"].call_count == 0


# --------------------------- Step 6 failure ---------------------------


def test_process_signal_step6_raises_finalization_error_rolls_back() -> None:
    """Step 6 raises ``FinalizationError`` on the last boundary →
    orchestrator rolls back the Step 6 fragment and re-raises. Prior
    steps' commits are preserved in the PG sense (already sealed);
    MagicMock shows commit_count=5 (steps 1-5) + rollback_count=1."""
    from kbl.exceptions import FinalizationError

    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
    )

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step6"].side_effect = FinalizationError(
            "signal_id=91: frontmatter validation failed (3 errors)"
        )

        with pytest.raises(FinalizationError, match="frontmatter"):
            _process_signal(signal_id=91, conn=conn)

    assert conn.commit.call_count == 5  # Steps 1-5 sealed.
    assert conn.rollback.call_count == 1  # Step 6 fragment rolled back.
    mocks["step6"].assert_called_once_with(91, conn)


def test_process_signal_step6_terminal_flip_internal_commit_then_rollback() -> None:
    """Step 6's terminal-state flip (finalize_failed after 3 Opus retries)
    mirrors Step 1/4/5 — the step commits internally to preserve the
    state flip, then raises. Orchestrator rollback fires but the sealed
    state survives.

    Expected: commit_count == 6 = 5 orchestrator (steps 1-5) + 1
    step-internal (finalize_failed flip). rollback_count == 1.
    """
    from kbl.exceptions import FinalizationError

    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
    )

    def _step6_terminal(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal finalize_failed flip
        raise FinalizationError("terminal finalize failure after 3 Opus retries")

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step6"].side_effect = _step6_terminal

        with pytest.raises(FinalizationError, match="terminal"):
            _process_signal(signal_id=73, conn=conn)

    assert conn.commit.call_count == 6  # 5 orchestrator + 1 step-internal.
    assert conn.rollback.call_count == 1
    mocks["step6"].assert_called_once_with(73, conn)


# --------------------------- Step 7 failures ---------------------------


def test_process_signal_step7_raises_commit_error_rolls_back() -> None:
    """Step 7 raises ``CommitError`` (e.g. push retry exhausted) →
    orchestrator rolls back Step 7 fragment and re-raises. Prior 6
    steps' commits already sealed → commit_count=6, rollback_count=1."""
    from kbl.exceptions import CommitError

    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="awaiting_commit",
    )

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step7"].side_effect = CommitError("git push failed after rebase retry")

        with pytest.raises(CommitError, match="push failed"):
            _process_signal(signal_id=74, conn=conn)

    assert conn.commit.call_count == 6  # Steps 1-6 sealed.
    assert conn.rollback.call_count == 1  # Step 7 fragment rolled back.
    mocks["step7"].assert_called_once_with(74, conn)


def test_process_signal_step7_terminal_flip_internal_commit_then_rollback() -> None:
    """Step 7's internal ``commit_failed`` flip survives the outer
    rollback (mirrors Step 1/4/5/6 pattern). MagicMock sees
    commit_count=7 (6 orchestrator + 1 step-internal) + rollback=1."""
    from kbl.exceptions import CommitError

    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="awaiting_finalize",
        post_step6_status="awaiting_commit",
    )

    def _step7_terminal(signal_id: int, c: Any) -> None:
        c.commit()  # step-internal commit_failed flip
        raise CommitError("vault write failed: disk full")

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step7"].side_effect = _step7_terminal

        with pytest.raises(CommitError, match="disk full"):
            _process_signal(signal_id=75, conn=conn)

    assert conn.commit.call_count == 7  # 6 orchestrator + 1 step-internal.
    assert conn.rollback.call_count == 1
    mocks["step7"].assert_called_once_with(75, conn)
