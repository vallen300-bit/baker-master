"""CORTEX_RETIRE_PHASE1_1 — retirement guard: default-410 on cycle-starting surfaces.

Brief: briefs/BRIEF_CORTEX_RETIRE_PHASE1_1.md (Director-ratified Cortex retirement
2026-07-23; memo briefs/_plans/CORTEX_RETIREMENT_MEMO_2026-07-23.md).

Cortex cycle service is retired. `_cortex_retired()` DEFAULTS TRUE, so all three
cycle-starting surfaces refuse to start a cycle with NO env var set:
- POST /api/cortex/trigger        → HTTP 410 {"detail": "cortex_retired"}
- POST /api/cortex/run            → HTTP 410 {"detail": "cortex_retired"}
- _cortex_gate_fire_cycle (bg)    → log + return, NEVER raises, no cycle fired

Rollback: CORTEX_RETIRED=false restores the pre-retirement behavior (covered by
the flag-OFF variants in test_cortex_trigger_endpoint.py / test_cortex_run_endpoint.py).

The stuck-cycle sentinel registration is gated off when retired — asserted
structurally via the established _register_jobs AST-walk pattern (the live
start_scheduler flow lazy-imports half the codebase, so we do not execute it).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


def _auth(monkeypatch, key="test-key-123"):
    """Set a valid X-Baker-Key so requests reach the in-handler retirement guard
    (auth is a dependency that runs BEFORE the guard)."""
    monkeypatch.setenv("BAKER_API_KEY", key)
    import outputs.dashboard as dash
    dash._BAKER_API_KEY = key
    from outputs.dashboard import verify_api_key
    dash.app.dependency_overrides.pop(verify_api_key, None)
    return key


# ---------------------------------------------------------------------------
# Helper — default TRUE, rollback via flag
# ---------------------------------------------------------------------------

def test_cortex_retired_default_true(monkeypatch):
    """With NO env var set, _cortex_retired() is TRUE (retired is the new normal)."""
    monkeypatch.delenv("CORTEX_RETIRED", raising=False)
    from outputs.dashboard import _cortex_retired
    assert _cortex_retired() is True


def test_cortex_retired_false_rollback(monkeypatch):
    """CORTEX_RETIRED=false flips the guard off (rollback lever)."""
    monkeypatch.setenv("CORTEX_RETIRED", "false")
    from outputs.dashboard import _cortex_retired
    assert _cortex_retired() is False


def test_cortex_retired_case_insensitive(monkeypatch):
    """Flag parse is case/space tolerant; anything != 'true' is NOT retired."""
    from outputs.dashboard import _cortex_retired
    monkeypatch.setenv("CORTEX_RETIRED", "  TRUE  ")
    assert _cortex_retired() is True
    monkeypatch.setenv("CORTEX_RETIRED", "False")
    assert _cortex_retired() is False


# ---------------------------------------------------------------------------
# POST /api/cortex/trigger — 410 default
# ---------------------------------------------------------------------------

def test_trigger_410_when_retired_default(monkeypatch):
    """No CORTEX_RETIRED env → 410 cortex_retired; maybe_run_cycle NOT awaited."""
    monkeypatch.delenv("CORTEX_RETIRED", raising=False)
    key = _auth(monkeypatch)

    from outputs.dashboard import app
    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=MagicMock()),
    ) as m:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/trigger",
            json={
                "matter_slug": "oskolkov",
                "director_question": "valid length question content here",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": key},
        )
    assert resp.status_code == 410, resp.text
    assert resp.json()["detail"] == "cortex_retired"
    m.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /api/cortex/run — 410 default
# ---------------------------------------------------------------------------

def test_run_410_when_retired_default(monkeypatch):
    """No CORTEX_RETIRED env → 410 cortex_retired; stream never started."""
    monkeypatch.delenv("CORTEX_RETIRED", raising=False)
    key = _auth(monkeypatch)

    from outputs.dashboard import app
    with patch("outputs.cortex_run_stream.stream_cycle_events") as m_stream:
        client = TestClient(app)
        resp = client.post(
            "/api/cortex/run",
            json={
                "matter_slug": "oskolkov",
                "director_question": "valid length question content here",
                "triggered_by": "test",
            },
            headers={"X-Baker-Key": key},
        )
    assert resp.status_code == 410, resp.text
    assert resp.json()["detail"] == "cortex_retired"
    # Guard is at the very top of the handler — the stream helper is never called.
    m_stream.assert_not_called()


# ---------------------------------------------------------------------------
# _cortex_gate_fire_cycle — background continuation: log + return, never raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_fire_cycle_noop_when_retired(monkeypatch):
    """Retired (default): the gate background fire path returns without calling
    maybe_run_cycle and NEVER raises."""
    monkeypatch.delenv("CORTEX_RETIRED", raising=False)
    from outputs.dashboard import _cortex_gate_fire_cycle

    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=MagicMock()),
    ) as m:
        # Must not raise even though it runs as a FastAPI background task.
        await _cortex_gate_fire_cycle("oskolkov", 999)
    m.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_fire_cycle_runs_when_flag_off(monkeypatch):
    """Rollback: CORTEX_RETIRED=false → the gate fire path calls maybe_run_cycle."""
    monkeypatch.setenv("CORTEX_RETIRED", "false")
    from outputs.dashboard import _cortex_gate_fire_cycle

    fake = MagicMock(cycle_id="bg-1", status="tier_b_pending", cost_dollars=4.0)
    with patch(
        "outputs.dashboard.maybe_run_cycle",
        new=AsyncMock(return_value=fake),
    ) as m:
        await _cortex_gate_fire_cycle("oskolkov", 999)
    m.assert_awaited_once()


# ---------------------------------------------------------------------------
# Stuck-cycle sentinel registration gated on retirement (structural AST walk)
# ---------------------------------------------------------------------------

def _retired_if_node() -> ast.If:
    """Return the `if _cortex_retired:` node from _register_jobs source."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "_cortex_retired"
        ):
            return node
    raise AssertionError("No `if _cortex_retired:` gate found in _register_jobs")


def _has_sentinel_add_job(nodes) -> bool:
    """True if any statement is scheduler.add_job(..., id='cortex_stuck_cycle_sentinel')."""
    for stmt in nodes:
        for call in ast.walk(stmt):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                    and call.func.attr == "add_job":
                for kw in call.keywords:
                    if (
                        kw.arg == "id"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "cortex_stuck_cycle_sentinel"
                    ):
                        return True
    return False


def _has_sentinel_register_expected(nodes) -> bool:
    """True if any statement is register_expected_job('cortex_stuck_cycle_sentinel', ...)."""
    for stmt in nodes:
        for call in ast.walk(stmt):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "register_expected_job" and call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and first.value == "cortex_stuck_cycle_sentinel":
                    return True
    return False


def test_sentinel_not_registered_when_retired():
    """AC 3: when retired (the `if _cortex_retired:` body), the stuck-cycle sentinel
    is NOT registered — neither add_job nor register_expected_job runs. The
    registration lives only in the retired-false (elif) branch, so the
    expected-job watchdog will not flag a missing job while retired.
    """
    if_node = _retired_if_node()

    # if-body (retired=True path): sentinel NOT registered.
    assert not _has_sentinel_add_job(if_node.body), (
        "cortex_stuck_cycle_sentinel add_job must NOT run when CORTEX_RETIRED"
    )
    assert not _has_sentinel_register_expected(if_node.body), (
        "register_expected_job('cortex_stuck_cycle_sentinel') must NOT run when retired"
    )

    # orelse (retired=False path, the elif chain): sentinel registration IS reachable.
    assert _has_sentinel_add_job(if_node.orelse), (
        "cortex_stuck_cycle_sentinel add_job must remain in the not-retired branch"
    )
    assert _has_sentinel_register_expected(if_node.orelse), (
        "register_expected_job('cortex_stuck_cycle_sentinel') must remain in the not-retired branch"
    )


def test_sentinel_retirement_skip_logged():
    """The retired branch logs the skip (observability)."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    assert "CORTEX_RETIRED — cycle service retired" in src
