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


# =====================================================================
# KBL_PIPELINE_SCHEDULER_WIRING — Steps 1-6 remote variant + main() gate
# =====================================================================

from kbl.pipeline_tick import _process_signal_remote, main as _pipeline_main


def test_process_signal_remote_happy_path_stops_at_awaiting_commit() -> None:
    """Steps 1-6 run in order, seven commits never happen — six.
    Step 7 is NOT imported or called. Signal ends at ``awaiting_commit``
    (Mac Mini poller takes over)."""
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

        _process_signal_remote(signal_id=101, conn=conn)

    # 6 commits (Steps 1-6), 0 rollbacks.
    assert conn.commit.call_count == 6
    assert conn.rollback.call_count == 0
    # Step 7 never invoked.
    assert mocks["step7"].call_count == 0
    # Steps 1-6 in strict order.
    assert call_log == ["step1", "step2", "step3", "step4", "step5", "step6"]


def test_process_signal_remote_routed_inbox_returns_early() -> None:
    """Step 1 terminal-routes low-score signal → Steps 2-6 skipped,
    Step 7 never called."""
    conn = _mock_conn(post_step1_status="routed_inbox")

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        _process_signal_remote(signal_id=102, conn=conn)

    mocks["step1"].assert_called_once_with(102, conn)
    assert conn.commit.call_count == 1
    for name in ("step2", "step3", "step4", "step5", "step6", "step7"):
        assert mocks[name].call_count == 0, f"{name} was called unexpectedly"


def test_process_signal_remote_paused_cost_cap_gates_out_step6() -> None:
    """Step 5 parks at ``paused_cost_cap`` — post-Step-5 status check
    skips Step 6. Step 7 also never reached."""
    conn = _mock_conn(
        post_step1_status="awaiting_resolve",
        post_step5_status="paused_cost_cap",
    )

    def _step5_cost_pause(signal_id: int, c: Any) -> None:
        c.commit()
        return None

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step5"].side_effect = _step5_cost_pause
        _process_signal_remote(signal_id=103, conn=conn)

    # 4 orchestrator (1-4) + 1 step5-internal + 1 orchestrator-post-step5.
    assert conn.commit.call_count == 6
    assert conn.rollback.call_count == 0
    assert mocks["step6"].call_count == 0
    assert mocks["step7"].call_count == 0


def test_main_disabled_returns_zero_without_claim(monkeypatch) -> None:
    """Default (flag unset) and explicit false both keep main() closed.
    claim_one_signal MUST NOT be called."""
    monkeypatch.delenv("KBL_FLAGS_PIPELINE_ENABLED", raising=False)

    with patch("kbl.pipeline_tick.claim_one_signal") as mock_claim, \
         patch("kbl.pipeline_tick.get_conn") as mock_conn_ctx:
        rc = _pipeline_main()

    assert rc == 0
    assert mock_claim.call_count == 0
    # get_conn must also be untouched — we bail before opening a conn.
    assert mock_conn_ctx.call_count == 0

    # And an explicit "false" behaves identically.
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "false")
    with patch("kbl.pipeline_tick.claim_one_signal") as mock_claim2, \
         patch("kbl.pipeline_tick.get_conn") as mock_conn_ctx2:
        rc2 = _pipeline_main()

    assert rc2 == 0
    assert mock_claim2.call_count == 0
    assert mock_conn_ctx2.call_count == 0


def test_main_enabled_calls_process_signal_remote(monkeypatch) -> None:
    """With the flag on and a claimable signal, main() delegates to
    _process_signal_remote with the claimed id."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=777) as mock_claim, \
         patch("kbl.pipeline_tick._process_signal_remote") as mock_remote, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    mock_claim.assert_called_once_with(fake_conn)
    mock_remote.assert_called_once_with(777, fake_conn)


def test_main_enabled_queue_empty_returns_zero(monkeypatch) -> None:
    """Flag on, ALL FIVE queues empty (primary pending + opus_failed
    reclaim + three awaiting_* crash-recovery reclaims) → main() returns
    0 without calling any processor.

    Contract updated for CLAIM_LOOP_ORPHAN_STATES_2: primary-empty is no
    longer sufficient to bail; the tick now consults the full 5-step
    claim chain before returning. Test patches all five so this stays a
    unit test (no live DB).
    """
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None) as mock_claim, \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None) as mock_reclaim, \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=None) as mock_cls, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus", return_value=None) as mock_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize", return_value=None) as mock_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as mock_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as mock_reclaim_fn, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as mock_cls_fn, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as mock_opus_fn, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as mock_fin_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    assert mock_claim.call_count == 1
    assert mock_reclaim.call_count == 1
    assert mock_cls.call_count == 1
    assert mock_opus.call_count == 1
    assert mock_fin.call_count == 1
    assert mock_remote.call_count == 0
    assert mock_reclaim_fn.call_count == 0
    assert mock_cls_fn.call_count == 0
    assert mock_opus_fn.call_count == 0
    assert mock_fin_fn.call_count == 0


def test_main_respects_anthropic_circuit(monkeypatch) -> None:
    """Anthropic circuit open → main() returns 0, does NOT claim."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    def _get_state(key):
        return "true" if key == "anthropic_circuit_open" else "false"

    with patch("kbl.pipeline_tick.get_state", side_effect=_get_state), \
         patch("kbl.pipeline_tick.claim_one_signal") as mock_claim, \
         patch("kbl.pipeline_tick.check_alert_dedupe", return_value=False):
        rc = _pipeline_main()

    assert rc == 0
    assert mock_claim.call_count == 0


def test_main_respects_cost_circuit(monkeypatch) -> None:
    """Cost circuit open → main() returns 0, does NOT claim."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    def _get_state(key):
        return "true" if key == "cost_circuit_open" else "false"

    with patch("kbl.pipeline_tick.get_state", side_effect=_get_state), \
         patch("kbl.pipeline_tick.claim_one_signal") as mock_claim:
        rc = _pipeline_main()

    assert rc == 0
    assert mock_claim.call_count == 0


def test_remote_variant_stops_at_finalize_failed() -> None:
    """Step 6 R3-exhaust path under ``_process_signal_remote``: Step 6
    internally commits the ``finalize_failed`` flip, then raises
    ``FinalizationError``. The remote variant's try/except rolls back
    the Step-6 fragment, but the step-internal commit has already sealed
    the terminal-state flip. The raise propagates out of the remote
    variant — Step 7 is not imported and cannot be invoked.

    Expected: commit_count == 6 = 5 orchestrator (steps 1-5) + 1
    step-internal (finalize_failed flip). rollback_count == 1. Step 7
    mock never called (brief §Scope.5 item 7 explicit assertion).
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
            _process_signal_remote(signal_id=201, conn=conn)

    assert conn.commit.call_count == 6  # 5 orchestrator + 1 step-internal.
    assert conn.rollback.call_count == 1
    mocks["step6"].assert_called_once_with(201, conn)
    # Remote variant never touches Step 7 — the step-internal commit
    # leaves the row at ``finalize_failed``; there is no Step-7 path here
    # to gate out or to call.
    assert mocks["step7"].call_count == 0


def test_main_disabled_silent_when_circuit_open(monkeypatch) -> None:
    """Brief v3 §Scope.5: env→circuit order means a disabled tick is
    silent even when the Anthropic / cost circuits are open. The env
    short-circuit returns before either ``get_state`` check fires, so
    ``check_alert_dedupe`` and ``emit_log`` are never invoked and no
    signal is claimed. The pipeline stays out of the way of whatever
    upstream state it is not acting on.
    """
    monkeypatch.delenv("KBL_FLAGS_PIPELINE_ENABLED", raising=False)

    # Force both circuits open — but env gate should short-circuit
    # before either ``get_state`` is read.
    def _get_state(key):
        if key in ("anthropic_circuit_open", "cost_circuit_open"):
            return "true"
        return "false"

    with patch("kbl.pipeline_tick.get_state", side_effect=_get_state) as mock_state, \
         patch("kbl.pipeline_tick.check_alert_dedupe") as mock_dedupe, \
         patch("kbl.pipeline_tick.emit_log") as mock_emit, \
         patch("kbl.pipeline_tick.claim_one_signal") as mock_claim, \
         patch("kbl.pipeline_tick.get_conn") as mock_conn_ctx:
        rc = _pipeline_main()

    assert rc == 0
    # Silence — no WARN dedupe, no emit_log.
    assert mock_dedupe.call_count == 0
    assert mock_emit.call_count == 0
    # Gate blocked — no claim, no connection opened, no circuit read.
    assert mock_claim.call_count == 0
    assert mock_conn_ctx.call_count == 0
    assert mock_state.call_count == 0

    # Explicit "false" behaves identically to unset.
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "false")
    with patch("kbl.pipeline_tick.get_state", side_effect=_get_state) as mock_state2, \
         patch("kbl.pipeline_tick.check_alert_dedupe") as mock_dedupe2, \
         patch("kbl.pipeline_tick.emit_log") as mock_emit2, \
         patch("kbl.pipeline_tick.claim_one_signal") as mock_claim2:
        rc2 = _pipeline_main()

    assert rc2 == 0
    assert mock_dedupe2.call_count == 0
    assert mock_emit2.call_count == 0
    assert mock_claim2.call_count == 0
    assert mock_state2.call_count == 0


# =====================================================================
# CLAIM_LOOP_OPUS_FAILED_RECLAIM_1 — secondary claim + reclaim orchestrator
# =====================================================================

from kbl.pipeline_tick import (
    _process_signal_reclaim_remote,
    claim_one_opus_failed,
)
from kbl.steps.step6_finalize import _MAX_OPUS_REFLIPS


def _claim_conn(select_returns: Any) -> tuple[MagicMock, list[tuple[str, Any]]]:
    """Mock conn for claim_one_opus_failed tests.

    ``select_returns`` is what ``fetchone()`` returns for the claim
    SELECT. All other SQL (ALTER, UPDATE) is observed via the captured
    ``executed`` list of ``(sql_lowercased, params)``.
    """
    conn = MagicMock()
    executed: list[tuple[str, Any]] = []

    def _make_cursor() -> MagicMock:
        cur = MagicMock()

        def _execute(sql: str, params: Any = None) -> None:
            executed.append((sql.lower(), params))
            s = sql.lower()
            if "select id from signal_queue" in s:
                cur.fetchone.return_value = select_returns
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
    return conn, executed


def test_claim_one_opus_failed_returns_eligible_row() -> None:
    """Eligible row (status=opus_failed, finalize_retry_count < budget) →
    claim returns its id, flips it to awaiting_opus, commits once.

    The SELECT must filter on ``status='opus_failed'`` AND
    ``finalize_retry_count < _MAX_OPUS_REFLIPS`` — verified by inspecting
    the captured SQL + params.
    """
    conn, executed = _claim_conn(select_returns=(42,))

    claimed = claim_one_opus_failed(conn)

    assert claimed == 42
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0

    # Budget guard landed in the SELECT.
    select_sql = next(
        (sql, p) for sql, p in executed if "select id from signal_queue" in sql
    )
    assert "status = 'opus_failed'" in select_sql[0]
    assert "finalize_retry_count" in select_sql[0]
    assert "for update skip locked" in select_sql[0]
    assert select_sql[1] == (_MAX_OPUS_REFLIPS,)

    # Post-claim UPDATE flips to awaiting_opus with the claimed id.
    update_sql = next(
        (sql, p) for sql, p in executed if sql.startswith("update signal_queue")
    )
    assert "status = 'awaiting_opus'" in update_sql[0]
    assert update_sql[1] == (42,)

    # Defensive ALTER ran once (idempotent on already-migrated DBs).
    alter_matches = [sql for sql, _ in executed if sql.startswith("alter table")]
    assert len(alter_matches) == 1
    assert "finalize_retry_count" in alter_matches[0]


def test_claim_one_opus_failed_skips_budget_exhausted() -> None:
    """Row at finalize_retry_count == _MAX_OPUS_REFLIPS must not be
    claimed — the SELECT's ``< %s`` filter excludes it.

    Simulated here by returning None from the claim SELECT (the live
    filter would screen the cap-exhausted row out of the result set).
    No UPDATE and no commit fire when the SELECT is empty.
    """
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_opus_failed(conn)

    assert claimed is None
    # No flip to awaiting_opus.
    updates = [sql for sql, _ in executed if sql.startswith("update signal_queue")]
    assert updates == []
    # No commit — the SELECT returned None, function returned early.
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 0
    # The SELECT's budget param is still _MAX_OPUS_REFLIPS — the filter
    # is what excludes cap-exhausted rows in the live DB.
    select_sql = next(
        (sql, p) for sql, p in executed if "select id from signal_queue" in sql
    )
    assert select_sql[1] == (_MAX_OPUS_REFLIPS,)


def test_claim_one_opus_failed_returns_none_when_empty() -> None:
    """No eligible rows (SELECT returns None) → claim returns None with
    no flip, no commit. Indistinguishable from the budget-exhausted case
    at the function boundary — both are ``fetchone() is None``."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_opus_failed(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 0
    # No UPDATE issued.
    assert not any(sql.startswith("update") for sql, _ in executed)


def test_reclaim_runs_steps_5_6_not_1_4() -> None:
    """_process_signal_reclaim_remote runs only Steps 5 + 6. Steps 1-4
    (triage, resolve, extract, classify) are never imported or called —
    the reclaim path trusts the upstream primary_matter / triage_score /
    related_matters written by the first attempt and lets Step 5 overwrite
    ``opus_draft_markdown``.

    Step 7 is also NOT called — reclaim mirrors ``_process_signal_remote``
    in stopping at Step 6's terminal state (awaiting_commit).
    """
    # NOTE: _mock_conn's status queue is consumed in SELECT order. The
    # reclaim path does one ``SELECT status`` — after Step 5, before
    # Step 6 — so it reads queue[0]. Set post_step1_status to the value
    # that check expects (``awaiting_finalize``); the other slots are
    # unused by this orchestrator variant.
    conn = _mock_conn(
        post_step1_status="awaiting_finalize",
        post_step5_status="__unused__",
        post_step6_status="__unused__",
    )
    call_log: list[str] = []

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        for name, mock in mocks.items():
            mock.side_effect = _tracked_step(call_log, name)

        _process_signal_reclaim_remote(signal_id=301, conn=conn)

    # Only Step 5 + Step 6 fire.
    assert call_log == ["step5", "step6"]
    mocks["step5"].assert_called_once_with(301, conn)
    mocks["step6"].assert_called_once_with(301, conn)
    # Steps 1-4 and Step 7 never touched.
    for name in ("step1", "step2", "step3", "step4", "step7"):
        assert mocks[name].call_count == 0, f"{name} ran on reclaim path"

    # 2 commits (one per step), 0 rollbacks.
    assert conn.commit.call_count == 2
    assert conn.rollback.call_count == 0


def test_reclaim_budget_exhaustion_routes_to_finalize_failed() -> None:
    """On the 3rd reflip (``finalize_retry_count`` hits
    ``_MAX_OPUS_REFLIPS``), Step 6's existing ``_route_validation_failure``
    promotes the row to ``finalize_failed`` terminal instead of flipping
    back to ``opus_failed``.

    Under the reclaim orchestrator this surfaces as: Step 6's internal
    commit-before-raise seals the ``finalize_failed`` state; the outer
    ``_process_signal_reclaim_remote`` rolls back its own Step-6 fragment
    and re-raises. Step 7 is never reached (not imported). Critically,
    the orchestrator does NOT loop or re-queue — the terminal state is
    durable and the next tick's ``claim_one_opus_failed`` skips this row
    because ``finalize_retry_count >= _MAX_OPUS_REFLIPS`` (and status
    is no longer ``opus_failed`` anyway).
    """
    from kbl.exceptions import FinalizationError

    # NOTE: _mock_conn's status queue is consumed in SELECT order. The
    # reclaim path does one ``SELECT status`` — after Step 5, before
    # Step 6 — so it reads queue[0]. Set post_step1_status to the value
    # that check expects (``awaiting_finalize``); the other slots are
    # unused by this orchestrator variant.
    conn = _mock_conn(
        post_step1_status="awaiting_finalize",
        post_step5_status="__unused__",
        post_step6_status="__unused__",
    )

    def _step6_terminal(signal_id: int, c: Any) -> None:
        c.commit()  # Step 6's fresh-conn terminal flip (simulated)
        raise FinalizationError(
            "terminal finalize failure after 3 Opus retries; routed to finalize_failed"
        )

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        mocks["step6"].side_effect = _step6_terminal

        with pytest.raises(FinalizationError, match="terminal finalize failure"):
            _process_signal_reclaim_remote(signal_id=302, conn=conn)

    # Step 5 sealed (1 orchestrator commit) + Step 6 internal commit (1) = 2.
    # Orchestrator rolled back the Step-6 fragment.
    assert conn.commit.call_count == 2
    assert conn.rollback.call_count == 1
    mocks["step5"].assert_called_once_with(302, conn)
    mocks["step6"].assert_called_once_with(302, conn)
    # Reclaim path never imports or calls Step 7.
    assert mocks["step7"].call_count == 0


def test_main_falls_back_to_reclaim_when_primary_empty(monkeypatch) -> None:
    """Primary claim returns None → main() tries claim_one_opus_failed.
    When that returns a row, dispatch goes to
    ``_process_signal_reclaim_remote``. This is the closed-loop path
    the brief introduces: no more orphaned opus_failed rows."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None) as mock_primary, \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=909) as mock_reclaim, \
         patch("kbl.pipeline_tick._process_signal_remote") as mock_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as mock_reclaim_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    mock_primary.assert_called_once_with(fake_conn)
    mock_reclaim.assert_called_once_with(fake_conn)
    # Primary processor NOT invoked (primary claim was empty).
    assert mock_remote.call_count == 0
    # Reclaim processor DID run with the reclaim id.
    mock_reclaim_fn.assert_called_once_with(909, fake_conn)


def test_main_both_queues_empty_returns_zero(monkeypatch) -> None:
    """Primary + opus_failed reclaim + three awaiting_* reclaims all
    empty → main() returns 0 without dispatching to any processor. Flag
    on, both circuits closed."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None) as mock_primary, \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None) as mock_reclaim, \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=None) as mock_cls, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus", return_value=None) as mock_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize", return_value=None) as mock_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as mock_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as mock_reclaim_fn, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as mock_cls_fn, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as mock_opus_fn, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as mock_fin_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    assert mock_primary.call_count == 1
    assert mock_reclaim.call_count == 1
    assert mock_cls.call_count == 1
    assert mock_opus.call_count == 1
    assert mock_fin.call_count == 1
    assert mock_remote.call_count == 0
    assert mock_reclaim_fn.call_count == 0
    assert mock_cls_fn.call_count == 0
    assert mock_opus_fn.call_count == 0
    assert mock_fin_fn.call_count == 0


def test_main_primary_claim_skips_reclaim(monkeypatch) -> None:
    """Primary claim returns an id → main() runs ``_process_signal_remote``
    and does NOT call ``claim_one_opus_failed`` on this tick. Reclaim is
    strictly a fallback; primary pending work gets first priority on
    every tick."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=555) as mock_primary, \
         patch("kbl.pipeline_tick.claim_one_opus_failed") as mock_reclaim, \
         patch("kbl.pipeline_tick._process_signal_remote") as mock_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as mock_reclaim_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    mock_primary.assert_called_once_with(fake_conn)
    mock_remote.assert_called_once_with(555, fake_conn)
    # Reclaim NEVER consulted when primary had work.
    assert mock_reclaim.call_count == 0
    assert mock_reclaim_fn.call_count == 0


# =====================================================================
# CLAIM_LOOP_ORPHAN_STATES_2 — awaiting_* crash-recovery reclaim chain
# =====================================================================

from kbl.pipeline_tick import (
    _AWAITING_ORPHAN_STALE_INTERVAL,
    _process_signal_classify_remote,
    _process_signal_finalize_remote,
    _process_signal_opus_remote,
    claim_one_awaiting_classify,
    claim_one_awaiting_finalize,
    claim_one_awaiting_opus,
)


# --------------------------- claim-function tests ---------------------------


def test_claim_one_awaiting_classify_returns_eligible_row() -> None:
    """Stale awaiting_classify row (started_at > 15 min ago) → claim
    returns its id, flips it to ``classify_running``, commits once.

    Staleness SQL must include the 15-minute interval; the SELECT filters
    on ``status='awaiting_classify'``. No budget counter (crash-recovery,
    not a retry state)."""
    conn, executed = _claim_conn(select_returns=(811,))

    claimed = claim_one_awaiting_classify(conn)

    assert claimed == 811
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0

    select_sql = next(
        (sql, p) for sql, p in executed if "select id from signal_queue" in sql
    )
    assert "status = 'awaiting_classify'" in select_sql[0]
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]
    assert "for update skip locked" in select_sql[0]
    # No budget param (unlike claim_one_opus_failed); SELECT takes no params.
    assert select_sql[1] is None

    update_sql = next(
        (sql, p) for sql, p in executed if sql.startswith("update signal_queue")
    )
    assert "status = 'classify_running'" in update_sql[0]
    assert update_sql[1] == (811,)

    # No ALTER — unlike claim_one_opus_failed, this function reuses the
    # existing ``started_at`` column which predates the module.
    assert not any(sql.startswith("alter table") for sql, _ in executed)


def test_claim_one_awaiting_classify_skips_fresh_rows() -> None:
    """Fresh awaiting_classify row (started_at within 15 min) must be
    skipped by the staleness guard. Simulated here by returning None from
    the claim SELECT — the live ``started_at < NOW() - INTERVAL '15 minutes'``
    filter screens the mid-flight row out of the result set. No UPDATE,
    no commit when the SELECT is empty."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_classify(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)
    # Guard clause is in the SELECT, and the SELECT still ran.
    select_sql = next(
        (sql, _) for sql, _ in executed if "select id from signal_queue" in sql
    )
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]


def test_claim_one_awaiting_classify_returns_none_when_empty() -> None:
    """No eligible rows at all → claim returns None, no side effects."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_classify(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert conn.rollback.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)


def test_claim_one_awaiting_opus_returns_eligible_row() -> None:
    """Stale awaiting_opus row → claim returns id, flips to
    ``opus_running``, commits once. Distinct from ``claim_one_opus_failed``
    which flips ``opus_failed → awaiting_opus``; this one flips
    ``awaiting_opus → opus_running``."""
    conn, executed = _claim_conn(select_returns=(822,))

    claimed = claim_one_awaiting_opus(conn)

    assert claimed == 822
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0

    select_sql = next(
        (sql, p) for sql, p in executed if "select id from signal_queue" in sql
    )
    assert "status = 'awaiting_opus'" in select_sql[0]
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]
    assert "for update skip locked" in select_sql[0]
    assert select_sql[1] is None

    update_sql = next(
        (sql, p) for sql, p in executed if sql.startswith("update signal_queue")
    )
    assert "status = 'opus_running'" in update_sql[0]
    assert update_sql[1] == (822,)


def test_claim_one_awaiting_opus_skips_fresh_rows() -> None:
    """Fresh awaiting_opus row must be skipped by staleness guard."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_opus(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)
    select_sql = next(
        (sql, _) for sql, _ in executed if "select id from signal_queue" in sql
    )
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]


def test_claim_one_awaiting_opus_returns_none_when_empty() -> None:
    """No eligible rows → None, no side effects."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_opus(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)


def test_claim_one_awaiting_finalize_returns_eligible_row() -> None:
    """Stale awaiting_finalize row → claim returns id, flips to
    ``finalize_running``, commits once. This is the state AI Head has
    been manually recovering in multiple sessions."""
    conn, executed = _claim_conn(select_returns=(833,))

    claimed = claim_one_awaiting_finalize(conn)

    assert claimed == 833
    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0

    select_sql = next(
        (sql, p) for sql, p in executed if "select id from signal_queue" in sql
    )
    assert "status = 'awaiting_finalize'" in select_sql[0]
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]
    assert "for update skip locked" in select_sql[0]
    assert select_sql[1] is None

    update_sql = next(
        (sql, p) for sql, p in executed if sql.startswith("update signal_queue")
    )
    assert "status = 'finalize_running'" in update_sql[0]
    assert update_sql[1] == (833,)


def test_claim_one_awaiting_finalize_skips_fresh_rows() -> None:
    """Fresh awaiting_finalize row must be skipped by staleness guard."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_finalize(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)
    select_sql = next(
        (sql, _) for sql, _ in executed if "select id from signal_queue" in sql
    )
    assert _AWAITING_ORPHAN_STALE_INTERVAL in select_sql[0]


def test_claim_one_awaiting_finalize_returns_none_when_empty() -> None:
    """No eligible rows → None, no side effects."""
    conn, executed = _claim_conn(select_returns=None)

    claimed = claim_one_awaiting_finalize(conn)

    assert claimed is None
    assert conn.commit.call_count == 0
    assert not any(sql.startswith("update") for sql, _ in executed)


# --------------------------- dispatch-function tests ---------------------------


def test_classify_dispatch_runs_4_5_6_not_1_3_or_7() -> None:
    """_process_signal_classify_remote runs only Steps 4 + 5 + 6. Steps
    1-3 (triage, resolve, extract) are never called — the reclaim entry
    trusts the upstream columns. Step 7 is never called — Render has no
    vault (CHANDA Inv 9).

    3 orchestrator commits (one per step), 0 rollbacks."""
    # The orchestrator performs ONE status check between Step 5 and
    # Step 6, reading queue[0] (post_step1_status slot).
    conn = _mock_conn(
        post_step1_status="awaiting_finalize",
        post_step5_status="__unused__",
        post_step6_status="__unused__",
    )
    call_log: list[str] = []

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        for name, mock in mocks.items():
            mock.side_effect = _tracked_step(call_log, name)

        _process_signal_classify_remote(signal_id=401, conn=conn)

    assert call_log == ["step4", "step5", "step6"]
    mocks["step4"].assert_called_once_with(401, conn)
    mocks["step5"].assert_called_once_with(401, conn)
    mocks["step6"].assert_called_once_with(401, conn)
    for name in ("step1", "step2", "step3", "step7"):
        assert mocks[name].call_count == 0, f"{name} ran on classify-reclaim path"

    assert conn.commit.call_count == 3
    assert conn.rollback.call_count == 0


def test_opus_dispatch_runs_5_6_not_1_4_or_7() -> None:
    """_process_signal_opus_remote runs only Steps 5 + 6. Same shape as
    PR #38's reclaim path but entered from ``opus_running`` (not a pre-flip
    to ``awaiting_opus``). Steps 1-4 and Step 7 never called."""
    conn = _mock_conn(
        post_step1_status="awaiting_finalize",
        post_step5_status="__unused__",
        post_step6_status="__unused__",
    )
    call_log: list[str] = []

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        for name, mock in mocks.items():
            mock.side_effect = _tracked_step(call_log, name)

        _process_signal_opus_remote(signal_id=501, conn=conn)

    assert call_log == ["step5", "step6"]
    mocks["step5"].assert_called_once_with(501, conn)
    mocks["step6"].assert_called_once_with(501, conn)
    for name in ("step1", "step2", "step3", "step4", "step7"):
        assert mocks[name].call_count == 0, f"{name} ran on opus-reclaim path"

    assert conn.commit.call_count == 2
    assert conn.rollback.call_count == 0


def test_finalize_dispatch_runs_6_not_others() -> None:
    """_process_signal_finalize_remote runs only Step 6. Steps 1-5 and
    Step 7 never called. 1 orchestrator commit, 0 rollbacks."""
    conn = MagicMock()
    call_log: list[str] = []

    with ExitStack() as stack:
        mocks = _enter_all_steps(stack)
        for name, mock in mocks.items():
            mock.side_effect = _tracked_step(call_log, name)

        _process_signal_finalize_remote(signal_id=601, conn=conn)

    assert call_log == ["step6"]
    mocks["step6"].assert_called_once_with(601, conn)
    for name in ("step1", "step2", "step3", "step4", "step5", "step7"):
        assert mocks[name].call_count == 0, f"{name} ran on finalize-reclaim path"

    assert conn.commit.call_count == 1
    assert conn.rollback.call_count == 0


# --------------------------- main() integration tests ---------------------------


def test_main_falls_back_to_classify_reclaim_when_earlier_queues_empty(monkeypatch) -> None:
    """Primary empty, opus_failed empty → main() consults
    claim_one_awaiting_classify next. When that returns a row, dispatch
    goes to ``_process_signal_classify_remote``."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None) as m_primary, \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None) as m_opusf, \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=811) as m_cls, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus") as m_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize") as m_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as m_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as m_reclaim, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as m_cls_fn, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as m_opus_fn, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as m_fin_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    m_primary.assert_called_once_with(fake_conn)
    m_opusf.assert_called_once_with(fake_conn)
    m_cls.assert_called_once_with(fake_conn)
    # Later reclaims NOT consulted — stop at first hit.
    assert m_opus.call_count == 0
    assert m_fin.call_count == 0

    # Primary + opus_failed processors not invoked. Classify reclaim DID run.
    assert m_remote.call_count == 0
    assert m_reclaim.call_count == 0
    m_cls_fn.assert_called_once_with(811, fake_conn)
    assert m_opus_fn.call_count == 0
    assert m_fin_fn.call_count == 0


def test_main_falls_back_to_opus_reclaim_when_earlier_queues_empty(monkeypatch) -> None:
    """Primary + opus_failed + awaiting_classify empty → consult
    claim_one_awaiting_opus. Dispatch to ``_process_signal_opus_remote``."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None), \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None), \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=None) as m_cls, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus", return_value=822) as m_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize") as m_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as m_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as m_reclaim, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as m_cls_fn, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as m_opus_fn, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as m_fin_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    m_cls.assert_called_once_with(fake_conn)
    m_opus.assert_called_once_with(fake_conn)
    # awaiting_finalize NOT consulted — stopped at awaiting_opus hit.
    assert m_fin.call_count == 0

    assert m_remote.call_count == 0
    assert m_reclaim.call_count == 0
    assert m_cls_fn.call_count == 0
    m_opus_fn.assert_called_once_with(822, fake_conn)
    assert m_fin_fn.call_count == 0


def test_main_falls_back_to_finalize_reclaim_when_earlier_queues_empty(monkeypatch) -> None:
    """All earlier queues empty → consult claim_one_awaiting_finalize.
    Dispatch to ``_process_signal_finalize_remote``."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None), \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None), \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=None), \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus", return_value=None) as m_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize", return_value=833) as m_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as m_remote, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as m_reclaim, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as m_cls_fn, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as m_opus_fn, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as m_fin_fn, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    m_opus.assert_called_once_with(fake_conn)
    m_fin.assert_called_once_with(fake_conn)

    assert m_remote.call_count == 0
    assert m_reclaim.call_count == 0
    assert m_cls_fn.call_count == 0
    assert m_opus_fn.call_count == 0
    m_fin_fn.assert_called_once_with(833, fake_conn)


def test_main_all_queues_empty_returns_zero_without_any_dispatch(monkeypatch) -> None:
    """All five claim functions return None → main() returns 0, no
    dispatch function is called. This is the quiet-tick contract on an
    idle pipeline."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=None) as m1, \
         patch("kbl.pipeline_tick.claim_one_opus_failed", return_value=None) as m2, \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify", return_value=None) as m3, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus", return_value=None) as m4, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize", return_value=None) as m5, \
         patch("kbl.pipeline_tick._process_signal_remote") as d1, \
         patch("kbl.pipeline_tick._process_signal_reclaim_remote") as d2, \
         patch("kbl.pipeline_tick._process_signal_classify_remote") as d3, \
         patch("kbl.pipeline_tick._process_signal_opus_remote") as d4, \
         patch("kbl.pipeline_tick._process_signal_finalize_remote") as d5, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    # All 5 claim functions consulted in order.
    for m in (m1, m2, m3, m4, m5):
        assert m.call_count == 1
    # No dispatch function called.
    for d in (d1, d2, d3, d4, d5):
        assert d.call_count == 0


def test_main_primary_hit_skips_all_reclaims(monkeypatch) -> None:
    """Primary claim returns an id → main() dispatches and returns 0
    without consulting ANY of the four reclaim claim functions.
    Primary pending work has strict priority every tick."""
    monkeypatch.setenv("KBL_FLAGS_PIPELINE_ENABLED", "true")

    fake_conn = MagicMock()
    fake_conn_ctx = MagicMock()
    fake_conn_ctx.__enter__.return_value = fake_conn
    fake_conn_ctx.__exit__.return_value = False

    with patch("kbl.pipeline_tick.get_conn", return_value=fake_conn_ctx), \
         patch("kbl.pipeline_tick.claim_one_signal", return_value=444) as m_primary, \
         patch("kbl.pipeline_tick.claim_one_opus_failed") as m_opusf, \
         patch("kbl.pipeline_tick.claim_one_awaiting_classify") as m_cls, \
         patch("kbl.pipeline_tick.claim_one_awaiting_opus") as m_opus, \
         patch("kbl.pipeline_tick.claim_one_awaiting_finalize") as m_fin, \
         patch("kbl.pipeline_tick._process_signal_remote") as m_remote, \
         patch("kbl.pipeline_tick.get_state", return_value="false"):
        rc = _pipeline_main()

    assert rc == 0
    m_primary.assert_called_once_with(fake_conn)
    m_remote.assert_called_once_with(444, fake_conn)
    # None of the four reclaim functions was consulted.
    for m in (m_opusf, m_cls, m_opus, m_fin):
        assert m.call_count == 0
