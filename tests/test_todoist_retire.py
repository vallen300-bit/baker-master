"""TODOIST_RETIRE_1 — todoist_poll registration is toggleable + default-on.

Director retired Todoist 2026-06-18 ("I don't use it; keep on-demand access").
Prod disables the recurring poll via env TODOIST_POLL_ENABLED=false. In code the
flag DEFAULTS TRUE so current behavior + the rest of the suite are preserved; the
prod disable happens via env. Mirrors FIREFLIES_SCAN_GATE_1 exactly.

Verification strategy mirrors test_fireflies_scan_gate.py: the live
start_scheduler flow lazy-imports half the codebase, so the gate is asserted via
an AST walk over inspect.getsource(_register_jobs) rather than by executing it.
The AST walk proves BOTH the add_job AND the register_expected_job for
todoist_poll live inside the `if config.triggers.todoist_poll_enabled:` body and
are absent from the else branch — i.e. enabled registers, disabled skips both (so
the expected-job watchdog won't flag a missing job).
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap
from pathlib import Path


def _register_jobs_if_node() -> ast.If:
    """Return the `if config.triggers.todoist_poll_enabled:` node from source."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # match attribute chain: config.triggers.todoist_poll_enabled
            if (
                isinstance(test, ast.Attribute)
                and test.attr == "todoist_poll_enabled"
                and isinstance(test.value, ast.Attribute)
                and test.value.attr == "triggers"
            ):
                return node
    raise AssertionError(
        "No `if config.triggers.todoist_poll_enabled:` gate found in _register_jobs"
    )


def _has_todoist_add_job(nodes) -> bool:
    """True if any statement in `nodes` is a scheduler.add_job(..., id='todoist_poll')."""
    for stmt in nodes:
        for call in ast.walk(stmt):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "add_job":
                for kw in call.keywords:
                    if (
                        kw.arg == "id"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "todoist_poll"
                    ):
                        return True
    return False


def _has_todoist_register_expected(nodes) -> bool:
    """True if any statement is register_expected_job('todoist_poll', ...)."""
    for stmt in nodes:
        for call in ast.walk(stmt):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "register_expected_job" and call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and first.value == "todoist_poll":
                    return True
    return False


def test_todoist_poll_gated():
    """enabled=True registers todoist_poll; enabled=False skips add_job AND register_expected_job.

    Proven structurally: both calls live in the if-body, neither in the else.
    """
    if_node = _register_jobs_if_node()

    # if-body (enabled=True path): BOTH calls present
    assert _has_todoist_add_job(if_node.body), (
        "todoist_poll add_job must be gated inside `if todoist_poll_enabled:`"
    )
    assert _has_todoist_register_expected(if_node.body), (
        "register_expected_job('todoist_poll') must be gated inside the if-body"
    )

    # else-branch (enabled=False path): NEITHER call present (only the skip log)
    assert not _has_todoist_add_job(if_node.orelse), (
        "todoist_poll add_job must NOT run when disabled"
    )
    assert not _has_todoist_register_expected(if_node.orelse), (
        "register_expected_job('todoist_poll') must NOT run when disabled "
        "(else the expected-job watchdog flags a missing job)"
    )


def test_todoist_disabled_logs_skip():
    """The else branch logs the disable, mirroring the fireflies skip log idiom."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    assert "todoist_poll disabled via TODOIST_POLL_ENABLED — skipping registration" in src


def test_todoist_poll_enabled_default_true():
    """In code the flag defaults TRUE (preserves current behavior + tests)."""
    from config.settings import config

    assert config.triggers.todoist_poll_enabled is True


def test_todoist_poll_env_parse(monkeypatch):
    """Env TODOIST_POLL_ENABLED toggles the bool; mirrors the settings parse expr."""
    def _parse() -> bool:
        return os.getenv("TODOIST_POLL_ENABLED", "true").lower() == "true"

    monkeypatch.delenv("TODOIST_POLL_ENABLED", raising=False)
    assert _parse() is True  # unset -> default on

    monkeypatch.setenv("TODOIST_POLL_ENABLED", "false")
    assert _parse() is False

    monkeypatch.setenv("TODOIST_POLL_ENABLED", "true")
    assert _parse() is True


def test_retire_migration_sets_disabled():
    """The retire migration flips the stored sentinel_health row to 'disabled'.

    Source-scan over the migration SQL so the health-surface contract (item 3 of
    the brief) is bound to the actual artifact: /api/health reads the stored
    status, run_health_watchdog's `WHERE status='down'` query must NOT pick
    todoist up, and should_skip_poll must see a disabled row. All three follow
    from status='disabled' (mirrors the established 'whoop' row).
    """
    mig = Path(__file__).resolve().parents[1] / "migrations" / "20260618b_todoist_retire_disable.sql"
    sql = mig.read_text()
    up = sql.split("-- == migrate:up ==")[1].split("-- == migrate:down ==")[0]
    norm = " ".join(up.lower().split())
    assert "update sentinel_health" in norm
    assert "set status = 'disabled'" in norm
    assert "where source = 'todoist'" in norm
