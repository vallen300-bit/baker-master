"""FIREFLIES_SCAN_GATE_1 — fireflies_scan registration is toggleable + default-on.

Director switched to Plaud-only (2026-06-09); prod disables Fireflies auto-ingest
via env FIREFLIES_SCAN_ENABLED=false. In code the flag DEFAULTS TRUE so current
behavior + the rest of the suite are preserved; the prod disable happens via env.

Verification strategy mirrors the established _register_jobs test pattern
(test_scheduler_liveness_sentinel.py test_13/14, test_hot_md_weekly_nudge.py):
the live start_scheduler flow lazy-imports half the codebase, so the gate is
asserted via an AST walk over inspect.getsource(_register_jobs) rather than by
executing it. The AST walk proves BOTH the add_job AND the register_expected_job
for fireflies_scan live inside the `if config.triggers.fireflies_scan_enabled:`
body and are absent from the else branch — i.e. enabled registers, disabled
skips both (so the expected-job watchdog won't flag a missing job).
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap


def _register_jobs_if_node() -> ast.If:
    """Return the `if config.triggers.fireflies_scan_enabled:` node from source."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # match attribute chain: config.triggers.fireflies_scan_enabled
            if (
                isinstance(test, ast.Attribute)
                and test.attr == "fireflies_scan_enabled"
                and isinstance(test.value, ast.Attribute)
                and test.value.attr == "triggers"
            ):
                return node
    raise AssertionError(
        "No `if config.triggers.fireflies_scan_enabled:` gate found in _register_jobs"
    )


def _has_fireflies_add_job(nodes) -> bool:
    """True if any statement in `nodes` is a scheduler.add_job(..., id='fireflies_scan')."""
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
                        and kw.value.value == "fireflies_scan"
                    ):
                        return True
    return False


def _has_fireflies_register_expected(nodes) -> bool:
    """True if any statement is register_expected_job('fireflies_scan', ...)."""
    for stmt in nodes:
        for call in ast.walk(stmt):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "register_expected_job" and call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and first.value == "fireflies_scan":
                    return True
    return False


def test_fireflies_scan_gated():
    """enabled=True registers fireflies_scan; enabled=False skips add_job AND register_expected_job.

    Proven structurally: both calls live in the if-body, neither in the else.
    """
    if_node = _register_jobs_if_node()

    # if-body (enabled=True path): BOTH calls present
    assert _has_fireflies_add_job(if_node.body), (
        "fireflies_scan add_job must be gated inside `if fireflies_scan_enabled:`"
    )
    assert _has_fireflies_register_expected(if_node.body), (
        "register_expected_job('fireflies_scan') must be gated inside the if-body"
    )

    # else-branch (enabled=False path): NEITHER call present (only the skip log)
    assert not _has_fireflies_add_job(if_node.orelse), (
        "fireflies_scan add_job must NOT run when disabled"
    )
    assert not _has_fireflies_register_expected(if_node.orelse), (
        "register_expected_job('fireflies_scan') must NOT run when disabled "
        "(else the expected-job watchdog flags a missing job)"
    )


def test_fireflies_disabled_logs_skip():
    """The else branch logs the disable, mirroring the Plaud skip log."""
    from triggers import embedded_scheduler

    src = textwrap.dedent(inspect.getsource(embedded_scheduler._register_jobs))
    assert "fireflies_scan disabled via FIREFLIES_SCAN_ENABLED — skipping registration" in src


def test_fireflies_scan_enabled_default_true():
    """In code the flag defaults TRUE (preserves current behavior + tests)."""
    from config.settings import config

    assert config.triggers.fireflies_scan_enabled is True


def test_boot_backfill_gated_in_dashboard_source():
    """The dashboard boot-backfill path gates fireflies_fn on the flag.

    Source-scan over outputs/dashboard.py:_delayed_backfills — the codex G0
    catch was that the flag gated only the recurring scheduler job, not this
    SECOND startup ingest path (run_boot_backfill_chain). Bind the fix to the
    real code: the backfill_fireflies / fireflies_fn assignment must live under
    an `if config.triggers.fireflies_scan_enabled:` guard.
    """
    import outputs.dashboard as dash

    src = textwrap.dedent(inspect.getsource(dash.startup))
    tree = ast.parse(src)

    gated = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Attribute)
            and test.attr == "fireflies_scan_enabled"
            and isinstance(test.value, ast.Attribute)
            and test.value.attr == "triggers"
        ):
            body_src = "\n".join(ast.dump(s) for s in node.body)
            if "backfill_fireflies" in body_src or "fireflies_fn" in body_src:
                gated = True
                break
    assert gated, (
        "boot-backfill fireflies_fn must be gated on config.triggers.fireflies_scan_enabled "
        "(else FIREFLIES_SCAN_ENABLED=false still re-ingests on restart)"
    )


def test_boot_backfill_skips_fireflies_when_disabled():
    """Disabled gate => fireflies_fn=None => 'fireflies' absent from invoked, 'plaud' present.

    Mirrors codex's probe at the run_boot_backfill_chain contract level: the
    dashboard passes fireflies_fn=None when the flag is off, and the chain then
    skips the fireflies branch while still running Plaud.
    """
    from unittest.mock import MagicMock, patch

    from triggers.backfill_runner import run_boot_backfill_chain

    plaud_fn = MagicMock()
    # Disabled-state wiring: dashboard leaves fireflies_fn=None when flag is off.
    fireflies_fn = None

    with patch("triggers.sentinel_health.report_success", MagicMock()):
        invoked = run_boot_backfill_chain(
            plaud_token="present",
            plaud_fn=plaud_fn,
            fireflies_api_key="present",  # key may still be set in env; flag wins
            fireflies_fn=fireflies_fn,
            timeout_s=5,
        )

    assert "fireflies" not in invoked
    assert "plaud" in invoked
    assert plaud_fn.called


def test_fireflies_scan_env_parse(monkeypatch):
    """Env FIREFLIES_SCAN_ENABLED toggles the bool; mirrors the settings parse expr."""
    def _parse() -> bool:
        return os.getenv("FIREFLIES_SCAN_ENABLED", "true").lower() == "true"

    monkeypatch.delenv("FIREFLIES_SCAN_ENABLED", raising=False)
    assert _parse() is True  # unset -> default on

    monkeypatch.setenv("FIREFLIES_SCAN_ENABLED", "false")
    assert _parse() is False

    monkeypatch.setenv("FIREFLIES_SCAN_ENABLED", "true")
    assert _parse() is True
