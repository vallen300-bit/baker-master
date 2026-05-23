"""BACKFILL_SCRIPT_ENV_PREFLIGHT_1 — env pre-flight tests.

Covers AC6:
  T1. All required envs missing → exit 2, error names every missing var.
  T2. Only VOYAGE_API_KEY missing → exit 2, error lists VOYAGE_API_KEY only.
  T3. DATABASE_URL set + POSTGRES_* cleared → check passes (DATABASE_URL fallback).
  T4. All envs present → check passes silently.

Identical tests run against both backfill scripts to enforce the AC5 parity
contract (same preflight function, same behavior).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Make repo + scripts/ importable
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))


_PREFLIGHT_VARS = (
    "VOYAGE_API_KEY",
    "DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
)

_SCRIPT_MODULES = (
    "backfill_meeting_transcripts_matter_slug",
    "backfill_matter_slug",
)


@pytest.fixture(params=_SCRIPT_MODULES)
def preflight(request, monkeypatch):
    """Yield the _check_required_env callable for each script under test."""
    for var in _PREFLIGHT_VARS:
        monkeypatch.delenv(var, raising=False)
    module = importlib.import_module(request.param)
    return module._check_required_env


def test_all_envs_missing_exits_two_and_lists_each(preflight, capsys):
    """T1 — every required var missing → exit 2 + each name in single error."""
    with pytest.raises(SystemExit) as exc_info:
        preflight()
    assert exc_info.value.code == 2

    err = capsys.readouterr().err
    assert err.startswith("ERROR: missing required environment variables:")
    for var in ("VOYAGE_API_KEY", "POSTGRES_HOST", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert f"- {var}" in err
    # One consolidated report, not one error per var.
    assert err.count("ERROR: missing required environment variables:") == 1


def test_only_voyage_missing_exits_two_and_lists_only_voyage(
    preflight, monkeypatch, capsys,
):
    """T2 — POSTGRES_* present, VOYAGE missing → only VOYAGE listed."""
    monkeypatch.setenv("POSTGRES_HOST", "h")
    monkeypatch.setenv("POSTGRES_DB", "d")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")

    with pytest.raises(SystemExit) as exc_info:
        preflight()
    assert exc_info.value.code == 2

    err = capsys.readouterr().err
    assert "- VOYAGE_API_KEY" in err
    for var in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert f"- {var}" not in err


def test_database_url_satisfies_postgres_split(preflight, monkeypatch, capsys):
    """T3 — DATABASE_URL present + POSTGRES_* cleared → check passes."""
    monkeypatch.setenv("VOYAGE_API_KEY", "vk")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    # POSTGRES_* stay unset (cleared in fixture).
    preflight()  # No SystemExit, no stderr output.
    assert capsys.readouterr().err == ""


def test_all_envs_present_no_error(preflight, monkeypatch, capsys):
    """T4 — every env set → check passes silently."""
    monkeypatch.setenv("VOYAGE_API_KEY", "vk")
    monkeypatch.setenv("POSTGRES_HOST", "h")
    monkeypatch.setenv("POSTGRES_DB", "d")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")

    preflight()
    assert capsys.readouterr().err == ""
