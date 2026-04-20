"""Tests for ``kbl.db._build_dsn`` — DATABASE_URL vs POSTGRES_* fallback.

Covers lesson #36 (env-convention drift between Render and Mac Mini).
"""

from __future__ import annotations

import os
import urllib.parse

import pytest

from kbl.db import _build_dsn


_POSTGRES_KEYS = (
    "DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every DATABASE_URL / POSTGRES_* key so each test starts clean."""
    for key in _POSTGRES_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_database_url_wins_when_both_are_set(clean_env):
    """If DATABASE_URL is set, it is returned even when split vars are also set."""
    clean_env.setenv("DATABASE_URL", "postgresql://url-wins@host/db")
    clean_env.setenv("POSTGRES_HOST", "split-host")
    clean_env.setenv("POSTGRES_USER", "split-user")
    clean_env.setenv("POSTGRES_PASSWORD", "split-pw")
    clean_env.setenv("POSTGRES_DB", "split-db")

    assert _build_dsn() == "postgresql://url-wins@host/db"


def test_split_form_builds_expected_url(clean_env):
    """POSTGRES_* fallback composes a URL with URL-quoted password."""
    clean_env.setenv("POSTGRES_HOST", "neon.example")
    clean_env.setenv("POSTGRES_USER", "baker")
    # Password with @ / : / # — all chars psycopg2 refuses in a raw URL.
    clean_env.setenv("POSTGRES_PASSWORD", "p@ss:w#rd")
    clean_env.setenv("POSTGRES_DB", "kbl")
    clean_env.setenv("POSTGRES_PORT", "5433")

    dsn = _build_dsn()

    expected_pw = urllib.parse.quote_plus("p@ss:w#rd")
    assert dsn == f"postgresql://baker:{expected_pw}@neon.example:5433/kbl"
    # Sanity: the raw password MUST NOT appear unquoted (would break psycopg2).
    assert "p@ss:w#rd" not in dsn


def test_missing_split_var_raises_clear_error(clean_env):
    """When neither DATABASE_URL nor a complete split form is set, error lists missing keys."""
    clean_env.setenv("POSTGRES_HOST", "neon.example")
    clean_env.setenv("POSTGRES_USER", "baker")
    # POSTGRES_PASSWORD + POSTGRES_DB intentionally missing.

    with pytest.raises(RuntimeError) as exc:
        _build_dsn()

    msg = str(exc.value)
    assert "DATABASE_URL" in msg
    assert "POSTGRES_PASSWORD" in msg
    assert "POSTGRES_DB" in msg


def test_default_port_when_not_set(clean_env):
    """POSTGRES_PORT defaults to 5432."""
    clean_env.setenv("POSTGRES_HOST", "h")
    clean_env.setenv("POSTGRES_USER", "u")
    clean_env.setenv("POSTGRES_PASSWORD", "p")
    clean_env.setenv("POSTGRES_DB", "d")

    assert _build_dsn() == "postgresql://u:p@h:5432/d"
